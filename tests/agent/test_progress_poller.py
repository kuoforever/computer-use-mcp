"""Tests for atomic live checkpoint polling (progress viewer delivery step 3).

These drive the poller against real on-disk checkpoints and the recording fake
window API, so atomicity, staleness honesty, and the non-activating contract are
proven without a desktop.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

import pytest

from computer_use_agent.atomic_file import publish_atomically
from computer_use_agent.progress_poller import (
    SCAN_UNAVAILABLE_LINES,
    ProgressPoller,
)
from computer_use_agent.fakes import FakeProgressWindowApi
from computer_use_agent.progress_window import PassiveProgressWindow
from computer_use_agent.trace import RunPhase, RunRecorder
from computer_use_agent.types import LedgerEvent, LedgerEventKind, RunBudget, RunState

FORBIDDEN = "POLLER_TASK_SECRET"


def _state(run_id: str) -> RunState:
    return RunState(
        run_id=run_id,
        task=FORBIDDEN,
        policy_version="poll-v1",
        observation_epoch=0,
        budgets=RunBudget(3, 4, 0, model_turns_used=1, tool_calls_used=2),
        event_log=(
            LedgerEvent(
                event_id=f"{run_id}:event:1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len(FORBIDDEN)},
            ),
        ),
    )


def _record(state_dir: Path, run_id: str, phase: RunPhase) -> RunRecorder:
    state = _state(run_id)
    recorder = RunRecorder(state_dir, run_id)
    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING)
    if phase is RunPhase.OBSERVING:
        return recorder
    recorder.record(state, RunPhase.PLANNING)
    if phase is RunPhase.PLANNING:
        return recorder
    if phase is RunPhase.SUCCESS:
        recorder.record(state, RunPhase.SUCCESS, run_duration_ms=20)
        return recorder
    raise AssertionError(f"unhandled phase {phase}")


def _poller(state_dir: Path) -> tuple[ProgressPoller, FakeProgressWindowApi]:
    api = FakeProgressWindowApi()
    window = PassiveProgressWindow(api)
    slept: list[float] = []
    poller = ProgressPoller(state_dir, window, interval_seconds=0.01, sleep=slept.append)
    poller.slept = slept  # type: ignore[attr-defined]
    return poller, api


def test_first_poll_opens_window_and_draws_current_state(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, api = _poller(state_dir)

    outcome = poller.poll_once()

    assert outcome.redrew is True
    assert outcome.scan_failed is False
    assert outcome.run_count == 1
    assert api.kinds()[:3] == ["create", "set_lines", "show_noactivate"]
    drawn = "\n".join(api.lines[poller.window.hwnd])
    assert "run_a" in drawn
    assert FORBIDDEN not in drawn


def test_unchanged_state_is_not_redrawn(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, api = _poller(state_dir)

    first = poller.poll_once()
    second = poller.poll_once()
    third = poller.poll_once()

    assert first.redrew is True
    assert second.redrew is False and third.redrew is False
    # Exactly one content push after the initial open, so a quiet desktop stays quiet.
    assert api.kinds().count("set_lines") == 2  # open's empty draw + first real draw


def test_phase_change_is_picked_up_on_the_next_poll(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    recorder = _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, api = _poller(state_dir)
    poller.poll_once()
    assert "In progress at last checkpoint" in "\n".join(api.lines[poller.window.hwnd])

    recorder.record(_state("run_a"), RunPhase.SUCCESS, run_duration_ms=20)
    outcome = poller.poll_once()

    assert outcome.redrew is True
    assert "Complete" in "\n".join(api.lines[poller.window.hwnd])


def test_new_run_appears_and_runs_stay_separate(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, api = _poller(state_dir)
    poller.poll_once()

    _record(state_dir, "run_b", RunPhase.SUCCESS)
    outcome = poller.poll_once()

    drawn = "\n".join(api.lines[poller.window.hwnd])
    assert outcome.run_count == 2
    # Acceptance check 2: both ids present, each with its own distinct state.
    assert "run_a" in drawn and "run_b" in drawn
    assert "In progress at last checkpoint" in drawn and "Complete" in drawn


def test_polling_never_activates_or_moves_foreground(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, api = _poller(state_dir)
    before = api.foreground()

    poller.run(max_polls=5)

    assert api.foreground() == before
    assert "show_noactivate" in api.kinds()
    # Nothing in the poll path repositions or re-shows the window after opening.
    assert api.kinds().count("show_noactivate") == 1


def test_run_loop_respects_max_polls_and_sleeps_between_only(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, _ = _poller(state_dir)

    outcomes = poller.run(max_polls=3)

    assert len(outcomes) == 3
    # Sleeps happen between polls, never after the last one.
    assert poller.slept == [0.01, 0.01]  # type: ignore[attr-defined]


def test_run_loop_stops_on_condition(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, _ = _poller(state_dir)
    calls = {"n": 0}

    def should_stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    outcomes = poller.run(should_stop=should_stop)

    assert 0 < len(outcomes) <= 2


def test_directory_tamper_discards_stale_view_instead_of_showing_it(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    poller, api = _poller(state_dir)
    poller.poll_once()
    assert "run_a" in "\n".join(api.lines[poller.window.hwnd])

    # Directory-level failure: `runs` exists but is not a directory, so the
    # whole scan is untrustworthy rather than merely empty. (A symlinked runs
    # directory is the other such case; creating one needs Windows privileges
    # the test suite must not require.)
    runs_dir = state_dir / "runs"
    for entry in runs_dir.iterdir():
        for child in entry.iterdir():
            child.unlink()
        entry.rmdir()
    runs_dir.rmdir()
    runs_dir.write_text("not a directory", encoding="utf-8")

    outcome = poller.poll_once()

    assert outcome.scan_failed is True
    drawn = api.lines[poller.window.hwnd]
    assert drawn == SCAN_UNAVAILABLE_LINES
    # The previously good view is gone; stale facts are never left on screen.
    assert "run_a" not in "\n".join(drawn)


def test_one_corrupt_record_does_not_invalidate_the_others(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_good", RunPhase.PLANNING)
    _record(state_dir, "run_bad", RunPhase.PLANNING)
    (state_dir / "runs" / "run_bad" / "state.json").write_text("{ not json", encoding="utf-8")
    poller, api = _poller(state_dir)

    outcome = poller.poll_once()

    drawn = "\n".join(api.lines[poller.window.hwnd])
    assert outcome.scan_failed is False
    assert outcome.run_count == 1 and outcome.unavailable_count == 1
    assert "run_good" in drawn
    assert "unavailable (1): run_bad" in drawn


def test_poller_rejects_relative_state_dir_and_bad_interval(tmp_path: Path) -> None:
    window = PassiveProgressWindow(FakeProgressWindowApi())
    with pytest.raises(ValueError):
        ProgressPoller(Path("relative"), window)
    with pytest.raises(ValueError):
        ProgressPoller(tmp_path.resolve(), window, interval_seconds=0)


def test_atomic_replacement_never_yields_a_torn_record(tmp_path: Path) -> None:
    """Acceptance check 3: a poll sees the previous or next complete checkpoint.

    A writer thread republishes the checkpoint with two different complete
    records through the production publish path while the main thread polls.
    Every *successful* observation must be one of the two whole records — never
    a mixture. A poll may occasionally miss the record entirely while a publish
    is in flight; that is a different, tolerated outcome (the record shows as
    unavailable and the next poll recovers) and is counted separately.
    """

    state_dir = tmp_path.resolve()
    _record(state_dir, "run_a", RunPhase.PLANNING)
    checkpoint_path = state_dir / "runs" / "run_a" / "state.json"

    planning = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    success = dict(planning)
    success["phase"] = "SUCCESS"
    success["metrics"] = dict(planning["metrics"], run_duration_ms=20)
    payloads = [
        json.dumps(planning).encode("utf-8"),
        json.dumps(success).encode("utf-8"),
    ]

    stop = threading.Event()

    failed_publishes = 0

    def writer() -> None:
        nonlocal failed_publishes
        index = 0
        while not stop.is_set():
            descriptor, raw = tempfile.mkstemp(
                prefix=".state-", suffix=".tmp", dir=str(checkpoint_path.parent)
            )
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payloads[index % 2])
            try:
                # The production publish path: a reader must never block it.
                publish_atomically(Path(raw), checkpoint_path)
            except OSError:
                failed_publishes += 1
                os.unlink(raw)
            index += 1

    poller, api = _poller(state_dir)
    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        observed: set[str] = set()
        transient_misses = 0
        for _ in range(300):
            outcome = poller.poll_once()
            assert outcome.scan_failed is False
            if outcome.run_count == 0:
                # Allowed by design, and distinct from a torn read: a publish
                # briefly frees the target name, so a racing read can miss it
                # entirely. The record is then shown unavailable and the next
                # poll recovers. What must never happen is a *partial* record.
                transient_misses += 1
                continue
            assert outcome.run_count == 1
            head = api.lines[poller.window.hwnd][1]
            observed.add(head.split("  ", 1)[1])
    finally:
        stop.set()
        thread.join(timeout=5)

    # The concurrent reader never blocked the production publish path.
    assert failed_publishes == 0

    # The actual acceptance property: every observation that succeeded was one
    # of the two whole records. A mixture of the two would show up here as an
    # unrecognised state, and a partial record would fail the reducer outright.
    assert observed <= {
        "In progress at last checkpoint; liveness unknown",
        "Complete",
    }
    assert observed, "expected at least one observation"
    # Transient misses are tolerated but must stay the exception.
    assert transient_misses < 150
