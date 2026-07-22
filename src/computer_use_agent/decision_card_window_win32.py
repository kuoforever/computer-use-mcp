"""ctypes Win32 backend for the focus-taking local Decision Card."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from computer_use_mcp.dpi import enable_dpi_awareness

from .decision_card_window import DecisionCardButton

_MB_YESNOCANCEL = 0x00000003
_MB_ICONWARNING = 0x00000030
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000
_IDYES = 6
_IDNO = 7


class Win32DecisionCardWindowApi:
    """Show one timed modal card; cancel, close, and timeout select nothing.

    The first interactive release intentionally supports two options. Windows'
    standard Yes and No controls are mapped explicitly in the content to the
    two fixed option titles; Cancel is reserved for fail-closed dismissal.
    """

    def __init__(self) -> None:
        enable_dpi_awareness()
        self._user32 = ctypes.windll.user32
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

    def choose(
        self,
        *,
        title: str,
        instruction: str,
        content: str,
        buttons: tuple[DecisionCardButton, ...],
        timeout_seconds: int,
    ) -> str | None:
        if len(buttons) != 2:
            raise OSError("DECISION_CARD_NATIVE_REQUIRES_TWO_OPTIONS")
        message = (
            f"{instruction}\n\n{content}\n\n"
            f"Yes — {buttons[0].label}\n"
            f"No — {buttons[1].label}\n"
            "Cancel / close / timeout — deny without selection"
        )
        message_box_timeout = getattr(self._user32, "MessageBoxTimeoutW", None)
        if message_box_timeout is None:
            raise OSError("DECISION_CARD_NATIVE_TIMEOUT_UNAVAILABLE")
        message_box_timeout.restype = ctypes.c_int
        message_box_timeout.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.UINT,
            wintypes.WORD,
            wintypes.DWORD,
        ]
        foreground_before = self._user32.GetForegroundWindow()
        try:
            selected = int(
                message_box_timeout(
                    foreground_before,
                    message,
                    title,
                    _MB_YESNOCANCEL
                    | _MB_ICONWARNING
                    | _MB_SETFOREGROUND
                    | _MB_TOPMOST,
                    0,
                    timeout_seconds * 1000,
                )
            )
        finally:
            if foreground_before and self._user32.IsWindow(foreground_before):
                self._user32.SetForegroundWindow(foreground_before)
        if selected == _IDYES:
            return buttons[0].option_id
        if selected == _IDNO:
            return buttons[1].option_id
        return None


__all__ = ["Win32DecisionCardWindowApi"]
