from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from computer_use_agent import executor_final as executor_final_module
from computer_use_agent.executor_final import (
    ExecutorFinalError,
    FinalResponsePort,
    compile_final_response_request,
)
from computer_use_agent.plan_store import PersistedTaskPlan
from computer_use_agent.planning import (
    PlanStepStatus,
    compile_task_plan,
    transition_plan_step,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    RecoveryStatus,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


TASK = "Inspect the current UI"
SECRET_OBSERVATION = "private desktop observation"


def _ready() -> tuple[PersistedTaskPlan, RunState]:
    plan = compile_task_plan(
        '{"version":1,"steps":['
        '{"action":"tool","tool":"find","arguments":{"query":"status"}},'
        '{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=("find",),
    )
    running = transition_plan_step(plan, "step_1", PlanStepStatus.IN_PROGRESS)
    completed = transition_plan_step(running, "step_1", PlanStepStatus.COMPLETED)
    snapshot = PersistedTaskPlan(
        plan=completed,
        sequence=2,
        envelope_digest="e" * 64,
    )
    identity = CallIdentity("run_1", "executor_turn_1", "call_1")
    call = ToolCall(identity, "find", {"query": "status"})
    result = ToolResult(
        identity=identity,
        tool_name="find",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text=SECRET_OBSERVATION,
    )
    state = RunState(
        run_id="run_1",
        task=TASK,
        policy_version="readonly-v1",
        observation_epoch=1,
        verified_observation_epoch=1,
        recovery_status=RecoveryStatus.READY,
        budgets=RunBudget(
            max_model_turns=4,
            max_tool_calls=4,
            max_side_effects=0,
            tool_calls_used=1,
        ),
        event_log=(
            LedgerEvent(
                "run_1:event:1",
                LedgerEventKind.USER_TASK,
                payload={"task_length": len(TASK)},
            ),
            LedgerEvent(
                "run_1:event:2",
                LedgerEventKind.TOOL_CALL,
                identity=identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=()
                ),
            ),
            LedgerEvent(
                "run_1:event:3",
                LedgerEventKind.TOOL_RESULT,
                identity=identity,
                tool_result=result,
            ),
            LedgerEvent(
                "run_1:event:4",
                LedgerEventKind.OBSERVATION,
                identity=identity,
                payload={"tool_name": "find", "observation_epoch": 1},
            ),
        ),
    )
    return snapshot, state


def _compile(
    snapshot: PersistedTaskPlan | None = None,
    state: RunState | None = None,
    **changes: object,
):
    resolved_snapshot, resolved_state = _ready()
    if snapshot is not None:
        resolved_snapshot = snapshot
    if state is not None:
        resolved_state = state
    arguments: dict[str, object] = {
        "expected_sequence": resolved_snapshot.sequence,
        "expected_plan_digest": resolved_snapshot.plan.digest,
        "turn_id": "executor_final_1",
    }
    arguments.update(changes)
    return compile_final_response_request(
        resolved_snapshot,
        resolved_state,
        **arguments,  # type: ignore[arg-type]
    )


def test_compiler_projects_exact_observations_into_inert_tool_free_data() -> None:
    snapshot, state = _ready()
    request = _compile(snapshot, state)

    assert request.run_id == "run_1"
    assert request.plan_id == "plan_1"
    assert request.plan_digest == snapshot.plan.digest
    assert request.snapshot_sequence == 2
    assert request.turn_id == "executor_final_1"
    assert request.task == TASK
    assert len(request.observations) == 1
    observation = request.observations[0]
    assert observation.step_id == "step_1"
    assert observation.tool_name == "find"
    assert observation.arguments_json == '{"query":"status"}'
    assert observation.sanitized_text == SECRET_OBSERVATION
    assert observation.images == ()
    assert len(request.request_digest) == 64
    assert snapshot.plan.steps[-1].status is PlanStepStatus.PENDING
    assert state.budgets.model_turns_used == 0
    assert not hasattr(request, "tools")
    assert not hasattr(request, "tool_calls")


def test_contract_repr_does_not_disclose_task_or_observation_content() -> None:
    request = _compile()

    assert TASK not in repr(request)
    assert SECRET_OBSERVATION not in repr(request)
    assert SECRET_OBSERVATION not in repr(request.observations[0])
    assert "task_length=" in repr(request)
    assert "text_length=" in repr(request.observations[0])

    with pytest.raises(ValueError, match="request_digest"):
        replace(request, task=TASK + " changed")


def test_final_response_port_has_only_one_tool_free_text_method() -> None:
    source = inspect.getsource(executor_final_module)

    assert "call_tool(" not in source
    assert "create_turn(" not in source
    assert "request_approval(" not in source
    assert "transition(" not in source
    public_methods = {
        name
        for name, value in FinalResponsePort.__dict__.items()
        if not name.startswith("_") and callable(value)
    }
    assert public_methods == {"create_final_response"}


@pytest.mark.parametrize(
    ("sequence", "digest"),
    [(3, None), (None, "0" * 64)],
)
def test_stale_plan_expectations_fail_without_mutation(
    sequence: int | None, digest: str | None
) -> None:
    snapshot, state = _ready()
    before = snapshot.plan.digest
    changes = {
        "expected_sequence": snapshot.sequence if sequence is None else sequence,
        "expected_plan_digest": snapshot.plan.digest if digest is None else digest,
    }

    with pytest.raises(ExecutorFinalError, match="^EXECUTOR_FINAL_PLAN_STALE$"):
        _compile(snapshot, state, **changes)
    assert snapshot.plan.digest == before
    assert snapshot.plan.steps[-1].status is PlanStepStatus.PENDING


@pytest.mark.parametrize(
    "state_change",
    [
        lambda state: replace(state, task="different task"),
        lambda state: replace(state, recovery_status=RecoveryStatus.UNKNOWN_OUTCOME),
        lambda state: replace(state, verified_observation_epoch=None),
        lambda state: replace(
            state,
            budgets=replace(
                state.budgets,
                model_turns_used=state.budgets.max_model_turns,
            ),
        ),
        lambda state: replace(
            state,
            budgets=replace(
                state.budgets,
                input_tokens_used=state.budgets.max_input_tokens,
            ),
        ),
        lambda state: replace(
            state,
            budgets=replace(state.budgets, tool_calls_used=2),
        ),
    ],
)
def test_identity_recovery_grounding_and_budget_drift_fail_closed(state_change) -> None:
    snapshot, state = _ready()

    with pytest.raises(ExecutorFinalError):
        _compile(snapshot, state_change(state))


@pytest.mark.parametrize(
    "drift",
    ["argument", "redacted", "identity", "result", "observation", "extra"],
)
def test_ledger_drift_and_historical_provider_events_are_rejected(drift: str) -> None:
    snapshot, state = _ready()
    events = list(state.event_log)
    if drift == "argument":
        call = ToolCall(events[1].identity, "find", {"query": "different"})
        events[1] = LedgerEvent(
            events[1].event_id,
            LedgerEventKind.TOOL_CALL,
            identity=call.identity,
            safe_argument_summary=SafeArgumentSummary.from_tool_call(
                call, sensitive_arguments=()
            ),
        )
    elif drift == "redacted":
        events[1] = replace(
            events[1],
            safe_argument_summary=SafeArgumentSummary(
                tool_name="find",
                values={"query_present": True, "query_length": 6},
                redacted_fields=("query",),
            ),
        )
    elif drift == "identity":
        identity = CallIdentity("run_1", "executor_turn_1", "different")
        events[3] = LedgerEvent(
            events[3].event_id,
            LedgerEventKind.OBSERVATION,
            identity=identity,
            payload=events[3].payload,
        )
    elif drift == "result":
        prior = events[2].tool_result
        assert prior is not None
        failed = ToolResult(
            identity=prior.identity,
            tool_name=prior.tool_name,
            status=ToolResultStatus.TRANSPORT_ERROR,
            dispatch=DispatchCertainty.NOT_DISPATCHED,
            code="MCP_TIMEOUT_BEFORE_DISPATCH",
        )
        events[2] = replace(events[2], tool_result=failed)
    elif drift == "observation":
        events.pop()
    else:
        events.append(
            LedgerEvent(
                "run_1:event:5",
                LedgerEventKind.MODEL_TURN,
                payload={"tool_call_count": 0},
            )
        )

    with pytest.raises(ExecutorFinalError, match="^EXECUTOR_FINAL_LEDGER_INVALID$"):
        _compile(snapshot, replace(state, event_log=tuple(events)))


def test_plan_must_end_with_pending_final_after_one_to_four_completed_observations() -> None:
    snapshot, state = _ready()
    final_running = transition_plan_step(
        snapshot.plan, "step_2", PlanStepStatus.IN_PROGRESS
    )
    started = replace(snapshot, plan=final_running, sequence=3)

    with pytest.raises(ExecutorFinalError, match="^EXECUTOR_FINAL_PLAN_NOT_READY$"):
        _compile(started, state)

    final_only = compile_task_plan(
        '{"version":1,"steps":[{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=(),
    )
    with pytest.raises(ExecutorFinalError, match="^EXECUTOR_FINAL_PLAN_NOT_READY$"):
        _compile(
            PersistedTaskPlan(final_only, 0, "e" * 64),
            replace(state, observation_epoch=0, verified_observation_epoch=0),
        )


def test_request_digest_is_lossless_and_request_size_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _compile()
    snapshot, state = _ready()
    result = state.event_log[2].tool_result
    assert result is not None
    changed_result = replace(result, sanitized_text=SECRET_OBSERVATION + "!")
    events = list(state.event_log)
    events[2] = replace(events[2], tool_result=changed_result)
    changed = _compile(snapshot, replace(state, event_log=tuple(events)))

    assert changed.request_digest != first.request_digest
    monkeypatch.setattr(executor_final_module, "MAX_FINAL_RESPONSE_REQUEST_BYTES", 1)
    with pytest.raises(ExecutorFinalError, match="^EXECUTOR_FINAL_REQUEST_TOO_LARGE$"):
        _compile(snapshot, state)
