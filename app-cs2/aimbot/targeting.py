"""Target selection and mouse movement.

The old path converted every detection to a Python tuple, then scanned
them again for the closest one. Here the closest box is picked on the
tensor and only that one row crosses back to the host.
"""

from math import atan

import torch
import win32api
import win32con

import config

# 0 = CT body, 1 = CT head, 2 = T body, 3 = T head. config.CT / config.T pick
# the team; both on (or both off) means every class competes.
_IDS = ([0, 1] if config.CT else []) + ([2, 3] if config.T else [])
CLASS_IDS = _IDS or [0, 1, 2, 3]

_INV_SMOOTH = 1.0 / config.lock_smooth
_INV_SEN = 1.0 / config.lock_sen
_AIM_RANGE_SQ = config.aim_range * config.aim_range
_WIDTH = float(config.screenShotWidth)
_HEIGHT = float(config.screenShotHeight)
_FIRING_SPEED = 3.0 / 2.6
_CAPS = 0x14


def class_filter(device):
    """Class ids as a column tensor, built once per detector."""
    return torch.tensor(CLASS_IDS, device=device, dtype=torch.float32).view(1, -1)


def pick(det, center, classes=None):
    """Closest box to the crosshair, as (x, y, w, h, conf, cls), or None.

    det is the NMS output, xyxy. classes restricts which rows compete;
    None keeps every class. The closest surviving box to the crosshair
    wins; with centerOfScreen off it is simply the first (top-score) row.
    """
    if det is None or det.shape[0] == 0:
        return None
    if classes is not None:
        det = det[(det[:, 5:6] == classes).any(1)]
        if det.shape[0] == 0:
            return None
    if config.centerOfScreen and det.shape[0] > 1:
        cx = (det[:, 0] + det[:, 2]) * 0.5
        cy = (det[:, 1] + det[:, 3]) * 0.5
        d = (cx - center[0]) ** 2 + (cy - center[1]) ** 2
        det = det[int(d.argmin())]
    else:
        det = det[0]
    row = det.detach()
    if row.is_cuda:
        row = row.cpu()
    x1, y1, x2, y2, conf, cls_id = row.tolist()
    return (x1 + x2) * 0.5, (y1 + y2) * 0.5, x2 - x1, y2 - y1, conf, cls_id


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
