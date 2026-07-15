from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

import pytest

from computer_use_agent.executor import (
    ExecutorPreflightError,
    PreparedPlanToolCall,
    compile_plan_tool_preflight,
)
from computer_use_agent.plan_store import PersistedTaskPlan
from computer_use_agent.planning import (
    PlanStepStatus,
    compile_task_plan,
    transition_plan_step,
)
from computer_use_agent.types import (
    CallIdentity,
    LedgerEvent,
    LedgerEventKind,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolCallStatus,
)


TASK = "Inspect the current UI"


def _snapshot(candidate: str | None = None) -> PersistedTaskPlan:
    plan = compile_task_plan(
        candidate
        or '{"version":1,"steps":['
        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
        '{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=("ui_snapshot",),
    )
    return PersistedTaskPlan(plan=plan, sequence=0, envelope_digest="e" * 64)


def _state(**changes: object) -> RunState:
    values: dict[str, object] = {
        "run_id": "run_1",
        "task": TASK,
        "policy_version": "policy-v1",
        "observation_epoch": 0,
        "budgets": RunBudget(max_model_turns=4, max_tool_calls=8, max_side_effects=2),
    }
    values.update(changes)
    return RunState(**values)  # type: ignore[arg-type]


def _compile(
    snapshot: PersistedTaskPlan | None = None,
    state: RunState | None = None,
    **changes: object,
) -> PreparedPlanToolCall:
    resolved = snapshot or _snapshot()
    arguments: dict[str, object] = {
        "expected_sequence": resolved.sequence,
        "expected_plan_digest": resolved.plan.digest,
        "turn_id": "executor_turn_1",
        "call_id": "executor_call_1",
    }
    arguments.update(changes)
    return compile_plan_tool_preflight(
        resolved,
        state or _state(),
        **arguments,  # type: ignore[arg-type]
    )


def test_preflight_reconstructs_only_a_fresh_requested_call() -> None:
    snapshot = _snapshot()
    original_digest = snapshot.plan.digest

    prepared = _compile(snapshot)

    assert prepared.plan_id == "plan_1"
    assert prepared.step_id == "step_1"
    assert prepared.snapshot_sequence == 0
    assert prepared.plan_digest == original_digest
    assert prepared.call.identity == CallIdentity(
        run_id="run_1", turn_id="executor_turn_1", call_id="executor_call_1"
    )
    assert prepared.call.name == "ui_snapshot"
    assert dict(prepared.call.arguments) == {}
    assert prepared.call.status is ToolCallStatus.REQUESTED
    assert snapshot.plan.steps[0].status is PlanStepStatus.PENDING
    assert snapshot.plan.digest == original_digest
    assert not hasattr(prepared, "authorized")
    assert not hasattr(prepared, "dispatch")


def test_preflight_does_not_consume_or_treat_budget_as_authority() -> None:
    budget = RunBudget(
        max_model_turns=1,
        max_tool_calls=1,
        max_side_effects=0,
        model_turns_used=1,
        tool_calls_used=1,
    )
    state = _state(budgets=budget)

    prepared = _compile(state=state)

    assert prepared.call.status is ToolCallStatus.REQUESTED
    assert state.budgets == budget


def test_side_effect_plan_step_still_compiles_only_to_requested() -> None:
    plan = compile_task_plan(
        '{"version":1,"steps":['
        '{"action":"tool","tool":"click","arguments":{"ref":"ref_1"}},'
        '{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=("click",),
    )
    snapshot = PersistedTaskPlan(plan=plan, sequence=0, envelope_digest="a" * 64)

    prepared = _compile(snapshot)

    assert prepared.call.name == "click"
    assert prepared.call.status is ToolCallStatus.REQUESTED
    assert not hasattr(prepared.call, "approval")
    assert not hasattr(prepared.call, "authorized")


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"expected_sequence": 1}, "EXECUTOR_PLAN_SNAPSHOT_STALE"),
        ({"expected_plan_digest": "0" * 64}, "EXECUTOR_PLAN_SNAPSHOT_STALE"),
        ({"turn_id": ""}, "EXECUTOR_IDENTITY_INVALID"),
        ({"call_id": ""}, "EXECUTOR_IDENTITY_INVALID"),
    ],
)
def test_preflight_rejects_stale_snapshot_or_invalid_identity(
    changes: dict[str, object], code: str
) -> None:
    with pytest.raises(ExecutorPreflightError, match=f"^{code}$"):
        _compile(**changes)


def test_preflight_rejects_run_task_and_registry_drift() -> None:
    snapshot = _snapshot()
    cases = (
        (snapshot, _state(run_id="other_run"), "EXECUTOR_RUN_MISMATCH"),
        (snapshot, _state(task="different task"), "EXECUTOR_TASK_MISMATCH"),
        (
            replace(snapshot, plan=replace(snapshot.plan, registry_digest="0" * 64)),
            _state(),
            "EXECUTOR_REGISTRY_MISMATCH",
        ),
    )
    for candidate, state, code in cases:
        with pytest.raises(ExecutorPreflightError, match=f"^{code}$"):
            _compile(candidate, state)


def test_preflight_rejects_started_terminal_and_final_response_steps() -> None:
    snapshot = _snapshot()
    running = replace(
        snapshot,
        plan=transition_plan_step(
            snapshot.plan, "step_1", PlanStepStatus.IN_PROGRESS
        ),
    )
    with pytest.raises(ExecutorPreflightError, match="^EXECUTOR_STEP_NOT_PENDING$"):
        _compile(running)

    final_plan = compile_task_plan(
        '{"version":1,"steps":[{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=(),
    )
    final = PersistedTaskPlan(plan=final_plan, sequence=0, envelope_digest="f" * 64)
    with pytest.raises(
        ExecutorPreflightError, match="^EXECUTOR_FINAL_RESPONSE_NOT_EXECUTABLE$"
    ):
        _compile(final)

    completed_plan = transition_plan_step(
        final_plan, "step_1", PlanStepStatus.IN_PROGRESS
    )
    completed_plan = transition_plan_step(
        completed_plan, "step_1", PlanStepStatus.COMPLETED
    )
    completed = replace(final, plan=completed_plan)
    with pytest.raises(ExecutorPreflightError, match="^EXECUTOR_PLAN_TERMINAL$"):
        _compile(completed)


def test_preflight_rejects_a_call_identity_already_present_in_the_ledger() -> None:
    identity = CallIdentity(
        run_id="run_1", turn_id="executor_turn_1", call_id="executor_call_1"
    )
    call = ToolCall(identity=identity, name="ui_snapshot", arguments={})
    event = LedgerEvent(
        event_id="run_1:event:1",
        kind=LedgerEventKind.TOOL_CALL,
        identity=identity,
        safe_argument_summary=SafeArgumentSummary.from_tool_call(
            call, sensitive_arguments=frozenset()
        ),
    )
    state = _state(event_log=(event,))

    with pytest.raises(
        ExecutorPreflightError, match="^EXECUTOR_CALL_IDENTITY_REUSED$"
    ):
        _compile(state=state)


def test_historical_calls_are_used_only_for_identity_collision_checks() -> None:
    identity = CallIdentity(
        run_id="run_1", turn_id="historical_turn", call_id="historical_call"
    )
    historical = ToolCall(identity=identity, name="click", arguments={"ref": "old_ref"})
    event = LedgerEvent(
        event_id="run_1:event:1",
        kind=LedgerEventKind.TOOL_CALL,
        identity=identity,
        safe_argument_summary=SafeArgumentSummary.from_tool_call(
            historical, sensitive_arguments=frozenset()
        ),
    )

    prepared = _compile(state=_state(event_log=(event,)))

    assert prepared.call.name == "ui_snapshot"
    assert dict(prepared.call.arguments) == {}
    assert prepared.call.identity != identity


def test_task_binding_is_exact_sha256_without_retaining_task_on_result() -> None:
    prepared = _compile()

    assert _snapshot().plan.task_digest == sha256(TASK.encode("utf-8")).hexdigest()
    assert not hasattr(prepared, "task")
