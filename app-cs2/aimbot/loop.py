"""The shared per-frame loop."""

import datetime
import os
import time

import win32api
import win32con

from aimbot.targeting import class_label
from config import aaQuitKey, capture, cpsDisplay, visuals

_QUIT = ord(aaQuitKey)
_LBUTTON = win32con.VK_LBUTTON
_VISUALS_EVERY = 2  # imshow + waitKey cost 1-3 ms; preview at half rate


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
                    print("CPS: {}".format(count))
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
