from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
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
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.plan_store import PlanStoreError, TaskPlanStore
from computer_use_agent.planning import (
    PlanStepStatus,
    TaskPlanStatus,
    compile_task_plan,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.types import (
    DispatchCertainty,
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
