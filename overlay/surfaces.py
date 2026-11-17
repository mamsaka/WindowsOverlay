"""Enumerate ordinary desktop windows whose top edge can hold snow.

Only data gathering lives here: which top-level windows are visible, where
their visible frames are (DWM bounds, so drop shadows and hidden resize
borders are excluded) and whether they are maximized. Z-order is preserved:
the first entry is the topmost window.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Iterable, List, NamedTuple, Optional, Tuple

IS_WINDOWS = sys.platform == "win32"

DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
SW_SHOWMAXIMIZED = 3


class DesktopWindow(NamedTuple):
    """A visible top-level window in z-order (topmost first)."""

    hwnd: int
    left: int
    top: int
    right: int
    bottom: int
    maximized: bool


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", _POINT),
        ("ptMaxPosition", _POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    try:
        _dwmapi: Optional[ctypes.WinDLL] = ctypes.WinDLL("dwmapi")
    except OSError:  # pragma: no cover - ancient Windows
        _dwmapi = None

    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    _user32.EnumWindows.argtypes = (_WNDENUMPROC, wintypes.LPARAM)
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = (wintypes.HWND,)
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = (wintypes.HWND,)
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindowPlacement.argtypes = (wintypes.HWND, ctypes.POINTER(_WINDOWPLACEMENT))
    _user32.GetWindowPlacement.restype = wintypes.BOOL

    if _dwmapi is not None:
        _dwmapi.DwmGetWindowAttribute.argtypes = (
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        )
        _dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long


def _frame_rect(hwnd: int) -> Optional[Tuple[int, int, int, int]]:
    """Visible window bounds (physical pixels) without the drop shadow."""
    rect = wintypes.RECT()
    if _dwmapi is not None:
        result = _dwmapi.DwmGetWindowAttribute(
            hwnd,
            DWMWA_EXTENDED_FRAME_BOUNDS,
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if result == 0:
            return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _is_cloaked(hwnd: int) -> bool:
    """Hidden UWP shells stay "visible" but are not on screen at all."""
    if _dwmapi is None:
        return False
    value = ctypes.c_int(0)
    result = _dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_CLOAKED, ctypes.byref(value), ctypes.sizeof(value)
    )
    return result == 0 and value.value != 0


def _is_maximized(hwnd: int) -> bool:
    placement = _WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(_WINDOWPLACEMENT)
    if not _user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
        return False
    return placement.showCmd == SW_SHOWMAXIMIZED


def list_windows(exclude: Iterable[int] = ()) -> List[DesktopWindow]:
    """Visible top-level windows in z-order, topmost first."""
    if not IS_WINDOWS:
        return []
    skip = {int(hwnd) for hwnd in exclude if hwnd}
    windows: List[DesktopWindow] = []

    def _visit(hwnd: int, _lparam: int) -> bool:
        try:
            if hwnd in skip:
                return True
            if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
                return True
            if _user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
                return True
            if _is_cloaked(hwnd):
                return True
            rect = _frame_rect(hwnd)
            if rect is None or rect[2] <= rect[0] or rect[3] <= rect[1]:
                return True
            windows.append(DesktopWindow(int(hwnd), *rect, _is_maximized(hwnd)))
        except Exception:  # a single odd window must not break enumeration
            return True
        return True

    _user32.EnumWindows(_WNDENUMPROC(_visit), 0)
    return windows
