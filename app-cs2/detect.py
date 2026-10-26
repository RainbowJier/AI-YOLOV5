"""Offline video detection on the runtime backends — same engines as main.py.

    .\\.venv\\Scripts\\python.exe app-cs2\\detect.py --source video.mp4
    ... --weights weights\\cs2\\xxx.engine --conf 0.75 --vid-stride 2

The weight suffix picks the backend (.pt torch / .onnx onnxruntime /
.engine tensorrt) and config.onnxChoice picks the ONNX engine (4 =
OpenVINO iGPU/NPU/CPU AUTO), exactly like the live bot. Frames are
letterboxed to the model's input size: whole-scene view, not the
center-crop view the bot sees in-game. Writes <source>_detected.mp4 next
to the source plus speed stats on stdout.
"""

import argparse
import os
import sys
import time

_APP = os.path.dirname(os.path.abspath(__file__))
if _APP not in sys.path:
    sys.path.insert(0, _APP)
os.chdir(os.path.dirname(_APP))

import cv2
import numpy as np

import config
from config import confidence as default_conf, iou as default_iou

_BACKENDS = {
    '.pt': ('aimbot.backends.torch_backend', 'TorchDetector'),
    '.onnx': ('aimbot.backends.onnx_backend', 'OnnxDetector'),
    '.engine': ('aimbot.backends.tensorrt_backend', 'TensorRTDetector'),
}
_SNAPSHOTS = 6  # annotated pngs saved, frames that had detections


def load_detector(weights):
    suffix = os.path.splitext(weights)[1].lower()
    try:
        module_name, class_name = _BACKENDS[suffix]
    except KeyError:
        raise SystemExit('unsupported weights {}: expected .pt, .onnx or .engine'.format(weights))
    module = __import__(module_name, fromlist=[class_name])
    return getattr(module, class_name)(weights, mouse=None)


def model_size(det):
    """(h, w) the loaded model wants. Falls back to the capture size."""
    try:
        if det.ov_request is not None:  # OpenVINO compiled model
            s = det.ov_request.inputs[0].shape
            return int(s[2]), int(s[3])
        if hasattr(det, 'session'):  # onnxruntime session
            s = det.session.get_inputs()[0].shape
            return int(s[2]), int(s[3])
        if hasattr(det, 'engine'):  # tensorrt engine wrapper
            s = det.engine.bindings[det.engine.input].shape
            return int(s[2]), int(s[3])
    except Exception:
        pass
    return config.screenShotHeight, config.screenShotWidth


def letterbox(frame, h, w):
    """Resize + pad to the model input, YOLO style (114 gray borders)."""
    ih, iw = frame.shape[:2]
    r = min(h / ih, w / iw)
    nh, nw = round(ih * r), round(iw * r)
    out = np.full((h, w, 3), 114, np.uint8)
    top, left = (h - nh) // 2, (w - nw) // 2
    out[top:top + nh, left:left + nw] = cv2.resize(frame, (nw, nh))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, help='video file')
    parser.add_argument('--weights', default='weights/cs2/10w-v5-320-16.onnx')
    parser.add_argument('--conf', type=float, default=default_conf)
    parser.add_argument('--iou', type=float, default=default_iou)
    parser.add_argument('--vid-stride', type=int, default=1, help='run every Nth frame')
    args = parser.parse_args()

    config.confidence, config.iou = args.conf, args.iou
    detector = load_detector(args.weights)
    mh, mw = model_size(detector)

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit('cannot open ' + args.source)
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30
    stem = os.path.splitext(os.path.basename(args.source))[0]
    out_mp4 = os.path.join(os.path.dirname(args.source) or '.', stem + '_detected.mp4')

    writer = None
    saved = n_seen = n_det = 0
    infer_ms = total_ms = 0.0
    start = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if n_seen % args.vid_stride:
            n_seen += 1
            continue
        n_seen += 1
        t0 = time.perf_counter()
        rgb = cv2.cvtColor(letterbox(frame, mh, mw), cv2.COLOR_BGR2RGB)
        det = detector.infer(np.ascontiguousarray(rgb))
        infer_ms += (time.perf_counter() - t0) * 1000

        rows = det.cpu().tolist() if det.numel() else []
        n_det += len(rows)
        canvas = letterbox(frame, mh, mw)
        for x1, y1, x2, y2, conf, cls_id in rows:
            label = '{} {:.0f}%'.format('Body' if cls_id in (0, 2) else 'Head', conf * 100)
            cv2.rectangle(canvas, (int(x1), int(y1)), (int(x2), int(y2)), (0, 255, 0), 1)
            cv2.putText(canvas, label, (int(x1), max(int(y1) - 4, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)

        if writer is None:
            writer = cv2.VideoWriter(out_mp4, cv2.VideoWriter_fourcc(*'mp4v'), fps_in, (mw, mh))
        writer.write(canvas)
        if rows and saved < _SNAPSHOTS:
            cv2.imwrite(os.path.join(os.path.dirname(args.source) or '.',
                        '{}_det_{}.png'.format(stem, n_seen)), canvas)
            saved += 1
        total_ms = (time.perf_counter() - start) * 1000

    cap.release()
    if writer:
        writer.release()
    if n_seen == 0:
        raise SystemExit('no frames decoded from ' + args.source)

    print('frames: {}  detections: {}  ({:.2f}/frame)'.format(n_seen, n_det, n_det / n_seen))
    print('infer:  {:.1f} ms/frame   wall: {:.1f} ms/frame  ~{:.0f} FPS'.format(
        infer_ms / n_seen, total_ms / n_seen, 1000 * n_seen / total_ms))
    print('output: ' + out_mp4)


main()
