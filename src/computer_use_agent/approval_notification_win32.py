"""No-authority Windows notification delivery for local approval attention.

The notification carries fixed product wording only.  It has no action button,
approval callback, provider port, desktop port, or task-state authority.  A
whole-toast activation reaches only the modern transport's inert sink; the
bound Decision Card remains the only approval surface.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Protocol

from .approval_inbox import ApprovalNotice
from .approval_notification_toast_win32 import ModernToastApprovalNotifier
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


class _NotificationPort(Protocol):
    def show(self, notice: ApprovalNotice) -> None: ...

    def withdraw(self, notice_id: str) -> None: ...


class _LegacyWin32ApprovalNotifier:
    """Show one fixed-content legacy tray notification until withdrawn."""

    def __init__(
        self,
        *,
        shell32: Any | None = None,
        user32: Any | None = None,
    ) -> None:
        injected = shell32 is not None or user32 is not None
        self._shell32: Any = shell32 if shell32 is not None else private_windll("shell32")
        self._user32: Any = user32 if user32 is not None else private_windll("user32")
        self._active_notice_id: str | None = None
        self._active_data: _NOTIFYICONDATAW | None = None
        self._active_hwnd: int | None = None
        if not injected:
            self._configure_prototypes()

    def _configure_prototypes(self) -> None:
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


class Win32ApprovalNotifier:
    """Prefer identity-backed toasts and retain legacy banner fallback."""

    def __init__(
        self,
        *,
        shell32: Any | None = None,
        user32: Any | None = None,
        modern: _NotificationPort | None = None,
    ) -> None:
        injected_legacy = shell32 is not None or user32 is not None
        self._legacy = _LegacyWin32ApprovalNotifier(
            shell32=shell32,
            user32=user32,
        )
        self._modern: _NotificationPort | None = (
            modern
            if modern is not None
            else (None if injected_legacy else ModernToastApprovalNotifier())
        )
        self._active_notice_id: str | None = None
        self._active_delivery: str | None = None

    @property
    def delivery_kind(self) -> str | None:
        return self._active_delivery

    @property
    def _active_hwnd(self) -> int | None:
        return self._legacy._active_hwnd

    def show(self, notice: ApprovalNotice) -> None:
        if not isinstance(notice, ApprovalNotice):
            raise ValueError("notice must be an ApprovalNotice")
        if self._active_notice_id is not None:
            self.withdraw(self._active_notice_id)
        if self._modern is not None:
            try:
                self._modern.show(notice)
            except Exception:
                # Notification transport is presentation-only.  A modern
                # registration/runtime failure may degrade to the existing
                # fixed-content banner, but cannot affect approval authority.
                pass
            else:
                self._active_notice_id = notice.notice_id
                self._active_delivery = "modern"
                return
        self._legacy.show(notice)
        self._active_notice_id = notice.notice_id
        self._active_delivery = "legacy"

    def withdraw(self, notice_id: str) -> None:
        if notice_id != self._active_notice_id or self._active_delivery is None:
            return
        delivery = self._active_delivery
        self._active_notice_id = None
        self._active_delivery = None
        if delivery == "modern":
            assert self._modern is not None
            self._modern.withdraw(notice_id)
            return
        self._legacy.withdraw(notice_id)


__all__ = ["Win32ApprovalNotifier"]
