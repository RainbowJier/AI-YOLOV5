"""Target selection and mouse movement (简单版：反正切阻尼).

移动核心回到原版的单步比例算法：误差经过 atan 阻尼后一步输出，
没有 EMA、引导、死区或弹簧——每帧完全无状态，感觉不对直接调
lock_smooth / lock_sen。选目标保留粘滞 + 滞回（防止头/身框来回跳）。

    move = -(speed / lock_smooth / lock_sen) * atan(d / W) * W

开火（按住左键）时瞄点落到框中心并加速 3.0/2.6×，与原版一致。

三角洲版：类别 0=身体 1=头，无阵营，过滤只看部位。
"""

import sys
from math import atan, hypot

import numpy as np
import win32api
import win32con

import config


def apply_class_filter():
    """Recompute the class filter from config: part only (body/head),
    0=身体 1=头. 三角洲模型没有阵营概念，敌我一视同仁。

    Called at import and from the tuner when a switch flips -- the aim
    loop reads CLASS_IDS/_ALL_CLASSES live, and any loaded backend that
    bound CLASS_IDS at import (tensorrt passes it to nms) gets the fresh
    list pushed in, exactly like refresh() does for confidence.
    """
    global _IDS, CLASS_IDS, _ALL_CLASSES
    body = bool(getattr(config, 'aim_body', True))
    head = bool(getattr(config, 'aim_head', True))
    _IDS = [c for c in (0, 1) if (c == 0 and body) or (c == 1 and head)]
    CLASS_IDS = _IDS
    _ALL_CLASSES = len(CLASS_IDS) == 2
    for name in ('tensorrt_backend', 'onnx_backend', 'torch_backend'):
        module = sys.modules.get('aimbot.backends.' + name)
        if module is not None and hasattr(module, 'CLASS_IDS'):
            module.CLASS_IDS = CLASS_IDS
    return CLASS_IDS


_IDS = []
CLASS_IDS = []
_ALL_CLASSES = False
apply_class_filter()


def class_label(cls_id):
    return 'Head' if cls_id == 1 else 'Body'


# Config-derived
_INV_SMOOTH = 1.0 / config.lock_smooth
_INV_SEN = 1.0 / config.lock_sen
_AIM_RANGE_SQ = config.aim_range * config.aim_range
_FALLOFF = getattr(config, 'aim_falloff', 0)   # px; 0 = uniform strength
_WIDTH = float(config.screenShotWidth)
_HEIGHT = float(config.screenShotHeight)
_FIRING_SPEED = 3.0 / 2.6
_CAPS = 0x14
_STICK_R2 = 40.0 ** 2     # px^2; same-target match radius between frames
_HYST = 0.35              # keep current target unless rival is 35% closer

# Target selection state
_stick_x = _stick_y = None


def pick(det):
    """NMS result, part-filtered."""
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
    """No detection this frame. The mover is stateless per frame; nothing
    to decay -- the sticky pick just starts fresh on the next target."""


def aim_at(box, center, mouse, speed):
    """Move toward the lock point while Caps Lock is on and the box is in
    range (原版算法). Left button held: aim at the box centre, move faster.
    """
    global _stick_x, _stick_y

    if not win32api.GetKeyState(_CAPS):
        _stick_x = _stick_y = None
        return
    x, y, w, h = box
    cx, cy = center
    dx, dy = cx - x, cy - y
    if dx * dx + dy * dy > _AIM_RANGE_SQ:
        return
    if _FALLOFF > 0:
        # 吸附范围：强度随距离线性衰减，到边界为 0（之外不瞄）。
        # Aim falloff: strength ramps down linearly with distance.
        dist = hypot(dx, dy)
        if dist >= _FALLOFF:
            return
        speed *= 1.0 - dist / _FALLOFF
    firing = win32api.GetKeyState(win32con.VK_LBUTTON) < 0
    if firing and not config.aim_while_firing:
        return
    if firing:
        speed *= _FIRING_SPEED
    else:
        dy = cy - (y - h * (0.5 - config.lock_y))
    mouse.move(*_smooth(dx, dy, speed))


def _smooth(dist_x, dist_y, speed):
    """Arctan damping. Lower speed, slower move. Returns mouse deltas."""
    k = speed * _INV_SMOOTH * _INV_SEN
    return (-k * atan(dist_x / _WIDTH) * _WIDTH,
            -k * atan(dist_y / _HEIGHT) * _WIDTH)
