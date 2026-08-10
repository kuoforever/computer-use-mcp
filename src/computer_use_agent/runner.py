"""Bounded provider-neutral Agent workflow for the local desktop bridge."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field, replace
from hashlib import sha256
from json import dumps
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping
from uuid import uuid4

from .campaign import CampaignStore
from .config import AgentConfig, HIGH_RISK_ONLY_APPROVAL
from .cooperative_control import (
    ControlBoundary,
    ControlOutcome,
    ControlRequest,
    ControlRequestKind,
    CooperativeControlError,
    CooperativeControlPort,
)
from .continuation import ContinuationError, RuntimeContinuationRecorder
from .context import ContextBudgetError, reduce_ledger
from .grounding import GroundingError, GroundingState
from .executor_final_store import FinalResponseStore
from .plan_store import TaskPlanStore
from .policy import HostPolicy, PolicyDisposition
from .privacy import PrivacyError, PrivacyImageRedactionPort, PrivacySession
from .presence_lifecycle import FailSilentLifecycle, PresenceLifecyclePort
from .run_lock import RunLock
from .telemetry import MAX_ATTRIBUTE_STRING_LENGTH, NoOpTelemetry, TelemetryPort
from .tool_registry import (
    ToolSpec,
    ToolValidationError,
    get_tool_spec,
    validate_tool_arguments,
    validate_tool_result,
    verify_discovered_tools,
    configured_optional_tool_names,
    reviewed_tools_with_optional,
    reviewed_registry_digest,
)
from .trace import RunPhase, RunRecorder, TraceError
from .tree_store import TaskTreeStore
from .types import (
    ApprovalPort,
    ApprovalBinding,
    ApprovalRequest,
    ActionRiskClassifierPort,
    ActionRiskTier,
    DesktopMCPPort,
    DispatchCertainty,
    FocusTakingApprovalPort,
    LedgerEvent,
    LedgerEventKind,
    MCPCallCancelled,
    MemoryContextItem,
    ModelProviderPort,
    ModelTurn,
    PolicyDecision,
    PolicyDecisionKind,
    RecoveryStatus,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


class RunnerError(RuntimeError):
    """A fixed workflow failure that does not embed task or desktop content."""


class RunnerBudgetError(RunnerError):
    """Raised when a model or tool-call hard bound is reached."""


class RunFailure(RunnerError):
    """A reviewed failure code plus the canonical state reached before stopping."""

    def __init__(self, code: str, state: RunState) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("failure code must be a non-empty string")
        if not isinstance(state, RunState):
            raise ValueError("state must be a RunState")
        super().__init__(code)
        self.code = code
        self.state = state


class RunDeferred(RunnerError):
    """A reviewed operator defer plus the canonical paused state."""

    code = "APPROVAL_DEFERRED"

    def __init__(self, state: RunState) -> None:
        if not isinstance(state, RunState):
            raise ValueError("state must be a RunState")
        super().__init__(self.code)
        self.state = state


@dataclass(frozen=True)
class RunOutcome:
    """Completed run output and its final in-memory audit state."""

    text: str
    state: RunState


@dataclass(frozen=True)
class _CallBoundaryOutcome:
    """State produced by the one authoritative host tool-call boundary."""

    state: RunState
    grounding: GroundingState
    result: ToolResult
    abandon_remaining_calls: bool = False


@dataclass(frozen=True)
class _CooperativeBoundaryOutcome:
    """State reached after one requested safe pause and explicit resume."""

    state: RunState
    grounding: GroundingState
    request: ControlRequest | None = None


@dataclass(frozen=True)
class RunnerPorts:
    """Injected external boundaries used by the bounded workflow."""

    provider: ModelProviderPort
    desktop: DesktopMCPPort
    approvals: ApprovalPort
    action_risk_classifier: ActionRiskClassifierPort | None = None
    image_redactor: PrivacyImageRedactionPort | None = None
    telemetry: TelemetryPort | None = None
    presence: PresenceLifecyclePort | None = None
    progress: PresenceLifecyclePort | None = None
    control: CooperativeControlPort | None = None


class _SafeSpan:
    """Wrap a span so telemetry can never propagate a failure into a run.

    Telemetry is observation only. An exporter or attribute error must not be
    able to change what a run does, so every call here is swallowed. Losing a
    span is acceptable; losing a checkpoint is not.
    """

    __slots__ = ("_span",)

    def __init__(self, span: object) -> None:
        self._span = span

    def set_attributes(self, attributes: Mapping[str, object]) -> None:
        try:
            self._span.set_attributes(attributes)  # type: ignore[attr-defined]
        except Exception:
            pass

    def record_error(self, code: str) -> None:
        try:
            self._span.record_error(code)  # type: ignore[attr-defined]
        except Exception:
            pass

    def end(self) -> None:
        try:
            self._span.end()  # type: ignore[attr-defined]
        except Exception:
            pass

    def __enter__(self) -> "_SafeSpan":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        self.end()
        return False


@dataclass
class PreparedRun:
    """An initial in-memory run state that owns one local run lock."""

    state: RunState
    _lock: RunLock = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def application_state_dir(self) -> Path:
        """Return the exact application root protected by this run lock."""

        return self._lock.lock_dir

    @property
    def owner_token(self) -> str:
        """Return the live run-lease token for digest binding only."""

        owner = self._lock.owner
        if self._closed or owner is None:
            raise RuntimeError("prepared run does not own a live lock")
        return owner.token

    def close(self) -> None:
        if self._closed:
            return
        self._lock.release()
        self._closed = True

    def __enter__(self) -> "PreparedRun":
        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return self

    def plan_store(self, state_dir: Path) -> TaskPlanStore:
        """Create a plan store bound to this run's still-live application lock."""

        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return TaskPlanStore(state_dir, self._lock)

    def final_response_store(self, state_dir: Path) -> FinalResponseStore:
        """Create a final-response WAL bound to this run's live lock."""

        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return FinalResponseStore(state_dir, self._lock)

    def campaign_store(self, state_dir: Path) -> CampaignStore:
        """Create a campaign store bound to this run's still-live lock."""

        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return CampaignStore(state_dir, self._lock)

    def tree_store(self, state_dir: Path) -> TaskTreeStore:
        """Create a tree store bound to this run's still-live application lock."""

        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return TaskTreeStore(state_dir, self._lock)

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


class AgentRunner:
    """Prepare and execute a bounded provider-neutral desktop workflow."""

    def __init__(self, config: AgentConfig, ports: RunnerPorts | None = None) -> None:
        if not isinstance(config, AgentConfig):
            raise ValueError("config must be an AgentConfig")
        if ports is not None and not isinstance(ports, RunnerPorts):
            raise ValueError("ports must be RunnerPorts or None")
        self.config = config
        self.ports = ports
        self.policy = HostPolicy.from_config(config.policy_version, config.policy)
        configured = ports.telemetry if ports is not None else None
        self.telemetry: TelemetryPort = configured or NoOpTelemetry()

    def _span(self, name: str, **attributes: object) -> _SafeSpan:
        """Start a span that cannot fail the run."""

        try:
            span = self.telemetry.start_span(name, attributes=attributes or None)
        except Exception:
            return _SafeSpan(NoOpTelemetry().start_span(name))
        return _SafeSpan(span)

    def prepare(
        self, task: str, *, run_id: str | None = None, recover_stale_lock: bool = False
    ) -> PreparedRun:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        resolved_run_id = run_id or uuid4().hex
        if not isinstance(resolved_run_id, str) or not resolved_run_id.strip():
            raise ValueError("run_id must be a non-empty string")

        state = RunState(
            run_id=resolved_run_id,
            task=task,
            policy_version=self.policy.version,
            observation_epoch=0,
            budgets=self.policy.initial_budget(),
            event_log=(
                LedgerEvent(
                    event_id=f"{resolved_run_id}:event:1",
                    kind=LedgerEventKind.USER_TASK,
                    payload={"task_length": len(task)},
                ),
            ),
        )
        lock = RunLock(self.config.application_state_dir)
        lock.acquire(recover_stale=recover_stale_lock)
        return PreparedRun(state=state, _lock=lock)

    @staticmethod
    def _event_id(state: RunState) -> str:
        return f"{state.run_id}:event:{len(state.event_log) + 1}"

    @staticmethod
    def _append(state: RunState, event: LedgerEvent, **changes: object) -> RunState:
        return replace(state, event_log=state.event_log + (event,), **changes)

    def _consume_model_turn(
        self, state: RunState, turn: ModelTurn, *, latency_ms: int
    ) -> RunState:
        if state.budgets.model_turns_used >= state.budgets.max_model_turns:
            raise RunnerBudgetError("MODEL_TURN_BUDGET_EXHAUSTED")
        budget = replace(
            state.budgets,
            model_turns_used=state.budgets.model_turns_used + 1,
            input_tokens_used=state.budgets.input_tokens_used
            + (turn.usage.input_tokens or 0),
        )
        return self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.MODEL_TURN,
                payload={
                    "provider_response_id": turn.provider_response_id,
                    "text_length": len(turn.text),
                    "tool_call_count": len(turn.tool_calls),
                    "input_tokens": turn.usage.input_tokens,
                    "output_tokens": turn.usage.output_tokens,
                    "latency_ms": latency_ms,
                },
            ),
            budgets=budget,
        )

    @staticmethod
    def _validated_tool_spec(call: ToolCall) -> ToolSpec:
        spec = get_tool_spec(call.name)
        normalized = validate_tool_arguments(call.name, call.arguments)
        if dict(call.arguments) != normalized:
            raise ToolValidationError("tool arguments are not in canonical form")
        return spec

    def _record_call(self, state: RunState, call: ToolCall) -> RunState:
        if state.budgets.tool_calls_used >= state.budgets.max_tool_calls:
            raise RunnerBudgetError("TOOL_CALL_BUDGET_EXHAUSTED")
        spec = self._validated_tool_spec(call)
        budget = replace(state.budgets, tool_calls_used=state.budgets.tool_calls_used + 1)
        return self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.TOOL_CALL,
                identity=call.identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=spec.sensitive_arguments
                ),
            ),
            budgets=budget,
        )

    def _record_result(
        self,
        state: RunState,
        result: ToolResult,
        *,
        effect: ToolEffect,
        latency_ms: int | None = None,
    ) -> RunState:
        observation_epoch = state.observation_epoch
        verified_epoch = state.verified_observation_epoch
        recovery_status = state.recovery_status
        if effect is ToolEffect.OBSERVATION and result.ok:
            observation_epoch += 1
            verified_epoch = observation_epoch
            recovery_status = RecoveryStatus.READY
        elif effect is ToolEffect.SIDE_EFFECT and result.dispatch is not DispatchCertainty.NOT_DISPATCHED:
            verified_epoch = None
            recovery_status = RecoveryStatus.REQUIRES_REOBSERVATION
        if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
            recovery_status = RecoveryStatus.UNKNOWN_OUTCOME
        payload = {} if latency_ms is None else {"latency_ms": latency_ms}
        state = self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.TOOL_RESULT,
                identity=result.identity,
                tool_result=result,
                payload=payload,
            ),
            observation_epoch=observation_epoch,
            verified_observation_epoch=verified_epoch,
            recovery_status=recovery_status,
        )
        if effect is ToolEffect.OBSERVATION and result.ok:
            state = self._append(
                state,
                LedgerEvent(
                    event_id=self._event_id(state),
                    kind=LedgerEventKind.OBSERVATION,
                    payload={
                        "tool_name": result.tool_name,
                        "observation_epoch": observation_epoch,
                    },
                    identity=result.identity,
                ),
            )
        return state

    def _record_pre_dispatch_continuation_failure(
        self,
        state: RunState,
        call: ToolCall,
        *,
        effect: ToolEffect,
    ) -> RunState:
        return self._record_result(
            state,
            ToolResult(
                identity=call.identity,
                tool_name=call.name,
                status=ToolResultStatus.REJECTED,
                dispatch=DispatchCertainty.NOT_DISPATCHED,
                code="CONTINUATION_WRITE_FAILED",
            ),
            effect=effect,
        )

    def _record_policy_decision(self, state: RunState, decision: PolicyDecision) -> RunState:
        return self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.POLICY_DECISION,
                identity=decision.identity,
                policy_decision=decision,
            ),
        )

    @staticmethod
    def _consume_side_effect(state: RunState) -> RunState:
        budget = state.budgets
        if budget.side_effects_used >= budget.max_side_effects:
            raise RunnerBudgetError("SIDE_EFFECT_BUDGET_EXHAUSTED")
        return replace(
            state,
            budgets=replace(budget, side_effects_used=budget.side_effects_used + 1),
        )

    def _preflight_post_action_verification_capacity(
        self,
        state: RunState,
        call: ToolCall,
    ) -> None:
        """Preflight one provider turn and observation call after a side effect."""

        budget = state.budgets
        if budget.model_turns_used >= budget.max_model_turns:
            raise RunnerBudgetError("MODEL_TURN_BUDGET_EXHAUSTED")
        if budget.input_tokens_used >= budget.max_input_tokens:
            raise RunnerBudgetError("INPUT_TOKEN_BUDGET_EXHAUSTED")

        # Build the exact immutable ledger topology that an allowed, dispatched
        # action would expose to the next provider call. This projection grants
        # no authority and is never assigned back to the real run state.
        projected_decision = PolicyDecision(
            request_id="verification-capacity-projection",
            identity=call.identity,
            call_digest=call.digest,
            kind=PolicyDecisionKind.ALLOW,
            reason="verification_capacity_projection",
        )
        projected_state = self._record_policy_decision(state, projected_decision)
        projected_state = self._record_result(
            projected_state,
            ToolResult(
                identity=call.identity,
                tool_name=call.name,
                status=ToolResultStatus.SUCCESS,
                dispatch=DispatchCertainty.DISPATCHED,
            ),
            effect=ToolEffect.SIDE_EFFECT,
        )
        reduce_ledger(
            projected_state.event_log,
            max_events=self.config.policy.max_context_events,
            run_id=state.run_id,
        )

        if budget.tool_calls_used >= budget.max_tool_calls:
            raise RunnerBudgetError("TOOL_CALL_BUDGET_EXHAUSTED")

    def _approval_binding(
        self, state: RunState, call: ToolCall, grounding: GroundingState
    ) -> ApprovalBinding:
        def digest(payload: object) -> str:
            encoded = dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            )
            return sha256(encoded.encode("utf-8")).hexdigest()

        budgets = state.budgets
        state_digest = digest(
            {
                "run_id": state.run_id,
                "observation_epoch": state.observation_epoch,
                "verified_observation_epoch": state.verified_observation_epoch,
                "recovery_status": state.recovery_status.value,
                "event_count": len(state.event_log),
                "last_event_id": (
                    None if not state.event_log else state.event_log[-1].event_id
                ),
                "budgets": {
                    "model_turns_used": budgets.model_turns_used,
                    "tool_calls_used": budgets.tool_calls_used,
                    "side_effects_used": budgets.side_effects_used,
                    "input_tokens_used": budgets.input_tokens_used,
                },
            }
        )
        evidence_digest = digest(
            {
                "generation": grounding.generation,
                "observation_epoch": grounding.observation_epoch,
                "refs": sorted(grounding.refs),
                "window_ids": sorted(grounding.window_ids),
                "screenshot_size": grounding.screenshot_size,
                "has_observation": grounding.has_observation,
            }
        )
        return ApprovalBinding(
            run_id=state.run_id,
            state_digest=state_digest,
            policy_digest=self.policy.digest,
            task_digest=digest({"task": state.task}),
            registry_digest=reviewed_registry_digest(
                configured_optional_tool_names(self.config.mcp.environment)
            ),
            object_digest=call.digest,
            evidence_digest=evidence_digest,
        )

    async def _cooperative_pause_boundary(
        self,
        state: RunState,
        grounding: GroundingState,
        *,
        recorder: RunRecorder,
        presence: FailSilentLifecycle,
        control: CooperativeControlPort | None,
        boundary: ControlBoundary,
    ) -> _CooperativeBoundaryOutcome:
        """Acknowledge one pause only after the current external call is over."""

        if control is None:
            return _CooperativeBoundaryOutcome(state, grounding)
        try:
            request = control.pending_request(state.run_id)
        except CooperativeControlError as exc:
            raise RunFailure("COOPERATIVE_CONTROL_FAILED", state) from exc
        if request is None:
            return _CooperativeBoundaryOutcome(state, grounding)

        paused_state = replace(
            state,
            verified_observation_epoch=None,
            recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
        )
        paused_grounding = grounding.invalidate()
        recorder.record(paused_state, RunPhase.PAUSED)
        # The durable paused checkpoint is published before the control record
        # can claim that desktop authority has been released.
        presence.yield_authority()
        try:
            control.acknowledge_paused(
                paused_state.run_id,
                request,
                boundary=boundary,
                checkpoint_sequence=recorder.checkpoint_sequence,
            )
            await control.wait_for_resume(paused_state.run_id, request)
            control.acknowledge_resumed(paused_state.run_id, request)
        except CooperativeControlError as exc:
            raise RunFailure("COOPERATIVE_CONTROL_FAILED", paused_state) from exc
        # Resume never restores the old grounding.  OBSERVING is a requirement,
        # not a claim that a fresh observation has already succeeded.
        recorder.record(paused_state, RunPhase.OBSERVING)
        return _CooperativeBoundaryOutcome(
            paused_state,
            paused_grounding,
            request,
        )

    def _paused_call_outcome(
        self,
        state: RunState,
        grounding: GroundingState,
        call: ToolCall,
        request: ControlRequest,
        *,
        effect: ToolEffect,
        recorder: RunRecorder,
    ) -> _CallBoundaryOutcome:
        """Reject the stale pre-pause call without dispatch or side-effect charge."""

        code = (
            "OPERATOR_TAKEOVER"
            if request.kind is ControlRequestKind.TAKEOVER
            else "OPERATOR_PAUSED"
        )
        result = ToolResult(
            identity=call.identity,
            tool_name=call.name,
            status=ToolResultStatus.REJECTED,
            dispatch=DispatchCertainty.NOT_DISPATCHED,
            code=code,
        )
        state = self._record_result(state, result, effect=effect)
        recorder.record(state, RunPhase.PLANNING)
        return _CallBoundaryOutcome(
            state=state,
            grounding=grounding,
            result=result,
            abandon_remaining_calls=True,
        )

    async def _execute_requested_call_boundary(
        self,
        state: RunState,
        call: ToolCall,
        *,
        grounding: GroundingState,
        recorder: RunRecorder,
        continuation: RuntimeContinuationRecorder | None,
        presence: FailSilentLifecycle | None = None,
        progress: FailSilentLifecycle | None = None,
        control: CooperativeControlPort | None = None,
        privacy: PrivacySession | None = None,
    ) -> _CallBoundaryOutcome:
        """Run one fresh requested call through every ordinary host boundary.

        This is the sole Runner path from a normalized request to MCP dispatch.
        A future plan Executor may reuse it, but plan data cannot skip or alter
        any policy, grounding, budget, approval, write-ahead, result, or
        verification behavior implemented here.
        """

        if self.ports is None:
            raise RunnerError("RUNNER_PORTS_REQUIRED")
        safe_presence = presence or FailSilentLifecycle(None)
        safe_progress = progress or FailSilentLifecycle(None)
        try:
            if privacy is not None:
                privacy.validate_tool_call(call)
                if (
                    privacy.config.enabled
                    and get_tool_spec(call.name).returns_image
                    and self.ports.image_redactor is None
                ):
                    raise PrivacyError("PRIVACY_IMAGE_REDACTOR_UNAVAILABLE")
            state = self._record_call(state, call)
        except PrivacyError as exc:
            raise RunFailure(str(exc), state) from exc
        except RunnerBudgetError as exc:
            raise RunFailure(str(exc), state) from exc
        except ToolValidationError as exc:
            raise RunFailure("SCHEMA_MISMATCH", state) from exc
        spec = get_tool_spec(call.name)
        pause = await self._cooperative_pause_boundary(
            state,
            grounding,
            recorder=recorder,
            presence=safe_presence,
            control=control,
            boundary=ControlBoundary.BEFORE_TOOL,
        )
        state = pause.state
        grounding = pause.grounding
        if pause.request is not None:
            return self._paused_call_outcome(
                state,
                grounding,
                call,
                pause.request,
                effect=spec.effect,
                recorder=recorder,
            )
        action_risk: ActionRiskTier | None = None
        if (
            spec.effect is ToolEffect.SIDE_EFFECT
            and self.config.policy.action_approval_policy
            == HIGH_RISK_ONLY_APPROVAL
        ):
            classifier = self.ports.action_risk_classifier
            if classifier is not None:
                try:
                    candidate_risk = classifier.classify_action(call, state.event_log)
                except Exception:
                    candidate_risk = ActionRiskTier.UNKNOWN
                if isinstance(candidate_risk, ActionRiskTier):
                    action_risk = candidate_risk
            if action_risk is None:
                action_risk = ActionRiskTier.UNKNOWN
        disposition = self.policy.disposition(
            spec,
            satisfied_safety_baselines=(
                self.ports.desktop.satisfied_safety_baselines
            ),
            action_risk=action_risk,
        )
        if disposition is PolicyDisposition.DENY:
            denied = ToolResult(
                identity=call.identity,
                tool_name=call.name,
                status=ToolResultStatus.REJECTED,
                dispatch=DispatchCertainty.NOT_DISPATCHED,
                code="POLICY_DENIED",
            )
            state = self._record_result(state, denied, effect=spec.effect)
            raise RunFailure("POLICY_DENIED", state)
        if (
            disposition is PolicyDisposition.ALLOW
            and spec.effect is ToolEffect.SIDE_EFFECT
        ):
            if state.recovery_status is RecoveryStatus.REQUIRES_REOBSERVATION:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure("REOBSERVATION_REQUIRED", state)
            try:
                grounding.validate(
                    call,
                    spec,
                    generation=self.ports.desktop.generation,
                )
                if state.budgets.side_effects_used >= state.budgets.max_side_effects:
                    raise RunnerBudgetError("SIDE_EFFECT_BUDGET_EXHAUSTED")
                self._preflight_post_action_verification_capacity(state, call)
            except GroundingError as exc:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure(str(exc), state) from exc
            except (ContextBudgetError, RunnerBudgetError) as exc:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="BUDGET_EXHAUSTED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure(str(exc), state) from exc
            state = self._record_policy_decision(
                state,
                PolicyDecision(
                    request_id=f"host-policy-{uuid4().hex}",
                    identity=call.identity,
                    call_digest=call.digest,
                    kind=PolicyDecisionKind.ALLOW,
                    reason="host_low_risk_policy",
                ),
            )
            pause = await self._cooperative_pause_boundary(
                state,
                grounding,
                recorder=recorder,
                presence=safe_presence,
                control=control,
                boundary=ControlBoundary.AFTER_AUTHORIZATION,
            )
            state = pause.state
            grounding = pause.grounding
            if pause.request is not None:
                return self._paused_call_outcome(
                    state,
                    grounding,
                    call,
                    pause.request,
                    effect=spec.effect,
                    recorder=recorder,
                )
            try:
                grounding.validate(
                    call,
                    spec,
                    generation=self.ports.desktop.generation,
                )
            except GroundingError as exc:
                rejected = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, rejected, effect=spec.effect)
                raise RunFailure(str(exc), state) from exc
            if not set(spec.required_safety_baselines).issubset(
                self.ports.desktop.satisfied_safety_baselines
            ):
                rejected = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, rejected, effect=spec.effect)
                raise RunFailure("SAFETY_BASELINE_UNSATISFIED", state)
            state = self._consume_side_effect(state)
        if disposition is PolicyDisposition.APPROVAL_REQUIRED:
            if state.recovery_status is RecoveryStatus.REQUIRES_REOBSERVATION:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure("REOBSERVATION_REQUIRED", state)
            try:
                grounding.validate(
                    call,
                    spec,
                    generation=self.ports.desktop.generation,
                )
                if state.budgets.side_effects_used >= state.budgets.max_side_effects:
                    raise RunnerBudgetError("SIDE_EFFECT_BUDGET_EXHAUSTED")
                self._preflight_post_action_verification_capacity(state, call)
            except GroundingError as exc:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure(str(exc), state) from exc
            except (ContextBudgetError, RunnerBudgetError) as exc:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="BUDGET_EXHAUSTED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure(str(exc), state) from exc

            request = ApprovalRequest.from_tool_call(
                request_id=uuid4().hex,
                call=call,
                reason="side_effect_requires_local_approval",
                sensitive_arguments=spec.sensitive_arguments,
                binding=self._approval_binding(state, call, grounding),
            )
            recorder.record(state, RunPhase.WAITING_APPROVAL)
            if isinstance(self.ports.approvals, FocusTakingApprovalPort):
                if self.ports.approvals.focus_taking:
                    # Yield the desktop before the card appears, but do not end
                    # the surface. Releasing here latched the presence
                    # lifecycle, so the halo vanished at the first approval and
                    # never came back for the rest of the run.
                    safe_presence.yield_authority()
            decision = await self.ports.approvals.request_approval(request)
            if not request.matches(decision) or decision.kind not in {
                PolicyDecisionKind.ALLOW,
                PolicyDecisionKind.DENY,
                PolicyDecisionKind.REOBSERVE,
                PolicyDecisionKind.DEFER,
                PolicyDecisionKind.TAKEOVER,
            }:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="APPROVAL_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure("APPROVAL_MISMATCH", state)
            if request.binding != self._approval_binding(state, call, grounding):
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="APPROVAL_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure("APPROVAL_MISMATCH", state)
            state = self._record_policy_decision(state, decision)
            recorder.record(state, RunPhase.WAITING_APPROVAL)
            if decision.kind is PolicyDecisionKind.DENY:
                denied = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="APPROVAL_DENIED",
                )
                state = self._record_result(state, denied, effect=spec.effect)
                raise RunFailure("APPROVAL_DENIED", state)
            if decision.kind is PolicyDecisionKind.REOBSERVE:
                rejected = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="APPROVAL_REOBSERVE_REQUIRED",
                )
                state = self._record_result(state, rejected, effect=spec.effect)
                state = replace(
                    state,
                    verified_observation_epoch=None,
                    recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
                )
                grounding = grounding.invalidate()
                recorder.record(state, RunPhase.PLANNING)
                return _CallBoundaryOutcome(
                    state=state,
                    grounding=grounding,
                    result=rejected,
                    abandon_remaining_calls=True,
                )
            if decision.kind is PolicyDecisionKind.DEFER:
                rejected = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="APPROVAL_DEFERRED",
                )
                state = self._record_result(state, rejected, effect=spec.effect)
                state = replace(state, recovery_status=RecoveryStatus.STOPPED)
                raise RunDeferred(state)
            if decision.kind is PolicyDecisionKind.TAKEOVER:
                if control is None:
                    rejected = ToolResult(
                        identity=call.identity,
                        tool_name=call.name,
                        status=ToolResultStatus.REJECTED,
                        dispatch=DispatchCertainty.NOT_DISPATCHED,
                        code="OPERATOR_TAKEOVER",
                    )
                    state = self._record_result(state, rejected, effect=spec.effect)
                    raise RunFailure("COOPERATIVE_CONTROL_UNAVAILABLE", state)
                try:
                    takeover = control.request_from_runner(
                        state.run_id, ControlRequestKind.TAKEOVER
                    )
                except CooperativeControlError as exc:
                    raise RunFailure("COOPERATIVE_CONTROL_FAILED", state) from exc
                pause = await self._cooperative_pause_boundary(
                    state,
                    grounding,
                    recorder=recorder,
                    presence=safe_presence,
                    control=control,
                    boundary=ControlBoundary.AFTER_APPROVAL,
                )
                if pause.request != takeover:
                    raise RunFailure("COOPERATIVE_CONTROL_FAILED", pause.state)
                return self._paused_call_outcome(
                    pause.state,
                    pause.grounding,
                    call,
                    takeover,
                    effect=spec.effect,
                    recorder=recorder,
                )
            pause = await self._cooperative_pause_boundary(
                state,
                grounding,
                recorder=recorder,
                presence=safe_presence,
                control=control,
                boundary=ControlBoundary.AFTER_APPROVAL,
            )
            state = pause.state
            grounding = pause.grounding
            if pause.request is not None:
                return self._paused_call_outcome(
                    state,
                    grounding,
                    call,
                    pause.request,
                    effect=spec.effect,
                    recorder=recorder,
                )
            # A correlated ALLOW remains useful audit evidence, but the card wait
            # grants no lease over MCP facts. Re-read them before any side-effect
            # charge, action continuation intent, or desktop dispatch can exist.
            try:
                grounding.validate(
                    call,
                    spec,
                    generation=self.ports.desktop.generation,
                )
            except GroundingError as exc:
                rejected = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, rejected, effect=spec.effect)
                raise RunFailure(str(exc), state) from exc
            if not set(spec.required_safety_baselines).issubset(
                self.ports.desktop.satisfied_safety_baselines
            ):
                rejected = ToolResult(
                    identity=call.identity,
                    tool_name=call.name,
                    status=ToolResultStatus.REJECTED,
                    dispatch=DispatchCertainty.NOT_DISPATCHED,
                    code="POLICY_DENIED",
                )
                state = self._record_result(state, rejected, effect=spec.effect)
                raise RunFailure("SAFETY_BASELINE_UNSATISFIED", state)
            state = self._consume_side_effect(state)

        recorder.record(state, RunPhase.EXECUTING)
        authorized_call = replace(call, status=ToolCallStatus.AUTHORIZED)
        tool_started_ns = perf_counter_ns()
        if continuation is not None:
            recorder.record(state, recorder.phase, advance_checkpoint_sequence=True)
            try:
                continuation.prepare_tool(
                    state,
                    authorized_call,
                    effect=spec.effect,
                    checkpoint_sequence=recorder.checkpoint_sequence,
                )
            except ContinuationError as exc:
                state = self._record_pre_dispatch_continuation_failure(
                    state, call, effect=spec.effect
                )
                raise RunFailure("CONTINUATION_WRITE_FAILED", state) from exc
            recorder.record(state, recorder.phase, advance_checkpoint_sequence=True)
            try:
                continuation.dispatch_tool(
                    state, checkpoint_sequence=recorder.checkpoint_sequence
                )
            except ContinuationError as exc:
                state = self._record_pre_dispatch_continuation_failure(
                    state, call, effect=spec.effect
                )
                raise RunFailure("CONTINUATION_WRITE_FAILED", state) from exc
        post_dispatch_cancellation: MCPCallCancelled | None = None
        try:
            dispatch_call = (
                authorized_call
                if privacy is None
                else privacy.resolve_local_call(authorized_call)
            )
            try:
                result = await self.ports.desktop.call_tool(dispatch_call)
            except MCPCallCancelled as cancelled:
                post_dispatch_cancellation = cancelled
                result = cancelled.result
                if result.status is not ToolResultStatus.UNKNOWN_OUTCOME:
                    raise ToolValidationError(
                        "post-dispatch cancellation requires an unknown result"
                    )
            validate_tool_result(dispatch_call, result)
            if privacy is not None:
                result = privacy.protect_result(result)
                if privacy.config.enabled and result.images:
                    if self.ports.image_redactor is None:
                        raise PrivacyError("PRIVACY_IMAGE_REDACTOR_UNAVAILABLE")
                    result = await self.ports.image_redactor.redact(result, privacy)
            validate_tool_result(authorized_call, result)
        except asyncio.CancelledError:
            raise
        except PrivacyError as exc:
            raise RunFailure(str(exc), state) from exc
        except Exception as exc:
            raise RunFailure("UNKNOWN_OUTCOME", state) from exc
        state = self._record_result(
            state,
            result,
            effect=spec.effect,
            latency_ms=max(0, (perf_counter_ns() - tool_started_ns) // 1_000_000),
        )
        if (
            spec.effect is ToolEffect.SIDE_EFFECT
            and result.status is ToolResultStatus.REJECTED
            and result.dispatch is DispatchCertainty.NOT_DISPATCHED
            and result.code in {"DENIED_BY_GATE", "HUMAN_ACTIVE"}
        ):
            state = replace(
                state,
                verified_observation_epoch=None,
                recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
            )
            grounding = grounding.invalidate()
        if result.code == "ABORTED":
            safe_presence.estop()
            safe_progress.estop()
        elif result.code == "HUMAN_ACTIVE":
            safe_presence.release()
        continuation_failure: Exception | None = None
        if continuation is not None:
            try:
                recorder.record(state, recorder.phase, advance_checkpoint_sequence=True)
                continuation.complete_tool(
                    state, result, checkpoint_sequence=recorder.checkpoint_sequence
                )
            except Exception as exc:
                if post_dispatch_cancellation is not None:
                    continuation_failure = exc
                elif result.status is ToolResultStatus.UNKNOWN_OUTCOME:
                    raise RunFailure("UNKNOWN_OUTCOME", state) from exc
                else:
                    raise
        if post_dispatch_cancellation is not None:
            try:
                recorder.record(
                    state,
                    RunPhase.UNKNOWN_OUTCOME,
                    failure_code="UNKNOWN_OUTCOME",
                )
            except Exception as exc:
                raise MCPCallCancelled(result) from exc
            if continuation_failure is not None:
                raise MCPCallCancelled(result) from continuation_failure
            raise MCPCallCancelled(result) from None
        if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
            raise RunFailure("UNKNOWN_OUTCOME", state)
        if spec.effect is ToolEffect.OBSERVATION and result.ok:
            grounding = grounding.observe(
                result,
                generation=self.ports.desktop.generation,
                epoch=state.observation_epoch,
            )
            recorder.record(state, RunPhase.OBSERVING)
            if control is not None:
                try:
                    control.acknowledge_fresh_observation(state.run_id)
                except CooperativeControlError as exc:
                    raise RunFailure("COOPERATIVE_CONTROL_FAILED", state) from exc
        elif (
            spec.effect is ToolEffect.SIDE_EFFECT
            and result.dispatch is not DispatchCertainty.NOT_DISPATCHED
        ):
            grounding = grounding.invalidate()
            recorder.record(state, RunPhase.VERIFYING)
        recorder.record(state, RunPhase.PLANNING)
        return _CallBoundaryOutcome(state=state, grounding=grounding, result=result)

    async def run(
        self,
        task: str,
        *,
        run_id: str | None = None,
        memories: tuple[MemoryContextItem, ...] = (),
        resume_initial: bool = False,
        allowed_tool_names: frozenset[str] | None = None,
    ) -> RunOutcome:
        """Run a bounded model/tool loop and release lock and desktop."""

        if self.ports is None:
            raise RunnerError("RUNNER_PORTS_REQUIRED")
        if self.ports.control is not None and self.config.continuation.enabled:
            raise RunnerError("COOPERATIVE_CONTROL_CONTINUATION_UNSUPPORTED")
        optional_tool_names = configured_optional_tool_names(
            self.config.mcp.environment
        )
        runtime_tools = reviewed_tools_with_optional(optional_tool_names)
        reviewed_tool_names = frozenset(tool.name for tool in runtime_tools)
        if (
            allowed_tool_names is not None
            and (
                not isinstance(allowed_tool_names, frozenset)
                or any(
                    not isinstance(name, str) or name not in reviewed_tool_names
                    for name in allowed_tool_names
                )
            )
        ):
            raise ValueError(
                "allowed_tool_names must be a frozenset of reviewed tool names or None"
            )
        if not isinstance(memories, tuple) or not all(
            isinstance(item, MemoryContextItem) for item in memories
        ):
            raise ValueError("memories must be a tuple of MemoryContextItem")
        if memories:
            from .memory import MAX_RUN_MEMORIES, MAX_RUN_MEMORY_CHARS

            if len(memories) > MAX_RUN_MEMORIES or sum(
                len(item.content) for item in memories
            ) > MAX_RUN_MEMORY_CHARS:
                raise RunnerError("MEMORY_CONTEXT_LIMIT_EXCEEDED")
        if resume_initial and run_id is None:
            raise ValueError("resume_initial requires run_id")
        resolved_run_id = run_id or uuid4().hex
        privacy = (
            PrivacySession(self.config.privacy, resolved_run_id)
            if self.config.privacy.enabled
            else None
        )
        protected_task = task
        if privacy is not None:
            try:
                protected_task = privacy.protect_task(task)
                memories = privacy.protect_memories(memories)
            except PrivacyError as exc:
                raise RunnerError(str(exc)) from exc
        prepared = self.prepare(
            protected_task,
            run_id=resolved_run_id,
            recover_stale_lock=resume_initial,
        )
        state = prepared.state
        provider_tools = tuple(
            tool
            for tool in runtime_tools
            if allowed_tool_names is None or tool.name in allowed_tool_names
            if bool(getattr(self.ports.provider, "supports_images", True))
            or not tool.returns_image
            if not self.config.privacy.enabled
            or not tool.returns_image
            or (
                self.config.privacy.image_redaction
                and self.ports is not None
                and self.ports.image_redactor is not None
            )
        )
        grounding = GroundingState()
        presence = FailSilentLifecycle(self.ports.presence)
        progress = FailSilentLifecycle(self.ports.progress)
        control = self.ports.control

        def publish_operator_phase(phase: RunPhase) -> None:
            presence.on_phase(phase)
            progress.on_phase(phase)

        recorder = RunRecorder(
            self.config.state_dir,
            state.run_id,
            phase_observer=publish_operator_phase,
        )
        run_started_ns = perf_counter_ns()
        recorder_started = False
        control_started = False
        desktop_closed = False
        continuation: RuntimeContinuationRecorder | None = None
        # Read defensively: telemetry observes injected ports and must never be
        # the reason a run fails, even against a port that omits an optional
        # protocol attribute.
        run_span = self._span(
            "agent.run",
            **{
                "run.phase": "running",
                "run.resumed": bool(resume_initial),
                "provider.name": str(getattr(self.ports.provider, "name", "unknown"))[
                    :MAX_ATTRIBUTE_STRING_LENGTH
                ],
            },
        )
        try:
            if resume_initial:
                recorder.attach_initial(state)
            else:
                recorder.start(state)
            recorder_started = True
            if control is not None:
                try:
                    control.start(
                        state.run_id,
                        owner_token=prepared.owner_token,
                        runner_state_dir=self.config.state_dir,
                    )
                    control_started = True
                except CooperativeControlError as exc:
                    raise RunFailure("COOPERATIVE_CONTROL_FAILED", state) from exc
            recorder.record(state, RunPhase.OBSERVING)
            discovered = await self.ports.desktop.discover_tools()
            verify_discovered_tools(discovered, optional_tool_names)
            provider_tools = tuple(
                tool
                for tool in provider_tools
                if set(tool.required_safety_baselines).issubset(
                    self.ports.desktop.satisfied_safety_baselines
                )
                # Continuation v6 intentionally rejects raw typed text. Do not
                # advertise an action whose provider completion cannot satisfy
                # that persistence contract.
                if not self.config.continuation.enabled or tool.name != "type"
            )
            advertised_tool_names = frozenset(tool.name for tool in provider_tools)
            if self.config.continuation.enabled:
                continuation = RuntimeContinuationRecorder(
                    state_dir=self.config.state_dir,
                    state=state,
                    provider_name=self.config.provider.name,
                    provider_model=self.config.provider.model,
                    provider_region=self.config.provider.effective_region,
                    provider_base_url=self.config.provider.effective_base_url,
                    registry_digest=reviewed_registry_digest(optional_tool_names),
                    advertised_tool_names=advertised_tool_names,
                    ttl_seconds=self.config.continuation.ttl_seconds,
                    mcp_generation=self.ports.desktop.generation,
                )
            recorder.record(state, RunPhase.PLANNING)
            turn_index = 0
            while True:
                pause = await self._cooperative_pause_boundary(
                    state,
                    grounding,
                    recorder=recorder,
                    presence=presence,
                    control=control,
                    boundary=ControlBoundary.BEFORE_PROVIDER,
                )
                state = pause.state
                grounding = pause.grounding
                if pause.request is not None:
                    recorder.record(state, RunPhase.PLANNING)
                if state.budgets.model_turns_used >= state.budgets.max_model_turns:
                    raise RunFailure("MODEL_TURN_BUDGET_EXHAUSTED", state)
                if state.budgets.input_tokens_used >= state.budgets.max_input_tokens:
                    raise RunFailure("INPUT_TOKEN_BUDGET_EXHAUSTED", state)
                turn_index += 1
                turn_id = f"turn_{turn_index}"
                try:
                    provider_ledger = reduce_ledger(
                        state.event_log,
                        max_events=self.config.policy.max_context_events,
                        run_id=state.run_id,
                    )
                except ContextBudgetError as exc:
                    raise RunFailure(str(exc), state) from exc
                provider_started_ns = perf_counter_ns()
                turn_tools = provider_tools
                if (
                    control is not None
                    and state.recovery_status is RecoveryStatus.REQUIRES_REOBSERVATION
                ):
                    turn_tools = tuple(
                        tool
                        for tool in provider_tools
                        if tool.effect is ToolEffect.OBSERVATION
                    )
                turn_advertised_tool_names = frozenset(
                    tool.name for tool in turn_tools
                )
                if continuation is not None:
                    recorder.record(
                        state, recorder.phase, advance_checkpoint_sequence=True
                    )
                    continuation.prepare_provider(
                        state, turn_id, checkpoint_sequence=recorder.checkpoint_sequence
                    )
                    recorder.record(
                        state, recorder.phase, advance_checkpoint_sequence=True
                    )
                    continuation.dispatch_provider(
                        state, checkpoint_sequence=recorder.checkpoint_sequence
                    )
                try:
                    async with asyncio.timeout(
                        self.config.provider.request_timeout_seconds
                    ):
                        turn = await self.ports.provider.create_turn(
                            run_id=state.run_id,
                            turn_id=turn_id,
                            task=state.task,
                            ledger=provider_ledger,
                            tools=turn_tools,
                            memories=memories,
                        )
                except TimeoutError as exc:
                    raise RunFailure("PROVIDER_TIMEOUT", state) from exc
                if turn.run_id != state.run_id or turn.turn_id != turn_id:
                    raise RunFailure("PROVIDER_TURN_IDENTITY_MISMATCH", state)
                if any(
                    call.name not in turn_advertised_tool_names
                    for call in turn.tool_calls
                ):
                    raise RunFailure("PROVIDER_TOOL_NOT_ADVERTISED", state)
                try:
                    returned_specs = tuple(
                        self._validated_tool_spec(call) for call in turn.tool_calls
                    )
                except ToolValidationError as exc:
                    raise RunFailure("SCHEMA_MISMATCH", state) from exc
                if len(turn.tool_calls) > 1 and any(
                    spec.effect is ToolEffect.SIDE_EFFECT for spec in returned_specs
                ):
                    raise RunFailure("PROVIDER_SIDE_EFFECT_TURN_NOT_SERIAL", state)
                if privacy is not None:
                    try:
                        privacy.validate_model_text(turn.text)
                        for call in turn.tool_calls:
                            privacy.validate_tool_call(call)
                    except PrivacyError as exc:
                        raise RunFailure(str(exc), state) from exc
                state = self._consume_model_turn(
                    state,
                    turn,
                    latency_ms=max(0, (perf_counter_ns() - provider_started_ns) // 1_000_000),
                )
                if continuation is not None:
                    recorder.record(
                        state, recorder.phase, advance_checkpoint_sequence=True
                    )
                    continuation.complete_provider(
                        state,
                        turn,
                        provider_state=self.ports.provider.export_continuation(
                            state.run_id
                        ),
                        checkpoint_sequence=recorder.checkpoint_sequence,
                    )
                recorder.record(state, RunPhase.PLANNING)
                if not turn.tool_calls:
                    if state.recovery_status is RecoveryStatus.REQUIRES_REOBSERVATION:
                        raise RunFailure("VERIFICATION_REQUIRED", state)
                    final_text = turn.text
                    if privacy is not None:
                        try:
                            final_text = privacy.restore_text(turn.text)
                        except PrivacyError as exc:
                            raise RunFailure(str(exc), state) from exc
                    await self.ports.desktop.close()
                    desktop_closed = True
                    recorder.record(
                        state,
                        RunPhase.SUCCESS,
                        final_text_length=len(final_text),
                        run_duration_ms=max(
                            0, (perf_counter_ns() - run_started_ns) // 1_000_000
                        ),
                    )
                    return RunOutcome(text=final_text, state=state)

                for call in turn.tool_calls:
                    # Observed from the call site on purpose. The authoritative
                    # boundary below stays one auditable function; telemetry
                    # must not reshape the path it observes.
                    boundary_started_ns = perf_counter_ns()
                    with self._span("tool.boundary", **{"tool.name": call.name}) as span:
                        try:
                            outcome = await self._execute_requested_call_boundary(
                                state,
                                call,
                                grounding=grounding,
                                recorder=recorder,
                                continuation=continuation,
                                presence=presence,
                                progress=progress,
                                control=control,
                                privacy=privacy,
                            )
                        except RunFailure as failure:
                            span.record_error(failure.code)
                            raise
                        finally:
                            span.set_attributes(
                                {
                                    "duration.ms": max(
                                        0,
                                        (perf_counter_ns() - boundary_started_ns)
                                        // 1_000_000,
                                    )
                                }
                            )
                        span.set_attributes(
                            {
                                "tool.effect": get_tool_spec(call.name).effect.value,
                                "result.status": outcome.result.status.value,
                                "dispatch.certainty": outcome.result.dispatch.value,
                            }
                        )
                        if outcome.result.code is not None:
                            span.set_attributes({"result.code": outcome.result.code})
                    state = outcome.state
                    grounding = outcome.grounding
                    if call.name == "browser_snapshot" and not outcome.result.ok:
                        # A configured browser helper is optional observation,
                        # never a reason to spin on one unavailable CDP path.
                        # Later provider turns must choose a desktop source.
                        provider_tools = tuple(
                            tool
                            for tool in provider_tools
                            if tool.name != "browser_snapshot"
                        )
                    if outcome.abandon_remaining_calls:
                        break
        except asyncio.CancelledError as cancelled:
            if (
                recorder_started
                and not isinstance(cancelled, MCPCallCancelled)
                and recorder.phase is not RunPhase.UNKNOWN_OUTCOME
            ):
                recorder.record(
                    state,
                    RunPhase.CANCELLED,
                    failure_code="CANCELLED",
                    run_duration_ms=max(0, (perf_counter_ns() - run_started_ns) // 1_000_000),
                )
            raise
        except RunFailure as failure:
            if recorder_started:
                terminal = (
                    RunPhase.UNKNOWN_OUTCOME
                    if failure.code == "UNKNOWN_OUTCOME"
                    else RunPhase.FAILED
                )
                recorder.record(
                    failure.state,
                    terminal,
                    failure_code=failure.code,
                    run_duration_ms=max(0, (perf_counter_ns() - run_started_ns) // 1_000_000),
                )
            raise
        except RunDeferred as deferred:
            if recorder_started:
                recorder.record(
                    deferred.state,
                    RunPhase.PAUSED,
                    run_duration_ms=max(
                        0, (perf_counter_ns() - run_started_ns) // 1_000_000
                    ),
                )
            raise
        except TraceError:
            raise
        except Exception:
            if recorder_started:
                recorder.record(
                    state,
                    RunPhase.FAILED,
                    failure_code="RUN_FAILED",
                    run_duration_ms=max(0, (perf_counter_ns() - run_started_ns) // 1_000_000),
                )
            raise
        finally:
            had_active_error = sys.exc_info()[0] is not None
            run_span.set_attributes(
                {
                    "run.phase": "failed" if had_active_error else "completed",
                    "duration.ms": max(
                        0, (perf_counter_ns() - run_started_ns) // 1_000_000
                    ),
                }
            )
            run_span.end()
            presence.release()
            progress.release()
            if control is not None and control_started:
                control_outcome = {
                    RunPhase.SUCCESS: ControlOutcome.SUCCESS,
                    RunPhase.CANCELLED: ControlOutcome.CANCELLED,
                    RunPhase.PAUSED: ControlOutcome.STOPPED,
                    RunPhase.UNKNOWN_OUTCOME: ControlOutcome.UNKNOWN_OUTCOME,
                }.get(recorder.phase, ControlOutcome.FAILED)
                try:
                    control.close(state.run_id, control_outcome)
                except CooperativeControlError:
                    if not had_active_error:
                        raise
            prepared.close()
            if continuation is not None:
                try:
                    continuation.close()
                except Exception:
                    if not had_active_error:
                        raise
            if not desktop_closed:
                try:
                    await self.ports.desktop.close()
                except Exception:
                    if not had_active_error:
                        raise
