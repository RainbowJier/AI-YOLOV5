"""Game window selection and centered region capture."""

import gc
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


class ResilientCamera:
    """bettercam camera that survives DXGI desktop-duplication loss.

    A display-mode change (fullscreen toggles, overlays, resolution) makes
    ReleaseFrame fail with DXGI_ERROR_ACCESS_LOST. bettercam's capture thread
    then dies, and its own error path calls join() on itself, so the camera
    is left half-stopped; get_latest_frame() waits on an event that nothing
    will ever set again and the aim loop freezes, quit key included.

    This wrapper never blocks: get_latest_frame() waits a bounded time and
    returns None (the loop's "no frame yet" path) instead. If the capture
    thread is dead, or no frame has arrived for _STALL_S, the duplication is
    rebuilt, retrying once a second until the output is available again.
    """

    _WAIT_S = 0.1     # bounded wait per get_latest_frame call
    _STALL_S = 1.5    # no frame for this long -> rebuild even if "alive"
    _RETRY_S = 1.0

    def __init__(self, region, fps):
        self._region = region
        self._fps = fps
        self._cam = None
        self._last_frame_t = time.monotonic()
        self._retry_at = 0.0
        self._open()

    def _open(self):
        cam = bettercam.create(
            output_color="RGB", region=self._region, max_buffer_len=64)
        cam.start(target_fps=self._fps, video_mode=True)
        self._cam = cam
        self._last_frame_t = time.monotonic()

    def _dead(self):
        thread = getattr(self._cam, '_BetterCam__thread', None)
        return thread is not None and not thread.is_alive()

    def _rebuild(self):
        now = time.monotonic()
        if now < self._retry_at:
            return
        self._retry_at = now + self._RETRY_S
        print('[capture] 采集会话丢失（DXGI），正在重建…')
        old, self._cam = self._cam, None
        try:
            if old is not None:
                old.release()
        except Exception:
            pass   # the duplication is already gone; nothing left to free
        del old
        gc.collect()
        # The factory hands back its cached instance for the same output, and
        # anything still referencing the broken one (e.g. the dead capture
        # thread's frame) keeps that weak entry alive -- evict it explicitly.
        factory = getattr(bettercam, '_' + 'DXFactory__factory', None) \
            or vars(bettercam).get('__factory')
        if factory is not None:
            factory._camera_instances.clear()
        try:
            self._open()
        except Exception as e:
            print('[capture] 重建失败，{:.0f} 秒后重试：{}'.format(
                self._RETRY_S, e))
        else:
            print('[capture] 采集已恢复')

    def get_latest_frame(self):
        """Newest frame, or None when none arrived (never blocks long)."""
        cam = self._cam
        if cam is None:
            self._rebuild()
            time.sleep(self._WAIT_S)
            return None
        event = getattr(cam, '_BetterCam__frame_available', None)
        if event is None or event.wait(self._WAIT_S):
            frame = cam.get_latest_frame()
            self._last_frame_t = time.monotonic()
            return frame
        if self._dead() or time.monotonic() - self._last_frame_t > self._STALL_S:
            self._rebuild()
        return None

    def stop(self):
        cam, self._cam = self._cam, None
        if cam is not None:
            try:
                cam.stop()
            except Exception:
                pass


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
        camera = ResilientCamera(region, target_fps)
    except Exception as e:
        print('[capture] 创建采集失败：{}（region={}）'.format(e, region))
        return None
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
