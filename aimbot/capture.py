"""Game window selection and centered region capture."""

import time

import bettercam
import pygetwindow

from config import screenShotHeight, screenShotWidth, target_fps


def game_selection():
    """Let the user pick a window and start a bettercam capture of its center.

    Returns (camera, c_width, c_height) where c_width/c_height are the
    crosshair position inside the capture region, or None on failure.
    """
    try:
        windows = pygetwindow.getAllWindows()
        print("=== All Windows ===")
        for index, window in enumerate(windows):
            if window.title != "":
                print("[{}]: {}".format(index, window.title))
        try:
            user_input = int(input(
                "Please enter the number corresponding to the window you'd like to select: "))
        except ValueError:
            print("You didn't enter a valid number. Please try again.")
            return None
        window = windows[user_input]
    except Exception as e:
        print("Failed to select game window: {}".format(e))
        return None

    retries = 10
    activated = False
    while retries > 0:
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
            retries = 0
            break
        time.sleep(3.0)
        retries -= 1
    if not activated:
        return None
    print("Successfully activated the game window...")

    left = ((window.left + window.right) // 2) - (screenShotWidth // 2)
    top = window.top + (window.height - screenShotHeight) // 2
    region = (left, top, left + screenShotWidth, top + screenShotHeight)

    # Crosshair position inside the capture region.
    c_width = screenShotWidth // 2
    c_height = screenShotHeight // 2

    camera = bettercam.create(region=region, max_buffer_len=512)
    if camera is None:
        print("Camera creation failed.")
        return None
    camera.start(target_fps=target_fps, video_mode=True)
    return camera, c_width, c_height
