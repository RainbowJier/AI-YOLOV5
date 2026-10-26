"""Shared detector wiring. Each backend only implements infer()."""

from aimbot.targeting import aim_at, closest, pick


class Detector:
    def __init__(self, mouse, headshot_fraction, speed):
        self.mouse = mouse
        self.headshot_fraction = headshot_fraction
        self.speed = speed

    def aim(self, det, center):
        """Aim at the best box and return the host rows for visuals.

        One D2H per frame: pick() transfers the NMS output once, the team
        filter and the closest-box pick run on the host, and the returned
        rows feed the preview without a second device sync.
        """
        rows = pick(det)
        if rows is not None:
            target = closest(rows, center)
            if target is not None:
                aim_at(target, center, self.mouse, self.headshot_fraction, self.speed)
        return rows
