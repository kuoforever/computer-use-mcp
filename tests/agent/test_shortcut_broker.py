from __future__ import annotations

from dataclasses import replace

from computer_use_agent.cooperative_control import (
    ControlBoundary,
    ControlRequestKind,
    ControlStatus,
    CooperativeControlError,
    CooperativeControlSnapshot,
    DesktopControlAuthority,
)
from computer_use_agent.shortcut_broker import (
    ShortcutAction,
    ShortcutBroker,
    ShortcutEventState,
)


def _active() -> CooperativeControlSnapshot:
    return CooperativeControlSnapshot(
        run_id="run-1",
        owner_token_digest="a" * 64,
        runner_state_path="runs/run-1",
        sequence=1,
        status=ControlStatus.ACTIVE,
        request_kind=None,
        request_id=None,
        authority=DesktopControlAuthority.AGENT,
        fresh_observation_required=False,
        boundary=None,
        checkpoint_sequence=None,
        outcome=None,
        created_at="2026-08-08T00:00:00+00:00",
        updated_at="2026-08-08T00:00:00+00:00",
    )


def _pause_requested() -> CooperativeControlSnapshot:
    return replace(
        _active(),
        sequence=2,
        status=ControlStatus.PAUSE_REQUESTED,
        request_kind=ControlRequestKind.PAUSE,
        request_id="request-1",
        updated_at="2026-08-08T00:00:01+00:00",
    )


def _paused() -> CooperativeControlSnapshot:
    return replace(
        _pause_requested(),
        sequence=3,
        status=ControlStatus.PAUSED,
        authority=DesktopControlAuthority.RELEASED,
        fresh_observation_required=True,
        boundary=ControlBoundary.BEFORE_PROVIDER,
        checkpoint_sequence=4,
        updated_at="2026-08-08T00:00:02+00:00",
    )


class _Control:
    def __init__(self) -> None:
        self.request_calls = 0
        self.read_snapshot = _pause_requested()
        self.error: CooperativeControlError | None = None

    def request_pause(
        self,
        kind: ControlRequestKind,
        *,
        run_id: str | None = None,
    ) -> CooperativeControlSnapshot:
        assert kind is ControlRequestKind.PAUSE
        assert run_id is None
        self.request_calls += 1
        if self.error is not None:
            raise self.error
        return _pause_requested()

    def read(self, run_id: str) -> CooperativeControlSnapshot:
        assert run_id == "run-1"
        if self.error is not None:
            raise self.error
        return self.read_snapshot


def test_open_controls_is_presentation_only() -> None:
    presented: list[str] = []
    events = []
    control = _Control()
    broker = ShortcutBroker(
        presenter=lambda: presented.append("shown"),
        control=control,
        event_sink=events.append,
    )

    broker.handle(ShortcutAction.OPEN_CONTROLS)

    assert presented == ["shown"]
    assert control.request_calls == 0
    assert [event.state for event in events] == [ShortcutEventState.CONTROLS_OPENED]
    assert events[0].as_json()["authority"] == {
        "can_approve": False,
        "can_dispatch": False,
        "can_resume": False,
    }
    assert not hasattr(broker, "approve")
    assert not hasattr(broker, "resume")


def test_pause_stays_requested_until_exact_released_state() -> None:
    events = []
    control = _Control()
    broker = ShortcutBroker(
        presenter=lambda: None,
        control=control,
        event_sink=events.append,
    )

    broker.handle(ShortcutAction.REQUEST_PAUSE)
    broker.handle(ShortcutAction.REQUEST_PAUSE)

    assert control.request_calls == 1
    assert [event.state for event in events] == [ShortcutEventState.PAUSE_REQUESTED]
    assert broker.pending_run_id == "run-1"
    assert events[0].as_json()["desktop_authority_released"] is False

    control.read_snapshot = _paused()
    broker.poll()

    assert [event.state for event in events] == [
        ShortcutEventState.PAUSE_REQUESTED,
        ShortcutEventState.PAUSED_RELEASED,
    ]
    assert events[-1].as_json()["desktop_authority_released"] is True
    assert broker.pending_run_id is None


def test_pause_unavailable_fails_closed_without_liveness_or_takeover_claim() -> None:
    events = []
    control = _Control()
    control.error = CooperativeControlError("COOPERATIVE_CONTROL_NOT_FOUND")
    broker = ShortcutBroker(
        presenter=lambda: None,
        control=control,
        event_sink=events.append,
    )

    broker.handle(ShortcutAction.REQUEST_PAUSE)

    assert len(events) == 1
    assert events[0].state is ShortcutEventState.PAUSE_UNAVAILABLE
    projection = events[0].as_json()
    assert projection["run_id"] is None
    assert projection["desktop_authority_released"] is False
    assert "COOPERATIVE_CONTROL" not in str(projection)


def test_poll_fails_closed_if_control_record_does_not_reach_released_pause() -> None:
    events = []
    control = _Control()
    broker = ShortcutBroker(
        presenter=lambda: None,
        control=control,
        event_sink=events.append,
    )
    broker.handle(ShortcutAction.REQUEST_PAUSE)
    control.read_snapshot = _active()

    broker.poll()

    assert events[-1].state is ShortcutEventState.PAUSE_UNAVAILABLE
    assert events[-1].desktop_authority_released is False
    assert broker.pending_run_id is None
