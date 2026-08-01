"""Operator-approved live smoke for the passive desktop presence halo.

This probe opens the real ctypes surface on the primary display, changes only
its own window, and verifies non-activation, click-through hit testing, capture
affinity, DPI geometry, animation/reduced-motion behavior, and immediate E-stop
and authority-release teardown. It discards the result if local input occurs.
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_agent.presence import (  # noqa: E402
    DesktopAuthority,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
)
from computer_use_agent.presence_window import (  # noqa: E402
    PRESENCE_EX_STYLE,
    PassivePresenceWindow,
    presence_geometry,
)
from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi  # noqa: E402

_GWL_EXSTYLE = -20
_WM_NCHITTEST = 0x0084
_WM_MOUSEACTIVATE = 0x0021
_HTTRANSPARENT = -1
_MA_NOACTIVATE = 3
_WDA_EXCLUDEFROMCAPTURE = 0x11


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _snapshot(
    phase: PresencePhase,
    authority: DesktopAuthority = DesktopAuthority.HELD,
    **over,
) -> PresenceSnapshot:
    return PresenceSnapshot(phase, authority, **over)


def main() -> int:
    user32 = ctypes.windll.user32
    api = Win32PresenceWindowApi()
    window = PassivePresenceWindow(api)
    foreground_before = api.foreground()
    tick_before = _last_input_tick()
    problems: list[str] = []

    opened = window.sync(_snapshot(PresencePhase.OBSERVING))
    api.pump()
    hwnd = window.hwnd
    if hwnd is None:
        print("RESULT: FAIL (presence window did not open)")
        return 1

    user32.GetWindowLongPtrW.restype = ctypes.c_longlong
    observed_style = int(user32.GetWindowLongPtrW(wintypes.HWND(hwnd), _GWL_EXSTYLE))
    if observed_style & PRESENCE_EX_STYLE != PRESENCE_EX_STYLE:
        problems.append("native extended styles lost click-through or non-activation flags")

    user32.SendMessageW.restype = ctypes.c_longlong
    hit = int(user32.SendMessageW(wintypes.HWND(hwnd), _WM_NCHITTEST, 0, 0))
    mouse_activate = int(
        user32.SendMessageW(wintypes.HWND(hwnd), _WM_MOUSEACTIVATE, 0, 0)
    )
    if hit != _HTTRANSPARENT or mouse_activate != _MA_NOACTIVATE:
        problems.append(f"hit testing was not transparent ({hit}, {mouse_activate})")

    affinity = wintypes.DWORD()
    got_affinity = bool(
        user32.GetWindowDisplayAffinity(wintypes.HWND(hwnd), ctypes.byref(affinity))
    )
    if not opened.capture_excluded or not got_affinity or affinity.value != _WDA_EXCLUDEFROMCAPTURE:
        problems.append("Windows did not retain WDA_EXCLUDEFROMCAPTURE")

    executing = window.sync(_snapshot(PresencePhase.EXECUTING))
    time.sleep(0.35)
    api.pump()
    if not executing.changed or api.animation_frame(hwnd) == 0:
        problems.append("executing animation timer did not advance")

    reduced = window.sync(
        _snapshot(
            PresencePhase.EXECUTING,
            preferences=PresencePreferences(reduced_motion=True, high_contrast=True),
        )
    )
    api.pump()
    state = api.state(hwnd)
    if state is None:
        problems.append("redaction-safe paint state disappeared")
    else:
        view, geometry = state
        bounds = api.display_bounds()
        if (
            not reduced.changed
            or view.animation_interval_ms is not None
            or view.color_rgb != 0xFFFFFF
        ):
            problems.append("reduced-motion/high-contrast projection was not applied")
        # Compare against the reviewed contract rather than a restated formula.
        # This check previously duplicated the border expression, so when the
        # halo border was widened the probe kept asserting the old value and
        # nobody noticed, because it was never run afterwards.
        expected = presence_geometry(bounds)
        if geometry != expected:
            problems.append(
                "primary-display DPI geometry was inconsistent: "
                f"observed {geometry}, contract {expected}"
            )

    estopped = window.sync(
        _snapshot(PresencePhase.EXECUTING, estop_engaged=True)
    )
    api.pump()
    if estopped.visible or window.hwnd is not None or user32.IsWindow(wintypes.HWND(hwnd)):
        problems.append("E-stop did not immediately destroy the indicator")

    reopened = window.sync(_snapshot(PresencePhase.WAITING_APPROVAL))
    api.pump()
    released = window.sync(
        _snapshot(PresencePhase.PAUSED, DesktopAuthority.RELEASED)
    )
    api.pump()
    if not reopened.visible or released.visible or window.hwnd is not None:
        problems.append("authority release did not tear down a reopened indicator")

    foreground_after = api.foreground()
    tick_after = _last_input_tick()
    if foreground_after != foreground_before:
        problems.append(
            f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
        )
    if tick_after != tick_before:
        print("RESULT: INCONCLUSIVE (local input occurred during the probe)")
        return 2
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; "
        "HTTRANSPARENT + MA_NOACTIVATE; capture affinity 0x11; "
        "DPI geometry valid; animation advanced and reduced motion stopped it; "
        "E-stop and authority release destroyed the halo)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
