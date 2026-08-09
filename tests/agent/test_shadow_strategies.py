from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import computer_use_agent.shadow_strategies as shadow_module
from computer_use_agent.shadow_strategies import (
    SHADOW_STRATEGY_DATA_CLASS,
    SHADOW_STRATEGY_USE,
    ShadowRecommendationKind,
    ShadowRewardWeights,
    ShadowStrategyError,
    ShadowStrategyEvidence,
    ShadowStrategyPolicy,
    compare_shadow_strategies,
    decode_shadow_strategy_policy,
)
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.verified_procedures import (
    ProcedureDefinition,
    ProcedureEvaluation,
    ProcedureFact,
    ProcedureLifecycle,
    ProcedurePin,
    ProcedureReplayFixture,
    ProcedureStatus,
    ProcedureStep,
    ProcedureStepKind,
    ProcedureTerminal,
    create_procedure_candidate,
    decode_procedure_fixture_suite,
    evaluate_procedure,
    transition_procedure_candidate,
)
from computer_use_agent.world_state import FactType


NOW = datetime(2030, 1, 1, tzinfo=UTC)
POLICY_DIGEST = "1" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "l3_shadow_replay.json"
POLICY_PATH = Path(__file__).parent / "fixtures" / "l3_shadow_policy.json"


def _definition(
    *,
    procedure_id: str,
    observation_tool: str,
    source_digest: str,
    postcondition_id: str = "dialog_present",
) -> ProcedureDefinition:
    return ProcedureDefinition(
        procedure_id=procedure_id,
        procedure_version=1,
        task_scope="dismiss_dialog",
        application_scope="safe_app",
        application_version="1.0",
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        generator_version=1,
        source_episode_digests=(source_digest,),
        preconditions=(
            ProcedureFact("dialog_present", FactType.BOOLEAN, True),
        ),
        steps=(
            ProcedureStep.reviewed(
                step_id="step_1",
                operation_id="observe_target",
                kind=ProcedureStepKind.OBSERVATION,
                tool_name=observation_tool,
                success_target="step_2",
                failure_target=ProcedureTerminal.SAFE_STOP.value,
            ),
            ProcedureStep.reviewed(
                step_id="step_2",
                operation_id="act_accept",
                kind=ProcedureStepKind.ACTION,
                tool_name="click",
                success_target="step_3",
                failure_target=ProcedureTerminal.SAFE_STOP.value,
            ),
            ProcedureStep.reviewed(
                step_id="step_3",
                operation_id="verify_closed",
                kind=ProcedureStepKind.VERIFY,
                tool_name="ui_snapshot",
                success_target=ProcedureTerminal.VERIFIED_SUCCESS.value,
                failure_target=ProcedureTerminal.SAFE_STOP.value,
                postcondition=ProcedureFact(
                    postcondition_id,
                    FactType.BOOLEAN,
                    False,
                ),
            ),
        ),
    )


def _screenshot() -> ProcedureDefinition:
    return _definition(
        procedure_id="screenshot_then_click",
        observation_tool="screenshot",
        source_digest="a" * 64,
    )


def _active_definition() -> ProcedureDefinition:
    return _definition(
        procedure_id="snapshot_then_click",
        observation_tool="ui_snapshot",
        source_digest="b" * 64,
    )


def _shadow_definition(*, postcondition_id: str = "dialog_present") -> ProcedureDefinition:
    return _definition(
        procedure_id=(
            "find_then_click"
            if postcondition_id == "dialog_present"
            else "find_then_click_changed_goal"
        ),
        observation_tool="find",
        source_digest="c" * 64,
        postcondition_id=postcondition_id,
    )


def _fixtures() -> tuple[ProcedureReplayFixture, ...]:
    return decode_procedure_fixture_suite(json.loads(FIXTURE_PATH.read_text("utf-8")))


def _policy() -> ShadowStrategyPolicy:
    return decode_shadow_strategy_policy(json.loads(POLICY_PATH.read_text("utf-8")))


def _evaluation(
    definition: ProcedureDefinition,
    fixtures: tuple[ProcedureReplayFixture, ...] | None = None,
) -> ProcedureEvaluation:
    return evaluate_procedure(definition, _fixtures() if fixtures is None else fixtures)


def _promote(
    definition: ProcedureDefinition,
    *,
    candidate_evaluation: ProcedureEvaluation,
    baseline_evaluation: ProcedureEvaluation,
    active: bool,
) -> ProcedureLifecycle:
    lifecycle = create_procedure_candidate(
        definition,
        now=NOW,
        expires_at=NOW + timedelta(days=30),
        rollback_target=ProcedurePin("manual_baseline", 1, "f" * 64),
    )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.EVALUATING,
        expected_revision=0,
        now=NOW + timedelta(seconds=1),
    )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.SHADOW,
        expected_revision=1,
        now=NOW + timedelta(seconds=2),
        reviewed=True,
        candidate_evaluation=candidate_evaluation,
        baseline_evaluation=baseline_evaluation,
    )
    if active:
        lifecycle = transition_procedure_candidate(
            lifecycle,
            ProcedureStatus.ACTIVE,
            expected_revision=2,
            now=NOW + timedelta(seconds=3),
            reviewed=True,
            candidate_evaluation=candidate_evaluation,
            baseline_evaluation=baseline_evaluation,
        )
    return lifecycle


def _evidence_pair() -> tuple[ShadowStrategyEvidence, ShadowStrategyEvidence]:
    screenshot = _evaluation(_screenshot())
    active_definition = _active_definition()
    active_evaluation = _evaluation(active_definition)
    shadow_definition = _shadow_definition()
    shadow_evaluation = _evaluation(shadow_definition)
    active = _promote(
        active_definition,
        candidate_evaluation=active_evaluation,
        baseline_evaluation=screenshot,
        active=True,
    )
    shadow = _promote(
        shadow_definition,
        candidate_evaluation=shadow_evaluation,
        baseline_evaluation=active_evaluation,
        active=False,
    )
    return (
        ShadowStrategyEvidence(active, active_evaluation),
        ShadowStrategyEvidence(shadow, shadow_evaluation),
    )


def test_frozen_policy_is_strict_visible_and_deterministic() -> None:
    policy = _policy()
    assert policy == _policy()
    assert policy.max_candidates == 8
    assert policy.weights.to_payload() == {
        "model_turns": 1,
        "tool_calls": 1,
        "side_effects": 1,
        "observation_calls": 1,
        "input_tokens": 1,
        "result_bytes": 1,
        "duration_ms": 1,
        "human_approvals": 1,
        "retries": 1,
    }
    payload = policy.to_payload()
    assert payload["hard_gates"] == {
        "complete_evaluation": True,
        "full_verified_success": True,
        "zero_safety_escapes": True,
        "zero_authority_regressions": True,
        "equivalent_authority_profile": True,
        "exact_fixture_suite": True,
    }
    assert payload["tie_behavior"] == "retain_active"
    assert payload["runtime_selection"] is False


@pytest.mark.parametrize("mutation", ["extra", "version", "secret", "empty", "bool"])
def test_policy_decoder_fails_closed(mutation: str) -> None:
    value = json.loads(POLICY_PATH.read_text("utf-8"))
    if mutation == "extra":
        value["unexpected"] = True
    elif mutation == "version":
        value["shadow_strategy_policy_version"] = 2
    elif mutation == "secret":
        value["policy_id"] = "api_key_strategy"
    elif mutation == "empty":
        value["weights"] = {key: 0 for key in value["weights"]}
    else:
        value["weights"]["tool_calls"] = True
    with pytest.raises(ShadowStrategyError):
        decode_shadow_strategy_policy(value)


def test_frozen_replay_evidence_is_exact_and_content_free() -> None:
    fixtures = _fixtures()
    assert [item.fixture_id for item in fixtures] == [
        "shadow_heldout_1",
        "shadow_heldout_2",
    ]
    assert all(item.registry_digest == reviewed_registry_digest() for item in fixtures)
    assert [item.digest for item in fixtures] == [
        "c848c527c63cbd44b0ab715542a1b6bbe390d825b90eba3fb75f327d2f8410f1",
        "f0c02c8eab1aac8032247cd693e365859ef47c3906ade3c819bfef9267ff21bb",
    ]
    assert all(
        item.to_payload()["privacy"]
        == {
            "contains_raw_task": False,
            "contains_model_prose": False,
            "contains_raw_tool_result": False,
            "contains_observation_text": False,
            "contains_arguments": False,
            "contains_image": False,
            "contains_secret": False,
        }
        for item in fixtures
    )


def test_shadow_comparison_recommends_strict_lower_visible_cost() -> None:
    active, shadow = _evidence_pair()
    comparison = compare_shadow_strategies(
        (shadow, active),
        policy=_policy(),
        evaluated_at=NOW + timedelta(days=1),
    )
    repeated = compare_shadow_strategies(
        (active, shadow),
        policy=_policy(),
        evaluated_at=NOW + timedelta(days=1),
    )
    assert comparison.digest == repeated.digest
    assert comparison.recommendation is ShadowRecommendationKind.RECOMMEND_SHADOW
    assert comparison.recommended_procedure == shadow.pin
    assert comparison.active_baseline == active.pin
    assert comparison.strict_improvement
    assert comparison.reason == "LOWER_WEIGHTED_COST"
    scores = {item.procedure.procedure_id: item for item in comparison.scores}
    assert scores["snapshot_then_click"].weighted_penalty == 912
    assert scores["find_then_click"].weighted_penalty == 516
    assert scores["snapshot_then_click"].reward.cost.result_bytes == 725
    assert scores["find_then_click"].reward.cost.result_bytes == 349
    assert all(item.reward.hard_gates_pass for item in comparison.scores)
    payload = comparison.to_payload()
    assert payload["data_class"] == SHADOW_STRATEGY_DATA_CLASS
    assert payload["use"] == SHADOW_STRATEGY_USE
    assert payload["runtime_selection"] is False
    assert payload["capabilities"] == {
        "authorize": False,
        "dispatch": False,
        "execute": False,
        "route_runtime": False,
        "inject_memory": False,
        "promote_procedure": False,
        "train": False,
    }


def test_equal_visible_weighted_cost_retains_active() -> None:
    active, shadow = _evidence_pair()
    zero = {field_name: 0 for field_name in _policy().weights.to_payload()}
    zero["side_effects"] = 1
    policy = replace(_policy(), weights=ShadowRewardWeights(**zero))
    comparison = compare_shadow_strategies(
        (active, shadow),
        policy=policy,
        evaluated_at=NOW + timedelta(days=1),
    )
    assert comparison.recommendation is ShadowRecommendationKind.RETAIN_ACTIVE
    assert comparison.recommended_procedure == active.pin
    assert not comparison.strict_improvement
    assert comparison.reason == "NO_STRICT_WEIGHTED_IMPROVEMENT"
    assert {item.weighted_penalty for item in comparison.scores} == {2}


def test_comparison_rejects_forged_score_or_recommendation() -> None:
    active, shadow = _evidence_pair()
    comparison = compare_shadow_strategies(
        (active, shadow),
        policy=_policy(),
        evaluated_at=NOW + timedelta(days=1),
    )
    with pytest.raises(ShadowStrategyError, match="^SHADOW_COMPARISON_INVALID$"):
        replace(comparison, recommended_procedure=active.pin)
    first = comparison.scores[0]
    forged_costs = tuple(
        (field_name, value + int(index == 0))
        for index, (field_name, value) in enumerate(first.weighted_costs)
    )
    forged_score = replace(
        first,
        weighted_costs=forged_costs,
        weighted_penalty=first.weighted_penalty + 1,
    )
    with pytest.raises(ShadowStrategyError, match="^SHADOW_COMPARISON_INVALID$"):
        replace(
            comparison,
            scores=(forged_score, *comparison.scores[1:]),
        )


def test_changed_verification_contract_is_not_an_equivalent_strategy() -> None:
    active, _ = _evidence_pair()
    active_evaluation = active.evaluation
    changed_definition = _shadow_definition(postcondition_id="dialog_closed")
    changed_evaluation = _evaluation(changed_definition)
    changed_lifecycle = _promote(
        changed_definition,
        candidate_evaluation=changed_evaluation,
        baseline_evaluation=active_evaluation,
        active=False,
    )
    changed = ShadowStrategyEvidence(changed_lifecycle, changed_evaluation)
    with pytest.raises(
        ShadowStrategyError,
        match="^SHADOW_AUTHORITY_PROFILE_MISMATCH$",
    ):
        compare_shadow_strategies(
            (active, changed),
            policy=_policy(),
            evaluated_at=NOW + timedelta(days=1),
        )


def test_fixture_suite_drift_fails_closed() -> None:
    active, shadow = _evidence_pair()
    fixtures = _fixtures()
    drifted_fixtures = (
        replace(fixtures[0], source_episode_digest="9" * 64),
        fixtures[1],
    )
    drifted = ShadowStrategyEvidence(
        shadow.lifecycle,
        _evaluation(shadow.definition, drifted_fixtures),
    )
    with pytest.raises(
        ShadowStrategyError,
        match="^SHADOW_FIXTURE_SUITE_MISMATCH$",
    ):
        compare_shadow_strategies(
            (active, drifted),
            policy=_policy(),
            evaluated_at=NOW + timedelta(days=1),
        )


@pytest.mark.parametrize("failure", ["unverified", "incomplete", "escape"])
def test_hard_outcome_and_authority_gates_cannot_be_weighted_away(failure: str) -> None:
    active, shadow = _evidence_pair()
    result = shadow.evaluation.results[0]
    if failure == "unverified":
        result = replace(
            result,
            terminal=ProcedureTerminal.SAFE_STOP,
            verified_success=False,
            failure_code="OPERATION_FAILED",
        )
    elif failure == "incomplete":
        result = replace(
            result,
            terminal=ProcedureTerminal.SAFE_STOP,
            verified_success=False,
            complete=False,
            failure_code="FIXTURE_OPERATION_MISSING",
        )
    else:
        result = replace(
            result,
            terminal=ProcedureTerminal.SAFE_STOP,
            verified_success=False,
            safety_escapes=1,
            authority_regressions=1,
            failure_code="AUTHORITY_ESCAPE",
        )
    failed_evaluation = replace(
        shadow.evaluation,
        results=(result, shadow.evaluation.results[1]),
        total_cost=result.cost + shadow.evaluation.results[1].cost,
    )
    failed = ShadowStrategyEvidence(shadow.lifecycle, failed_evaluation)
    with pytest.raises(ShadowStrategyError, match="^SHADOW_HARD_GATE_FAILED$"):
        compare_shadow_strategies(
            (active, failed),
            policy=_policy(),
            evaluated_at=NOW + timedelta(days=1),
        )


def test_exactly_one_active_baseline_is_required() -> None:
    active, shadow = _evidence_pair()
    shadow_active_lifecycle = transition_procedure_candidate(
        shadow.lifecycle,
        ProcedureStatus.ACTIVE,
        expected_revision=2,
        now=NOW + timedelta(seconds=3),
        reviewed=True,
        candidate_evaluation=shadow.evaluation,
        baseline_evaluation=active.evaluation,
    )
    shadow_active = ShadowStrategyEvidence(shadow_active_lifecycle, shadow.evaluation)
    with pytest.raises(ShadowStrategyError, match="^SHADOW_BASELINE_INVALID$"):
        compare_shadow_strategies(
            (active, shadow_active),
            policy=_policy(),
            evaluated_at=NOW + timedelta(days=1),
        )


def test_duplicate_expired_and_future_evidence_fail_closed() -> None:
    active, shadow = _evidence_pair()
    with pytest.raises(ShadowStrategyError, match="^SHADOW_PROCEDURE_DUPLICATE$"):
        compare_shadow_strategies(
            (active, active),
            policy=_policy(),
            evaluated_at=NOW + timedelta(days=1),
        )
    with pytest.raises(ShadowStrategyError, match="^SHADOW_EVIDENCE_EXPIRED$"):
        compare_shadow_strategies(
            (active, shadow),
            policy=_policy(),
            evaluated_at=NOW + timedelta(days=30),
        )
    with pytest.raises(ShadowStrategyError, match="^SHADOW_EVIDENCE_EXPIRED$"):
        compare_shadow_strategies(
            (active, shadow),
            policy=_policy(),
            evaluated_at=NOW,
        )


def test_shadow_evidence_rejects_nonreviewed_lifecycle_and_definition_drift() -> None:
    active, _ = _evidence_pair()
    candidate = create_procedure_candidate(
        _shadow_definition(),
        now=NOW,
        expires_at=NOW + timedelta(days=30),
        rollback_target=ProcedurePin("manual_baseline", 1, "f" * 64),
    )
    with pytest.raises(ShadowStrategyError, match="^SHADOW_EVIDENCE_INVALID$"):
        ShadowStrategyEvidence(candidate, _evaluation(_shadow_definition()))
    with pytest.raises(ShadowStrategyError, match="^SHADOW_EVIDENCE_INVALID$"):
        ShadowStrategyEvidence(active.lifecycle, _evaluation(_shadow_definition()))


def test_shadow_strategy_module_has_no_runtime_or_persistence_port() -> None:
    source = inspect.getsource(shadow_module)
    assert not hasattr(shadow_module, "AgentRunner")
    assert not hasattr(shadow_module, "ToolCall")
    assert not hasattr(shadow_module, "MemoryStore")
    assert not hasattr(shadow_module, "CandidateFactQuarantine")
    assert "from .runner" not in source
    assert "from .learning_quarantine" not in source
    assert "sqlite3" not in source
    assert "open(" not in source
    assert "argparse" not in source
