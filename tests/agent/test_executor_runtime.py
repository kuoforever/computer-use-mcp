from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import continuation_path, read_continuation
from computer_use_agent.executor_runtime import (
    ExecutorRuntimeError,
    open_runtime_executor_session,
)
from computer_use_agent import executor_runtime as executor_runtime_module
from computer_use_agent.executor_final import FinalResponseRequest, FinalResponseResult
from computer_use_agent.executor_final_reconciliation import (
    compile_final_response_reconciliation,
)
from computer_use_agent.executor_final_store import (
    FinalResponseStage,
    FinalResponseStore,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.plan_store import PlanStoreError, TaskPlanStore
from computer_use_agent.planning import (
    PlanStepStatus,
    TaskPlanStatus,
    compile_task_plan,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import (
    DispatchCertainty,
    LedgerEventKind,
    ModelUsage,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


TASK = "Inspect the current UI"


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    continuation_enabled: bool = True,
) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "executor-runtime",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=4),
        continuation=ContinuationConfig(enabled=continuation_enabled),
    )


def _plan(*, tool: str = "ui_snapshot", arguments: str = "{}"):
    return compile_task_plan(
        '{"version":1,"steps":['
        f'{{"action":"tool","tool":"{tool}","arguments":{arguments}}},'
        '{"action":"final_response"}]}',
        plan_id="plan_1",
        run_id="run_1",
        task=TASK,
        allowed_tools=(tool,),
    )


@dataclass
class DynamicDesktop(FakeDesktopMCP):
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


@dataclass
class FakeFinalResponsePort:
    response: FinalResponseResult | BaseException
    on_call: Callable[[FinalResponseRequest], None] | None = None
    calls: list[FinalResponseRequest] = field(default_factory=list)

    async def create_final_response(
        self, request: FinalResponseRequest
    ) -> FinalResponseResult:
        self.calls.append(request)
        if self.on_call is not None:
            self.on_call(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def _runner(
    config: AgentConfig,
    desktop: FakeDesktopMCP,
) -> tuple[AgentRunner, FakeModelProvider, FakeApprovalPort]:
    provider = FakeModelProvider()
    approvals = FakeApprovalPort()
    return (
        AgentRunner(
            config,
            RunnerPorts(provider=provider, desktop=desktop, approvals=approvals),
        ),
        provider,
        approvals,
    )


def _read_plan_after_close(config: AgentConfig):
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        return TaskPlanStore(config.state_dir, lock).read("run_1")
    finally:
        lock.release()


def _read_final_after_close(config: AgentConfig):
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        return FinalResponseStore(config.state_dir, lock).read("run_1")
    finally:
        lock.release()


def test_runtime_has_no_direct_mcp_dispatch_path() -> None:
    source = inspect.getsource(executor_runtime_module)

    assert ".desktop.call_tool(" not in source
    assert source.count("._execute_requested_call_boundary(") == 1


def test_runtime_executes_observation_only_after_plan_and_wal_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, provider, approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))

    def inspect_dispatch(call: ToolCall) -> None:
        snapshot = session.store.read("run_1")
        assert snapshot.plan.steps[0].status is PlanStepStatus.IN_PROGRESS
        envelope = read_continuation(config.state_dir, "run_1")
        assert envelope.payload["boundary"]["stage"] == "dispatch_intent"
        assert call.status is ToolCallStatus.AUTHORIZED

    desktop.on_call = inspect_dispatch
    outcome = asyncio.run(session.execute_next_observation())

    snapshot = session.store.read("run_1")
    assert outcome.result.ok
    assert outcome.state.budgets.tool_calls_used == 1
    assert outcome.state.observation_epoch == 1
    assert snapshot.sequence == 2
    assert snapshot.plan.steps[0].status is PlanStepStatus.COMPLETED
    assert snapshot.plan.steps[1].status is PlanStepStatus.PENDING
    assert provider.calls == []
    assert approvals.requests == []
    assert len(desktop.tool_calls) == 1
    assert read_continuation(config.state_dir, "run_1").payload["boundary"][
        "stage"
    ] == "completed"

    asyncio.run(session.cancel())
    assert session.closed
    assert desktop.close_calls == 1
    assert not continuation_path(config.state_dir, "run_1").exists()
    final = _read_plan_after_close(config)
    assert final.plan.status is TaskPlanStatus.CANCELLED
    assert final.plan.steps[1].status is PlanStepStatus.CANCELLED


def test_runtime_unknown_outcome_is_preserved_and_never_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop(
        result_status=ToolResultStatus.UNKNOWN_OUTCOME,
        result_dispatch=DispatchCertainty.UNKNOWN,
    )
    runner, provider, approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))

    with pytest.raises(ExecutorRuntimeError, match="^UNKNOWN_OUTCOME$"):
        asyncio.run(session.execute_next_observation())

    assert session.closed
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1
    assert provider.calls == []
    assert approvals.requests == []
    assert continuation_path(config.state_dir, "run_1").exists()
    snapshot = _read_plan_after_close(config)
    assert snapshot.sequence == 1
    assert snapshot.plan.steps[0].status is PlanStepStatus.IN_PROGRESS


def test_runtime_known_tool_failure_is_committed_and_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop(
        result_status=ToolResultStatus.TRANSPORT_ERROR,
        result_dispatch=DispatchCertainty.NOT_DISPATCHED,
    )
    runner, provider, approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_TOOL_FAILED$"):
        asyncio.run(session.execute_next_observation())

    assert session.closed
    assert len(desktop.tool_calls) == 1
    assert provider.calls == []
    assert approvals.requests == []
    assert not continuation_path(config.state_dir, "run_1").exists()
    snapshot = _read_plan_after_close(config)
    assert snapshot.sequence == 2
    assert snapshot.plan.steps[0].status is PlanStepStatus.FAILED


def test_runtime_plan_commit_failure_preserves_completed_wal_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, _provider, _approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))
    original_transition = session.store.transition

    def fail_completed_transition(*args: object, **kwargs: object):
        if args[2] is PlanStepStatus.COMPLETED:
            raise PlanStoreError("PLAN_STORE_WRITE_FAILED")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(session.store, "transition", fail_completed_transition)
    with pytest.raises(
        ExecutorRuntimeError, match="^EXECUTOR_PLAN_COMMIT_FAILED$"
    ):
        asyncio.run(session.execute_next_observation())

    assert session.closed
    assert len(desktop.tool_calls) == 1
    assert continuation_path(config.state_dir, "run_1").exists()
    envelope = read_continuation(config.state_dir, "run_1")
    assert envelope.payload["boundary"]["stage"] == "completed"
    snapshot = _read_plan_after_close(config)
    assert snapshot.sequence == 1
    assert snapshot.plan.steps[0].status is PlanStepStatus.IN_PROGRESS


def test_runtime_rejects_side_effect_before_transition_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, _provider, approvals = _runner(config, desktop)
    plan = _plan(tool="click", arguments='{"ref":"ref_1"}')
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=plan))

    with pytest.raises(
        ExecutorRuntimeError, match="^EXECUTOR_SESSION_SIDE_EFFECT_UNSUPPORTED$"
    ):
        asyncio.run(session.execute_next_observation())

    snapshot = session.store.read("run_1")
    assert snapshot.sequence == 0
    assert snapshot.plan.steps[0].status is PlanStepStatus.PENDING
    assert desktop.tool_calls == []
    assert approvals.requests == []
    asyncio.run(session.cancel())


def test_runtime_requires_wal_before_starting_any_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch, continuation_enabled=False)
    desktop = DynamicDesktop()
    runner, provider, approvals = _runner(config, desktop)

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_RUNTIME_WAL_REQUIRED$"):
        asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))

    assert desktop.discovery_calls == 0
    assert desktop.tool_calls == []
    assert provider.calls == []
    assert approvals.requests == []


def test_runtime_final_response_orders_wal_budget_plan_trace_and_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, provider, approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))
    asyncio.run(session.execute_next_observation())
    final = FakeFinalResponsePort(
        FinalResponseResult(
            run_id="run_1",
            turn_id="executor_final_1",
            provider_response_id="resp_final_1",
            text="The UI is ready.",
            usage=ModelUsage(input_tokens=10, output_tokens=4),
        )
    )

    def inspect_dispatch(request: FinalResponseRequest) -> None:
        snapshot = session.store.read("run_1")
        assert snapshot.plan.steps[-1].status is PlanStepStatus.IN_PROGRESS
        wal = session.prepared_run.final_response_store(config.state_dir).read("run_1")
        assert wal.stage is FinalResponseStage.DISPATCH_INTENT
        assert wal.request_digest == request.request_digest

    original_consume = runner._consume_model_turn

    def inspect_budget_consumption(state, turn, *, latency_ms: int):
        wal = session.prepared_run.final_response_store(config.state_dir).read("run_1")
        assert wal.stage is FinalResponseStage.COMPLETED
        assert state.budgets.model_turns_used == 0
        assert session.store.read("run_1").plan.steps[-1].status is PlanStepStatus.IN_PROGRESS
        return original_consume(state, turn, latency_ms=latency_ms)

    original_record = session.recorder.record

    def inspect_terminal_trace(state, phase, **kwargs):
        if phase.value == "SUCCESS":
            assert state.budgets.model_turns_used == 1
            assert session.store.read("run_1").plan.steps[-1].status is PlanStepStatus.COMPLETED
        return original_record(state, phase, **kwargs)

    final.on_call = inspect_dispatch
    monkeypatch.setattr(runner, "_consume_model_turn", inspect_budget_consumption)
    monkeypatch.setattr(session.recorder, "record", inspect_terminal_trace)
    outcome = asyncio.run(session.execute_final_response(final))

    assert outcome.text == "The UI is ready."
    assert "The UI is ready." not in repr(outcome)
    assert outcome.state.budgets.model_turns_used == 1
    assert outcome.state.budgets.input_tokens_used == 10
    assert outcome.state.event_log[-1].kind is LedgerEventKind.MODEL_TURN
    assert outcome.state.event_log[-1].payload["tool_call_count"] == 0
    assert session.closed
    assert len(final.calls) == 1
    assert provider.calls == []
    assert approvals.requests == []
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1
    assert not continuation_path(config.state_dir, "run_1").exists()
    plan = _read_plan_after_close(config)
    assert plan.plan.status is TaskPlanStatus.COMPLETED
    assert plan.plan.steps[-1].status is PlanStepStatus.COMPLETED
    wal = _read_final_after_close(config)
    assert wal.stage is FinalResponseStage.COMPLETED
    assert wal.result is not None
    assert wal.result.text == "The UI is ready."
    checkpoint = read_run_record(config.state_dir, "run_1")["state"]
    assert checkpoint["phase"] == "SUCCESS"
    assert checkpoint["final_text_length"] == len("The UI is ready.")
    assert checkpoint["budgets"]["model_turns_used"] == 1


def test_runtime_final_provider_failure_preserves_intent_and_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, provider, approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))
    asyncio.run(session.execute_next_observation())
    final = FakeFinalResponsePort(RuntimeError("private provider failure"))

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_FINAL_UNCERTAIN$"):
        asyncio.run(session.execute_final_response(final))

    assert session.closed
    assert len(final.calls) == 1
    assert provider.calls == []
    assert approvals.requests == []
    assert continuation_path(config.state_dir, "run_1").exists()
    plan = _read_plan_after_close(config)
    assert plan.plan.steps[-1].status is PlanStepStatus.IN_PROGRESS
    wal = _read_final_after_close(config)
    assert wal.stage is FinalResponseStage.DISPATCH_INTENT
    assert wal.result is None
    checkpoint = read_run_record(config.state_dir, "run_1")["state"]
    assert checkpoint["phase"] == "FAILED"
    assert checkpoint["failure_code"] == "EXECUTOR_FINAL_UNCERTAIN"


@pytest.mark.parametrize(
    "response",
    [
        asyncio.CancelledError(),
        FinalResponseResult(
            run_id="different",
            turn_id="executor_final_1",
            provider_response_id="resp_wrong_run",
            text="uncorrelated",
            usage=ModelUsage(1, 1),
        ),
    ],
)
def test_runtime_final_cancellation_or_identity_drift_is_non_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: FinalResponseResult | BaseException,
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, _provider, _approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))
    asyncio.run(session.execute_next_observation())
    final = FakeFinalResponsePort(response)

    expected = asyncio.CancelledError if isinstance(response, asyncio.CancelledError) else ExecutorRuntimeError
    with pytest.raises(expected):
        asyncio.run(session.execute_final_response(final))

    assert session.closed
    assert len(final.calls) == 1
    assert _read_plan_after_close(config).plan.steps[-1].status is PlanStepStatus.IN_PROGRESS
    wal = _read_final_after_close(config)
    assert wal.stage is FinalResponseStage.DISPATCH_INTENT
    assert wal.result is None


def test_runtime_final_plan_commit_failure_preserves_completed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, _provider, _approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))
    asyncio.run(session.execute_next_observation())
    original_transition = session.store.transition

    def fail_final_completion(*args: object, **kwargs: object):
        if args[2] is PlanStepStatus.COMPLETED and args[1] == "step_2":
            raise PlanStoreError("PLAN_STORE_WRITE_FAILED")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(session.store, "transition", fail_final_completion)
    final = FakeFinalResponsePort(
        FinalResponseResult(
            run_id="run_1",
            turn_id="executor_final_1",
            provider_response_id="resp_final_1",
            text="Completed but not terminalized",
            usage=ModelUsage(3, 2),
        )
    )

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_FINAL_UNCERTAIN$"):
        asyncio.run(session.execute_final_response(final))

    assert session.closed
    assert len(final.calls) == 1
    assert continuation_path(config.state_dir, "run_1").exists()
    plan = _read_plan_after_close(config)
    assert plan.plan.steps[-1].status is PlanStepStatus.IN_PROGRESS
    wal = _read_final_after_close(config)
    assert wal.stage is FinalResponseStage.COMPLETED
    assert wal.result is not None
    assert wal.result.text == "Completed but not terminalized"
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        plan = TaskPlanStore(config.state_dir, lock).read("run_1")
        final_snapshot = FinalResponseStore(config.state_dir, lock).read("run_1")
        prepared = compile_final_response_reconciliation(
            plan,
            final_snapshot,
            read_continuation(config.state_dir, "run_1"),
            read_run_record(config.state_dir, "run_1"),
            task=TASK,
            expected_plan_sequence=plan.sequence,
            expected_plan_digest=plan.plan.digest,
            expected_final_sequence=final_snapshot.sequence,
            expected_final_digest=final_snapshot.envelope_digest,
        )
    finally:
        lock.release()
    assert prepared.terminal_event_already_recorded
    assert prepared.terminal_state.budgets.model_turns_used == 1


def test_runtime_final_preflight_before_observations_is_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = DynamicDesktop()
    runner, _provider, _approvals = _runner(config, desktop)
    session = asyncio.run(open_runtime_executor_session(runner, task=TASK, plan=_plan()))
    final = FakeFinalResponsePort(RuntimeError("must not be called"))

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_FINAL_PLAN_NOT_READY$"):
        asyncio.run(session.execute_final_response(final))

    assert not session.closed
    assert final.calls == []
    snapshot = session.store.read("run_1")
    assert snapshot.sequence == 0
    assert all(step.status is PlanStepStatus.PENDING for step in snapshot.plan.steps)
    asyncio.run(session.cancel())
