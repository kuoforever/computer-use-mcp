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
from computer_use_agent.runner import AgentRunner, RunnerBudgetError, RunnerError, RunnerPorts
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEventKind,
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

    outcome = asyncio.run(
        _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
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

    with pytest.raises(RunnerError, match="POLICY_DENIED"):
        asyncio.run(
            _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
                "Click something", run_id="run_2"
            )
        )

    assert desktop.tool_calls == []
    assert desktop.close_calls == 1


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

    with pytest.raises(RunnerBudgetError, match="MODEL_TURN_BUDGET_EXHAUSTED"):
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
