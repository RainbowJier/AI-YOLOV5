"""Single entry point. The backend follows the weight file's suffix.

    .\\.venv\\Scripts\\python.exe app\\main.py --weights weights\\cs2\\xiaozhen.engine
    .\\.venv\\Scripts\\python.exe main.py --weights weights\\sanjiaozhou\\v1\\320-FP16\\sjz.onnx
    .\\.venv\\Scripts\\python.exe main.py --weights weights\\sanjiaozhou\\v2\\320-FP16\\sjz_yolov5.pt

main_onnx.py and main_tensorrt.py remain as thin wrappers around this.
"""

import argparse
import os
import sys

_APP = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_APP)
if _APP not in sys.path:
    sys.path.insert(0, _APP)
os.chdir(_ROOT)

from aimbot.capture import game_selection
from aimbot.driver import LogitechDriver
from aimbot.loop import run

DEFAULT_WEIGHTS = 'weights/cs2/xiaozhen.engine'

_BACKENDS = {
    '.pt': ('aimbot.backends.torch_backend', 'TorchDetector'),
    '.onnx': ('aimbot.backends.onnx_backend', 'OnnxDetector'),
    '.engine': ('aimbot.backends.tensorrt_backend', 'TensorRTDetector'),
}


def load_detector(weights, mouse):
    suffix = os.path.splitext(weights)[1].lower()
    try:
        module_name, class_name = _BACKENDS[suffix]
    except KeyError:
        raise SystemExit('unsupported weights {}: expected .pt, .onnx or .engine'.format(weights))
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)(weights, mouse)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', default=DEFAULT_WEIGHTS, help='.pt, .onnx or .engine model')
    args = parser.parse_args()

    selected = game_selection()
    if selected is None:
        return
    camera, c_width, c_height = selected

    mouse = LogitechDriver()
    detector = load_detector(args.weights, mouse)
    run(detector, camera, (c_width, c_height))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exception(e)
        print("ERROR: " + str(e))
