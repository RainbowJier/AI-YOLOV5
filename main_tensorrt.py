"""TensorRT entry point. Fastest path, NVIDIA only.

    python main_tensorrt.py --weights weights/cs2/xiaozhen.engine
"""

import argparse

from aimbot.backends.tensorrt_backend import TensorRTDetector
from aimbot.capture import game_selection
from aimbot.driver import LogitechDriver
from aimbot.loop import run

DEFAULT_WEIGHTS = 'weights/cs2/xiaozhen.engine'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS, help='path to a .engine file')
    args = parser.parse_args()

    selected = game_selection()
    if selected is None:
        return
    camera, c_width, c_height = selected

    mouse = LogitechDriver()
    detector = TensorRTDetector(args.weights, mouse)
    run(detector, camera, (c_width, c_height))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exception(e)
        print("ERROR: " + str(e))
