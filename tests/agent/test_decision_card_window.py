from __future__ import annotations

import asyncio
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from computer_use_agent.decision_card_window import DecisionCardWindow
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
                DecisionOptionKind.HUMAN_TAKEOVER,
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
        "option_human_takeover",
        "option_deny",
    ]
    assert "Recommendation is advisory and grants no authority" in call["content"]
    assert "Expected time seconds:" in call["content"]
    assert "Expected tokens:" in call["content"]
    assert "Confidence:" in call["content"]
    assert "Fallback:" in call["content"]
    assert "Close or timeout denies" in call["content"]
    evidence = call["expanded_information"]
    assert "Evidence references (SHA-256 digests only)" in evidence
    assert "observation: " + "7" * 64 in evidence
    assert "completion_outcome" in evidence
    assert "state: " + "1" * 64 in evidence
    assert "policy: " + "2" * 64 in evidence
    assert "task: " + "3" * 64 in evidence
    assert "registry: " + "4" * 64 in evidence
    assert "object: " + "5" * 64 in evidence
    assert "evidence: " + "6" * 64 in evidence
    assert card.card_digest in evidence
    assert "not execution authority" in evidence


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
