from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from computer_use_agent.presence import DesktopAuthority, PresencePhase, PresenceSnapshot
from computer_use_agent.presence_lifecycle import RunPresenceCoordinator
from computer_use_agent.trace import RunPhase


@dataclass
class _Surface:
    snapshots: list[PresenceSnapshot] = field(default_factory=list)
    close_calls: int = 0
    fail_sync: bool = False
    fail_close: bool = False

    def sync(self, snapshot: PresenceSnapshot) -> None:
        if self.fail_sync:
            raise RuntimeError("surface failure")
        self.snapshots.append(snapshot)

    def close(self) -> None:
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("close failure")


def test_durable_run_phases_map_to_fixed_presence_and_authority() -> None:
    surface = _Surface()
    coordinator = RunPresenceCoordinator(surface)

    coordinator.on_phase(RunPhase.CREATED)
    for phase in (
        RunPhase.OBSERVING,
        RunPhase.PLANNING,
        RunPhase.WAITING_APPROVAL,
        RunPhase.EXECUTING,
        RunPhase.VERIFYING,
    ):
        coordinator.on_phase(phase)

    assert [snapshot.phase for snapshot in surface.snapshots] == [
        PresencePhase.OBSERVING,
        PresencePhase.PLANNING,
        PresencePhase.WAITING_APPROVAL,
        PresencePhase.EXECUTING,
        PresencePhase.VERIFYING,
    ]
    assert [snapshot.authority for snapshot in surface.snapshots] == [
        DesktopAuthority.HELD,
        DesktopAuthority.HELD,
        DesktopAuthority.WAITING,
        DesktopAuthority.HELD,
        DesktopAuthority.HELD,
    ]
    assert surface.close_calls == 1


@pytest.mark.parametrize(
    "terminal",
    [RunPhase.SUCCESS, RunPhase.FAILED, RunPhase.UNKNOWN_OUTCOME, RunPhase.CANCELLED],
)
def test_terminal_phase_closes_and_latches_surface(terminal: RunPhase) -> None:
    surface = _Surface()
    coordinator = RunPresenceCoordinator(surface)
    coordinator.on_phase(RunPhase.OBSERVING)

    coordinator.on_phase(terminal)
    coordinator.on_phase(RunPhase.PLANNING)

    assert [snapshot.phase for snapshot in surface.snapshots] == [PresencePhase.OBSERVING]
    assert surface.close_calls == 1


@pytest.mark.parametrize("boundary", ["estop", "release"])
def test_authority_loss_closes_and_cannot_be_reopened(boundary: str) -> None:
    surface = _Surface()
    coordinator = RunPresenceCoordinator(surface)
    coordinator.on_phase(RunPhase.EXECUTING)

    getattr(coordinator, boundary)()
    coordinator.on_phase(RunPhase.PLANNING)

    assert len(surface.snapshots) == 1
    assert surface.close_calls == 1


def test_surface_failure_is_bounded_fail_silent_and_not_retried() -> None:
    surface = _Surface(fail_sync=True, fail_close=True)
    coordinator = RunPresenceCoordinator(surface)

    coordinator.on_phase(RunPhase.OBSERVING)
    coordinator.on_phase(RunPhase.PLANNING)
    coordinator.release()

    assert coordinator.error_count == 1
    assert surface.close_calls == 1
