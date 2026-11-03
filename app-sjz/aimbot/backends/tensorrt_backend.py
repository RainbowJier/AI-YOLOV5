"""TensorRT backend. The fastest path: the engine runs FP16 on CUDA.

The frame is staged into pinned memory and uploaded once, the engine reads
that buffer directly, and the whole prediction comes back to the host in
one copy for the NMS.

No class filter here: the aim/head switches are applied by pick() on the
host for every backend alike, so detect.py compares weights apples-to-
apples (a CLASS_IDS pass inside this nms once made the engine look like
it missed a third of the boxes the onnx backend found).
"""

import torch

from aimbot.backends.base import Detector
from aimbot.engine import Engine
from aimbot.nms import nms
from aimbot.preprocess import CudaUploader
from config import confidence, iou


class TensorRTDetector(Detector):
    def __init__(self, weights, mouse, speed=2.6):
        super().__init__(mouse, speed)
        self.engine = Engine(weights)
        # Match the uploader to the engine's input dtype: a strongly-typed
        # build of an fp32 onnx takes fp32 (feeding it fp16 silently
        # produced garbage -- same shape, zero detections).
        input_buf = self.engine.bindings[self.engine.input].data
        self.uploader = CudaUploader(half=input_buf.dtype == torch.float16)

    def infer(self, frame):
        return nms(self.engine(self.uploader.upload(frame)),
                   confidence, iou, max_det=3)
