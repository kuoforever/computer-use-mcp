from __future__ import annotations

import pytest

from computer_use_mcp.drivers.windows import WindowsDriver
from computer_use_mcp.interaction_feedback import resolve_interaction_pacing


class _Feedback:
    def __init__(self) -> None:
        self.events: list[tuple[str, str] | tuple[str]] = []
        self.progress: list[tuple[int, float]] = []

    def show_pointer(self, x: int, y: int, *, action: str) -> None:
        self.events.append(("pointer", action))

    def show_keyboard(
        self,
        *,
        action: str,
        total_units: int = 0,
        estimated_seconds: float = 0.0,
    ) -> None:
        self.events.append(("keyboard", action))
        self.progress.append((total_units, estimated_seconds))

    def clear(self) -> None:
        self.events.append(("clear",))


class _PointerApi:
    def __init__(self) -> None:
        self.positions: list[tuple[int, int]] = []

    def GetCursorPos(self, pointer: object) -> bool:
        pointer._obj.x = 2  # type: ignore[attr-defined]
        pointer._obj.y = 4  # type: ignore[attr-defined]
        return True

    def SetCursorPos(self, x: int, y: int) -> bool:
        self.positions.append((x, y))
        return True


def test_keyboard_typing_uses_the_configured_visible_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, float, float]] = []
    monkeypatch.setattr(
        "computer_use_mcp.drivers.windows.auto.SendKeys",
        lambda text, *, interval, waitTime: calls.append(
            (text, interval, waitTime)
        ),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.035
    driver._typing_interval = 0.035

    result = driver.type("visible")

    assert result.ok
    assert calls == [("visible", 0.035, 0.0)]


def test_unset_profile_preserves_uiautomation_native_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, float]] = []
    monkeypatch.setattr(
        "computer_use_mcp.drivers.windows.auto.SendKeys",
        lambda text, *, waitTime: calls.append((text, waitTime)),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.0
    driver._typing_interval = None

    result = driver.type("native")

    assert result.ok
    assert calls == [("native", 0.0)]


def test_keyboard_feedback_never_receives_typed_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feedback = _Feedback()
    sleeps: list[float] = []
    monkeypatch.setattr(
        "computer_use_mcp.drivers.windows.auto.SendKeys",
        lambda _text, *, interval, waitTime: None,
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.025
    driver._typing_interval = 0.025
    driver._pacing = resolve_interaction_pacing("normal")
    driver._action_feedback = feedback
    driver._sleep = sleeps.append

    result = driver.type("never show this secret")

    assert result.ok
    assert feedback.events == [("keyboard", "typing"), ("clear",)]
    assert feedback.progress == [(len("never show this secret"), 0.55)]
    assert sleeps == [0.04, 0.08]
    assert "secret" not in repr(feedback.events)


def test_speed_profile_supplies_typing_delay_unless_explicitly_overridden() -> None:
    profiled = WindowsDriver(interaction_speed="normal")
    overridden = WindowsDriver(
        interaction_speed="normal",
        type_wait_seconds=0.035,
    )

    assert profiled._type_wait_seconds == 0.025
    assert overridden._type_wait_seconds == 0.035


def test_pointer_profile_animates_to_the_target_and_pauses_before_action() -> None:
    feedback = _Feedback()
    api = _PointerApi()
    sleeps: list[float] = []
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._pacing = resolve_interaction_pacing("normal")
    driver._action_feedback = feedback
    driver._sleep = sleeps.append

    driver._move_pointer(api, 32, 16, "click")

    assert api.positions[-1] == (32, 16)
    assert feedback.events[-1] == ("pointer", "click")
    assert len(api.positions) == 11
    assert sleeps[-1] == 0.04


@pytest.mark.parametrize("value", [-0.01, 0.101, float("inf"), True])
def test_keyboard_typing_delay_is_bounded(value: object) -> None:
    with pytest.raises(ValueError, match="between 0 and 0.1"):
        WindowsDriver(type_wait_seconds=value)  # type: ignore[arg-type]


def test_page_navigation_keys_have_standard_windows_virtual_key_codes() -> None:
    assert WindowsDriver._vk("PageUp") == 0x21
    assert WindowsDriver._vk("PageDown") == 0x22
