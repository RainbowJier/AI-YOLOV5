"""The shared per-frame loop."""

import datetime
import os
import time

import win32api
import win32con

from config import aaQuitKey, capture, cpsDisplay, visuals

_QUIT = ord(aaQuitKey)
_LBUTTON = win32con.VK_LBUTTON


def run(detector, camera, center):
    """Run until the quit key is pressed.

    detector.infer(frame) returns the NMS tensor; detector.aim consumes it.
    """
    cv2 = None
    if visuals:
        import cv2

    count = 0
    start = time.perf_counter()
    aim = detector.aim
    infer = detector.infer
    get = camera.get_latest_frame
    try:
        while win32api.GetAsyncKeyState(_QUIT) == 0:
            frame = get()
            if frame is None:
                continue
            det = infer(frame)
            aim(det, center)

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
                _draw(cv2, frame, det)
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


def _draw(cv2, frame, det):
    if det is None or det.shape[0] == 0:
        return
    rows = det.detach().cpu().tolist()
    for x1, y1, x2, y2, conf, cls_id in rows:
        start = (int(x2), int(y2))
        end = (int(x1), int(y1))
        label = "{}: {:.2f}%".format("Body" if cls_id in (0, 2) else "Head", conf * 100)
        cv2.rectangle(frame, start, end, (0, 255, 0), 2)
        text_y = start[1] - 15 if start[1] - 15 > 15 else start[1] + 15
        cv2.putText(frame, label, (start[0], text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
