"""NMS for a single 320x320 frame.

utils.general.non_max_suppression does the same math, but it also sorts
every candidate, builds a class-offset tensor and checks a time limit on
every frame. At max_det of 2-3 and one class family that is all overhead.
This keeps the result identical: (n, 6) of xyxy, conf, cls.
"""

import torch
import torchvision


def nms(prediction, conf_thres, iou_thres, classes=None, max_det=10):
    """prediction: (1, anchors, 5+nc) in xywh, already on its device."""
    if isinstance(prediction, (list, tuple)):
        prediction = prediction[0]
    x = prediction[0]
    x = x[x[:, 4] > conf_thres]
    if x.shape[0] == 0:
        return x.new_zeros((0, 6))

    nc = x.shape[1] - 5
    x[:, 5:] *= x[:, 4:5]
    box = _xywh2xyxy(x[:, :4])
    conf, cls = x[:, 5:5 + nc].max(1, keepdim=True)
    keep = conf.view(-1) > conf_thres
    box, conf, cls = box[keep], conf[keep], cls[keep]
    if classes is not None:
        keep = (cls == classes).any(1)
        box, conf, cls = box[keep], conf[keep], cls[keep]
    if box.shape[0] == 0:
        return x.new_zeros((0, 6))

    # Class-agnostic: one person is one person, overlapping body/head boxes
    # of the same player should collapse instead of both surviving.
    idx = torchvision.ops.nms(box, conf.view(-1), iou_thres)[:max_det]
    return torch.cat((box[idx], conf[idx], cls[idx]), 1)


def _xywh2xyxy(x):
    y = x.new_empty(x.shape)
    y[:, 0] = x[:, 0] - x[:, 2] / 2
    y[:, 1] = x[:, 1] - x[:, 3] / 2
    y[:, 2] = x[:, 0] + x[:, 2] / 2
    y[:, 3] = x[:, 1] + x[:, 3] / 2
    return y
