"""Local-only application of completed final-response reconciliation."""
from __future__ import annotations

from .continuation import ContinuationError, delete_continuation, read_continuation
from .executor_final_reconciliation import (
    ExecutorFinalReconciliationError,
    PreparedFinalResponseReconciliation,
    compile_final_response_reconciliation,
)
from .executor_final_store import FinalResponseStore, FinalResponseStoreError
from .plan_store import PlanStoreError, TaskPlanStore
from .planning import PlanStepStatus
from .trace import RunRecorder, TraceError, read_run_record


def apply_completed_final_response_reconciliation(
    plan_store: TaskPlanStore,
    final_store: FinalResponseStore,
    *,
    run_id: str,
    task: str,
    expected_plan_sequence: int,
    expected_plan_digest: str,
    expected_final_sequence: int,
    expected_final_digest: str,
) -> PreparedFinalResponseReconciliation:
    """Validate and apply one completed final result using local CAS only.

    The caller must hold the one application run lock through both stores.
    This function performs no provider, MCP, policy, approval, or desktop call.
    The completed final WAL is retained; only the ordinary sensitive
    continuation is removed after plan and terminal trace state are durable.
    """

    if (
        not isinstance(plan_store, TaskPlanStore)
        or not isinstance(final_store, FinalResponseStore)
        or plan_store.lock is not final_store.lock
        or plan_store.state_dir != final_store.state_dir
        or not plan_store.lock.acquired
        or not isinstance(run_id, str)
        or not run_id
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_INPUT_INVALID"
        )
    try:
        plan_snapshot = plan_store.read(run_id)
        final_snapshot = final_store.read(run_id)
        envelope = read_continuation(plan_store.state_dir, run_id)
        run_record = read_run_record(plan_store.state_dir, run_id)
        prepared = compile_final_response_reconciliation(
            plan_snapshot,
            final_snapshot,
            envelope,
            run_record,
            task=task,
            expected_plan_sequence=expected_plan_sequence,
            expected_plan_digest=expected_plan_digest,
            expected_final_sequence=expected_final_sequence,
            expected_final_digest=expected_final_digest,
        )
    except (ContinuationError, FinalResponseStoreError, PlanStoreError, TraceError) as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc

    if not prepared.plan_already_completed:
        try:
            plan_store.transition(
                prepared.run_id,
                prepared.step_id,
                PlanStepStatus.COMPLETED,
                expected_sequence=prepared.expected_plan_sequence,
                expected_plan_digest=prepared.expected_plan_digest,
            )
        except PlanStoreError as exc:
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_PLAN_COMMIT_FAILED"
            ) from exc

    recorder = RunRecorder(plan_store.state_dir, prepared.run_id)
    try:
        recorder.reconcile_final_success(
            prepared.terminal_state,
            expected_checkpoint_sequence=prepared.checkpoint_sequence,
            terminal_event_already_recorded=prepared.terminal_event_already_recorded,
            final_text_length=len(prepared.result.text),
        )
    except TraceError as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_TERMINAL_COMMIT_FAILED"
        ) from exc
    try:
        delete_continuation(plan_store.state_dir, prepared.run_id)
    except ContinuationError as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_CLEANUP_FAILED"
        ) from exc
    return prepared


__all__ = ["apply_completed_final_response_reconciliation"]
