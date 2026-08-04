"""Live smoke for the Decision Card's safe exits (`GDA-HUD-004`).

The rule the issue states is that "Locked" must never mean trapping the
operator. Dispatch pausing while the card is open was already structural: the
Runner awaits `request_approval`, so it cannot proceed. What had no live
evidence is the other half -- that every way out of the card is a safe denial
and gives the previous application its foreground back.

This drives all three non-choice exits against the real window:

* `Esc` posted to the card;
* the caption close button, as `WM_CLOSE`;
* the countdown expiring.

Each must return no selection, and the foreground window observed before the
card opened must be foreground again afterwards. A positive approval is never
produced here, because none of these paths may produce one.

No Runner, MCP server, provider, application, or desktop action is opened. The
card content is fixed synthetic text.
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

_WM_CLOSE = 0x0010
_WM_KEYDOWN = 0x0100
_VK_ESCAPE = 0x1B

_TITLE = "Decision required · action blocked"
_BUTTONS = (
    DecisionCardButton("option_approve_exact_effect", "Approve once"),
    DecisionCardButton("option_reobserve", "Re-observe"),
    DecisionCardButton("option_defer", "Defer"),
    DecisionCardButton("option_deny", "Deny"),
)
_INSTRUCTION = "\n".join(
    (
        "NEEDS INPUT  ·  APPROVAL LOCKED",
        "Exit-path smoke; no effect is proposed",
        "APPROVAL 1/1  ·  Synthetic review",
        "",
    )
)


def _find_card(user32: ctypes.WinDLL, *, timeout: float = 10.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        # A NULL HWND comes back as None through ctypes, not 0.
        found = user32.FindWindowW(None, _TITLE)
        if found:
            return int(found)
        time.sleep(0.05)
    return 0


def _run_exit(
    label: str,
    *,
    timeout_seconds: int,
    act: object,
) -> tuple[str, bool, str | None, int, int]:
    """Open one real card, trigger one exit, and report what came back."""

    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]

    api = Win32DecisionCardWindowApi()
    foreground_before = int(user32.GetForegroundWindow())
    result: list[str | None] = [None]
    failure: list[BaseException | None] = [None]

    def call() -> None:
        try:
            result[0] = api.choose(
                # The caption is what FindWindowW matches on.
                title=_TITLE,
                instruction=_INSTRUCTION,
                content="Exit-path smoke. Esc, close, or timeout denies.",
                expanded_information="No evidence is bound to this synthetic card.",
                buttons=_BUTTONS,
                timeout_seconds=timeout_seconds,
            )
        except BaseException as exc:  # noqa: BLE001 - reported, not raised
            failure[0] = exc

    worker = threading.Thread(target=call, name=f"card-{label}", daemon=True)
    worker.start()

    hwnd = _find_card(user32)
    opened = bool(hwnd)
    if opened and callable(act):
        # Let the card settle and finish taking foreground before acting.
        time.sleep(1.0)
        act(user32, hwnd)

    worker.join(timeout=timeout_seconds + 15)
    alive = worker.is_alive()
    time.sleep(0.6)
    foreground_after = int(user32.GetForegroundWindow())

    if failure[0] is not None:
        raise failure[0]
    if alive:
        raise RuntimeError(f"the card never closed for exit {label!r}")
    return label, opened, result[0], foreground_before, foreground_after


def main() -> int:
    def send_escape(user32: ctypes.WinDLL, hwnd: int) -> None:
        user32.PostMessageW(wintypes.HWND(hwnd), _WM_KEYDOWN, _VK_ESCAPE, 0)

    def send_close(user32: ctypes.WinDLL, hwnd: int) -> None:
        user32.PostMessageW(wintypes.HWND(hwnd), _WM_CLOSE, 0, 0)

    cases = (
        ("escape", 60, send_escape),
        ("close", 60, send_close),
        ("timeout", 5, None),
    )

    problems: list[str] = []
    for label, timeout_seconds, act in cases:
        name, opened, selection, before, after = _run_exit(
            label, timeout_seconds=timeout_seconds, act=act
        )
        print(
            f"{name:<8} opened={opened} selection={selection!r} "
            f"foreground {before:#x} -> {after:#x}"
        )
        if not opened:
            problems.append(f"{name}: the card never appeared")
        if selection is not None:
            problems.append(f"{name}: returned {selection!r} instead of a denial")
        if before and after != before:
            problems.append(
                f"{name}: foreground was not restored ({before:#x} -> {after:#x})"
            )

    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        "RESULT: PASS (Esc, close, and timeout each denied without selecting an "
        "option, and each restored the previous foreground window)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
