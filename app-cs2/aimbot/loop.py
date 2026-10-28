"""The shared per-frame loop."""

import datetime
import os
import time

import win32api
import win32con

import config
from aimbot.targeting import class_label
from config import aaQuitKey, capture, cpsDisplay, visuals

_QUIT = ord(aaQuitKey)
_LBUTTON = win32con.VK_LBUTTON
_VISUALS_EVERY = 2  # imshow + waitKey cost 1-3 ms; preview at half rate
_Y_STEP = 0.02      # lock_y nudge per tap; hold repeats every _Y_REPEAT s
_Y_REPEAT = 0.15
_y_down = {}        # key -> held last frame
_y_last = {}        # key -> last repeat time


def _nudge_lock_y():
    """Up/Down arrows move the vertical lock point on the target box.
    GetAsyncKeyState is global, so this works while the game has focus."""
    now = time.perf_counter()
    step = 0.0
    for key, d in ((win32con.VK_UP, 1.0), (win32con.VK_DOWN, -1.0)):
        down = win32api.GetAsyncKeyState(key) < 0
        if down and (not _y_down.get(key) or now - _y_last.get(key, 0) > _Y_REPEAT):
            step += d
            _y_last[key] = now
        _y_down[key] = down
    if step:
        config.lock_y = min(1.0, max(0.0, config.lock_y + _Y_STEP * step))
        print('[aim] lock_y = {:.2f}   (0=框顶  0.2=头  0.5=中心  1=框底)'.format(
            config.lock_y))


def run(detector, camera, center):
    """Run until the quit key is pressed.

    detector.infer(frame) returns the NMS tensor; detector.aim consumes it
    and returns the host rows, which visuals draws without another sync.
    """
    cv2 = None
    if visuals:
        import cv2

    count = 0
    shown = 0
    start = time.perf_counter()
    aim = detector.aim
    infer = detector.infer
    get = camera.get_latest_frame
    try:
        while win32api.GetAsyncKeyState(_QUIT) == 0:
            _nudge_lock_y()
            frame = get()
            if frame is None:
                time.sleep(0.001)  # capture warm-up; don't spin a core
                continue
            rows = aim(infer(frame), center)

            if capture and win32api.GetKeyState(_LBUTTON) < 0:
                _save_frame(frame)

            count += 1
            now = time.perf_counter()
            if now - start > 1:
                if cpsDisplay:
                    print("CPS: {}  aim: {}".format(
                        count, "ON" if win32api.GetKeyState(win32con.VK_CAPITAL) else "off"))
                count = 0
                start = now

            if visuals:
                shown += 1
                if shown % _VISUALS_EVERY == 0:
                    _draw(cv2, frame, rows)
                    cv2.imshow('Live Feed', frame)
                    if (cv2.waitKey(1) & 0xFF) == ord('q'):
                        break
    finally:
        camera.stop()


def _save_frame(frame):
    from PIL import Image
    os.makedirs('images', exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    Image.fromarray(frame).save('images/' + stamp + '.png')


def _draw(cv2, frame, rows):
    """Draw the host rows Detector.aim already transferred -- no device sync."""
    if rows is None or rows.shape[0] == 0:
        return
    for x1, y1, x2, y2, conf, cls_id in rows.tolist():
        start = (int(x2), int(y2))
        end = (int(x1), int(y1))
        label = "{}: {:.2f}%".format(class_label(cls_id), conf * 100)
        cv2.rectangle(frame, start, end, (0, 255, 0), 2)
        text_y = start[1] - 15 if start[1] - 15 > 15 else start[1] + 15
        cv2.putText(frame, label, (start[0], text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
