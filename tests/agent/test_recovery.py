from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import replace
from pathlib import Path

import pytest

from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import RuntimeContinuationRecorder, read_continuation
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.recovery import (
    LockedRecoveryPersistence,
    RecoveryExecutionError,
    RecoveryPlanError,
    execute_read_only_recovery_step,
    plan_read_only_recovery,
)
from computer_use_agent.reconstruction import ReconstructionAction
from computer_use_agent.run_lock import RunLock
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.trace import RunPhase, RunRecorder, read_run_checkpoint
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ModelTurn,
    RunBudget,
    RunState,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


def _config(tmp_path: Path, monkeypatch: object) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))  # type: ignore[attr-defined]
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "recovery-test",
        policy_version="policy-v1",
        provider=ProviderConfig("openai", "model-v1"),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=4),
        continuation=ContinuationConfig(enabled=True),
    )


def _state(run_id: str = "run_1") -> RunState:
    return RunState(
        run_id,
        "Inspect windows",
        "policy-v1",
        0,
        RunBudget(4, 4, 8, model_turns_used=1),
    )


def _recorder(
    config: AgentConfig,
    state: RunState,
    *,
    provider_name: str = "openai",
) -> RuntimeContinuationRecorder:
    return RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=state,
        provider_name=provider_name,
        provider_model="model-v1",
        registry_digest=reviewed_registry_digest(),
        ttl_seconds=900,
        mcp_generation=1,
    )


def _checkpoint(state: RunState, sequence: int) -> dict[str, object]:
    return {
        "run_id": state.run_id,
        "policy_version": state.policy_version,
        "task_length": len(state.task),
        "checkpoint_sequence": sequence,
    }


def test_completed_provider_reconstructs_exactly_one_pending_observation(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    turn = ModelTurn("run_1", "turn_1", "response_1", "", (call,))
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        turn,
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    envelope = read_continuation(config.state_dir, "run_1")

    plan = plan_read_only_recovery(
        _checkpoint(state, 3), envelope, config, task=state.task
    )

    assert plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION
    assert plan.call == call
    assert plan.result is None
    assert plan.decision.automatic_resume is False


def test_completed_observation_reconstructs_result_without_mcp_replay(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    turn = ModelTurn("run_1", "turn_1", "response_1", "", (call,))
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        turn,
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    tool_state = RunState(
        state.run_id,
        state.task,
        state.policy_version,
        1,
        RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
        verified_observation_epoch=1,
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder.prepare_tool(
        tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4
    )
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    envelope = read_continuation(config.state_dir, "run_1")

    plan = plan_read_only_recovery(
        _checkpoint(tool_state, 6), envelope, config, task=tool_state.task
    )

    assert plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER
    assert plan.result == result
    assert plan.call is None


def test_attach_drift_never_returns_external_work(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 2),
        read_continuation(config.state_dir, "run_1"),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.FAIL_CLOSED
    assert plan.call is None
    assert plan.result is None


def test_attach_rejects_provider_state_that_does_not_correlate_to_turn(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "different_response"},
        checkpoint_sequence=3,
    )

    with pytest.raises(
        RecoveryPlanError, match="CONTINUATION_PROVIDER_STATE_INVALID"
    ):
        plan_read_only_recovery(
            _checkpoint(state, 3),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
        )


def test_claude_attach_correlates_exact_tool_use_history(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig("anthropic", "model-v1"),
    )
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state, provider_name="anthropic")
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "messages": [
                {"role": "user", "content": state.task},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "list_windows",
                            "input": {},
                        }
                    ],
                },
            ]
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, "run_1"),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION
    assert plan.call == call


def test_budget_counters_must_equal_a_fresh_ledger_fold(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = replace(
        _state(),
        budgets=RunBudget(4, 4, 8, model_turns_used=2),
    )
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, "run_1"),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert plan.call is None
    assert plan.result is None


def test_executor_commits_before_exactly_one_observation_dispatch(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    expected = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    desktop = FakeDesktopMCP(results=deque([expected]))
    commits: list[tuple[int, str, ReconstructionAction]] = []

    def commit(sequence: int, operation_id: str, action: ReconstructionAction) -> None:
        assert desktop.tool_calls == []
        commits.append((sequence, operation_id, action))

    step = asyncio.run(
        execute_read_only_recovery_step(
            _checkpoint(state, 3),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
            provider=FakeModelProvider(),
            desktop=desktop,
            commit_intent=commit,
        )
    )

    assert commits == [
        (3, "run_1:turn_1:call_1", ReconstructionAction.DISPATCH_OBSERVATION)
    ]
    assert len(desktop.tool_calls) == 1
    assert desktop.tool_calls[0].status.value == "authorized"
    assert step.tool_result == expected


def test_executor_restores_then_commits_one_new_provider_continuation(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder.prepare_tool(
        tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4
    )
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    provider = FakeModelProvider(
        turns=deque([ModelTurn("run_1", "turn_2", "response_2", "done")])
    )
    commits: list[tuple[int, str, ReconstructionAction]] = []

    def commit(sequence: int, operation_id: str, action: ReconstructionAction) -> None:
        assert provider.calls == []
        assert provider.continuation_state["run_1"] == {"response_id": "response_1"}
        commits.append((sequence, operation_id, action))

    step = asyncio.run(
        execute_read_only_recovery_step(
            _checkpoint(tool_state, 6),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
            provider=provider,
            desktop=FakeDesktopMCP(),
            commit_intent=commit,
        )
    )

    assert commits == [
        (6, "run_1:turn_2:provider", ReconstructionAction.CONTINUE_PROVIDER)
    ]
    assert len(provider.calls) == 1
    assert provider.calls[0]["task"] == state.task
    ledger = provider.calls[0]["ledger"]
    assert isinstance(ledger, tuple) and ledger[0].tool_result == result
    assert step.model_turn is not None
    assert step.model_turn.provider_response_id == "response_2"


def test_executor_stale_attach_has_zero_commits_and_external_calls(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    with pytest.raises(RecoveryExecutionError, match="RECOVERY_PLAN_NOT_EXECUTABLE"):
        asyncio.run(
            execute_read_only_recovery_step(
                _checkpoint(state, 2),
                read_continuation(config.state_dir, "run_1"),
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert commits == []
    assert provider.calls == []
    assert desktop.tool_calls == []


def test_locked_recovery_persists_observation_intent_and_completion_atomically(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    desktop = FakeDesktopMCP(results=deque([result]))
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        step = asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=None,
                desktop=desktop,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    current = read_run_checkpoint(config.state_dir, state.run_id)
    assert step.tool_result == result
    assert persisted.payload["checkpoint_sequence"] == 5
    assert current["checkpoint_sequence"] == 5
    assert persisted.payload["boundary"] == {
        "operation_kind": "tool",
        "stage": "completed",
        "operation_id": "run_1:turn_1:call_1",
        "effect": "observation",
        "dispatch": "dispatched",
        "next_step": "provider_continue",
    }
    assert persisted.payload["budget"]["tool_calls_used"] == 1
    assert persisted.payload["observation"]["verified_epoch"] == 1


def test_locked_recovery_leaves_durable_unknown_intent_when_external_call_fails(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        with pytest.raises(RuntimeError, match="no fake tool result"):
            asyncio.run(
                execute_read_only_recovery_step(
                    checkpoint,
                    envelope,
                    config,
                    task=state.task,
                    provider=None,
                    desktop=FakeDesktopMCP(),
                    commit_intent=persistence.commit_intent,
                    commit_completion=persistence.commit_completion,
                )
            )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    assert persisted.payload["checkpoint_sequence"] == 4
    assert persisted.payload["boundary"]["stage"] == "dispatch_intent"
    assert persisted.payload["boundary"]["dispatch"] == "unknown"

    repeated_desktop = FakeDesktopMCP(results=deque([ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
    )]))
    lock.acquire()
    try:
        repeated = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        with pytest.raises(RecoveryExecutionError, match="RECOVERY_SEQUENCE_MISMATCH"):
            asyncio.run(
                execute_read_only_recovery_step(
                    checkpoint,
                    envelope,
                    config,
                    task=state.task,
                    provider=None,
                    desktop=repeated_desktop,
                    commit_intent=repeated.commit_intent,
                    commit_completion=repeated.commit_completion,
                )
            )
    finally:
        lock.release()
    assert repeated_desktop.tool_calls == []


def test_locked_recovery_persists_provider_intent_and_completion(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={"response_id": "response_1"},
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder.prepare_tool(
        tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4
    )
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(tool_state)
    safe.record(tool_state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(tool_state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    for _ in range(3):
        safe.record(tool_state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    provider = FakeModelProvider(
        turns=deque([ModelTurn("run_1", "turn_2", "response_2", "done")])
    )
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        step = asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=None,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    assert step.model_turn is not None and step.model_turn.text == "done"
    assert persisted.payload["checkpoint_sequence"] == 8
    assert persisted.payload["provider_state"] == {"response_id": "response_2"}
    assert persisted.payload["budget"]["model_turns_used"] == 2
    assert persisted.payload["boundary"] == {
        "operation_kind": "provider",
        "stage": "completed",
        "operation_id": "run_1:turn_2:provider",
        "effect": None,
        "dispatch": "dispatched",
        "next_step": "stop",
    }
