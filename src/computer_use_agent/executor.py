"""Pure preflight compiler for one bounded task-plan step.

This module performs no execution.  A persisted plan is untrusted data: the
compiler only reconstructs a fresh, requested ``ToolCall`` after checking the
current run and plan bindings.  The returned call has not passed policy,
grounding, budgets, approval, write-ahead persistence, MCP dispatch, or
post-action verification and therefore carries no action authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from .plan_store import PersistedTaskPlan, TaskPlanStore
from .planning import PlanStepAction, PlanStepStatus
from .tool_registry import (
    ToolValidationError,
    get_tool_spec,
    reviewed_registry_digest,
    validate_tool_arguments,
)
from .types import (
    CallIdentity,
    LedgerEvent,
    LedgerEventKind,
    RecoveryStatus,
    RunBudget,
    RunState,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResultStatus,
    to_json_value,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_EXECUTOR_SESSION_STEPS = 4


class ExecutorPreflightError(RuntimeError):
    """A fixed, non-sensitive rejection before any execution boundary."""


class ExecutorSessionError(RuntimeError):
    """A fixed rejection from the non-executing bounded session contract."""


@dataclass(frozen=True)
class PreparedPlanToolCall:
    """A fresh requested call bound to one exact, still-pending plan snapshot."""

    plan_id: str
    step_id: str
    snapshot_sequence: int
    plan_digest: str
    call: ToolCall

    def __post_init__(self) -> None:
        if not isinstance(self.call, ToolCall):
            raise ValueError("call must be a ToolCall")
        if self.call.status is not ToolCallStatus.REQUESTED:
            raise ValueError("a preflight call must remain requested")


def _identity_was_used(identity: CallIdentity, events: tuple[LedgerEvent, ...]) -> bool:
    return any(event.identity == identity for event in events)


def compile_plan_tool_preflight(
    snapshot: PersistedTaskPlan,
    state: RunState,
    *,
    expected_sequence: int,
    expected_plan_digest: str,
    turn_id: str,
    call_id: str,
) -> PreparedPlanToolCall:
    """Compile one exact pending plan step into a fresh, unauthorized request.

    The caller must later send ``result.call`` through the ordinary host
    workflow.  This function does not consume a budget or mutate the plan, and
    successful preflight must never be interpreted as policy authorization.
    """

    if not isinstance(snapshot, PersistedTaskPlan) or not isinstance(state, RunState):
        raise ExecutorPreflightError("EXECUTOR_INPUT_INVALID")
    if (
        isinstance(expected_sequence, bool)
        or not isinstance(expected_sequence, int)
        or expected_sequence < 0
        or not isinstance(expected_plan_digest, str)
        or _SHA256.fullmatch(expected_plan_digest) is None
    ):
        raise ExecutorPreflightError("EXECUTOR_EXPECTATION_INVALID")

    plan = snapshot.plan
    if snapshot.sequence != expected_sequence or plan.digest != expected_plan_digest:
        raise ExecutorPreflightError("EXECUTOR_PLAN_SNAPSHOT_STALE")
    if plan.run_id != state.run_id:
        raise ExecutorPreflightError("EXECUTOR_RUN_MISMATCH")
    try:
        current_task_digest = sha256(state.task.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise ExecutorPreflightError("EXECUTOR_TASK_MISMATCH") from exc
    if plan.task_digest != current_task_digest:
        raise ExecutorPreflightError("EXECUTOR_TASK_MISMATCH")
    if plan.registry_digest != reviewed_registry_digest():
        raise ExecutorPreflightError("EXECUTOR_REGISTRY_MISMATCH")

    step = next(
        (item for item in plan.steps if item.status is not PlanStepStatus.COMPLETED),
        None,
    )
    if step is None:
        raise ExecutorPreflightError("EXECUTOR_PLAN_TERMINAL")
    if step.status is not PlanStepStatus.PENDING:
        raise ExecutorPreflightError("EXECUTOR_STEP_NOT_PENDING")
    if step.action is not PlanStepAction.TOOL:
        raise ExecutorPreflightError("EXECUTOR_FINAL_RESPONSE_NOT_EXECUTABLE")
    if step.tool_name is None:
        raise ExecutorPreflightError("EXECUTOR_STEP_INVALID")

    try:
        spec = get_tool_spec(step.tool_name)
        arguments = validate_tool_arguments(step.tool_name, step.arguments)
    except ToolValidationError as exc:
        raise ExecutorPreflightError("EXECUTOR_STEP_INVALID") from exc
    if spec.sensitive_arguments:
        raise ExecutorPreflightError("EXECUTOR_SENSITIVE_ARGUMENTS_FORBIDDEN")
    if step.effect is not spec.effect or step.requires_approval is not spec.requires_host_approval:
        raise ExecutorPreflightError("EXECUTOR_REGISTRY_MISMATCH")

    try:
        identity = CallIdentity(run_id=state.run_id, turn_id=turn_id, call_id=call_id)
    except ValueError as exc:
        raise ExecutorPreflightError("EXECUTOR_IDENTITY_INVALID") from exc
    if _identity_was_used(identity, state.event_log):
        raise ExecutorPreflightError("EXECUTOR_CALL_IDENTITY_REUSED")

    call = ToolCall(
        identity=identity,
        name=step.tool_name,
        arguments=arguments,
        status=ToolCallStatus.REQUESTED,
    )
    return PreparedPlanToolCall(
        plan_id=plan.plan_id,
        step_id=step.step_id,
        snapshot_sequence=snapshot.sequence,
        plan_digest=plan.digest,
        call=call,
    )


def _same_budget_limits(previous: RunBudget, current: RunBudget) -> bool:
    return (
        previous.max_model_turns == current.max_model_turns
        and previous.max_tool_calls == current.max_tool_calls
        and previous.max_side_effects == current.max_side_effects
        and previous.max_input_tokens == current.max_input_tokens
    )


def _state_advances(previous: RunState, current: RunState) -> bool:
    return (
        previous.run_id == current.run_id
        and previous.task == current.task
        and previous.policy_version == current.policy_version
        and current.event_log[: len(previous.event_log)] == previous.event_log
        and _same_budget_limits(previous.budgets, current.budgets)
        and current.budgets.model_turns_used >= previous.budgets.model_turns_used
        and current.budgets.tool_calls_used >= previous.budgets.tool_calls_used
        and current.budgets.side_effects_used >= previous.budgets.side_effects_used
        and current.budgets.input_tokens_used >= previous.budgets.input_tokens_used
        and current.observation_epoch >= previous.observation_epoch
    )


class BoundedExecutorSession:
    """Lock-scoped sequencing for future execution, with no execution methods.

    The session reads one ``TaskPlanStore`` while its existing application lock
    remains held. It creates fresh requested calls and later verifies that an
    external caller used the shared Runner boundary and persisted the matching
    plan transition. It has no provider, approval, recovery, MCP, trace, or
    desktop port and cannot authorize or dispatch its prepared calls.
    """

    def __init__(
        self,
        store: TaskPlanStore,
        initial_state: RunState,
        *,
        allow_side_effects: bool = False,
    ) -> None:
        if (
            not isinstance(store, TaskPlanStore)
            or not isinstance(initial_state, RunState)
            or not isinstance(allow_side_effects, bool)
        ):
            raise ExecutorSessionError("EXECUTOR_SESSION_INPUT_INVALID")
        if not store.lock.acquired:
            raise ExecutorSessionError("EXECUTOR_SESSION_LOCK_REQUIRED")
        self._store = store
        self._state = initial_state
        self._outstanding: PreparedPlanToolCall | None = None
        self._prepared_steps = 0
        self._closed = False
        self._allow_side_effects = allow_side_effects

    @property
    def prepared_steps(self) -> int:
        return self._prepared_steps

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        self._closed = True

    def _require_active(self) -> None:
        if self._closed:
            raise ExecutorSessionError("EXECUTOR_SESSION_CLOSED")
        if not self._store.lock.acquired:
            raise ExecutorSessionError("EXECUTOR_SESSION_LOCK_REQUIRED")

    def prepare_next(self, current_state: RunState) -> PreparedPlanToolCall:
        """Prepare one fresh observation request without granting authority."""

        self._require_active()
        if not isinstance(current_state, RunState) or not _state_advances(
            self._state, current_state
        ):
            raise ExecutorSessionError("EXECUTOR_SESSION_STATE_DRIFT")
        if self._outstanding is not None:
            raise ExecutorSessionError("EXECUTOR_SESSION_CALL_OUTSTANDING")
        if self._prepared_steps >= MAX_EXECUTOR_SESSION_STEPS:
            raise ExecutorSessionError("EXECUTOR_SESSION_STEP_LIMIT")

        snapshot = self._store.read(current_state.run_id)
        turn_number = self._prepared_steps + 1
        try:
            prepared = compile_plan_tool_preflight(
                snapshot,
                current_state,
                expected_sequence=snapshot.sequence,
                expected_plan_digest=snapshot.plan.digest,
                turn_id=f"executor_turn_{turn_number}",
                call_id=uuid4().hex,
            )
        except ExecutorPreflightError as exc:
            raise ExecutorSessionError(str(exc)) from exc
        effect = get_tool_spec(prepared.call.name).effect
        if effect is not ToolEffect.OBSERVATION and not (
            effect is ToolEffect.SIDE_EFFECT and self._allow_side_effects
        ):
            raise ExecutorSessionError("EXECUTOR_SESSION_SIDE_EFFECT_UNSUPPORTED")

        self._state = current_state
        self._outstanding = prepared
        self._prepared_steps = turn_number
        return prepared

    def accept_boundary_outcome(
        self,
        prepared: PreparedPlanToolCall,
        current_state: RunState,
        *,
        expected_status: PlanStepStatus | None = None,
    ) -> None:
        """Accept exact ledger and plan evidence produced outside this contract."""

        self._require_active()
        if prepared is not self._outstanding:
            raise ExecutorSessionError("EXECUTOR_SESSION_CALL_MISMATCH")
        if not isinstance(current_state, RunState) or not _state_advances(
            self._state, current_state
        ):
            raise ExecutorSessionError("EXECUTOR_SESSION_STATE_DRIFT")

        call_events = [
            event
            for event in current_state.event_log
            if event.kind is LedgerEventKind.TOOL_CALL
            and event.identity == prepared.call.identity
        ]
        result_events = [
            event
            for event in current_state.event_log
            if event.kind is LedgerEventKind.TOOL_RESULT
            and event.identity == prepared.call.identity
        ]
        if len(call_events) != 1 or len(result_events) != 1:
            raise ExecutorSessionError("EXECUTOR_SESSION_BOUNDARY_EVIDENCE_MISSING")
        call_index = current_state.event_log.index(call_events[0])
        result_index = current_state.event_log.index(result_events[0])
        if call_index >= result_index:
            raise ExecutorSessionError("EXECUTOR_SESSION_BOUNDARY_EVIDENCE_INVALID")
        result = result_events[0].tool_result
        if result is None or result.tool_name != prepared.call.name:
            raise ExecutorSessionError("EXECUTOR_SESSION_BOUNDARY_EVIDENCE_INVALID")

        snapshot = self._store.read(current_state.run_id)
        if snapshot.plan.plan_id != prepared.plan_id:
            raise ExecutorSessionError("EXECUTOR_SESSION_PLAN_MISMATCH")
        step = next(
            (item for item in snapshot.plan.steps if item.step_id == prepared.step_id),
            None,
        )
        if step is None:
            raise ExecutorSessionError("EXECUTOR_SESSION_PLAN_MISMATCH")
        spec = get_tool_spec(prepared.call.name)
        if (
            step.tool_name != prepared.call.name
            or to_json_value(step.arguments) != to_json_value(prepared.call.arguments)
            or step.effect is not spec.effect
            or (
                step.effect is ToolEffect.SIDE_EFFECT
                and not self._allow_side_effects
            )
        ):
            raise ExecutorSessionError("EXECUTOR_SESSION_PLAN_MISMATCH")
        if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
            if expected_status is not None:
                raise ExecutorSessionError("EXECUTOR_SESSION_TRANSITION_MISMATCH")
            if (
                snapshot.sequence != prepared.snapshot_sequence + 1
                or step.status is not PlanStepStatus.IN_PROGRESS
            ):
                raise ExecutorSessionError("EXECUTOR_SESSION_TRANSITION_MISMATCH")
            self._closed = True
        else:
            derived = (
                PlanStepStatus.COMPLETED if result.ok else PlanStepStatus.FAILED
            )
            expected = derived if expected_status is None else expected_status
            if expected is PlanStepStatus.BLOCKED:
                deferred = (
                    result.code == "APPROVAL_DEFERRED"
                    and current_state.recovery_status is RecoveryStatus.STOPPED
                )
                verification_required = (
                    not result.ok
                    and current_state.recovery_status
                    is RecoveryStatus.REQUIRES_REOBSERVATION
                )
                if not deferred and not verification_required:
                    raise ExecutorSessionError(
                        "EXECUTOR_SESSION_TRANSITION_MISMATCH"
                    )
            elif expected is not derived:
                raise ExecutorSessionError("EXECUTOR_SESSION_TRANSITION_MISMATCH")
            if (
                snapshot.sequence != prepared.snapshot_sequence + 2
                or step.status is not expected
            ):
                raise ExecutorSessionError("EXECUTOR_SESSION_TRANSITION_MISMATCH")

        self._state = current_state
        self._outstanding = None


__all__ = [
    "BoundedExecutorSession",
    "ExecutorPreflightError",
    "ExecutorSessionError",
    "MAX_EXECUTOR_SESSION_STEPS",
    "PreparedPlanToolCall",
    "compile_plan_tool_preflight",
]
