"""Visual-only Decision Card review with synthetic, non-dispatching data."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from operator_hud_review_guard import (
    ReviewAlreadyRunningError,
    exclusive_review,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.decision_card_window import (  # noqa: E402
    DecisionCardWindow,
    OperatorStepContext,
    WorkflowBreadcrumb,
)
from computer_use_agent.decision_card_window_win32 import (  # noqa: E402
    Win32DecisionCardWindowApi,
)
from computer_use_agent.decision_cards import (  # noqa: E402
    ApplicationClass,
    DecisionBinding,
    DecisionCardRequest,
    DecisionClass,
    DecisionOptionKind,
    EvidenceKind,
    EvidenceReference,
    IntendedEffect,
    RecipientScope,
    UnknownFact,
    compile_decision_card,
)
from computer_use_agent.demo_cross_app import DEMO_WORKFLOW  # noqa: E402
from computer_use_agent.workflow_checklist import WorkflowStatus  # noqa: E402

_REVIEW_WINDOW_TITLE = "Decision required · action blocked"
_WM_COMMAND = 0x0111
_EVIDENCE_TOGGLE_ID = 2002


def _expand_when_ready() -> None:
    """Toggle the synthetic card through its real local window procedure."""

    user32 = ctypes.windll.user32
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        hwnd = user32.FindWindowW(None, _REVIEW_WINDOW_TITLE)
        if hwnd:
            user32.PostMessageW(hwnd, _WM_COMMAND, _EVIDENCE_TOGGLE_ID, 0)
            return
        time.sleep(0.01)


def _card(timeout_seconds: int):
    now = datetime.now(UTC)
    binding = DecisionBinding(
        "visual_only",
        *(f"{index:x}" * 64 for index in range(1, 7)),
    )
    return compile_decision_card(
        DecisionCardRequest(
            "visual_only_decision",
            binding,
            now + timedelta(seconds=timeout_seconds),
            DecisionClass.EXTERNAL_EFFECT,
            ApplicationClass.DESKTOP,
            IntendedEffect.APPROVE_ONE_EXACT_EFFECT,
            RecipientScope.NONE,
            (EvidenceReference(EvidenceKind.OBSERVATION, "7" * 64),),
            (UnknownFact.COMPLETION_OUTCOME,),
            (
                DecisionOptionKind.APPROVE_EXACT_EFFECT,
                DecisionOptionKind.REOBSERVE,
                DecisionOptionKind.DEFER,
                DecisionOptionKind.DENY,
            ),
        ),
        now=now,
    )


async def _show(timeout_seconds: int) -> str:
    workflow = DEMO_WORKFLOW.project(
        WorkflowStatus.NEEDS_INPUT,
        completed_step_ids=(
            "prepare_workspace",
            "review_public_source",
            "open_research_brief",
        ),
        current_step_id="add_verified_note",
    )
    context = OperatorStepContext(
        current=4,
        total=7,
        label="Add the source note to the research brief",
        application="Microsoft Word",
        workflow=WorkflowBreadcrumb.from_checklist(workflow),
    )
    selection = await DecisionCardWindow(
        Win32DecisionCardWindowApi(),
        step_context=lambda: context,
    ).choose(_card(timeout_seconds), timeout_seconds=timeout_seconds)
    return "closed safely" if selection is None else f"selected {selection.option_id}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Show the isolated compact/expanded Decision Card. "
            "No Runner, MCP, provider, application, or desktop action is opened."
        )
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Seconds before the visual-only card closes safely (default: 300).",
    )
    parser.add_argument(
        "--expanded",
        action="store_true",
        help=(
            "Start expanded by posting the same local Show details command. "
            "This remains visual-only and cannot dispatch an action."
        ),
    )
    args = parser.parse_args()
    if not 15 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be between 15 and 600")
    try:
        with exclusive_review("decision-card"):
            if args.expanded:
                threading.Thread(target=_expand_when_ready, daemon=True).start()
            print(asyncio.run(_show(args.timeout_seconds)))
    except ReviewAlreadyRunningError as error:
        print(error, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
