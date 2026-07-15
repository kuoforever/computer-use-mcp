"""Strict, non-executable task-plan contract for the Agent Host.

Plans are untrusted declarative data. Compiling or transitioning a plan never
calls a provider, policy, approval port, MCP bridge, or desktop driver and does
not authorize any tool call.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping, Sequence

from .tool_registry import (
    ToolValidationError,
    get_tool_spec,
    reviewed_registry_digest,
    validate_tool_arguments,
)
from .types import JSONValue, ToolEffect, to_json_value


PLAN_CONTRACT_VERSION = 1
MAX_PLAN_STEPS = 16
MAX_PLAN_CANDIDATE_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class PlanValidationError(ValueError):
    """A fixed, non-sensitive failure for an invalid task-plan candidate."""


class PlanStepAction(str, Enum):
    TOOL = "tool"
    FINAL_RESPONSE = "final_response"


class PlanStepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class TaskPlanStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PlanValidationError(f"{field_name} is invalid")


def _require_digest(value: str, field_name: str) -> None:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise PlanValidationError(f"{field_name} must be a SHA-256 digest")


def _freeze_json(value: JSONValue) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_arguments(arguments: Mapping[str, object]) -> Mapping[str, JSONValue]:
    copied = to_json_value(arguments)
    if not isinstance(copied, dict):
        raise PlanValidationError("plan step arguments must be an object")
    frozen = _freeze_json(copied)
    if not isinstance(frozen, Mapping):
        raise PlanValidationError("plan step arguments must be an object")
    return frozen  # type: ignore[return-value]


@dataclass(frozen=True)
class PlanStep:
    """One host-normalized declarative step; it is never an executable call."""

    step_id: str
    action: PlanStepAction
    status: PlanStepStatus = PlanStepStatus.PENDING
    tool_name: str | None = None
    arguments: Mapping[str, JSONValue] = field(
        default_factory=lambda: MappingProxyType({})
    )
    effect: ToolEffect | None = None
    requires_approval: bool = False

    def __post_init__(self) -> None:
        _require_identifier(self.step_id, "step_id")
        if not isinstance(self.action, PlanStepAction):
            raise PlanValidationError("action is invalid")
        if not isinstance(self.status, PlanStepStatus):
            raise PlanValidationError("status is invalid")
        if not isinstance(self.arguments, Mapping):
            raise PlanValidationError("arguments must be an object")
        if not isinstance(self.requires_approval, bool):
            raise PlanValidationError("requires_approval must be boolean")
        object.__setattr__(self, "arguments", _freeze_arguments(self.arguments))
        if self.action is PlanStepAction.FINAL_RESPONSE:
            if (
                self.tool_name is not None
                or self.arguments
                or self.effect is not None
                or self.requires_approval
            ):
                raise PlanValidationError("final_response cannot carry tool authority")
            return
        if not isinstance(self.tool_name, str) or not self.tool_name:
            raise PlanValidationError("tool step requires a tool name")
        if not isinstance(self.effect, ToolEffect):
            raise PlanValidationError("tool step requires a reviewed effect")
        try:
            spec = get_tool_spec(self.tool_name)
        except ToolValidationError as exc:
            raise PlanValidationError("tool step references an unreviewed tool") from exc
        if spec.sensitive_arguments:
            raise PlanValidationError("plan steps cannot retain sensitive tool arguments")
        try:
            validated_arguments = validate_tool_arguments(self.tool_name, self.arguments)
        except ToolValidationError as exc:
            raise PlanValidationError("plan step tool arguments are invalid") from exc
        object.__setattr__(self, "arguments", _freeze_arguments(validated_arguments))
        if self.effect is not spec.effect or self.requires_approval is not spec.requires_host_approval:
            raise PlanValidationError("tool metadata does not match the reviewed registry")


@dataclass(frozen=True)
class TaskPlan:
    """Digest-bound plan state with strictly ordered, bounded steps."""

    plan_id: str
    run_id: str
    task_digest: str
    registry_digest: str
    steps: tuple[PlanStep, ...]
    contract_version: int = PLAN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.plan_id, "plan_id")
        _require_identifier(self.run_id, "run_id")
        _require_digest(self.task_digest, "task_digest")
        _require_digest(self.registry_digest, "registry_digest")
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version != PLAN_CONTRACT_VERSION
        ):
            raise PlanValidationError("plan contract version is unsupported")
        if not isinstance(self.steps, tuple) or not 1 <= len(self.steps) <= MAX_PLAN_STEPS:
            raise PlanValidationError("plan step count is outside the reviewed limit")
        if not all(isinstance(step, PlanStep) for step in self.steps):
            raise PlanValidationError("steps must contain PlanStep values")
        expected_ids = tuple(f"step_{index}" for index in range(1, len(self.steps) + 1))
        if tuple(step.step_id for step in self.steps) != expected_ids:
            raise PlanValidationError("plan step identifiers must be host-ordered")
        final_indexes = [
            index
            for index, step in enumerate(self.steps)
            if step.action is PlanStepAction.FINAL_RESPONSE
        ]
        if final_indexes != [len(self.steps) - 1]:
            raise PlanValidationError("plan requires exactly one final response as its last step")
        self._validate_status_order()

    def _validate_status_order(self) -> None:
        first_noncompleted = next(
            (
                index
                for index, step in enumerate(self.steps)
                if step.status is not PlanStepStatus.COMPLETED
            ),
            len(self.steps),
        )
        if any(
            step.status is PlanStepStatus.COMPLETED
            for step in self.steps[first_noncompleted + 1 :]
        ):
            raise PlanValidationError("completed plan steps must form an ordered prefix")
        active = [
            index
            for index, step in enumerate(self.steps)
            if step.status is PlanStepStatus.IN_PROGRESS
        ]
        if len(active) > 1 or (active and active[0] != first_noncompleted):
            raise PlanValidationError("only the next ordered step may be in progress")
        terminal = [
            index
            for index, step in enumerate(self.steps)
            if step.status
            in {PlanStepStatus.FAILED, PlanStepStatus.BLOCKED, PlanStepStatus.CANCELLED}
        ]
        if len(terminal) > 1 or (terminal and terminal[0] != first_noncompleted):
            raise PlanValidationError("only the next ordered step may stop the plan")
        if terminal and any(
            step.status is not PlanStepStatus.PENDING
            for step in self.steps[terminal[0] + 1 :]
        ):
            raise PlanValidationError("steps after a terminal plan step must remain pending")

    @property
    def status(self) -> TaskPlanStatus:
        statuses = tuple(step.status for step in self.steps)
        if PlanStepStatus.FAILED in statuses:
            return TaskPlanStatus.FAILED
        if PlanStepStatus.BLOCKED in statuses:
            return TaskPlanStatus.BLOCKED
        if PlanStepStatus.CANCELLED in statuses:
            return TaskPlanStatus.CANCELLED
        if all(status is PlanStepStatus.COMPLETED for status in statuses):
            return TaskPlanStatus.COMPLETED
        if any(
            status in {PlanStepStatus.IN_PROGRESS, PlanStepStatus.COMPLETED}
            for status in statuses
        ):
            return TaskPlanStatus.IN_PROGRESS
        return TaskPlanStatus.PENDING

    @property
    def digest(self) -> str:
        material = {
            "contract_version": self.contract_version,
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "task_digest": self.task_digest,
            "registry_digest": self.registry_digest,
            "steps": [
                {
                    "step_id": step.step_id,
                    "action": step.action.value,
                    "status": step.status.value,
                    "tool_name": step.tool_name,
                    "arguments": to_json_value(step.arguments),
                    "effect": None if step.effect is None else step.effect.value,
                    "requires_approval": step.requires_approval,
                }
                for step in self.steps
            ],
        }
        encoded = json.dumps(
            material, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


def _parse_candidate(candidate: str) -> dict[str, object]:
    if not isinstance(candidate, str) or not candidate:
        raise PlanValidationError("plan candidate must be non-empty JSON text")
    if len(candidate.encode("utf-8")) > MAX_PLAN_CANDIDATE_BYTES:
        raise PlanValidationError("plan candidate exceeds the reviewed byte limit")
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise PlanValidationError("plan candidate is not valid bounded JSON") from exc
    if not isinstance(value, dict):
        raise PlanValidationError("plan candidate must be a JSON object")
    return value


def _validated_allowed_tools(allowed_tools: Sequence[str]) -> frozenset[str]:
    if isinstance(allowed_tools, (str, bytes)) or not isinstance(allowed_tools, Sequence):
        raise PlanValidationError("allowed_tools must be an explicit sequence")
    names = tuple(allowed_tools)
    if not all(isinstance(name, str) and name for name in names):
        raise PlanValidationError("allowed_tools contains an invalid name")
    if len(names) != len(set(names)):
        raise PlanValidationError("allowed_tools contains duplicates")
    try:
        for name in names:
            get_tool_spec(name)
    except ToolValidationError as exc:
        raise PlanValidationError("allowed_tools contains an unreviewed tool") from exc
    return frozenset(names)


def compile_task_plan(
    candidate: str,
    *,
    plan_id: str,
    run_id: str,
    task: str,
    allowed_tools: Sequence[str],
) -> TaskPlan:
    """Compile untrusted JSON into a non-executable, registry-bound task plan."""

    _require_identifier(plan_id, "plan_id")
    _require_identifier(run_id, "run_id")
    if not isinstance(task, str) or not task:
        raise PlanValidationError("task must be non-empty")
    allowed = _validated_allowed_tools(allowed_tools)
    value = _parse_candidate(candidate)
    if set(value) != {"version", "steps"}:
        raise PlanValidationError("plan candidate fields do not match the contract")
    if (
        not isinstance(value["version"], int)
        or isinstance(value["version"], bool)
        or value["version"] != PLAN_CONTRACT_VERSION
    ):
        raise PlanValidationError("plan candidate version is unsupported")
    raw_steps = value["steps"]
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_PLAN_STEPS:
        raise PlanValidationError("plan candidate step count is outside the reviewed limit")

    steps: list[PlanStep] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict) or not isinstance(raw_step.get("action"), str):
            raise PlanValidationError("plan candidate contains a malformed step")
        action = raw_step["action"]
        if action == PlanStepAction.FINAL_RESPONSE.value:
            if set(raw_step) != {"action"}:
                raise PlanValidationError("final_response step contains unknown fields")
            steps.append(
                PlanStep(step_id=f"step_{index}", action=PlanStepAction.FINAL_RESPONSE)
            )
            continue
        if action != PlanStepAction.TOOL.value or set(raw_step) != {
            "action",
            "tool",
            "arguments",
        }:
            raise PlanValidationError("tool step fields do not match the contract")
        tool_name = raw_step["tool"]
        arguments = raw_step["arguments"]
        if not isinstance(tool_name, str) or tool_name not in allowed:
            raise PlanValidationError("plan candidate requested a tool outside host scope")
        if not isinstance(arguments, dict):
            raise PlanValidationError("plan step arguments must be an object")
        spec = get_tool_spec(tool_name)
        if spec.sensitive_arguments:
            raise PlanValidationError("plan candidates cannot retain sensitive tool arguments")
        try:
            validated_arguments = validate_tool_arguments(tool_name, arguments)
        except ToolValidationError as exc:
            raise PlanValidationError("plan step tool arguments are invalid") from exc
        steps.append(
            PlanStep(
                step_id=f"step_{index}",
                action=PlanStepAction.TOOL,
                tool_name=tool_name,
                arguments=validated_arguments,
                effect=spec.effect,
                requires_approval=spec.requires_host_approval,
            )
        )

    return TaskPlan(
        plan_id=plan_id,
        run_id=run_id,
        task_digest=sha256(task.encode("utf-8")).hexdigest(),
        registry_digest=reviewed_registry_digest(),
        steps=tuple(steps),
    )


def transition_plan_step(
    plan: TaskPlan, step_id: str, target: PlanStepStatus
) -> TaskPlan:
    """Return a new plan after one legal, ordered local status transition."""

    if not isinstance(plan, TaskPlan):
        raise PlanValidationError("plan must be a TaskPlan")
    _require_identifier(step_id, "step_id")
    if not isinstance(target, PlanStepStatus):
        raise PlanValidationError("target status is invalid")
    if plan.status in {
        TaskPlanStatus.COMPLETED,
        TaskPlanStatus.FAILED,
        TaskPlanStatus.BLOCKED,
        TaskPlanStatus.CANCELLED,
    }:
        raise PlanValidationError("terminal plans cannot transition")
    try:
        index = next(index for index, step in enumerate(plan.steps) if step.step_id == step_id)
    except StopIteration as exc:
        raise PlanValidationError("plan step does not exist") from exc
    current = plan.steps[index].status
    allowed_targets = {
        PlanStepStatus.PENDING: {
            PlanStepStatus.IN_PROGRESS,
            PlanStepStatus.BLOCKED,
            PlanStepStatus.CANCELLED,
        },
        PlanStepStatus.IN_PROGRESS: {
            PlanStepStatus.COMPLETED,
            PlanStepStatus.FAILED,
            PlanStepStatus.BLOCKED,
            PlanStepStatus.CANCELLED,
        },
    }.get(current, set())
    if target not in allowed_targets:
        raise PlanValidationError("plan step transition is illegal")
    first_noncompleted = next(
        (
            position
            for position, step in enumerate(plan.steps)
            if step.status is not PlanStepStatus.COMPLETED
        ),
        len(plan.steps),
    )
    if index != first_noncompleted:
        raise PlanValidationError("only the next ordered plan step may transition")
    updated = list(plan.steps)
    updated[index] = replace(updated[index], status=target)
    return replace(plan, steps=tuple(updated))


__all__ = [
    "MAX_PLAN_CANDIDATE_BYTES",
    "MAX_PLAN_STEPS",
    "PLAN_CONTRACT_VERSION",
    "PlanStep",
    "PlanStepAction",
    "PlanStepStatus",
    "PlanValidationError",
    "TaskPlan",
    "TaskPlanStatus",
    "compile_task_plan",
    "transition_plan_step",
]
