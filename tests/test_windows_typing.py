from __future__ import annotations

import ctypes
from contextlib import contextmanager

import pytest

from computer_use_mcp.drivers import windows as windows_driver_module
from computer_use_mcp.drivers.windows import WindowsDriver
from computer_use_mcp.interaction_feedback import resolve_interaction_pacing
from computer_use_mcp.native_authority import NativeActionBoundary, NativeAuthorityLost


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


def _allow() -> tuple[bool, str]:
    return True, ""


@contextmanager
def _authorized(driver: WindowsDriver):
    boundary = NativeActionBoundary()
    driver.bind_native_action_boundary(boundary)
    with boundary.call_scope(_allow, _allow):
        yield


def test_keyboard_typing_uses_the_configured_visible_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        WindowsDriver,
        "_literal_character_input_batch",
        staticmethod(lambda character: (character, character)),
    )
    monkeypatch.setattr(
        WindowsDriver,
        "_send_input_batch",
        staticmethod(lambda batch: calls.append(str(batch[0])) or len(batch)),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.035
    driver._typing_interval = 0.035
    driver._sleep = sleeps.append

    with _authorized(driver):
        result = driver.type("visible")

    assert result.ok
    assert calls == list("visible")
    assert sleeps == [0.035] * len("visible")


def test_unset_profile_preserves_uiautomation_native_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    sleeps: list[float] = []
    monkeypatch.setattr(
        WindowsDriver,
        "_literal_character_input_batch",
        staticmethod(lambda character: (character, character)),
    )
    monkeypatch.setattr(
        WindowsDriver,
        "_send_input_batch",
        staticmethod(lambda batch: calls.append(str(batch[0])) or len(batch)),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.0
    driver._typing_interval = None
    driver._sleep = sleeps.append

    with _authorized(driver):
        result = driver.type("native")

    assert result.ok
    assert calls == list("native")
    assert sleeps == [0.01] * len("native")


def test_keyboard_feedback_never_receives_typed_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feedback = _Feedback()
    sleeps: list[float] = []
    monkeypatch.setattr(
        WindowsDriver,
        "_literal_character_input_batch",
        staticmethod(lambda character: (character, character)),
    )
    monkeypatch.setattr(
        WindowsDriver,
        "_send_input_batch",
        staticmethod(len),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._type_wait_seconds = 0.025
    driver._typing_interval = 0.025
    driver._pacing = resolve_interaction_pacing("normal")
    driver._action_feedback = feedback
    driver._sleep = sleeps.append

    with _authorized(driver):
        result = driver.type("never show this secret")

    assert result.ok
    assert feedback.events == [("keyboard", "typing"), ("clear",)]
    assert feedback.progress == [(len("never show this secret"), 0.55)]
    assert sleeps == [0.04] + [0.025] * len("never show this secret") + [0.08]
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

    with _authorized(driver):
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


@pytest.mark.parametrize(
    ("character", "expected_scans"),
    [
        ("A", [0x0041, 0x0041]),
        ("😀", [0xD83D, 0xD83D, 0xDE00, 0xDE00]),
    ],
)
def test_literal_character_submits_one_complete_win32_input_array(
    character: str,
    expected_scans: list[int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, list[tuple[int, int]]]] = []

    class User32:
        def SendInput(self, count: int, pointer: object, size: int) -> int:
            typed_pointer = ctypes.cast(
                pointer,
                ctypes.POINTER(windows_driver_module.auto.INPUT),
            )
            events = [
                (
                    int(typed_pointer[index].union.ki.wScan),
                    int(typed_pointer[index].union.ki.dwFlags),
                )
                for index in range(count)
            ]
            calls.append((count, size, events))
            return count

    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", User32())

    batch = WindowsDriver._literal_character_input_batch(character)
    inserted = WindowsDriver._send_input_batch(batch)

    assert inserted == len(expected_scans)
    assert calls == [
        (
            len(expected_scans),
            ctypes.sizeof(windows_driver_module.auto.INPUT),
            list(zip(expected_scans, [0x0004, 0x0006] * (len(expected_scans) // 2))),
        )
    ]


@pytest.mark.parametrize(
    ("character", "inserted", "cleanup_scan"),
    [("A", 1, 0x0041), ("😀", 3, 0xDE00)],
)
def test_partial_odd_unicode_prefix_releases_key_before_tick_capture_failure(
    character: str,
    inserted: int,
    cleanup_scan: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[tuple[int, int]]] = []
    results = iter((inserted, 1))

    class User32:
        def SendInput(self, count: int, pointer: object, _size: int) -> int:
            typed_pointer = ctypes.cast(
                pointer,
                ctypes.POINTER(windows_driver_module.auto.INPUT),
            )
            calls.append(
                [
                    (
                        int(typed_pointer[index].union.ki.wScan),
                        int(typed_pointer[index].union.ki.dwFlags),
                    )
                    for index in range(count)
                ]
            )
            return next(results)

    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", User32())
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._typing_interval = 0.0
    driver._sleep = lambda _seconds: None
    boundary = NativeActionBoundary()
    driver.bind_native_action_boundary(boundary)

    with boundary.call_scope(
        _allow,
        lambda: (False, "HUMAN_ACTIVE: input state unavailable"),
    ):
        with pytest.raises(NativeAuthorityLost):
            driver.type(character)

    assert len(calls[0]) == len(WindowsDriver._literal_character_input_batch(character))
    assert calls[1] == [(cleanup_scan, 0x0006)]


@pytest.mark.parametrize("character", ["{", "}", "\n", "\t"])
def test_focused_type_treats_braces_and_controls_as_literal_scalars(
    character: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        WindowsDriver,
        "_literal_character_input_batch",
        staticmethod(lambda value: (value, value)),
    )
    monkeypatch.setattr(
        WindowsDriver,
        "_send_input_batch",
        staticmethod(lambda batch: calls.append(str(batch[0])) or len(batch)),
    )
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._typing_interval = 0.0
    driver._sleep = lambda _seconds: None

    with _authorized(driver):
        result = driver.type(character)

    assert result.ok
    assert calls == [character]
