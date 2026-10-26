"""Mouse drivers. config.mouse_driver picks one:

- 'logitech'  GHUB / LGS relative driver (logitech.driver.dll), the
  original path; needs Logitech software running.
- 'sendinput' win32 relative injection; brand-agnostic, no vendor
  software, works with any mouse.
"""

import ctypes
import os

import win32api
import win32con

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


class SendInputDriver:
    """Relative moves through win32 mouse_event. Works with every mouse."""

    _MOVE = win32con.MOUSEEVENTF_MOVE

    def __init__(self):
        self._move_event = win32api.mouse_event
        self._ok = True

    @property
    def ok(self):
        return self._ok

    def move(self, x, y):
        """Relative move. Positive x right, positive y down."""
        ix, iy = int(x), int(y)
        if ix or iy:
            self._move_event(self._MOVE, ix, iy, 0, 0)


def create_driver(name):
    """Mouse driver factory, driven by config.mouse_driver."""
    if name == 'logitech':
        return LogitechDriver()
    if name == 'sendinput':
        return SendInputDriver()
    raise SystemExit("unknown mouse_driver: '{}' (logitech | sendinput)".format(name))
