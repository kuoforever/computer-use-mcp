"""Bounded two-locale native accessibility smoke for operator surfaces.

The probe opens no provider, MCP, application, or desktop-action port.  The
passive surfaces must preserve the foreground window.  The focus-taking
Decision Card is inspected through UI Automation and resolved with keyboard
navigation to its safe ``option_deny`` choice in English and Simplified Chinese.
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
from computer_use_agent.operator_localization import (  # noqa: E402
    OperatorLocale,
    decision_button_label,
    localize_fixed_text,
    operator_text,
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
from computer_use_agent.progress_window import (  # noqa: E402
    render_workflow_detail_lines,
    render_workflow_summary_lines,
    workflow_accessible_name,
)
from computer_use_agent.demo_cross_app import DEMO_WORKFLOW  # noqa: E402
from computer_use_agent.workflow_checklist import (  # noqa: E402
    WorkflowStatus,
)


def _title(locale: OperatorLocale) -> str:
    return f"{operator_text(locale, 'decision_required')} ({locale.value})"


def _foreground() -> int:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    return int(user32.GetForegroundWindow() or 0)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    rect = wintypes.RECT()
    if not user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise RuntimeError("native window rectangle is unavailable")
    return int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)


def _inside(
    inner: tuple[int, int, int, int],
    outer: tuple[int, int, int, int],
) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


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
    locale: OperatorLocale,
) -> dict[str, object]:
    before = _foreground()
    progress = Win32ProgressWindowApi(
        accessibility=accessibility,
        locale=locale,
    )
    progress_hwnd = progress.create(
        ex_style=0x08000088,
        style=0x80000000,
        title=operator_text(locale, "product_name"),
    )
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        current_step_id="prepare_workspace",
    )
    compact = render_workflow_summary_lines(checklist, locale)
    details = render_workflow_detail_lines(checklist, locale)
    presence_api = Win32PresenceWindowApi(
        accessibility=accessibility,
        locale=locale,
    )
    presence = PassivePresenceWindow(
        presence_api,
        title=operator_text(locale, "presence_window_title"),
    )
    try:
        selected = presence_api.display_monitor()
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
                    locale=locale,
                ),
            )
        )
        presence_api.pump()
        after = _foreground()
        progress_name = str(auto.ControlFromHandle(progress_hwnd).Name)
        if presence.hwnd is None:
            raise RuntimeError("presence window was not created")
        presence_name = str(auto.ControlFromHandle(presence.hwnd).Name)
        progress_rect = _window_rect(progress_hwnd)
        presence_rect = _window_rect(presence.hwnd)
        if before != after:
            raise RuntimeError("passive operator surface changed foreground")
        if progress_name != workflow_accessible_name(compact, locale):
            raise RuntimeError("progress accessible summary is incomplete")
        expected_presence_name = (
            "电脑操作。审批。需要确认。"
            if locale is OperatorLocale.ZH_CN
            else "Computer Use. Approval. Needs input."
        )
        if presence_name != expected_presence_name:
            raise RuntimeError("presence accessible name is incomplete")
        if not _inside(progress_rect, selected.work_area):
            raise RuntimeError("progress window escaped selected monitor work area")
        if presence_rect != selected.bounds:
            raise RuntimeError("presence window does not match selected monitor bounds")
        return {
            "foreground_unchanged": True,
            "monitor": {
                "bounds": selected.bounds,
                "work_area": selected.work_area,
                "dpi": selected.dpi,
            },
            "progress_rect": progress_rect,
            "presence_rect": presence_rect,
            "progress_name": progress_name,
            "presence_name": presence_name,
            "presence_capture_excluded": presence_result.capture_excluded,
        }
    finally:
        presence.close()
        progress.destroy(progress_hwnd)


def _decision_card_smoke(
    accessibility: OperatorAccessibilitySettings,
    locale: OperatorLocale,
) -> dict[str, object]:
    result: list[str | None] = []
    error: list[BaseException] = []

    def choose() -> None:
        try:
            result.append(
                Win32DecisionCardWindowApi(
                    accessibility=accessibility,
                    locale=locale,
                ).choose(
                    title=_title(locale),
                    instruction=(
                        f"{localize_fixed_text(locale, 'Needs input').upper()}  ·  "
                        f"{operator_text(locale, 'approval_locked')}\n"
                        f"{localize_fixed_text(locale, 'Save the research brief')}\n"
                        f"{operator_text(locale, 'approval')} 1/1  ·  Microsoft Word\n"
                        f"{operator_text(locale, 'workflow')} 6/6  ·  "
                        f"{localize_fixed_text(locale, 'Verify the saved document')}"
                    ),
                    content=operator_text(locale, "decision_scope"),
                    expanded_information=operator_text(locale, "evidence_available"),
                    buttons=(
                        *(
                            DecisionCardButton(
                                option_id,
                                decision_button_label(locale, option_id, option_id),
                            )
                            for option_id in (
                                "option_approve_exact_effect",
                                "option_reobserve",
                                "option_defer",
                                "option_deny",
                            )
                        ),
                    ),
                    timeout_seconds=20,
                )
            )
        except BaseException as exc:  # pragma: no cover - native diagnostic
            error.append(exc)

    worker = threading.Thread(target=choose, daemon=True)
    worker.start()
    hwnd = _wait_for_window(_title(locale))
    user32 = ctypes.windll.user32
    monitor_api = Win32PresenceWindowApi(
        accessibility=accessibility,
        locale=locale,
    )
    selected = monitor_api.display_monitor()
    card_rect = _window_rect(hwnd)
    if not _inside(card_rect, selected.work_area):
        user32.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
        worker.join(timeout=2)
        raise RuntimeError("Decision Card escaped selected monitor work area")
    with auto.UIAutomationInitializerInThread():
        rows = _control_rows(auto.ControlFromHandle(hwnd))
        names = {str(row["name"]): str(row["type"]) for row in rows if row["name"]}
        safe_label = decision_button_label(locale, "option_deny", "option_deny")
        expected_controls = (
            f"{localize_fixed_text(locale, 'Needs input').upper()}  ·  "
            f"{operator_text(locale, 'approval_locked')}",
            localize_fixed_text(locale, "Save the research brief"),
            f"{operator_text(locale, 'approval')} 1/1  ·  Microsoft Word",
            f"{operator_text(locale, 'workflow')} 6/6  ·  "
            f"{localize_fixed_text(locale, 'Verify the saved document')}",
            *(
                decision_button_label(locale, option_id, option_id)
                for option_id in (
                    "option_approve_exact_effect",
                    "option_reobserve",
                    "option_defer",
                    "option_deny",
                )
            ),
        )
        for expected in expected_controls:
            if expected not in names:
                raise RuntimeError(f"missing UIA control: {expected}")
        if names[safe_label] != "ButtonControl":
            raise RuntimeError("deny is not exposed as a UIA Button")
        focused = auto.GetFocusedControl()
        initial_focus = str(focused.Name or "")
        if initial_focus != safe_label:
            raise RuntimeError(f"safe initial focus missing: {initial_focus}")

        # option_deny is the final tab stop. Tab wraps to the first control (details
        # toggle), then five more Tabs reach Deny after the details pane opens.
        auto.SendKeys("{Tab}", waitTime=0.1)
        toggle_focus = str(auto.GetFocusedControl().Name or "")
        if toggle_focus != operator_text(locale, "show_details"):
            raise RuntimeError(f"details toggle name is invalid: {toggle_focus}")
        auto.SendKeys("{Enter}", waitTime=0.1)
        time.sleep(0.3)
        expanded_rows = _control_rows(auto.ControlFromHandle(hwnd))
        expanded_name_types = {
            (str(row["name"]), str(row["type"]))
            for row in expanded_rows
            if row["name"]
        }
        details_label = operator_text(locale, "decision_details")
        if (details_label, "TextControl") not in expanded_name_types:
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
        if focus_path[0] != {"name": details_label, "type": "EditControl"}:
            raise RuntimeError(f"details edit is not labelled: {focus_path[0]!r}")
        final_focus = focus_path[-1]["name"]
        if final_focus != safe_label:
            raise RuntimeError(
                f"tab order did not return to safe choice: {focus_path!r}"
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
        "monitor": {
            "bounds": selected.bounds,
            "work_area": selected.work_area,
            "dpi": selected.dpi,
        },
        "window_rect": card_rect,
        "result": result[0],
    }


def main() -> int:
    accessibility = OperatorAccessibilitySettings(
        high_contrast=True,
        reduced_motion=True,
        text_scale_factor=1.0,
    )
    locales: dict[str, object] = {}
    for locale in OperatorLocale:
        with auto.UIAutomationInitializerInThread():
            passive = _passive_surface_smoke(accessibility, locale)
        decision = _decision_card_smoke(accessibility, locale)
        locales[locale.value] = {"passive": passive, "decision": decision}
    print(
        json.dumps(
            {
                "accessibility": {
                    "high_contrast": accessibility.high_contrast,
                    "reduced_motion": accessibility.reduced_motion,
                    "text_scale_factor": accessibility.text_scale_factor,
                },
                "locales": locales,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
