"""Bounded native accessibility smoke for the three operator surfaces.

The probe opens no provider, MCP, application, or desktop-action port.  The
passive surfaces must preserve the foreground window.  The focus-taking
Decision Card is inspected through UI Automation and resolved with keyboard
navigation to its safe Deny option.
"""
from __future__ import annotations

import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

import uiautomation as auto

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.decision_card_window import DecisionCardButton  # noqa: E402
from computer_use_agent.decision_card_window_win32 import (  # noqa: E402
    Win32DecisionCardWindowApi,
)
from computer_use_agent.operator_accessibility import (  # noqa: E402
    OperatorAccessibilitySettings,
)
from computer_use_agent.presence import (  # noqa: E402
    DesktopAuthority,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
)
from computer_use_agent.presence_window import PassivePresenceWindow  # noqa: E402
from computer_use_agent.presence_window_win32 import (  # noqa: E402
    Win32PresenceWindowApi,
)
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)


_TITLE = "Accessibility smoke decision"


def _foreground() -> int:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    return int(user32.GetForegroundWindow() or 0)


def _wait_for_window(title: str, seconds: float = 5.0) -> int:
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        hwnd = int(user32.FindWindowW(None, title) or 0)
        if hwnd:
            return hwnd
        time.sleep(0.05)
    raise RuntimeError(f"window did not appear: {title}")


def _control_rows(control, depth: int = 0) -> list[dict[str, object]]:  # noqa: ANN001
    rows = [
        {
            "name": str(control.Name or ""),
            "type": str(control.ControlTypeName or ""),
            "focused": bool(control.HasKeyboardFocus),
        }
    ]
    if depth < 4:
        for child in control.GetChildren():
            rows.extend(_control_rows(child, depth + 1))
    return rows


def _passive_surface_smoke(
    accessibility: OperatorAccessibilitySettings,
) -> dict[str, object]:
    before = _foreground()
    progress = Win32ProgressWindowApi(accessibility=accessibility)
    progress_hwnd = progress.create(
        ex_style=0x08000088,
        style=0x80000000,
        title="Computer Use",
    )
    compact = (
        "COMPUTER USE  ·  IN PROGRESS",
        "Public web to Word",
        "0 completed  ·  6 not started  ·  6 total",
        "CURRENT STEP 1 OF 6",
        "Prepare workspace",
        "Desktop",
    )
    details = compact + ("WORKFLOW CHECKLIST", "○  1  Prepare workspace")
    presence_api = Win32PresenceWindowApi(accessibility=accessibility)
    presence = PassivePresenceWindow(presence_api)
    try:
        progress.set_workflow_lines(
            progress_hwnd,
            compact_lines=compact,
            expanded_lines=details,
            expanded=False,
            accent_rgb=0x2F80ED,
            on_toggle=lambda _expanded: None,
        )
        progress.show_noactivate(progress_hwnd)
        progress.pump()
        presence_result = presence.sync(
            PresenceSnapshot(
                phase=PresencePhase.WAITING_APPROVAL,
                authority=DesktopAuthority.WAITING,
                preferences=PresencePreferences(
                    reduced_motion=accessibility.reduced_motion,
                    high_contrast=accessibility.high_contrast,
                ),
            )
        )
        presence_api.pump()
        after = _foreground()
        progress_name = str(auto.ControlFromHandle(progress_hwnd).Name)
        if presence.hwnd is None:
            raise RuntimeError("presence window was not created")
        presence_name = str(auto.ControlFromHandle(presence.hwnd).Name)
        if before != after:
            raise RuntimeError("passive operator surface changed foreground")
        if "Current step 1 of 6" not in progress_name:
            raise RuntimeError("progress accessible summary is incomplete")
        if presence_name != "Computer Use. Approval. Needs input.":
            raise RuntimeError("presence accessible name is incomplete")
        return {
            "foreground_unchanged": True,
            "progress_name": progress_name,
            "presence_name": presence_name,
            "presence_capture_excluded": presence_result.capture_excluded,
        }
    finally:
        presence.close()
        progress.destroy(progress_hwnd)


def _decision_card_smoke(
    accessibility: OperatorAccessibilitySettings,
) -> dict[str, object]:
    result: list[str | None] = []
    error: list[BaseException] = []

    def choose() -> None:
        try:
            result.append(
                Win32DecisionCardWindowApi(accessibility=accessibility).choose(
                    title=_TITLE,
                    instruction=(
                        "NEEDS INPUT  ·  APPROVAL LOCKED\n"
                        "Save the research brief\n"
                        "APPROVAL 1/1  ·  Microsoft Word\n"
                        "WORKFLOW 6/6  ·  Save and verify"
                    ),
                    content="One exact local save requires review.",
                    expanded_information="Evidence is digest-bound and local.",
                    buttons=(
                        DecisionCardButton("option_approve_exact_effect", "Approve once"),
                        DecisionCardButton("option_reobserve", "Check screen again"),
                        DecisionCardButton("option_defer", "Pause and inspect"),
                        DecisionCardButton("option_deny", "Deny"),
                    ),
                    timeout_seconds=20,
                )
            )
        except BaseException as exc:  # pragma: no cover - native diagnostic
            error.append(exc)

    worker = threading.Thread(target=choose, daemon=True)
    worker.start()
    hwnd = _wait_for_window(_TITLE)
    user32 = ctypes.windll.user32
    with auto.UIAutomationInitializerInThread():
        rows = _control_rows(auto.ControlFromHandle(hwnd))
        names = {str(row["name"]): str(row["type"]) for row in rows if row["name"]}
        for expected in (
            "NEEDS INPUT  ·  APPROVAL LOCKED",
            "Save the research brief",
            "APPROVAL 1/1  ·  Microsoft Word",
            "WORKFLOW 6/6  ·  Save and verify",
            "Approve once",
            "Check screen again",
            "Pause and inspect",
            "Deny",
        ):
            if expected not in names:
                raise RuntimeError(f"missing UIA control: {expected}")
        if names["Deny"] != "ButtonControl":
            raise RuntimeError("deny is not exposed as a UIA Button")
        focused = auto.GetFocusedControl()
        initial_focus = str(focused.Name or "")
        if initial_focus != "Deny":
            raise RuntimeError(f"safe initial focus missing: {initial_focus}")

        # Deny is the final tab stop. Tab wraps to the first control (details
        # toggle), then five more Tabs reach Deny after the details pane opens.
        auto.SendKeys("{Tab}", waitTime=0.1)
        toggle_focus = str(auto.GetFocusedControl().Name or "")
        if toggle_focus != "Show details":
            raise RuntimeError(f"details toggle name is invalid: {toggle_focus}")
        auto.SendKeys("{Enter}", waitTime=0.1)
        time.sleep(0.3)
        expanded_rows = _control_rows(auto.ControlFromHandle(hwnd))
        expanded_name_types = {
            (str(row["name"]), str(row["type"]))
            for row in expanded_rows
            if row["name"]
        }
        if ("Decision details", "TextControl") not in expanded_name_types:
            raise RuntimeError("details label is not exposed as UIA Text")
        focus_path: list[dict[str, str]] = []
        for _ in range(5):
            auto.SendKeys("{Tab}", waitTime=0.05)
            current = auto.GetFocusedControl()
            focus_path.append(
                {
                    "name": str(current.Name or ""),
                    "type": str(current.ControlTypeName or ""),
                }
            )
        if focus_path[0] != {"name": "Decision details", "type": "EditControl"}:
            raise RuntimeError(f"details edit is not labelled: {focus_path[0]!r}")
        final_focus = focus_path[-1]["name"]
        if final_focus != "Deny":
            raise RuntimeError(
                f"tab order did not return to Deny: {focus_path!r}"
            )
        auto.SendKeys("{Enter}", waitTime=0.1)

    worker.join(timeout=3)
    if worker.is_alive():
        user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
        worker.join(timeout=2)
        raise RuntimeError("keyboard Enter did not resolve the Decision Card")
    if error:
        raise error[0]
    if result != ["option_deny"]:
        raise RuntimeError(f"unexpected Decision Card result: {result!r}")
    return {
        "control_count": len(rows),
        "initial_focus": initial_focus,
        "tab_wrap_focus": toggle_focus,
        "final_focus": final_focus,
        "focus_path": focus_path,
        "result": result[0],
    }


def main() -> int:
    accessibility = OperatorAccessibilitySettings(
        high_contrast=True,
        reduced_motion=True,
        text_scale_factor=1.0,
    )
    with auto.UIAutomationInitializerInThread():
        passive = _passive_surface_smoke(accessibility)
    decision = _decision_card_smoke(accessibility)
    print(
        json.dumps(
            {
                "accessibility": {
                    "high_contrast": accessibility.high_contrast,
                    "reduced_motion": accessibility.reduced_motion,
                    "text_scale_factor": accessibility.text_scale_factor,
                },
                "passive": passive,
                "decision": decision,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
