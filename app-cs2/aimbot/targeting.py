"""Target selection and mouse movement (v3.1: error-space damped spring).

v2 shook because the world-velocity feed-forward bypassed the deadband:
near lock, detector noise (differentiated, /dt amplified) was re-injected
into the mouse every frame.

v3.0 fixed that with a spring chasing a *simulated* crosshair -- but the
simulation assumed our injected dots move the view by exactly the px we
predicted (open loop). Any sensitivity mismatch (wrong lock_sen, a view
that ignores the input, a dead driver) made the simulated crosshair
reach the target while the real one stood still -> output decayed to
zero -> "the mouse stopped moving".

v3.1 keeps one state variable per axis -- a spring *velocity* driven by
the freshly OBSERVED error each frame. No position is ever integrated:

    v'  = (v - dt * omega^2 * e) / (1 + 2*omega*dt)   critically damped
    e   = observed error, deadband-gated              (0 inside deadband)
    out = v * dt, v soft-capped                        (max_move_speed)

Closed loop by construction: if the view does not respond, the error
never shrinks, v saturates against the cap, and the mouse keeps pushing
-- it can never "believe" it has arrived. A sensitivity mismatch only
changes convergence speed, not correctness.

Anti-shake properties (kept from v3.0):
- box -> EMA (track_tau) absorbs detector jitter
- lead is noise-gated (lead_min_speed): a standing target gets exactly
  zero feed-forward
- deadband hard-zeroes the error -> v decays exponentially to zero, so
  a resting target rests the mouse
- sticky + hysteresis selection stops head/body flip-flop
- aim_while_firing=False: LMB pauses the snap -- the mouse rests while
  firing, the tracker stays warm, aiming resumes on release
"""

import time
from math import exp, hypot, tanh

import numpy as np
import win32api
import win32con

import config


_IDS = ([0, 1] if config.CT else []) + ([2, 3] if config.T else [])
CLASS_IDS = _IDS or [0, 1, 2, 3]
_ALL_CLASSES = len(CLASS_IDS) == 4


def class_label(cls_id):
    return 'Head' if cls_id in (1, 3) else 'Body'


# Config-derived
_INV_SEN = 1.0 / config.lock_sen
_AIM_RANGE_SQ = config.aim_range * config.aim_range
_CAPS = 0x14

# Movement constants
_FIRING_GAIN = 3.0 / 2.6
_VEL_TAU = getattr(config, 'velocity_tau', 0.060)
_VEL_CLAMP = 2500.0
_STALE_DT = 0.25          # s without a detection -> full re-acquire
_JUMP_BASE = 30.0         # px margin for the jump test at zero speed
_JUMPS_TO_RESET = 2       # consecutive off-prediction frames -> re-acquire
_LEAD_FADE_R = getattr(config, 'lead_fade_radius', 12.0)
_LEAD_MIN = getattr(config, 'lead_min_speed', 30.0)   # px/s noise gate
_DEADBAND = getattr(config, 'deadband_px', 2.5)
_STICK_R2 = 40.0 ** 2     # px^2; same-target match radius between frames
_HYST = 0.35              # keep current target unless rival is 35% closer
_MIN_RATE = 3.3           # 1/s; floor on the spring stiffness

# Tracking state (box)
_sx = _sy = _sh = None    # EMA-smoothed box center + height
_wx = _wy = 0.0           # world-frame velocity (px/s)
_mx = _my = 0.0           # last injected move (world reconstruction)
_last_t = None
_strikes = 0

# Spring state: one velocity per axis, in ERROR space. No position state
# exists -- the error is re-observed every frame, so the loop closes on
# reality, not on a simulation of it.
_svx = _svy = 0.0

# Target selection state
_stick_x = _stick_y = None
_announced = False


def _reset_spring():
    global _svx, _svy
    _svx = _svy = 0.0


def _lead_gate(speed):
    """0 below _LEAD_MIN, 1 above 3x -- smoothstep in between.

    A stationary target's velocity estimate is pure noise (~15 px/s);
    gating the lead on it removes the last feed-forward shake path.
    """
    t = (speed - _LEAD_MIN) / (2.0 * _LEAD_MIN)
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * (3.0 - 2.0 * t)


def _update_track(x, y, h, dt):
    """EMA the box, estimate world velocity, detect re-acquisition."""
    global _sx, _sy, _sh, _wx, _wy, _strikes

    if _sx is None or _last_t is None or dt > _STALE_DT:
        return True, x, y, h, 0.0, 0.0

    # Predict where the EMA box should be, then test the observation
    # against a speed-aware margin so real strafing never reads as a jump.
    px = _sx + _wx * dt
    py = _sy + _wy * dt
    margin = _JUMP_BASE + 1.5 * hypot(_wx, _wy) * dt
    if (x - px) ** 2 + (y - py) ** 2 > margin * margin:
        _strikes += 1
        if _strikes >= _JUMPS_TO_RESET:
            return True, x, y, h, 0.0, 0.0
    else:
        _strikes = 0

    ema_alpha = 1.0 - exp(-dt / config.track_tau)
    nx = _sx + ema_alpha * (x - _sx)
    ny = _sy + ema_alpha * (y - _sy)
    nh = _sh + ema_alpha * (h - _sh)

    # World velocity: observed delta + our own injected move.
    vel_alpha = 1.0 - exp(-dt / _VEL_TAU)
    obs_vx = ((nx - _sx) + _mx) / dt
    obs_vy = ((ny - _sy) + _my) / dt
    wx = _wx + vel_alpha * (obs_vx - _wx)
    wy = _wy + vel_alpha * (obs_vy - _wy)
    wx = float(np.clip(wx, -_VEL_CLAMP, _VEL_CLAMP))
    wy = float(np.clip(wy, -_VEL_CLAMP, _VEL_CLAMP))

    return False, nx, ny, nh, wx, wy


def _aim_point(bx, by, bh, cx, cy):
    """Lead + lock_y. Lead is noise-gated and fades near the crosshair."""
    dist = hypot(bx - cx, by - cy)
    fade = min(1.0, dist / _LEAD_FADE_R) if _LEAD_FADE_R > 0 else 0.0

    ax = bx + _wx * config.track_tau * _lead_gate(abs(_wx)) * fade
    ay = by + _wy * config.track_tau * _lead_gate(abs(_wy)) * fade
    ay -= bh * (0.5 - config.lock_y)
    return ax, ay


def pick(det):
    """NMS result, team-filtered."""
    if det is None or det.shape[0] == 0:
        return None
    if det.is_cuda:
        det = det.detach().cpu()
    rows = det.numpy()
    if not _ALL_CLASSES:
        rows = rows[np.isin(rows[:, 5], CLASS_IDS)]
        if rows.shape[0] == 0:
            return None
    return rows


def closest(rows, center):
    """Pick the best box: sticky with hysteresis, no head/body flicker."""
    global _stick_x, _stick_y

    if rows.shape[0] == 1:
        # The common duel: one box, no numpy over 1-row arrays needed.
        x1, y1, x2, y2 = rows[0, :4]
        _stick_x = (x1 + x2) * 0.5
        _stick_y = (y1 + y2) * 0.5
        return _stick_x, _stick_y, x2 - x1, y2 - y1

    cx = (rows[:, 0] + rows[:, 2]) * 0.5
    cy = (rows[:, 1] + rows[:, 3]) * 0.5
    n = rows.shape[0]

    # Candidate: nearest to the crosshair (bigger box wins near-ties),
    # or simply the top-score row when center preference is off.
    if n == 1 or not config.centerOfScreen:
        c = 0
    else:
        d = (cx - center[0]) ** 2 + (cy - center[1]) ** 2
        near = np.where(d <= d.min() * 2.25)[0]
        area = (rows[:, 2] - rows[:, 0]) * (rows[:, 3] - rows[:, 1])
        c = int(near[int(area[near].argmax())])

    # Hysteresis: stay on the previous target unless the candidate is
    # meaningfully closer to the crosshair. Kills the flip-flop between
    # an overlapping head box and its body box.
    i = c
    if _stick_x is not None and n > 1:
        ds = (cx - _stick_x) ** 2 + (cy - _stick_y) ** 2
        j = int(ds.argmin())
        if j != c and ds[j] <= _STICK_R2:
            dc = (cx[c] - center[0]) ** 2 + (cy[c] - center[1]) ** 2
            dj = (cx[j] - center[0]) ** 2 + (cy[j] - center[1]) ** 2
            if dj <= dc * (1.0 + _HYST):
                i = j

    _stick_x, _stick_y = cx[i], cy[i]
    return (cx[i], cy[i], rows[i, 2] - rows[i, 0], rows[i, 3] - rows[i, 1])


def target_lost(center):
    """No detection this frame: tracker stays warm; the spring velocity
    self-decays through its damping term on the next active frame."""
    global _mx, _my
    _mx = _my = 0.0


def aim_at(box, center, mouse, speed):
    """Main tracking loop."""
    global _sx, _sy, _sh, _wx, _wy, _mx, _my, _last_t, _announced, _strikes
    global _svx, _svy

    # Gate: Caps Lock
    if not win32api.GetKeyState(_CAPS):
        if _last_t is not None:
            _sx = _sy = _sh = _last_t = None
            _stick_x = _stick_y = None
            _strikes = 0
            _wx = _wy = _mx = _my = 0.0
            _reset_spring()
        return

    x, y, w, h = box
    cx, cy = center

    now = time.perf_counter()
    if _last_t is None:
        dt = 1.0 / 60.0
    else:
        dt = max(now - _last_t, 0.001)

    reacquired, nx, ny, nh, wx, wy = _update_track(x, y, h, dt)
    if reacquired:
        _sx, _sy, _sh = x, y, h
        _wx = _wy = _mx = _my = 0.0
        _strikes = 0
        _reset_spring()
    else:
        _sx, _sy = nx, ny
        _sh = nh
        _wx = wx
        _wy = wy

    _last_t = now

    # 开火加速：按住左键时弹簧刚度提升 3.0/2.6×（与 v2 手感一致），
    # 压枪时锁得更狠。_mx/_my 正常记录，世界速度重构不受影响。
    # Firing: LMB boosts the spring stiffness 3.0/2.6x (v2 feel) --
    # a tighter lock while spraying. World-velocity reconstruction is
    # unaffected (_mx/_my still recorded normally).
    firing = win32api.GetKeyState(win32con.VK_LBUTTON) < 0

    # 开火时不吸附（aim_while_firing=False）：按住左键时鼠标静止，但上面
    # 的跟踪器照常更新，松开后立即接上。_mx/_my 清零，不注入移动。
    # Stop-while-firing (aim_while_firing=False): the mouse rests while LMB
    # is held; the tracker above keeps updating, so aiming resumes at once
    # after release. No moves are injected, so _mx/_my zero out.
    if firing and not config.aim_while_firing:
        _mx = _my = 0.0
        _reset_spring()
        return

    # Range gate
    if (_sx - cx) ** 2 + (_sy - cy) ** 2 > _AIM_RANGE_SQ:
        _mx = _my = 0.0
        _reset_spring()
        return

    ax, ay = _aim_point(_sx, _sy, _sh, cx, cy)

    # Observed error, radial-deadbanded: inside the deadband the error is
    # exactly zero, so the spring velocity decays exponentially to zero
    # and the mouse rests -- no matter what the input noise does.
    ex = ax - cx
    ey = ay - cy
    dist = hypot(ex, ey)
    if dist <= _DEADBAND:
        ex = ey = 0.0
    else:
        scale = (dist - _DEADBAND) / dist
        ex *= scale
        ey *= scale

    # Semi-implicit critically damped spring step (unconditionally stable
    # at any dt). omega = move_rate * speed, boosted while firing.
    # Error convention: e points from crosshair TO aim, so the
    # acceleration term enters with +.
    omega = max(config.move_rate * speed * (_FIRING_GAIN if firing else 1.0), _MIN_RATE)
    damp = 1.0 + 2.0 * omega * dt
    _svx = (_svx + dt * omega * omega * ex) / damp
    _svy = (_svy + dt * omega * omega * ey) / damp

    # Soft cap on the spring velocity; the per-frame step is then bounded
    # by max_move_speed * dt by construction.
    vmax = config.max_move_speed
    _svx = vmax * tanh(_svx / vmax)
    _svy = vmax * tanh(_svy / vmax)

    mx = _svx * dt
    my = _svy * dt
    _mx, _my = mx, my

    if not _announced:
        _announced = True
        print('[aim] tracking: v=({:.0f},{:.0f}) px/s  step=({:.2f},{:.2f}) px  '
              'stiffness={:.1f}/s'.format(_wx, _wy, mx, my, omega))

    mouse.move(mx * _INV_SEN, my * _INV_SEN)
