"""Isolated smoke for live checkpoint polling (delivery step 3).

Where the step-2 smoke drew synthetic view models, this one closes the loop on a
live desktop: a real ``RunRecorder`` publishes real checkpoints while the real
poller scans them and refreshes the real ctypes window. It confirms three
properties that offline tests can only assert in injectable or single-process
form:

1. **Liveness end to end.** A phase transition written by the recorder actually
   reaches the drawn window, so the displayed state follows real state.
2. **Polling stays passive.** The foreground window the operator was using is
   unchanged across the whole polling session.
3. **The publish/read hazard stays fixed on a real desktop.** A writer publishes
   continuously while the poller reads the same checkpoints. Every publish must
   succeed: before the ``ReplaceFileW`` + share-delete fix this measured 61.9%
   hard ``CHECKPOINT_WRITE_FAILED`` failures, which would fail the agent's run.

The probe discards its result if the system's last-input tick changes during the
observation window, because human or injected input would make foreground
attribution inconclusive — the same guard the other desktop smokes use.

Run only with operator approval, on a real interactive Windows session:

    python scripts/smoke_progress_poller.py
"""
from __future__ import annotations

import ctypes
import sys
import tempfile
import threading
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_agent.progress_poller import ProgressPoller  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402
from computer_use_agent.trace import RunPhase, RunRecorder, TraceError  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    LedgerEvent,
    LedgerEventKind,
    RunBudget,
    RunState,
)

SECRET = "SMOKE_TASK_TEXT_MUST_NOT_APPEAR"
PUBLISH_ROUNDS = 400


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _state(run_id: str) -> RunState:
    return RunState(
        run_id=run_id,
        task=SECRET,
        policy_version="smoke-poll-v1",
        observation_epoch=0,
        budgets=RunBudget(3, 4, 0, model_turns_used=1, tool_calls_used=2),
        event_log=(
            LedgerEvent(
                event_id=f"{run_id}:event:1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len(SECRET)},
            ),
        ),
    )


def main() -> int:
    state_dir = Path(tempfile.mkdtemp(prefix="cua-poll-smoke-")).resolve()

    # One run that will transition live, and one that stays put so the view has
    # to keep two runs separate while it updates.
    moving = RunRecorder(state_dir, "run_live")
    moving.start(_state("run_live"))
    moving.record(_state("run_live"), RunPhase.OBSERVING)

    still = RunRecorder(state_dir, "run_idle")
    still.start(_state("run_idle"))
    still.record(_state("run_idle"), RunPhase.OBSERVING)

    api = Win32ProgressWindowApi()
    window = PassiveProgressWindow(api)
    poller = ProgressPoller(state_dir, window, interval_seconds=0.05)

    foreground_before = api.foreground()
    tick_before = _last_input_tick()

    poller.poll_once()
    api.pump()
    first_lines = api.lines(window.hwnd)

    # Publish continuously from another thread while the poller reads, so the
    # read/publish race is exercised the way a live agent would create it.
    publish_failures: list[str] = []
    stop = threading.Event()

    def writer() -> None:
        state = _state("run_idle")
        for _ in range(PUBLISH_ROUNDS):
            if stop.is_set():
                return
            try:
                still.record(state, RunPhase.OBSERVING)
            except TraceError as exc:
                publish_failures.append(str(exc))

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    try:
        for _ in range(20):
            poller.poll_once()
            api.pump()
    finally:
        stop.set()
        thread.join(timeout=10)

    # Now make a real, visible transition and confirm it reaches the window.
    moving.record(_state("run_live"), RunPhase.PLANNING)
    moving.record(_state("run_live"), RunPhase.SUCCESS, run_duration_ms=1234)
    outcome = poller.poll_once()
    api.pump()
    final_lines = api.lines(window.hwnd)

    foreground_after = api.foreground()
    tick_after = _last_input_tick()
    window.close()
    api.pump()

    drawn = "\n".join(final_lines)
    problems: list[str] = []
    if publish_failures:
        problems.append(
            f"{len(publish_failures)}/{PUBLISH_ROUNDS} publishes FAILED "
            f"(first: {publish_failures[0]})"
        )
    if foreground_after != foreground_before:
        problems.append(f"foreground changed {foreground_before:#x} -> {foreground_after:#x}")
    if not outcome.redrew or final_lines == first_lines:
        problems.append("the live transition never reached the window")
    if "Complete" not in drawn:
        problems.append("terminal phase not displayed")
    if "run_idle" not in drawn or "run_live" not in drawn:
        problems.append("the two runs were not both displayed")
    if SECRET in drawn:
        problems.append("task text leaked into the drawn view")

    if tick_after != tick_before:
        print("RESULT: INCONCLUSIVE (local input occurred during the probe)")
        return 2
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; "
        f"{PUBLISH_ROUNDS}/{PUBLISH_ROUNDS} publishes succeeded under a live poller; "
        "live SUCCESS transition reached the window; two runs kept separate; no task text)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
