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

from .plan_store import PersistedTaskPlan
from .planning import PlanStepAction, PlanStepStatus
from .tool_registry import (
    ToolValidationError,
    get_tool_spec,
    reviewed_registry_digest,
    validate_tool_arguments,
)
from .types import CallIdentity, LedgerEvent, RunState, ToolCall, ToolCallStatus


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ExecutorPreflightError(RuntimeError):
    """A fixed, non-sensitive rejection before any execution boundary."""


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


__all__ = [
    "ExecutorPreflightError",
    "PreparedPlanToolCall",
    "compile_plan_tool_preflight",
]
