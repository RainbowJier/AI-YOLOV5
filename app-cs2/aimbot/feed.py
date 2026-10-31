"""Latest-frame slot from the aim loop to the tuner UI's embedded feed.

The loop publishes (producer, the aim thread); the UI takes (consumer,
its own thread). One slot, latest wins: a stalled UI never blocks the
loop, and the UI always renders the freshest drawn frame.
"""

_latest = None


def publish(frame):
    """Store a private copy of the drawn frame. bettercam hands out views
    into its ring buffer, which the next grab overwrites."""
    global _latest
    _latest = frame.copy()


def take():
    """Pop the latest frame, or None if nothing new was published."""
    global _latest
    frame, _latest = _latest, None
    return frame
