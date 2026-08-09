from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable

import pytest

from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import continuation_path
from computer_use_agent.executor_final import (
    ExecutorFinalError,
    FinalResponseRequest,
    FinalResponseResult,
    compile_hierarchical_side_effect_final_response_request,
)
from computer_use_agent.executor_runtime import (
    ExecutorRuntimeError,
    open_hierarchical_side_effect_runtime_executor_session,
)
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.hierarchical_side_effects import (
    HierarchicalSideEffectError,
    validate_bounded_side_effect_plan,
)
from computer_use_agent.plan_store import TaskPlanStore
from computer_use_agent.planning import PlanStepStatus, compile_task_plan
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.tree_store import TaskTreeStore
from computer_use_agent.types import (
    ApprovalRequest,
    DispatchCertainty,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    RecoveryStatus,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


TASK = "Toggle the isolated application control and verify its new state"


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "h7",
        policy_version="h7-reviewed-v1",
        provider=ProviderConfig(name="openai", model="fake"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "isolated-toggle.exe"},
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=4,
            max_tool_calls=3,
            max_side_effects=1,
        ),
        continuation=ContinuationConfig(enabled=True),
    )


def _plan(*, steps: str | None = None):
    body = steps or (
        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
        '{"action":"tool","tool":"click","arguments":{"ref":"ref_1"}},'
        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
        '{"action":"final_response"}'
    )
    return compile_task_plan(
        f'{{"version":1,"steps":[{body}]}}',
        plan_id="plan_h7",
        run_id="run_h7",
        task=TASK,
        allowed_tools=("ui_snapshot", "click"),
    )


@dataclass
class BoundApprovalPort:
    kind: PolicyDecisionKind = PolicyDecisionKind.ALLOW
    on_request: Callable[[ApprovalRequest], None] | None = None
    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        if self.on_request is not None:
            self.on_request(request)
        return PolicyDecision(
            request_id=request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=self.kind,
            reason="isolated_operator_review",
        )


@dataclass
class IsolatedToggleApplication(FakeDesktopMCP):
    checked: bool = False
    action_status: ToolResultStatus = ToolResultStatus.SUCCESS
    action_dispatch: DispatchCertainty = DispatchCertainty.DISPATCHED

    async def call_tool(self, call: ToolCall) -> ToolResult:
        self.tool_calls.append(call)
        assert call.status is ToolCallStatus.AUTHORIZED
        if call.name == "ui_snapshot":
            text = (
                'ref_2 | checkbox "Enabled" | checked | enabled'
                if self.checked
                else 'ref_1 | checkbox "Enabled" | unchecked | enabled'
            )
            return ToolResult(
                identity=call.identity,
                tool_name=call.name,
                status=ToolResultStatus.SUCCESS,
                dispatch=DispatchCertainty.DISPATCHED,
                sanitized_text=text,
            )
        assert call.name == "click"
        assert call.arguments == {"ref": "ref_1"}
        if self.action_status is ToolResultStatus.SUCCESS:
            self.checked = True
        return ToolResult(
            identity=call.identity,
            tool_name=call.name,
            status=self.action_status,
            dispatch=self.action_dispatch,
            sanitized_text="action result content is not final-response input",
            code=(
                "MCP_TRANSPORT_ERROR"
                if self.action_status is ToolResultStatus.UNKNOWN_OUTCOME
                else "DRIVER_ERROR"
                if self.action_status is ToolResultStatus.ACTION_ERROR
                else None
            ),
        )


@dataclass
class RecordingFinalPort:
    requests: list[FinalResponseRequest] = field(default_factory=list)

    async def create_final_response(
        self, request: FinalResponseRequest
    ) -> FinalResponseResult:
        self.requests.append(request)
        return FinalResponseResult(
            run_id=request.run_id,
            turn_id=request.turn_id,
            provider_response_id="isolated-final-1",
            text="The isolated control is enabled.",
            usage=ModelUsage(input_tokens=1, output_tokens=1),
        )


def _runner(
    config: AgentConfig,
    desktop: IsolatedToggleApplication,
    approvals: BoundApprovalPort,
) -> AgentRunner:
    return AgentRunner(
        config,
        RunnerPorts(
            provider=FakeModelProvider(),
            desktop=desktop,
            approvals=approvals,
        ),
    )


def _durable_statuses(config: AgentConfig) -> tuple[list[str], list[str]]:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        plan = TaskPlanStore(config.state_dir, lock).read("run_h7").plan
        tree = TaskTreeStore(config.state_dir, lock).read("run_h7").tree
    finally:
        lock.release()
    return (
        [step.status.value for step in plan.steps],
        [
            node.status.value
            for node in sorted(
                (item for item in tree.nodes if item.is_leaf),
                key=lambda item: item.node_id,
            )
        ],
    )


@pytest.mark.parametrize(
    "steps",
    [
        (
            '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
            '{"action":"final_response"}'
        ),
        (
            '{"action":"tool","tool":"click","arguments":{"ref":"ref_1"}},'
            '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
            '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
            '{"action":"final_response"}'
        ),
        (
            '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
            '{"action":"tool","tool":"click","arguments":{"ref":"ref_1"}},'
            '{"action":"tool","tool":"click","arguments":{"ref":"ref_1"}},'
            '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
            '{"action":"final_response"}'
        ),
    ],
)
def test_h7_review_gate_rejects_every_non_exact_sequence(steps: str) -> None:
    with pytest.raises(HierarchicalSideEffectError, match="^H7_PLAN_SHAPE_UNSAFE$"):
        validate_bounded_side_effect_plan(_plan(steps=steps))


def test_h7_rejects_unsafe_shape_before_store_or_external_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = IsolatedToggleApplication()
    approvals = BoundApprovalPort()

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_TREE_PLAN_UNSAFE$"):
        asyncio.run(
            open_hierarchical_side_effect_runtime_executor_session(
                _runner(config, desktop, approvals),
                task=TASK,
                plan=_plan(
                    steps=(
                        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
                        '{"action":"final_response"}'
                    )
                ),
                tree_id="tree_h7",
            )
        )

    assert desktop.discovery_calls == 0
    assert desktop.tool_calls == []
    assert approvals.requests == []
    assert not config.state_dir.exists()


def test_h7_isolated_application_preserves_exact_approval_and_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = IsolatedToggleApplication()
    approvals = BoundApprovalPort()
    runner = _runner(config, desktop, approvals)
    session = asyncio.run(
        open_hierarchical_side_effect_runtime_executor_session(
            runner,
            task=TASK,
            plan=_plan(),
            tree_id="tree_h7",
        )
    )

    before = asyncio.run(session.execute_next_tool())
    assert before.state.observation_epoch == 1
    assert before.state.verified_observation_epoch == 1

    with pytest.raises(
        ExecutorRuntimeError, match="^EXECUTOR_SESSION_SIDE_EFFECT_UNSUPPORTED$"
    ):
        asyncio.run(session.execute_next_observation())
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]

    def inspect_approval(request: ApprovalRequest) -> None:
        assert request.tool_name == "click"
        assert request.binding is not None
        assert request.binding.object_digest == request.call_digest
        plan = session.store.read("run_h7").plan
        assert plan.steps[1].status is PlanStepStatus.IN_PROGRESS
        assert session.tree_projection is not None
        tree = session.tree_projection.snapshot().tree
        active = [node for node in tree.nodes if node.status is PlanStepStatus.IN_PROGRESS and node.is_leaf]
        assert [(node.step_id, node.kind.value) for node in active] == [
            ("step_2", "tool_step")
        ]

    approvals.on_request = inspect_approval
    action = asyncio.run(session.execute_next_tool())
    assert desktop.checked
    assert action.state.recovery_status is RecoveryStatus.REQUIRES_REOBSERVATION
    assert action.state.verified_observation_epoch is None
    assert action.state.budgets.side_effects_used == 1
    assert len(approvals.requests) == 1

    with pytest.raises(ExecutorRuntimeError, match="^EXECUTOR_FINAL_PLAN_NOT_READY$"):
        asyncio.run(session.execute_final_response(RecordingFinalPort()))

    after = asyncio.run(session.execute_next_tool())
    assert after.state.recovery_status is RecoveryStatus.READY
    assert after.state.observation_epoch == 2
    assert after.state.verified_observation_epoch == 2

    snapshot = session.store.read("run_h7")
    events = list(after.state.event_log)
    decision_index = next(
        index for index, event in enumerate(events) if event.policy_decision is not None
    )
    decision = events[decision_index].policy_decision
    assert decision is not None
    events[decision_index] = replace(
        events[decision_index],
        policy_decision=replace(decision, call_digest="0" * 64),
    )
    forged_state = replace(after.state, event_log=tuple(events))
    with pytest.raises(ExecutorFinalError, match="^EXECUTOR_FINAL_LEDGER_INVALID$"):
        compile_hierarchical_side_effect_final_response_request(
            snapshot,
            forged_state,
            expected_sequence=snapshot.sequence,
            expected_plan_digest=snapshot.plan.digest,
            turn_id="executor_final_1",
        )

    final_port = RecordingFinalPort()
    final = asyncio.run(session.execute_final_response(final_port))
    assert final.text == "The isolated control is enabled."
    assert session.closed
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "click",
        "ui_snapshot",
    ]
    assert len(final_port.requests) == 1
    assert [item.step_id for item in final_port.requests[0].observations] == [
        "step_1",
        "step_3",
    ]
    assert all(
        "action result content" not in item.sanitized_text
        for item in final_port.requests[0].observations
    )
    assert final.state.budgets.tool_calls_used == 3
    assert final.state.budgets.side_effects_used == 1
    assert _durable_statuses(config) == (
        ["completed", "completed", "completed", "completed"],
        ["completed", "completed", "completed", "completed"],
    )
    assert not continuation_path(config.state_dir, "run_h7").exists()


def test_h7_denial_terminalizes_action_without_action_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = IsolatedToggleApplication()
    approvals = BoundApprovalPort(kind=PolicyDecisionKind.DENY)
    session = asyncio.run(
        open_hierarchical_side_effect_runtime_executor_session(
            _runner(config, desktop, approvals),
            task=TASK,
            plan=_plan(),
            tree_id="tree_h7",
        )
    )
    asyncio.run(session.execute_next_tool())

    with pytest.raises(ExecutorRuntimeError, match="^APPROVAL_DENIED$"):
        asyncio.run(session.execute_next_tool())

    assert not desktop.checked
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]
    assert len(approvals.requests) == 1
    plan_statuses, _tree_statuses = _durable_statuses(config)
    assert plan_statuses == ["completed", "failed", "pending", "pending"]
    assert not continuation_path(config.state_dir, "run_h7").exists()


def test_h7_defer_is_known_paused_evidence_not_unknown_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = IsolatedToggleApplication()
    approvals = BoundApprovalPort(kind=PolicyDecisionKind.DEFER)
    session = asyncio.run(
        open_hierarchical_side_effect_runtime_executor_session(
            _runner(config, desktop, approvals),
            task=TASK,
            plan=_plan(),
            tree_id="tree_h7",
        )
    )
    asyncio.run(session.execute_next_tool())

    with pytest.raises(ExecutorRuntimeError, match="^APPROVAL_DEFERRED$"):
        asyncio.run(session.execute_next_tool())

    assert session.closed
    assert not desktop.checked
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]
    assert len(approvals.requests) == 1
    plan_statuses, tree_statuses = _durable_statuses(config)
    assert plan_statuses == ["completed", "blocked", "pending", "pending"]
    assert tree_statuses.count("blocked") == 1
    checkpoint = read_run_record(config.state_dir, "run_h7")["state"]
    assert checkpoint["phase"] == "PAUSED"
    assert checkpoint["failure_code"] == "APPROVAL_DEFERRED"
    assert checkpoint["recovery_status"] == "stopped"
    assert not continuation_path(config.state_dir, "run_h7").exists()


def test_h7_unknown_action_keeps_exact_leaf_active_with_zero_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = IsolatedToggleApplication(
        action_status=ToolResultStatus.UNKNOWN_OUTCOME,
        action_dispatch=DispatchCertainty.UNKNOWN,
    )
    approvals = BoundApprovalPort()
    session = asyncio.run(
        open_hierarchical_side_effect_runtime_executor_session(
            _runner(config, desktop, approvals),
            task=TASK,
            plan=_plan(),
            tree_id="tree_h7",
        )
    )
    asyncio.run(session.execute_next_tool())

    with pytest.raises(ExecutorRuntimeError, match="^UNKNOWN_OUTCOME$"):
        asyncio.run(session.execute_next_tool())

    assert session.closed
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot", "click"]
    assert len(approvals.requests) == 1
    plan_statuses, tree_statuses = _durable_statuses(config)
    assert plan_statuses == ["completed", "in_progress", "pending", "pending"]
    assert tree_statuses.count("in_progress") == 1
    assert continuation_path(config.state_dir, "run_h7").exists()


def test_h7_dispatched_action_error_blocks_for_verification_and_preserves_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = IsolatedToggleApplication(
        action_status=ToolResultStatus.ACTION_ERROR,
        action_dispatch=DispatchCertainty.DISPATCHED,
    )
    approvals = BoundApprovalPort()
    session = asyncio.run(
        open_hierarchical_side_effect_runtime_executor_session(
            _runner(config, desktop, approvals),
            task=TASK,
            plan=_plan(),
            tree_id="tree_h7",
        )
    )
    asyncio.run(session.execute_next_tool())

    with pytest.raises(
        ExecutorRuntimeError, match="^EXECUTOR_VERIFICATION_REQUIRED$"
    ):
        asyncio.run(session.execute_next_tool())

    assert session.closed
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot", "click"]
    assert len(approvals.requests) == 1
    plan_statuses, tree_statuses = _durable_statuses(config)
    assert plan_statuses == ["completed", "blocked", "pending", "pending"]
    assert tree_statuses.count("blocked") == 1
    checkpoint = read_run_record(config.state_dir, "run_h7")["state"]
    assert checkpoint["failure_code"] == "EXECUTOR_VERIFICATION_REQUIRED"
    assert checkpoint["recovery_status"] == "requires_reobservation"
    assert continuation_path(config.state_dir, "run_h7").exists()
