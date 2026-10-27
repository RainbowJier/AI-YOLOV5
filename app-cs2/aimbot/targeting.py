"""Target selection and mouse movement (v2: modular, smooth-optimized).

Movement algorithm (unchanged logic, restructured for clarity):
- EMA-tracked box center absorbs detector jitter
- dual velocity: frame-relative (lag compensation) + world (feed-forward)
- error closure: time-normalized exponential (same feel at 60/144 CPS)
- soft-capped by tanh to prevent teleport
- deadband + lead fade reduce jitter near lock
- sticky target selection prevents body/head flicker
"""

import time
from math import exp, tanh

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

# Movement constants (from config where available)
_FIRING_GAIN = 3.0 / 2.6
_VEL_TAU = getattr(config, 'velocity_tau', 0.060)
_VEL_CLAMP = 2500.0
_JUMP_RESET = 40.0
_STALE_DT = 0.25
_LEAD_FADE_R = getattr(config, 'lead_fade_radius', 12.0)
_DEADBAND = getattr(config, 'deadband_px', 2.5)
_STICK_R2 = 25.0 ** 2

# Tracking state
_sx = _sy = _sh = None
_rx = _ry = 0.0
_wx = _wy = 0.0
_mx = _my = 0.0
_last_t = None
_strikes = 0

# Target selection state
_stick_x = _stick_y = None
_announced = False


def _update_track_state(x, y, h, dt):
    """Update EMA-smoothed position and dual velocity."""
    global _sx, _sy, _sh, _rx, _ry, _wx, _wy, _mx, _my, _strikes, _last_t

    if _last_t is None:
        return True, x, y, h, 0.0, 0.0, 0.0, 0.0

    # Predict position (one EMA lag ahead)
    px = _sx + _rx * config.track_tau
    py = _sy + _ry * config.track_tau

    # Detect jump
    jump_dist_sq = (x - px) ** 2 + (y - py) ** 2
    if jump_dist_sq > _JUMP_RESET ** 2:
        _strikes += 1
    else:
        _strikes = 0

    # Re-acquire on stale or persistent jump
    if dt > _STALE_DT or _strikes >= 2:
        return True, x, y, h, 0.0, 0.0, 0.0, 0.0

    # EMA smooth box
    tau = config.track_tau
    ema_alpha = 1.0 if tau <= 0 else 1.0 - exp(-dt / tau)
    nx = _sx + ema_alpha * (x - _sx)
    ny = _sy + ema_alpha * (y - _sy)
    nh = _sh + ema_alpha * (h - _sh)

    # Update velocities (both EMA-smoothed)
    vel_alpha = 1.0 - exp(-dt / _VEL_TAU)

    # Frame-relative velocity
    dox = nx - _sx
    doy = ny - _sy
    obs_vx = dox / dt if dt > 0 else 0.0
    obs_vy = doy / dt if dt > 0 else 0.0

    rx = _rx + vel_alpha * (obs_vx - _rx)
    ry = _ry + vel_alpha * (obs_vy - _ry)

    # World-frame velocity (observed + our move)
    world_dx = dox + _mx
    world_dy = doy + _my
    world_vx = world_dx / dt if dt > 0 else 0.0
    world_vy = world_dy / dt if dt > 0 else 0.0

    wx = _wx + vel_alpha * (world_vx - _wx)
    wy = _wy + vel_alpha * (world_vy - _wy)

    # Clamp velocities
    rx = np.clip(rx, -_VEL_CLAMP, _VEL_CLAMP)
    ry = np.clip(ry, -_VEL_CLAMP, _VEL_CLAMP)
    wx = np.clip(wx, -_VEL_CLAMP, _VEL_CLAMP)
    wy = np.clip(wy, -_VEL_CLAMP, _VEL_CLAMP)

    return False, nx, ny, nh, rx, ry, wx, wy


def _compute_aim_point(bx, by, bh, cx, cy, firing):
    """Compute aim point with lead and lock_y."""
    # Lead fade with proximity
    ex = bx - cx
    ey = by - cy
    dist_sq = ex * ex + ey * ey
    dist = dist_sq ** 0.5 if dist_sq > 0 else 0.0
    fade = min(1.0, dist / _LEAD_FADE_R)

    # Lead point
    ax = bx + _rx * config.track_tau * fade
    ay = by + _ry * config.track_tau * fade

    # Apply lock_y
    if not firing:
        ay -= bh * (0.5 - config.lock_y)

    return ax, ay


def _compute_move(aim_x, aim_y, center_x, center_y, speed, dt, firing):
    """Compute mouse move with soft cap."""
    # Error fraction
    rate = config.move_rate * speed * (_FIRING_GAIN if firing else 1.0)
    frac = 1.0 - exp(-rate * dt) if dt > 0 else 0.0

    # Soft cap
    cap = config.max_move_speed * dt

    # Chase vector with deadband
    chase_x = aim_x - center_x
    chase_y = aim_y - center_y
    chase_dist_sq = chase_x * chase_x + chase_y * chase_y
    chase_dist = chase_dist_sq ** 0.5 if chase_dist_sq > 0 else 0.0

    deadband_scale = max(0.0, chase_dist - _DEADBAND) / chase_dist if chase_dist > 0.0 else 0.0

    # Blend: error fraction + world-velocity feed-forward
    ax = frac * chase_x * deadband_scale + _wx * dt
    ay = frac * chase_y * deadband_scale + _wy * dt

    # Soft cap with tanh
    mx = cap * tanh(ax / cap) if cap > 0 else 0.0
    my = cap * tanh(ay / cap) if cap > 0 else 0.0

    return mx, my


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
    """Pick the best box, sticky to prevent flicker."""
    global _stick_x, _stick_y

    cx = (rows[:, 0] + rows[:, 2]) * 0.5
    cy = (rows[:, 1] + rows[:, 3]) * 0.5

    if _stick_x is not None:
        d = (cx - _stick_x) ** 2 + (cy - _stick_y) ** 2
        i = int(d.argmin())
        if d[i] <= _STICK_R2:
            _stick_x, _stick_y = cx[i], cy[i]
            return (cx[i], cy[i], rows[i, 2] - rows[i, 0], rows[i, 3] - rows[i, 1])

    if rows.shape[0] == 1 or not config.centerOfScreen:
        i = 0
    else:
        d = (cx - center[0]) ** 2 + (cy - center[1]) ** 2
        near = np.where(d <= d.min() * 2.25)[0]
        area = (rows[:, 2] - rows[:, 0]) * (rows[:, 3] - rows[:, 1])
        i = int(near[int(area[near].argmax())])

    _stick_x, _stick_y = cx[i], cy[i]
    return (cx[i], cy[i], rows[i, 2] - rows[i, 0], rows[i, 3] - rows[i, 1])


def aim_at(box, center, mouse, speed):
    """Main tracking loop."""
    global _sx, _sy, _sh, _rx, _ry, _wx, _wy, _mx, _my, _last_t, _announced, _strikes

    # Gate: Caps Lock
    if not win32api.GetKeyState(_CAPS):
        if _last_t is not None:
            _sx = _last_t = None
            _stick_x = _stick_y = None
            _strikes = 0
        return

    x, y, w, h = box
    cx, cy = center

    now = time.perf_counter()
    if _last_t is None:
        dt = 1.0 / 60.0
    else:
        dt = max(now - _last_t, 0.001)

    # Update tracking
    reacquired, nx, ny, nh, rx, ry, wx, wy = _update_track_state(x, y, h, dt)
    if reacquired:
        _sx, _sy, _sh = x, y, h
        _rx = _ry = _wx = _wy = 0.0
        _mx = _my = 0.0
    else:
        _sx, _sy, _sh = nx, ny, nh
        _rx, _ry = rx, ry
        _wx, _wy = wx, wy

    _last_t = now

    # Range gate
    if (_sx - cx) ** 2 + (_sy - cy) ** 2 > _AIM_RANGE_SQ:
        _mx = _my = 0.0
        return

    firing = win32api.GetKeyState(win32con.VK_LBUTTON) < 0

    # Aim and move
    ax, ay = _compute_aim_point(_sx, _sy, _sh, cx, cy, firing)
    mx, my = _compute_move(ax, ay, cx, cy, speed, dt, firing)

    _mx, _my = mx, my

    if not _announced:
        _announced = True
        print('[aim] tracking: v=({:.0f},{:.0f}) px/s  step=({:.1f},{:.1f}) px  '
              'rate={:.0f}/s'.format(_wx, _wy, mx, my, config.move_rate * speed))

    mouse.move(mx * _INV_SEN, my * _INV_SEN)
