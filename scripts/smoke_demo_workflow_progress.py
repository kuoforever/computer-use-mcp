"""Live smoke for the Demo-only workflow HUD lifecycle.

`GDA-HUD-005` and `GDA-HUD-006` were offline-verified only: `DemoWorkflowProgress`
had never driven a real non-activating window. This drives it through the fixed
chapter transitions against the real Win32 surface and asserts the properties
only a live run can show — that the worker thread paints real pixels, that the
operator's foreground never moves, and that release destroys the window.

No Runner, MCP server, provider, Chrome/Word action, approval dispatch, network
request, or complete Demo runs here. Every input is a fixed integer boundary or
a durable phase enum.
"""

from __future__ import annotations

import ctypes
import re
import sys
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

from computer_use_agent.demo_workflow_progress import (  # noqa: E402
    DEMO_TERMINAL_PROVIDER_STEP,
    DemoWorkflowProgress,
)
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.trace import RunPhase  # noqa: E402

#: Text that belongs to the generic ``state_dir`` diagnostics view. The workflow
#: HUD replaced that surface for the Demo precisely so tool-call budgets stop
#: competing with chapter counts, so none of it may reach these pixels.
FORBIDDEN_FRAGMENTS = (
    "calls  model",
    "tokens in",
    "screenshots",
    "liveness unknown",
)

#: The approval ``n/7`` count belongs to the Decision Card. ``APPROVAL NEEDED``
#: is legitimate workflow text; an approval *count* here would be exactly the
#: mixed-total confusion `GDA-HUD-005` exists to remove.
FORBIDDEN_PATTERN = re.compile(r"APPROVAL\s+\d+\s*/\s*\d+")


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _wait_for(predicate, *, timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def main() -> int:
    api = Win32ProgressWindowApi()
    window = PassiveProgressWindow(api)
    lifecycle = DemoWorkflowProgress(window, pump=api.pump, interval_seconds=0.05)

    def drawn() -> str:
        hwnd = window.hwnd
        return "" if hwnd is None else "\n".join(api.lines(hwnd))

    foreground_before = api.foreground()
    tick_before = _last_input_tick()
    observed: list[str] = []

    lifecycle.on_phase(RunPhase.OBSERVING)
    opened = _wait_for(
        lambda: window.hwnd is not None
        and "Review the public collaboration guide" in drawn()
    )
    first_open_expanded = window.expanded
    observed.append(drawn())

    lifecycle.on_provider_step(9)
    advanced = _wait_for(lambda: "Add the verified source note" in drawn())
    observed.append(drawn())

    lifecycle.on_phase(RunPhase.WAITING_APPROVAL)
    waiting = _wait_for(lambda: "APPROVAL NEEDED" in drawn())
    observed.append(drawn())

    lifecycle.on_phase(RunPhase.EXECUTING)
    resumed = _wait_for(lambda: "APPROVAL NEEDED" not in drawn())

    lifecycle.on_provider_step(DEMO_TERMINAL_PROVIDER_STEP)
    held = _wait_for(lambda: "Verify the saved document" in drawn())
    held_open = "ALL WORKFLOW STEPS RESOLVED" not in drawn()

    lifecycle.on_phase(RunPhase.SUCCESS)
    finished = _wait_for(lambda: "ALL WORKFLOW STEPS RESOLVED" in drawn())
    observed.append(drawn())

    final = drawn()
    foreground_after = api.foreground()
    lifecycle.release()
    tick_after = _last_input_tick()

    problems: list[str] = []
    if not opened:
        problems.append("the durable phase never opened the workflow window")
    if not first_open_expanded:
        problems.append("first open did not show every chapter")
    if not advanced:
        problems.append("a provider boundary never reached real pixels")
    if not waiting:
        problems.append("approval wait never reached real pixels")
    if not resumed:
        problems.append("the surface stayed in approval wait after execution resumed")
    if not held:
        problems.append("the terminal boundary never reached real pixels")
    if not held_open:
        problems.append(
            "the last chapter completed before the durable run said so"
        )
    if not finished:
        problems.append("durable SUCCESS never resolved every chapter")
    if lifecycle.rejected_count:
        problems.append(
            f"{lifecycle.rejected_count} valid transitions were rejected"
        )
    if lifecycle.error_count:
        problems.append("the passive surface reported a failure")
    if lifecycle.running:
        problems.append("the UI thread survived release")
    if window.hwnd is not None:
        problems.append("release did not destroy the native window")
    if foreground_after != foreground_before:
        problems.append(
            f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
        )
    for fragment in FORBIDDEN_FRAGMENTS:
        if any(fragment in frame for frame in observed):
            problems.append(
                f"run diagnostics leaked into the workflow HUD: {fragment!r}"
            )
    if any(FORBIDDEN_PATTERN.search(frame) for frame in observed):
        problems.append("an approval n/7 count leaked into the workflow HUD")

    if tick_after != tick_before:
        print("RESULT: INCONCLUSIVE (local input occurred during the probe)")
        return 2
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(final)
    print(
        f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; "
        "first open showed every chapter; boundary, approval wait, held terminal "
        "chapter, and durable SUCCESS each reached the worker-owned window; "
        "release joined the UI thread and destroyed it; no run diagnostics)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
