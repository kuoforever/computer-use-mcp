"""Private atomic persistence for non-executable task plans.

The store is intentionally disconnected from provider, policy, approval, MCP,
and desktop ports. Mutations require the caller's acquired application RunLock
and compare the exact persisted sequence and plan digest before replacement.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .planning import (
    PlanStep,
    PlanStepAction,
    PlanStepStatus,
    PlanValidationError,
    TaskPlan,
    TaskPlanStatus,
    transition_plan_step,
)
from .run_lock import RunLock
from .tool_registry import reviewed_registry_digest
from .types import ToolEffect, to_json_value


PLAN_STORE_VERSION = 1
MAX_PERSISTED_PLAN_BYTES = 128 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_ENVELOPE_FIELDS = frozenset(
    {"store_version", "sequence", "plan", "plan_digest", "envelope_digest"}
)
_PLAN_FIELDS = frozenset(
    {"contract_version", "plan_id", "run_id", "task_digest", "registry_digest", "steps"}
)
_STEP_FIELDS = frozenset(
    {
        "step_id",
        "action",
        "status",
        "tool_name",
        "arguments",
        "effect",
        "requires_approval",
    }
)


class PlanStoreError(RuntimeError):
    """Fixed persistence failure that never embeds plan or task content."""


@dataclass(frozen=True)
class PersistedTaskPlan:
    """One strictly validated private plan snapshot."""

    plan: TaskPlan
    sequence: int
    envelope_digest: str


def _canonical(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PlanStoreError("PLAN_STORE_INVALID") from exc


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise PlanStoreError("PLAN_STORE_INVALID")
    return value


def _require_sequence(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PlanStoreError("PLAN_STORE_INVALID")
    return value


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PlanStoreError("PLAN_STORE_INVALID")
    return value


def _is_unsafe_path(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse)


def task_plan_path(state_dir: Path, run_id: str) -> Path:
    """Return the private plan path after strict path-shape validation."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    _require_identifier(run_id)
    return state_dir / "runs" / run_id / "task-plan.json"


def _plan_payload(plan: TaskPlan) -> dict[str, object]:
    return {
        "contract_version": plan.contract_version,
        "plan_id": plan.plan_id,
        "run_id": plan.run_id,
        "task_digest": plan.task_digest,
        "registry_digest": plan.registry_digest,
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
            for step in plan.steps
        ],
    }


def _decode_plan(value: object, *, expected_run_id: str) -> TaskPlan:
    if not isinstance(value, Mapping) or set(value) != _PLAN_FIELDS:
        raise PlanStoreError("PLAN_STORE_INVALID")
    if value.get("run_id") != expected_run_id:
        raise PlanStoreError("PLAN_STORE_IDENTITY_MISMATCH")
    raw_steps = value.get("steps")
    if not isinstance(raw_steps, list):
        raise PlanStoreError("PLAN_STORE_INVALID")
    steps: list[PlanStep] = []
    try:
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping) or set(raw_step) != _STEP_FIELDS:
                raise PlanStoreError("PLAN_STORE_INVALID")
            raw_arguments = raw_step.get("arguments")
            if not isinstance(raw_arguments, Mapping):
                raise PlanStoreError("PLAN_STORE_INVALID")
            raw_effect = raw_step.get("effect")
            effect = None if raw_effect is None else ToolEffect(raw_effect)
            steps.append(
                PlanStep(
                    step_id=_require_identifier(raw_step.get("step_id")),
                    action=PlanStepAction(raw_step.get("action")),
                    status=PlanStepStatus(raw_step.get("status")),
                    tool_name=raw_step.get("tool_name"),
                    arguments=raw_arguments,
                    effect=effect,
                    requires_approval=raw_step.get("requires_approval"),
                )
            )
        plan = TaskPlan(
            contract_version=value.get("contract_version"),
            plan_id=_require_identifier(value.get("plan_id")),
            run_id=expected_run_id,
            task_digest=_require_digest(value.get("task_digest")),
            registry_digest=_require_digest(value.get("registry_digest")),
            steps=tuple(steps),
        )
    except (PlanValidationError, ValueError, TypeError) as exc:
        raise PlanStoreError("PLAN_STORE_INVALID") from exc
    if plan.registry_digest != reviewed_registry_digest():
        raise PlanStoreError("PLAN_STORE_REGISTRY_MISMATCH")
    return plan


def _envelope(plan: TaskPlan, sequence: int) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "store_version": PLAN_STORE_VERSION,
        "sequence": sequence,
        "plan": _plan_payload(plan),
        "plan_digest": plan.digest,
    }
    return {**unsigned, "envelope_digest": _digest(unsigned)}


def _decode_envelope(value: object, *, expected_run_id: str) -> PersistedTaskPlan:
    if not isinstance(value, Mapping) or set(value) != _ENVELOPE_FIELDS:
        raise PlanStoreError("PLAN_STORE_INVALID")
    store_version = value.get("store_version")
    if (
        not isinstance(store_version, int)
        or isinstance(store_version, bool)
        or store_version != PLAN_STORE_VERSION
    ):
        raise PlanStoreError("PLAN_STORE_VERSION_UNSUPPORTED")
    sequence = _require_sequence(value.get("sequence"))
    plan = _decode_plan(value.get("plan"), expected_run_id=expected_run_id)
    if _require_digest(value.get("plan_digest")) != plan.digest:
        raise PlanStoreError("PLAN_STORE_DIGEST_MISMATCH")
    envelope_digest = _require_digest(value.get("envelope_digest"))
    unsigned = {key: item for key, item in value.items() if key != "envelope_digest"}
    if envelope_digest != _digest(unsigned):
        raise PlanStoreError("PLAN_STORE_DIGEST_MISMATCH")
    return PersistedTaskPlan(
        plan=plan, sequence=sequence, envelope_digest=envelope_digest
    )


class TaskPlanStore:
    """Run-lock-bound storage with atomic, compare-and-swap transitions."""

    def __init__(self, state_dir: Path, lock: RunLock) -> None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        if not isinstance(lock, RunLock):
            raise ValueError("lock must be a RunLock")
        self.state_dir = state_dir
        self.lock = lock

    def _require_lock(self) -> None:
        if not self.lock.acquired:
            raise PlanStoreError("PLAN_STORE_LOCK_REQUIRED")

    def _path(self, run_id: str) -> Path:
        path = task_plan_path(self.state_dir, run_id)
        if (
            _is_unsafe_path(self.state_dir)
            or _is_unsafe_path(self.state_dir / "runs")
            or _is_unsafe_path(path.parent)
            or _is_unsafe_path(path)
        ):
            raise PlanStoreError("PLAN_STORE_UNSAFE_PATH")
        return path

    def _read(self, run_id: str) -> PersistedTaskPlan:
        path = self._path(run_id)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise PlanStoreError("PLAN_STORE_READ_FAILED") from exc
        if not data or len(data) > MAX_PERSISTED_PLAN_BYTES:
            raise PlanStoreError("PLAN_STORE_READ_FAILED")
        try:
            value = json.loads(data)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PlanStoreError("PLAN_STORE_READ_FAILED") from exc
        return _decode_envelope(value, expected_run_id=run_id)

    def _write(self, snapshot: PersistedTaskPlan, *, create: bool) -> PersistedTaskPlan:
        payload = _envelope(snapshot.plan, snapshot.sequence)
        validated = _decode_envelope(payload, expected_run_id=snapshot.plan.run_id)
        encoded = _canonical(payload) + b"\n"
        if len(encoded) > MAX_PERSISTED_PLAN_BYTES:
            raise PlanStoreError("PLAN_STORE_TOO_LARGE")
        path = self._path(snapshot.plan.run_id)
        if create and path.exists():
            raise PlanStoreError("PLAN_STORE_ALREADY_EXISTS")
        path.parent.mkdir(parents=True, exist_ok=True)
        if _is_unsafe_path(path.parent) or _is_unsafe_path(path):
            raise PlanStoreError("PLAN_STORE_UNSAFE_PATH")
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".task-plan-", suffix=".tmp", dir=path.parent
            )
            temporary = Path(raw_path)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            if create and path.exists():
                raise PlanStoreError("PLAN_STORE_ALREADY_EXISTS")
            os.replace(temporary, path)
            temporary = None
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except PlanStoreError:
            raise
        except OSError as exc:
            raise PlanStoreError("PLAN_STORE_WRITE_FAILED") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return validated

    def create(self, plan: TaskPlan) -> PersistedTaskPlan:
        """Persist a new pending plan without replacing existing state."""

        self._require_lock()
        if not isinstance(plan, TaskPlan) or plan.status is not TaskPlanStatus.PENDING:
            raise PlanStoreError("PLAN_STORE_INITIAL_STATE_INVALID")
        if plan.registry_digest != reviewed_registry_digest():
            raise PlanStoreError("PLAN_STORE_REGISTRY_MISMATCH")
        return self._write(
            PersistedTaskPlan(plan=plan, sequence=0, envelope_digest="0" * 64),
            create=True,
        )

    def read(self, run_id: str) -> PersistedTaskPlan:
        """Read one plan while the owning application run lock is held."""

        self._require_lock()
        return self._read(run_id)

    def transition(
        self,
        run_id: str,
        step_id: str,
        target: PlanStepStatus,
        *,
        expected_sequence: int,
        expected_plan_digest: str,
    ) -> PersistedTaskPlan:
        """Atomically persist one legal transition after exact CAS validation."""

        self._require_lock()
        _require_sequence(expected_sequence)
        _require_digest(expected_plan_digest)
        current = self._read(run_id)
        if (
            current.sequence != expected_sequence
            or current.plan.digest != expected_plan_digest
        ):
            raise PlanStoreError("PLAN_STORE_STALE_WRITE")
        try:
            updated = transition_plan_step(current.plan, step_id, target)
        except PlanValidationError as exc:
            raise PlanStoreError("PLAN_STORE_TRANSITION_INVALID") from exc
        return self._write(
            PersistedTaskPlan(
                plan=updated,
                sequence=current.sequence + 1,
                envelope_digest="0" * 64,
            ),
            create=False,
        )


__all__ = [
    "MAX_PERSISTED_PLAN_BYTES",
    "PLAN_STORE_VERSION",
    "PersistedTaskPlan",
    "PlanStoreError",
    "TaskPlanStore",
    "task_plan_path",
]
