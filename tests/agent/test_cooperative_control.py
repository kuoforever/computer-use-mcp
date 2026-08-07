from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
import json
from pathlib import Path
import pytest

from computer_use_agent.approvals import DecisionCardApprovalPort
import computer_use_agent.cli as agent_cli
from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    HIGH_RISK_ONLY_APPROVAL,
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.cooperative_control import (
    ControlBoundary,
    ControlOutcome,
    ControlRequest,
    ControlRequestKind,
    ControlStatus,
    CooperativeControlError,
    LocalCooperativeControl,
)
from computer_use_agent.decision_cards import DecisionSelection
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerError, RunnerPorts
from computer_use_agent.trace import RunPhase, RunRecorder, read_run_record
from computer_use_agent.types import (
    ActionRiskTier,
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    ModelTurn,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    RecoveryStatus,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "cooperative-test",
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
            max_model_turns=8,
            max_tool_calls=8,
            max_side_effects=2,
            max_context_events=128,
        ),
        continuation=ContinuationConfig(enabled=False),
    )


def _call(
    run_id: str, turn: int, call_id: str, name: str, arguments: dict[str, object]
) -> ToolCall:
    return ToolCall(CallIdentity(run_id, f"turn_{turn}", call_id), name, arguments)


def _turn(
    run_id: str, number: int, *calls: ToolCall, text: str = ""
) -> ModelTurn:
    return ModelTurn(
        run_id,
        f"turn_{number}",
        f"response_{number}",
        text,
        tuple(calls),
        ModelUsage(),
    )


def _result(
    call: ToolCall,
    *,
    text: str = "",
    status: ToolResultStatus = ToolResultStatus.SUCCESS,
    dispatch: DispatchCertainty = DispatchCertainty.DISPATCHED,
    code: str | None = None,
) -> ToolResult:
    return ToolResult(
        call.identity,
        call.name,
        status,
        dispatch,
        code=code,
        sanitized_text=text,
    )


@dataclass
class DynamicApproval:
    kind: PolicyDecisionKind = PolicyDecisionKind.ALLOW
    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision(
            request.request_id,
            request.identity,
            request.call_digest,
            self.kind,
            "test_operator",
        )


@dataclass
class AutoResumeControl:
    trigger_check: int | None = None
    trigger_kind: ControlRequestKind = ControlRequestKind.PAUSE
    status: ControlStatus = ControlStatus.ACTIVE
    request: ControlRequest | None = None
    pending_checks: int = 0
    paused: list[tuple[ControlBoundary, int]] = field(default_factory=list)
    fresh_observations: int = 0
    closed_outcome: ControlOutcome | None = None

    def start(
        self, run_id: str, *, owner_token: str, runner_state_dir: Path
    ) -> None:
        assert run_id
        assert owner_token
        assert runner_state_dir.is_absolute()

    def pending_request(self, run_id: str) -> ControlRequest | None:
        assert run_id
        self.pending_checks += 1
        if (
            self.trigger_check == self.pending_checks
            and self.status is ControlStatus.ACTIVE
        ):
            self.request = ControlRequest("external_request", self.trigger_kind)
            self.status = ControlStatus.PAUSE_REQUESTED
        if self.status is ControlStatus.PAUSE_REQUESTED:
            return self.request
        return None

    def request_from_runner(
        self, run_id: str, kind: ControlRequestKind
    ) -> ControlRequest:
        assert run_id
        assert self.status is ControlStatus.ACTIVE
        self.request = ControlRequest("card_takeover", kind)
        self.status = ControlStatus.PAUSE_REQUESTED
        return self.request

    def acknowledge_paused(
        self,
        run_id: str,
        request: ControlRequest,
        *,
        boundary: ControlBoundary,
        checkpoint_sequence: int,
    ) -> None:
        assert run_id
        assert request == self.request
        self.status = ControlStatus.PAUSED
        self.paused.append((boundary, checkpoint_sequence))

    async def wait_for_resume(self, run_id: str, request: ControlRequest) -> None:
        assert run_id
        assert request == self.request
        assert self.status is ControlStatus.PAUSED
        self.status = ControlStatus.RESUME_REQUESTED

    def acknowledge_resumed(self, run_id: str, request: ControlRequest) -> None:
        assert run_id
        assert request == self.request
        assert self.status is ControlStatus.RESUME_REQUESTED
        self.status = ControlStatus.RESUMING

    def acknowledge_fresh_observation(self, run_id: str) -> None:
        assert run_id
        if self.status is ControlStatus.RESUMING:
            self.fresh_observations += 1
            self.request = None
            self.status = ControlStatus.ACTIVE

    def close(self, run_id: str, outcome: ControlOutcome) -> None:
        assert run_id
        self.status = ControlStatus.CLOSED
        self.closed_outcome = outcome


@dataclass
class LowRiskClassifier:
    calls: list[ToolCall] = field(default_factory=list)

    def classify_action(
        self,
        call: ToolCall,
        ledger: Sequence[LedgerEvent],
    ) -> ActionRiskTier:
        assert ledger
        self.calls.append(call)
        return ActionRiskTier.LOW


def test_local_control_requires_live_owner_and_exact_paused_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    runner_control = LocalCooperativeControl(
        config.state_dir, config.application_state_dir, poll_seconds=0.01
    )
    operator_control = LocalCooperativeControl(
        config.state_dir, config.application_state_dir, poll_seconds=0.01
    )
    prepared = AgentRunner(config).prepare("Cooperative task", run_id="run_control")
    recorder = RunRecorder(config.state_dir, "run_control")
    state = prepared.state
    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING)
    recorder.record(state, RunPhase.PLANNING)
    runner_control.start(
        "run_control",
        owner_token=prepared.owner_token,
        runner_state_dir=config.state_dir,
    )

    requested = operator_control.request_pause(ControlRequestKind.TAKEOVER)
    assert requested.status is ControlStatus.PAUSE_REQUESTED
    # A successful observation that was already in flight does not consume or
    # fail a later pause request; the next safe boundary must acknowledge it.
    runner_control.acknowledge_fresh_observation("run_control")
    assert operator_control.inspect("run_control").status is ControlStatus.PAUSE_REQUESTED
    request = runner_control.pending_request("run_control")
    assert request is not None and request.kind is ControlRequestKind.TAKEOVER

    state = replace(
        state,
        recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
        verified_observation_epoch=None,
    )
    recorder.record(state, RunPhase.PAUSED)
    runner_control.acknowledge_paused(
        "run_control",
        request,
        boundary=ControlBoundary.BEFORE_PROVIDER,
        checkpoint_sequence=recorder.checkpoint_sequence,
    )
    paused = operator_control.inspect("run_control")
    assert paused.status is ControlStatus.PAUSED
    assert paused.authority.value == "released"
    assert paused.fresh_observation_required is True

    resume = operator_control.request_resume(run_id="run_control")
    assert resume.status is ControlStatus.RESUME_REQUESTED
    asyncio.run(runner_control.wait_for_resume("run_control", request))
    runner_control.acknowledge_resumed("run_control", request)
    assert operator_control.inspect("run_control").status is ControlStatus.RESUMING
    runner_control.acknowledge_fresh_observation("run_control")
    assert operator_control.inspect("run_control").status is ControlStatus.ACTIVE
    runner_control.close("run_control", ControlOutcome.SUCCESS)
    prepared.close()

    stale = AgentRunner(config).prepare("Stale task", run_id="run_stale_control")
    stale_control = LocalCooperativeControl(
        config.state_dir, config.application_state_dir
    )
    stale_recorder = RunRecorder(config.state_dir, "run_stale_control")
    stale_recorder.start(stale.state)
    stale_control.start(
        "run_stale_control",
        owner_token=stale.owner_token,
        runner_state_dir=config.state_dir,
    )
    stale.close()
    with pytest.raises(
        CooperativeControlError, match="COOPERATIVE_CONTROL_RUN_NOT_ACTIVE"
    ):
        operator_control.request_pause(
            ControlRequestKind.PAUSE, run_id="run_stale_control"
        )


def test_cli_controls_one_live_run_and_nested_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    base_config = _config(tmp_path, monkeypatch)
    nested_state = (
        base_config.state_dir
        / "workflows"
        / "public-web-word"
        / "workflow_1"
        / "reopen"
    )
    config = replace(base_config, state_dir=nested_state)
    prepared = AgentRunner(config).prepare("Nested verifier", run_id="run_nested")
    recorder = RunRecorder(config.state_dir, "run_nested")
    state = prepared.state
    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING)
    recorder.record(state, RunPhase.PLANNING)
    runner_control = LocalCooperativeControl(
        base_config.state_dir, config.application_state_dir, poll_seconds=0.01
    )
    runner_control.start(
        "run_nested",
        owner_token=prepared.owner_token,
        runner_state_dir=config.state_dir,
    )
    monkeypatch.setattr(agent_cli, "load_agent_config", lambda _path: base_config)

    assert (
        agent_cli.main(
            ["task", "takeover", "--config", str(tmp_path / "agent.toml"), "--json"]
        )
        == 0
    )
    requested = json.loads(capsys.readouterr().out)
    assert requested["status"] == "pause_requested"
    request = runner_control.pending_request("run_nested")
    assert request is not None
    state = replace(
        state,
        recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
        verified_observation_epoch=None,
    )
    recorder.record(state, RunPhase.PAUSED)
    runner_control.acknowledge_paused(
        "run_nested",
        request,
        boundary=ControlBoundary.BEFORE_PROVIDER,
        checkpoint_sequence=recorder.checkpoint_sequence,
    )

    assert (
        agent_cli.main(
            ["task", "resume", "--config", str(tmp_path / "agent.toml"), "--json"]
        )
        == 0
    )
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["status"] == "resume_requested"
    runner_control.close("run_nested", ControlOutcome.STOPPED)
    prepared.close()


def test_control_and_continuation_reject_before_any_external_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        continuation=ContinuationConfig(enabled=True),
    )
    provider = FakeModelProvider(turns=deque())
    desktop = FakeDesktopMCP(results=deque())

    with pytest.raises(
        RunnerError, match="COOPERATIVE_CONTROL_CONTINUATION_UNSUPPORTED"
    ):
        asyncio.run(
            AgentRunner(
                config,
                RunnerPorts(
                    provider,
                    desktop,
                    DynamicApproval(),
                    control=AutoResumeControl(),
                ),
            ).run("Unsupported combination", run_id="run_unsupported")
        )

    assert provider.calls == []
    assert desktop.discovery_calls == 0
    assert not (config.state_dir / "runs" / "run_unsupported").exists()


def test_pause_before_tool_rejects_stale_call_and_requires_fresh_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_pause_before_tool"
    stale = _call(run_id, 1, "call_stale", "list_windows", {})
    fresh = _call(run_id, 2, "call_fresh", "list_windows", {})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, stale),
                _turn(run_id, 2, fresh),
                _turn(run_id, 3, text="fresh result"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque([_result(fresh, text='* 42 | notepad.exe | "Note"')])
    )
    control = AutoResumeControl(trigger_check=2)

    outcome = asyncio.run(
        AgentRunner(
            _config(tmp_path, monkeypatch),
            RunnerPorts(provider, desktop, DynamicApproval(), control=control),
        ).run("Pause before observation", run_id=run_id)
    )

    assert outcome.text == "fresh result"
    assert [call.identity.call_id for call in desktop.tool_calls] == ["call_fresh"]
    assert control.paused and control.paused[0][0] is ControlBoundary.BEFORE_TOOL
    assert control.fresh_observations == 1
    assert control.closed_outcome is ControlOutcome.SUCCESS
    second_turn_tools = provider.calls[1]["tools"]
    assert second_turn_tools
    assert all(tool.effect is ToolEffect.OBSERVATION for tool in second_turn_tools)
    results = [
        event.tool_result
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
    ]
    assert any(
        result is not None
        and result.identity == stale.identity
        and result.code == "OPERATOR_PAUSED"
        and result.dispatch is DispatchCertainty.NOT_DISPATCHED
        for result in results
    )


def test_takeover_decision_uses_same_pause_path_without_action_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_card_takeover"
    before = _call(run_id, 1, "call_before", "list_windows", {})
    action = _call(run_id, 2, "call_action", "activate_window", {"window_id": "42"})
    refreshed = _call(run_id, 3, "call_refreshed", "list_windows", {})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, before),
                _turn(run_id, 2, action),
                _turn(run_id, 3, refreshed),
                _turn(run_id, 4, text="continued after takeover"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(before, text='* 42 | notepad.exe | "Note"'),
                _result(refreshed, text='* 42 | notepad.exe | "Note"'),
            ]
        )
    )
    control = AutoResumeControl()

    outcome = asyncio.run(
        AgentRunner(
            _config(tmp_path, monkeypatch),
            RunnerPorts(
                provider,
                desktop,
                DynamicApproval(PolicyDecisionKind.TAKEOVER),
                control=control,
            ),
        ).run("Take over before activation", run_id=run_id)
    )

    assert outcome.text == "continued after takeover"
    assert [call.identity.call_id for call in desktop.tool_calls] == [
        "call_before",
        "call_refreshed",
    ]
    assert control.paused[0][0] is ControlBoundary.AFTER_APPROVAL
    assert outcome.state.budgets.side_effects_used == 0
    decisions = [
        event.policy_decision
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.POLICY_DECISION
    ]
    assert decisions[-1] is not None
    assert decisions[-1].kind is PolicyDecisionKind.TAKEOVER
    assert any(
        event.tool_result is not None
        and event.tool_result.code == "OPERATOR_TAKEOVER"
        and event.tool_result.dispatch is DispatchCertainty.NOT_DISPATCHED
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
    )


def test_external_takeover_after_low_risk_authorization_requires_fresh_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_takeover_after_low_risk_authorization"
    before = _call(run_id, 1, "call_before", "ui_snapshot", {})
    stale_action = _call(run_id, 2, "call_stale", "click", {"ref": "ref_1"})
    refreshed = _call(run_id, 3, "call_refreshed", "ui_snapshot", {})
    fresh_action = _call(run_id, 4, "call_fresh", "click", {"ref": "ref_2"})
    verified = _call(run_id, 5, "call_verified", "ui_snapshot", {})
    provider = FakeModelProvider(
        turns=deque(
            [
                _turn(run_id, 1, before),
                _turn(run_id, 2, stale_action),
                _turn(run_id, 3, refreshed),
                _turn(run_id, 4, fresh_action),
                _turn(run_id, 5, verified),
                _turn(run_id, 6, text="fresh low-risk action verified"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(before, text='ref_1 | button "Old" | (1,1,10,10) | enabled'),
                _result(
                    refreshed,
                    text='ref_2 | button "Fresh" | (1,1,10,10) | enabled',
                ),
                _result(fresh_action),
                _result(
                    verified,
                    text='ref_3 | text "Done" | (1,1,10,10) | enabled',
                ),
            ]
        )
    )
    control = AutoResumeControl(
        trigger_check=5,
        trigger_kind=ControlRequestKind.TAKEOVER,
    )
    classifier = LowRiskClassifier()
    base_config = _config(tmp_path, monkeypatch)
    config = replace(
        base_config,
        policy=replace(
            base_config.policy,
            action_approval_policy=HIGH_RISK_ONLY_APPROVAL,
        ),
    )

    outcome = asyncio.run(
        AgentRunner(
            config,
            RunnerPorts(
                provider,
                desktop,
                DynamicApproval(),
                action_risk_classifier=classifier,
                control=control,
            ),
        ).run("Take over after Host authorization", run_id=run_id)
    )

    assert outcome.text == "fresh low-risk action verified"
    assert len(control.paused) == 1
    assert control.paused[0][0] is ControlBoundary.AFTER_AUTHORIZATION
    assert control.paused[0][1] > 0
    assert control.fresh_observations == 1
    assert control.closed_outcome is ControlOutcome.SUCCESS
    assert classifier.calls == [stale_action, fresh_action]
    assert [call.identity for call in desktop.tool_calls] == [
        before.identity,
        refreshed.identity,
        fresh_action.identity,
        verified.identity,
    ]
    assert outcome.state.budgets.side_effects_used == 1
    stale_results = [
        event.tool_result
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
        and event.tool_result is not None
        and event.tool_result.identity == stale_action.identity
    ]
    assert len(stale_results) == 1
    assert stale_results[0].code == "OPERATOR_TAKEOVER"
    assert stale_results[0].dispatch is DispatchCertainty.NOT_DISPATCHED


def test_unknown_side_effect_wins_over_late_pause_and_is_never_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_unknown_beats_pause"
    before = _call(run_id, 1, "call_before", "list_windows", {})
    action = _call(run_id, 2, "call_action", "activate_window", {"window_id": "42"})
    control = AutoResumeControl()

    class LatePauseDesktop(FakeDesktopMCP):
        async def call_tool(self, call: ToolCall) -> ToolResult:
            self.tool_calls.append(call)
            if call.identity == action.identity:
                control.request = ControlRequest(
                    "late_pause", ControlRequestKind.TAKEOVER
                )
                control.status = ControlStatus.PAUSE_REQUESTED
            if not self.results:
                raise AssertionError("missing fake result")
            return self.results.popleft()

    desktop = LatePauseDesktop(
        results=deque(
            [
                _result(before, text='* 42 | notepad.exe | "Note"'),
                _result(
                    action,
                    status=ToolResultStatus.UNKNOWN_OUTCOME,
                    dispatch=DispatchCertainty.UNKNOWN,
                    code="NATIVE_OUTCOME_UNKNOWN",
                ),
            ]
        )
    )
    provider = FakeModelProvider(
        turns=deque([_turn(run_id, 1, before), _turn(run_id, 2, action)])
    )

    with pytest.raises(RunFailure, match="^UNKNOWN_OUTCOME$"):
        asyncio.run(
            AgentRunner(
                _config(tmp_path, monkeypatch),
                RunnerPorts(provider, desktop, DynamicApproval(), control=control),
            ).run("Unknown action", run_id=run_id)
        )

    assert [call.identity.call_id for call in desktop.tool_calls] == [
        "call_before",
        "call_action",
    ]
    assert control.paused == []
    assert control.closed_outcome is ControlOutcome.UNKNOWN_OUTCOME
    assert read_run_record(_config(tmp_path, monkeypatch).state_dir, run_id)["state"][
        "phase"
    ] == "UNKNOWN_OUTCOME"


def test_takeover_enabled_decision_card_returns_distinct_bound_decision() -> None:
    call = ToolCall(
        CallIdentity("run_card", "turn_1", "call_1"),
        "activate_window",
        {"window_id": "42"},
    )
    request = ApprovalRequest.from_tool_call(
        request_id="approval_card",
        call=call,
        reason="side_effect_requires_local_approval",
        sensitive_arguments=(),
    )

    class Surface:
        cards = []

        async def choose(self, card, *, timeout_seconds: int):  # noqa: ANN001
            del timeout_seconds
            self.cards.append(card)
            return DecisionSelection(
                card.decision_id,
                card.card_digest,
                "option_human_takeover",
            )

    # A bound card is required; reuse the Runner-produced binding shape through
    # the existing test-safe immutable constructor.
    from computer_use_agent.types import ApprovalBinding

    request = replace(
        request,
        binding=ApprovalBinding(
            "run_card", *(f"{index:x}" * 64 for index in range(1, 7))
        ),
    )
    surface = Surface()
    decision = asyncio.run(
        DecisionCardApprovalPort(
            surface,
            takeover_enabled=True,
            clock=lambda: datetime(2026, 8, 7, tzinfo=UTC),
        ).request_approval(request)
    )

    assert decision.kind is PolicyDecisionKind.TAKEOVER
    assert decision.reason == "decision_card_human_takeover"
    assert [option.option_id for option in surface.cards[0].options] == [
        "option_approve_exact_effect",
        "option_reobserve",
        "option_human_takeover",
        "option_deny",
    ]
