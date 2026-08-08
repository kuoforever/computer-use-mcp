from __future__ import annotations

import pytest

from computer_use_agent.shortcut_broker import ShortcutAction
from computer_use_agent.shortcut_broker_win32 import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    OPEN_CONTROLS_HOTKEY_ID,
    REQUEST_PAUSE_HOTKEY_ID,
    GlobalShortcutLoop,
    ShortcutLoopEvent,
    ShortcutRegistrationError,
)


class _Broker:
    def __init__(self) -> None:
        self.actions: list[ShortcutAction] = []
        self.polls = 0

    def handle(self, action: ShortcutAction) -> None:
        self.actions.append(action)

    def poll(self) -> None:
        self.polls += 1


class _Api:
    def __init__(
        self,
        *,
        registration_results: list[bool] | None = None,
        events: list[ShortcutLoopEvent] | None = None,
        layout_conflicts: set[int] | None = None,
    ) -> None:
        self.registration_results = registration_results or [True, True]
        self.events = events or [ShortcutLoopEvent.STOP]
        self.registrations: list[tuple[int, int, int]] = []
        self.unregistrations: list[int] = []
        self.timer_started: list[int] = []
        self.timer_stopped = 0
        self.layout_conflicts = layout_conflicts or set()
        self.layout_checks: list[int] = []

    def has_ctrl_alt_mapping(self, virtual_key: int) -> bool:
        self.layout_checks.append(virtual_key)
        return virtual_key in self.layout_conflicts

    def register_hotkey(self, identifier: int, modifiers: int, virtual_key: int) -> bool:
        self.registrations.append((identifier, modifiers, virtual_key))
        return self.registration_results[len(self.registrations) - 1]

    def unregister_hotkey(self, identifier: int) -> None:
        self.unregistrations.append(identifier)

    def start_timer(self, interval_ms: int) -> None:
        self.timer_started.append(interval_ms)

    def stop_timer(self) -> None:
        self.timer_stopped += 1

    def next_event(self) -> ShortcutLoopEvent:
        return self.events.pop(0)


def test_global_loop_uses_norepeat_and_never_registers_estop_key() -> None:
    api = _Api(
        events=[
            ShortcutLoopEvent.OPEN_CONTROLS,
            ShortcutLoopEvent.REQUEST_PAUSE,
            ShortcutLoopEvent.TICK,
            ShortcutLoopEvent.STOP,
        ]
    )
    broker = _Broker()
    registered: list[str] = []

    handled = GlobalShortcutLoop(api).run(
        broker,
        on_registered=lambda: registered.append("active"),
    )

    expected_modifiers = MOD_ALT | MOD_CONTROL | MOD_NOREPEAT
    assert api.registrations == [
        (OPEN_CONTROLS_HOTKEY_ID, expected_modifiers, ord("G")),
        (REQUEST_PAUSE_HOTKEY_ID, expected_modifiers, ord("P")),
    ]
    assert api.layout_checks == [ord("G"), ord("P")]
    assert all(virtual_key != ord("Q") for _, _, virtual_key in api.registrations)
    assert broker.actions == [
        ShortcutAction.OPEN_CONTROLS,
        ShortcutAction.REQUEST_PAUSE,
    ]
    assert broker.polls == 1
    assert handled == 3
    assert api.timer_started == [100]
    assert api.timer_stopped == 1
    assert registered == ["active"]
    assert api.unregistrations == [
        REQUEST_PAUSE_HOTKEY_ID,
        OPEN_CONTROLS_HOTKEY_ID,
    ]


@pytest.mark.parametrize(
    ("registration_results", "message", "unregistered"),
    [
        ([False], "SHORTCUT_CONFLICT_OPEN_CONTROLS", []),
        (
            [True, False],
            "SHORTCUT_CONFLICT_REQUEST_PAUSE",
            [OPEN_CONTROLS_HOTKEY_ID],
        ),
    ],
)
def test_registration_conflict_is_visible_and_rolls_back_atomically(
    registration_results: list[bool],
    message: str,
    unregistered: list[int],
) -> None:
    api = _Api(registration_results=registration_results)
    registered: list[str] = []

    with pytest.raises(ShortcutRegistrationError, match=message):
        GlobalShortcutLoop(api).run(
            _Broker(),
            on_registered=lambda: registered.append("active"),
        )

    assert registered == []
    assert api.unregistrations == unregistered
    assert api.timer_started == []
    assert api.timer_stopped == 0


def test_loop_always_unregisters_after_broker_failure() -> None:
    class FailingBroker(_Broker):
        def handle(self, action: ShortcutAction) -> None:
            raise RuntimeError("presentation failed")

    api = _Api(events=[ShortcutLoopEvent.OPEN_CONTROLS])

    with pytest.raises(RuntimeError, match="presentation failed"):
        GlobalShortcutLoop(api).run(FailingBroker())

    assert api.timer_stopped == 1
    assert api.unregistrations == [
        REQUEST_PAUSE_HOTKEY_ID,
        OPEN_CONTROLS_HOTKEY_ID,
    ]


def test_configured_pause_key_replaces_only_default_p_registration() -> None:
    api = _Api()

    GlobalShortcutLoop(api, request_pause_virtual_key=ord("K")).run(_Broker())

    expected_modifiers = MOD_ALT | MOD_CONTROL | MOD_NOREPEAT
    assert api.layout_checks == [ord("G"), ord("K")]
    assert api.registrations == [
        (OPEN_CONTROLS_HOTKEY_ID, expected_modifiers, ord("G")),
        (REQUEST_PAUSE_HOTKEY_ID, expected_modifiers, ord("K")),
    ]


@pytest.mark.parametrize(
    ("conflict_key", "message"),
    [
        (ord("G"), "SHORTCUT_LAYOUT_CONFLICT_OPEN_CONTROLS"),
        (ord("K"), "SHORTCUT_LAYOUT_CONFLICT_REQUEST_PAUSE"),
    ],
)
def test_layout_conflict_fails_before_any_registration(
    conflict_key: int,
    message: str,
) -> None:
    api = _Api(layout_conflicts={conflict_key})

    with pytest.raises(ShortcutRegistrationError, match=message):
        GlobalShortcutLoop(api, request_pause_virtual_key=ord("K")).run(_Broker())

    assert api.registrations == []
    assert api.timer_started == []
    assert api.unregistrations == []


@pytest.mark.parametrize("virtual_key", [False, ord("1"), ord("G"), ord("Q"), 0x7B])
def test_pause_virtual_key_is_bounded_to_non_reserved_a_to_z(
    virtual_key: object,
) -> None:
    with pytest.raises(ShortcutRegistrationError, match="SHORTCUT_LOOP_CONFIG_INVALID"):
        GlobalShortcutLoop(  # type: ignore[arg-type]
            _Api(),
            request_pause_virtual_key=virtual_key,
        )
