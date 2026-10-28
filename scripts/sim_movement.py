# -*- coding: utf-8 -*-
"""v3.1 movement core simulation: closed-loop view + regression tests.

The view model: every injected dot rotates the camera, so the target box
moves by -dots * lock_sen pixels on screen (a `gain` factor can break
this -- 0 = dead view, 0.5 = sensitivity mismatch).

Run:  .\\.venv\\Scripts\\python.exe scripts\\sim_movement.py
"""
import importlib
import random
import sys
import types

win32api = types.ModuleType('win32api')
win32con = types.ModuleType('win32con')
win32api._lmb = 0


def _ks(vk):
    if vk == 0x01:
        return win32api._lmb
    return 1  # caps lock on


win32api.GetKeyState = _ks
win32con.VK_LBUTTON = 0x01
sys.modules['win32api'] = win32api
sys.modules['win32con'] = win32con

sys.path.insert(0, r'D:\桌面\github\AI-AIMBOT-YOLOV5\app-cs2')
import config  # noqa: E402
# Pin the params the algorithm's math depends on so the sim tests don't
# flap with whatever the user currently tuned in config.py.
config.move_rate = 10
config.track_tau = 0.019
config.deadband_px = 1
config.lead_min_speed = 30.0
config.lead_fade_radius = 12.0
config.max_move_speed = 4800
config.aim_range = 70
config.lock_sen = 1.25
import aimbot.targeting as T  # noqa: E402


class ViewMouse:
    """Closed-loop fake: records dots; the view offset applies to the box.

    gain: how many px the view really moves per injected dot, as a
    fraction of lock_sen (1.0 = calibrated, 0 = dead view).
    """

    def __init__(self, gain=1.0):
        self.gain = gain * config.lock_sen
        self.dots_x = 0.0
        self.dots_y = 0.0
        self.view_x = 0.0   # px offset applied back to the box
        self.view_y = 0.0
        self.last_dx = 0.0
        self.last_dy = 0.0

    def move(self, dx, dy):
        self.last_dx = dx
        self.last_dy = dy
        self.dots_x += dx
        self.dots_y += dy
        self.view_x -= dx * self.gain
        self.view_y -= dy * self.gain


class Recorder:
    """Dots-only mouse for tests that don't need a view."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.last_dx = 0.0
        self.last_dy = 0.0

    def move(self, dx, dy):
        self.last_dx = dx
        self.last_dy = dy
        self.x += dx
        self.y += dy


def reset():
    importlib.reload(T)
    return T


_DT = 1.0 / 60.0
CX = CY = 160.0


def run_frames(T, m, box_fn, n, speed=2.6):
    """box_fn(i) -> (x, y, w, h); the mouse's view offset is applied."""
    for i in range(n):
        x, y, w, h = box_fn(i)
        if hasattr(m, 'view_x'):
            x += m.view_x
            y += m.view_y
        T.aim_at((x, y, w, h), (CX, CY), m, speed)
        if T._last_t is not None:
            T._last_t -= _DT


def test_stationary_zero_jitter():
    T = reset()
    m = ViewMouse()  # fully closed loop
    random.seed(7)
    noise = lambda: random.uniform(-0.8, 0.8)

    def box(i):
        return (160 + noise(), 130 + noise(), 20, 40)

    run_frames(T, m, box, 300)
    err = (130 - 40 * 0.3) + m.view_y - CY  # aim + view vs crosshair
    assert abs(err) < 6.0, 'did not converge: residual err {:.2f} px'.format(err)
    m.last_dx = m.last_dy = 0.0
    run_frames(T, m, box, 60)
    tail = abs(m.last_dx) + abs(m.last_dy)
    assert tail < 0.06, 'shaking while locked: {:.3f} dots/frame'.format(tail)
    print('PASS stationary: residual {:.2f} px, tail {:.4f} dots/frame'.format(err, tail))


def test_step_no_overshoot():
    T = reset()
    m = ViewMouse()
    crossed = 0.0   # max penetration PAST the aim point after reaching it
    reached = False
    for i in range(400):
        T.aim_at((200 + m.view_x, 130 + m.view_y, 20, 40), (CX, CY), m, 2.6)
        if T._last_t is not None:
            T._last_t -= _DT
        err = (118.0 + m.view_y) - CY   # negative = still below (approaching)
        if err >= -3.0:
            reached = True
        if reached:
            crossed = max(crossed, err)  # positive err = overshot past aim
    err = abs(118.0 + m.view_y - CY)
    assert err < 6.0, 'converge failed: {:.2f}'.format(err)
    assert crossed < 3.0, 'overshoot {:.2f} px past the aim point'.format(crossed)
    print('PASS step: residual {:.2f} px, overshoot {:.2f} px'.format(err, crossed))


def test_strafe_no_lag():
    T = reset()
    m = ViewMouse()

    def box(i):
        # 30 px/s world motion stays inside aim_range for the whole second
        return (160.0 + 0.5 * i, 130.0, 20, 40)

    run_frames(T, m, box, 60)
    box_x = 160.0 + 0.5 * 59
    err = (box_x + m.view_x) - CX
    assert abs(err) < 8.0, 'strafe lag too big: {:.1f} px'.format(err)
    print('PASS strafe: residual err {:.2f} px @ 30 px/s'.format(err))


def test_dead_view_keeps_pushing():
    """v3.0 regression: view ignores input -> output must NOT decay."""
    T = reset()
    m = ViewMouse(gain=0.0)  # view never moves

    def box(i):
        return (200, 130, 20, 40)

    run_frames(T, m, box, 240)  # 4 seconds
    last = abs(m.last_dx) + abs(m.last_dy)
    assert last > 0.5, 'output decayed on dead view: {:.4f} dots'.format(last)
    total = abs(m.dots_x) + abs(m.dots_y)
    assert total > 100, 'gave up too early: {:.1f} dots total'.format(total)
    print('PASS dead view: still pushing {:.2f} dots/frame after 4 s '
          '({:.0f} total)'.format(last, total))


def test_half_sensitivity_converges():
    """v3.0 regression: sensitivity 2x off -> must still converge."""
    T = reset()
    m = ViewMouse(gain=0.5)  # view moves half as far as assumed

    def box(i):
        return (200, 130, 20, 40)

    run_frames(T, m, box, 600)  # 10 seconds
    err = abs(118.0 + m.view_y - CY)
    assert err < 6.0, 'half-sens failed to converge: {:.2f} px'.format(err)
    print('PASS half sensitivity: residual {:.2f} px'.format(err))


def test_lmb_speeds_up():
    def converge(lmb):
        T = reset()
        m = ViewMouse()
        win32api._lmb = lmb
        for i in range(120):  # 2 s
            T.aim_at((200 + m.view_x, 130 + m.view_y, 20, 40), (CX, CY), m, 2.6)
            if T._last_t is not None:
                T._last_t -= _DT
        win32api._lmb = 0
        return abs(118.0 + m.view_y - CY)

    err0 = converge(0)
    err1 = converge(-1)
    assert err0 < 6.0, 'normal did not converge: {:.2f}'.format(err0)
    assert err1 < 6.0, 'firing did not converge: {:.2f}'.format(err1)
    # firing converges in fewer frames: time-to-threshold comparison
    def frames_to(err_thresh, lmb):
        T = reset()
        m = ViewMouse()
        win32api._lmb = lmb
        for i in range(120):
            T.aim_at((200 + m.view_x, 130 + m.view_y, 20, 40), (CX, CY), m, 2.6)
            if T._last_t is not None:
                T._last_t -= _DT
            if abs(118.0 + m.view_y - CY) < err_thresh:
                win32api._lmb = 0
                return i + 1
        win32api._lmb = 0
        return 999

    f0 = frames_to(2.0, 0)
    f1 = frames_to(2.0, -1)
    assert f1 < f0, 'firing not faster: {} vs {} frames'.format(f1, f0)
    print('PASS lmb firing: frames-to-2px normal={} firing={}'.format(f0, f1))


def test_head_body_no_flipflop():
    import numpy as np
    T = reset()
    rows = np.array([
        [100.0, 100.0, 140.0, 180.0, 0.9, 2.0],  # body, center (120,140)
        [110.0, 105.0, 130.0, 125.0, 0.8, 3.0],  # head, center (120,115)
    ], dtype=np.float32)
    center = (160.0, 160.0)
    picks = [T.closest(rows, center) for _ in range(10)]
    xs = {round(float(p[0]), 3) for p in picks}
    ys = {round(float(p[1]), 3) for p in picks}
    assert len(xs) == 1 and len(ys) == 1, 'flip-flopping between boxes!'
    print('PASS sticky selection')


def test_caps_off_resets():
    T = reset()
    m = Recorder()
    saved = win32api.GetKeyState
    win32api.GetKeyState = lambda vk: 0

    def box(i):
        return (200, 130, 20, 40)

    run_frames(T, m, box, 30)
    assert abs(m.x) + abs(m.y) < 1e-9
    assert T._sx is None and T._last_t is None
    win32api.GetKeyState = saved
    print('PASS caps off reset')


if __name__ == '__main__':
    test_stationary_zero_jitter()
    test_step_no_overshoot()
    test_strafe_no_lag()
    test_dead_view_keeps_pushing()
    test_half_sensitivity_converges()
    test_lmb_speeds_up()
    test_head_body_no_flipflop()
    test_caps_off_resets()
    print('ALL TESTS PASSED')
