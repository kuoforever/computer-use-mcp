from __future__ import annotations

import json

import pytest

from computer_use_agent.boss_semantic_extraction import (
    BOSS_OBSERVATION_LADDER,
    BOSS_SEMANTIC_SCHEMA_VERSION,
    BossIncompleteReason,
    BossObservationAttempt,
    BossObservationDecisionState,
    BossObservationSource,
    BossObservationStatus,
    BossSemanticClassification,
    BossSemanticContractError,
    BossSemanticReason,
    boss_semantic_result_schema,
    boss_semantic_schema_digest,
    decide_next_boss_observation,
    parse_boss_semantic_result,
)


DIGEST = "a" * 64


def _payload() -> dict[str, object]:
    return {
        "schema_version": BOSS_SEMANTIC_SCHEMA_VERSION,
        "item_key": "boss:job:publicjob001",
        "company": "Example Company",
        "role": "AI Engineer",
        "location": "Shanghai",
        "compensation": None,
        "experience": "3-5 years",
        "classification": "POSSIBLE",
        "classification_reasons": ["ROLE", "LOCATION"],
        "classification_policy_digest": "b" * 64,
        "source": "document_text",
        "source_digest": DIGEST,
    }


def _attempt(
    source: BossObservationSource,
    status: BossObservationStatus = BossObservationStatus.INCOMPLETE,
) -> BossObservationAttempt:
    return BossObservationAttempt(
        source=source,
        status=status,
        content_digest=DIGEST,
        incomplete_reason=(
            BossIncompleteReason.REQUIRED_FIELDS_MISSING
            if status is BossObservationStatus.INCOMPLETE
            else None
        ),
    )


def test_exact_bounded_result_round_trips_and_has_stable_digest() -> None:
    result = parse_boss_semantic_result(_payload())

    assert result.classification is BossSemanticClassification.POSSIBLE
    assert result.classification_reasons == (
        BossSemanticReason.ROLE,
        BossSemanticReason.LOCATION,
    )
    assert result.source is BossObservationSource.DOCUMENT_TEXT
    assert result.canonical_payload() == _payload()
    assert len(result.content_digest) == 64
    assert result.content_digest == parse_boss_semantic_result(_payload()).content_digest


def test_result_rejects_extra_fields_unbounded_text_and_control_characters() -> None:
    extra = _payload()
    extra["description"] = "raw page text is outside the contract"
    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_SEMANTIC_RESULT_SHAPE_INVALID$",
    ):
        parse_boss_semantic_result(extra)

    oversized = _payload()
    oversized["company"] = "x" * 161
    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_SEMANTIC_COMPANY_INVALID$",
    ):
        parse_boss_semantic_result(oversized)

    control = _payload()
    control["role"] = "AI\nEngineer"
    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_SEMANTIC_ROLE_INVALID$",
    ):
        parse_boss_semantic_result(control)


def test_result_rejects_unknown_enums_and_inconsistent_insufficient_reason() -> None:
    unknown = _payload()
    unknown["classification"] = "MODEL_PROSE"
    with pytest.raises(BossSemanticContractError, match="^BOSS_SEMANTIC_ENUM_INVALID$"):
        parse_boss_semantic_result(unknown)

    inconsistent = _payload()
    inconsistent["classification"] = "INSUFFICIENT_EVIDENCE"
    with pytest.raises(BossSemanticContractError, match="^BOSS_SEMANTIC_REASONS_INVALID$"):
        parse_boss_semantic_result(inconsistent)

    mixed = _payload()
    mixed["classification_reasons"] = ["ROLE", "INSUFFICIENT_EVIDENCE"]
    with pytest.raises(BossSemanticContractError, match="^BOSS_SEMANTIC_REASONS_INVALID$"):
        parse_boss_semantic_result(mixed)

    valid = _payload()
    valid["classification"] = "INSUFFICIENT_EVIDENCE"
    valid["classification_reasons"] = ["INSUFFICIENT_EVIDENCE"]
    assert (
        parse_boss_semantic_result(valid).classification
        is BossSemanticClassification.INSUFFICIENT_EVIDENCE
    )


def test_strict_json_schema_is_serializable_bounded_and_digest_stable() -> None:
    schema = boss_semantic_result_schema()
    encoded = json.dumps(schema, sort_keys=True, separators=(",", ":"))

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "description" not in schema["properties"]
    assert '"maxLength":160' in encoded
    assert len(boss_semantic_schema_digest()) == 64
    assert boss_semantic_schema_digest() == boss_semantic_schema_digest()
    schema["additionalProperties"] = True
    assert boss_semantic_result_schema()["additionalProperties"] is False


def test_ladder_starts_with_uia_and_escalates_only_after_explicit_incomplete() -> None:
    decision = decide_next_boss_observation(())
    assert decision.state is BossObservationDecisionState.OBSERVE
    assert decision.next_source is BossObservationSource.UIA

    attempts = []
    for expected_next, source in zip(BOSS_OBSERVATION_LADDER[1:], BOSS_OBSERVATION_LADDER):
        attempts.append(_attempt(source))
        decision = decide_next_boss_observation(attempts)
        assert decision.state is BossObservationDecisionState.OBSERVE
        assert decision.next_source is expected_next

    attempts.append(_attempt(BossObservationSource.SCREENSHOT))
    exhausted = decide_next_boss_observation(attempts)
    assert exhausted.state is BossObservationDecisionState.HANDOFF
    assert exhausted.stop_code == "BOSS_OBSERVATION_LADDER_EXHAUSTED"


def test_sufficient_observation_extracts_and_fixed_site_states_handoff() -> None:
    sufficient = decide_next_boss_observation(
        [_attempt(BossObservationSource.UIA, BossObservationStatus.SUFFICIENT)]
    )
    assert sufficient.state is BossObservationDecisionState.EXTRACT
    assert sufficient.next_source is None

    challenge = decide_next_boss_observation(
        [_attempt(BossObservationSource.UIA, BossObservationStatus.CHALLENGE_REQUIRED)]
    )
    assert challenge.state is BossObservationDecisionState.HANDOFF
    assert challenge.stop_code == "BOSS_CHALLENGE_REQUIRED"


def test_ladder_rejects_skips_retries_and_continuation_after_terminal() -> None:
    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_OBSERVATION_SEQUENCE_INVALID$",
    ):
        decide_next_boss_observation([_attempt(BossObservationSource.OCR)])

    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_OBSERVATION_SEQUENCE_INVALID$",
    ):
        decide_next_boss_observation(
            [
                _attempt(BossObservationSource.UIA),
                _attempt(BossObservationSource.UIA),
            ]
        )

    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_OBSERVATION_AFTER_TERMINAL$",
    ):
        decide_next_boss_observation(
            [
                _attempt(BossObservationSource.UIA, BossObservationStatus.SUFFICIENT),
                _attempt(BossObservationSource.DOCUMENT_TEXT),
            ]
        )


def test_incomplete_reason_is_required_only_for_incomplete_attempts() -> None:
    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_OBSERVATION_REASON_INVALID$",
    ):
        BossObservationAttempt(
            source=BossObservationSource.UIA,
            status=BossObservationStatus.INCOMPLETE,
            content_digest=DIGEST,
        )

    with pytest.raises(
        BossSemanticContractError,
        match="^BOSS_OBSERVATION_REASON_INVALID$",
    ):
        BossObservationAttempt(
            source=BossObservationSource.UIA,
            status=BossObservationStatus.SUFFICIENT,
            content_digest=DIGEST,
            incomplete_reason=BossIncompleteReason.TRUNCATED,
        )
