"""Thin Win32 helpers: global hotkeys, click-through, mouse button state."""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes
from typing import Callable, Dict

from PyQt6.QtCore import QAbstractNativeEventFilter

LOGGER = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
VK_Q = 0x51
VK_X = 0x58
VK_LBUTTON = 0x01

HOTKEY_ID_QUIT = 1
HOTKEY_ID_CLICK_THROUGH = 2

GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080

if IS_WINDOWS:
    _user32 = ctypes.WinDLL("user32", use_last_error=True)

    _user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
    _user32.UnregisterHotKey.restype = wintypes.BOOL

    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _get_ex_style = _user32.GetWindowLongPtrW
        _set_ex_style = _user32.SetWindowLongPtrW
    else:
        _get_ex_style = _user32.GetWindowLongW
        _set_ex_style = _user32.SetWindowLongW
    _get_ex_style.argtypes = (wintypes.HWND, ctypes.c_int)
    _get_ex_style.restype = ctypes.c_ssize_t
    _set_ex_style.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t)
    _set_ex_style.restype = ctypes.c_ssize_t

    _user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    _user32.GetAsyncKeyState.restype = ctypes.c_short


def register_hotkey(hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
    if not IS_WINDOWS:
        return False
    if _user32.RegisterHotKey(hwnd, hotkey_id, modifiers | MOD_NOREPEAT, vk):
        return True
    LOGGER.warning(
        "Не удалось зарегистрировать hotkey %s (ошибка Windows: %s)",
        hotkey_id,
        ctypes.get_last_error(),
    )
    return False


def unregister_hotkey(hwnd: int, hotkey_id: int) -> None:
    if IS_WINDOWS:
        _user32.UnregisterHotKey(hwnd, hotkey_id)


def left_button_down() -> bool:
    """True while the left mouse button is physically held (global)."""
    if not IS_WINDOWS:
        return False
    return bool(_user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)


def set_click_through(hwnd: int, enabled: bool) -> None:
    """Let mouse input pass through the whole window to what lies beneath."""
    if not IS_WINDOWS:
        return
    style = _get_ex_style(hwnd, GWL_EXSTYLE)
    style |= WS_EX_LAYERED | WS_EX_TOOLWINDOW
    style = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
    _set_ex_style(hwnd, GWL_EXSTYLE, style)


class HotkeyFilter(QAbstractNativeEventFilter):
    """Route registered global hotkeys to their callbacks by id."""

    def __init__(self, callbacks: Dict[int, Callable[[], None]]) -> None:
        super().__init__()
        self._callbacks = dict(callbacks)

    def nativeEventFilter(self, event_type, message):
        if event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam in self._callbacks:
                self._callbacks[msg.wParam]()
                return True, 0
        return False, 0
