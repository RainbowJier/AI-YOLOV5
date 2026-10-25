"""Logitech GHUB / LGS relative mouse driver.

Relative moves go through logitech.driver.dll, which bypasses win32
SendInput. Requires GHUB or LGS to be running; otherwise device_open()
fails and every move is a no-op.
"""

import ctypes
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class LogitechDriver:
    def __init__(self, dll_path=None):
        if dll_path is None:
            dll_path = os.path.join(_ROOT, 'logitech.driver.dll')
        self._ok = False
        try:
            self._driver = ctypes.CDLL(dll_path)
        except OSError:
            print('Error, DLL file not found: {}'.format(dll_path))
            return
        self._move = self._driver.moveR
        self._move.argtypes = (ctypes.c_int, ctypes.c_int, ctypes.c_bool)
        self._ok = self._driver.device_open() == 1
        if not self._ok:
            print('Error, GHUB or LGS driver not found')

    @property
    def ok(self):
        return self._ok

    def move(self, x, y):
        """Relative move. Positive x right, positive y down."""
        if not self._ok:
            return
        ix, iy = int(x), int(y)
        if ix or iy:
            self._move(ix, iy, True)
