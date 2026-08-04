from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from computer_use_agent.decision_cards import (
    ApplicationClass,
    ConfidenceEstimate,
    ConfidenceKind,
    ConfidenceLabel,
    DecisionBinding,
    DecisionCardError,
    DecisionCardRequest,
    DecisionClass,
    DecisionOptionKind,
    DecisionSelection,
    EstimateKind,
    EvidenceKind,
    EvidenceReference,
    IntendedEffect,
    RangeEstimate,
    RecipientScope,
    SelectionStatus,
    UnknownFact,
    compile_decision_card,
    validate_decision_selection,
)

NOW = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)
DIGESTS = tuple(f"{index:x}" * 64 for index in range(1, 8))


def _binding() -> DecisionBinding:
    return DecisionBinding("run_1", *DIGESTS[:6])


def _request(
    *,
    option_kinds: tuple[DecisionOptionKind, ...] = (
        DecisionOptionKind.REOBSERVE,
        DecisionOptionKind.HUMAN_TAKEOVER,
        DecisionOptionKind.DENY,
    ),
    recommended: DecisionOptionKind | None = DecisionOptionKind.REOBSERVE,
) -> DecisionCardRequest:
    return DecisionCardRequest(
        decision_id="decision_1",
        binding=_binding(),
        expires_at=NOW + timedelta(minutes=5),
        decision_class=DecisionClass.OBJECT_DRIFT,
        application=ApplicationClass.MESSAGING,
        intended_effect=IntendedEffect.RECOVER_WITHOUT_EXTERNAL_EFFECT,
        recipient_scope=RecipientScope.EXTERNAL,
        evidence=(EvidenceReference(EvidenceKind.OBSERVATION, DIGESTS[6]),),
        unknown_facts=(UnknownFact.ACTIVE_TARGET,),
        option_kinds=option_kinds,
        recommended=recommended,
    )


def test_compiler_emits_only_fixed_bounded_tradeoffs() -> None:
    card = compile_decision_card(_request(), now=NOW)
    rendered = card.as_display_dict()

    assert card.recommended_option_id == "option_reobserve"
    assert card.advisory_only is True
    assert len(card.options) == 3
    assert card.options[0].expected_time_seconds == RangeEstimate(
        EstimateKind.CONFIGURED_RANGE, 15, 45
    )
    assert card.options[0].confidence == ConfidenceEstimate(
        ConfidenceKind.UNCALIBRATED, ConfidenceLabel.MEDIUM
    )
    assert rendered["recommended_option_id"] == "option_reobserve"
    assert rendered["advisory_only"] is True
    assert "approval" not in rendered and "dispatch" not in rendered


def test_compilation_is_deterministic_and_recommendation_is_not_selection() -> None:
    first = compile_decision_card(_request(), now=NOW)
    second = compile_decision_card(_request(), now=NOW + timedelta(seconds=1))

    assert first == second
    assert first.card_digest == second.card_digest
    result = validate_decision_selection(
        first, None, current_binding=first.binding, now=NOW
    )
    assert result.status is SelectionStatus.NO_SELECTION
    assert result.option_kind is None


def test_valid_choices_remain_non_authoritative_and_require_separate_approval() -> None:
    card = compile_decision_card(
        _request(
            option_kinds=(
                DecisionOptionKind.APPROVE_EXACT_EFFECT,
                DecisionOptionKind.DEFER,
            ),
            recommended=DecisionOptionKind.APPROVE_EXACT_EFFECT,
        ),
        now=NOW,
    )
    selection = DecisionSelection(
        card.decision_id, card.card_digest, "option_approve_exact_effect"
    )

    result = validate_decision_selection(
        card, selection, current_binding=card.binding, now=NOW
    )

    assert result.status is SelectionStatus.SELECTED
    assert result.requires_separate_approval is True
    assert result.releases_desktop_authority is False
    assert set(result.__dict__) == {
        "status",
        "option_kind",
        "requires_separate_approval",
        "releases_desktop_authority",
    }


def test_resume_is_advisory_and_grants_no_action_authority() -> None:
    card = compile_decision_card(
        _request(
            option_kinds=(DecisionOptionKind.RESUME, DecisionOptionKind.DENY),
            recommended=DecisionOptionKind.RESUME,
        ),
        now=NOW,
    )

    result = validate_decision_selection(
        card,
        DecisionSelection(card.decision_id, card.card_digest, "option_resume"),
        current_binding=card.binding,
        now=NOW,
    )

    assert result.status is SelectionStatus.SELECTED
    assert result.option_kind is DecisionOptionKind.RESUME
    assert result.requires_separate_approval is False
    assert result.releases_desktop_authority is False


@pytest.mark.parametrize(
    ("kind", "status", "release"),
    [
        (DecisionOptionKind.DENY, SelectionStatus.DENIED, False),
        (DecisionOptionKind.DEFER, SelectionStatus.DEFERRED, False),
        (DecisionOptionKind.HUMAN_TAKEOVER, SelectionStatus.HANDOFF, True),
    ],
)
def test_safe_exit_paths_are_explicit(
    kind: DecisionOptionKind, status: SelectionStatus, release: bool
) -> None:
    card = compile_decision_card(
        _request(option_kinds=(DecisionOptionKind.REOBSERVE, kind), recommended=None),
        now=NOW,
    )
    result = validate_decision_selection(
        card,
        DecisionSelection(card.decision_id, card.card_digest, f"option_{kind.value}"),
        current_binding=card.binding,
        now=NOW,
    )
    assert result.status is status
    assert result.releases_desktop_authority is release
    assert result.requires_separate_approval is False


@pytest.mark.parametrize(
    ("selection_mutation", "binding_mutation", "when", "status"),
    [
        ("decision", None, NOW, SelectionStatus.INVALID),
        ("digest", None, NOW, SelectionStatus.INVALID),
        ("option", None, NOW, SelectionStatus.INVALID),
        (None, "state", NOW, SelectionStatus.STALE),
        (None, "policy", NOW, SelectionStatus.STALE),
        (None, "task", NOW, SelectionStatus.STALE),
        (None, "registry", NOW, SelectionStatus.STALE),
        (None, "object", NOW, SelectionStatus.STALE),
        (None, "evidence", NOW, SelectionStatus.STALE),
        (None, None, NOW + timedelta(minutes=5), SelectionStatus.EXPIRED),
    ],
)
def test_identity_expiry_and_every_binding_drift_fail_closed(
    selection_mutation: str | None,
    binding_mutation: str | None,
    when: datetime,
    status: SelectionStatus,
) -> None:
    card = compile_decision_card(_request(), now=NOW)
    selection = DecisionSelection(
        card.decision_id, card.card_digest, "option_reobserve"
    )
    if selection_mutation == "decision":
        selection = replace(selection, decision_id="decision_2")
    elif selection_mutation == "digest":
        selection = replace(selection, card_digest="f" * 64)
    elif selection_mutation == "option":
        selection = replace(selection, option_id="option_missing")
    binding = card.binding
    if binding_mutation is not None:
        binding = replace(binding, **{f"{binding_mutation}_digest": "f" * 64})

    result = validate_decision_selection(
        card, selection, current_binding=binding, now=when
    )
    assert result.status is status
    assert result.option_kind is None
    assert result.requires_separate_approval is False


@pytest.mark.parametrize(
    "option_kinds",
    [
        (DecisionOptionKind.REOBSERVE,),
        (
            DecisionOptionKind.REOBSERVE,
            DecisionOptionKind.APPROVE_EXACT_EFFECT,
        ),
        (
            DecisionOptionKind.DEFER,
            DecisionOptionKind.DEFER,
        ),
        (
            DecisionOptionKind.DEFER,
            DecisionOptionKind.DENY,
            DecisionOptionKind.HUMAN_TAKEOVER,
            DecisionOptionKind.REOBSERVE,
            DecisionOptionKind.APPROVE_EXACT_EFFECT,
        ),
    ],
)
def test_options_are_bounded_unique_and_require_safe_exit(
    option_kinds: tuple[DecisionOptionKind, ...]
) -> None:
    with pytest.raises(DecisionCardError):
        _request(option_kinds=option_kinds, recommended=None)


def test_schema_rejects_content_bearing_identifiers_and_false_precision() -> None:
    assert RangeEstimate(EstimateKind.MEASURED_RANGE, 3, 4).minimum == 3
    with pytest.raises(DecisionCardError, match="ID_INVALID"):
        replace(_request(), decision_id="Secret conversation with Alice")
    with pytest.raises(DecisionCardError, match="ESTIMATE_INVALID"):
        RangeEstimate(EstimateKind.UNKNOWN, 1, 2)
    with pytest.raises(DecisionCardError, match="CONFIDENCE_INVALID"):
        ConfidenceEstimate(ConfidenceKind.UNCALIBRATED)
    with pytest.raises(DecisionCardError, match="EXPIRY_INVALID"):
        compile_decision_card(
            replace(_request(), expires_at=NOW + timedelta(hours=25)), now=NOW
        )


def test_display_and_module_are_structurally_redaction_and_authority_safe() -> None:
    card = compile_decision_card(_request(), now=NOW)
    serialized = json.dumps(card.as_display_dict(), sort_keys=True)
    source = inspect.getsource(__import__(
        "computer_use_agent.decision_cards", fromlist=["decision_cards"]
    ))

    assert "Secret conversation" not in serialized
    assert "ToolCall" not in source
    assert "ApprovalPort" not in source
    assert "request_approval" not in source
    assert "call_tool" not in source
    with pytest.raises(DecisionCardError, match="OPTION_INVALID"):
        replace(card.options[0], title="Secret conversation with Alice")
    with pytest.raises(DecisionCardError, match="DECISION_CARD_INVALID"):
        replace(card, advisory_only=False)
