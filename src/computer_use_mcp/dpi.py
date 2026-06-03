"""DPI awareness — ctypes only, NO third-party imports.

This module is deliberately dependency-free so it can be imported and called
*before* ``mss`` or ``uiautomation`` are imported. The process must enter
Per-Monitor-DPI-Aware V2 before anything caches a DPI context — that is what
makes mss pixels and UIA ``BoundingRectangle`` values share one physical-pixel
coordinate space (Driver Contract invariant #2). Get this wrong and every
coordinate is off under 125%/150% display scaling.
"""
from __future__ import annotations

import ctypes

# DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 is the documented sentinel -4.
_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

_AWARENESS = {0: "unaware", 1: "system", 2: "per-monitor"}

_mode: str | None = None


def _query_awareness() -> str:
    """Report the DPI awareness actually in effect for this process."""
    try:
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        hproc = k32.GetCurrentProcess()
        shcore = ctypes.windll.shcore
        shcore.GetProcessDpiAwareness.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
        value = ctypes.c_int()
        shcore.GetProcessDpiAwareness(hproc, ctypes.byref(value))
        return _AWARENESS.get(value.value, "unknown")
    except Exception:
        return "unknown"


def enable_dpi_awareness() -> str:
    """Escalate this process to the strongest DPI awareness available, then
    return the awareness actually in effect.

    Tries strongest -> weakest; a weaker call simply no-ops or raises (and is
    swallowed) once a stronger mode is already set. Idempotent and cached, so
    it is safe to call from both the process entrypoint and the driver.
    """
    global _mode
    if _mode is not None:
        return _mode

    user32 = ctypes.windll.user32
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext(_PER_MONITOR_AWARE_V2)
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass

    _mode = _query_awareness()
    return _mode
