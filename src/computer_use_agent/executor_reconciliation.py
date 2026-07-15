"""Local-only reconciliation for a durably completed observation plan step.

Persisted plans and continuation records remain untrusted data.  This module
can repair only the narrow case where the continuation WAL proves that the
currently ``in_progress`` observation completed with a known outcome while the
matching terminal plan transition was not committed.  It has no external
ports and never resumes or replays a call.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Mapping

from .continuation import ContinuationEnvelope, ContinuationError
from .plan_store import PersistedTaskPlan, PlanStoreError, TaskPlanStore
from .planning import PlanStepAction, PlanStepStatus
from .tool_registry import (
    ToolValidationError,
    reviewed_registry_digest,
    validate_tool_arguments,
)
from .types import (
    CallIdentity,
    DispatchCertainty,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResultStatus,
    to_json_value,
)


class ExecutorReconciliationError(RuntimeError):
    """A fixed rejection from local-only Executor reconciliation."""


@dataclass(frozen=True)
class PreparedObservationReconciliation:
    """One exact plan transition proven by a validated continuation envelope."""

    run_id: str
    plan_id: str
    step_id: str
    expected_sequence: int
    expected_plan_digest: str
    continuation_digest: str
    target: PlanStepStatus

    def __post_init__(self) -> None:
        if self.target not in {PlanStepStatus.COMPLETED, PlanStepStatus.FAILED}:
            raise ValueError("reconciliation target must be terminal")


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    return value


def _identity(value: object, run_id: str) -> CallIdentity:
    raw = _mapping(value)
    if set(raw) != {"run_id", "turn_id", "call_id"} or raw.get("run_id") != run_id:
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    try:
        return CallIdentity(
            run_id=str(raw["run_id"]),
            turn_id=str(raw["turn_id"]),
            call_id=str(raw["call_id"]),
        )
    except (KeyError, ValueError) as exc:
        raise ExecutorReconciliationError(
            "EXECUTOR_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc


def compile_observation_reconciliation(
    snapshot: PersistedTaskPlan,
    envelope: ContinuationEnvelope,
    *,
    task: str,
    expected_sequence: int,
    expected_plan_digest: str,
) -> PreparedObservationReconciliation:
    """Prove one local terminal transition without granting execution authority."""

    if (
        not isinstance(snapshot, PersistedTaskPlan)
        or not isinstance(envelope, ContinuationEnvelope)
        or not isinstance(task, str)
        or not task
        or isinstance(expected_sequence, bool)
        or not isinstance(expected_sequence, int)
        or expected_sequence < 0
        or not isinstance(expected_plan_digest, str)
    ):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_INPUT_INVALID")
    plan = snapshot.plan
    if snapshot.sequence != expected_sequence or plan.digest != expected_plan_digest:
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_PLAN_STALE")
    try:
        task_digest = sha256(task.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise ExecutorReconciliationError(
            "EXECUTOR_RECONCILIATION_IDENTITY_MISMATCH"
        ) from exc
    try:
        envelope = ContinuationEnvelope.from_payload(
            envelope.payload,
            expected_run_id=plan.run_id,
        )
    except ContinuationError as exc:
        raise ExecutorReconciliationError(
            "EXECUTOR_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc
    payload = envelope.payload
    if (
        payload.get("run_id") != plan.run_id
        or payload.get("task") != task
        or plan.task_digest != task_digest
        or payload.get("registry_digest") != plan.registry_digest
        or plan.registry_digest != reviewed_registry_digest()
    ):
        raise ExecutorReconciliationError(
            "EXECUTOR_RECONCILIATION_IDENTITY_MISMATCH"
        )

    step = next(
        (item for item in plan.steps if item.status is not PlanStepStatus.COMPLETED),
        None,
    )
    if (
        step is None
        or step.status is not PlanStepStatus.IN_PROGRESS
        or step.action is not PlanStepAction.TOOL
        or step.tool_name is None
        or step.effect is not ToolEffect.OBSERVATION
    ):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_STEP_UNSAFE")

    boundary = _mapping(payload.get("boundary"))
    if (
        boundary.get("operation_kind") != "tool"
        or boundary.get("stage") != "completed"
        or boundary.get("effect") != "observation"
        or boundary.get("dispatch") != "dispatched"
        or boundary.get("next_step") != "provider_continue"
    ):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_OUTCOME_UNCERTAIN")

    ledger = payload.get("ledger")
    if not isinstance(ledger, list) or len(ledger) < 3:
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    call_event = _mapping(ledger[-2])
    result_event = _mapping(ledger[-1])
    if call_event.get("kind") != "tool_call" or result_event.get("kind") != "tool_result":
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    call_data = _mapping(call_event.get("data"))
    result_data = _mapping(result_event.get("data"))
    call_identity = _identity(call_data.get("identity"), plan.run_id)
    result_identity = _identity(result_data.get("identity"), plan.run_id)
    if call_identity != result_identity:
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")

    raw_arguments = call_data.get("arguments")
    if not isinstance(raw_arguments, Mapping):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    try:
        arguments = validate_tool_arguments(step.tool_name, raw_arguments)
        reconstructed = ToolCall(
            identity=call_identity,
            name=step.tool_name,
            arguments=arguments,
            status=ToolCallStatus.REQUESTED,
        )
    except (ToolValidationError, ValueError, TypeError) as exc:
        raise ExecutorReconciliationError(
            "EXECUTOR_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc
    if (
        call_data.get("tool_name") != step.tool_name
        or call_data.get("effect") != "observation"
        or call_data.get("call_digest") != reconstructed.digest
        or to_json_value(arguments) != to_json_value(step.arguments)
        or result_data.get("tool_name") != step.tool_name
    ):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    operation_id = f"{call_identity.run_id}:{call_identity.turn_id}:{call_identity.call_id}"
    if boundary.get("operation_id") != operation_id:
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")

    try:
        status = ToolResultStatus(result_data.get("status"))
        dispatch = DispatchCertainty(result_data.get("dispatch"))
    except (TypeError, ValueError) as exc:
        raise ExecutorReconciliationError(
            "EXECUTOR_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc
    allowed_dispatch = {
        ToolResultStatus.SUCCESS: DispatchCertainty.DISPATCHED,
        ToolResultStatus.ACTION_ERROR: DispatchCertainty.DISPATCHED,
        ToolResultStatus.TRANSPORT_ERROR: DispatchCertainty.NOT_DISPATCHED,
        ToolResultStatus.REJECTED: DispatchCertainty.NOT_DISPATCHED,
    }
    if (
        status is ToolResultStatus.UNKNOWN_OUTCOME
        or dispatch is DispatchCertainty.UNKNOWN
        or allowed_dispatch.get(status) is not dispatch
    ):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_OUTCOME_UNCERTAIN")
    target = PlanStepStatus.COMPLETED if status is ToolResultStatus.SUCCESS else PlanStepStatus.FAILED
    continuation_digest = payload.get("payload_digest")
    if not isinstance(continuation_digest, str):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_EVIDENCE_INVALID")
    return PreparedObservationReconciliation(
        run_id=plan.run_id,
        plan_id=plan.plan_id,
        step_id=step.step_id,
        expected_sequence=snapshot.sequence,
        expected_plan_digest=plan.digest,
        continuation_digest=continuation_digest,
        target=target,
    )


def reconcile_completed_observation(
    store: TaskPlanStore,
    envelope: ContinuationEnvelope,
    *,
    task: str,
    expected_sequence: int,
    expected_plan_digest: str,
) -> PersistedTaskPlan:
    """Apply one proven local plan repair; retain WAL and perform no external I/O."""

    if not isinstance(store, TaskPlanStore):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_INPUT_INVALID")
    run_id = envelope.payload.get("run_id") if isinstance(envelope, ContinuationEnvelope) else None
    if not isinstance(run_id, str):
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_INPUT_INVALID")
    snapshot = store.read(run_id)
    prepared = compile_observation_reconciliation(
        snapshot,
        envelope,
        task=task,
        expected_sequence=expected_sequence,
        expected_plan_digest=expected_plan_digest,
    )
    try:
        return store.transition(
            prepared.run_id,
            prepared.step_id,
            prepared.target,
            expected_sequence=prepared.expected_sequence,
            expected_plan_digest=prepared.expected_plan_digest,
        )
    except PlanStoreError as exc:
        raise ExecutorReconciliationError("EXECUTOR_RECONCILIATION_COMMIT_FAILED") from exc


__all__ = [
    "ExecutorReconciliationError",
    "PreparedObservationReconciliation",
    "compile_observation_reconciliation",
    "reconcile_completed_observation",
]
