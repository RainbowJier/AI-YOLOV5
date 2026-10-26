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
from aimbot.backends import load_detector
from aimbot.targeting import class_label
from config import confidence as default_conf, iou as default_iou

_SNAPSHOTS = 6  # annotated pngs saved, frames that had detections


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
    detector = load_detector(args.weights, mouse=None)
    mh, mw = model_size(detector)

    cap = cv2.VideoCapture(args.source)
    if not cap.isOpened():
        raise SystemExit('cannot open {} (resolved: {})'.format(
            args.source, os.path.abspath(args.source)))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 30
    stem = os.path.splitext(os.path.basename(args.source))[0]
    out_mp4 = os.path.join(os.path.dirname(args.source) or '.', stem + '_detected.mp4')

    writer = None
    saved = n_seen = n_infer = n_det = 0
    infer_ms = total_ms = 0.0
    start = time.perf_counter()
    last_log = 0.0

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if n_seen == 0:  # letterbox params, fixed for the whole video
            ih, iw = frame.shape[:2]
            scale = min(mh / ih, mw / iw)
            pad_top, pad_left = (mh - round(ih * scale)) // 2, (mw - round(iw * scale)) // 2
            if writer is None:
                writer = cv2.VideoWriter(out_mp4, cv2.VideoWriter_fourcc(*'mp4v'), fps_in, (iw, ih))
        if n_seen % args.vid_stride:
            n_seen += 1
            continue
        n_seen += 1
        t0 = time.perf_counter()
        rgb = cv2.cvtColor(letterbox(frame, mh, mw), cv2.COLOR_BGR2RGB)
        det = detector.infer(np.ascontiguousarray(rgb))
        n_infer += 1
        infer_ms += (time.perf_counter() - t0) * 1000
        now = time.perf_counter()
        if now - last_log > 2:  # progress line, refreshed in place
            last_log = now
            eta = (total_frames - n_seen) / max(n_seen, 1) * (now - start)
            print('\r{:6d}/{}  infer {:4.1f} ms  ETA {:02d}:{:02d}   '.format(
                n_seen, total_frames, infer_ms / n_infer, int(eta) // 60, int(eta) % 60),
                end='', flush=True)

        rows = det.cpu().tolist() if det.numel() else []
        n_det += len(rows)
        # Draw on the full-resolution frame: boxes map back out of the
        # letterbox (model coords -> original pixels), so the output video
        # keeps the source quality instead of the 320x320 model view.
        for x1, y1, x2, y2, conf, cls_id in rows:
            p1 = (int((x1 - pad_left) / scale), int((y1 - pad_top) / scale))
            p2 = (int((x2 - pad_left) / scale), int((y2 - pad_top) / scale))
            label = '{} {:.0f}%'.format(class_label(cls_id), conf * 100)
            cv2.rectangle(frame, p1, p2, (0, 255, 0), 2)
            cv2.putText(frame, label, (p1[0], max(p1[1] - 6, 14)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        writer.write(frame)
        if rows and saved < _SNAPSHOTS:
            cv2.imwrite(os.path.join(os.path.dirname(args.source) or '.',
                        '{}_det_{}.png'.format(stem, n_seen)), frame)
            saved += 1
        total_ms = (time.perf_counter() - start) * 1000

    cap.release()
    if writer:
        writer.release()
    if n_seen == 0:
        raise SystemExit('no frames decoded from ' + args.source)
    print()  # close the progress line before the summary

    print('frames: {}  inferred: {}  detections: {}  ({:.2f}/frame)'.format(
        n_seen, n_infer, n_det, n_det / n_infer))
    print('infer:  {:.1f} ms/frame   wall: {:.1f} ms/frame  ~{:.0f} FPS'.format(
        infer_ms / n_seen, total_ms / n_seen, 1000 * n_seen / total_ms))
    print('output: ' + out_mp4)


if __name__ == '__main__':
    main()
