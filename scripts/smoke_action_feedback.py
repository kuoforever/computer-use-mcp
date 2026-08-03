"""Live probe for the passive, capture-excluded action feedback overlay."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from computer_use_mcp.interaction_feedback_win32 import (  # noqa: E402
    Win32ActionFeedback,
)

_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_WDA_EXCLUDEFROMCAPTURE = 0x00000011


def main() -> int:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    foreground_before = int(user32.GetForegroundWindow() or 0)
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        raise OSError("GetCursorPos failed")
    feedback = Win32ActionFeedback()
    try:
        feedback.show_pointer(int(point.x), int(point.y), action="click")
        time.sleep(0.8)
        feedback.pump()
        pointer_state = feedback.state
        pointer_visible = bool(user32.IsWindowVisible(wintypes.HWND(feedback.hwnd)))
        pending_rect = wintypes.RECT()
        pointer_painted = not bool(
            user32.GetUpdateRect(
                wintypes.HWND(feedback.hwnd),
                ctypes.byref(pending_rect),
                False,
            )
        )
        feedback.show_keyboard(
            action="typing",
            total_units=40,
            estimated_seconds=1.2,
        )
        time.sleep(0.25)
        progress_first = feedback.typing_progress
        time.sleep(0.35)
        feedback.pump()
        progress_second = feedback.typing_progress
        keyboard_state = feedback.state
        keyboard_visible = bool(user32.IsWindowVisible(wintypes.HWND(feedback.hwnd)))
        affinity = wintypes.DWORD()
        affinity_ok = bool(
            user32.GetWindowDisplayAffinity(
                wintypes.HWND(feedback.hwnd), ctypes.byref(affinity)
            )
        )
        ex_style = int(user32.GetWindowLongPtrW(feedback.hwnd, _GWL_EXSTYLE))
        foreground_after = int(user32.GetForegroundWindow() or 0)
        required_style = (
            _WS_EX_TRANSPARENT
            | _WS_EX_TOOLWINDOW
            | _WS_EX_LAYERED
            | _WS_EX_NOACTIVATE
        )
        report = {
            "capture_excluded": affinity_ok
            and int(affinity.value) == _WDA_EXCLUDEFROMCAPTURE,
            "click_through_nonactivating": (ex_style & required_style)
            == required_style,
            "foreground_preserved": foreground_before == foreground_after,
            "keyboard_state": keyboard_state,
            "keyboard_visible": keyboard_visible,
            "pointer_painted": pointer_painted,
            "pointer_state": pointer_state,
            "pointer_visible": pointer_visible,
            "typing_progress_advanced": 0 < progress_first < progress_second < 100,
            "typing_anchor_source": feedback.typing_anchor_source,
        }
        print(json.dumps(report, sort_keys=True))
        return 0 if all(
            value
            for key, value in report.items()
            if key
            in {
                "capture_excluded",
                "click_through_nonactivating",
                "foreground_preserved",
                "keyboard_visible",
                "pointer_painted",
                "pointer_visible",
                "typing_progress_advanced",
            }
        ) else 1
    finally:
        feedback.close()


if __name__ == "__main__":
    raise SystemExit(main())
