from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import pytest

from computer_use_agent import continuation as continuation_module
from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import continuation_path
from computer_use_agent.approvals import DecisionCardApprovalPort
from computer_use_agent.decision_cards import DecisionSelection
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunDeferred, RunFailure, RunnerPorts
from computer_use_agent.trace import classify_run_recovery, read_run_record
from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    LedgerEventKind,
    MCPCallCancelled,
    ModelTurn,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    RecoveryStatus,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


_PNG_10X10 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x0a\x00\x00\x00\x0a"
)


@dataclass
class DynamicApprovalPort:
    kind: PolicyDecisionKind = PolicyDecisionKind.ALLOW
    mismatch: bool = False
    on_request: Callable[[ApprovalRequest], None] | None = None
    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        if self.on_request is not None:
            self.on_request(request)
        return PolicyDecision(
            request_id="wrong" if self.mismatch else request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=self.kind,
            reason="test_operator",
        )


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    continuation_enabled: bool = False,
    max_model_turns: int = 6,
    max_tool_calls: int = 6,
    max_context_events: int = 128,
    max_input_tokens: int = 1_000_000,
) -> AgentConfig:
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
            max_model_turns=max_model_turns,
            max_tool_calls=max_tool_calls,
            max_side_effects=2,
            max_context_events=max_context_events,
            max_input_tokens=max_input_tokens,
        ),
        continuation=ContinuationConfig(enabled=continuation_enabled),
    )


def _turn(
    run_id: str,
    number: int,
    *calls: ToolCall,
    text: str = "",
    input_tokens: int | None = None,
) -> ModelTurn:
    return ModelTurn(
        run_id,
        f"turn_{number}",
        f"response_{number}",
        text,
        tuple(calls),
        ModelUsage(
            input_tokens=input_tokens,
            output_tokens=None if input_tokens is None else 1,
        ),
    )


def _call(run_id: str, turn: int, call_id: str, name: str, arguments: dict) -> ToolCall:
    return ToolCall(CallIdentity(run_id, f"turn_{turn}", call_id), name, arguments)


def _result(
    call: ToolCall,
    *,
    text: str = "",
    images: tuple[ImageContent, ...] = (),
) -> ToolResult:
    return ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text=text,
        images=images,
    )


def _verification_workflow(
    run_id: str,
) -> tuple[FakeModelProvider, FakeDesktopMCP, DynamicApprovalPort, ToolCall]:
    before = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "click", {"ref": "ref_1"})
    after = _call(run_id, 3, "call_3", "ui_snapshot", {})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, before, input_tokens=1),
                _turn(run_id, 2, action, input_tokens=1),
                _turn(run_id, 3, after, input_tokens=1),
                _turn(run_id, 4, text="verified", input_tokens=1),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(
                    before,
                    text='ref_1 | button "OK" | (1,1,10,10) | enabled',
                ),
                _result(action),
                _result(
                    after,
                    text='ref_2 | text "Done" | (1,1,10,10) | enabled',
                ),
            ]
        )
    )
    return provider, desktop, DynamicApprovalPort(), action


def _capture_continuations(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    payloads: list[dict[str, object]] = []
    original_write = continuation_module.write_continuation

    def capture(state_dir: Path, payload: object) -> object:
        assert isinstance(payload, dict)
        payloads.append(deepcopy(payload))
        return original_write(state_dir, payload)

    monkeypatch.setattr(continuation_module, "write_continuation", capture)
    return payloads


def _assert_post_approval_authority_failure(
    failure: RunFailure,
    *,
    expected_code: str,
    config: AgentConfig,
    task: str,
    observe: ToolCall,
    action: ToolCall,
    provider: FakeModelProvider,
    desktop: FakeDesktopMCP,
    approvals: DynamicApprovalPort,
    payloads: list[dict[str, object]] | None,
) -> None:
    state = failure.state
    assert [event.kind for event in state.event_log] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.POLICY_DECISION,
        LedgerEventKind.TOOL_RESULT,
    ]
    decision = state.event_log[-2].policy_decision
    assert decision is not None
    assert decision.identity == action.identity
    assert decision.kind is PolicyDecisionKind.ALLOW
    rejected = state.event_log[-1].tool_result
    assert rejected is not None
    assert rejected.identity == action.identity
    assert rejected.status is ToolResultStatus.REJECTED
    assert rejected.dispatch is DispatchCertainty.NOT_DISPATCHED
    assert rejected.code == "POLICY_DENIED"
    assert state.budgets.model_turns_used == 2
    assert state.budgets.input_tokens_used == 2
    assert state.budgets.tool_calls_used == 2
    assert state.budgets.side_effects_used == 0
    assert state.observation_epoch == state.verified_observation_epoch == 1
    assert state.recovery_status is RecoveryStatus.READY

    assert len(provider.calls) == 2
    assert len(desktop.tool_calls) == 1
    assert desktop.tool_calls[0].identity == observe.identity
    assert desktop.tool_calls[0].name == observe.name
    assert desktop.tool_calls[0].arguments == observe.arguments
    assert desktop.tool_calls[0].status is ToolCallStatus.AUTHORIZED
    assert len(approvals.requests) == 1
    assert approvals.requests[0].identity == action.identity
    assert desktop.close_calls == 1

    provider_completion: list[dict[str, object]] = []
    if payloads is not None:
        action_operation_id = (
            f"{action.identity.run_id}:{action.identity.turn_id}:"
            f"{action.identity.call_id}"
        )
        action_boundaries = [
            boundary
            for payload in payloads
            if isinstance((boundary := payload.get("boundary")), dict)
            and boundary.get("operation_kind") == "tool"
            and boundary.get("operation_id") == action_operation_id
        ]
        assert action_boundaries == []
        provider_completion = [
            payload
            for payload in payloads
            if isinstance(payload.get("boundary"), dict)
            and payload["boundary"]
            == {
                "operation_kind": "provider",
                "stage": "completed",
                "operation_id": (
                    f"{action.identity.run_id}:{action.identity.turn_id}:provider"
                ),
                "effect": "side_effect",
                "dispatch": "dispatched",
                "next_step": "stop",
            }
        ]
        assert len(provider_completion) == 1

    record = read_run_record(config.state_dir, action.identity.run_id)
    checkpoint = record["state"]
    assert checkpoint["phase"] == "FAILED"
    assert checkpoint["failure_code"] == expected_code
    assert checkpoint["event_count"] == 9
    assert checkpoint["observation_epoch"] == 1
    assert checkpoint["verified_observation_epoch"] == 1
    assert checkpoint["recovery_status"] == "ready"
    assert checkpoint["resume_allowed"] is False
    assert checkpoint["recovery_action"] == "inspect_trace_then_start_new_run"
    assert checkpoint["budgets"] == {
        "max_input_tokens": 1_000_000,
        "max_model_turns": 6,
        "max_side_effects": 2,
        "max_tool_calls": 6,
        "input_tokens_used": 2,
        "model_turns_used": 2,
        "side_effects_used": 0,
        "tool_calls_used": 2,
    }
    if provider_completion:
        assert checkpoint["checkpoint_sequence"] == provider_completion[0][
            "checkpoint_sequence"
        ]
    assert record["events"][-2]["kind"] == "policy_decision"
    assert record["events"][-2]["decision"] == "allow"
    last_event = record["events"][-1]
    assert last_event["kind"] == "tool_result"
    assert last_event["tool"] == action.name
    assert last_event["status"] == "rejected"
    assert last_event["dispatch"] == "not_dispatched"
    assert last_event["code"] == "POLICY_DENIED"
    recovery = classify_run_recovery(
        checkpoint,
        task_length=len(task),
        policy_version="approved-v1",
    )
    assert (recovery.action, recovery.reason) == ("start_new_run", "RUN_TERMINAL")
    assert not continuation_path(config.state_dir, action.identity.run_id).exists()


def test_unadvertised_action_has_no_approval_or_desktop_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_unadvertised_action"
    observe = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 1, "call_2", "click", {"ref": "ref_1"})
    provider = FakeModelProvider(turns=deque([_turn(run_id, 1, observe, action)]))
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(
                    observe,
                    text='ref_1 | button "OK" | (1,1,10,10) | enabled',
                ),
                _result(action),
            ]
        )
    )
    approvals = DynamicApprovalPort()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunFailure, match="^PROVIDER_TOOL_NOT_ADVERTISED$"):
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                "Inspect only",
                run_id=run_id,
                allowed_tool_names=frozenset({"ui_snapshot"}),
            )
        )

    assert {tool.name for tool in provider.calls[0]["tools"]} == {"ui_snapshot"}
    assert approvals.requests == []
    assert desktop.tool_calls == []
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "PROVIDER_TOOL_NOT_ADVERTISED"
    assert [event["kind"] for event in record["events"]] == ["user_task"]


def test_malformed_sibling_has_no_approval_or_desktop_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_malformed_action_turn"
    observe = _call(run_id, 1, "call_1", "list_windows", {})
    action = _call(run_id, 1, "call_2", "activate_window", {"window_id": "42"})
    malformed = _call(
        run_id,
        1,
        "call_3",
        "list_windows",
        {"unexpected": True},
    )
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, observe, action, malformed)])
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(observe, text='* 42 | app.exe | "App"'),
                _result(action),
            ]
        )
    )
    approvals = DynamicApprovalPort()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunFailure, match="^SCHEMA_MISMATCH$"):
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                "Activate the observed window",
                run_id=run_id,
            )
        )

    advertised = {tool.name for tool in provider.calls[0]["tools"]}
    assert {"list_windows", "activate_window"}.issubset(advertised)
    assert approvals.requests == []
    assert desktop.tool_calls == []
    assert len(desktop.results) == 2
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "SCHEMA_MISMATCH"
    assert record["state"]["budgets"]["model_turns_used"] == 0
    assert record["state"]["budgets"]["tool_calls_used"] == 0
    assert record["state"]["budgets"]["side_effects_used"] == 0
    assert [event["kind"] for event in record["events"]] == ["user_task"]


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
    assert approvals.requests[0].binding is not None
    assert approvals.requests[0].binding.object_digest == action.digest
    assert [event.kind for event in outcome.state.event_log].count(
        LedgerEventKind.POLICY_DECISION
    ) == 1
    assert read_run_record(config.state_dir, run_id)["state"]["phase"] == "SUCCESS"


@pytest.mark.parametrize(
    (
        "max_model_turns",
        "max_input_tokens",
        "max_context_events",
        "max_tool_calls",
        "expected_code",
    ),
    [
        (2, 2, 8, 2, "MODEL_TURN_BUDGET_EXHAUSTED"),
        (4, 2, 8, 2, "INPUT_TOKEN_BUDGET_EXHAUSTED"),
        (4, 4, 8, 2, "CONTEXT_REQUIRED_EVENTS_EXCEED_BUDGET"),
        (4, 4, 9, 2, "TOOL_CALL_BUDGET_EXHAUSTED"),
    ],
)
def test_verification_capacity_fails_before_side_effect_authority_in_fixed_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    max_model_turns: int,
    max_input_tokens: int,
    max_context_events: int,
    max_tool_calls: int,
    expected_code: str,
) -> None:
    run_id = f"run_verify_capacity_{expected_code.lower()}"
    task = "Click OK and verify"
    provider, desktop, approvals, action = _verification_workflow(run_id)
    payloads = _capture_continuations(monkeypatch)
    config = _config(
        tmp_path,
        monkeypatch,
        continuation_enabled=True,
        max_model_turns=max_model_turns,
        max_input_tokens=max_input_tokens,
        max_context_events=max_context_events,
        max_tool_calls=max_tool_calls,
    )

    with pytest.raises(RunFailure, match=f"^{expected_code}$") as raised:
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                task,
                run_id=run_id,
            )
        )

    state = raised.value.state
    assert [event.kind for event in state.event_log] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
    ]
    rejected = state.event_log[-1].tool_result
    assert rejected is not None
    assert rejected.identity == action.identity
    assert rejected.status is ToolResultStatus.REJECTED
    assert rejected.dispatch is DispatchCertainty.NOT_DISPATCHED
    assert rejected.code == "BUDGET_EXHAUSTED"
    assert state.budgets.model_turns_used == 2
    assert state.budgets.input_tokens_used == 2
    assert state.budgets.tool_calls_used == 2
    assert state.budgets.side_effects_used == 0
    assert state.observation_epoch == state.verified_observation_epoch == 1
    assert state.recovery_status is RecoveryStatus.READY

    assert len(provider.calls) == 2
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]
    assert approvals.requests == []
    assert len(desktop.results) == 2
    assert desktop.close_calls == 1

    action_operation_id = f"{run_id}:turn_2:call_2"
    action_boundaries = [
        boundary
        for payload in payloads
        if isinstance((boundary := payload.get("boundary")), dict)
        and boundary.get("operation_kind") == "tool"
        and boundary.get("operation_id") == action_operation_id
    ]
    assert action_boundaries == []
    provider_completion = [
        payload
        for payload in payloads
        if isinstance(payload.get("boundary"), dict)
        and payload["boundary"] == {
            "operation_kind": "provider",
            "stage": "completed",
            "operation_id": f"{run_id}:turn_2:provider",
            "effect": "side_effect",
            "dispatch": "dispatched",
            "next_step": "stop",
        }
    ]
    assert len(provider_completion) == 1

    record = read_run_record(config.state_dir, run_id)
    checkpoint = record["state"]
    assert checkpoint["phase"] == "FAILED"
    assert checkpoint["failure_code"] == expected_code
    assert checkpoint["event_count"] == 8
    assert checkpoint["observation_epoch"] == 1
    assert checkpoint["verified_observation_epoch"] == 1
    assert checkpoint["recovery_status"] == "ready"
    assert checkpoint["resume_allowed"] is False
    assert checkpoint["recovery_action"] == "inspect_trace_then_start_new_run"
    assert checkpoint["budgets"]["model_turns_used"] == 2
    assert checkpoint["budgets"]["input_tokens_used"] == 2
    assert checkpoint["budgets"]["tool_calls_used"] == 2
    assert checkpoint["budgets"]["side_effects_used"] == 0
    assert checkpoint["checkpoint_sequence"] == provider_completion[0][
        "checkpoint_sequence"
    ]
    last_event = record["events"][-1]
    assert isinstance(last_event, dict)
    assert last_event["kind"] == "tool_result"
    assert last_event["tool"] == "click"
    assert last_event["status"] == "rejected"
    assert last_event["dispatch"] == "not_dispatched"
    assert last_event["code"] == "BUDGET_EXHAUSTED"
    recovery = classify_run_recovery(
        checkpoint,
        task_length=len(task),
        policy_version="approved-v1",
    )
    assert (recovery.action, recovery.reason) == ("start_new_run", "RUN_TERMINAL")
    assert not continuation_path(config.state_dir, run_id).exists()


def test_exact_verification_capacity_preserves_the_complete_approved_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run_exact_verification_capacity"
    task = "Click OK and verify"
    provider, desktop, approvals, _action = _verification_workflow(run_id)
    payloads = _capture_continuations(monkeypatch)
    config = _config(
        tmp_path,
        monkeypatch,
        continuation_enabled=True,
        max_model_turns=4,
        max_input_tokens=4,
        max_context_events=9,
        max_tool_calls=3,
    )

    outcome = asyncio.run(
        AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
            task,
            run_id=run_id,
        )
    )

    assert outcome.text == "verified"
    assert [event.kind for event in outcome.state.event_log] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.POLICY_DECISION,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
        LedgerEventKind.MODEL_TURN,
    ]
    assert outcome.state.budgets.model_turns_used == 4
    assert outcome.state.budgets.input_tokens_used == 4
    assert outcome.state.budgets.tool_calls_used == 3
    assert outcome.state.budgets.side_effects_used == 1
    assert outcome.state.observation_epoch == 2
    assert outcome.state.verified_observation_epoch == 2
    assert outcome.state.recovery_status is RecoveryStatus.READY
    assert len(provider.calls) == 4
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "click",
        "ui_snapshot",
    ]
    assert len(approvals.requests) == 1

    action_operation_id = f"{run_id}:turn_2:call_2"
    action_boundaries = [
        boundary
        for payload in payloads
        if isinstance((boundary := payload.get("boundary")), dict)
        and boundary.get("operation_kind") == "tool"
        and boundary.get("operation_id") == action_operation_id
    ]
    assert [boundary["stage"] for boundary in action_boundaries] == [
        "prepared",
        "dispatch_intent",
        "completed",
    ]
    assert action_boundaries[-1]["next_step"] == "mandatory_reobserve"

    record = read_run_record(config.state_dir, run_id)
    checkpoint = record["state"]
    assert checkpoint["phase"] == "SUCCESS"
    assert checkpoint["event_count"] == 14
    assert checkpoint["budgets"]["model_turns_used"] == 4
    assert checkpoint["budgets"]["input_tokens_used"] == 4
    assert checkpoint["budgets"]["tool_calls_used"] == 3
    assert checkpoint["budgets"]["side_effects_used"] == 1
    assert checkpoint["observation_epoch"] == 2
    assert checkpoint["verified_observation_epoch"] == 2
    assert checkpoint["recovery_status"] == "ready"
    assert checkpoint["resume_allowed"] is False
    assert checkpoint["recovery_action"] == "none"
    recovery = classify_run_recovery(
        checkpoint,
        task_length=len(task),
        policy_version="approved-v1",
    )
    assert (recovery.action, recovery.reason) == ("none", "RUN_SUCCEEDED")
    assert not continuation_path(config.state_dir, run_id).exists()


def test_exact_single_verification_lane_is_not_overreserved_for_final_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run_single_verification_lane"
    task = "Click OK and verify"
    provider, desktop, approvals, _action = _verification_workflow(run_id)
    payloads = _capture_continuations(monkeypatch)
    config = _config(
        tmp_path,
        monkeypatch,
        continuation_enabled=True,
        max_model_turns=3,
        max_input_tokens=3,
        max_context_events=9,
        max_tool_calls=3,
    )

    with pytest.raises(
        RunFailure,
        match="^MODEL_TURN_BUDGET_EXHAUSTED$",
    ) as raised:
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                task,
                run_id=run_id,
            )
        )

    state = raised.value.state
    assert state.budgets.model_turns_used == 3
    assert state.budgets.input_tokens_used == 3
    assert state.budgets.tool_calls_used == 3
    assert state.budgets.side_effects_used == 1
    assert state.observation_epoch == state.verified_observation_epoch == 2
    assert state.recovery_status is RecoveryStatus.READY
    assert state.event_log[-1].kind is LedgerEventKind.OBSERVATION
    assert len(state.event_log) == 13
    assert len(provider.calls) == 3
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "click",
        "ui_snapshot",
    ]
    assert len(approvals.requests) == 1

    completed_tool_ids = {
        str(boundary["operation_id"])
        for payload in payloads
        if isinstance((boundary := payload.get("boundary")), dict)
        and boundary.get("operation_kind") == "tool"
        and boundary.get("stage") == "completed"
    }
    assert completed_tool_ids == {
        f"{run_id}:turn_1:call_1",
        f"{run_id}:turn_2:call_2",
        f"{run_id}:turn_3:call_3",
    }

    record = read_run_record(config.state_dir, run_id)
    checkpoint = record["state"]
    assert checkpoint["phase"] == "FAILED"
    assert checkpoint["failure_code"] == "MODEL_TURN_BUDGET_EXHAUSTED"
    assert checkpoint["event_count"] == 13
    assert checkpoint["observation_epoch"] == 2
    assert checkpoint["verified_observation_epoch"] == 2
    assert checkpoint["recovery_status"] == "ready"
    assert checkpoint["budgets"]["model_turns_used"] == 3
    assert checkpoint["budgets"]["input_tokens_used"] == 3
    assert checkpoint["budgets"]["tool_calls_used"] == 3
    assert checkpoint["budgets"]["side_effects_used"] == 1
    assert checkpoint["resume_allowed"] is False
    assert checkpoint["recovery_action"] == "inspect_trace_then_start_new_run"
    recovery = classify_run_recovery(
        checkpoint,
        task_length=len(task),
        policy_version="approved-v1",
    )
    assert (recovery.action, recovery.reason) == ("start_new_run", "RUN_TERMINAL")
    assert not continuation_path(config.state_dir, run_id).exists()


def test_focus_taking_card_yields_before_choice_and_uses_sole_dispatch_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_card_order"
    observe = _call(run_id, 1, "call_1", "list_windows", {})
    action = _call(run_id, 2, "call_2", "activate_window", {"window_id": "42"})
    verify = _call(run_id, 3, "call_3", "list_windows", {})
    provider = FakeModelProvider(turns=deque([
        _turn(run_id, 1, observe),
        _turn(run_id, 2, action),
        _turn(run_id, 3, verify),
        _turn(run_id, 4, text="verified"),
    ]))
    events: list[str] = []

    class OrderedDesktop(FakeDesktopMCP):
        async def call_tool(self, call: ToolCall) -> ToolResult:
            if call.name == "activate_window":
                events.append("dispatch")
            return await super().call_tool(call)

    desktop = OrderedDesktop(results=deque([
        _result(observe, text='* 42 | app.exe | "App"'),
        _result(action),
        _result(verify, text='* 42 | app.exe | "App"'),
    ]))

    class Surface:
        cards = []

        async def choose(self, card, *, timeout_seconds: int):  # noqa: ANN001
            del timeout_seconds
            events.append("card")
            self.cards.append(card)
            return DecisionSelection(
                card.decision_id, card.card_digest, "option_approve_exact_effect"
            )

    class Presence:
        def on_phase(self, _phase) -> None:  # noqa: ANN001
            pass

        def estop(self) -> None:
            pass

        def release(self) -> None:
            events.append("yield")

    surface = Surface()
    approvals = DecisionCardApprovalPort(
        surface, timeout_seconds=30, clock=lambda: datetime(2026, 7, 22, tzinfo=UTC)
    )
    outcome = asyncio.run(AgentRunner(
        _config(tmp_path, monkeypatch),
        RunnerPorts(provider, desktop, approvals, presence=Presence()),
    ).run("Activate and verify", run_id=run_id))

    assert outcome.text == "verified"
    assert events == ["yield", "card", "dispatch"]
    assert surface.cards[0].binding.object_digest == action.digest
    assert [option.option_id for option in surface.cards[0].options] == [
        "option_approve_exact_effect",
        "option_reobserve",
        "option_defer",
        "option_deny",
    ]


def test_decision_card_defer_persists_paused_without_side_effect_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_card_defer"
    observe = _call(run_id, 1, "call_1", "list_windows", {})
    action = _call(run_id, 2, "call_2", "activate_window", {"window_id": "42"})
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, observe), _turn(run_id, 2, action)])
    )
    desktop = FakeDesktopMCP(
        results=deque([_result(observe, text='* 42 | app.exe | "App"')])
    )

    class DeferSurface:
        async def choose(self, card, *, timeout_seconds: int):  # noqa: ANN001
            del timeout_seconds
            return DecisionSelection(
                card.decision_id, card.card_digest, "option_defer"
            )

    approvals = DecisionCardApprovalPort(
        DeferSurface(), clock=lambda: datetime(2026, 7, 22, tzinfo=UTC)
    )
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunDeferred, match="APPROVAL_DEFERRED") as deferred:
        asyncio.run(
            AgentRunner(
                config, RunnerPorts(provider, desktop, approvals)
            ).run("Defer for operator", run_id=run_id)
        )

    assert [call.name for call in desktop.tool_calls] == ["list_windows"]
    assert deferred.value.state.recovery_status is RecoveryStatus.STOPPED
    assert deferred.value.state.budgets.side_effects_used == 0
    decisions = [
        event.policy_decision
        for event in deferred.value.state.event_log
        if event.kind is LedgerEventKind.POLICY_DECISION
    ]
    assert decisions[-1] is not None
    assert decisions[-1].reason == "decision_card_deferred"
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "PAUSED"
    assert record["state"]["recovery_status"] == "stopped"
    assert record["state"]["resume_allowed"] is False
    recovery = classify_run_recovery(
        record["state"], task_length=len("Defer for operator"), policy_version="approved-v1"
    )
    assert (recovery.action, recovery.reason) == ("start_new_run", "OPERATOR_DEFERRED")


def test_decision_card_reobserve_abandons_turn_and_requires_fresh_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_card_reobserve"
    before = _call(run_id, 1, "call_1", "list_windows", {})
    proposed = _call(run_id, 2, "call_2", "activate_window", {"window_id": "42"})
    abandoned = _call(run_id, 2, "call_3", "activate_window", {"window_id": "43"})
    refreshed = _call(run_id, 3, "call_4", "list_windows", {})
    provider = FakeModelProvider(turns=deque([
        _turn(run_id, 1, before),
        _turn(run_id, 2, proposed, abandoned),
        _turn(run_id, 3, refreshed),
        _turn(run_id, 4, text="fresh evidence retained"),
    ]))
    desktop = FakeDesktopMCP(results=deque([
        _result(before, text='* 42 | app.exe | "App"'),
        _result(refreshed, text='* 42 | app.exe | "App"'),
    ]))

    outcome = asyncio.run(
        AgentRunner(
            _config(tmp_path, monkeypatch),
            RunnerPorts(provider, desktop, DynamicApprovalPort(PolicyDecisionKind.REOBSERVE)),
        ).run("Refresh before acting", run_id=run_id)
    )

    assert outcome.text == "fresh evidence retained"
    assert [call.identity.call_id for call in desktop.tool_calls] == ["call_1", "call_4"]
    assert outcome.state.budgets.side_effects_used == 0
    assert outcome.state.recovery_status is RecoveryStatus.READY
    results = [
        event.tool_result for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
    ]
    assert any(
        result is not None and result.code == "APPROVAL_REOBSERVE_REQUIRED"
        and result.dispatch is DispatchCertainty.NOT_DISPATCHED
        for result in results
    )


def test_reobserve_choice_rejects_an_action_until_observation_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_card_reobserve_action"
    before = _call(run_id, 1, "call_1", "list_windows", {})
    proposed = _call(run_id, 2, "call_2", "activate_window", {"window_id": "42"})
    premature = _call(run_id, 3, "call_3", "activate_window", {"window_id": "42"})
    provider = FakeModelProvider(turns=deque([
        _turn(run_id, 1, before),
        _turn(run_id, 2, proposed),
        _turn(run_id, 3, premature),
    ]))
    desktop = FakeDesktopMCP(
        results=deque([_result(before, text='* 42 | app.exe | "App"')])
    )

    with pytest.raises(RunFailure, match="REOBSERVATION_REQUIRED"):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch),
                RunnerPorts(
                    provider,
                    desktop,
                    DynamicApprovalPort(PolicyDecisionKind.REOBSERVE),
                ),
            ).run("Refresh before acting", run_id=run_id)
        )

    assert [call.identity.call_id for call in desktop.tool_calls] == ["call_1"]


def test_host_binding_drift_during_card_blocks_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_card_drift"
    observe = _call(run_id, 1, "call_1", "list_windows", {})
    action = _call(run_id, 2, "call_2", "activate_window", {"window_id": "42"})
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, observe), _turn(run_id, 2, action)])
    )
    desktop = FakeDesktopMCP(
        results=deque([_result(observe, text='* 42 | app.exe | "App"')])
    )
    runner: AgentRunner

    class DriftSurface:
        async def choose(self, card, *, timeout_seconds: int):  # noqa: ANN001
            del timeout_seconds
            runner.policy = replace(runner.policy, version="changed-policy")
            return DecisionSelection(
                card.decision_id, card.card_digest, "option_approve_exact_effect"
            )

    approvals = DecisionCardApprovalPort(
        DriftSurface(), clock=lambda: datetime(2026, 7, 22, tzinfo=UTC)
    )
    runner = AgentRunner(
        _config(tmp_path, monkeypatch), RunnerPorts(provider, desktop, approvals)
    )

    with pytest.raises(RunFailure, match="APPROVAL_MISMATCH"):
        asyncio.run(runner.run("Activate", run_id=run_id))
    assert [call.name for call in desktop.tool_calls] == ["list_windows"]


@pytest.mark.parametrize(
    (
        "case",
        "observation_name",
        "observation_text",
        "observation_images",
        "action_name",
        "action_arguments",
    ),
    [
        pytest.param(
            "ref",
            "ui_snapshot",
            'ref_1 | button "OK" | (1,1,10,10) | enabled',
            (),
            "click",
            {"ref": "ref_1"},
            id="ref",
        ),
        pytest.param(
            "window",
            "list_windows",
            '* 42 | app.exe | "App"',
            (),
            "activate_window",
            {"window_id": "42"},
            id="window",
        ),
        pytest.param(
            "screenshot",
            "screenshot",
            "",
            (ImageContent("image/png", _PNG_10X10, 10, 10),),
            "click",
            {"x": 0, "y": 0},
            id="screenshot",
        ),
    ],
)
def test_generation_drift_after_allow_has_no_side_effect_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    observation_name: str,
    observation_text: str,
    observation_images: tuple[ImageContent, ...],
    action_name: str,
    action_arguments: dict[str, object],
) -> None:
    run_id = f"run_post_approval_generation_{case}"
    task = "Use only current desktop authority"
    observe = _call(run_id, 1, "call_1", observation_name, {})
    action = _call(run_id, 2, "call_2", action_name, action_arguments)
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, observe, input_tokens=1),
                _turn(run_id, 2, action, input_tokens=1),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(
                    observe,
                    text=observation_text,
                    images=observation_images,
                )
            ]
        )
    )
    approvals = DynamicApprovalPort(
        on_request=lambda _request: setattr(desktop, "generation", 2)
    )
    payloads = _capture_continuations(monkeypatch)
    config = _config(tmp_path, monkeypatch, continuation_enabled=True)

    with pytest.raises(RunFailure, match="^MCP_GENERATION_CHANGED$") as raised:
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                task,
                run_id=run_id,
            )
        )

    _assert_post_approval_authority_failure(
        raised.value,
        expected_code="MCP_GENERATION_CHANGED",
        config=config,
        task=task,
        observe=observe,
        action=action,
        provider=provider,
        desktop=desktop,
        approvals=approvals,
        payloads=payloads,
    )


def test_safety_baseline_loss_after_allow_has_no_side_effect_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run_post_approval_baseline_loss"
    task = "Type only while redaction is evidenced"
    observe = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "type", {"text": "sensitive-value"})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, observe, input_tokens=1),
                _turn(run_id, 2, action, input_tokens=1),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        satisfied_safety_baselines=frozenset({"typed_text_audit_redaction"}),
        results=deque(
            [
                _result(
                    observe,
                    text='ref_1 | textbox "Input" | (1,1,10,10) | enabled',
                )
            ]
        ),
    )
    approvals = DynamicApprovalPort(
        on_request=lambda _request: setattr(
            desktop,
            "satisfied_safety_baselines",
            frozenset(),
        )
    )
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(
        RunFailure,
        match="^SAFETY_BASELINE_UNSATISFIED$",
    ) as raised:
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                task,
                run_id=run_id,
            )
        )

    assert "type" in {tool.name for tool in provider.calls[1]["tools"]}
    _assert_post_approval_authority_failure(
        raised.value,
        expected_code="SAFETY_BASELINE_UNSATISFIED",
        config=config,
        task=task,
        observe=observe,
        action=action,
        provider=provider,
        desktop=desktop,
        approvals=approvals,
        payloads=None,
    )


def test_post_approval_live_authority_recheck_allows_unchanged_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = "run_post_approval_authority_unchanged"
    before = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "type", {"text": "approved-value"})
    after = _call(run_id, 3, "call_3", "ui_snapshot", {})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, before, input_tokens=1),
                _turn(run_id, 2, action, input_tokens=1),
                _turn(run_id, 3, after, input_tokens=1),
                _turn(run_id, 4, text="verified", input_tokens=1),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        satisfied_safety_baselines=frozenset({"typed_text_audit_redaction"}),
        results=deque(
            [
                _result(
                    before,
                    text='ref_1 | textbox "Input" | (1,1,10,10) | enabled',
                ),
                _result(action),
                _result(
                    after,
                    text='ref_2 | text "approved" | (1,1,10,10) | enabled',
                ),
            ]
        ),
    )
    approvals = DynamicApprovalPort()
    config = _config(tmp_path, monkeypatch)

    outcome = asyncio.run(
        AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
            "Type and verify",
            run_id=run_id,
        )
    )

    assert outcome.text == "verified"
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "type",
        "ui_snapshot",
    ]
    assert outcome.state.budgets.side_effects_used == 1
    assert outcome.state.observation_epoch == outcome.state.verified_observation_epoch == 2
    assert outcome.state.recovery_status is RecoveryStatus.READY
    assert len(approvals.requests) == 1
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


def test_unadvertised_type_is_rejected_before_requesting_approval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_type_denied"
    call = _call(run_id, 1, "call_1", "type", {"text": "typed-value"})
    provider = FakeModelProvider(turns=deque([_turn(run_id, 1, call)]))
    approvals = DynamicApprovalPort()
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunFailure, match="^PROVIDER_TOOL_NOT_ADVERTISED$"):
        asyncio.run(
            AgentRunner(
                config, RunnerPorts(provider, desktop, approvals)
            ).run("Type", run_id=run_id)
        )

    assert "type" not in {tool.name for tool in provider.calls[0]["tools"]}
    assert approvals.requests == []
    assert desktop.tool_calls == []
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["failure_code"] == "PROVIDER_TOOL_NOT_ADVERTISED"


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


@pytest.mark.parametrize("completion_write_fails", [False, True])
def test_post_dispatch_cancellation_persists_unknown_result_before_propagating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completion_write_fails: bool,
) -> None:
    run_id = "run_cancelled_action"
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
    completed_tool_boundaries: list[dict[str, object]] = []
    original_write = continuation_module.write_continuation

    def capture_completed_tool(state_dir: Path, payload: object) -> object:
        assert isinstance(payload, dict)
        boundary = payload.get("boundary")
        action_completed = (
            isinstance(boundary, dict)
            and boundary.get("operation_kind") == "tool"
            and boundary.get("stage") == "completed"
            and boundary.get("operation_id") == f"{run_id}:turn_2:call_2"
        )
        if action_completed:
            completed_tool_boundaries.append(deepcopy(payload))
            if completion_write_fails:
                raise OSError("injected continuation completion failure")
        return original_write(state_dir, payload)

    monkeypatch.setattr(
        continuation_module,
        "write_continuation",
        capture_completed_tool,
    )

    class CancellingDesktop(FakeDesktopMCP):
        def __init__(self) -> None:
            super().__init__(
                results=deque(
                    [
                        _result(
                            observe,
                            text='ref_1 | button "OK" | (1,1,10,10) | enabled',
                        )
                    ]
                )
            )
            self.action_entered = asyncio.Event()

        async def call_tool(self, call: ToolCall) -> ToolResult:
            if call.identity != action.identity:
                return await super().call_tool(call)
            self.tool_calls.append(call)
            self.action_entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                raise MCPCallCancelled(unknown) from None
            raise AssertionError("cancelled action unexpectedly resumed")

    desktop = CancellingDesktop()
    config = _config(tmp_path, monkeypatch, continuation_enabled=True)
    runner = AgentRunner(
        config,
        RunnerPorts(provider, desktop, DynamicApprovalPort()),
    )

    async def scenario() -> tuple[MCPCallCancelled, bool]:
        task = asyncio.create_task(runner.run("Click", run_id=run_id))
        await desktop.action_entered.wait()
        task.cancel()
        with pytest.raises(MCPCallCancelled) as raised:
            await task
        return raised.value, task.cancelled()

    cancelled, task_cancelled = asyncio.run(scenario())

    assert task_cancelled
    assert cancelled.result == unknown
    if completion_write_fails:
        assert isinstance(cancelled.__cause__, OSError)
        assert str(cancelled.__cause__) == "injected continuation completion failure"
    else:
        assert cancelled.__cause__ is None
    assert [call.identity.call_id for call in desktop.tool_calls] == [
        "call_1",
        "call_2",
    ]
    assert len(provider.calls) == 2
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "UNKNOWN_OUTCOME"
    assert record["state"]["failure_code"] == "UNKNOWN_OUTCOME"
    assert record["state"]["recovery_status"] == "unknown_outcome"
    assert record["state"]["recovery_action"] == "human_reobserve_then_start_new_run"
    unknown_events = [
        event
        for event in record["events"]
        if isinstance(event, dict)
        and event.get("kind") == "tool_result"
        and event.get("status") == "unknown_outcome"
    ]
    assert len(unknown_events) == 1
    assert unknown_events[0]["tool"] == "click"
    assert unknown_events[0]["dispatch"] == "unknown"
    assert unknown_events[0]["code"] == "MCP_TRANSPORT_ERROR"
    action_completion = completed_tool_boundaries[-1]
    assert action_completion["checkpoint_sequence"] == record["state"][
        "checkpoint_sequence"
    ]
    assert action_completion["boundary"] == {
        "operation_kind": "tool",
        "stage": "completed",
        "operation_id": f"{run_id}:turn_2:call_2",
        "effect": "side_effect",
        "dispatch": "unknown",
        "next_step": "stop",
    }
    ledger = action_completion["ledger"]
    assert isinstance(ledger, list)
    last_event = ledger[-1]
    assert isinstance(last_event, dict)
    assert last_event["kind"] == "tool_result"
    data = last_event["data"]
    assert isinstance(data, dict)
    assert data["status"] == "unknown_outcome"
    assert not continuation_path(config.state_dir, run_id).exists()
