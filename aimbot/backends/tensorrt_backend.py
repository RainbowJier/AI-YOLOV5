"""TensorRT backend. The fastest path: engine runs FP16 on CUDA.

The frame is uploaded once and normalized, transposed and batched entirely
as a torch tensor, so nothing bounces back through the host before inference.
"""

import torch

from aimbot.targeting import aim_at, boxes_from_nms, select_target
from config import confidence, iou
from models.common import DetectMultiBackend
from utils.general import non_max_suppression


class TensorRTDetector:
    def __init__(self, weights, mouse, headshot_fraction=0.32, speed=2.6):
        self.mouse = mouse
        self.headshot_fraction = headshot_fraction
        self.speed = speed
        self.model = DetectMultiBackend(weights, device=torch.device('cuda'), dnn=False, data='', fp16=True)

    def infer(self, frame):
        # from_numpy shares the capture buffer's memory; one HtoD copy follows.
        im = torch.from_numpy(frame)
        if im.shape[2] == 4:
            im = im[:, :, :3]
        im = im.permute(2, 0, 1).unsqueeze(0).to('cuda', non_blocking=True)  # HWC -> BCHW
        im = im.half().div_(255)
        with torch.no_grad():
            results = self.model(im)
            pred = non_max_suppression(results, confidence, iou, [0, 1, 2, 3], False, max_det=2)
        return boxes_from_nms(pred[0], im.shape, bodies_only=True)

    def aim(self, boxes, center):
        target = select_target(boxes, center)
        if target is not None:
            aim_at(target, center, self.mouse, self.headshot_fraction, self.speed)
