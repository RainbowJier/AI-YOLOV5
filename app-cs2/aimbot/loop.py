"""The shared per-frame loop."""

import datetime
import os
import queue
import threading
import time

import win32api
import win32con

import config
from aimbot import feed
from aimbot.targeting import class_label
from config import aaQuitKey, capture, cpsDisplay

_QUIT = ord(aaQuitKey)
_LBUTTON = win32con.VK_LBUTTON
_VISUALS_EVERY = 2  # draw + publish cost ~1 ms; feed at half the CPS
_Y_STEP = 0.02      # lock_y nudge per tap; hold repeats every _Y_REPEAT s
_Y_REPEAT = 0.15
_y_down = {}        # key -> held last frame
_y_last = {}        # key -> last repeat time

# Dataset saving runs off the loop thread: a PNG encode is 1-3 ms, which
# would otherwise eat the whole per-frame budget while the trigger is held.
_save_q = queue.Queue(maxsize=8)
_save_thread = None
_save_warn = 0.0


def _save_worker():
    from PIL import Image
    os.makedirs('images', exist_ok=True)
    while True:
        # The queued array is a private copy: bettercam hands out views into
        # its ring buffer, which the next grabs overwrite.
        Image.fromarray(_save_q.get()).save(
            'images/' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + '.png')


def _save_frame(frame):
    global _save_warn, _save_thread
    if _save_thread is None:
        # Daemon: a stuck disk must not keep the process alive after quit.
        _save_thread = threading.Thread(target=_save_worker, name='save',
                                        daemon=True)
        _save_thread.start()
    try:
        _save_q.put_nowait(frame.copy())
    except queue.Full:
        now = time.perf_counter()
        if now - _save_warn > 5:
            _save_warn = now
            print('[capture] disk behind, dropping frames')


def _drain_saves(timeout=2.0):
    """On quit, give queued frames a moment to hit the disk."""
    deadline = time.perf_counter() + timeout
    while not _save_q.empty() and time.perf_counter() < deadline:
        time.sleep(0.02)


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
        print('[aim] lock_y = {:.2f}   (小=往上瞄 大=往下瞄; 0=头顶 0.2≈头 0.5≈胸腹)'.format(
            config.lock_y))


def run(detector, camera, center):
    """Run until the quit key is pressed.

    detector.infer(frame) returns the NMS tensor; detector.aim consumes it
    and returns the host rows, which visuals draws without another sync.
    """
    cv2 = None  # imported lazily for _draw; config.visuals is read live
                # (the tuner panel flips it mid-run)

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

            # Embedded preview (tuner panel): draw the boxes here, then hand
            # the finished frame to the UI's feed slot -- latest wins.
            if config.visuals:
                if cv2 is None:
                    import cv2
                shown += 1
                if shown % _VISUALS_EVERY == 0:
                    _draw(cv2, frame, rows)
                    feed.publish(frame)
    finally:
        camera.stop()
        _drain_saves()


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
