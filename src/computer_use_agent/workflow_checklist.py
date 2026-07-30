"""Bounded Host-owned workflow checklist projection for operator UI.

This module describes human-readable workflow chapters, not executable plan
steps, tool calls, approval authority, or provider progress. Definitions must
come from reviewed Host code. A projection is immutable and rejects unordered
or contradictory state instead of guessing what happened.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Sequence


WORKFLOW_CHECKLIST_CONTRACT_VERSION = 1
MAX_WORKFLOW_STEPS = 32
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")


class WorkflowChecklistError(ValueError):
    """Fixed failure for an invalid operator checklist projection."""


class WorkflowStepStatus(str, Enum):
    """Truthful state of one fixed, human-readable workflow chapter."""

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNCERTAIN = "uncertain"


class WorkflowStatus(str, Enum):
    """Overall operator status, intentionally separate from step completion."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    NEEDS_INPUT = "needs_input"
    PAUSED = "paused"
    VERIFYING = "verifying"
    READY = "ready"
    FAILED = "failed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


def _require_identifier(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise WorkflowChecklistError(f"{field_name} is invalid")


def _require_text(value: str, field_name: str, *, max_length: int) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise WorkflowChecklistError(f"{field_name} is invalid")


@dataclass(frozen=True)
class WorkflowStepDefinition:
    """One reviewed chapter label with no execution or approval authority."""

    step_id: str
    label: str
    application: str

    def __post_init__(self) -> None:
        _require_identifier(self.step_id, "step_id")
        _require_text(self.label, "step label", max_length=120)
        _require_text(self.application, "step application", max_length=80)


@dataclass(frozen=True)
class WorkflowStepView:
    """One immutable checklist row derived from a reviewed definition."""

    step_id: str
    label: str
    application: str
    status: WorkflowStepStatus

    def __post_init__(self) -> None:
        _require_identifier(self.step_id, "step_id")
        _require_text(self.label, "step label", max_length=120)
        _require_text(self.application, "step application", max_length=80)
        if not isinstance(self.status, WorkflowStepStatus):
            raise WorkflowChecklistError("step status is invalid")


@dataclass(frozen=True)
class WorkflowChecklist:
    """Validated, linear checklist state suitable for passive presentation."""

    workflow_id: str
    title: str
    status: WorkflowStatus
    steps: tuple[WorkflowStepView, ...]
    current_step_id: str | None = None
    contract_version: int = WORKFLOW_CHECKLIST_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.workflow_id, "workflow_id")
        _require_text(self.title, "workflow title", max_length=160)
        if not isinstance(self.status, WorkflowStatus):
            raise WorkflowChecklistError("workflow status is invalid")
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version != WORKFLOW_CHECKLIST_CONTRACT_VERSION
        ):
            raise WorkflowChecklistError("workflow contract version is unsupported")
        if (
            not isinstance(self.steps, tuple)
            or not 1 <= len(self.steps) <= MAX_WORKFLOW_STEPS
            or not all(isinstance(step, WorkflowStepView) for step in self.steps)
        ):
            raise WorkflowChecklistError("workflow step count is outside the reviewed limit")
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise WorkflowChecklistError("workflow step identifiers must be unique")
        if self.current_step_id is not None:
            _require_identifier(self.current_step_id, "current_step_id")
            if self.current_step_id not in step_ids:
                raise WorkflowChecklistError("current workflow step is unknown")
        self._validate_status_order()

    def _validate_status_order(self) -> None:
        current_status = {
            WorkflowStatus.RUNNING: WorkflowStepStatus.IN_PROGRESS,
            WorkflowStatus.NEEDS_INPUT: WorkflowStepStatus.WAITING_APPROVAL,
            WorkflowStatus.PAUSED: WorkflowStepStatus.IN_PROGRESS,
            WorkflowStatus.VERIFYING: WorkflowStepStatus.IN_PROGRESS,
            WorkflowStatus.FAILED: WorkflowStepStatus.FAILED,
            WorkflowStatus.UNCERTAIN: WorkflowStepStatus.UNCERTAIN,
        }.get(self.status)
        current_indexes = [
            index
            for index, step in enumerate(self.steps)
            if step.status
            in {
                WorkflowStepStatus.IN_PROGRESS,
                WorkflowStepStatus.WAITING_APPROVAL,
                WorkflowStepStatus.FAILED,
                WorkflowStepStatus.UNCERTAIN,
            }
        ]

        if current_status is None:
            if self.current_step_id is not None or current_indexes:
                raise WorkflowChecklistError("terminal workflow cannot have a current step")
        else:
            if len(current_indexes) != 1 or self.current_step_id is None:
                raise WorkflowChecklistError("workflow requires exactly one current step")
            current = self.steps[current_indexes[0]]
            if current.step_id != self.current_step_id or current.status is not current_status:
                raise WorkflowChecklistError("current workflow step does not match status")

        resolved = {WorkflowStepStatus.COMPLETED, WorkflowStepStatus.SKIPPED}
        if self.status is WorkflowStatus.NOT_STARTED:
            if any(step.status is not WorkflowStepStatus.NOT_STARTED for step in self.steps):
                raise WorkflowChecklistError("not-started workflow contains progressed steps")
            return
        if self.status is WorkflowStatus.READY:
            if any(step.status not in resolved for step in self.steps):
                raise WorkflowChecklistError("ready workflow contains unresolved steps")
            return

        boundary = current_indexes[0] if current_indexes else next(
            (
                index
                for index, step in enumerate(self.steps)
                if step.status is WorkflowStepStatus.NOT_STARTED
            ),
            len(self.steps),
        )
        if any(step.status not in resolved for step in self.steps[:boundary]):
            raise WorkflowChecklistError("resolved workflow steps must form an ordered prefix")
        if any(
            step.status is not WorkflowStepStatus.NOT_STARTED
            for step in self.steps[boundary + (1 if current_indexes else 0) :]
        ):
            raise WorkflowChecklistError("future workflow steps must remain not started")

    @property
    def completed_count(self) -> int:
        return sum(step.status is WorkflowStepStatus.COMPLETED for step in self.steps)

    @property
    def skipped_count(self) -> int:
        return sum(step.status is WorkflowStepStatus.SKIPPED for step in self.steps)

    @property
    def not_started_count(self) -> int:
        return sum(step.status is WorkflowStepStatus.NOT_STARTED for step in self.steps)

    @property
    def current_step_number(self) -> int | None:
        if self.current_step_id is None:
            return None
        return next(
            index
            for index, step in enumerate(self.steps, start=1)
            if step.step_id == self.current_step_id
        )


@dataclass(frozen=True)
class WorkflowDefinition:
    """Reviewed linear workflow used to construct truthful UI snapshots."""

    workflow_id: str
    title: str
    steps: tuple[WorkflowStepDefinition, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.workflow_id, "workflow_id")
        _require_text(self.title, "workflow title", max_length=160)
        if (
            not isinstance(self.steps, tuple)
            or not 1 <= len(self.steps) <= MAX_WORKFLOW_STEPS
            or not all(isinstance(step, WorkflowStepDefinition) for step in self.steps)
        ):
            raise WorkflowChecklistError("workflow step count is outside the reviewed limit")
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise WorkflowChecklistError("workflow step identifiers must be unique")

    def project(
        self,
        status: WorkflowStatus,
        *,
        completed_step_ids: Sequence[str] = (),
        skipped_step_ids: Sequence[str] = (),
        current_step_id: str | None = None,
    ) -> WorkflowChecklist:
        """Build a snapshot while preserving ordered, non-overlapping state."""

        if not isinstance(status, WorkflowStatus):
            raise WorkflowChecklistError("workflow status is invalid")
        completed = tuple(completed_step_ids)
        skipped = tuple(skipped_step_ids)
        if (
            len(set(completed)) != len(completed)
            or len(set(skipped)) != len(skipped)
            or set(completed) & set(skipped)
        ):
            raise WorkflowChecklistError("workflow completion sets are invalid")
        known = {step.step_id for step in self.steps}
        if not set(completed) | set(skipped) <= known:
            raise WorkflowChecklistError("workflow completion references an unknown step")
        if current_step_id is not None and current_step_id in set(completed) | set(skipped):
            raise WorkflowChecklistError("current workflow step is already resolved")

        current_status = {
            WorkflowStatus.RUNNING: WorkflowStepStatus.IN_PROGRESS,
            WorkflowStatus.NEEDS_INPUT: WorkflowStepStatus.WAITING_APPROVAL,
            WorkflowStatus.PAUSED: WorkflowStepStatus.IN_PROGRESS,
            WorkflowStatus.VERIFYING: WorkflowStepStatus.IN_PROGRESS,
            WorkflowStatus.FAILED: WorkflowStepStatus.FAILED,
            WorkflowStatus.UNCERTAIN: WorkflowStepStatus.UNCERTAIN,
        }.get(status)
        if (current_status is None) is not (current_step_id is None):
            raise WorkflowChecklistError("workflow current step does not match status")

        rows = tuple(
            WorkflowStepView(
                step.step_id,
                step.label,
                step.application,
                (
                    WorkflowStepStatus.COMPLETED
                    if step.step_id in completed
                    else WorkflowStepStatus.SKIPPED
                    if step.step_id in skipped
                    else current_status
                    if step.step_id == current_step_id and current_status is not None
                    else WorkflowStepStatus.NOT_STARTED
                ),
            )
            for step in self.steps
        )
        return WorkflowChecklist(
            workflow_id=self.workflow_id,
            title=self.title,
            status=status,
            steps=rows,
            current_step_id=current_step_id,
        )


__all__ = [
    "MAX_WORKFLOW_STEPS",
    "WORKFLOW_CHECKLIST_CONTRACT_VERSION",
    "WorkflowChecklist",
    "WorkflowChecklistError",
    "WorkflowDefinition",
    "WorkflowStatus",
    "WorkflowStepDefinition",
    "WorkflowStepStatus",
    "WorkflowStepView",
]
