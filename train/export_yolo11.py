"""Export a YOLOv11 (ultralytics) model to .onnx / .engine for app/main.py.

YOLOv11 checkpoints cannot go through train/export.py -- that script speaks
the vendored YOLOv5 graph. ultralytics exports its own formats:

    .\\.venv\\Scripts\\python.exe train\\export_yolo11.py ^
        --weights runs\\detect\\train\\weights\\best.pt ^
        --include onnx engine --imgsz 320 --half --device 0

The output is (1, 4+nc, anchors) with no objectness; app/aimbot/nms.py
detects the layout by shape, so the runtime needs no per-model switch.
"""

import argparse

from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--weights', required=True, help='ultralytics .pt checkpoint')
    parser.add_argument('--include', nargs='+', default=['onnx'], choices=['onnx', 'engine'],
                        help='formats to export (default: onnx)')
    parser.add_argument('--imgsz', type=int, default=320,
                        help='square input size, keep it equal to the app/config.py capture area')
    parser.add_argument('--half', action='store_true', help='FP16 export')
    parser.add_argument('--device', default='0', help='cuda device, e.g. 0')
    parser.add_argument('--workspace', type=int, default=4, help='TensorRT workspace, GiB')
    args = parser.parse_args()

    for fmt in args.include:
        path = YOLO(args.weights).export(
            format=fmt, imgsz=args.imgsz, half=args.half, device=args.device,
            dynamic=False, simplify=True, workspace=args.workspace, verbose=False)
        print('{} -> {}'.format(args.weights, path))


if __name__ == '__main__':
    main()
