from __future__ import annotations

import asyncio
import copy
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from computer_use_agent import executor_reconciliation as reconciliation_module
from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import (
    ContinuationEnvelope,
    RuntimeContinuationRecorder,
    continuation_path,
    read_continuation,
)
from computer_use_agent.executor_reconciliation import (
    ExecutorReconciliationError,
    compile_observation_reconciliation,
    reconcile_completed_observation,
)
from computer_use_agent.executor_runtime import (
    ExecutorRuntimeError,
    open_runtime_executor_session,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.plan_store import PlanStoreError, TaskPlanStore
from computer_use_agent.planning import PlanStepStatus, compile_task_plan
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


TASK = "Inspect the current UI"


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "executor-reconciliation",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=4),
        continuation=ContinuationConfig(enabled=True),
    )


def _plan():
    return compile_task_plan(
        '{"version":1,"steps":['
        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
        '{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=("ui_snapshot",),
    )


@dataclass
class ReconciliationDesktop(FakeDesktopMCP):
    result_status: ToolResultStatus = ToolResultStatus.SUCCESS
    result_dispatch: DispatchCertainty = DispatchCertainty.DISPATCHED
    on_call: Callable[[ToolCall], None] | None = None

    async def call_tool(self, call: ToolCall) -> ToolResult:
        self.tool_calls.append(call)
        if self.on_call is not None:
            self.on_call(call)
        return ToolResult(
            identity=call.identity,
            tool_name=call.name,
            status=self.result_status,
            dispatch=self.result_dispatch,
            sanitized_text="observed" if self.result_status is ToolResultStatus.SUCCESS else "",
            code=(
                "MCP_TRANSPORT_ERROR"
                if self.result_status is ToolResultStatus.UNKNOWN_OUTCOME
                else "MCP_TIMEOUT_BEFORE_DISPATCH"
                if self.result_status is ToolResultStatus.TRANSPORT_ERROR
                else None
            ),
        )


def _runner(config: AgentConfig, desktop: ReconciliationDesktop) -> AgentRunner:
    return AgentRunner(
        config,
        RunnerPorts(
            provider=FakeModelProvider(),
            desktop=desktop,
            approvals=FakeApprovalPort(),
        ),
    )


def _locked_store(config: AgentConfig) -> tuple[TaskPlanStore, RunLock]:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    return TaskPlanStore(config.state_dir, lock), lock


def _leave_completed_wal_with_in_progress_plan(
    config: AgentConfig,
    desktop: ReconciliationDesktop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = asyncio.run(
        open_runtime_executor_session(_runner(config, desktop), task=TASK, plan=_plan())
    )
    original_transition = session.store.transition

    def fail_terminal_transition(*args: object, **kwargs: object):
        if args[2] in {PlanStepStatus.COMPLETED, PlanStepStatus.FAILED}:
            raise PlanStoreError("PLAN_STORE_WRITE_FAILED")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(session.store, "transition", fail_terminal_transition)
    with pytest.raises(
        ExecutorRuntimeError, match="^EXECUTOR_PLAN_COMMIT_FAILED$"
    ):
        asyncio.run(session.execute_next_observation())


def test_reconciliation_module_has_no_external_execution_path() -> None:
    source = inspect.getsource(reconciliation_module)

    assert "call_tool(" not in source
    assert "create_turn(" not in source
    assert "_execute_requested_call_boundary(" not in source
    assert "approval" not in source.lower()


@pytest.mark.parametrize(
    ("status", "dispatch", "target"),
    [
        (ToolResultStatus.SUCCESS, DispatchCertainty.DISPATCHED, PlanStepStatus.COMPLETED),
        (
            ToolResultStatus.TRANSPORT_ERROR,
            DispatchCertainty.NOT_DISPATCHED,
            PlanStepStatus.FAILED,
        ),
    ],
)
def test_completed_wal_repairs_only_the_matching_local_plan_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: ToolResultStatus,
    dispatch: DispatchCertainty,
    target: PlanStepStatus,
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = ReconciliationDesktop(result_status=status, result_dispatch=dispatch)
    _leave_completed_wal_with_in_progress_plan(config, desktop, monkeypatch)
    calls_before = tuple(desktop.tool_calls)
    envelope = read_continuation(config.state_dir, "run_1")
    store, lock = _locked_store(config)
    try:
        before = store.read("run_1")
        repaired = reconcile_completed_observation(
            store,
            envelope,
            task=TASK,
            expected_sequence=before.sequence,
            expected_plan_digest=before.plan.digest,
        )
    finally:
        lock.release()

    assert repaired.sequence == before.sequence + 1
    assert repaired.plan.steps[0].status is target
    assert tuple(desktop.tool_calls) == calls_before
    assert len(calls_before) == 1
    assert continuation_path(config.state_dir, "run_1").exists()


def test_unknown_outcome_is_never_reconciled_or_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = ReconciliationDesktop(
        result_status=ToolResultStatus.UNKNOWN_OUTCOME,
        result_dispatch=DispatchCertainty.UNKNOWN,
    )
    session = asyncio.run(
        open_runtime_executor_session(_runner(config, desktop), task=TASK, plan=_plan())
    )
    with pytest.raises(ExecutorRuntimeError, match="^UNKNOWN_OUTCOME$"):
        asyncio.run(session.execute_next_observation())
    envelope = read_continuation(config.state_dir, "run_1")
    store, lock = _locked_store(config)
    try:
        before = store.read("run_1")
        with pytest.raises(
            ExecutorReconciliationError,
            match="^EXECUTOR_RECONCILIATION_OUTCOME_UNCERTAIN$",
        ):
            compile_observation_reconciliation(
                before,
                envelope,
                task=TASK,
                expected_sequence=before.sequence,
                expected_plan_digest=before.plan.digest,
            )
        after = store.read("run_1")
    finally:
        lock.release()

    assert after == before
    assert len(desktop.tool_calls) == 1


def test_dispatch_intent_is_never_treated_as_completed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = ReconciliationDesktop()
    runner = _runner(config, desktop)
    prepared_run = runner.prepare(TASK, run_id="run_1")
    store = prepared_run.plan_store(config.state_dir)
    created = store.create(_plan())
    running = store.transition(
        "run_1",
        "step_1",
        PlanStepStatus.IN_PROGRESS,
        expected_sequence=created.sequence,
        expected_plan_digest=created.plan.digest,
    )
    call = ToolCall(
        identity=CallIdentity("run_1", "executor_turn_1", "call_1"),
        name="ui_snapshot",
        arguments={},
        status=ToolCallStatus.AUTHORIZED,
    )
    continuation = RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=prepared_run.state,
        provider_name=config.provider.name,
        provider_model=config.provider.model,
        registry_digest=reviewed_registry_digest(),
        ttl_seconds=config.continuation.ttl_seconds,
        mcp_generation=desktop.generation,
    )
    continuation.prepare_tool(
        prepared_run.state,
        call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=1,
    )
    continuation.dispatch_tool(prepared_run.state, checkpoint_sequence=2)
    prepared_run.close()
    envelope = read_continuation(config.state_dir, "run_1")
    assert envelope.payload["boundary"]["stage"] == "dispatch_intent"
    store, lock = _locked_store(config)
    try:
        before = store.read("run_1")
        with pytest.raises(
            ExecutorReconciliationError,
            match="^EXECUTOR_RECONCILIATION_OUTCOME_UNCERTAIN$",
        ):
            reconcile_completed_observation(
                store,
                envelope,
                task=TASK,
                expected_sequence=before.sequence,
                expected_plan_digest=before.plan.digest,
            )
        after = store.read("run_1")
    finally:
        lock.release()
    assert after == before
    assert running.plan.steps[0].status is PlanStepStatus.IN_PROGRESS
    assert desktop.tool_calls == []


@pytest.mark.parametrize("drift", ["task", "sequence", "digest"])
def test_identity_and_snapshot_drift_fail_without_plan_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drift: str
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = ReconciliationDesktop()
    _leave_completed_wal_with_in_progress_plan(config, desktop, monkeypatch)
    envelope = read_continuation(config.state_dir, "run_1")
    store, lock = _locked_store(config)
    try:
        before = store.read("run_1")
        with pytest.raises(ExecutorReconciliationError):
            reconcile_completed_observation(
                store,
                envelope,
                task="different task" if drift == "task" else TASK,
                expected_sequence=before.sequence + (1 if drift == "sequence" else 0),
                expected_plan_digest=("0" * 64 if drift == "digest" else before.plan.digest),
            )
        after = store.read("run_1")
    finally:
        lock.release()
    assert after == before
    assert len(desktop.tool_calls) == 1


def test_forged_continuation_object_is_revalidated_before_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = ReconciliationDesktop()
    _leave_completed_wal_with_in_progress_plan(config, desktop, monkeypatch)
    valid = read_continuation(config.state_dir, "run_1")
    forged_payload = copy.deepcopy(valid.payload)
    forged_payload["ledger"][-2]["data"]["tool_name"] = "list_windows"
    forged = ContinuationEnvelope(forged_payload)
    store, lock = _locked_store(config)
    try:
        before = store.read("run_1")
        with pytest.raises(
            ExecutorReconciliationError,
            match="^EXECUTOR_RECONCILIATION_EVIDENCE_INVALID$",
        ):
            reconcile_completed_observation(
                store,
                forged,
                task=TASK,
                expected_sequence=before.sequence,
                expected_plan_digest=before.plan.digest,
            )
        after = store.read("run_1")
    finally:
        lock.release()
    assert after == before
    assert len(desktop.tool_calls) == 1
