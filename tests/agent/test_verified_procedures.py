from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import computer_use_agent.verified_procedures as procedure_module
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.types import DispatchCertainty
from computer_use_agent.verified_procedures import (
    PROCEDURE_DATA_CLASS,
    PROCEDURE_USE,
    ProcedureDefinition,
    ProcedureFact,
    ProcedureFixtureSplit,
    ProcedureImprovement,
    ProcedureLifecycle,
    ProcedureLifecycleAction,
    ProcedurePin,
    ProcedureReplayFixture,
    ProcedureReplayOutcome,
    ProcedureStatus,
    ProcedureStep,
    ProcedureStepKind,
    ProcedureTerminal,
    ProcedureValidationError,
    build_activation_gate,
    create_procedure_candidate,
    decode_procedure_fixture_suite,
    evaluate_procedure,
    replay_procedure,
    transition_procedure_candidate,
)
from computer_use_agent.world_state import FactType


NOW = datetime(2030, 1, 1, tzinfo=UTC)
POLICY_DIGEST = "1" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "l2_procedure_replay.json"


def _definition(
    *,
    procedure_id: str,
    observation_tool: str,
    source_digest: str,
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
                    "dialog_present",
                    FactType.BOOLEAN,
                    False,
                ),
            ),
        ),
    )


def _candidate() -> ProcedureDefinition:
    return _definition(
        procedure_id="candidate_find_then_click",
        observation_tool="find",
        source_digest="a" * 64,
    )


def _baseline() -> ProcedureDefinition:
    return _definition(
        procedure_id="baseline_snapshot_then_click",
        observation_tool="ui_snapshot",
        source_digest="b" * 64,
    )


def _fixtures() -> tuple[ProcedureReplayFixture, ...]:
    return decode_procedure_fixture_suite(json.loads(FIXTURE_PATH.read_text("utf-8")))


def _evaluations():
    fixtures = _fixtures()
    return (
        evaluate_procedure(_candidate(), fixtures),
        evaluate_procedure(_baseline(), fixtures),
    )


def test_versioned_definition_is_content_free_and_deterministic() -> None:
    definition = _candidate()
    assert definition.digest == _candidate().digest
    assert [step.effect.value for step in definition.steps] == [
        "observation",
        "side_effect",
        "observation",
    ]
    payload = definition.to_payload()
    assert payload["privacy"] == {
        "contains_raw_task": False,
        "contains_model_prose": False,
        "contains_raw_tool_result": False,
        "contains_observation_text": False,
        "contains_arguments": False,
        "contains_ref": False,
        "contains_window_identity": False,
        "contains_approval": False,
        "contains_payload": False,
        "contains_secret": False,
    }
    assert payload["capabilities"] == {
        "authorize": False,
        "dispatch": False,
        "execute": False,
        "inject_memory": False,
        "select_strategy": False,
        "promote_runtime": False,
    }
    steps_payload = payload["steps"]
    assert isinstance(steps_payload, list)
    assert all(isinstance(step, dict) and "arguments" not in step for step in steps_payload)
    assert all(isinstance(step, dict) and "ref" not in step for step in steps_payload)


def test_definition_rejects_sensitive_content_drift_and_unsafe_graphs() -> None:
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_CONTENT_REJECTED$"):
        ProcedureFact("api_key_value", FactType.BOOLEAN, True)
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_CONTENT_REJECTED$"):
        ProcedureFact("safe", FactType.TEXT, "page text")  # type: ignore[arg-type]
    definition = _candidate()
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_REGISTRY_DRIFT$"):
        replace(definition, registry_digest="0" * 64)
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_ACTION_PATH_INVALID$"):
        replace(
            definition,
            steps=(
                definition.steps[0],
                replace(
                    definition.steps[1],
                    success_target=ProcedureTerminal.SAFE_STOP.value,
                ),
                definition.steps[2],
            ),
        )
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_GRAPH_INVALID$"):
        replace(
            definition,
            steps=(
                replace(definition.steps[0], success_target="step_1"),
                *definition.steps[1:],
            ),
        )
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_TOOL_DRIFT$"):
        replace(definition.steps[0], tool_contract_digest="0" * 64)


def test_frozen_fixture_suite_decodes_strictly_and_deterministically() -> None:
    fixtures = _fixtures()
    assert [fixture.fixture_id for fixture in fixtures] == ["heldout_1", "heldout_2"]
    assert all(fixture.split is ProcedureFixtureSplit.HELD_OUT for fixture in fixtures)
    assert all(fixture.registry_digest == reviewed_registry_digest() for fixture in fixtures)
    assert [fixture.digest for fixture in fixtures] == [
        "1e309af710d2b9af61acc4dec1853cd93fe2c55396ffe9817bb981c7f4754bd6",
        "a5e84336e698a8502ebec72eecea137c9c278955174b308ba3a5fbbb6fb87f05",
    ]


@pytest.mark.parametrize(
    "mutation",
    ["extra", "privacy", "text", "order", "fact_bound", "operation_bound"],
)
def test_fixture_decoder_fails_closed(mutation: str) -> None:
    value = json.loads(FIXTURE_PATH.read_text("utf-8"))
    if mutation == "extra":
        value["fixtures"][0]["unexpected"] = True
    elif mutation == "privacy":
        value["fixtures"][0]["privacy"]["contains_raw_task"] = True
    elif mutation == "text":
        value["fixtures"][0]["facts"][0]["value"] = "raw text"
    elif mutation == "order":
        value["fixtures"].reverse()
    elif mutation == "fact_bound":
        value["fixtures"][0]["facts"] *= 17
    else:
        value["fixtures"][0]["operations"] *= 97
    with pytest.raises(ProcedureValidationError):
        decode_procedure_fixture_suite(value)


def test_fixture_dataclass_rejects_unbounded_or_malformed_collections() -> None:
    fixture = _fixtures()[0]
    with pytest.raises(
        ProcedureValidationError,
        match="^PROCEDURE_FIXTURE_FACT_INVALID$",
    ):
        replace(fixture, facts=fixture.facts * 17)
    with pytest.raises(
        ProcedureValidationError,
        match="^PROCEDURE_FIXTURE_OPERATION_INVALID$",
    ):
        replace(fixture, operations=(object(),))  # type: ignore[arg-type]


def test_isolated_replay_proves_held_out_pareto_improvement() -> None:
    candidate, baseline = _evaluations()
    assert candidate.complete and baseline.complete
    assert candidate.verified_successes == baseline.verified_successes == 2
    assert candidate.safety_escapes == baseline.safety_escapes == 0
    assert candidate.authority_regressions == baseline.authority_regressions == 0
    assert candidate.fixture_suite_digest == baseline.fixture_suite_digest
    assert candidate.total_cost.result_bytes < baseline.total_cost.result_bytes
    assert candidate.total_cost.duration_ms < baseline.total_cost.duration_ms
    gate = build_activation_gate(candidate, baseline)
    assert gate.passes
    assert gate.reasons == ()
    assert gate.improvement is ProcedureImprovement.PARETO_COST
    assert gate.to_payload()["runtime_activation"] is False
    assert candidate.to_payload()["data_class"] == PROCEDURE_DATA_CLASS
    assert candidate.to_payload()["use"] == PROCEDURE_USE


def test_dispatched_action_without_approval_is_a_safety_escape() -> None:
    fixtures = list(_fixtures())
    for index, fixture in enumerate(fixtures):
        click = fixture.operations[0]
        fixtures[index] = replace(
            fixture,
            operations=(
                replace(
                    click,
                    approval_granted=False,
                    cost=replace(click.cost, human_approvals=0),
                ),
                *fixture.operations[1:],
            ),
        )
    candidate = evaluate_procedure(_candidate(), fixtures)
    baseline = evaluate_procedure(_baseline(), fixtures)
    assert candidate.safety_escapes == 2
    assert candidate.authority_regressions == 2
    gate = build_activation_gate(candidate, baseline)
    assert not gate.passes
    assert "SAFETY_ESCAPE" in gate.reasons
    assert "AUTHORITY_REGRESSION" in gate.reasons


def test_unknown_action_stops_without_replay_or_safety_escape() -> None:
    fixture = _fixtures()[0]
    click = fixture.operations[0]
    unknown = replace(
        click,
        outcome=ProcedureReplayOutcome.UNKNOWN,
        dispatch_certainty=DispatchCertainty.UNKNOWN,
    )
    fixture = replace(fixture, operations=(unknown, *fixture.operations[1:]))
    result = replay_procedure(_candidate(), fixture)
    assert result.terminal is ProcedureTerminal.SAFE_STOP
    assert result.failure_code == "UNKNOWN_OUTCOME"
    assert result.safety_escapes == 0
    assert result.authority_regressions == 0
    assert result.visited_operations == ("observe_target", "act_accept")
    assert "verify_closed" not in result.visited_operations


def test_forward_only_recovery_branch_replays_without_authority_change() -> None:
    definition = ProcedureDefinition(
        procedure_id="candidate_recovery_observation",
        procedure_version=1,
        task_scope="dismiss_dialog",
        application_scope="safe_app",
        application_version="1.0",
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        generator_version=1,
        source_episode_digests=("c" * 64,),
        preconditions=(ProcedureFact("dialog_present", FactType.BOOLEAN, True),),
        steps=(
            ProcedureStep.reviewed(
                step_id="step_1",
                operation_id="observe_primary",
                kind=ProcedureStepKind.OBSERVATION,
                tool_name="find",
                success_target="step_3",
                failure_target="step_2",
            ),
            ProcedureStep.reviewed(
                step_id="step_2",
                operation_id="observe_recovery",
                kind=ProcedureStepKind.OBSERVATION,
                tool_name="ui_snapshot",
                success_target="step_3",
                failure_target=ProcedureTerminal.SAFE_STOP.value,
            ),
            ProcedureStep.reviewed(
                step_id="step_3",
                operation_id="act_accept",
                kind=ProcedureStepKind.ACTION,
                tool_name="click",
                success_target="step_4",
                failure_target=ProcedureTerminal.SAFE_STOP.value,
            ),
            ProcedureStep.reviewed(
                step_id="step_4",
                operation_id="verify_closed",
                kind=ProcedureStepKind.VERIFY,
                tool_name="ui_snapshot",
                success_target=ProcedureTerminal.VERIFIED_SUCCESS.value,
                failure_target=ProcedureTerminal.SAFE_STOP.value,
                postcondition=ProcedureFact(
                    "dialog_present",
                    FactType.BOOLEAN,
                    False,
                ),
            ),
        ),
    )
    original = _fixtures()[0]
    click, _, snapshot, verify = original.operations
    primary_failure = replace(
        original.operations[1],
        operation_id="observe_primary",
        outcome=ProcedureReplayOutcome.FAILURE,
        dispatch_certainty=DispatchCertainty.NOT_DISPATCHED,
        cost=replace(
            original.operations[1].cost,
            tool_calls=0,
            observation_calls=0,
            result_bytes=0,
            duration_ms=0,
        ),
    )
    recovery = replace(snapshot, operation_id="observe_recovery")
    fixture = replace(
        original,
        operations=tuple(sorted(
            (click, primary_failure, recovery, verify),
            key=lambda item: (item.operation_id, item.tool_name),
        )),
    )
    result = replay_procedure(definition, fixture)
    assert result.verified_success
    assert result.visited_operations == (
        "observe_primary",
        "observe_recovery",
        "act_accept",
        "verify_closed",
    )
    assert result.safety_escapes == result.authority_regressions == 0


def test_held_out_source_leakage_and_incomplete_fixture_fail_gate() -> None:
    fixtures = _fixtures()
    leaked = replace(
        _candidate(),
        source_episode_digests=(fixtures[0].source_episode_digest,),
    )
    evaluation = evaluate_procedure(leaked, fixtures)
    assert not evaluation.complete
    assert evaluation.results[0].failure_code == "HELD_OUT_SOURCE_LEAKAGE"
    baseline = evaluate_procedure(_baseline(), fixtures)
    gate = build_activation_gate(evaluation, baseline)
    assert not gate.passes
    assert "EVALUATION_INCOMPLETE" in gate.reasons


def test_evaluation_requires_two_ordered_held_out_fixtures() -> None:
    fixtures = _fixtures()
    with pytest.raises(
        ProcedureValidationError,
        match="^PROCEDURE_EVALUATION_FIXTURES_INVALID$",
    ):
        evaluate_procedure(_candidate(), fixtures[:1])
    with pytest.raises(ProcedureValidationError):
        evaluate_procedure(_candidate(), tuple(reversed(fixtures)))
    with pytest.raises(ProcedureValidationError):
        evaluate_procedure(
            _candidate(),
            (replace(fixtures[0], split=ProcedureFixtureSplit.SOURCE), fixtures[1]),
        )


def test_no_improvement_or_fixture_drift_cannot_pass_gate() -> None:
    candidate, baseline = _evaluations()
    no_change = build_activation_gate(candidate, candidate)
    assert not no_change.passes
    assert "BASELINE_EQUALS_CANDIDATE" in no_change.reasons
    assert "NO_HELD_OUT_IMPROVEMENT" in no_change.reasons
    drifted_result = replace(
        baseline.results[0],
        fixture_digest="0" * 64,
    )
    drifted_baseline = replace(
        baseline,
        results=(drifted_result, baseline.results[1]),
        total_cost=drifted_result.cost + baseline.results[1].cost,
    )
    drifted = build_activation_gate(candidate, drifted_baseline)
    assert not drifted.passes
    assert "FIXTURE_SUITE_MISMATCH" in drifted.reasons


def test_reviewed_lifecycle_reaches_active_then_exact_rollback() -> None:
    candidate_evaluation, baseline_evaluation = _evaluations()
    rollback_target = ProcedurePin("manual_baseline", 1, "f" * 64)
    lifecycle = create_procedure_candidate(
        _candidate(),
        now=NOW,
        expires_at=NOW + timedelta(days=30),
        rollback_target=rollback_target,
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
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.ACTIVE,
        expected_revision=2,
        now=NOW + timedelta(seconds=3),
        reviewed=True,
        candidate_evaluation=candidate_evaluation,
        baseline_evaluation=baseline_evaluation,
    )
    assert lifecycle.record.status is ProcedureStatus.ACTIVE
    assert lifecycle.record.activation_gate_digest is not None
    capabilities = lifecycle.record.to_payload()["capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["execute"] is False
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.ROLLED_BACK,
        expected_revision=3,
        now=NOW + timedelta(seconds=4),
        reviewed=True,
        rollback_target=rollback_target,
    )
    assert lifecycle.record.status is ProcedureStatus.ROLLED_BACK
    assert [event.action for event in lifecycle.events] == [
        ProcedureLifecycleAction.CREATED,
        ProcedureLifecycleAction.STARTED_EVALUATION,
        ProcedureLifecycleAction.ENTERED_SHADOW,
        ProcedureLifecycleAction.ACTIVATED,
        ProcedureLifecycleAction.ROLLED_BACK,
    ]
    assert lifecycle.events[-1].rollback_target == rollback_target


def test_lifecycle_rejects_missing_review_bad_revision_expiry_and_bad_target() -> None:
    candidate_evaluation, baseline_evaluation = _evaluations()
    target = ProcedurePin("manual_baseline", 1, "f" * 64)
    lifecycle = create_procedure_candidate(
        _candidate(),
        now=NOW,
        expires_at=NOW + timedelta(seconds=3),
        rollback_target=target,
    )
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_REVISION_CONFLICT$"):
        transition_procedure_candidate(
            lifecycle,
            ProcedureStatus.EVALUATING,
            expected_revision=1,
            now=NOW + timedelta(seconds=1),
        )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.EVALUATING,
        expected_revision=0,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(ProcedureValidationError, match="^PROCEDURE_REVIEW_REQUIRED$"):
        transition_procedure_candidate(
            lifecycle,
            ProcedureStatus.SHADOW,
            expected_revision=1,
            now=NOW + timedelta(seconds=2),
            candidate_evaluation=candidate_evaluation,
            baseline_evaluation=baseline_evaluation,
        )
    with pytest.raises(
        ProcedureValidationError,
        match="^PROCEDURE_ACTIVATION_GATE_FAILED$",
    ):
        transition_procedure_candidate(
            lifecycle,
            ProcedureStatus.SHADOW,
            expected_revision=1,
            now=NOW + timedelta(seconds=3),
            reviewed=True,
            candidate_evaluation=candidate_evaluation,
            baseline_evaluation=baseline_evaluation,
        )
    with pytest.raises(ProcedureValidationError):
        transition_procedure_candidate(
            lifecycle,
            ProcedureStatus.ACTIVE,
            expected_revision=1,
            now=NOW + timedelta(seconds=2),
            reviewed=True,
            candidate_evaluation=candidate_evaluation,
            baseline_evaluation=baseline_evaluation,
        )


def test_deprecation_retirement_rejection_and_audit_tamper_are_strict() -> None:
    candidate_evaluation, baseline_evaluation = _evaluations()
    target = ProcedurePin("manual_baseline", 1, "f" * 64)
    lifecycle = create_procedure_candidate(
        _candidate(),
        now=NOW,
        expires_at=NOW + timedelta(days=30),
        rollback_target=target,
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
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.ACTIVE,
        expected_revision=2,
        now=NOW + timedelta(seconds=3),
        reviewed=True,
        candidate_evaluation=candidate_evaluation,
        baseline_evaluation=baseline_evaluation,
    )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.DEPRECATED,
        expected_revision=3,
        now=NOW + timedelta(seconds=4),
    )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.RETIRED,
        expected_revision=4,
        now=NOW + timedelta(seconds=5),
    )
    assert lifecycle.record.status is ProcedureStatus.RETIRED
    with pytest.raises(ProcedureValidationError):
        ProcedureLifecycle(
            lifecycle.record,
            (
                *lifecycle.events[:-1],
                replace(lifecycle.events[-1], record_digest="0" * 64),
            ),
        )
    rejected = create_procedure_candidate(
        _candidate(),
        now=NOW,
        expires_at=NOW + timedelta(days=30),
        rollback_target=target,
    )
    rejected = transition_procedure_candidate(
        rejected,
        ProcedureStatus.REJECTED,
        expected_revision=0,
        now=NOW + timedelta(seconds=1),
    )
    assert rejected.record.status is ProcedureStatus.REJECTED


def test_verified_procedures_has_no_runtime_or_learning_injection_port() -> None:
    source = inspect.getsource(procedure_module)
    assert not hasattr(procedure_module, "AgentRunner")
    assert not hasattr(procedure_module, "ToolCall")
    assert not hasattr(procedure_module, "MemoryStore")
    assert not hasattr(procedure_module, "CandidateFactQuarantine")
    assert "from .learning_quarantine" not in source
    assert "build_memory_context" not in source
    assert "sqlite3" not in source
    assert "open(" not in source
