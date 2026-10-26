"""Shared detector wiring. Each backend only implements infer()."""

import torch

from aimbot.targeting import CLASS_IDS, aim_at, pick


class Detector:
    def __init__(self, mouse, headshot_fraction, speed):
        self.mouse = mouse
        self.headshot_fraction = headshot_fraction
        self.speed = speed

    def aim(self, det, center):
        # The config.CT / config.T team filter, enforced on every backend.
        ids = torch.tensor(CLASS_IDS, device=det.device, dtype=det.dtype).view(1, -1)
        target = pick(det, center, ids)
        if target is not None:
            aim_at(target, center, self.mouse, self.headshot_fraction, self.speed)
