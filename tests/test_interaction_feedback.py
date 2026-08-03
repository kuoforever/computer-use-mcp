from __future__ import annotations

import pytest

from computer_use_mcp.interaction_feedback import resolve_interaction_pacing
from computer_use_mcp.interaction_feedback_win32 import Win32ActionFeedback


class _CaretApi:
    def GetForegroundWindow(self) -> int:
        return 10

    def GetWindowThreadProcessId(self, hwnd: int, process_id: object) -> int:
        return 20

    def GetGUIThreadInfo(self, thread_id: int, pointer: object) -> bool:
        pointer._obj.hwndCaret = 30  # type: ignore[attr-defined]
        pointer._obj.rcCaret.left = 12  # type: ignore[attr-defined]
        pointer._obj.rcCaret.bottom = 18  # type: ignore[attr-defined]
        return True

    def ClientToScreen(self, hwnd: int, pointer: object) -> bool:
        pointer._obj.x += 100  # type: ignore[attr-defined]
        pointer._obj.y += 200  # type: ignore[attr-defined]
        return True


class _FallbackApi(_CaretApi):
    def GetGUIThreadInfo(self, thread_id: int, pointer: object) -> bool:
        return False

    def GetCursorPos(self, pointer: object) -> bool:
        pointer._obj.x = 44  # type: ignore[attr-defined]
        pointer._obj.y = 55  # type: ignore[attr-defined]
        return True


def test_interaction_speed_profiles_are_bounded_and_ordered() -> None:
    fast = resolve_interaction_pacing("fast")
    normal = resolve_interaction_pacing("NORMAL")
    deliberate = resolve_interaction_pacing(" deliberate ")

    assert fast is not None and normal is not None and deliberate is not None
    assert fast.pointer_move_ms < normal.pointer_move_ms < deliberate.pointer_move_ms
    assert fast.type_wait_seconds < normal.type_wait_seconds < deliberate.type_wait_seconds
    assert deliberate.type_wait_seconds <= 0.1


def test_unset_interaction_speed_preserves_native_driver_timing() -> None:
    assert resolve_interaction_pacing(None) is None
    assert resolve_interaction_pacing("") is None


def test_unknown_interaction_speed_never_silently_falls_back() -> None:
    with pytest.raises(ValueError, match="fast, normal, deliberate"):
        resolve_interaction_pacing("turbo")


def test_keyboard_feedback_anchors_to_native_caret_geometry() -> None:
    feedback = Win32ActionFeedback.__new__(Win32ActionFeedback)
    feedback._user32 = _CaretApi()
    feedback._width = 1920
    feedback._height = 1080

    assert feedback._keyboard_anchor() == (112, 218, "caret")


def test_keyboard_feedback_uses_pointer_only_when_no_native_caret_exists() -> None:
    feedback = Win32ActionFeedback.__new__(Win32ActionFeedback)
    feedback._user32 = _FallbackApi()
    feedback._width = 1920
    feedback._height = 1080

    assert feedback._keyboard_anchor() == (44, 55, "pointer_fallback")
