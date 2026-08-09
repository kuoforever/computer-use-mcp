from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest

import computer_use_agent.adaptive_routing as routing_module
import computer_use_agent.executor_runtime as runtime_module
from computer_use_agent.adaptive_routing import (
    ADAPTIVE_ROUTING_DATA_CLASS,
    ADAPTIVE_ROUTING_USE,
    AdaptiveRouteChoice,
    AdaptiveRolloutStatus,
    AdaptiveRoutingContext,
    AdaptiveRoutingError,
    AdaptiveRoutingOutcome,
    AdaptiveRoutingPolicy,
    AdaptiveRoutingStore,
    AdaptiveRoutingStoreError,
    adaptive_action_call_digest,
    adaptive_routing_lock,
    bind_adaptive_h7_plan,
    create_adaptive_rollout,
    record_adaptive_outcome,
    route_adaptive_procedure,
)
from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.episode_outcome import EpisodeOutcomeLabel
from computer_use_agent.executor_final import FinalResponseRequest, FinalResponseResult
from computer_use_agent.executor_runtime import (
    open_adaptive_routed_hierarchical_side_effect_runtime_executor_session,
)
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.hierarchical_runtime import runtime_policy_digest
from computer_use_agent.planning import compile_task_plan
from computer_use_agent.shadow_strategies import (
    ShadowRewardWeights,
    ShadowStrategyEvidence,
    ShadowStrategyPolicy,
    compare_shadow_strategies,
)
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.types import (
    ActionRiskTier,
    ApprovalRequest,
    DispatchCertainty,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
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
TASK = "Dismiss the isolated dialog and verify it is closed"
TASK_DIGEST = sha256(TASK.encode("utf-8")).hexdigest()
POLICY_DIGEST = "1" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "l3_shadow_replay.json"


@dataclass
class RoutedApprovalPort:
    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision(
            request_id=request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=PolicyDecisionKind.ALLOW,
            reason="isolated_operator_review",
        )


@dataclass
class RoutedDialogApplication(FakeDesktopMCP):
    closed: bool = False

    async def call_tool(self, call: ToolCall) -> ToolResult:
        self.tool_calls.append(call)
        if call.name == "find":
            text = 'ref_1 | button "Accept" | enabled'
        elif call.name == "click":
            self.closed = True
            text = "isolated action completed"
        else:
            assert call.name == "ui_snapshot"
            text = "dialog absent" if self.closed else 'ref_1 | button "Accept"'
        return ToolResult(
            identity=call.identity,
            tool_name=call.name,
            status=ToolResultStatus.SUCCESS,
            dispatch=DispatchCertainty.DISPATCHED,
            sanitized_text=text,
        )


@dataclass
class RoutedFinalPort:
    requests: list[FinalResponseRequest] = field(default_factory=list)

    async def create_final_response(
        self, request: FinalResponseRequest
    ) -> FinalResponseResult:
        self.requests.append(request)
        return FinalResponseResult(
            run_id=request.run_id,
            turn_id=request.turn_id,
            provider_response_id="isolated-l4-final",
            text="The isolated dialog is closed.",
            usage=ModelUsage(input_tokens=1, output_tokens=1),
        )


def _runtime_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "l4",
        policy_version="l4-reviewed-v1",
        provider=ProviderConfig(name="openai", model="fake"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "isolated-dialog.exe"},
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=4,
            max_tool_calls=3,
            max_side_effects=1,
        ),
        continuation=ContinuationConfig(enabled=True),
    )


def _definition(
    *,
    procedure_id: str,
    observation_tool: str,
    source_digest: str,
    policy_digest: str = POLICY_DIGEST,
) -> ProcedureDefinition:
    return ProcedureDefinition(
        procedure_id=procedure_id,
        procedure_version=1,
        task_scope="dismiss_dialog",
        application_scope="safe_app",
        application_version="1.0",
        registry_digest=reviewed_registry_digest(),
        policy_digest=policy_digest,
        generator_version=1,
        source_episode_digests=(source_digest,),
        preconditions=(ProcedureFact("dialog_present", FactType.BOOLEAN, True),),
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


def _baseline_definition(*, policy_digest: str = POLICY_DIGEST) -> ProcedureDefinition:
    return _definition(
        procedure_id="snapshot_then_click",
        observation_tool="ui_snapshot",
        source_digest="a" * 64,
        policy_digest=policy_digest,
    )


def _candidate_definition(*, policy_digest: str = POLICY_DIGEST) -> ProcedureDefinition:
    return _definition(
        procedure_id="find_then_click",
        observation_tool="find",
        source_digest="b" * 64,
        policy_digest=policy_digest,
    )


def _fixtures(
    *, policy_digest: str = POLICY_DIGEST
) -> tuple[ProcedureReplayFixture, ...]:
    fixtures = decode_procedure_fixture_suite(
        json.loads(FIXTURE_PATH.read_text("utf-8"))
    )
    return tuple(replace(item, policy_digest=policy_digest) for item in fixtures)


def _evaluation(definition: ProcedureDefinition) -> ProcedureEvaluation:
    return evaluate_procedure(
        definition,
        _fixtures(policy_digest=definition.policy_digest),
    )


def _shadow_policy() -> ShadowStrategyPolicy:
    return ShadowStrategyPolicy(
        policy_id="l4_source_comparison",
        policy_version=1,
        max_candidates=4,
        weights=ShadowRewardWeights(
            model_turns=1,
            tool_calls=1,
            side_effects=1,
            observation_calls=1,
            input_tokens=1,
            result_bytes=1,
            duration_ms=1,
            human_approvals=1,
            retries=1,
        ),
    )


def _promote(
    definition: ProcedureDefinition,
    *,
    candidate_evaluation: ProcedureEvaluation,
    baseline_evaluation: ProcedureEvaluation,
    rollback_target: ProcedurePin,
    active: bool,
) -> ProcedureLifecycle:
    lifecycle = create_procedure_candidate(
        definition,
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


def _evidence_pair(
    *, policy_digest: str = POLICY_DIGEST
) -> tuple[ShadowStrategyEvidence, ShadowStrategyEvidence]:
    baseline_definition = _baseline_definition(policy_digest=policy_digest)
    baseline_evaluation = _evaluation(baseline_definition)
    candidate_definition = _candidate_definition(policy_digest=policy_digest)
    candidate_evaluation = _evaluation(candidate_definition)
    manual = ProcedurePin("manual_baseline", 1, "f" * 64)
    baseline = _promote(
        baseline_definition,
        candidate_evaluation=baseline_evaluation,
        baseline_evaluation=_evaluation(
            _definition(
                procedure_id="screenshot_then_click",
                observation_tool="screenshot",
                source_digest="c" * 64,
                policy_digest=policy_digest,
            )
        ),
        rollback_target=manual,
        active=True,
    )
    active_pin = ProcedurePin(
        baseline_definition.procedure_id,
        baseline_definition.procedure_version,
        baseline_definition.digest,
    )
    candidate = _promote(
        candidate_definition,
        candidate_evaluation=candidate_evaluation,
        baseline_evaluation=baseline_evaluation,
        rollback_target=active_pin,
        active=False,
    )
    return (
        ShadowStrategyEvidence(baseline, baseline_evaluation),
        ShadowStrategyEvidence(candidate, candidate_evaluation),
    )


def _comparison(*, policy_digest: str = POLICY_DIGEST):
    active, candidate = _evidence_pair(policy_digest=policy_digest)
    comparison = compare_shadow_strategies(
        (active, candidate),
        policy=_shadow_policy(),
        evaluated_at=NOW + timedelta(seconds=4),
    )
    assert comparison.recommended_procedure == candidate.pin
    return comparison, active, candidate


def _routing_policy(*, max_canary_runs: int = 2) -> AdaptiveRoutingPolicy:
    return AdaptiveRoutingPolicy(
        policy_id="dialog_canary",
        policy_version=1,
        baseline_warmup_successes=1,
        canary_interval=10,
        max_canary_runs=max_canary_runs,
    )


def _rollout(
    *, max_canary_runs: int = 2, policy_digest: str = POLICY_DIGEST
):
    comparison, active, candidate = _comparison(policy_digest=policy_digest)
    rollout = create_adaptive_rollout(
        comparison,
        (candidate, active),
        policy=_routing_policy(max_canary_runs=max_canary_runs),
        now=NOW + timedelta(seconds=5),
        expires_at=NOW + timedelta(days=20),
    )
    return rollout, active, candidate


def _context(
    *,
    risk: ActionRiskTier = ActionRiskTier.LOW,
    policy_digest: str = POLICY_DIGEST,
) -> AdaptiveRoutingContext:
    return AdaptiveRoutingContext(
        task_scope="dismiss_dialog",
        application_scope="safe_app",
        application_version="1.0",
        task_digest=TASK_DIGEST,
        registry_digest=reviewed_registry_digest(),
        policy_digest=policy_digest,
        preconditions=(ProcedureFact("dialog_present", FactType.BOOLEAN, True),),
        action_risks=(risk,),
        action_call_digests=(
            adaptive_action_call_digest("click", {"ref": "ref_1"}),
        ),
    )


def _outcome(decision, **overrides: object) -> AdaptiveRoutingOutcome:
    values: dict[str, object] = {
        "decision_digest": decision.digest,
        "selected_procedure": decision.selected_procedure,
        "context_digest": decision.context.digest,
        "source_episode_digest": "e" * 64,
        "terminal": EpisodeOutcomeLabel.VERIFIED_SUCCESS,
        "safety_escapes": 0,
        "authority_regressions": 0,
        "approval_gate_unchanged": True,
        "authority_gate_unchanged": True,
        "known_side_effect_outcome": True,
        "verified_postcondition": True,
    }
    values.update(overrides)
    return AdaptiveRoutingOutcome(**values)  # type: ignore[arg-type]


def _route_and_record_success(rollout, active, candidate, *, index: int):
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=candidate,
        context=_context(),
        expected_revision=rollout.revision,
        now=NOW + timedelta(minutes=index),
    )
    updated = record_adaptive_outcome(
        transition.rollout,
        _outcome(transition.decision),
        expected_revision=transition.rollout.revision,
    )
    return updated, transition.decision


def test_policy_and_rollout_are_strict_visible_and_non_authorizing() -> None:
    rollout, active, candidate = _rollout()
    policy = rollout.policy.to_payload()
    assert policy["maximum_canary_fraction"] == {"numerator": 1, "denominator": 10}
    assert policy["rollback"]["automatic_candidate_retry"] is False  # type: ignore[index]
    payload = rollout.to_payload()
    assert payload["data_class"] == ADAPTIVE_ROUTING_DATA_CLASS
    assert payload["use"] == ADAPTIVE_ROUTING_USE
    assert payload["active_baseline"] == active.pin.to_payload()
    assert payload["candidate"] == candidate.pin.to_payload()
    assert payload["automatic_promotion"] is False
    assert len(rollout.digest) == 64
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_POLICY_INVALID"):
        replace(rollout.policy, canary_interval=9)


def test_rollout_requires_the_exact_evidence_scored_by_l3() -> None:
    comparison, active, candidate = _comparison()
    lifecycle = create_procedure_candidate(
        candidate.definition,
        now=NOW + timedelta(seconds=5),
        expires_at=NOW + timedelta(days=30),
        rollback_target=active.pin,
    )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.EVALUATING,
        expected_revision=0,
        now=NOW + timedelta(seconds=6),
    )
    lifecycle = transition_procedure_candidate(
        lifecycle,
        ProcedureStatus.SHADOW,
        expected_revision=1,
        now=NOW + timedelta(seconds=7),
        reviewed=True,
        candidate_evaluation=candidate.evaluation,
        baseline_evaluation=active.evaluation,
    )
    refreshed_candidate = ShadowStrategyEvidence(lifecycle, candidate.evaluation)
    assert refreshed_candidate.pin == candidate.pin
    assert refreshed_candidate.digest != candidate.digest
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_EVIDENCE_INVALID"):
        create_adaptive_rollout(
            comparison,
            (active, refreshed_candidate),
            policy=_routing_policy(),
            now=NOW + timedelta(seconds=8),
            expires_at=NOW + timedelta(days=20),
        )


def test_canary_schedule_is_prefix_bounded_and_never_auto_promotes() -> None:
    rollout, active, candidate = _rollout(max_canary_runs=2)
    choices: list[AdaptiveRouteChoice] = []
    for index in range(1, 21):
        rollout, decision = _route_and_record_success(
            rollout,
            active,
            candidate,
            index=index,
        )
        choices.append(decision.choice)
        assert choices.count(AdaptiveRouteChoice.CANARY_CANDIDATE) <= index // 10
    assert choices[9] is AdaptiveRouteChoice.CANARY_CANDIDATE
    assert choices[19] is AdaptiveRouteChoice.CANARY_CANDIDATE
    assert rollout.status is AdaptiveRolloutStatus.COMPLETE
    assert rollout.candidate_successes == 2
    assert rollout.to_payload()["automatic_promotion"] is False
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_ROLLOUT_INACTIVE"):
        route_adaptive_procedure(
            rollout,
            active_evidence=active,
            candidate_evidence=candidate,
            context=_context(),
            expected_revision=rollout.revision,
            now=NOW + timedelta(hours=1),
        )


def test_non_low_risk_context_can_only_select_active_baseline() -> None:
    rollout, active, candidate = _rollout()
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=candidate,
        context=_context(risk=ActionRiskTier.HIGH),
        expected_revision=0,
        now=NOW + timedelta(minutes=1),
    )
    assert transition.decision.choice is AdaptiveRouteChoice.ACTIVE_BASELINE
    assert transition.decision.reason == "NON_LOW_RISK_BASELINE_ONLY"
    assert transition.decision.selected_procedure == active.pin
    assert transition.decision.to_payload()["capabilities"] == {
        "authorize": False,
        "approve": False,
        "dispatch": False,
        "execute": False,
        "retry": False,
        "replay": False,
        "inject_memory": False,
        "promote_procedure": False,
        "train": False,
    }


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"terminal": EpisodeOutcomeLabel.UNCERTAIN, "known_side_effect_outcome": False},
            "CANDIDATE_OUTCOME_REGRESSION",
        ),
        ({"safety_escapes": 1}, "CANDIDATE_OUTCOME_REGRESSION"),
        ({"authority_regressions": 1}, "CANDIDATE_OUTCOME_REGRESSION"),
        ({"approval_gate_unchanged": False}, "CANDIDATE_OUTCOME_REGRESSION"),
        ({"authority_gate_unchanged": False}, "CANDIDATE_OUTCOME_REGRESSION"),
    ],
)
def test_first_canary_regression_rolls_back_without_retry(
    overrides: dict[str, object], reason: str
) -> None:
    rollout, active, candidate = _rollout()
    for index in range(1, 10):
        rollout, _ = _route_and_record_success(
            rollout,
            active,
            candidate,
            index=index,
        )
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=candidate,
        context=_context(),
        expected_revision=rollout.revision,
        now=NOW + timedelta(minutes=10),
    )
    assert transition.decision.choice is AdaptiveRouteChoice.CANARY_CANDIDATE
    rolled_back = record_adaptive_outcome(
        transition.rollout,
        _outcome(transition.decision, **overrides),
        expected_revision=transition.rollout.revision,
    )
    assert rolled_back.status is AdaptiveRolloutStatus.ROLLED_BACK
    assert rolled_back.rollback_reason == reason
    assert rolled_back.active_baseline == active.pin
    assert rolled_back.to_payload()["automatic_candidate_retry"] is False
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_ROLLOUT_INACTIVE"):
        route_adaptive_procedure(
            rolled_back,
            active_evidence=active,
            candidate_evidence=candidate,
            context=_context(),
            expected_revision=rolled_back.revision,
            now=NOW + timedelta(minutes=11),
        )


def test_pending_cas_and_forged_outcome_fail_closed() -> None:
    rollout, active, candidate = _rollout()
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=candidate,
        context=_context(),
        expected_revision=0,
        now=NOW + timedelta(minutes=1),
    )
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_OUTCOME_REQUIRED"):
        route_adaptive_procedure(
            transition.rollout,
            active_evidence=active,
            candidate_evidence=candidate,
            context=_context(),
            expected_revision=transition.rollout.revision,
            now=NOW + timedelta(minutes=2),
        )
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_REVISION_CONFLICT"):
        record_adaptive_outcome(
            transition.rollout,
            _outcome(transition.decision),
            expected_revision=0,
        )
    forged = replace(_outcome(transition.decision), decision_digest="0" * 64)
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_OUTCOME_MISMATCH"):
        record_adaptive_outcome(
            transition.rollout,
            forged,
            expected_revision=transition.rollout.revision,
        )


def test_candidate_evidence_drift_issues_one_exact_rollback_fallback() -> None:
    rollout, active, candidate = _rollout()
    other_definition = _definition(
        procedure_id="alternate_find_then_click",
        observation_tool="find",
        source_digest="9" * 64,
    )
    other_evaluation = _evaluation(other_definition)
    other_lifecycle = _promote(
        other_definition,
        candidate_evaluation=other_evaluation,
        baseline_evaluation=active.evaluation,
        rollback_target=active.pin,
        active=False,
    )
    other = ShadowStrategyEvidence(other_lifecycle, other_evaluation)
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=other,
        context=_context(),
        expected_revision=0,
        now=NOW + timedelta(minutes=1),
    )
    assert transition.rollout.status is AdaptiveRolloutStatus.ROLLED_BACK
    assert transition.rollout.rollback_reason == "CANDIDATE_EVIDENCE_DRIFT"
    assert transition.decision.choice is AdaptiveRouteChoice.ROLLBACK_BASELINE
    assert transition.decision.selected_procedure == active.pin
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_ACTIVE_EVIDENCE_DRIFT"):
        route_adaptive_procedure(
            rollout,
            active_evidence=candidate,
            candidate_evidence=candidate,
            context=_context(),
            expected_revision=0,
            now=NOW + timedelta(minutes=1),
        )


def test_expired_rollout_cannot_fallback_through_expired_active_evidence() -> None:
    rollout, active, candidate = _rollout()
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_ACTIVE_EVIDENCE_EXPIRED"):
        route_adaptive_procedure(
            rollout,
            active_evidence=active,
            candidate_evidence=candidate,
            context=_context(),
            expected_revision=0,
            now=NOW + timedelta(days=31),
        )
    assert rollout.revision == 0
    assert rollout.pending_decision is None


def test_exact_context_drift_fails_before_selection() -> None:
    rollout, active, candidate = _rollout()
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_CONTEXT_MISMATCH"):
        route_adaptive_procedure(
            rollout,
            active_evidence=active,
            candidate_evidence=candidate,
            context=_context(policy_digest="2" * 64),
            expected_revision=0,
            now=NOW + timedelta(minutes=1),
        )
    assert rollout.revision == 0
    assert rollout.pending_decision is None


def _candidate_plan(
    *, observation_tool: str = "find", action_ref: str = "ref_1"
):
    return compile_task_plan(
        json.dumps(
            {
                "version": 1,
                "steps": [
                    {
                        "action": "tool",
                        "tool": observation_tool,
                        "arguments": (
                            {"query": "dialog"} if observation_tool == "find" else {}
                        ),
                    },
                    {
                        "action": "tool",
                        "tool": "click",
                        "arguments": {"ref": action_ref},
                    },
                    {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
                    {"action": "final_response"},
                ],
            }
        ),
        plan_id="plan_l4",
        run_id="run_l4",
        task=TASK,
        allowed_tools=("find", "ui_snapshot", "click", "screenshot"),
    )


def test_selected_procedure_binds_exactly_to_separate_h7_plan() -> None:
    rollout, active, candidate = _rollout()
    for index in range(1, 10):
        rollout, _ = _route_and_record_success(
            rollout,
            active,
            candidate,
            index=index,
        )
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=candidate,
        context=_context(),
        expected_revision=rollout.revision,
        now=NOW + timedelta(minutes=10),
    )
    binding = bind_adaptive_h7_plan(
        transition.decision,
        candidate,
        _candidate_plan(),
    )
    assert binding.procedure == candidate.pin
    assert binding.ordered_tool_names == ("find", "click", "ui_snapshot")
    assert binding.to_payload()["contains_arguments"] is False
    fixtures = _fixtures()
    drifted_evaluation = evaluate_procedure(
        candidate.definition,
        (replace(fixtures[0], source_episode_digest="e" * 64), *fixtures[1:]),
    )
    refreshed_candidate = ShadowStrategyEvidence(
        candidate.lifecycle,
        drifted_evaluation,
    )
    assert refreshed_candidate.pin == candidate.pin
    assert refreshed_candidate.digest != candidate.digest
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_PLAN_BINDING_INVALID"):
        bind_adaptive_h7_plan(
            transition.decision,
            refreshed_candidate,
            _candidate_plan(),
        )
    with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_PLAN_TOOL_MISMATCH"):
        bind_adaptive_h7_plan(
            transition.decision,
            candidate,
            _candidate_plan(observation_tool="screenshot"),
        )
    with pytest.raises(
        AdaptiveRoutingError,
        match="ADAPTIVE_PLAN_ACTION_RISK_MISMATCH",
    ):
        bind_adaptive_h7_plan(
            transition.decision,
            candidate,
            _candidate_plan(action_ref="ref_2"),
        )


def test_routed_opener_passes_only_validated_binding_to_existing_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rollout, active, candidate = _rollout()
    for index in range(1, 10):
        rollout, _ = _route_and_record_success(
            rollout,
            active,
            candidate,
            index=index,
        )
    transition = route_adaptive_procedure(
        rollout,
        active_evidence=active,
        candidate_evidence=candidate,
        context=_context(),
        expected_revision=rollout.revision,
        now=NOW + timedelta(minutes=10),
    )
    plan = _candidate_plan()
    binding = bind_adaptive_h7_plan(transition.decision, candidate, plan)
    sentinel = object()
    captured: dict[str, object] = {}

    async def fake_open(*args: object, **kwargs: object):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(runtime_module, "_open_runtime_executor_session", fake_open)
    result = asyncio.run(
        runtime_module.open_adaptive_routed_hierarchical_side_effect_runtime_executor_session(
                object(),  # type: ignore[arg-type]
                task=TASK,
                plan=plan,
                tree_id="tree_l4",
                route_binding=binding,
        )
    )
    assert result is sentinel
    assert captured == {
        "task": TASK,
        "plan": plan,
        "tree_id": "tree_l4",
        "allow_hierarchical_side_effects": True,
        "route_binding": binding,
    }


def test_adaptive_router_has_no_execution_or_external_port() -> None:
    source = inspect.getsource(routing_module)
    assert not hasattr(routing_module, "AgentRunner")
    assert not hasattr(routing_module, "ToolCall")
    assert not hasattr(routing_module, "MemoryStore")
    assert ".desktop.call_tool(" not in source
    assert "request_approval(" not in source
    runtime_source = inspect.getsource(runtime_module)
    assert ".desktop.call_tool(" not in runtime_source
    assert runtime_source.count("_execute_requested_call_boundary(") == 1
    assert runtime_policy_digest is not None


def test_atomic_store_persists_pending_decision_and_exact_outcome(
    tmp_path: Path,
) -> None:
    rollout, active, candidate = _rollout()
    state_dir = tmp_path.resolve() / "state"
    lock = adaptive_routing_lock(state_dir, rollout.rollout_id)
    store = AdaptiveRoutingStore(state_dir, rollout.rollout_id, lock)
    with pytest.raises(AdaptiveRoutingStoreError, match="ADAPTIVE_STORE_LOCK_REQUIRED"):
        store.create(rollout)
    with lock:
        created = store.create(rollout)
        transition = store.route(
            active_evidence=active,
            candidate_evidence=candidate,
            context=_context(),
            expected_revision=created.revision,
            expected_digest=created.digest,
            now=NOW + timedelta(minutes=1),
        )
        assert store.read() == transition.rollout
        assert store.path.stat().st_size < routing_module.MAX_ADAPTIVE_ROUTING_STORE_BYTES

    reopened_lock = adaptive_routing_lock(state_dir, rollout.rollout_id)
    reopened = AdaptiveRoutingStore(state_dir, rollout.rollout_id, reopened_lock)
    with reopened_lock:
        pending = reopened.read()
        assert pending.pending_decision == transition.decision
        with pytest.raises(AdaptiveRoutingError, match="ADAPTIVE_OUTCOME_REQUIRED"):
            reopened.route(
                active_evidence=active,
                candidate_evidence=candidate,
                context=_context(),
                expected_revision=pending.revision,
                expected_digest=pending.digest,
                now=NOW + timedelta(minutes=2),
            )
        with pytest.raises(
            AdaptiveRoutingStoreError,
            match="ADAPTIVE_STORE_REVISION_CONFLICT",
        ):
            reopened.record_outcome(
                _outcome(transition.decision),
                expected_revision=0,
                expected_digest=rollout.digest,
            )
        recorded = reopened.record_outcome(
            _outcome(transition.decision),
            expected_revision=pending.revision,
            expected_digest=pending.digest,
        )
        assert recorded.pending_decision is None
        assert recorded.last_outcome_digest is not None
        assert reopened.read() == recorded


def test_store_write_failure_preserves_last_durable_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rollout, active, candidate = _rollout()
    state_dir = tmp_path.resolve() / "state"
    lock = adaptive_routing_lock(state_dir, rollout.rollout_id)
    store = AdaptiveRoutingStore(state_dir, rollout.rollout_id, lock)
    with lock:
        created = store.create(rollout)

        def fail_replace(*_args: object, **_kwargs: object) -> None:
            raise OSError("injected atomic replacement failure")

        monkeypatch.setattr(routing_module.os, "replace", fail_replace)
        with pytest.raises(
            AdaptiveRoutingStoreError,
            match="ADAPTIVE_STORE_WRITE_FAILED",
        ):
            store.route(
                active_evidence=active,
                candidate_evidence=candidate,
                context=_context(),
                expected_revision=created.revision,
                expected_digest=created.digest,
                now=NOW + timedelta(minutes=1),
            )
        assert store.read() == created


def test_store_rejects_tamper_and_wrong_lock_scope(tmp_path: Path) -> None:
    rollout, _, _ = _rollout()
    state_dir = tmp_path.resolve() / "state"
    lock = adaptive_routing_lock(state_dir, rollout.rollout_id)
    with pytest.raises(ValueError, match="exact adaptive routing lock"):
        AdaptiveRoutingStore(
            state_dir,
            rollout.rollout_id,
            adaptive_routing_lock(state_dir, "0" * 64),
        )
    store = AdaptiveRoutingStore(state_dir, rollout.rollout_id, lock)
    with lock:
        store.create(rollout)
        payload = json.loads(store.path.read_text("utf-8"))
        payload["rollout"]["candidate_successes"] = 1
        payload["rollout_digest"] = routing_module._digest(payload["rollout"])
        unsigned = {
            key: value for key, value in payload.items() if key != "envelope_digest"
        }
        payload["envelope_digest"] = routing_module._digest(unsigned)
        store.path.write_text(json.dumps(payload), "utf-8")
        with pytest.raises(
            AdaptiveRoutingStoreError,
            match="ADAPTIVE_STORE_INVALID|ADAPTIVE_STORE_DIGEST_MISMATCH",
        ):
            store.read()


def test_persisted_canary_composes_with_real_h7_runner_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _runtime_config(tmp_path, monkeypatch)
    desktop = RoutedDialogApplication()
    approvals = RoutedApprovalPort()
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=FakeModelProvider(),
            desktop=desktop,
            approvals=approvals,
        ),
    )
    policy_digest = runtime_policy_digest(runner.policy)
    rollout, active, candidate = _rollout(
        max_canary_runs=1,
        policy_digest=policy_digest,
    )
    context = _context(policy_digest=policy_digest)
    route_lock = adaptive_routing_lock(config.state_dir, rollout.rollout_id)
    store = AdaptiveRoutingStore(config.state_dir, rollout.rollout_id, route_lock)
    with route_lock:
        current = store.create(rollout)
        for index in range(1, 10):
            transition = store.route(
                active_evidence=active,
                candidate_evidence=candidate,
                context=context,
                expected_revision=current.revision,
                expected_digest=current.digest,
                now=NOW + timedelta(minutes=index),
            )
            current = store.record_outcome(
                _outcome(transition.decision),
                expected_revision=transition.rollout.revision,
                expected_digest=transition.rollout.digest,
            )
        canary = store.route(
            active_evidence=active,
            candidate_evidence=candidate,
            context=context,
            expected_revision=current.revision,
            expected_digest=current.digest,
            now=NOW + timedelta(minutes=10),
        )
        assert canary.decision.choice is AdaptiveRouteChoice.CANARY_CANDIDATE

    plan = _candidate_plan()
    binding = bind_adaptive_h7_plan(canary.decision, candidate, plan)
    session = asyncio.run(
        open_adaptive_routed_hierarchical_side_effect_runtime_executor_session(
            runner,
            task=TASK,
            plan=plan,
            tree_id="tree_l4",
            route_binding=binding,
        )
    )
    before = asyncio.run(session.execute_next_tool())
    action = asyncio.run(session.execute_next_tool())
    after = asyncio.run(session.execute_next_tool())
    final_port = RoutedFinalPort()
    final = asyncio.run(session.execute_final_response(final_port))

    assert [call.name for call in desktop.tool_calls] == [
        "find",
        "click",
        "ui_snapshot",
    ]
    assert len(approvals.requests) == 1
    assert final_port.requests[0].observations[0].tool_name == "find"
    assert final_port.requests[0].observations[1].tool_name == "ui_snapshot"
    for runtime_outcome in (before, action, after, final):
        assert runtime_outcome.route_binding_digest == binding.digest
        assert runtime_outcome.routed_procedure == candidate.pin

    outcome = _outcome(canary.decision)
    reopened_lock = adaptive_routing_lock(config.state_dir, rollout.rollout_id)
    reopened = AdaptiveRoutingStore(
        config.state_dir,
        rollout.rollout_id,
        reopened_lock,
    )
    with reopened_lock:
        pending = reopened.read()
        completed = reopened.record_outcome(
            outcome,
            expected_revision=pending.revision,
            expected_digest=pending.digest,
        )
    assert completed.status is AdaptiveRolloutStatus.COMPLETE
    assert completed.candidate_successes == 1
    assert completed.pending_decision is None
