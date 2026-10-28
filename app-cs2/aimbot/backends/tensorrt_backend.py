"""TensorRT backend. The fastest path: the engine runs FP16 on CUDA.

The frame is staged into pinned memory and uploaded once, the engine reads
that buffer directly, and the whole prediction comes back to the host in
one copy for the NMS.
"""

from aimbot.backends.base import Detector
from aimbot.engine import Engine
from aimbot.nms import nms
from aimbot.preprocess import CudaUploader
from aimbot.targeting import CLASS_IDS
from config import confidence, iou


class TensorRTDetector(Detector):
    def __init__(self, weights, mouse, speed=2.6):
        super().__init__(mouse, speed)
        self.engine = Engine(weights)
        self.uploader = CudaUploader(half=True)

    def infer(self, frame):
        return nms(self.engine(self.uploader.upload(frame)),
                   confidence, iou, CLASS_IDS, max_det=2)
