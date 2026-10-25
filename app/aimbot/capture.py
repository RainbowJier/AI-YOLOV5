"""Game window selection and centered region capture."""

import time

import bettercam
import pygetwindow

from config import screenShotHeight, screenShotWidth, target_fps

_ACTIVATE_RETRIES = 10
_ACTIVATE_WAIT = 3.0


def game_selection():
    """Let the user pick a window and start a bettercam capture of its center.

    Returns (camera, c_width, c_height), the crosshair position inside the
    capture region, or None on failure.
    """
    try:
        windows = [w for w in pygetwindow.getAllWindows() if w.title]
        print("=== All Windows ===")
        for index, window in enumerate(windows):
            print("[{}]: {}".format(index, window.title))
        try:
            user_input = int(input(
                "Please enter the number corresponding to the window you'd like to select: "))
            window = windows[user_input]
        except (ValueError, IndexError):
            print("You didn't enter a valid number. Please try again.")
            return None
    except Exception as e:
        print("Failed to select game window: {}".format(e))
        return None

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
            print("Failed to activate game window: {}".format(str(e)))
            print("Read the relevant restrictions here: "
                  "https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow")
            break
        if attempt + 1 < _ACTIVATE_RETRIES:
            time.sleep(_ACTIVATE_WAIT)
    if not activated:
        return None
    print("Successfully activated the game window...")

    left = ((window.left + window.right) // 2) - (screenShotWidth // 2)
    top = window.top + (window.height - screenShotHeight) // 2
    region = (left, top, left + screenShotWidth, top + screenShotHeight)

    camera = bettercam.create(output_color="RGB", region=region, max_buffer_len=64)
    if camera is None:
        print("Camera creation failed.")
        return None
    camera.start(target_fps=target_fps, video_mode=True)
    return camera, screenShotWidth // 2, screenShotHeight // 2
