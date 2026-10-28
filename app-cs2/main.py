"""Single entry point. The backend follows the weight file's suffix.

    .\\.venv\\Scripts\\python.exe app-cs2\\main.py --weights app-cs2\\weights\\10w-v5-320-16.engine
"""

import argparse
import os
import sys

_APP = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_APP)
if _APP not in sys.path:
    sys.path.insert(0, _APP)
os.chdir(_ROOT)

from aimbot.backends import load_detector
from aimbot.capture import game_selection
from aimbot.driver import create_driver
from aimbot.loop import run
from aimbot.tuner import start as start_tuner
from config import mouse_driver

DEFAULT_WEIGHTS = 'app-cs2/weights/10w-v5-320-16.engine'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS, help='.pt, .onnx or .engine model')
    args = parser.parse_args()

    selected = game_selection()
    if selected is None:
        return
    camera, c_width, c_height = selected

    mouse = create_driver(mouse_driver)
    if not mouse.ok:
        raise SystemExit('mouse driver "{}" failed to init; see the error above'.format(mouse_driver))
    try:
        detector = load_detector(args.weights, mouse)
        start_tuner()  # runtime tuning window; sliders apply instantly
        run(detector, camera, (c_width, c_height))
    finally:
        close = getattr(mouse, 'close', None)
        if close is not None:
            close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exception(e)
        print("ERROR: " + str(e))
