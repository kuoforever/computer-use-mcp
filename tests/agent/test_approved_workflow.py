from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    LedgerEventKind,
    ModelTurn,
    PolicyDecision,
    PolicyDecisionKind,
    RecoveryStatus,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


@dataclass
class DynamicApprovalPort:
    kind: PolicyDecisionKind = PolicyDecisionKind.ALLOW
    mismatch: bool = False
    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision(
            request_id="wrong" if self.mismatch else request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=self.kind,
            reason="test_operator",
        )


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "approved-test",
        policy_version="approved-v1",
        provider=ProviderConfig("openai", "fake"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=6,
            max_tool_calls=6,
            max_side_effects=2,
        ),
    )


def _turn(run_id: str, number: int, *calls: ToolCall, text: str = "") -> ModelTurn:
    return ModelTurn(
        run_id,
        f"turn_{number}",
        f"response_{number}",
        text,
        tuple(calls),
    )


def _call(run_id: str, turn: int, call_id: str, name: str, arguments: dict) -> ToolCall:
    return ToolCall(CallIdentity(run_id, f"turn_{turn}", call_id), name, arguments)


def _result(call: ToolCall, *, text: str = "") -> ToolResult:
    return ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text=text,
    )


def test_approved_action_requires_grounding_then_reobservation_before_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_approved"
    before = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "click", {"ref": "ref_1"})
    after = _call(run_id, 3, "call_3", "ui_snapshot", {})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, before),
                _turn(run_id, 2, action),
                _turn(run_id, 3, after),
                _turn(run_id, 4, text="verified"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(before, text='ref_1 | button "OK" | (1,1,10,10) | enabled'),
                _result(action),
                _result(after, text='ref_2 | text "Done" | (1,1,10,10) | enabled'),
            ]
        )
    )
    approvals = DynamicApprovalPort()
    config = _config(tmp_path, monkeypatch)
    runner = AgentRunner(config, RunnerPorts(provider, desktop, approvals))

    outcome = asyncio.run(runner.run("Click OK and verify", run_id=run_id))

    assert outcome.text == "verified"
    assert outcome.state.budgets.side_effects_used == 1
    assert outcome.state.recovery_status is RecoveryStatus.READY
    assert outcome.state.verified_observation_epoch == 2
    assert len(approvals.requests) == 1
    assert approvals.requests[0].tool_name == "click"
    assert [event.kind for event in outcome.state.event_log].count(
        LedgerEventKind.POLICY_DECISION
    ) == 1
    assert read_run_record(config.state_dir, run_id)["state"]["phase"] == "SUCCESS"


def test_action_without_grounding_is_denied_before_approval_or_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_no_grounding"
    action = _call(run_id, 1, "call_1", "click", {"ref": "ref_1"})
    provider = FakeModelProvider(turns=deque([_turn(run_id, 1, action)]))
    desktop = FakeDesktopMCP()
    approvals = DynamicApprovalPort()

    with pytest.raises(RunFailure, match="GROUNDING_REQUIRED"):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch), RunnerPorts(provider, desktop, approvals)
            ).run("Click", run_id=run_id)
        )

    assert approvals.requests == []
    assert desktop.tool_calls == []


@pytest.mark.parametrize(
    ("approval_kind", "mismatch", "expected"),
    [
        (PolicyDecisionKind.DENY, False, "APPROVAL_DENIED"),
        (PolicyDecisionKind.ALLOW, True, "APPROVAL_MISMATCH"),
    ],
)
def test_denied_or_mismatched_approval_never_dispatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    approval_kind: PolicyDecisionKind,
    mismatch: bool,
    expected: str,
) -> None:
    run_id = f"run_{expected.lower()}"
    observe = _call(run_id, 1, "call_1", "list_windows", {})
    action = _call(run_id, 2, "call_2", "activate_window", {"window_id": "42"})
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, observe), _turn(run_id, 2, action)])
    )
    desktop = FakeDesktopMCP(results=deque([_result(observe, text='* 42 | app.exe | "App"')]))
    approvals = DynamicApprovalPort(kind=approval_kind, mismatch=mismatch)

    with pytest.raises(RunFailure, match=expected):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch), RunnerPorts(provider, desktop, approvals)
            ).run("Activate", run_id=run_id)
        )

    assert [call.name for call in desktop.tool_calls] == ["list_windows"]


def test_final_answer_immediately_after_action_requires_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_verify_required"
    observe = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "click", {"ref": "ref_1"})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, observe),
                _turn(run_id, 2, action),
                _turn(run_id, 3, text="claimed success"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(observe, text='ref_1 | button "OK" | (1,1,10,10) | enabled'),
                _result(action),
            ]
        )
    )

    with pytest.raises(RunFailure, match="VERIFICATION_REQUIRED"):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch),
                RunnerPorts(provider, desktop, DynamicApprovalPort()),
            ).run("Click", run_id=run_id)
        )


def test_type_remains_denied_without_requesting_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_type_denied"
    call = _call(run_id, 1, "call_1", "type", {"text": "typed-value"})
    provider = FakeModelProvider(turns=deque([_turn(run_id, 1, call)]))
    approvals = DynamicApprovalPort()
    desktop = FakeDesktopMCP()

    with pytest.raises(RunFailure, match="POLICY_DENIED"):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch), RunnerPorts(provider, desktop, approvals)
            ).run("Type", run_id=run_id)
        )

    assert approvals.requests == []
    assert desktop.tool_calls == []


def test_second_action_without_reobservation_is_not_approved_or_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_two_actions"
    observe = _call(run_id, 1, "call_1", "ui_snapshot", {})
    first = _call(run_id, 2, "call_2", "click", {"ref": "ref_1"})
    second = _call(run_id, 2, "call_3", "click", {"ref": "ref_1"})
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, observe), _turn(run_id, 2, first, second)])
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(observe, text='ref_1 | button "OK" | (1,1,10,10) | enabled'),
                _result(first),
            ]
        )
    )
    approvals = DynamicApprovalPort()

    with pytest.raises(RunFailure, match="REOBSERVATION_REQUIRED"):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch), RunnerPorts(provider, desktop, approvals)
            ).run("Click twice", run_id=run_id)
        )

    assert len(approvals.requests) == 1
    assert [call.identity.call_id for call in desktop.tool_calls] == ["call_1", "call_2"]


def test_unknown_action_outcome_stops_without_replay_and_marks_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_unknown_action"
    observe = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "click", {"ref": "ref_1"})
    unknown = ToolResult(
        action.identity,
        action.name,
        ToolResultStatus.UNKNOWN_OUTCOME,
        DispatchCertainty.UNKNOWN,
        code="MCP_TRANSPORT_ERROR",
    )
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, observe), _turn(run_id, 2, action)])
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(observe, text='ref_1 | button "OK" | (1,1,10,10) | enabled'),
                unknown,
            ]
        )
    )
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunFailure, match="UNKNOWN_OUTCOME"):
        asyncio.run(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, DynamicApprovalPort()),
            ).run("Click", run_id=run_id)
        )

    assert [call.identity.call_id for call in desktop.tool_calls] == ["call_1", "call_2"]
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "UNKNOWN_OUTCOME"
    assert record["state"]["recovery_action"] == "human_reobserve_then_start_new_run"
