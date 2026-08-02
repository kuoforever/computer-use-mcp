"""Live composition smoke for both passive HUD surfaces at once (`GDA-HUD-009`).

Every previous probe drove one surface. This opens the workflow Progress HUD
and the Decision Card together, which is the only arrangement an operator
actually sees during an approval, and checks the properties that only hold when
both exist:

* Progress never becomes foreground, including while it repaints;
* the Decision Card is the only surface that takes focus;
* the two rectangles do not overlap each other;
* both stay inside the monitor work area;
* after the card exits, the window that was foreground before it opened has the
  foreground back, and Progress still does not.

No Runner, MCP server, provider, or application is opened. Chrome and Word are
deliberately absent: this covers surface-to-surface composition only, and the
`GDA-HUD-009` clause about Chrome/Word remaining foreground needs the bounded
Demo and its own evidence plan.
"""

from __future__ import annotations

import ctypes
import sys
import threading
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

from computer_use_agent.decision_card_window import DecisionCardButton  # noqa: E402
from computer_use_agent.decision_card_window_win32 import (  # noqa: E402
    Win32DecisionCardWindowApi,
)
from computer_use_agent.demo_workflow_progress import (  # noqa: E402
    DemoWorkflowProgress,
)
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.trace import RunPhase  # noqa: E402

_WM_CLOSE = 0x0010
_MONITOR_DEFAULTTONEAREST = 2

_CARD_TITLE = "Needs input · approval locked"
_BUTTONS = (
    DecisionCardButton("option_approve_exact_effect", "Approve once"),
    DecisionCardButton("option_reobserve", "Re-observe"),
    DecisionCardButton("option_defer", "Defer"),
    DecisionCardButton("option_deny", "Deny"),
)
_INSTRUCTION = "\n".join(
    (
        "NEEDS INPUT  ·  APPROVAL LOCKED",
        "Composition smoke; no effect is proposed",
        "APPROVAL 1/1  ·  Synthetic review",
        "WORKFLOW 4/6  ·  Add the verified source note",
    )
)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _rect(user32: ctypes.WinDLL, hwnd: int) -> tuple[int, int, int, int]:
    rectangle = wintypes.RECT()
    user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rectangle))
    return (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)


def _work_area(user32: ctypes.WinDLL, hwnd: int) -> tuple[int, int, int, int]:
    monitor = user32.MonitorFromWindow(wintypes.HWND(hwnd), _MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    user32.GetMonitorInfoW(monitor, ctypes.byref(info))
    return (info.rcWork.left, info.rcWork.top, info.rcWork.right, info.rcWork.bottom)


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _contains(outer: tuple[int, int, int, int], inner: tuple[int, int, int, int]) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _find_card(user32: ctypes.WinDLL, *, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = user32.FindWindowW(None, _CARD_TITLE)
        if found:
            return int(found)
        time.sleep(0.05)
    return 0


def main() -> int:
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]

    problems: list[str] = []
    foreground_before = int(user32.GetForegroundWindow())

    progress_api = Win32ProgressWindowApi()
    progress = DemoWorkflowProgress(
        PassiveProgressWindow(progress_api),
        pump=progress_api.pump,
        interval_seconds=0.05,
    )
    card_api = Win32DecisionCardWindowApi()
    card_result: list[str | None] = [None]

    try:
        progress.on_phase(RunPhase.OBSERVING)
        deadline = time.monotonic() + 5.0
        while progress.window.hwnd is None and time.monotonic() < deadline:
            time.sleep(0.05)
        progress_hwnd = progress.window.hwnd
        if progress_hwnd is None:
            print("RESULT: FAIL (the progress surface never opened)")
            return 1

        # Repaint the passive surface several times; none may take foreground.
        for step in (6, 9, 15):
            progress.on_provider_step(step)
            time.sleep(0.4)
            if int(user32.GetForegroundWindow()) == progress_hwnd:
                problems.append("the passive progress surface took foreground")
        after_progress = int(user32.GetForegroundWindow())
        if foreground_before and after_progress != foreground_before:
            problems.append(
                f"progress updates moved the foreground "
                f"({foreground_before:#x} -> {after_progress:#x})"
            )

        def open_card() -> None:
            card_result[0] = card_api.choose(
                title=_CARD_TITLE,
                instruction=_INSTRUCTION,
                content="Composition smoke. Esc, close, or timeout denies.",
                expanded_information="No evidence is bound to this synthetic card.",
                buttons=_BUTTONS,
                timeout_seconds=30,
            )

        worker = threading.Thread(target=open_card, name="card", daemon=True)
        worker.start()
        card_hwnd = _find_card(user32)
        if not card_hwnd:
            problems.append("the decision card never appeared")
        else:
            time.sleep(1.2)
            focused = int(user32.GetForegroundWindow())
            if focused != card_hwnd:
                problems.append(
                    f"the decision card did not take focus ({focused:#x})"
                )
            if focused == progress_hwnd:
                problems.append("the passive surface took focus instead of the card")

            card_rect = _rect(user32, card_hwnd)
            progress_rect = _rect(user32, progress_hwnd)
            work = _work_area(user32, card_hwnd)
            print(f"progress rect {progress_rect}")
            print(f"card     rect {card_rect}")
            print(f"work area     {work}")
            if _overlaps(card_rect, progress_rect):
                problems.append("the two HUD surfaces overlap each other")
            if not _contains(work, card_rect):
                problems.append("the decision card leaves the work area")
            if not _contains(work, progress_rect):
                problems.append("the progress surface leaves the work area")

            user32.PostMessageW(wintypes.HWND(card_hwnd), _WM_CLOSE, 0, 0)

        worker.join(timeout=45)
        if worker.is_alive():
            problems.append("the decision card never closed")
        time.sleep(0.8)

        if card_result[0] is not None:
            problems.append(f"closing selected {card_result[0]!r} instead of denying")
        restored = int(user32.GetForegroundWindow())
        if foreground_before and restored != foreground_before:
            problems.append(
                f"prior foreground was not restored "
                f"({foreground_before:#x} -> {restored:#x})"
            )
        if restored == progress_hwnd:
            problems.append("the passive surface inherited the foreground")
    finally:
        progress.release()

    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        f"RESULT: PASS (progress repainted three times without taking foreground; "
        f"the card alone took focus; the two rectangles do not overlap and both "
        f"stay inside the work area; closing denied and restored "
        f"{foreground_before:#x})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
