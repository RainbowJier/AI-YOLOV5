"""PyTorch backend. Loads a local .pt checkpoint through hubconf.py."""

import pathlib

import torch

from aimbot.targeting import aim_at, boxes_from_nms, select_target
from config import confidence, iou, screenShotHeight
from utils.general import non_max_suppression

# Checkpoints saved on Linux store PosixPath; make them loadable on Windows.
pathlib.PosixPath = pathlib.WindowsPath


class TorchDetector:
    def __init__(self, weights, mouse, headshot_fraction=0.2, speed=2.6):
        self.mouse = mouse
        self.headshot_fraction = headshot_fraction
        self.speed = speed
        self.cuda = torch.cuda.is_available()
        self.model = torch.hub.load('.', 'custom', source='local', path=weights, force_reload=True)
        if self.cuda:
            self.model.half()

    def infer(self, frame):
        im = torch.from_numpy(frame)
        if im.shape[2] == 4:
            im = im[:, :, :3]
        im = im.permute(2, 0, 1).unsqueeze(0)
        if self.cuda:
            im = im.to('cuda', non_blocking=True).half()
        im = im.float().div_(255) if not self.cuda else im.div_(255)
        with torch.no_grad():
            results = self.model(im, size=screenShotHeight)
            pred = non_max_suppression(results, confidence, iou, [0, 1, 2, 3], False, max_det=30)
        return boxes_from_nms(pred[0], im.shape)

    def aim(self, boxes, center):
        target = select_target(boxes, center)
        if target is not None:
            aim_at(target, center, self.mouse, self.headshot_fraction, self.speed)
