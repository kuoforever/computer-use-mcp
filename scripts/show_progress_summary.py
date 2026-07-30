"""Visual-only compact Progress HUD review with synthetic trusted state."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.demo_cross_app import DEMO_WORKFLOW  # noqa: E402
from computer_use_agent.progress_view import ProgressProjection  # noqa: E402
from computer_use_agent.progress_window import (  # noqa: E402
    PassiveProgressWindow,
    render_workflow_detail_lines,
    render_workflow_summary_lines,
    workflow_visual,
)
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.workflow_checklist import WorkflowStatus  # noqa: E402

_REVIEW_OVERLAPPED_WINDOW = 0x00CF0000


def _empty_projection() -> ProgressProjection:
    return ProgressProjection((), (), 0)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Show the isolated compact Progress HUD with synthetic checklist "
            "state. No Runner, MCP, provider, application, or desktop action is opened."
        )
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Seconds before the visual-only HUD closes (default: 300).",
    )
    parser.add_argument(
        "--inspection-frame",
        action="store_true",
        help=(
            "Wrap the identical content renderer in a targetable review window. "
            "Production passive-window styles are not changed."
        ),
    )
    parser.add_argument(
        "--expanded",
        action="store_true",
        help="Start in the full six-row checklist state.",
    )
    parser.add_argument(
        "--status",
        choices=("running", "needs_input", "verifying", "uncertain"),
        default="running",
        help="Synthetic overall workflow status (default: running).",
    )
    args = parser.parse_args()
    if not 15 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be between 15 and 600")

    status = WorkflowStatus(args.status)
    checklist = DEMO_WORKFLOW.project(
        status,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )
    api = Win32ProgressWindowApi()
    window: PassiveProgressWindow | None = None
    review_hwnd: int | None = None
    if args.inspection_frame:
        review_hwnd = api.create(
            ex_style=0,
            style=_REVIEW_OVERLAPPED_WINDOW,
            title="Progress HUD visual review",
        )
        api.set_workflow_lines(
            review_hwnd,
            compact_lines=render_workflow_summary_lines(checklist),
            expanded_lines=render_workflow_detail_lines(checklist),
            expanded=args.expanded,
            accent_rgb=workflow_visual(checklist.status).color_rgb,
            on_toggle=lambda _expanded: None,
        )
        api.show_noactivate(review_hwnd)
    else:
        window = PassiveProgressWindow(api)
        window.open(
            _empty_projection(),
            workflow=checklist,
            expanded=args.expanded,
        )
    deadline = time.monotonic() + args.timeout_seconds
    try:
        while time.monotonic() < deadline:
            api.pump()
            time.sleep(0.02)
    except KeyboardInterrupt:
        pass
    finally:
        if window is not None:
            window.close()
        if review_hwnd is not None:
            api.destroy(review_hwnd)
        api.pump()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
