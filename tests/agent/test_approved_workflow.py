from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from computer_use_agent.config import (
    AGENTIC_ACTIONS_MODE,
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.approvals import DecisionCardApprovalPort
from computer_use_agent.decision_cards import DecisionSelection
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunDeferred, RunFailure, RunnerPorts
from computer_use_agent.trace import classify_run_recovery, read_run_record
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


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = APPROVED_ACTIONS_MODE,
    max_side_effects: int = 2,
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
            mode=mode,
            require_approval_for_actions=mode != AGENTIC_ACTIONS_MODE,
            max_model_turns=6,
            max_tool_calls=6,
            max_side_effects=max_side_effects,
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
    assert approvals.requests[0].binding is not None
    assert approvals.requests[0].binding.object_digest == action.digest
    assert [event.kind for event in outcome.state.event_log].count(
        LedgerEventKind.POLICY_DECISION
    ) == 1
    assert read_run_record(config.state_dir, run_id)["state"]["phase"] == "SUCCESS"


def test_agentic_action_dispatches_without_per_action_approval_but_keeps_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_agentic"
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
    config = _config(tmp_path, monkeypatch, mode=AGENTIC_ACTIONS_MODE)

    outcome = asyncio.run(
        AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
            "Click OK and verify", run_id=run_id
        )
    )

    assert outcome.text == "verified"
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "click",
        "ui_snapshot",
    ]
    assert approvals.requests == []
    assert outcome.state.budgets.side_effects_used == 1
    assert outcome.state.verified_observation_epoch == 2


def test_agentic_action_cannot_bypass_side_effect_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_agentic_budget"
    before = _call(run_id, 1, "call_1", "ui_snapshot", {})
    action = _call(run_id, 2, "call_2", "click", {"ref": "ref_1"})
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, before), _turn(run_id, 2, action)])
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [_result(before, text='ref_1 | button "OK" | (1,1,10,10) | enabled')]
        )
    )
    approvals = DynamicApprovalPort()
    config = _config(
        tmp_path,
        monkeypatch,
        mode=AGENTIC_ACTIONS_MODE,
        max_side_effects=0,
    )

    with pytest.raises(RunFailure, match="SIDE_EFFECT_BUDGET_EXHAUSTED"):
        asyncio.run(
            AgentRunner(config, RunnerPorts(provider, desktop, approvals)).run(
                "Click OK", run_id=run_id
            )
        )

    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]
    assert approvals.requests == []


def test_provider_timeout_stops_before_any_desktop_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class HangingProvider(FakeModelProvider):
        async def create_turn(self, **_kwargs: object) -> ModelTurn:  # type: ignore[override]
            await asyncio.sleep(10)
            raise AssertionError("provider timeout did not cancel the request")

    config = replace(
        _config(tmp_path, monkeypatch, mode=AGENTIC_ACTIONS_MODE),
        provider=ProviderConfig(
            "openai",
            "fake",
            request_timeout_seconds=1,
        ),
    )
    desktop = FakeDesktopMCP()

    with pytest.raises(RunFailure, match="PROVIDER_TIMEOUT") as failed:
        asyncio.run(
            AgentRunner(
                config,
                RunnerPorts(HangingProvider(), desktop, DynamicApprovalPort()),
            ).run("Wait for a bounded provider", run_id="run_provider_timeout")
        )

    assert failed.value.state.budgets.model_turns_used == 0
    assert desktop.tool_calls == []
    assert read_run_record(config.state_dir, "run_provider_timeout")["state"][
        "failure_code"
    ] == "PROVIDER_TIMEOUT"


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
