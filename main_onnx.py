"""ONNX Runtime entry point. Provider is chosen by onnxChoice in config.py
(1 = CPU, 2 = DirectML/AMD, 3 = CUDA/NVIDIA).

    python main_onnx.py --weights weights/sanjiaozhou/v1/320-FP16/sjz.onnx
"""

import argparse

from aimbot.backends.onnx_backend import OnnxDetector
from aimbot.capture import game_selection
from aimbot.driver import LogitechDriver
from aimbot.loop import run

DEFAULT_WEIGHTS = 'weights/sanjiaozhou/v1/320-FP16/sjz.onnx'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS, help='path to an .onnx model')
    args = parser.parse_args()

    selected = game_selection()
    if selected is None:
        return
    camera, c_width, c_height = selected

    mouse = LogitechDriver()
    detector = OnnxDetector(args.weights, mouse)
    run(detector, camera, (c_width, c_height))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exception(e)
        print("ERROR: " + str(e))
