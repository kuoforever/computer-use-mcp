from __future__ import annotations

import threading
import time
from pathlib import Path

from computer_use_agent.fakes import FakeProgressWindowApi
from computer_use_agent.progress_lifecycle import RunProgressCoordinator
from computer_use_agent.progress_poller import ProgressPoller
from computer_use_agent.progress_window import PassiveProgressWindow
from computer_use_agent.trace import RunPhase


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _coordinator(
    state_dir: Path,
    *,
    api: FakeProgressWindowApi | None = None,
    pump=None,
) -> tuple[RunProgressCoordinator, FakeProgressWindowApi]:
    resolved_api = api or FakeProgressWindowApi()
    poller = ProgressPoller(
        state_dir,
        PassiveProgressWindow(resolved_api),
        interval_seconds=0.01,
    )
    return (
        RunProgressCoordinator(
            poller,
            pump=(lambda: None) if pump is None else pump,
            join_timeout_seconds=1.0,
        ),
        resolved_api,
    )


def test_phase_notifications_drive_one_ui_thread_and_release_closes(
    tmp_path: Path,
) -> None:
    caller_thread = threading.get_ident()
    pump_threads: list[int] = []
    pumped = threading.Event()

    def pump() -> None:
        pump_threads.append(threading.get_ident())
        pumped.set()

    coordinator, api = _coordinator(tmp_path.resolve(), pump=pump)

    coordinator.on_phase(RunPhase.CREATED)
    assert pumped.wait(1.0)
    assert coordinator.running is True
    assert api.kinds()[:3] == ["create", "set_lines", "show_noactivate"]

    coordinator.on_phase(RunPhase.PLANNING)
    assert _wait_until(lambda: len(pump_threads) >= 2)
    coordinator.release()

    assert coordinator.running is False
    assert api.alive == set()
    assert api.kinds()[-1] == "destroy"
    assert pump_threads
    assert all(thread_id != caller_thread for thread_id in pump_threads)


def test_campaign_wake_starts_without_inventing_a_run_phase(tmp_path: Path) -> None:
    coordinator, api = _coordinator(tmp_path.resolve())

    coordinator.wake()
    assert _wait_until(lambda: "create" in api.kinds())
    coordinator.release()

    assert api.kinds().count("create") == 1
    assert api.kinds().count("destroy") == 1
    assert coordinator.running is False


def test_release_is_idempotent_and_prevents_reopening(tmp_path: Path) -> None:
    coordinator, api = _coordinator(tmp_path.resolve())

    coordinator.on_phase(RunPhase.OBSERVING)
    assert _wait_until(lambda: "create" in api.kinds())
    coordinator.release()
    coordinator.release()
    coordinator.on_phase(RunPhase.PLANNING)

    assert api.kinds().count("create") == 1
    assert api.kinds().count("destroy") == 1


def test_surface_failure_is_bounded_and_cannot_fail_the_caller(
    tmp_path: Path,
) -> None:
    class BrokenApi(FakeProgressWindowApi):
        def create(self, *, ex_style: int, style: int, title: str) -> int:
            del ex_style, style, title
            raise RuntimeError("native surface failed")

    coordinator, api = _coordinator(tmp_path.resolve(), api=BrokenApi())

    coordinator.on_phase(RunPhase.CREATED)
    assert _wait_until(lambda: coordinator.error_count == 1)
    coordinator.on_phase(RunPhase.PLANNING)
    coordinator.release()

    assert coordinator.error_count == 1
    assert api.kinds() == []
    assert coordinator.running is False


def test_invalid_phase_fails_closed_without_starting_thread(tmp_path: Path) -> None:
    coordinator, api = _coordinator(tmp_path.resolve())

    coordinator.on_phase("PLANNING")  # type: ignore[arg-type]
    coordinator.on_phase(RunPhase.PLANNING)

    assert coordinator.error_count == 1
    assert coordinator.running is False
    assert api.kinds() == []
