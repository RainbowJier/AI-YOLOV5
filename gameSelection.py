"""Backward-compatible wrapper. The implementation moved to aimbot.capture.

Kept so older scripts importing gameSelection still work. New code should
call aimbot.capture.game_selection(), which returns (camera, c_width, c_height).
"""

from aimbot.capture import game_selection


def gameSelection():
    """Old name. Returns (camera, c_width, c_height, None)."""
    selected = game_selection()
    if selected is None:
        return None
    camera, c_width, c_height = selected
    return camera, c_width, c_height, None
