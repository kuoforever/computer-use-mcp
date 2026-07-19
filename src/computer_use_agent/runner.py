"""Bounded provider-neutral Agent workflow for the local desktop bridge."""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from .campaign import CampaignStore
from .config import AgentConfig
from .continuation import RuntimeContinuationRecorder
from .context import ContextBudgetError, reduce_ledger
from .grounding import GroundingError, GroundingState
from .executor_final_store import FinalResponseStore
from .plan_store import TaskPlanStore
from .policy import HostPolicy, PolicyDisposition
from .privacy import PrivacyError, PrivacyImageRedactionPort, PrivacySession
from .run_lock import RunLock
from .tool_registry import (
    REVIEWED_TOOLS,
    ToolValidationError,
    get_tool_spec,
    validate_tool_arguments,
    validate_tool_result,
    verify_discovered_tools,
    reviewed_registry_digest,
)
from .trace import RunPhase, RunRecorder, TraceError
from .types import (
    ApprovalPort,
    ApprovalRequest,
    DesktopMCPPort,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
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


@dataclass(frozen=True)
class RunnerPorts:
    """Injected external boundaries used by the bounded workflow."""

    provider: ModelProviderPort
    desktop: DesktopMCPPort
    approvals: ApprovalPort
    image_redactor: PrivacyImageRedactionPort | None = None


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

    def _record_call(self, state: RunState, call: ToolCall) -> RunState:
        if state.budgets.tool_calls_used >= state.budgets.max_tool_calls:
            raise RunnerBudgetError("TOOL_CALL_BUDGET_EXHAUSTED")
        spec = get_tool_spec(call.name)
        normalized = validate_tool_arguments(call.name, call.arguments)
        if dict(call.arguments) != normalized:
            raise ToolValidationError("tool arguments are not in canonical form")
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

    async def _execute_requested_call_boundary(
        self,
        state: RunState,
        call: ToolCall,
        *,
        grounding: GroundingState,
        recorder: RunRecorder,
        continuation: RuntimeContinuationRecorder | None,
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
        try:
            if privacy is not None:
                privacy.validate_tool_call(call)
                if (
                    privacy.config.enabled
                    and call.name == "screenshot"
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
        disposition = self.policy.disposition(spec)
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
            except RunnerBudgetError as exc:
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
            )
            recorder.record(state, RunPhase.WAITING_APPROVAL)
            decision = await self.ports.approvals.request_approval(request)
            if not request.matches(decision) or decision.kind not in {
                PolicyDecisionKind.ALLOW,
                PolicyDecisionKind.DENY,
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
            state = self._consume_side_effect(state)

        recorder.record(state, RunPhase.EXECUTING)
        authorized_call = replace(call, status=ToolCallStatus.AUTHORIZED)
        tool_started_ns = perf_counter_ns()
        if continuation is not None:
            recorder.record(state, recorder.phase, advance_checkpoint_sequence=True)
            continuation.prepare_tool(
                state,
                authorized_call,
                effect=spec.effect,
                checkpoint_sequence=recorder.checkpoint_sequence,
            )
            recorder.record(state, recorder.phase, advance_checkpoint_sequence=True)
            continuation.dispatch_tool(
                state, checkpoint_sequence=recorder.checkpoint_sequence
            )
        try:
            dispatch_call = (
                authorized_call
                if privacy is None
                else privacy.resolve_local_call(authorized_call)
            )
            result = await self.ports.desktop.call_tool(dispatch_call)
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
        if continuation is not None:
            recorder.record(state, recorder.phase, advance_checkpoint_sequence=True)
            continuation.complete_tool(
                state, result, checkpoint_sequence=recorder.checkpoint_sequence
            )
        if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
            raise RunFailure("UNKNOWN_OUTCOME", state)
        if spec.effect is ToolEffect.OBSERVATION and result.ok:
            grounding = grounding.observe(
                result,
                generation=self.ports.desktop.generation,
                epoch=state.observation_epoch,
            )
            recorder.record(state, RunPhase.OBSERVING)
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
    ) -> RunOutcome:
        """Run a bounded model/tool loop and release lock and desktop."""

        if self.ports is None:
            raise RunnerError("RUNNER_PORTS_REQUIRED")
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
            for tool in REVIEWED_TOOLS
            if not self.config.privacy.enabled
            or tool.name != "screenshot"
            or (
                self.config.privacy.image_redaction
                and self.ports is not None
                and self.ports.image_redactor is not None
            )
        )
        grounding = GroundingState()
        recorder = RunRecorder(self.config.state_dir, state.run_id)
        run_started_ns = perf_counter_ns()
        recorder_started = False
        desktop_closed = False
        continuation: RuntimeContinuationRecorder | None = None
        try:
            if resume_initial:
                recorder.attach_initial(state)
            else:
                recorder.start(state)
            recorder_started = True
            recorder.record(state, RunPhase.OBSERVING)
            discovered = await self.ports.desktop.discover_tools()
            verify_discovered_tools(discovered)
            if self.config.continuation.enabled:
                continuation = RuntimeContinuationRecorder(
                    state_dir=self.config.state_dir,
                    state=state,
                    provider_name=self.config.provider.name,
                    provider_model=self.config.provider.model,
                    registry_digest=reviewed_registry_digest(),
                    ttl_seconds=self.config.continuation.ttl_seconds,
                    mcp_generation=self.ports.desktop.generation,
                )
            recorder.record(state, RunPhase.PLANNING)
            turn_index = 0
            while True:
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
                turn = await self.ports.provider.create_turn(
                    run_id=state.run_id,
                    turn_id=turn_id,
                    task=state.task,
                    ledger=provider_ledger,
                    tools=provider_tools,
                    memories=memories,
                )
                if turn.run_id != state.run_id or turn.turn_id != turn_id:
                    raise RunFailure("PROVIDER_TURN_IDENTITY_MISMATCH", state)
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
                    outcome = await self._execute_requested_call_boundary(
                        state,
                        call,
                        grounding=grounding,
                        recorder=recorder,
                        continuation=continuation,
                        privacy=privacy,
                    )
                    state = outcome.state
                    grounding = outcome.grounding
        except asyncio.CancelledError:
            if recorder_started:
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
