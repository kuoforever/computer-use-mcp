from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta

import pytest

from computer_use_agent.approvals import DecisionCardApprovalPort
from computer_use_agent.decision_cards import DecisionSelection
from computer_use_agent.types import (
    ApprovalBinding,
    ApprovalRequest,
    CallIdentity,
    PolicyDecisionKind,
    ToolCall,
)

NOW = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)


def _request(*, binding: bool = True) -> ApprovalRequest:
    call = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"), "click", {"ref": "ref_1"}
    )
    return ApprovalRequest.from_tool_call(
        request_id="approval_1",
        call=call,
        reason="side_effect_requires_local_approval",
        sensitive_arguments=(),
        binding=(
            ApprovalBinding("run_1", *(f"{index:x}" * 64 for index in range(1, 7)))
            if binding
            else None
        ),
    )


class Surface:
    def __init__(self, option_id: str | None = None, *, fail: bool = False) -> None:
        self.option_id = option_id
        self.fail = fail
        self.cards = []

    async def choose(self, card, *, timeout_seconds: int):  # noqa: ANN001
        self.cards.append((card, timeout_seconds))
        if self.fail:
            raise RuntimeError("window failed")
        if self.option_id is None:
            return None
        return DecisionSelection(card.decision_id, card.card_digest, self.option_id)


def _clock(*values: datetime):
    moments = deque(values)
    return lambda: moments.popleft()


def test_exact_effect_choice_returns_only_one_digest_bound_allow() -> None:
    request = _request()
    surface = Surface("option_approve_exact_effect")
    port = DecisionCardApprovalPort(
        surface, timeout_seconds=30, clock=_clock(NOW, NOW)
    )

    decision = asyncio.run(port.request_approval(request))

    assert port.focus_taking is True
    assert request.matches(decision)
    assert decision.kind is PolicyDecisionKind.ALLOW
    assert decision.reason == "decision_card_exact_effect"
    card, timeout = surface.cards[0]
    assert timeout == 30
    assert card.binding == request.binding
    assert card.recommended_option_id is None
    assert [option.option_id for option in card.options] == [
        "option_approve_exact_effect",
        "option_deny",
    ]


@pytest.mark.parametrize(
    ("option_id", "reason"),
    [
        ("option_deny", "decision_card_denied"),
        (None, "decision_card_no_selection"),
    ],
)
def test_close_deny_and_handoff_all_return_bound_denial(
    option_id: str | None, reason: str
) -> None:
    request = _request()
    decision = asyncio.run(
        DecisionCardApprovalPort(
            Surface(option_id), clock=_clock(NOW, NOW)
        ).request_approval(request)
    )
    assert request.matches(decision)
    assert decision.kind is PolicyDecisionKind.DENY
    assert decision.reason == reason


def test_expiry_malformed_choice_surface_failure_and_missing_binding_deny() -> None:
    request = _request()
    expired = asyncio.run(
        DecisionCardApprovalPort(
            Surface("option_approve_exact_effect"),
            timeout_seconds=5,
            clock=_clock(NOW, NOW + timedelta(seconds=5)),
        ).request_approval(request)
    )
    assert expired.kind is PolicyDecisionKind.DENY
    assert expired.reason == "decision_card_expired"

    malformed = asyncio.run(
        DecisionCardApprovalPort(
            Surface("option_missing"), clock=_clock(NOW, NOW)
        ).request_approval(request)
    )
    assert malformed.kind is PolicyDecisionKind.DENY
    assert malformed.reason == "decision_card_invalid"

    failed = asyncio.run(
        DecisionCardApprovalPort(
            Surface(fail=True), clock=_clock(NOW)
        ).request_approval(request)
    )
    assert failed.kind is PolicyDecisionKind.DENY
    assert failed.reason == "decision_card_failed_closed"

    no_binding_surface = Surface("option_approve_exact_effect")
    no_binding_request = _request(binding=False)
    no_binding = asyncio.run(
        DecisionCardApprovalPort(no_binding_surface).request_approval(
            no_binding_request
        )
    )
    assert no_binding.kind is PolicyDecisionKind.DENY
    assert no_binding.reason == "decision_card_binding_unavailable"
    assert no_binding_surface.cards == []


def test_cancellation_propagates_without_an_allow_decision() -> None:
    class CancelledSurface:
        async def choose(self, _card, *, timeout_seconds: int):  # noqa: ANN001
            del timeout_seconds
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            DecisionCardApprovalPort(
                CancelledSurface(), clock=_clock(NOW)
            ).request_approval(_request())
        )
