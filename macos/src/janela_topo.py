import sys
import ctypes

try:
    from ctypes import wintypes
except Exception:
    wintypes = None

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 8
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 1, 2, 16, 64


def fixar_no_topo(hwnd):
    if sys.platform == 'darwin' or not hasattr(ctypes, 'WinDLL'):
        return True
    u = ctypes.WinDLL('user32')
    u.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    u.SetWindowPos.restype = wintypes.BOOL
    return bool(u.SetWindowPos(
        hwnd,
        wintypes.HWND(-1),
        0, 0, 0, 0,
        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    ))


def tem_topmost(hwnd):
    if sys.platform == 'darwin' or not hasattr(ctypes, 'windll'):
        return True
    return bool(ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST)
