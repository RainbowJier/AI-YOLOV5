"""The shared per-frame loop."""

import datetime
import os
import time

import win32api
import win32con

from config import aaQuitKey, capture, cpsDisplay, visuals


def _save_frame(camera):
    """Save the current frame to images/ while the left button is held."""
    if win32api.GetKeyState(win32con.VK_LBUTTON) >= 0:
        return
    frame = camera.get_latest_frame()
    from PIL import Image
    os.makedirs('images', exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    Image.fromarray(frame).save('images/' + stamp + '.png')


def run(detector, camera, center):
    """Run until the quit key is pressed.

    detector must implement infer(frame) -> list of (x, y, w, h, conf, cls)
    and aim(boxes, center).
    """
    from utils.general import cv2

    count = 0
    start = time.time()
    try:
        while win32api.GetAsyncKeyState(ord(aaQuitKey)) == 0:
            frame = camera.get_latest_frame()
            if frame is None:
                continue
            boxes = detector.infer(frame)
            detector.aim(boxes, center)

            if capture:
                _save_frame(camera)

            count += 1
            if time.time() - start > 1:
                if cpsDisplay:
                    print("CPS: {}".format(count))
                count = 0
                start = time.time()

            if visuals:
                _draw(cv2, frame, boxes)
                cv2.imshow('Live Feed', frame)
                if (cv2.waitKey(1) & 0xFF) == ord('q'):
                    break
    finally:
        camera.stop()


def _draw(cv2, frame, boxes):
    for x, y, w, h, conf, cls_id in boxes:
        half_w, half_h = round(w / 2), round(h / 2)
        start = (int(x + half_w), int(y + half_h))
        end = (int(x - half_w), int(y - half_h))
        label = "{}: {:.2f}%".format("Body" if cls_id in (0, 2) else "Head", conf * 100)
        cv2.rectangle(frame, start, end, (0, 255, 0), 2)
        text_y = start[1] - 15 if start[1] - 15 > 15 else start[1] + 15
        cv2.putText(frame, label, (start[0], text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
