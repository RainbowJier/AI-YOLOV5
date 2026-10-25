"""PyTorch entry point. Slowest of the three, kept for checkpoints that have
not been exported yet.

    python main.py --weights weights/cs2/yolov5s.pt
"""

import argparse

from aimbot.backends.torch_backend import TorchDetector
from aimbot.capture import game_selection
from aimbot.driver import LogitechDriver
from aimbot.loop import run

# weights/CS2-2/yolov5s.pt never existed; point at the weights that are present.
DEFAULT_WEIGHTS = 'weights/cs2/yolov5s.pt'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS, help='path to a .pt checkpoint')
    args = parser.parse_args()

    selected = game_selection()
    if selected is None:
        return
    camera, c_width, c_height = selected

    mouse = LogitechDriver()
    detector = TorchDetector(args.weights, mouse)
    run(detector, camera, (c_width, c_height))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exception(e)
        print("ERROR: " + str(e))
