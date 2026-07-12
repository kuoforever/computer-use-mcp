from __future__ import annotations

import asyncio
import json
from collections import deque
from pathlib import Path

import pytest

from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerError, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEventKind,
    MemoryContextItem,
    ModelTurn,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_model_turns: int = 4,
    max_tool_calls: int = 4,
    max_context_events: int = 128,
) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "runtime-test",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            max_model_turns=max_model_turns,
            max_tool_calls=max_tool_calls,
            max_context_events=max_context_events,
        ),
    )


def _runner(
    config: AgentConfig,
    provider: FakeModelProvider,
    desktop: FakeDesktopMCP,
) -> AgentRunner:
    return AgentRunner(
        config,
        RunnerPorts(provider=provider, desktop=desktop, approvals=FakeApprovalPort()),
    )


def test_read_only_observe_then_answer_is_bounded_and_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity(run_id="run_1", turn_id="turn_1", call_id="call_1")
    call = ToolCall(identity=identity, name="list_windows", arguments={})
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_1",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                ),
                ModelTurn(
                    run_id="run_1",
                    turn_id="turn_2",
                    provider_response_id="response_2",
                    text="Notepad is open.",
                ),
            ]
        )
    )
    result = ToolResult(
        identity=identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad",
    )
    desktop = FakeDesktopMCP(results=deque([result]))

    config = _config(tmp_path, monkeypatch)
    outcome = asyncio.run(
        _runner(config, provider, desktop).run(
            "Inspect open windows", run_id="run_1"
        )
    )

    assert outcome.text == "Notepad is open."
    assert outcome.state.budgets.model_turns_used == 2
    assert outcome.state.budgets.tool_calls_used == 1
    assert outcome.state.observation_epoch == 1
    assert outcome.state.verified_observation_epoch == 1
    assert [event.kind for event in outcome.state.event_log] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
        LedgerEventKind.MODEL_TURN,
    ]
    assert desktop.tool_calls == [
        ToolCall(
            identity=call.identity,
            name=call.name,
            arguments=call.arguments,
            status=ToolCallStatus.AUTHORIZED,
        )
    ]
    assert desktop.close_calls == 1
    assert len(provider.calls) == 2
    assert provider.calls[1]["ledger"][-1].kind is LedgerEventKind.OBSERVATION
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "SUCCESS"
    assert record["state"]["final_text_length"] == len(outcome.text)
    assert record["state"]["resume_allowed"] is False
    assert record["state"]["metrics"]["model_calls"] == 2
    assert record["state"]["metrics"]["tool_calls"] == 1
    assert record["state"]["metrics"]["tool_failures"] == 0
    assert record["state"]["metrics"]["provider_latency_ms"] >= 0
    assert record["state"]["metrics"]["tool_latency_ms"] >= 0
    assert record["state"]["metrics"]["run_duration_ms"] >= 0
    assert len(record["events"]) == len(outcome.state.event_log)
    lock_path = _config(tmp_path, monkeypatch).application_state_dir / "active-run.lock"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == {"released": True}


def test_read_only_action_is_recorded_as_denied_and_never_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = ToolCall(
        identity=CallIdentity(run_id="run_2", turn_id="turn_1", call_id="call_1"),
        name="click",
        arguments={"ref": "ref_1"},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_2",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                )
            ]
        )
    )
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunnerError, match="POLICY_DENIED"):
        asyncio.run(
            _runner(config, provider, desktop).run(
                "Click something", run_id="run_2"
            )
        )

    assert desktop.tool_calls == []
    assert desktop.close_calls == 1
    record = read_run_record(config.state_dir, "run_2")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "POLICY_DENIED"
    assert record["state"]["metrics"]["model_calls"] == 1
    assert record["state"]["metrics"]["tool_failures"] == 1


def test_model_turn_budget_stops_before_an_extra_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity(run_id="run_3", turn_id="turn_1", call_id="call_1")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_3",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(
                        ToolCall(identity=identity, name="list_windows", arguments={}),
                    ),
                )
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=identity,
                    tool_name="list_windows",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    sanitized_text="none",
                )
            ]
        )
    )

    with pytest.raises(RunFailure, match="MODEL_TURN_BUDGET_EXHAUSTED"):
        asyncio.run(
            _runner(
                _config(tmp_path, monkeypatch, max_model_turns=1), provider, desktop
            ).run("Inspect", run_id="run_3")
        )

    assert len(provider.calls) == 1
    assert desktop.close_calls == 1


def test_provider_identity_mismatch_fails_before_desktop_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="wrong_run",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="done",
                )
            ]
        )
    )
    desktop = FakeDesktopMCP()

    with pytest.raises(RunnerError, match="PROVIDER_TURN_IDENTITY_MISMATCH"):
        asyncio.run(
            _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
                "Inspect", run_id="run_4"
            )
        )

    assert desktop.tool_calls == []
    assert desktop.close_calls == 1


def test_success_is_not_checkpointed_when_desktop_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CloseFailingDesktop(FakeDesktopMCP):
        async def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("raw-close-error")

    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_close_failure",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="would have succeeded",
                )
            ]
        )
    )
    desktop = CloseFailingDesktop()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="raw-close-error"):
        asyncio.run(
            _runner(config, provider, desktop).run(
                "Inspect", run_id="run_close_failure"
            )
        )

    record = read_run_record(config.state_dir, "run_close_failure")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "RUN_FAILED"
    assert "final_text_length" not in record["state"]


def test_runner_reduces_only_provider_view_and_keeps_canonical_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_identity = CallIdentity("run_context", "turn_1", "call_1")
    second_identity = CallIdentity("run_context", "turn_2", "call_2")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "run_context",
                    "turn_1",
                    "response_1",
                    "",
                    (ToolCall(first_identity, "list_windows", {}),),
                ),
                ModelTurn(
                    "run_context",
                    "turn_2",
                    "response_2",
                    "",
                    (ToolCall(second_identity, "find", {"query": "Notepad"}),),
                ),
                ModelTurn("run_context", "turn_3", "response_3", "done"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    first_identity,
                    "list_windows",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="windows",
                ),
                ToolResult(
                    second_identity,
                    "find",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="notepad",
                ),
            ]
        )
    )
    config = _config(tmp_path, monkeypatch, max_context_events=6)

    outcome = asyncio.run(
        _runner(config, provider, desktop).run("Inspect", run_id="run_context")
    )

    provider_ledger = provider.calls[2]["ledger"]
    assert [event.kind for event in provider_ledger] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.RECOVERY,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
    ]
    assert provider_ledger[1].payload["status"] == "context_truncated"
    assert len(outcome.state.event_log) == 10
    assert all(event.kind is not LedgerEventKind.RECOVERY for event in outcome.state.event_log)


def test_explicit_memory_reaches_provider_but_not_ledger_or_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "MEMORY_CONTEXT_PRIVATE_VALUE"
    provider = FakeModelProvider(
        turns=deque([ModelTurn("run_memory", "turn_1", "response_1", "done")])
    )
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)
    memory = MemoryContextItem("preference", marker, "user_confirmed", "global")

    outcome = asyncio.run(
        _runner(config, provider, desktop).run(
            "Inspect", run_id="run_memory", memories=(memory,)
        )
    )

    assert provider.calls[0]["memories"] == (memory,)
    assert marker not in repr(outcome.state.event_log)
    assert marker not in json.dumps(read_run_record(config.state_dir, "run_memory"))


def test_runner_rejects_oversized_memory_context_before_external_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)
    memory = MemoryContextItem("preference", "concise", "user_confirmed", "global")

    with pytest.raises(RunnerError, match="MEMORY_CONTEXT_LIMIT_EXCEEDED"):
        asyncio.run(
            _runner(config, provider, desktop).run(
                "Inspect", run_id="run_memory_limit", memories=(memory,) * 9
            )
        )

    assert provider.calls == []
    assert desktop.discovery_calls == 0
    assert not config.state_dir.exists()
