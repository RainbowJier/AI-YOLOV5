"""PyTorch backend. Loads a .pt checkpoint directly, without torch.hub.

The checkpoint carries its own network definition, which lives in train/.
That tree is only put on the path while the file is unpickled.
"""

import pathlib
import sys

import torch

from aimbot.backends.base import Detector
from aimbot.nms import nms
from aimbot.preprocess import frame_to_cuda, frame_to_numpy
from config import confidence, iou

# Checkpoints saved on Linux store PosixPath; make them loadable on Windows.
pathlib.PosixPath = pathlib.WindowsPath

_TRAIN = pathlib.Path(__file__).resolve().parents[3] / 'train'


def _load(weights):
    """Unpickle a .pt checkpoint straight into a model.

    Works for both YOLOv5 and YOLOv11 checkpoints. A v11 checkpoint pickles
    ultralytics classes, so the `ultralytics` package (train/requirements.txt)
    must be installed; its eval forward returns (y, x) with y shaped
    (1, 4+nc, anchors), which aimbot.nms detects by shape like any export.
    """
    if str(_TRAIN) not in sys.path:
        sys.path.insert(0, str(_TRAIN))
    ckpt = torch.load(weights, map_location='cpu', weights_only=False)
    model = ckpt.get('ema') or ckpt['model']
    return model.float().fuse().eval() if hasattr(model, 'fuse') else model.float().eval()


class TorchDetector(Detector):
    def __init__(self, weights, mouse, headshot_fraction=0.2, speed=2.6):
        super().__init__(mouse, headshot_fraction, speed)
        self.cuda = torch.cuda.is_available()
        self.model = _load(weights)
        if self.cuda:
            self.model = self.model.half().cuda()

    def infer(self, frame):
        if self.cuda:
            im = frame_to_cuda(frame, half=True)
        else:
            im = torch.from_numpy(frame_to_numpy(frame, half=False))
        with torch.no_grad():
            pred = self.model(im)
        if isinstance(pred, (list, tuple)):
            pred = pred[0]
        return nms(pred, confidence, iou, max_det=10)
