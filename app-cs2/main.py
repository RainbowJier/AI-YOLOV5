"""Single entry point. The backend follows the weight file's suffix.

    .\\.venv\\Scripts\\python.exe app-cs2\\main.py --weights weights\\cs2\\xiaozhen.engine
    .\\.venv\\Scripts\\python.exe app-cs2\\main.py --weights weights\\sanjiaozhou\\v1\\320-FP16\\sjz.onnx
    .\\.venv\\Scripts\\python.exe app-cs2\\main.py --weights weights\\sanjiaozhou\\v2\\320-FP16\\sjz_yolov5.pt
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
from config import mouse_driver

DEFAULT_WEIGHTS = 'weights/cs2/xiaozhen.engine'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS, help='.pt, .onnx or .engine model')
    args = parser.parse_args()

    selected = game_selection()
    if selected is None:
        return
    camera, c_width, c_height = selected

    mouse = create_driver(mouse_driver)
    try:
        detector = load_detector(args.weights, mouse)
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
