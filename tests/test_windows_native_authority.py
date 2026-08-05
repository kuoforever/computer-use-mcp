from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from itertools import repeat

import pytest

from computer_use_mcp.contract import Rect
from computer_use_mcp.drivers.windows import WindowsDriver
from computer_use_mcp.interaction_feedback import resolve_interaction_pacing
from computer_use_mcp.native_authority import NativeActionBoundary, NativeAuthorityLost


class _PointerInputApi:
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def GetCursorPos(self, point: object) -> bool:
        point._obj.x = 0  # type: ignore[attr-defined]
        point._obj.y = 0  # type: ignore[attr-defined]
        return True

    def SetCursorPos(self, x: int, y: int) -> bool:
        self.events.append(("pointer", x, y))
        return True

    def mouse_event(self, flags: int, _x: int, _y: int, data: int, _extra: int) -> None:
        self.events.append(("mouse", flags, data))

    def keybd_event(self, vk: int, _scan: int, flags: int, _extra: int) -> None:
        self.events.append(("key", vk, flags))


def _driver(*, pacing: str | None = None) -> WindowsDriver:
    driver = WindowsDriver.__new__(WindowsDriver)
    driver._pacing = resolve_interaction_pacing(pacing)
    driver._action_feedback = None
    driver._typing_interval = 0.0
    driver._sleep = lambda _seconds: None
    return driver


def _allow() -> tuple[bool, str]:
    return True, ""


@contextmanager
def _scope(
    driver: WindowsDriver,
    decisions: Iterator[tuple[bool, str]],
    capture: Callable[[], tuple[bool, str]] | None = None,
) -> Iterator[None]:
    boundary = NativeActionBoundary()
    driver.bind_native_action_boundary(boundary)
    with boundary.call_scope(lambda: next(decisions), capture or _allow):
        yield


def test_paced_semantic_loss_after_delay_calls_no_uia_mutation() -> None:
    class Pattern:
        calls = 0

        def Invoke(self) -> None:
            self.calls += 1

    class Control:
        pattern = Pattern()

        def GetInvokePattern(self):
            return self.pattern

    driver = _driver(pacing="normal")
    control = Control()
    sleeps: list[float] = []
    driver._sleep = sleeps.append
    driver._resolve = lambda _native_id: control  # type: ignore[method-assign]
    driver._rect_of = lambda _control: Rect(10, 20, 30, 40)  # type: ignore[method-assign]

    with _scope(driver, iter(((False, "ABORTED: e-stop engaged"),))):
        with pytest.raises(NativeAuthorityLost) as caught:
            driver.invoke("node")

    assert not caught.value.after_dispatch
    assert control.pattern.calls == 0
    assert sleeps == [0.04]


def test_paced_pointer_partial_loss_stops_before_click(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _PointerInputApi()
    driver = _driver(pacing="fast")
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)
    decisions = iter(
        (
            (True, ""),
            (True, ""),
            (False, "DENIED by gate: foreground changed"),
        )
    )

    with _scope(driver, decisions):
        with pytest.raises(NativeAuthorityLost) as caught:
            driver.click(50, 60)

    assert caught.value.after_dispatch
    assert [event[0] for event in api.events] == ["pointer", "pointer"]


def test_drag_loss_after_mouse_down_only_releases_held_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _PointerInputApi()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)
    decisions = iter(
        (
            (True, ""),
            (True, ""),
            (False, "HUMAN_ACTIVE: changed"),
        )
    )

    with _scope(driver, decisions):
        with pytest.raises(NativeAuthorityLost) as caught:
            driver.drag(10, 20, 30, 40, 32)

    assert caught.value.after_dispatch
    assert api.events == [
        ("pointer", 10, 20),
        ("mouse", 0x0002, 0),
        ("mouse", 0x0004, 0),
    ]


def test_key_loss_after_modifier_down_only_releases_held_modifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _PointerInputApi()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)
    decisions = iter(((True, ""), (False, "ABORTED: e-stop engaged")))

    with _scope(driver, decisions):
        with pytest.raises(NativeAuthorityLost) as caught:
            driver.key("Ctrl+S")

    assert caught.value.after_dispatch
    assert api.events == [("key", 0x11, 0), ("key", 0x11, 0x0002)]


def test_key_capture_failure_after_modifier_down_still_releases_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = _PointerInputApi()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)

    with _scope(
        driver,
        iter(((True, ""),)),
        capture=lambda: (False, "HUMAN_ACTIVE: input state unavailable"),
    ):
        with pytest.raises(NativeAuthorityLost) as caught:
            driver.key("Ctrl+S")

    assert caught.value.after_dispatch
    assert api.events == [("key", 0x11, 0), ("key", 0x11, 0x0002)]


def test_focused_type_loss_between_scalars_stops_remaining_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = _driver()
    sent: list[str] = []
    monkeypatch.setattr(
        driver,
        "_literal_character_input_batch",
        lambda character: (character, character),
    )
    monkeypatch.setattr(
        driver,
        "_send_input_batch",
        lambda batch: sent.append(str(batch[0])) or len(batch),
    )
    decisions = iter(((True, ""), (False, "HUMAN_ACTIVE: changed")))

    with _scope(driver, decisions):
        with pytest.raises(NativeAuthorityLost) as caught:
            driver.type("abc")

    assert caught.value.after_dispatch
    assert sent == ["a"]


def test_key_down_effect_then_error_still_releases_possible_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Api(_PointerInputApi):
        def keybd_event(self, vk: int, scan: int, flags: int, extra: int) -> None:
            super().keybd_event(vk, scan, flags, extra)
            if flags == 0:
                raise OSError("effect then error")

    api = Api()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)

    with _scope(driver, repeat((True, ""))):
        result = driver.key("Ctrl")

    assert not result.ok
    assert api.events == [("key", 0x11, 0), ("key", 0x11, 0x0002)]


@pytest.mark.parametrize("action", ["click", "drag"])
def test_mouse_down_effect_then_error_still_releases_possible_button(
    action: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Api(_PointerInputApi):
        def mouse_event(
            self,
            flags: int,
            x: int,
            y: int,
            data: int,
            extra: int,
        ) -> None:
            super().mouse_event(flags, x, y, data, extra)
            if flags == 0x0002:
                raise OSError("effect then error")

    api = Api()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)

    with _scope(driver, repeat((True, ""))):
        result = (
            driver.click(10, 20)
            if action == "click"
            else driver.drag(10, 20, 30, 40, 0)
        )

    assert not result.ok
    assert api.events == [
        ("pointer", 10, 20),
        ("mouse", 0x0002, 0),
        ("mouse", 0x0004, 0),
    ]


def test_pointer_failure_stops_before_mouse_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Api(_PointerInputApi):
        def SetCursorPos(self, x: int, y: int) -> bool:
            super().SetCursorPos(x, y)
            return False

    api = Api()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)

    with _scope(driver, repeat((True, ""))):
        result = driver.click(50, 60)

    assert not result.ok
    assert api.events == [("pointer", 50, 60)]


def test_paced_pointer_failure_stops_after_prefix_without_mouse_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Api(_PointerInputApi):
        def SetCursorPos(self, x: int, y: int) -> bool:
            super().SetCursorPos(x, y)
            return len(self.events) < 3

    api = Api()
    driver = _driver(pacing="fast")
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)

    with _scope(driver, repeat((True, ""))):
        result = driver.click(50, 60)

    assert not result.ok
    assert [event[0] for event in api.events] == ["pointer", "pointer", "pointer"]


def test_drag_path_pointer_failure_stops_and_only_releases_button(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Api(_PointerInputApi):
        def SetCursorPos(self, x: int, y: int) -> bool:
            super().SetCursorPos(x, y)
            pointer_calls = sum(event[0] == "pointer" for event in self.events)
            return pointer_calls < 3

    api = Api()
    driver = _driver()
    monkeypatch.setattr("computer_use_mcp.drivers.windows.ctypes.windll.user32", api)

    with _scope(driver, repeat((True, ""))):
        result = driver.drag(10, 20, 30, 40, 32)

    assert not result.ok
    assert api.events == [
        ("pointer", 10, 20),
        ("mouse", 0x0002, 0),
        ("pointer", 20, 30),
        ("pointer", 30, 40),
        ("mouse", 0x0004, 0),
    ]
