"""Mouse drivers. config.mouse_driver picks one:

- 'dll'       native/mouse_driver.dll built from native/mouse_driver.c;
  relative SendInput inside C, keeps sub-pixel leftovers, and can raise
  the process timer resolution. Brand-agnostic.
- 'logitech'  GHUB / LGS relative driver (native/logitech.driver.dll), the
  original path; needs Logitech software running.
"""

import ctypes
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from config import dll_timer_ms as _DLL_TIMER_MS
except ImportError:
    _DLL_TIMER_MS = 0


class LogitechDriver:
    def __init__(self, dll_path=None):
        if dll_path is None:
            dll_path = os.path.join(_ROOT, 'native', 'logitech.driver.dll')
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


class DllDriver:
    """Relative moves through native/mouse_driver.dll.

    The DLL sends the same MOUSEEVENTF_MOVE the win32 path used, but the
    call, struct fill and SendInput all stay in C. Deltas are passed as
    floats so the DLL can carry the fractional remainder: the aim loop
    produces sub-pixel corrections that int() would floor to zero.
    """

    def __init__(self, dll_path=None, timer_ms=None):
        if dll_path is None:
            dll_path = os.path.join(_ROOT, 'native', 'mouse_driver.dll')
        if timer_ms is None:
            timer_ms = _DLL_TIMER_MS
        self._lib = None
        self._ok = False
        try:
            self._lib = ctypes.CDLL(dll_path)
        except OSError as e:
            print('Error, DLL file not found: {} ({})'.format(dll_path, e))
            print('Build it with: powershell -ExecutionPolicy Bypass -File scripts\\build_dll.ps1')
            return

        self._move = self._lib.md_move
        self._move.argtypes = (ctypes.c_float, ctypes.c_float)
        self._move.restype = ctypes.c_int

        self._shutdown = self._lib.md_shutdown
        self._shutdown.argtypes = ()
        self._shutdown.restype = None

        self._set_timer = self._lib.md_set_timer_resolution
        self._set_timer.argtypes = (ctypes.c_uint,)
        self._set_timer.restype = ctypes.c_int

        self._ok = self._lib.md_init() == 1
        if not self._ok:
            print('Error, mouse_driver.dll md_init failed')
            return
        if timer_ms:
            self._set_timer(int(timer_ms))

    @property
    def ok(self):
        return self._ok

    def move(self, x, y):
        """Relative move. Positive x right, positive y down."""
        if not self._ok:
            return
        if x or y:
            self._move(float(x), float(y))

    def close(self):
        if self._lib is not None:
            self._shutdown()
            self._lib = None
        self._ok = False


def create_driver(name):
    """Mouse driver factory, driven by config.mouse_driver."""
    if name == 'dll':
        return DllDriver()
    if name == 'logitech':
        return LogitechDriver()
    raise SystemExit("unknown mouse_driver: '{}' (dll | logitech)".format(name))
