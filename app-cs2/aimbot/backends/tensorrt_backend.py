"""TensorRT backend. The fastest path: the engine runs FP16 on CUDA.

The frame is staged into pinned memory and uploaded once, the engine reads
that buffer directly, and nothing returns to the host until the single
D2H of the surviving rows.
"""

from aimbot.backends.base import Detector
from aimbot.engine import Engine
from aimbot.nms import nms
from aimbot.preprocess import CudaUploader
from aimbot.targeting import class_filter
from config import confidence, iou


class TensorRTDetector(Detector):
    def __init__(self, weights, mouse, headshot_fraction=0.32, speed=2.6):
        super().__init__(mouse, headshot_fraction, speed)
        self.engine = Engine(weights)
        self.uploader = CudaUploader(half=True)
        # Off-team boxes are dropped before the class-agnostic NMS, so a
        # body of the wrong team never crowds out one of the right team.
        self.classes = class_filter('cuda')

    def infer(self, frame):
        return nms(self.engine(self.uploader.upload(frame)),
                   confidence, iou, self.classes, max_det=2)
