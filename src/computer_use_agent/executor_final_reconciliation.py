"""Pure preflight for completed Executor final-response reconciliation.

All persisted inputs remain untrusted data.  This module reconstructs the
exact pre-dispatch request and terminal host state, but performs no writes and
has no provider, policy, approval, recovery-executor, MCP, or desktop port.
"""
from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Mapping

from .continuation import ContinuationEnvelope, ContinuationError
from .executor_final import ExecutorFinalError, FinalResponseResult, compile_final_response_request
from .executor_final_store import (
    FinalResponseStage,
    PersistedFinalResponse,
)
from .plan_store import PersistedTaskPlan
from .planning import PlanStepAction, PlanStepStatus, PlanValidationError
from .tool_registry import (
    ToolValidationError,
    reviewed_registry_digest,
    validate_tool_arguments,
    validate_tool_result,
)
from .types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    LedgerEvent,
    LedgerEventKind,
    RecoveryStatus,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
    to_json_value,
)


class ExecutorFinalReconciliationError(RuntimeError):
    """Fixed rejection from local-only final-response reconciliation preflight."""


@dataclass(frozen=True, repr=False)
class PreparedFinalResponseReconciliation:
    """Exact terminal evidence for a future separately reviewed CAS writer."""

    run_id: str
    plan_id: str
    step_id: str
    expected_plan_sequence: int
    expected_plan_digest: str
    final_response_sequence: int
    final_response_digest: str
    checkpoint_sequence: int
    continuation_digest: str
    plan_already_completed: bool
    terminal_event_already_recorded: bool
    terminal_state: RunState
    result: FinalResponseResult
    provider_latency_ms: int

    def __repr__(self) -> str:
        return (
            "PreparedFinalResponseReconciliation("
            f"run_id={self.run_id!r}, plan_id={self.plan_id!r}, "
            f"step_id={self.step_id!r}, "
            f"plan_already_completed={self.plan_already_completed}, "
            f"terminal_event_already_recorded={self.terminal_event_already_recorded}, "
            f"checkpoint_sequence={self.checkpoint_sequence}, "
            f"text_length={len(self.result.text)})"
        )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    return value


def _uint(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    return value


def _identity(value: object, *, run_id: str, turn_id: str) -> CallIdentity:
    raw = _mapping(value)
    if set(raw) != {"run_id", "turn_id", "call_id"}:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    try:
        identity = CallIdentity(str(raw["run_id"]), str(raw["turn_id"]), str(raw["call_id"]))
    except (KeyError, ValueError) as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc
    if identity.run_id != run_id or identity.turn_id != turn_id:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    return identity


def _images(value: object) -> tuple[ImageContent, ...]:
    if not isinstance(value, list):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    images: list[ImageContent] = []
    try:
        for raw in value:
            item = _mapping(raw)
            if set(item) != {"mime_type", "data", "width", "height"}:
                raise ValueError
            images.append(
                ImageContent(
                    mime_type=str(item["mime_type"]),
                    data=b64decode(str(item["data"]), validate=True),
                    width=item["width"],  # type: ignore[arg-type]
                    height=item["height"],  # type: ignore[arg-type]
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc
    return tuple(images)


def _trace_event(
    events: list[object], index: int, *, kind: str, run_id: str
) -> Mapping[str, object]:
    if index >= len(events):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_TRACE_MISMATCH"
        )
    event = _mapping(events[index])
    if (
        event.get("trace_version") != 1
        or event.get("sequence") != index + 1
        or event.get("run_id") != run_id
        or event.get("kind") != kind
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_TRACE_MISMATCH"
        )
    return event


def _reconstruct_state(
    plan_snapshot: PersistedTaskPlan,
    final_snapshot: PersistedFinalResponse,
    envelope: ContinuationEnvelope,
    run_record: Mapping[str, object],
    *,
    task: str,
    checkpoint_sequence: int,
) -> tuple[RunState, RunState, bool]:
    plan = plan_snapshot.plan
    payload = envelope.payload
    tool_steps = tuple(step for step in plan.steps if step.action is PlanStepAction.TOOL)
    ledger = payload.get("ledger")
    if not isinstance(ledger, list) or len(ledger) != 1 + 2 * len(tool_steps):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    first = _mapping(ledger[0])
    if (
        set(first) != {"kind", "event_id", "data"}
        or first.get("kind") != "user_task"
        or first.get("event_id") != f"{plan.run_id}:recovery:1"
        or _mapping(first.get("data")) != {"task": task}
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )

    checkpoint = _mapping(run_record.get("state"))
    trace = run_record.get("events")
    base_event_count = 1 + 3 * len(tool_steps)
    if not isinstance(trace, list) or len(trace) not in {
        base_event_count,
        base_event_count + 1,
    }:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_TRACE_MISMATCH"
        )
    first_trace = _trace_event(trace, 0, kind="user_task", run_id=plan.run_id)
    if set(first_trace) != {
        "trace_version",
        "sequence",
        "run_id",
        "kind",
        "task_length",
    } or first_trace.get("task_length") != len(task):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_TRACE_MISMATCH"
        )

    canonical_events: list[LedgerEvent] = [
        LedgerEvent(
            event_id=f"{plan.run_id}:event:1",
            kind=LedgerEventKind.USER_TASK,
            payload={"task_length": len(task)},
        )
    ]
    for index, step in enumerate(tool_steps, start=1):
        call_event = _mapping(ledger[2 * index - 1])
        result_event = _mapping(ledger[2 * index])
        if (
            set(call_event) != {"kind", "event_id", "data"}
            or set(result_event) != {"kind", "event_id", "data"}
            or call_event.get("kind") != "tool_call"
            or result_event.get("kind") != "tool_result"
            or call_event.get("event_id") != f"{plan.run_id}:recovery:{2 * index}"
            or result_event.get("event_id") != f"{plan.run_id}:recovery:{2 * index + 1}"
        ):
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            )
        call_data = _mapping(call_event.get("data"))
        result_data = _mapping(result_event.get("data"))
        if set(call_data) != {"identity", "tool_name", "arguments", "call_digest", "effect"}:
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            )
        if set(result_data) != {
            "identity",
            "tool_name",
            "status",
            "dispatch",
            "code",
            "sanitized_text",
            "images",
        }:
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            )
        if step.tool_name is None or step.effect is not ToolEffect.OBSERVATION:
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_PLAN_UNSAFE"
            )
        identity = _identity(
            call_data.get("identity"),
            run_id=plan.run_id,
            turn_id=f"executor_turn_{index}",
        )
        if identity != _identity(
            result_data.get("identity"),
            run_id=plan.run_id,
            turn_id=f"executor_turn_{index}",
        ):
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            )
        try:
            arguments = validate_tool_arguments(step.tool_name, call_data.get("arguments"))  # type: ignore[arg-type]
            call = ToolCall(identity, step.tool_name, arguments)
            result = ToolResult(
                identity=identity,
                tool_name=step.tool_name,
                status=ToolResultStatus(str(result_data.get("status"))),
                dispatch=DispatchCertainty(str(result_data.get("dispatch"))),
                code=result_data.get("code"),  # type: ignore[arg-type]
                sanitized_text=result_data.get("sanitized_text"),  # type: ignore[arg-type]
                images=_images(result_data.get("images")),
            )
            validate_tool_result(call, result)
        except (ToolValidationError, TypeError, ValueError) as exc:
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            ) from exc
        if (
            call_data.get("tool_name") != step.tool_name
            or call_data.get("effect") != ToolEffect.OBSERVATION.value
            or call_data.get("call_digest") != call.digest
            or to_json_value(arguments) != to_json_value(step.arguments)
            or result_data.get("tool_name") != step.tool_name
            or not result.ok
            or result.dispatch is not DispatchCertainty.DISPATCHED
        ):
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            )

        call_trace = _trace_event(
            trace, 3 * index - 2, kind="tool_call", run_id=plan.run_id
        )
        result_trace = _trace_event(
            trace, 3 * index - 1, kind="tool_result", run_id=plan.run_id
        )
        observation_trace = _trace_event(
            trace, 3 * index, kind="observation", run_id=plan.run_id
        )
        if (
            set(call_trace)
            != {
                "trace_version",
                "sequence",
                "run_id",
                "kind",
                "tool",
                "arguments",
                "redacted_fields",
            }
            or set(result_trace)
            != {
                "trace_version",
                "sequence",
                "run_id",
                "kind",
                "tool",
                "status",
                "dispatch",
                "text_length",
                "image_count",
                "latency_ms",
            }
            or set(observation_trace)
            != {
                "trace_version",
                "sequence",
                "run_id",
                "kind",
                "tool",
                "observation_epoch",
            }
            or call_trace.get("tool") != step.tool_name
            or call_trace.get("arguments") != to_json_value(arguments)
            or call_trace.get("redacted_fields") != []
            or result_trace.get("tool") != step.tool_name
            or result_trace.get("status") != "success"
            or result_trace.get("dispatch") != "dispatched"
            or result_trace.get("text_length") != len(result.sanitized_text)
            or result_trace.get("image_count") != len(result.images)
            or observation_trace.get("tool") != step.tool_name
            or observation_trace.get("observation_epoch") != index
        ):
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_TRACE_MISMATCH"
            )
        latency = result_trace.get("latency_ms")
        _uint(latency)
        safe = SafeArgumentSummary.from_tool_call(call, sensitive_arguments=())
        canonical_events.extend(
            (
                LedgerEvent(
                    event_id=f"{plan.run_id}:event:{len(canonical_events) + 1}",
                    kind=LedgerEventKind.TOOL_CALL,
                    identity=identity,
                    safe_argument_summary=safe,
                ),
                LedgerEvent(
                    event_id=f"{plan.run_id}:event:{len(canonical_events) + 2}",
                    kind=LedgerEventKind.TOOL_RESULT,
                    identity=identity,
                    tool_result=result,
                    payload={"latency_ms": latency},
                ),
                LedgerEvent(
                    event_id=f"{plan.run_id}:event:{len(canonical_events) + 3}",
                    kind=LedgerEventKind.OBSERVATION,
                    identity=identity,
                    payload={"tool_name": step.tool_name, "observation_epoch": index},
                ),
            )
        )

    budget = _mapping(payload.get("budget"))
    observation = _mapping(payload.get("observation"))
    if (
        budget.get("model_turns_used") != 0
        or budget.get("tool_calls_used") != len(tool_steps)
        or budget.get("side_effects_used") != 0
        or budget.get("input_tokens_used") != 0
        or observation.get("epoch") != len(tool_steps)
        or observation.get("verified_epoch") != len(tool_steps)
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_STATE_MISMATCH"
        )
    try:
        run_budget = RunBudget(**{key: value for key, value in budget.items()})  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_STATE_MISMATCH"
        ) from exc
    if (
        checkpoint.get("checkpoint_version") != 1
        or checkpoint.get("checkpoint_sequence") != checkpoint_sequence
        or checkpoint.get("run_id") != plan.run_id
        or checkpoint.get("policy_version") != payload.get("policy_version")
        or checkpoint.get("task_length") != len(task)
        or checkpoint.get("recovery_status") != RecoveryStatus.READY.value
        or checkpoint.get("observation_epoch") != len(tool_steps)
        or checkpoint.get("verified_observation_epoch") != len(tool_steps)
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_CHECKPOINT_MISMATCH"
        )
    base_state = RunState(
        run_id=plan.run_id,
        task=task,
        policy_version=str(payload["policy_version"]),
        observation_epoch=len(tool_steps),
        verified_observation_epoch=len(tool_steps),
        budgets=run_budget,
        event_log=tuple(canonical_events),
        recovery_status=RecoveryStatus.READY,
    )
    terminal_state = _terminal_state(base_state, final_snapshot)
    terminal_recorded = len(trace) == base_event_count + 1
    if terminal_recorded:
        result = final_snapshot.result
        latency = final_snapshot.provider_latency_ms
        if result is None or latency is None:
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
            )
        terminal_trace = _trace_event(
            trace, base_event_count, kind="model_turn", run_id=plan.run_id
        )
        if set(terminal_trace) != {
            "trace_version",
            "sequence",
            "run_id",
            "kind",
            "text_length",
            "tool_call_count",
            "input_tokens",
            "output_tokens",
            "latency_ms",
        } or any(
            terminal_trace.get(key) != value
            for key, value in {
                "text_length": len(result.text),
                "tool_call_count": 0,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "latency_ms": latency,
            }.items()
        ):
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_TRACE_MISMATCH"
            )
    expected_state = terminal_state if terminal_recorded else base_state
    if (
        checkpoint.get("event_count") != len(expected_state.event_log)
        or checkpoint.get("budgets") != to_json_value(expected_state.budgets.__dict__)
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_CHECKPOINT_MISMATCH"
        )
    phase = checkpoint.get("phase")
    if terminal_recorded:
        if phase != "FAILED" or checkpoint.get("failure_code") != "EXECUTOR_FINAL_UNCERTAIN":
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_CHECKPOINT_MISMATCH"
            )
    elif phase == "FAILED":
        if checkpoint.get("failure_code") != "EXECUTOR_FINAL_UNCERTAIN":
            raise ExecutorFinalReconciliationError(
                "EXECUTOR_FINAL_RECONCILIATION_CHECKPOINT_MISMATCH"
            )
    elif phase != "PLANNING" or "failure_code" in checkpoint:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_CHECKPOINT_MISMATCH"
        )
    return base_state, terminal_state, terminal_recorded


def _terminal_state(
    state: RunState, final_snapshot: PersistedFinalResponse
) -> RunState:
    result = final_snapshot.result
    latency = final_snapshot.provider_latency_ms
    if result is None or latency is None:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_OUTCOME_UNCERTAIN"
        )
    usage = result.usage
    budget = replace(
        state.budgets,
        model_turns_used=state.budgets.model_turns_used + 1,
        input_tokens_used=state.budgets.input_tokens_used + (usage.input_tokens or 0),
    )
    terminal_event = LedgerEvent(
        event_id=f"{state.run_id}:event:{len(state.event_log) + 1}",
        kind=LedgerEventKind.MODEL_TURN,
        payload={
            "provider_response_id": result.provider_response_id,
            "text_length": len(result.text),
            "tool_call_count": 0,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "latency_ms": latency,
        },
    )
    return replace(
        state, budgets=budget, event_log=state.event_log + (terminal_event,)
    )


def compile_final_response_reconciliation(
    plan_snapshot: PersistedTaskPlan,
    final_snapshot: PersistedFinalResponse,
    envelope: ContinuationEnvelope,
    run_record: Mapping[str, object],
    *,
    task: str,
    expected_plan_sequence: int,
    expected_plan_digest: str,
    expected_final_sequence: int,
    expected_final_digest: str,
) -> PreparedFinalResponseReconciliation:
    """Reconstruct exact terminal evidence without mutating any artifact."""

    if (
        not isinstance(plan_snapshot, PersistedTaskPlan)
        or not isinstance(final_snapshot, PersistedFinalResponse)
        or not isinstance(envelope, ContinuationEnvelope)
        or not isinstance(run_record, Mapping)
        or not isinstance(task, str)
        or not task
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_INPUT_INVALID"
        )
    plan = plan_snapshot.plan
    if (
        plan_snapshot.sequence != expected_plan_sequence
        or plan.digest != expected_plan_digest
        or final_snapshot.sequence != expected_final_sequence
        or final_snapshot.envelope_digest != expected_final_digest
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_SNAPSHOT_STALE"
        )
    try:
        task_digest = sha256(task.encode("utf-8")).hexdigest()
        envelope = ContinuationEnvelope.from_payload(
            envelope.payload, expected_run_id=plan.run_id
        )
    except (UnicodeError, ContinuationError) as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        ) from exc
    payload = envelope.payload
    continuation_digest = payload.get("payload_digest")
    boundary = _mapping(payload.get("boundary"))
    if (
        plan.run_id != final_snapshot.run_id
        or plan.plan_id != final_snapshot.plan_id
        or plan.task_digest != task_digest
        or plan.registry_digest != reviewed_registry_digest()
        or payload.get("task") != task
        or payload.get("registry_digest") != plan.registry_digest
        or payload.get("checkpoint_sequence") != final_snapshot.checkpoint_sequence
        or continuation_digest != final_snapshot.continuation_digest
        or boundary.get("operation_kind") != "tool"
        or boundary.get("stage") != "completed"
        or boundary.get("effect") != "observation"
        or boundary.get("dispatch") != "dispatched"
        or boundary.get("next_step") != "provider_continue"
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_EVIDENCE_INVALID"
        )
    if (
        final_snapshot.stage is not FinalResponseStage.COMPLETED
        or final_snapshot.result is None
        or final_snapshot.provider_latency_ms is None
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_OUTCOME_UNCERTAIN"
        )
    final_step = plan.steps[-1]
    if (
        final_step.action is not PlanStepAction.FINAL_RESPONSE
        or final_step.step_id != final_snapshot.step_id
        or final_step.status not in {PlanStepStatus.IN_PROGRESS, PlanStepStatus.COMPLETED}
        or any(step.status is not PlanStepStatus.COMPLETED for step in plan.steps[:-1])
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_PLAN_UNSAFE"
        )
    try:
        source_plan = replace(
            plan,
            steps=plan.steps[:-1]
            + (replace(final_step, status=PlanStepStatus.PENDING),),
        )
    except (PlanValidationError, ValueError) as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_PLAN_UNSAFE"
        ) from exc
    transition_count = 1 if final_step.status is PlanStepStatus.IN_PROGRESS else 2
    if (
        final_snapshot.plan_digest != source_plan.digest
        or final_snapshot.snapshot_sequence + transition_count != plan_snapshot.sequence
    ):
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_PLAN_MISMATCH"
        )
    source_snapshot = PersistedTaskPlan(
        plan=source_plan,
        sequence=final_snapshot.snapshot_sequence,
        envelope_digest="0" * 64,
    )
    state, terminal_state, terminal_recorded = _reconstruct_state(
        source_snapshot,
        final_snapshot,
        envelope,
        run_record,
        task=task,
        checkpoint_sequence=final_snapshot.checkpoint_sequence,
    )
    try:
        request = compile_final_response_request(
            source_snapshot,
            state,
            expected_sequence=source_snapshot.sequence,
            expected_plan_digest=source_plan.digest,
            turn_id=final_snapshot.turn_id,
        )
    except ExecutorFinalError as exc:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_REQUEST_INVALID"
        ) from exc
    if request.request_digest != final_snapshot.request_digest:
        raise ExecutorFinalReconciliationError(
            "EXECUTOR_FINAL_RECONCILIATION_REQUEST_MISMATCH"
        )
    result = final_snapshot.result
    return PreparedFinalResponseReconciliation(
        run_id=plan.run_id,
        plan_id=plan.plan_id,
        step_id=final_step.step_id,
        expected_plan_sequence=plan_snapshot.sequence,
        expected_plan_digest=plan.digest,
        final_response_sequence=final_snapshot.sequence,
        final_response_digest=final_snapshot.envelope_digest,
        checkpoint_sequence=final_snapshot.checkpoint_sequence,
        continuation_digest=str(continuation_digest),
        plan_already_completed=final_step.status is PlanStepStatus.COMPLETED,
        terminal_event_already_recorded=terminal_recorded,
        terminal_state=terminal_state,
        result=result,
        provider_latency_ms=final_snapshot.provider_latency_ms,
    )


__all__ = [
    "ExecutorFinalReconciliationError",
    "PreparedFinalResponseReconciliation",
    "compile_final_response_reconciliation",
]
