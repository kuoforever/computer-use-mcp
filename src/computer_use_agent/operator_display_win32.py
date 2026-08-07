"""Read-only Win32 adapter for the native operator monitor contract."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any

from .operator_display import OperatorDisplayError, OperatorMonitor

_MONITOR_DEFAULTTOPRIMARY = 1
_MDT_EFFECTIVE_DPI = 0
_BASE_DPI = 96


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def configure_operator_monitor_apis(user32: Any, shcore: Any | None = None) -> None:
    """Configure only the read-only Win32 calls used for monitor selection."""

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_MONITORINFO),
    ]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
    if get_dpi_for_window is not None:
        get_dpi_for_window.argtypes = [wintypes.HWND]
        get_dpi_for_window.restype = wintypes.UINT
    get_dpi_for_system = getattr(user32, "GetDpiForSystem", None)
    if get_dpi_for_system is not None:
        get_dpi_for_system.restype = wintypes.UINT
    if shcore is not None:
        get_dpi_for_monitor = getattr(shcore, "GetDpiForMonitor", None)
        if get_dpi_for_monitor is not None:
            get_dpi_for_monitor.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.POINTER(wintypes.UINT),
                ctypes.POINTER(wintypes.UINT),
            ]
            get_dpi_for_monitor.restype = ctypes.c_long


def operator_dpi_for_window(user32: Any, hwnd: int) -> int:
    """Return the selected window's effective DPI with a bounded fallback."""

    get_dpi_for_window = getattr(user32, "GetDpiForWindow", None)
    if get_dpi_for_window is not None and hwnd:
        observed = int(get_dpi_for_window(wintypes.HWND(hwnd)))
        if 48 <= observed <= 768:
            return observed
    get_dpi_for_system = getattr(user32, "GetDpiForSystem", None)
    if get_dpi_for_system is not None:
        observed = int(get_dpi_for_system())
        if 48 <= observed <= 768:
            return observed
    return _BASE_DPI


def operator_dpi_for_monitor(
    user32: Any,
    shcore: Any | None,
    monitor: int,
    hwnd: int,
) -> int:
    """Return effective DPI for the selected monitor, then bounded fallbacks."""

    get_dpi_for_monitor = (
        getattr(shcore, "GetDpiForMonitor", None) if shcore is not None else None
    )
    if get_dpi_for_monitor is not None:
        dpi_x = wintypes.UINT()
        dpi_y = wintypes.UINT()
        result = int(
            get_dpi_for_monitor(
                monitor,
                _MDT_EFFECTIVE_DPI,
                ctypes.byref(dpi_x),
                ctypes.byref(dpi_y),
            )
        )
        if (
            result == 0
            and dpi_x.value == dpi_y.value
            and 48 <= dpi_x.value <= 768
        ):
            return int(dpi_x.value)
    return operator_dpi_for_window(user32, hwnd)


def operator_monitor_for_window(
    user32: Any,
    hwnd: int,
    *,
    shcore: Any | None = None,
) -> OperatorMonitor:
    """Resolve one window to its monitor, or the primary monitor if absent."""

    monitor = user32.MonitorFromWindow(
        wintypes.HWND(hwnd),
        _MONITOR_DEFAULTTOPRIMARY,
    )
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not monitor or not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise OperatorDisplayError("OPERATOR_MONITOR_INFO_FAILED")
    return OperatorMonitor(
        bounds=(
            int(info.rcMonitor.left),
            int(info.rcMonitor.top),
            int(info.rcMonitor.right),
            int(info.rcMonitor.bottom),
        ),
        work_area=(
            int(info.rcWork.left),
            int(info.rcWork.top),
            int(info.rcWork.right),
            int(info.rcWork.bottom),
        ),
        dpi=operator_dpi_for_monitor(user32, shcore, int(monitor), hwnd),
    )


def foreground_operator_monitor(
    user32: Any,
    *,
    shcore: Any | None = None,
) -> OperatorMonitor:
    """Snapshot the current foreground window and its monitor exactly once."""

    foreground = int(user32.GetForegroundWindow() or 0)
    return operator_monitor_for_window(user32, foreground, shcore=shcore)


__all__ = [
    "configure_operator_monitor_apis",
    "foreground_operator_monitor",
    "operator_dpi_for_monitor",
    "operator_dpi_for_window",
    "operator_monitor_for_window",
]
