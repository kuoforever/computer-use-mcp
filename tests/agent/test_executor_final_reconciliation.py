from __future__ import annotations

import inspect
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from computer_use_agent import executor_final_reconciliation as reconciliation_module
from computer_use_agent import (
    executor_final_reconciliation_apply as reconciliation_apply_module,
)
from computer_use_agent.continuation import (
    RuntimeContinuationRecorder,
    continuation_path,
    read_continuation,
)
from computer_use_agent.executor_final import (
    FinalResponseResult,
    compile_final_response_request,
)
from computer_use_agent.executor_final_reconciliation import (
    ExecutorFinalReconciliationError,
    compile_final_response_reconciliation,
)
from computer_use_agent.executor_final_reconciliation_apply import (
    apply_completed_final_response_reconciliation,
)
from computer_use_agent.executor_final_store import (
    FinalResponseStage,
    FinalResponseStore,
    final_response_path,
)
from computer_use_agent.plan_store import TaskPlanStore, task_plan_path
from computer_use_agent.planning import PlanStepStatus, compile_task_plan
from computer_use_agent.run_lock import RunLock
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.trace import RunPhase, RunRecorder, read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    ModelUsage,
    RecoveryStatus,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


TASK = "Inspect the current UI"
SECRET = "sensitive completed answer"


@dataclass
class ReconciliationFixture:
    state_dir: Path
    lock: RunLock
    plan_store: TaskPlanStore
    final_store: FinalResponseStore
    task: str
    observed_state: RunState

    def snapshots(self):
        return (
            self.plan_store.read("run_1"),
            self.final_store.read("run_1"),
            read_continuation(self.state_dir, "run_1"),
            read_run_record(self.state_dir, "run_1"),
        )


def _fixture(tmp_path: Path, *, failed_checkpoint: bool = False) -> ReconciliationFixture:
    state_dir = (tmp_path / "state").resolve()
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    plan_store = TaskPlanStore(state_dir, lock)
    final_store = FinalResponseStore(state_dir, lock)
    plan = compile_task_plan(
        '{"version":1,"steps":['
        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
        '{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=("ui_snapshot",),
    )
    snapshot = plan_store.create(plan)
    running_observation = plan_store.transition(
        "run_1",
        "step_1",
        PlanStepStatus.IN_PROGRESS,
        expected_sequence=snapshot.sequence,
        expected_plan_digest=snapshot.plan.digest,
    )
    completed_observation = plan_store.transition(
        "run_1",
        "step_1",
        PlanStepStatus.COMPLETED,
        expected_sequence=running_observation.sequence,
        expected_plan_digest=running_observation.plan.digest,
    )

    identity = CallIdentity("run_1", "executor_turn_1", "call_1")
    call = ToolCall(identity, "ui_snapshot", {})
    result = ToolResult(
        identity=identity,
        tool_name="ui_snapshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="observed",
    )
    initial_budget = RunBudget(4, 4, 0)
    initial = RunState(
        run_id="run_1",
        task=TASK,
        policy_version="readonly-v1",
        observation_epoch=0,
        budgets=initial_budget,
        event_log=(
            LedgerEvent(
                event_id="run_1:event:1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len(TASK)},
            ),
        ),
    )
    observed = replace(
        initial,
        observation_epoch=1,
        verified_observation_epoch=1,
        recovery_status=RecoveryStatus.READY,
        budgets=replace(initial_budget, tool_calls_used=1),
        event_log=initial.event_log
        + (
            LedgerEvent(
                event_id="run_1:event:2",
                kind=LedgerEventKind.TOOL_CALL,
                identity=identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=()
                ),
            ),
            LedgerEvent(
                event_id="run_1:event:3",
                kind=LedgerEventKind.TOOL_RESULT,
                identity=identity,
                tool_result=result,
                payload={"latency_ms": 5},
            ),
            LedgerEvent(
                event_id="run_1:event:4",
                kind=LedgerEventKind.OBSERVATION,
                identity=identity,
                payload={"tool_name": "ui_snapshot", "observation_epoch": 1},
            ),
        ),
    )
    recorder = RunRecorder(state_dir, "run_1")
    recorder.start(initial)
    recorder.record(initial, RunPhase.OBSERVING)
    recorder.record(observed, RunPhase.PLANNING)
    continuation = RuntimeContinuationRecorder(
        state_dir=state_dir,
        state=initial,
        provider_name="openai",
        provider_model="test-model",
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(),
        ttl_seconds=3600,
        mcp_generation=1,
    )
    continuation.prepare_tool(
        replace(initial, budgets=replace(initial_budget, tool_calls_used=1)),
        call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=recorder.checkpoint_sequence,
    )
    continuation.dispatch_tool(
        replace(initial, budgets=replace(initial_budget, tool_calls_used=1)),
        checkpoint_sequence=recorder.checkpoint_sequence,
    )
    envelope = continuation.complete_tool(
        observed, result, checkpoint_sequence=recorder.checkpoint_sequence
    )
    request = compile_final_response_request(
        completed_observation,
        observed,
        expected_sequence=completed_observation.sequence,
        expected_plan_digest=completed_observation.plan.digest,
        turn_id="executor_final_1",
    )
    continuation_digest = envelope.payload["payload_digest"]
    assert isinstance(continuation_digest, str)
    prepared = final_store.create(
        request,
        step_id="step_2",
        checkpoint_sequence=recorder.checkpoint_sequence,
        continuation_digest=continuation_digest,
    )
    running_final = plan_store.transition(
        "run_1",
        "step_2",
        PlanStepStatus.IN_PROGRESS,
        expected_sequence=completed_observation.sequence,
        expected_plan_digest=completed_observation.plan.digest,
    )
    intent = final_store.mark_dispatch_intent(
        "run_1",
        expected_sequence=prepared.sequence,
        expected_digest=prepared.envelope_digest,
    )
    final_result = FinalResponseResult(
        run_id="run_1",
        turn_id="executor_final_1",
        provider_response_id="resp_final_1",
        text=SECRET,
        usage=ModelUsage(11, 7),
    )
    final_store.complete(
        "run_1",
        final_result,
        provider_latency_ms=23,
        expected_sequence=intent.sequence,
        expected_digest=intent.envelope_digest,
    )
    if failed_checkpoint:
        terminal_state = replace(
            observed,
            budgets=replace(
                observed.budgets,
                model_turns_used=1,
                input_tokens_used=11,
            ),
            event_log=observed.event_log
            + (
                LedgerEvent(
                    event_id="run_1:event:5",
                    kind=LedgerEventKind.MODEL_TURN,
                    payload={
                        "provider_response_id": "resp_final_1",
                        "text_length": len(SECRET),
                        "tool_call_count": 0,
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "latency_ms": 23,
                    },
                ),
            ),
        )
        recorder.record(
            terminal_state,
            RunPhase.FAILED,
            failure_code="EXECUTOR_FINAL_UNCERTAIN",
        )
    assert running_final.plan.steps[-1].status is PlanStepStatus.IN_PROGRESS
    return ReconciliationFixture(
        state_dir=state_dir,
        lock=lock,
        plan_store=plan_store,
        final_store=final_store,
        task=TASK,
        observed_state=observed,
    )


def _compile(fixture: ReconciliationFixture, **changes: object):
    plan, final, envelope, record = fixture.snapshots()
    values: dict[str, object] = {
        "plan_snapshot": plan,
        "final_snapshot": final,
        "envelope": envelope,
        "run_record": record,
        "task": fixture.task,
        "expected_plan_sequence": plan.sequence,
        "expected_plan_digest": plan.plan.digest,
        "expected_final_sequence": final.sequence,
        "expected_final_digest": final.envelope_digest,
    }
    values.update(changes)
    return compile_final_response_reconciliation(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("failed_checkpoint", [False, True])
def test_preflight_reconstructs_exact_terminal_state_without_writes(
    tmp_path: Path, failed_checkpoint: bool
) -> None:
    fixture = _fixture(tmp_path, failed_checkpoint=failed_checkpoint)
    paths = (
        task_plan_path(fixture.state_dir, "run_1"),
        final_response_path(fixture.state_dir, "run_1"),
        continuation_path(fixture.state_dir, "run_1"),
        RunRecorder(fixture.state_dir, "run_1").checkpoint_path,
        RunRecorder(fixture.state_dir, "run_1").trace_path,
    )
    before = tuple(path.read_bytes() for path in paths)
    try:
        prepared = _compile(fixture)
    finally:
        fixture.lock.release()

    assert tuple(path.read_bytes() for path in paths) == before
    assert prepared.plan_already_completed is False
    assert prepared.terminal_event_already_recorded is failed_checkpoint
    assert prepared.result.text == SECRET
    assert SECRET not in repr(prepared)
    assert prepared.provider_latency_ms == 23
    assert prepared.terminal_state.budgets.model_turns_used == 1
    assert prepared.terminal_state.budgets.input_tokens_used == 11
    terminal = prepared.terminal_state.event_log[-1]
    assert terminal.kind is LedgerEventKind.MODEL_TURN
    assert terminal.payload["text_length"] == len(SECRET)
    assert terminal.payload["tool_call_count"] == 0


def test_preflight_accepts_plan_cas_already_completed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    current = fixture.plan_store.read("run_1")
    fixture.plan_store.transition(
        "run_1",
        "step_2",
        PlanStepStatus.COMPLETED,
        expected_sequence=current.sequence,
        expected_plan_digest=current.plan.digest,
    )
    try:
        prepared = _compile(fixture)
    finally:
        fixture.lock.release()

    assert prepared.plan_already_completed is True


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("request", "REQUEST_MISMATCH"),
        ("continuation", "EVIDENCE_INVALID"),
        ("intent", "OUTCOME_UNCERTAIN"),
        ("trace", "TRACE_MISMATCH"),
        ("task", "EVIDENCE_INVALID"),
    ],
)
def test_preflight_rejects_drift_without_mutation(
    tmp_path: Path, mutation: str, code: str
) -> None:
    fixture = _fixture(tmp_path)
    plan, final, envelope, record = fixture.snapshots()
    changes: dict[str, object] = {}
    if mutation == "request":
        changes["final_snapshot"] = replace(final, request_digest="0" * 64)
    elif mutation == "continuation":
        changes["final_snapshot"] = replace(final, continuation_digest="0" * 64)
    elif mutation == "intent":
        changes["final_snapshot"] = replace(
            final,
            stage=FinalResponseStage.DISPATCH_INTENT,
            sequence=1,
            result=None,
            provider_latency_ms=None,
        )
        changes["expected_final_sequence"] = 1
    elif mutation == "trace":
        forged_record = dict(record)
        events = list(record["events"])
        events[1] = {**events[1], "tool": "find"}
        forged_record["events"] = events
        changes["run_record"] = forged_record
    else:
        changes["task"] = "different task"
    paths = (
        task_plan_path(fixture.state_dir, "run_1"),
        final_response_path(fixture.state_dir, "run_1"),
        continuation_path(fixture.state_dir, "run_1"),
    )
    before = tuple(path.read_bytes() for path in paths)
    try:
        with pytest.raises(ExecutorFinalReconciliationError, match=code):
            _compile(fixture, **changes)
        assert tuple(path.read_bytes() for path in paths) == before
    finally:
        fixture.lock.release()


def test_preflight_has_no_external_or_recovery_executor_port() -> None:
    source = inspect.getsource(reconciliation_module)

    assert "create_final_response(" not in source
    assert ".call_tool(" not in source
    assert "from .recovery" not in source
    assert "TaskPlanStore" not in source
    assert "FinalResponseStore" not in source


@pytest.mark.parametrize("failed_checkpoint", [False, True])
def test_apply_commits_exact_plan_terminal_trace_and_cleanup(
    tmp_path: Path, failed_checkpoint: bool
) -> None:
    fixture = _fixture(tmp_path, failed_checkpoint=failed_checkpoint)
    plan, final, _, _ = fixture.snapshots()
    try:
        prepared = apply_completed_final_response_reconciliation(
            fixture.plan_store,
            fixture.final_store,
            run_id="run_1",
            task=fixture.task,
            expected_plan_sequence=plan.sequence,
            expected_plan_digest=plan.plan.digest,
            expected_final_sequence=final.sequence,
            expected_final_digest=final.envelope_digest,
        )
        repaired_plan = fixture.plan_store.read("run_1")
        retained_final = fixture.final_store.read("run_1")
        record = read_run_record(fixture.state_dir, "run_1")
    finally:
        fixture.lock.release()

    assert repaired_plan.plan.steps[-1].status is PlanStepStatus.COMPLETED
    assert repaired_plan.sequence == plan.sequence + 1
    assert retained_final == final
    assert record["state"]["phase"] == "SUCCESS"
    assert record["state"]["final_text_length"] == len(SECRET)
    assert record["state"]["event_count"] == 5
    assert record["events"][-1]["kind"] == "model_turn"
    assert len(record["events"]) == 5
    assert not continuation_path(fixture.state_dir, "run_1").exists()
    assert final_response_path(fixture.state_dir, "run_1").exists()
    assert prepared.result.text == SECRET
    assert SECRET not in str(record)


def test_apply_retries_cleanup_without_duplicate_terminal_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _fixture(tmp_path)
    plan, final, _, _ = fixture.snapshots()
    original_delete = reconciliation_apply_module.delete_continuation

    def fail_cleanup(*_args: object, **_kwargs: object) -> None:
        raise reconciliation_apply_module.ContinuationError(
            "CONTINUATION_DELETE_FAILED"
        )

    monkeypatch.setattr(reconciliation_apply_module, "delete_continuation", fail_cleanup)
    try:
        with pytest.raises(
            ExecutorFinalReconciliationError,
            match="^EXECUTOR_FINAL_RECONCILIATION_CLEANUP_FAILED$",
        ):
            apply_completed_final_response_reconciliation(
                fixture.plan_store,
                fixture.final_store,
                run_id="run_1",
                task=fixture.task,
                expected_plan_sequence=plan.sequence,
                expected_plan_digest=plan.plan.digest,
                expected_final_sequence=final.sequence,
                expected_final_digest=final.envelope_digest,
            )
        after_first = fixture.plan_store.read("run_1")
        first_record = read_run_record(fixture.state_dir, "run_1")
        monkeypatch.setattr(
            reconciliation_apply_module, "delete_continuation", original_delete
        )
        apply_completed_final_response_reconciliation(
            fixture.plan_store,
            fixture.final_store,
            run_id="run_1",
            task=fixture.task,
            expected_plan_sequence=after_first.sequence,
            expected_plan_digest=after_first.plan.digest,
            expected_final_sequence=final.sequence,
            expected_final_digest=final.envelope_digest,
        )
        second_record = read_run_record(fixture.state_dir, "run_1")
    finally:
        fixture.lock.release()

    assert first_record["state"]["phase"] == "SUCCESS"
    assert len(first_record["events"]) == 5
    assert second_record["state"]["phase"] == "SUCCESS"
    assert len(second_record["events"]) == 5
    assert not continuation_path(fixture.state_dir, "run_1").exists()


def test_apply_has_local_store_and_trace_paths_only() -> None:
    source = inspect.getsource(reconciliation_apply_module)

    assert "create_final_response(" not in source
    assert ".call_tool(" not in source
    assert "_execute_requested_call_boundary(" not in source
    assert "ApprovalPort" not in source
