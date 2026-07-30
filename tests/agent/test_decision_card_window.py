from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from computer_use_agent.decision_card_window import (
    DecisionCardWindow,
    OperatorStepContext,
)
from computer_use_agent.decision_cards import (
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

NOW = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)


def _card():
    binding = DecisionBinding(
        "run_1", *(f"{index:x}" * 64 for index in range(1, 7))
    )
    return compile_decision_card(
        DecisionCardRequest(
            "approval_1",
            binding,
            NOW + timedelta(minutes=5),
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
        now=NOW,
    )


class Api:
    def __init__(self, result: str | None) -> None:
        self.result = result
        self.calls = []

    def choose(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls.append(kwargs)
        return self.result


def test_controller_renders_fixed_tradeoffs_and_correlates_choice() -> None:
    api = Api("option_approve_exact_effect")
    card = _card()
    selection = asyncio.run(
        DecisionCardWindow(api).choose(card, timeout_seconds=30)
    )

    assert selection is not None
    assert selection.decision_id == card.decision_id
    assert selection.card_digest == card.card_digest
    call = api.calls[0]
    assert call["title"] == "Decision required"
    assert call["timeout_seconds"] == 30
    assert [button.option_id for button in call["buttons"]] == [
        "option_approve_exact_effect",
        "option_reobserve",
        "option_defer",
        "option_deny",
    ]
    assert [button.label for button in call["buttons"]] == [
        "Approve once",
        "Re-observe",
        "Defer",
        "Deny",
    ]
    assert "A recommendation is advice, not permission" in call["content"]
    assert "Expected time:" in call["content"]
    assert "Compute cost:" in call["content"]
    assert "Confidence:" in call["content"]
    assert "Esc, close, or timeout denies" in call["content"]
    evidence = call["expanded_information"]
    assert "Safety checks" in evidence
    assert "Observation" in evidence
    assert "Completion outcome" in evidence
    assert "Screen state: 1111111111…111111" in evidence
    assert "Safety policy: 2222222222…222222" in evidence
    assert "Task: 3333333333…333333" in evidence
    assert "Tool registry: 4444444444…444444" in evidence
    assert "Target object: 5555555555…555555" in evidence
    assert "Evidence set: 6666666666…666666" in evidence
    assert card.card_digest not in evidence
    assert "They grant no authority" in evidence
    assert "completion_outcome" not in evidence
    assert "7" * 64 not in evidence


def test_controller_renders_compact_locked_step_context() -> None:
    api = Api("option_deny")
    context = OperatorStepContext(
        current=3,
        total=7,
        label="Switch to the research notes",
        application="Microsoft Word",
    )

    asyncio.run(
        DecisionCardWindow(api, step_context=lambda: context).choose(
            _card(), timeout_seconds=30
        )
    )

    call = api.calls[0]
    assert call["title"] == "Approval locked"
    assert "3/7" in call["instruction"]
    assert "Switch to the research notes" in call["instruction"]
    assert "Microsoft Word" in call["instruction"]
    assert call["content"].startswith("Decision scope")
    assert "Switch to the research notes" not in call["content"]
    assert "Microsoft Word" not in call["content"]


@pytest.mark.parametrize(
    "context",
    [
        (0, 7, "label", "Word"),
        (8, 7, "label", "Word"),
        (1, 0, "label", "Word"),
        (1, 7, "", "Word"),
    ],
)
def test_operator_step_context_is_bounded(context: tuple[object, ...]) -> None:
    with pytest.raises(Exception, match="DECISION_CARD_STEP"):
        OperatorStepContext(*context)  # type: ignore[arg-type]


@pytest.mark.parametrize("result", [None, "option_missing"])
def test_close_timeout_or_unknown_native_choice_returns_none(result: str | None) -> None:
    assert (
        asyncio.run(DecisionCardWindow(Api(result)).choose(_card(), timeout_seconds=5))
        is None
    )


def test_window_controller_has_no_approval_or_execution_boundary() -> None:
    source = inspect.getsource(__import__(
        "computer_use_agent.decision_card_window", fromlist=["decision_card_window"]
    ))
    assert "PolicyDecision" not in source
    assert "ApprovalPort" not in source
    assert "call_tool" not in source
    assert "ToolCall" not in source
