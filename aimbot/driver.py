"""Logitech GHUB / LGS relative mouse driver.

Relative moves go through logitech.driver.dll, which bypasses win32
SendInput (blocked by some anti-cheat platforms). Requires GHUB or LGS to
be running; otherwise device_open() fails and every move is a no-op.
"""

import ctypes
import os


class LogitechDriver:
    def __init__(self, dll_path=None):
        if dll_path is None:
            dll_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                    'logitech.driver.dll')
        self._ok = False
        try:
            self._driver = ctypes.CDLL(dll_path)
        except OSError:
            print(f'Error, DLL file not found: {dll_path}')
            return
        self._ok = self._driver.device_open() == 1  # one instance per process
        if not self._ok:
            print('Error, GHUB or LGS driver not found')

    @property
    def ok(self):
        return self._ok

    def move(self, x, y):
        """Relative move. Positive x right, positive y down."""
        if not self._ok:
            return
        x, y = int(x), int(y)
        if x == 0 and y == 0:
            return
        self._driver.moveR(x, y, True)
