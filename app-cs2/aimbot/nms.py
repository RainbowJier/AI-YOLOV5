"""NMS for a single 320x320 frame, YOLOv5 and YOLOv8/11 layouts.

utils.general.non_max_suppression does the same math, but it also sorts
every candidate, builds a class-offset tensor and checks a time limit on
every frame. At max_det of 2-3 and one class family that is all overhead.

The device side never synchronizes: the prediction is reduced to a
fixed-size slab of the top-_TOPK candidates (multiply, max, topk, gather
-- no data-dependent shapes), and the slab crosses to the host in one
copy. The threshold, the class filter and a small greedy NMS then run in
numpy over at most _TOPK rows.

YOLOv5 emits (1, anchors, 5+nc): xywh, objectness, class scores, and the
confidence is objectness times class score. YOLOv8/11 emits (1, 4+nc,
anchors) with no objectness -- the class score is the confidence. The
layouts are told apart by shape (the anchor count, 2100 at 320x320, always
dwarfs 4+nc). Result: (n, 6) cpu float32 tensor of xyxy, conf, cls.

_TOPK=64 covers everything a 5v5 frame puts past 0.75 confidence with a
wide margin; raise it for crowd scenes, the per-frame cost is the same.
"""

import numpy as np
import torch

_TOPK = 64


def nms(prediction, conf_thres, iou_thres, classes=None, max_det=10):
    """prediction: v5 (1, anchors, 5+nc) or v8/11 (1, 4+nc, anchors), xywh.

    classes is a host iterable of class ids, applied before the NMS so a
    wrong-team box never crowds out a right-team one.
    """
    if isinstance(prediction, (list, tuple)):
        prediction = prediction[0]
    x = prediction[0]
    if x.dtype == torch.float16 and not x.is_cuda:
        x = x.float()  # CPU Half lacks some torch ops used below
    if x.shape[0] < x.shape[1]:
        # v8/11: (4+nc, anchors); transpose and score straight off the classes.
        x = x.T
        scores = x[:, 4:]
    else:
        # v5: (anchors, 5+nc); confidence is objectness times class score.
        # Out of place: the prediction buffer is reused by the backend, so
        # an in-place multiply would corrupt the next frame's objectness.
        scores = x[:, 5:] * x[:, 4:5]

    conf, cls = scores.max(1)
    conf, idx = conf.topk(min(_TOPK, conf.shape[0]))

    # The frame's single device sync: the whole slab in one copy.
    xywh = x[idx, :4].cpu().numpy().astype(np.float32)
    conf = conf.cpu().numpy()
    cls = cls[idx].cpu().numpy()

    box = np.empty_like(xywh)
    box[:, 0] = xywh[:, 0] - xywh[:, 2] * 0.5
    box[:, 1] = xywh[:, 1] - xywh[:, 3] * 0.5
    box[:, 2] = xywh[:, 0] + xywh[:, 2] * 0.5
    box[:, 3] = xywh[:, 1] + xywh[:, 3] * 0.5

    keep = conf > conf_thres
    if classes is not None:
        keep &= np.isin(cls, classes)
    box, conf, cls = box[keep], conf[keep], cls[keep]
    order = _greedy_nms(box, conf, iou_thres)[:max_det]

    out = np.empty((len(order), 6), np.float32)
    if order:
        kept = np.asarray(order)
        out[:, :4], out[:, 4], out[:, 5] = box[kept], conf[kept], cls[kept]
    return torch.from_numpy(out)


def _greedy_nms(box, conf, iou_thres):
    """Class-agnostic greedy NMS: overlapping body/head boxes of the same
    player collapse instead of both surviving."""
    areas = (box[:, 2] - box[:, 0]) * (box[:, 3] - box[:, 1])
    order = conf.argsort()[::-1]
    keep = []
    while order.size:
        i = order[0]
        keep.append(int(i))
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(box[i, 0], box[rest, 0])
        yy1 = np.maximum(box[i, 1], box[rest, 1])
        xx2 = np.minimum(box[i, 2], box[rest, 2])
        yy2 = np.minimum(box[i, 3], box[rest, 3])
        w = np.clip(xx2 - xx1, 0, None)
        h = np.clip(yy2 - yy1, 0, None)
        inter = w * h
        iou = inter / (areas[i] + areas[rest] - inter)
        order = rest[iou <= iou_thres]
    return keep
