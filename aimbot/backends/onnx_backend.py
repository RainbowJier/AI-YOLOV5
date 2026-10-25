"""ONNX Runtime backend. Provider comes from onnxChoice in config.py."""

import numpy as np
import onnxruntime as ort
import torch

from aimbot.targeting import aim_at, boxes_from_nms, select_target
from config import confidence, iou, onnxChoice
from utils.general import non_max_suppression

_PROVIDERS = {1: "CPUExecutionProvider", 2: "DmlExecutionProvider", 3: "CUDAExecutionProvider"}


class OnnxDetector:
    def __init__(self, weights, mouse, headshot_fraction=0.1, speed=2.6):
        self.mouse = mouse
        self.headshot_fraction = headshot_fraction
        self.speed = speed
        self.provider = _PROVIDERS[onnxChoice]

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(weights, sess_options=options, providers=[self.provider])

        meta = self.session.get_inputs()[0]
        self.input_name = meta.name
        self.half = meta.type == "tensor(float16)"
        print("模型的tensor：", meta.type)
        print("模型的shape：", meta.shape)

    def infer(self, frame):
        if onnxChoice == 3:
            im = torch.from_numpy(frame)
            if im.shape[2] == 4:
                im = im[:, :, :3]
            im = im.permute(2, 0, 1).unsqueeze(0).to('cuda', non_blocking=True)
            im = (im.half() if self.half else im.float()).div_(255)
            feed = im.cpu().numpy()
        else:
            im = np.array([frame])
            if im.shape[3] == 4:
                im = im[:, :, :, :3]
            im = (im / 255).astype(np.float16 if self.half else np.float32)
            im = np.moveaxis(im, 3, 1)
            feed = im

        outputs = self.session.run(None, {self.input_name: feed})
        pred = non_max_suppression(torch.from_numpy(outputs[0]), confidence, iou,
                                   [0, 1, 2, 3], False, max_det=3)
        return boxes_from_nms(pred[0], feed.shape)

    def aim(self, boxes, center):
        target = select_target(boxes, center)
        if target is not None:
            aim_at(target, center, self.mouse, self.headshot_fraction, self.speed)
