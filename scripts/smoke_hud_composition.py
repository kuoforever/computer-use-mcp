"""Live composition smoke for all three HUD surfaces at once (`GDA-HUD-009`).

Every earlier probe drove one surface. Driving two exposed a defect that made
the workflow HUD silently absent from a real Demo, so the same question is
asked of the full set the Demo actually runs: the full-screen Presence halo,
the workflow Progress HUD, and the Decision Card.

The properties only hold when all three exist:

* the halo is click-through and non-activating. It covers the entire screen, so
  if it were not, it would swallow every click meant for the Decision Card's
  buttons -- the operator would see an approval they could not answer;
* neither passive surface ever becomes foreground, including while Progress
  repaints;
* the Decision Card alone takes focus, even under a full-screen topmost halo;
* the halo's opaque regions -- its border ring and its phase tab -- cover
  neither of the other two surfaces;
* Progress and the card do not overlap each other and both stay inside the
  monitor work area;
* after the card exits the prior foreground is back, and neither passive
  surface has inherited it.

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
from computer_use_agent.presence import (  # noqa: E402
    DesktopAuthority,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
)
from computer_use_agent.presence_window import (  # noqa: E402
    PassivePresenceWindow,
    presence_geometry,
)
from computer_use_agent.presence_window_win32 import (  # noqa: E402
    Win32PresenceWindowApi,
)
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.trace import RunPhase  # noqa: E402

_WM_CLOSE = 0x0010
_WM_NCHITTEST = 0x0084
_WM_MOUSEACTIVATE = 0x0021
_HTTRANSPARENT = -1
_MA_NOACTIVATE = 3
_MONITOR_DEFAULTTONEAREST = 2

_CARD_TITLE = "Decision required · action blocked"
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


def _halo_opaque_regions(geometry: object) -> tuple[tuple[int, int, int, int], ...]:
    """The halo pixels that are actually painted, in screen coordinates.

    Everything else is removed by the colour key, so only these can cover
    another surface. The border is a ring, expressed as the region outside the
    inset interior; the phase tab is the solid block in the top-left corner.
    """

    border = geometry.border_px  # type: ignore[attr-defined]
    inset = geometry.label_inset_px  # type: ignore[attr-defined]
    left = geometry.x  # type: ignore[attr-defined]
    top = geometry.y  # type: ignore[attr-defined]
    right = left + geometry.width  # type: ignore[attr-defined]
    bottom = top + geometry.height  # type: ignore[attr-defined]
    tab_width = min(360, max(240, geometry.width // 5))  # type: ignore[attr-defined]
    tab_height = max(42, inset * 2 + 18)
    return (
        (left, top, right, top + border),
        (left, bottom - border, right, bottom),
        (left, top, left + border, bottom),
        (right - border, top, right, bottom),
        (left + border, top + border, left + tab_width, top + tab_height),
    )


def _clearance(
    rect: tuple[int, int, int, int],
    regions: tuple[tuple[int, int, int, int], ...],
) -> int:
    """Smallest gap between one surface and any painted halo pixel.

    Not overlapping is the acceptance condition, but the margin is worth
    printing: a border widened or a card widened past this number turns a pass
    into a surface covering another one, and a bare pass would not warn.
    """

    gaps = []
    for left, top, right, bottom in regions:
        horizontal = max(left - rect[2], rect[0] - right)
        vertical = max(top - rect[3], rect[1] - bottom)
        gaps.append(max(horizontal, vertical))
    return min(gaps)


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

    presence_api = Win32PresenceWindowApi()
    presence = PassivePresenceWindow(presence_api)
    progress_api = Win32ProgressWindowApi()
    progress = DemoWorkflowProgress(
        PassiveProgressWindow(progress_api),
        pump=progress_api.pump,
        interval_seconds=0.05,
    )
    card_api = Win32DecisionCardWindowApi()
    card_result: list[str | None] = [None]

    def keep_alive(seconds: float) -> None:
        """Wait while still pumping the halo, which has no worker of its own."""

        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            presence_api.pump()
            time.sleep(0.05)

    try:
        presence.sync(
            PresenceSnapshot(
                phase=PresencePhase.EXECUTING,
                authority=DesktopAuthority.HELD,
                estop_engaged=False,
                preferences=PresencePreferences(),
            )
        )
        presence_api.pump()
        presence_hwnd = presence.hwnd
        if presence_hwnd is None:
            print("RESULT: FAIL (the presence halo never opened)")
            return 1

        # A full-screen halo that is not click-through would swallow every
        # click meant for the card's buttons.
        user32.SendMessageW.restype = ctypes.c_longlong
        hit = int(user32.SendMessageW(wintypes.HWND(presence_hwnd), _WM_NCHITTEST, 0, 0))
        activate = int(
            user32.SendMessageW(wintypes.HWND(presence_hwnd), _WM_MOUSEACTIVATE, 0, 0)
        )
        if hit != _HTTRANSPARENT:
            problems.append(f"the halo is not click-through (hit test {hit})")
        if activate != _MA_NOACTIVATE:
            problems.append(f"the halo can be activated by a click ({activate})")
        if int(user32.GetForegroundWindow()) == presence_hwnd:
            problems.append("the halo took foreground")

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
            keep_alive(0.4)
            foreground = int(user32.GetForegroundWindow())
            if foreground == progress_hwnd:
                problems.append("the passive progress surface took foreground")
            if foreground == presence_hwnd:
                problems.append("the halo took foreground during a progress repaint")
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
            keep_alive(1.2)
            focused = int(user32.GetForegroundWindow())
            if focused != card_hwnd:
                problems.append(
                    f"the decision card did not take focus ({focused:#x})"
                )
            if focused in {progress_hwnd, presence_hwnd}:
                problems.append("a passive surface took focus instead of the card")

            card_rect = _rect(user32, card_hwnd)
            progress_rect = _rect(user32, progress_hwnd)
            work = _work_area(user32, card_hwnd)
            geometry = presence_geometry(presence_api.display_bounds())
            opaque = _halo_opaque_regions(geometry)
            print(f"halo     {geometry.width}x{geometry.height} border {geometry.border_px}px")
            print(f"progress rect {progress_rect}")
            print(f"card     rect {card_rect}")
            print(f"work area     {work}")
            if _overlaps(card_rect, progress_rect):
                problems.append("the two HUD surfaces overlap each other")
            if not _contains(work, card_rect):
                problems.append("the decision card leaves the work area")
            if not _contains(work, progress_rect):
                problems.append("the progress surface leaves the work area")
            for region in opaque:
                if _overlaps(region, card_rect):
                    problems.append(f"a painted halo region {region} covers the card")
                if _overlaps(region, progress_rect):
                    problems.append(f"a painted halo region {region} covers progress")
            print(
                f"clearance from painted halo: card {_clearance(card_rect, opaque)}px, "
                f"progress {_clearance(progress_rect, opaque)}px"
            )

            user32.PostMessageW(wintypes.HWND(card_hwnd), _WM_CLOSE, 0, 0)

        deadline = time.monotonic() + 45
        while worker.is_alive() and time.monotonic() < deadline:
            presence_api.pump()
            time.sleep(0.05)
        if worker.is_alive():
            problems.append("the decision card never closed")
        keep_alive(0.8)

        if card_result[0] is not None:
            problems.append(f"closing selected {card_result[0]!r} instead of denying")
        restored = int(user32.GetForegroundWindow())
        if foreground_before and restored != foreground_before:
            problems.append(
                f"prior foreground was not restored "
                f"({foreground_before:#x} -> {restored:#x})"
            )
        if restored in {progress_hwnd, presence_hwnd}:
            problems.append("a passive surface inherited the foreground")
    finally:
        progress.release()
        presence.close()
        presence_api.pump()

    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        f"RESULT: PASS (the halo stayed click-through and non-activating so it "
        f"could not swallow the card's clicks; neither passive surface took "
        f"foreground across three repaints; the card alone took focus; no "
        f"painted halo region covered another surface; progress and the card do "
        f"not overlap and both stay inside the work area; closing denied and "
        f"restored {foreground_before:#x})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
