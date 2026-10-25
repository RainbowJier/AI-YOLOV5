"""TensorRT backend. The fastest path: the engine runs FP16 on CUDA.

The frame is uploaded once and normalized as a torch tensor, then the engine
reads that buffer directly. Nothing returns to the host until the single
chosen box does.
"""

from aimbot.backends.base import Detector
from aimbot.engine import Engine
from aimbot.nms import nms
from aimbot.preprocess import frame_to_cuda
from aimbot.targeting import class_filter
from config import confidence, iou


class TensorRTDetector(Detector):
    def __init__(self, weights, mouse, headshot_fraction=0.32, speed=2.6):
        super().__init__(mouse, headshot_fraction, speed)
        self.engine = Engine(weights)
        self.classes = class_filter('cuda')

    def infer(self, frame):
        im = frame_to_cuda(frame, half=True)
        return nms(self.engine(im), confidence, iou, self.classes, max_det=2)
