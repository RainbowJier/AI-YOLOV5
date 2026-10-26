"""Target selection and mouse movement.

The NMS result is at most a handful of boxes, so it crosses to the host
once and every decision after that -- team filter, closest box -- runs in
numpy. The old path kept the filter and the argmin on the device, which
cost a per-frame class-id upload plus two implicit syncs to save a
comparison over two rows.
"""

from math import atan

import numpy as np
import win32api
import win32con

import config

# 0 = CT body, 1 = CT head, 2 = T body, 3 = T head. config.CT / config.T pick
# the team; both on (or both off) means every class competes.
_IDS = ([0, 1] if config.CT else []) + ([2, 3] if config.T else [])
CLASS_IDS = _IDS or [0, 1, 2, 3]
_ALL_CLASSES = len(CLASS_IDS) == 4

_INV_SMOOTH = 1.0 / config.lock_smooth
_INV_SEN = 1.0 / config.lock_sen
_AIM_RANGE_SQ = config.aim_range * config.aim_range
_WIDTH = float(config.screenShotWidth)
_HEIGHT = float(config.screenShotHeight)
_FIRING_SPEED = 3.0 / 2.6
_CAPS = 0x14


def pick(det):
    """The whole (n, 6) NMS result as a host array, team-filtered, or None.

    Single transfer: det crosses to the host once, and the returned rows
    feed both the aim and the visuals without touching the device again.
    """
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
    """Closest surviving box to the crosshair, as (x, y, w, h).

    With centerOfScreen off it is simply the first (top-score) row.
    """
    if rows.shape[0] == 1 or not config.centerOfScreen:
        x1, y1, x2, y2 = rows[0, :4]
    else:
        cx = (rows[:, 0] + rows[:, 2]) * 0.5
        cy = (rows[:, 1] + rows[:, 3]) * 0.5
        d = (cx - center[0]) ** 2 + (cy - center[1]) ** 2
        x1, y1, x2, y2 = rows[int(d.argmin()), :4]
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5, x2 - x1, y2 - y1


def aim_at(box, center, mouse, headshot_fraction, speed):
    """Move toward the head point while Caps Lock is on and the box is in range.

    Left button held: the point drops to the box center and the move speeds
    up, same ratio the TensorRT path used before.
    """
    if not win32api.GetKeyState(_CAPS):
        return
    x, y, w, h = box[0], box[1], box[2], box[3]
    cx, cy = center
    dx, dy = cx - x, cy - y
    if dx * dx + dy * dy > _AIM_RANGE_SQ:
        return
    if win32api.GetKeyState(win32con.VK_LBUTTON) < 0:
        speed *= _FIRING_SPEED
    else:
        dy = cy - (y - h * headshot_fraction)
    mouse.move(*_smooth(dx, dy, speed))


def _smooth(dist_x, dist_y, speed):
    """Arctan damping. Lower speed, slower move. Returns mouse deltas."""
    k = speed * _INV_SMOOTH * _INV_SEN
    return (-k * atan(dist_x / _WIDTH) * _WIDTH,
            -k * atan(dist_y / _HEIGHT) * _WIDTH)
