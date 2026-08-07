"""Noninteractive Windows notification delivery for local approval attention.

The tray notification carries fixed product wording only.  It has no click
handler, action button, approval callback, provider port, desktop port, or task
state authority.  The bound Decision Card remains the only approval surface.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from .approval_inbox import ApprovalNotice
from .win32_dll import private_windll


_NIM_ADD = 0x00000000
_NIM_DELETE = 0x00000002
_NIM_SETVERSION = 0x00000004
_NIF_MESSAGE = 0x00000001
_NIF_ICON = 0x00000002
_NIF_TIP = 0x00000004
_NIF_INFO = 0x00000010
_NIIF_INFO = 0x00000001
_NIIF_RESPECT_QUIET_TIME = 0x00000080
_NOTIFYICON_VERSION_4 = 4
_WM_APP = 0x8000
_CALLBACK_MESSAGE = _WM_APP + 0x159
_ICON_ID = 0x474441  # "GDA"; one active local approval per Runner.
_IDI_INFORMATION = 32516
_HOST_CLASS = "STATIC"
_HOST_NAME = "Guarded Desktop Agent notification host"


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", _GUID),
        ("hBalloonIcon", wintypes.HICON),
    ]


class Win32ApprovalNotifier:
    """Show one fixed-content Windows tray notification until withdrawn."""

    def __init__(
        self,
        *,
        shell32: Any | None = None,
        user32: Any | None = None,
    ) -> None:
        self._shell32: Any = shell32 if shell32 is not None else private_windll("shell32")
        self._user32: Any = user32 if user32 is not None else private_windll("user32")
        self._active_notice_id: str | None = None
        self._active_data: _NOTIFYICONDATAW | None = None
        self._active_hwnd: int | None = None
        # Prototypes are configured per handle, so injecting one test double
        # cannot leave the other real library with ctypes' default int return
        # type -- which would truncate a 64-bit HWND.
        if user32 is None:
            self._configure_user32()
        if shell32 is None:
            self._configure_shell32()

    def _configure_user32(self) -> None:
        self._user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.DestroyWindow.restype = wintypes.BOOL
        self._user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        self._user32.LoadIconW.restype = wintypes.HICON

    def _configure_shell32(self) -> None:
        self._shell32.Shell_NotifyIconW.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(_NOTIFYICONDATAW),
        ]
        self._shell32.Shell_NotifyIconW.restype = wintypes.BOOL

    @staticmethod
    def _icon_resource(identifier: int) -> wintypes.LPCWSTR:
        return ctypes.cast(ctypes.c_void_p(identifier), wintypes.LPCWSTR)

    def show(self, notice: ApprovalNotice) -> None:
        if not isinstance(notice, ApprovalNotice):
            raise ValueError("notice must be an ApprovalNotice")
        if self._active_notice_id is not None:
            self.withdraw(self._active_notice_id)
        hwnd = int(
            self._user32.CreateWindowExW(
                0,
                _HOST_CLASS,
                _HOST_NAME,
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                None,
                None,
            )
            or 0
        )
        if not hwnd:
            raise OSError("APPROVAL_NOTIFICATION_HOST_UNAVAILABLE")
        icon = int(
            self._user32.LoadIconW(None, self._icon_resource(_IDI_INFORMATION)) or 0
        )
        if not icon:
            self._user32.DestroyWindow(hwnd)
            raise OSError("APPROVAL_NOTIFICATION_ICON_UNAVAILABLE")
        data = _NOTIFYICONDATAW()
        data.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        data.hWnd = hwnd
        data.uID = _ICON_ID
        data.uFlags = _NIF_MESSAGE | _NIF_ICON | _NIF_TIP | _NIF_INFO
        data.uCallbackMessage = _CALLBACK_MESSAGE
        data.hIcon = icon
        data.szTip = notice.title
        data.szInfo = notice.body
        data.szInfoTitle = notice.title
        data.dwInfoFlags = _NIIF_INFO | _NIIF_RESPECT_QUIET_TIME
        if not self._shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(data)):
            self._user32.DestroyWindow(hwnd)
            raise OSError("APPROVAL_NOTIFICATION_SHOW_FAILED")
        data.uVersion = _NOTIFYICON_VERSION_4
        if not self._shell32.Shell_NotifyIconW(_NIM_SETVERSION, ctypes.byref(data)):
            self._shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(data))
            self._user32.DestroyWindow(hwnd)
            raise OSError("APPROVAL_NOTIFICATION_VERSION_FAILED")
        self._active_notice_id = notice.notice_id
        self._active_data = data
        self._active_hwnd = hwnd

    def withdraw(self, notice_id: str) -> None:
        if (
            notice_id != self._active_notice_id
            or self._active_data is None
            or self._active_hwnd is None
        ):
            return
        data = self._active_data
        hwnd = self._active_hwnd
        self._active_notice_id = None
        self._active_data = None
        self._active_hwnd = None
        deleted = bool(
            self._shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(data))
        )
        destroyed = bool(self._user32.DestroyWindow(hwnd))
        if not deleted:
            raise OSError("APPROVAL_NOTIFICATION_WITHDRAW_FAILED")
        if not destroyed:
            raise OSError("APPROVAL_NOTIFICATION_HOST_DESTROY_FAILED")


__all__ = ["Win32ApprovalNotifier"]
