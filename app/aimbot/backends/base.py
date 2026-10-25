"""Shared detector wiring. Each backend only implements infer()."""

from aimbot.targeting import aim_at, pick


class Detector:
    def __init__(self, mouse, headshot_fraction, speed):
        self.mouse = mouse
        self.headshot_fraction = headshot_fraction
        self.speed = speed

    def aim(self, det, center, classes=None):
        target = pick(det, center, classes)
        if target is not None:
            aim_at(target, center, self.mouse, self.headshot_fraction, self.speed)
