"""Local approval ports for explicit Agent Host authorization."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from .decision_cards import (
    ApplicationClass,
    DecisionCard,
    DecisionCardRequest,
    DecisionClass,
    DecisionOptionKind,
    DecisionSelection,
    EvidenceKind,
    EvidenceReference,
    IntendedEffect,
    RecipientScope,
    SelectionStatus,
    UnknownFact,
    compile_decision_card,
    validate_decision_selection,
)
from .types import ApprovalRequest, PolicyDecision, PolicyDecisionKind, to_json_value


class DecisionCardChoicePort(Protocol):
    async def choose(
        self, card: DecisionCard, *, timeout_seconds: int
    ) -> DecisionSelection | None: ...


class ReadOnlyApprovalPort:
    """Fail if approval is ever requested by the read-only runtime."""

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        del request
        raise RuntimeError("APPROVAL_UNAVAILABLE_IN_READ_ONLY_MODE")


class ConsoleApprovalPort:
    """Ask the local operator for one digest-bound action approval."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        summary = json.dumps(
            to_json_value(request.safe_argument_summary.values),
            sort_keys=True,
            separators=(",", ":"),
        )
        self._output(
            f"Approval required: tool={request.tool_name} arguments={summary} "
            f"digest={request.call_digest}"
        )
        try:
            answer = await asyncio.to_thread(self._input, "Approve this one action? [y/N]: ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        kind = (
            PolicyDecisionKind.ALLOW
            if answer.strip().lower() in {"y", "yes"}
            else PolicyDecisionKind.DENY
        )
        return PolicyDecision(
            request_id=request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=kind,
            reason="local_operator_response",
        )


class DecisionCardApprovalPort:
    """Focus-taking, fail-closed card adapter for the existing ApprovalPort."""

    focus_taking = True

    def __init__(
        self,
        surface: DecisionCardChoicePort,
        *,
        timeout_seconds: int = 300,
        takeover_enabled: bool = False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool):
            raise ValueError("decision card timeout must be an integer")
        if not 5 <= timeout_seconds <= 3_600:
            raise ValueError("decision card timeout must be between 5 and 3600")
        if not callable(clock):
            raise ValueError("decision card clock must be callable")
        if not isinstance(takeover_enabled, bool):
            raise ValueError("takeover_enabled must be a boolean")
        self._surface = surface
        self._timeout_seconds = timeout_seconds
        self._takeover_enabled = takeover_enabled
        self._clock = clock

    @staticmethod
    def _decision(
        request: ApprovalRequest, kind: PolicyDecisionKind, reason: str
    ) -> PolicyDecision:
        return PolicyDecision(
            request_id=request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=kind,
            reason=reason,
        )

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        if not isinstance(request, ApprovalRequest):
            raise ValueError("request must be an ApprovalRequest")
        if request.binding is None:
            return self._decision(
                request, PolicyDecisionKind.DENY, "decision_card_binding_unavailable"
            )
        try:
            now = self._clock()
            card = compile_decision_card(
                DecisionCardRequest(
                    decision_id=request.request_id,
                    binding=request.binding,
                    expires_at=now + timedelta(seconds=self._timeout_seconds),
                    decision_class=DecisionClass.EXTERNAL_EFFECT,
                    application=ApplicationClass.DESKTOP,
                    intended_effect=IntendedEffect.APPROVE_ONE_EXACT_EFFECT,
                    recipient_scope=RecipientScope.NONE,
                    evidence=(
                        EvidenceReference(
                            EvidenceKind.OBSERVATION,
                            request.binding.evidence_digest,
                        ),
                    ),
                    unknown_facts=(UnknownFact.COMPLETION_OUTCOME,),
                    option_kinds=(
                        DecisionOptionKind.APPROVE_EXACT_EFFECT,
                        DecisionOptionKind.REOBSERVE,
                        (
                            DecisionOptionKind.HUMAN_TAKEOVER
                            if self._takeover_enabled
                            else DecisionOptionKind.DEFER
                        ),
                        DecisionOptionKind.DENY,
                    ),
                ),
                now=now,
            )
            selection = await self._surface.choose(
                card, timeout_seconds=self._timeout_seconds
            )
            result = validate_decision_selection(
                card,
                selection,
                current_binding=request.binding,
                now=self._clock(),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return self._decision(
                request, PolicyDecisionKind.DENY, "decision_card_failed_closed"
            )
        if (
            result.status is SelectionStatus.SELECTED
            and result.option_kind is DecisionOptionKind.APPROVE_EXACT_EFFECT
            and result.requires_separate_approval
        ):
            return self._decision(
                request, PolicyDecisionKind.ALLOW, "decision_card_exact_effect"
            )
        if (
            result.status is SelectionStatus.SELECTED
            and result.option_kind is DecisionOptionKind.REOBSERVE
        ):
            return self._decision(
                request, PolicyDecisionKind.REOBSERVE, "decision_card_reobserve"
            )
        if result.status is SelectionStatus.DEFERRED:
            return self._decision(
                request, PolicyDecisionKind.DEFER, "decision_card_deferred"
            )
        if (
            result.status is SelectionStatus.HANDOFF
            and result.option_kind is DecisionOptionKind.HUMAN_TAKEOVER
        ):
            return self._decision(
                request, PolicyDecisionKind.TAKEOVER, "decision_card_human_takeover"
            )
        return self._decision(
            request, PolicyDecisionKind.DENY, f"decision_card_{result.status.value}"
        )


__all__ = [
    "ConsoleApprovalPort",
    "DecisionCardApprovalPort",
    "DecisionCardChoicePort",
    "ReadOnlyApprovalPort",
]

