"""Isolated smoke for the passive operator progress window (delivery step 2).

Draws the real ctypes window over synthetic view models and confirms the one
acceptance property that unit tests can only assert in injectable form: opening,
refreshing, moving, and toggling topmost on a live desktop does **not** change
the foreground window the operator was using.

The probe discards its result if the system's last-input tick changes during
the observation window, because human or injected input would make foreground
attribution inconclusive — the same guard the background-focus smoke uses.

Run only with operator approval, on a real interactive Windows session:

    python scripts/smoke_progress_window.py
"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_agent.progress_view import (  # noqa: E402
    CallBudget,
    ProgressProjection,
    RunProgressView,
)
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _synthetic() -> ProgressProjection:
    def view(run_id, phase, state, **over):
        base = dict(
            run_id=run_id, phase=phase, display_state=state, is_terminal=False,
            liveness_known=False, needs_reobserve=False,
            model_calls=CallBudget(6, 9), tool_calls=CallBudget(4, 12),
            input_tokens=18400, output_tokens=2100, token_coverage_known=False,
            image_results=2, tool_failures=0, elapsed_known=False,
            duration_ms=None, failure_code=None,
        )
        base.update(over)
        return RunProgressView(**base)

    return ProgressProjection(
        views=(
            view("run_ab12", "PLANNING", "In progress at last checkpoint; liveness unknown"),
            view("run_cd34", "WAITING_APPROVAL", "Waiting approval"),
            view(
                "run_ef56", "UNKNOWN_OUTCOME", "Uncertain; re-observe before retry",
                is_terminal=True, liveness_known=True, needs_reobserve=True,
            ),
            view(
                "run_gh78", "SUCCESS", "Complete",
                is_terminal=True, liveness_known=True, duration_ms=20345,
            ),
        ),
        unavailable_run_ids=("run_torn",),
        unavailable_unnamed=1,
    )


def main() -> int:
    api = Win32ProgressWindowApi()
    window = PassiveProgressWindow(api)

    foreground_before = api.foreground()
    tick_before = _last_input_tick()

    window.open(_synthetic())
    api.pump()
    window.update(_synthetic())
    api.pump()
    window.move(80, 80)
    api.pump()
    window.set_topmost(False)
    window.set_topmost(True)
    api.pump()
    time.sleep(0.4)
    api.pump()

    foreground_after = api.foreground()
    tick_after = _last_input_tick()
    window.close()
    api.pump()

    if tick_after != tick_before:
        print("RESULT: INCONCLUSIVE (local input occurred during the probe)")
        return 2
    if foreground_after != foreground_before:
        print(
            "RESULT: FAIL (foreground changed "
            f"{foreground_before:#x} -> {foreground_after:#x})"
        )
        return 1
    print(f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; passive window drawn)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
