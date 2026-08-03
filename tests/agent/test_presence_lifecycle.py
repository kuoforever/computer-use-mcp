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


def test_yielding_authority_shows_the_operator_state_without_ending_the_halo() -> None:
    """The defect a complete Demo run exposed on 2026-08-02.

    The Runner yielded the desktop before a focus-taking approval by calling
    `release`, which latches. The halo was torn down at the first approval --
    seconds into the run -- and every later phase was discarded, so an operator
    who watched a whole Demo saw no halo at all.
    """

    surface = _Surface()
    coordinator = RunPresenceCoordinator(surface)

    coordinator.on_phase(RunPhase.EXECUTING)
    coordinator.yield_authority()
    coordinator.on_phase(RunPhase.EXECUTING)

    assert surface.close_calls == 0, "yielding must not end the surface"
    phases = [(s.phase, s.authority) for s in surface.snapshots]
    assert phases == [
        (PresencePhase.EXECUTING, DesktopAuthority.HELD),
        (PresencePhase.WAITING_APPROVAL, DesktopAuthority.WAITING),
        (PresencePhase.EXECUTING, DesktopAuthority.HELD),
    ], "the halo must show the yield and then come back"


def test_release_still_ends_the_surface_for_good() -> None:
    surface = _Surface()
    coordinator = RunPresenceCoordinator(surface)

    coordinator.on_phase(RunPhase.EXECUTING)
    coordinator.release()
    coordinator.on_phase(RunPhase.EXECUTING)
    coordinator.yield_authority()

    assert surface.close_calls == 1
    assert len(surface.snapshots) == 1, "nothing may reach a released surface"


def test_fail_silent_yield_falls_back_to_release_for_an_unknown_surface() -> None:
    """A surface that cannot express a transient yield is closed instead.

    Yielding the desktop is the safety property, and a closed surface has
    certainly yielded. Silently doing nothing would leave a halo claiming
    authority while the operator is being asked to decide.
    """

    from computer_use_agent.presence_lifecycle import FailSilentLifecycle

    class OldSurface:
        def __init__(self) -> None:
            self.events: list[str] = []

        def on_phase(self, _phase: object) -> None:
            self.events.append("phase")

        def estop(self) -> None:
            self.events.append("estop")

        def release(self) -> None:
            self.events.append("release")

    port = OldSurface()
    lifecycle = FailSilentLifecycle(port)  # type: ignore[arg-type]
    lifecycle.yield_authority()
    lifecycle.on_phase(RunPhase.EXECUTING)

    assert port.events == ["release"], "a latched surface receives nothing more"


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def test_a_pumped_coordinator_paints_on_its_own_worker_thread() -> None:
    """Projections must reach a pumped surface, and only from the worker.

    Without a pump the halo was created, visible, and never sent WM_PAINT, so
    it drew nothing. A colour-keyed layered window that never paints is fully
    transparent: the Runner projected every phase correctly and no operator
    ever saw one during a complete Demo.
    """

    import threading

    surface = _Surface()
    pumped: list[int] = []
    coordinator = RunPresenceCoordinator(
        surface,
        pump=lambda: pumped.append(threading.get_ident()),
        interval_seconds=0.01,
        join_timeout_seconds=1.0,
    )
    caller = threading.get_ident()

    coordinator.on_phase(RunPhase.EXECUTING)
    assert _wait_until(lambda: bool(surface.snapshots))
    coordinator.yield_authority()
    assert _wait_until(
        lambda: any(
            s.phase is PresencePhase.WAITING_APPROVAL for s in surface.snapshots
        )
    )
    assert surface.close_calls == 0, "yielding must not end the surface"

    coordinator.release()
    assert _wait_until(lambda: surface.close_calls == 1)
    assert pumped, "the surface was never pumped"
    assert caller not in pumped, "the caller thread must not pump the halo"
    assert coordinator.error_count == 0


def test_created_closes_a_stale_surface_without_ending_the_lifecycle() -> None:
    """CREATED is the first phase of every run.

    Treating its close as "stop the worker" meant the halo was never created at
    all: the worker started, saw a stop already set, and exited before syncing
    anything. A sampled Demo run recorded projection_count 0 and 32 samples
    with no window in existence.
    """

    import threading

    surface = _Surface()
    coordinator = RunPresenceCoordinator(
        surface,
        pump=lambda: None,
        interval_seconds=0.01,
        join_timeout_seconds=1.0,
    )

    coordinator.on_phase(RunPhase.CREATED)
    coordinator.on_phase(RunPhase.OBSERVING)
    coordinator.on_phase(RunPhase.EXECUTING)

    assert _wait_until(
        lambda: any(s.phase is PresencePhase.EXECUTING for s in surface.snapshots)
    ), "the halo must exist after CREATED"
    assert coordinator.error_count == 0
    assert isinstance(coordinator._thread, threading.Thread)
    assert coordinator._thread.is_alive()

    coordinator.release()
    assert _wait_until(lambda: surface.close_calls >= 1)
