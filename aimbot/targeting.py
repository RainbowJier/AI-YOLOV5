"""Detection filtering, target selection and mouse movement.

Kept free of pandas: the old pipeline built a DataFrame, computed a
distance column and sorted it every single frame. With max_det of a few
boxes, a plain min() over tuples does the same work with no allocations.
"""

from math import atan

import torch
import win32api
import win32con

from config import (CT, T, aim_range, centerOfScreen, lock_sen, lock_smooth,
                    screenShotHeight, screenShotWidth)

# Model class ids: 0 = CT body, 1 = CT head, 2 = T body, 3 = T head.
_BODY_CLASSES = []
if CT:
    _BODY_CLASSES.append(0)
if T:
    _BODY_CLASSES.append(2)
if not _BODY_CLASSES:  # neither side selected: target both bodies
    _BODY_CLASSES = [0, 2]
BODY_CLASSES = set(_BODY_CLASSES)


def boxes_from_nms(det, image_shape, bodies_only=False):
    """Convert one image's NMS output into (x, y, w, h, conf, cls) tuples.

    xyxy comes in as absolute pixels; the old code divided by a tensor built
    from the image shape, which is all zeros, so the division was a no-op and
    the coordinates stayed in pixels. That is reproduced here on purpose.
    """
    if det is None or len(det) == 0:
        return []
    if bodies_only:
        det = det[torch.isin(det[:, 5], torch.tensor(list(BODY_CLASSES), device=det.device))]
        if len(det) == 0:
            return []
    # xyxy -> xywh in one pass, then a single transfer back to the host.
    xywh = det[:, :4].clone()
    xywh[:, 2:] -= xywh[:, :2]
    xywh[:, :2] += xywh[:, 2:] / 2
    out = torch.cat((xywh, det[:, 4:6]), 1).detach().cpu().tolist()
    return [tuple(row) for row in out]


def select_target(boxes, center):
    """Return the box closest to the crosshair, or None."""
    if not boxes:
        return None
    if not centerOfScreen:
        return boxes[0]
    cx, cy = center

    def dist(b):
        return (b[0] - cx) ** 2 + (b[1] - cy) ** 2

    return min(boxes, key=dist)


def move_smooth(dist_x, dist_y, speed):
    """Arctan-shaped move so large corrections are damped. Lower speed = slower."""
    k = speed * (1.0 / lock_smooth)
    ex_x = k / lock_sen * atan(dist_x / screenShotWidth) * screenShotWidth
    ex_y = k / lock_sen * atan(dist_y / screenShotHeight) * screenShotWidth
    return -ex_x, -ex_y


def aim_at(box, center, mouse, headshot_fraction, speed):
    """Move the mouse toward the target's head point while CAPS_LOCK is held.

    While the left button is down (firing) the aim point drops to the box
    center and the move is faster, matching the old main_tensorrt behavior.
    aim_range gates both cases.
    """
    if not win32api.GetKeyState(0x14):
        return
    x, y, w, h = box[0], box[1], box[2], box[3]
    cx, cy = center
    if (x - cx) ** 2 + (y - cy) ** 2 > aim_range ** 2:
        return
    firing = win32api.GetKeyState(win32con.VK_LBUTTON) < 0
    if firing:
        dx, dy = cx - x, cy - y
        speed = speed * 3.0 / 2.6
    else:
        dx, dy = cx - x, cy - (y - h * headshot_fraction)
    mx, my = move_smooth(dx, dy, speed)
    mouse.move(mx, my)
