"""Single entry point. The backend follows the weight file's suffix.

    .\\.venv\\Scripts\\python.exe app-sjz\\main.py --weights app-sjz\\weights\\sjzs.engine

默认权重 sjzs（YOLOv8s · 256×256 · 0=身体 1=头，训练集过滤队友），
与 config.py 的 screenShotWidth/Height = 256 配套。weights/ 另有
6AY_v26m（YOLO26 端到端）、三角洲模型（v5s）、delta_force_v4（v8n）
备选；换权重需同步截取尺寸并重转 engine（TensorRT STRONGLY_TYPED，
换显卡需重转）。
"""

import argparse
import os
import sys

_APP = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_APP)
if _APP not in sys.path:
    sys.path.insert(0, _APP)
os.chdir(_ROOT)

# Below-normal CPU priority: when the game and the bot share the machine,
# the game's threads win every scheduling fight. GPU duty is untouched,
# but capture/inference orchestration stops stealing game frame time.
try:
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)  # BELOW_NORMAL
except Exception:
    pass

from aimbot import tuner
from aimbot.backends import load_detector
from aimbot.capture import game_selection
from aimbot.driver import create_driver
from aimbot.loop import run
from config import mouse_driver

DEFAULT_WEIGHTS = 'app-sjz/weights/6AY_v26m_1020_320x320.engine'


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
        tuner.start()  # runtime tuning workbench; sliders apply instantly
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
