"""Game window selection and centered region capture."""

import time

import bettercam
import pygetwindow
import win32api
import win32con

from config import screenShotHeight, screenShotWidth, target_fps

_ACTIVATE_RETRIES = 10
_ACTIVATE_WAIT = 3.0
_READY_RETRIES = 10    # ~30 s waiting for the window to become usable
_READY_WAIT = 3.0


def list_windows():
    """Every titled window; the pick list for both the UI and the console."""
    try:
        return [w for w in pygetwindow.getAllWindows() if w.title]
    except Exception as e:
        print("Failed to enumerate windows: {}".format(e))
        return []


def _primary_size():
    """Primary monitor size in physical px -- bettercam validates the
    capture region against exactly this rect."""
    return (win32api.GetSystemMetrics(win32con.SM_CXSCREEN),
            win32api.GetSystemMetrics(win32con.SM_CYSCREEN))


def _window_ready(window):
    """(ok, cx, cy): the window is restored and its centre sits on the
    primary screen -- the rect bettercam validates against."""
    if getattr(window, 'isMinimized', False):
        return False, None, None
    width, height = _primary_size()
    cx = (window.left + window.right) // 2
    cy = (window.top + window.bottom) // 2
    return (0 <= cx < width and 0 <= cy < height), cx, cy


def _region_from_center(cx, cy):
    """Centered capture region, clamped to the primary screen. Minimized
    windows report (-32000, -32000); a restore from a background process
    can be deferred by the OS, and activate() alone never restores -- so
    callers must wait for _window_ready first."""
    width, height = _primary_size()
    left = max(0, min(cx - screenShotWidth // 2, width - screenShotWidth))
    top = max(0, min(cy - screenShotHeight // 2, height - screenShotHeight))
    message = None
    if (left, top) != (cx - screenShotWidth // 2, cy - screenShotHeight // 2):
        message = '窗口部分出界，截取区已钳制到屏幕内'
    return (left, top, left + screenShotWidth, top + screenShotHeight), message


def open_window(window):
    """Activate `window`, wait until it is restored and on the primary
    screen, then start the centered bettercam capture.

    Returns (camera, cx, cy) -- the crosshair position inside the capture
    region -- or None on failure.
    """
    activated = False
    for attempt in range(_ACTIVATE_RETRIES):
        try:
            window.activate()
            activated = True
            break
        except pygetwindow.PyGetWindowException as we:
            print("Failed to activate game window: {}".format(str(we)))
            print("Trying again... (you should switch to the game now)")
        except Exception as e:
            print("Failed to activate game window: {}".format(e))
            print("Read the relevant restrictions here: "
                  "https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow")
            break
        if attempt + 1 < _ACTIVATE_RETRIES:
            time.sleep(_ACTIVATE_WAIT)
    if not activated:
        return None
    print("Successfully activated the game window...")

    # activate() never restores a minimized window and a restore issued by
    # a background process can be deferred -- poll until the window is
    # actually usable (restored, centre on the primary screen).
    ready, cx, cy = _window_ready(window)
    for attempt in range(_READY_RETRIES):
        if ready:
            break
        if getattr(window, 'isMinimized', False):
            try:
                window.restore()
            except Exception as e:
                print("Failed to restore game window: {}".format(e))
        if attempt == 0:
            print('[capture] 等待游戏窗口就绪（若游戏最小化，请点一下游戏窗口）...')
        time.sleep(_READY_WAIT)
        ready, cx, cy = _window_ready(window)
    if not ready:
        if getattr(window, 'isMinimized', False):
            print('[capture] 游戏窗口一直处于最小化状态，已放弃；'
                  '请先点开游戏窗口再重新选择')
        else:
            width, height = _primary_size()
            print('[capture] 游戏窗口中心始终不在主显示器 {}x{} 内，已放弃'.format(
                width, height))
        return None

    region, message = _region_from_center(cx, cy)
    if message:
        print('[capture] {}'.format(message))

    try:
        camera = bettercam.create(
            output_color="RGB", region=region, max_buffer_len=64)
    except ValueError as e:
        print('[capture] 创建采集失败：{}（region={}）'.format(e, region))
        return None
    if camera is None:
        print("Camera creation failed.")
        return None
    camera.start(target_fps=target_fps, video_mode=True)
    return camera, screenShotWidth // 2, screenShotHeight // 2


def game_selection():
    """Console window picker; fallback when the tuner UI is unavailable."""
    windows = list_windows()
    print("=== All Windows ===")
    for index, window in enumerate(windows):
        try:
            size = " ({}x{})".format(window.width, window.height)
        except Exception:
            size = ""
        print("[{}]: {}{}".format(index, window.title, size))
    try:
        user_input = int(input(
            "Enter the number of the GAME window (the one showing the match; "
            "not a launcher/overlay): "))
        return open_window(windows[user_input])
    except (ValueError, IndexError):
        print("You didn't enter a valid number. Please try again.")
        return None
