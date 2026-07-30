"""Visual-only Decision Card review with synthetic, non-dispatching data."""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.decision_card_window import (  # noqa: E402
    DecisionCardWindow,
    OperatorStepContext,
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
    context = OperatorStepContext(
        current=4,
        total=7,
        label="Add the source note to the research brief",
        application="Microsoft Word",
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
    args = parser.parse_args()
    if not 15 <= args.timeout_seconds <= 600:
        parser.error("--timeout-seconds must be between 15 and 600")
    print(asyncio.run(_show(args.timeout_seconds)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
