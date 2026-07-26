"""Live smoke for opt-in ordinary-run progress-window lifecycle wiring."""

from __future__ import annotations

import ctypes
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_agent.progress_lifecycle import RunProgressCoordinator  # noqa: E402
from computer_use_agent.progress_poller import ProgressPoller  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402
from computer_use_agent.trace import RunPhase, RunRecorder  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    LedgerEvent,
    LedgerEventKind,
    RunBudget,
    RunState,
)

SECRET = "PROGRESS_LIFECYCLE_TASK_MUST_NOT_APPEAR"


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _state() -> RunState:
    return RunState(
        run_id="run_lifecycle",
        task=SECRET,
        policy_version="progress-lifecycle-v1",
        observation_epoch=0,
        budgets=RunBudget(2, 2, 0),
        event_log=(
            LedgerEvent(
                event_id="run_lifecycle:event:1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len(SECRET)},
            ),
        ),
    )


def _wait_for(predicate, *, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="cua-progress-lifecycle-") as raw_dir:
        state_dir = Path(raw_dir).resolve()
        state = _state()
        recorder = RunRecorder(state_dir, state.run_id)
        recorder.start(state)
        recorder.record(state, RunPhase.OBSERVING)

        api = Win32ProgressWindowApi()
        window = PassiveProgressWindow(api)
        poller = ProgressPoller(state_dir, window, interval_seconds=0.05)
        lifecycle = RunProgressCoordinator(poller, pump=api.pump)

        foreground_before = api.foreground()
        tick_before = _last_input_tick()
        lifecycle.on_phase(RunPhase.OBSERVING)

        opened = _wait_for(
            lambda: window.hwnd is not None
            and "run_lifecycle" in "\n".join(api.lines(window.hwnd))
        )
        recorder.record(state, RunPhase.PLANNING)
        lifecycle.on_phase(RunPhase.PLANNING)
        recorder.record(state, RunPhase.SUCCESS, run_duration_ms=25)
        lifecycle.on_phase(RunPhase.SUCCESS)
        completed = _wait_for(
            lambda: window.hwnd is not None
            and "History  1" in api.lines(window.hwnd)
            and "Complete" in "\n".join(api.lines(window.hwnd))
        )
        drawn = "" if window.hwnd is None else "\n".join(api.lines(window.hwnd))
        foreground_after = api.foreground()
        lifecycle.release()
        tick_after = _last_input_tick()

        problems: list[str] = []
        if not opened:
            problems.append("background lifecycle never opened the progress window")
        if not completed:
            problems.append("durable SUCCESS never reached the progress window")
        if lifecycle.error_count:
            problems.append("background lifecycle reported a surface failure")
        if lifecycle.running:
            problems.append("background UI thread survived release")
        if window.hwnd is not None:
            problems.append("release did not destroy the native window")
        if foreground_after != foreground_before:
            problems.append(
                f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
            )
        if SECRET in drawn:
            problems.append("private task content leaked into the progress window")

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
            "durable OBSERVING and SUCCESS reached the background-owned window; "
            "release joined the UI thread and destroyed the window; no private content)"
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
