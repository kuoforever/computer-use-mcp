"""Pure final-response request contract for a completed observation plan.

The compiler performs no provider or desktop I/O. Historical calls and results
are validated only as input evidence and are projected into inert observation
data; they never become executable ``ToolCall`` values on this boundary.
"""
from __future__ import annotations

import json
from base64 import b64encode
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol, runtime_checkable

from .executor import MAX_EXECUTOR_SESSION_STEPS
from .plan_store import PersistedTaskPlan
from .planning import PlanStepAction, PlanStepStatus
from .tool_registry import reviewed_registry_digest
from .types import (
    DispatchCertainty,
    ImageContent,
    LedgerEventKind,
    RecoveryStatus,
    RunState,
    ToolEffect,
    ToolResultStatus,
    ModelUsage,
    to_json_value,
)


MAX_FINAL_RESPONSE_REQUEST_BYTES = 48 * 1024 * 1024


class ExecutorFinalError(RuntimeError):
    """A fixed rejection from final-response request compilation."""


@dataclass(frozen=True, repr=False)
class FinalResponseObservation:
    """One inert, lossless observation supplied as untrusted provider input."""

    step_id: str
    tool_name: str
    arguments_json: str
    sanitized_text: str = field(repr=False)
    images: tuple[ImageContent, ...] = field(default=(), repr=False)

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.step_id, self.tool_name, self.arguments_json)
        ):
            raise ValueError("final observation identity must be non-empty")
        if not isinstance(self.sanitized_text, str):
            raise ValueError("sanitized_text must be a string")
        if not isinstance(self.images, tuple) or not all(
            isinstance(image, ImageContent) for image in self.images
        ):
            raise ValueError("images must contain ImageContent values")
        try:
            decoded = json.loads(self.arguments_json)
        except json.JSONDecodeError as exc:
            raise ValueError("arguments_json must be canonical JSON") from exc
        if (
            not isinstance(decoded, dict)
            or json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            != self.arguments_json
        ):
            raise ValueError("arguments_json must be canonical JSON")

    def __repr__(self) -> str:
        return (
            "FinalResponseObservation("
            f"step_id={self.step_id!r}, tool_name={self.tool_name!r}, "
            f"arguments_bytes={len(self.arguments_json.encode('utf-8'))}, "
            f"text_length={len(self.sanitized_text)}, image_count={len(self.images)})"
        )


@dataclass(frozen=True, repr=False)
class FinalResponseRequest:
    """Bounded tool-free input for a future one-shot final-response adapter."""

    run_id: str
    plan_id: str
    plan_digest: str
    snapshot_sequence: int
    turn_id: str
    task: str = field(repr=False)
    observations: tuple[FinalResponseObservation, ...] = field(repr=False)
    request_digest: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (
                self.run_id,
                self.plan_id,
                self.plan_digest,
                self.turn_id,
                self.task,
                self.request_digest,
            )
        ):
            raise ValueError("final-response request fields must be non-empty")
        if (
            isinstance(self.snapshot_sequence, bool)
            or not isinstance(self.snapshot_sequence, int)
            or self.snapshot_sequence < 0
        ):
            raise ValueError("snapshot_sequence must be non-negative")
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, FinalResponseObservation) for item in self.observations
        ):
            raise ValueError("observations must contain FinalResponseObservation values")
        if not 1 <= len(self.observations) <= MAX_EXECUTOR_SESSION_STEPS:
            raise ValueError("observations must remain within the Executor step cap")
        for name, value in (
            ("plan_digest", self.plan_digest),
            ("request_digest", self.request_digest),
        ):
            try:
                if len(value) != 64:
                    raise ValueError
                int(value, 16)
            except ValueError as exc:
                raise ValueError(f"{name} must be a SHA-256 digest") from exc
        payload = _request_payload(
            run_id=self.run_id,
            plan_id=self.plan_id,
            plan_digest=self.plan_digest,
            snapshot_sequence=self.snapshot_sequence,
            turn_id=self.turn_id,
            task=self.task,
            observations=self.observations,
        )
        encoded = _canonical(payload)
        if len(encoded) > MAX_FINAL_RESPONSE_REQUEST_BYTES:
            raise ValueError("final-response request is too large")
        if sha256(encoded).hexdigest() != self.request_digest:
            raise ValueError("request_digest does not match final-response data")

    def __repr__(self) -> str:
        return (
            "FinalResponseRequest("
            f"run_id={self.run_id!r}, plan_id={self.plan_id!r}, "
            f"snapshot_sequence={self.snapshot_sequence}, turn_id={self.turn_id!r}, "
            f"task_length={len(self.task)}, observation_count={len(self.observations)}, "
            f"request_digest={self.request_digest!r})"
        )


@dataclass(frozen=True, repr=False)
class FinalResponseResult:
    """One bounded provider result; text remains sensitive and untrusted."""

    run_id: str
    turn_id: str
    provider_response_id: str
    text: str = field(repr=False)
    usage: ModelUsage

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str) and value
            for value in (self.run_id, self.turn_id, self.provider_response_id)
        ):
            raise ValueError("final-response result identity must be non-empty")
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("final-response result text must be non-empty")
        if not isinstance(self.usage, ModelUsage):
            raise ValueError("usage must be ModelUsage")

    def __repr__(self) -> str:
        return (
            "FinalResponseResult("
            f"run_id={self.run_id!r}, turn_id={self.turn_id!r}, "
            f"provider_response_id={self.provider_response_id!r}, "
            f"text_length={len(self.text)}, usage={self.usage!r})"
        )


@runtime_checkable
class FinalResponsePort(Protocol):
    """Tool-free one-shot adapter; returned text remains untrusted data."""

    async def create_final_response(
        self, request: FinalResponseRequest
    ) -> FinalResponseResult: ...


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ExecutorFinalError("EXECUTOR_FINAL_REQUEST_INVALID") from exc


def _request_payload(
    *,
    run_id: str,
    plan_id: str,
    plan_digest: str,
    snapshot_sequence: int,
    turn_id: str,
    task: str,
    observations: tuple[FinalResponseObservation, ...],
) -> dict[str, object]:
    return {
        "version": 1,
        "run_id": run_id,
        "plan_id": plan_id,
        "plan_digest": plan_digest,
        "snapshot_sequence": snapshot_sequence,
        "turn_id": turn_id,
        "task": task,
        "observations": [
            {
                "step_id": item.step_id,
                "tool_name": item.tool_name,
                "arguments": json.loads(item.arguments_json),
                "sanitized_text": item.sanitized_text,
                "images": [
                    {
                        "mime_type": image.mime_type,
                        "data": b64encode(image.data).decode("ascii"),
                        "width": image.width,
                        "height": image.height,
                    }
                    for image in item.images
                ],
            }
            for item in observations
        ],
    }


def compile_final_response_request(
    snapshot: PersistedTaskPlan,
    state: RunState,
    *,
    expected_sequence: int,
    expected_plan_digest: str,
    turn_id: str,
) -> FinalResponseRequest:
    """Compile exact completed observation evidence into inert provider input."""

    if not isinstance(snapshot, PersistedTaskPlan) or not isinstance(state, RunState):
        raise ExecutorFinalError("EXECUTOR_FINAL_INPUT_INVALID")
    if (
        isinstance(expected_sequence, bool)
        or not isinstance(expected_sequence, int)
        or expected_sequence < 0
        or not isinstance(expected_plan_digest, str)
        or not isinstance(turn_id, str)
        or not turn_id
    ):
        raise ExecutorFinalError("EXECUTOR_FINAL_EXPECTATION_INVALID")
    plan = snapshot.plan
    if snapshot.sequence != expected_sequence or plan.digest != expected_plan_digest:
        raise ExecutorFinalError("EXECUTOR_FINAL_PLAN_STALE")
    try:
        task_digest = sha256(state.task.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise ExecutorFinalError("EXECUTOR_FINAL_IDENTITY_MISMATCH") from exc
    if (
        plan.run_id != state.run_id
        or plan.task_digest != task_digest
        or plan.registry_digest != reviewed_registry_digest()
    ):
        raise ExecutorFinalError("EXECUTOR_FINAL_IDENTITY_MISMATCH")

    tool_steps = tuple(
        step for step in plan.steps if step.action is PlanStepAction.TOOL
    )
    final_steps = tuple(
        step for step in plan.steps if step.action is PlanStepAction.FINAL_RESPONSE
    )
    if (
        not tool_steps
        or len(tool_steps) > MAX_EXECUTOR_SESSION_STEPS
        or any(
            step.status is not PlanStepStatus.COMPLETED
            or step.effect is not ToolEffect.OBSERVATION
            for step in tool_steps
        )
        or len(final_steps) != 1
        or final_steps[0] is not plan.steps[-1]
        or final_steps[0].status is not PlanStepStatus.PENDING
    ):
        raise ExecutorFinalError("EXECUTOR_FINAL_PLAN_NOT_READY")
    if (
        state.recovery_status is not RecoveryStatus.READY
        or state.verified_observation_epoch != state.observation_epoch
        or state.observation_epoch != len(tool_steps)
        or state.budgets.model_turns_used != 0
        or state.budgets.tool_calls_used != len(tool_steps)
        or state.budgets.side_effects_used != 0
        or state.budgets.input_tokens_used != 0
        or state.budgets.model_turns_used >= state.budgets.max_model_turns
        or state.budgets.input_tokens_used >= state.budgets.max_input_tokens
    ):
        raise ExecutorFinalError("EXECUTOR_FINAL_STATE_NOT_READY")

    events = state.event_log
    if len(events) != 1 + 3 * len(tool_steps):
        raise ExecutorFinalError("EXECUTOR_FINAL_LEDGER_INVALID")
    first = events[0]
    if (
        first.kind is not LedgerEventKind.USER_TASK
        or first.identity is not None
        or set(first.payload) != {"task_length"}
        or first.payload.get("task_length") != len(state.task)
    ):
        raise ExecutorFinalError("EXECUTOR_FINAL_LEDGER_INVALID")

    observations: list[FinalResponseObservation] = []
    for index, step in enumerate(tool_steps):
        call_event, result_event, observation_event = events[1 + index * 3 : 4 + index * 3]
        if (
            call_event.kind is not LedgerEventKind.TOOL_CALL
            or result_event.kind is not LedgerEventKind.TOOL_RESULT
            or observation_event.kind is not LedgerEventKind.OBSERVATION
            or call_event.identity is None
            or call_event.identity != result_event.identity
            or call_event.identity != observation_event.identity
            or call_event.safe_argument_summary is None
            or call_event.payload
            or call_event.safe_argument_summary.tool_name != step.tool_name
            or call_event.safe_argument_summary.redacted_fields
            or to_json_value(call_event.safe_argument_summary.values)
            != to_json_value(step.arguments)
            or result_event.tool_result is None
            or set(result_event.payload) - {"latency_ms"}
            or result_event.tool_result.tool_name != step.tool_name
            or result_event.tool_result.status is not ToolResultStatus.SUCCESS
            or result_event.tool_result.dispatch is not DispatchCertainty.DISPATCHED
            or observation_event.payload.get("tool_name") != step.tool_name
            or observation_event.payload.get("observation_epoch") != index + 1
            or set(observation_event.payload) != {"tool_name", "observation_epoch"}
            or call_event.identity.run_id != state.run_id
            or call_event.identity.turn_id != f"executor_turn_{index + 1}"
        ):
            raise ExecutorFinalError("EXECUTOR_FINAL_LEDGER_INVALID")
        latency = result_event.payload.get("latency_ms")
        if latency is not None and (
            isinstance(latency, bool) or not isinstance(latency, int) or latency < 0
        ):
            raise ExecutorFinalError("EXECUTOR_FINAL_LEDGER_INVALID")
        arguments_json = _canonical(to_json_value(step.arguments)).decode("utf-8")
        result = result_event.tool_result
        observations.append(
            FinalResponseObservation(
                step_id=step.step_id,
                tool_name=step.tool_name,
                arguments_json=arguments_json,
                sanitized_text=result.sanitized_text,
                images=result.images,
            )
        )

    frozen_observations = tuple(observations)
    payload = _request_payload(
        run_id=plan.run_id,
        plan_id=plan.plan_id,
        plan_digest=plan.digest,
        snapshot_sequence=snapshot.sequence,
        turn_id=turn_id,
        task=state.task,
        observations=frozen_observations,
    )
    encoded = _canonical(payload)
    if len(encoded) > MAX_FINAL_RESPONSE_REQUEST_BYTES:
        raise ExecutorFinalError("EXECUTOR_FINAL_REQUEST_TOO_LARGE")
    return FinalResponseRequest(
        run_id=plan.run_id,
        plan_id=plan.plan_id,
        plan_digest=plan.digest,
        snapshot_sequence=snapshot.sequence,
        turn_id=turn_id,
        task=state.task,
        observations=frozen_observations,
        request_digest=sha256(encoded).hexdigest(),
    )


__all__ = [
    "ExecutorFinalError",
    "FinalResponseObservation",
    "FinalResponsePort",
    "FinalResponseRequest",
    "FinalResponseResult",
    "MAX_FINAL_RESPONSE_REQUEST_BYTES",
    "compile_final_response_request",
]
