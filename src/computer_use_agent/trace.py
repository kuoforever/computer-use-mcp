"""Redacted JSONL traces and atomic safe run checkpoints."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Mapping

from .continuation import delete_continuation
from .types import JSONValue, LedgerEvent, LedgerEventKind, RunState, to_json_value


TRACE_VERSION = 1
CHECKPOINT_VERSION = 1
MAX_CHECKPOINT_BYTES = 64 * 1024
MAX_TRACE_LINE_BYTES = 1024 * 1024


class TraceError(RuntimeError):
    """Fixed trace/checkpoint failure that never embeds persisted content."""


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    resume_allowed: bool = False

    def __post_init__(self) -> None:
        if self.action not in {"resume_initial", "start_new_run", "human_reobserve", "none"}:
            raise ValueError("unsupported recovery action")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("recovery reason must be non-empty")
        if self.resume_allowed != (self.action == "resume_initial"):
            raise ValueError("resume_allowed must match the recovery action")


def classify_run_recovery(
    checkpoint: Mapping[str, JSONValue], *, task_length: int, policy_version: str
) -> RecoveryDecision:
    """Classify an untrusted safe checkpoint without replaying external work."""
    if not isinstance(checkpoint, Mapping):
        raise ValueError("checkpoint must be a mapping")
    if isinstance(task_length, bool) or not isinstance(task_length, int) or task_length <= 0:
        raise ValueError("task_length must be a positive integer")
    if not isinstance(policy_version, str) or not policy_version:
        raise ValueError("policy_version must be non-empty")
    try:
        phase = RunPhase(checkpoint.get("phase"))
    except ValueError:
        return RecoveryDecision("none", "CHECKPOINT_INVALID")
    if phase is RunPhase.SUCCESS:
        return RecoveryDecision("none", "RUN_SUCCEEDED")
    if phase is RunPhase.UNKNOWN_OUTCOME:
        return RecoveryDecision("human_reobserve", "UNKNOWN_OUTCOME")
    if phase in {RunPhase.FAILED, RunPhase.CANCELLED}:
        return RecoveryDecision("start_new_run", "RUN_TERMINAL")
    budgets = checkpoint.get("budgets")
    initial = (
        phase in {RunPhase.CREATED, RunPhase.OBSERVING}
        and checkpoint.get("resume_allowed") is True
        and checkpoint.get("event_count") == 1
        and checkpoint.get("task_length") == task_length
        and checkpoint.get("policy_version") == policy_version
        and checkpoint.get("recovery_status") == "ready"
        and checkpoint.get("observation_epoch") == 0
        and checkpoint.get("verified_observation_epoch") is None
        and isinstance(budgets, Mapping)
        and all(
            budgets.get(name) == 0
            for name in (
                "model_turns_used",
                "tool_calls_used",
                "side_effects_used",
                "input_tokens_used",
            )
        )
    )
    if initial:
        return RecoveryDecision("resume_initial", "INITIAL_CHECKPOINT", True)
    if phase in {RunPhase.CREATED, RunPhase.OBSERVING}:
        return RecoveryDecision("start_new_run", "CHECKPOINT_MISMATCH")
    return RecoveryDecision("start_new_run", "PROVIDER_OR_TOOL_PROGRESS")


class RunPhase(str, Enum):
    CREATED = "CREATED"
    OBSERVING = "OBSERVING"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    CANCELLED = "CANCELLED"


TERMINAL_PHASES = frozenset(
    {RunPhase.SUCCESS, RunPhase.FAILED, RunPhase.UNKNOWN_OUTCOME, RunPhase.CANCELLED}
)
_TRANSITIONS = {
    RunPhase.CREATED: {RunPhase.OBSERVING, RunPhase.FAILED, RunPhase.CANCELLED},
    RunPhase.OBSERVING: {
        RunPhase.PLANNING,
        RunPhase.FAILED,
        RunPhase.UNKNOWN_OUTCOME,
        RunPhase.CANCELLED,
    },
    RunPhase.PLANNING: {
        RunPhase.WAITING_APPROVAL,
        RunPhase.EXECUTING,
        RunPhase.SUCCESS,
        RunPhase.FAILED,
        RunPhase.CANCELLED,
    },
    RunPhase.WAITING_APPROVAL: {
        RunPhase.EXECUTING,
        RunPhase.FAILED,
        RunPhase.CANCELLED,
    },
    RunPhase.EXECUTING: {
        RunPhase.OBSERVING,
        RunPhase.PLANNING,
        RunPhase.VERIFYING,
        RunPhase.FAILED,
        RunPhase.UNKNOWN_OUTCOME,
        RunPhase.CANCELLED,
    },
    RunPhase.VERIFYING: {
        RunPhase.PLANNING,
        RunPhase.SUCCESS,
        RunPhase.FAILED,
        RunPhase.UNKNOWN_OUTCOME,
        RunPhase.CANCELLED,
    },
}
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


def validate_transition(current: RunPhase, target: RunPhase) -> None:
    if not isinstance(current, RunPhase) or not isinstance(target, RunPhase):
        raise ValueError("run phases must be RunPhase values")
    if current in TERMINAL_PHASES or target not in _TRANSITIONS[current]:
        raise TraceError("ILLEGAL_RUN_PHASE_TRANSITION")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _safe_event(event: LedgerEvent, sequence: int, run_id: str) -> dict[str, JSONValue]:
    item: dict[str, JSONValue] = {
        "trace_version": TRACE_VERSION,
        "sequence": sequence,
        "run_id": run_id,
        "kind": event.kind.value,
    }
    if event.kind is LedgerEventKind.USER_TASK:
        item["task_length"] = event.payload["task_length"]
    elif event.kind is LedgerEventKind.MODEL_TURN:
        for field_name in ("text_length", "tool_call_count", "input_tokens", "output_tokens"):
            item[field_name] = event.payload[field_name]
        item["latency_ms"] = event.payload.get("latency_ms", 0)
    elif event.kind is LedgerEventKind.TOOL_CALL:
        assert event.safe_argument_summary is not None
        item["tool"] = event.safe_argument_summary.tool_name
        item["arguments"] = to_json_value(event.safe_argument_summary.values)
        item["redacted_fields"] = list(event.safe_argument_summary.redacted_fields)
    elif event.kind is LedgerEventKind.TOOL_RESULT:
        assert event.tool_result is not None
        item["tool"] = event.tool_result.tool_name
        item["status"] = event.tool_result.status.value
        item["dispatch"] = event.tool_result.dispatch.value
        item["text_length"] = len(event.tool_result.sanitized_text)
        item["image_count"] = len(event.tool_result.images)
        if "latency_ms" in event.payload:
            item["latency_ms"] = event.payload["latency_ms"]
        if event.tool_result.code is not None:
            item["code"] = event.tool_result.code
    elif event.kind is LedgerEventKind.OBSERVATION:
        item["tool"] = event.payload["tool_name"]
        item["observation_epoch"] = event.payload["observation_epoch"]
    elif event.kind is LedgerEventKind.POLICY_DECISION:
        assert event.policy_decision is not None
        item["decision"] = event.policy_decision.kind.value
    elif event.kind is LedgerEventKind.RECOVERY:
        item["status"] = event.payload.get("status")
    return item


def _checkpoint(
    state: RunState,
    phase: RunPhase,
    *,
    checkpoint_sequence: int,
    failure_code: str | None = None,
    final_text_length: int | None = None,
    run_duration_ms: int | None = None,
) -> dict[str, JSONValue]:
    budget = state.budgets
    payload: dict[str, JSONValue] = {
        "checkpoint_version": CHECKPOINT_VERSION,
        "checkpoint_sequence": checkpoint_sequence,
        "run_id": state.run_id,
        "phase": phase.value,
        "policy_version": state.policy_version,
        "recovery_status": state.recovery_status.value,
        "task_length": len(state.task),
        "observation_epoch": state.observation_epoch,
        "verified_observation_epoch": state.verified_observation_epoch,
        "event_count": len(state.event_log),
        "budgets": {
            "max_model_turns": budget.max_model_turns,
            "max_tool_calls": budget.max_tool_calls,
            "max_side_effects": budget.max_side_effects,
            "model_turns_used": budget.model_turns_used,
            "tool_calls_used": budget.tool_calls_used,
            "side_effects_used": budget.side_effects_used,
            "max_input_tokens": budget.max_input_tokens,
            "input_tokens_used": budget.input_tokens_used,
        },
        "updated_at": _now(),
        "metrics": _metrics(state, run_duration_ms=run_duration_ms),
    }
    if failure_code is not None:
        payload["failure_code"] = failure_code
    if final_text_length is not None:
        payload["final_text_length"] = final_text_length
    initial_resume = (
        phase in {RunPhase.CREATED, RunPhase.OBSERVING}
        and len(state.event_log) == 1
        and budget.model_turns_used == 0
        and budget.tool_calls_used == 0
        and budget.side_effects_used == 0
        and budget.input_tokens_used == 0
        and state.recovery_status.value == "ready"
        and state.observation_epoch == 0
    )
    if initial_resume:
        payload["resume_allowed"] = True
        payload["recovery_action"] = "resume_with_original_task"
    elif phase is RunPhase.SUCCESS:
        payload["resume_allowed"] = False
        payload["recovery_action"] = "none"
    elif phase is RunPhase.UNKNOWN_OUTCOME:
        payload["resume_allowed"] = False
        payload["recovery_action"] = "human_reobserve_then_start_new_run"
    else:
        payload["resume_allowed"] = False
        payload["recovery_action"] = "inspect_trace_then_start_new_run"
    return payload


def _metrics(state: RunState, *, run_duration_ms: int | None) -> dict[str, JSONValue]:
    input_tokens = 0
    output_tokens = 0
    provider_latency_ms = 0
    tool_latency_ms = 0
    tool_failures = 0
    image_results = 0
    for event in state.event_log:
        if event.kind is LedgerEventKind.MODEL_TURN:
            input_tokens += _metric_int(event.payload.get("input_tokens"))
            output_tokens += _metric_int(event.payload.get("output_tokens"))
            provider_latency_ms += _metric_int(event.payload.get("latency_ms"))
        elif event.kind is LedgerEventKind.TOOL_RESULT and event.tool_result is not None:
            tool_latency_ms += _metric_int(event.payload.get("latency_ms"))
            tool_failures += int(not event.tool_result.ok)
            image_results += len(event.tool_result.images)
    metrics: dict[str, JSONValue] = {
        "model_calls": state.budgets.model_turns_used,
        "tool_calls": state.budgets.tool_calls_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "provider_latency_ms": provider_latency_ms,
        "tool_latency_ms": tool_latency_ms,
        "tool_failures": tool_failures,
        "image_results": image_results,
        "retry_count": 0,
    }
    if run_duration_ms is not None:
        metrics["run_duration_ms"] = run_duration_ms
    return metrics


def _metric_int(value: JSONValue | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _atomic_json(path: Path, payload: Mapping[str, JSONValue]) -> None:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(encoded) > MAX_CHECKPOINT_BYTES:
        raise TraceError("CHECKPOINT_TOO_LARGE")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=path.parent)
        temporary = Path(raw_path)
        with os.fdopen(descriptor, "wb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise TraceError("CHECKPOINT_WRITE_FAILED") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


@dataclass
class RunRecorder:
    """Own one run's append-only redacted trace and atomic checkpoint."""

    state_dir: Path
    run_id: str
    phase: RunPhase = RunPhase.CREATED
    _event_count: int = 0
    _checkpoint_sequence: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.state_dir, Path) or not self.state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        if not isinstance(self.run_id, str) or _RUN_ID.fullmatch(self.run_id) is None:
            raise ValueError("run_id must be a path-safe identifier")

    @property
    def run_dir(self) -> Path:
        return self.state_dir / "runs" / self.run_id

    @property
    def checkpoint_path(self) -> Path:
        return self.run_dir / "state.json"

    @property
    def trace_path(self) -> Path:
        return self.state_dir / "traces" / f"{self.run_id}.jsonl"

    @property
    def checkpoint_sequence(self) -> int:
        return self._checkpoint_sequence

    def start(self, state: RunState) -> None:
        if self.checkpoint_path.exists() or self.trace_path.exists():
            raise TraceError("RUN_RECORD_ALREADY_EXISTS")
        self.record(state, RunPhase.CREATED)

    def attach_initial(self, state: RunState) -> None:
        """Attach to a crash-safe initial record without replaying external work."""
        record = read_run_record(self.state_dir, self.run_id)
        checkpoint = record["state"]
        decision = classify_run_recovery(
            checkpoint, task_length=len(state.task), policy_version=state.policy_version
        )
        if not decision.resume_allowed:
            raise TraceError("RUN_NOT_RESUMABLE")
        self.phase = RunPhase(checkpoint["phase"])
        self._event_count = 1
        sequence = checkpoint.get("checkpoint_sequence", 1)
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise TraceError("CHECKPOINT_READ_FAILED")
        self._checkpoint_sequence = sequence
    def record(
        self,
        state: RunState,
        phase: RunPhase,
        *,
        advance_checkpoint_sequence: bool = False,
        failure_code: str | None = None,
        final_text_length: int | None = None,
        run_duration_ms: int | None = None,
    ) -> None:
        if state.run_id != self.run_id:
            raise TraceError("RUN_RECORD_IDENTITY_MISMATCH")
        if phase is not self.phase:
            validate_transition(self.phase, phase)
        new_events = state.event_log[self._event_count :]
        if self._event_count > len(state.event_log):
            raise TraceError("RUN_EVENT_LOG_REWIND")
        self.trace_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.trace_path.open("ab") as file:
                for offset, event in enumerate(new_events, start=self._event_count + 1):
                    encoded = (
                        json.dumps(
                            _safe_event(event, offset, self.run_id),
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        + "\n"
                    ).encode()
                    if len(encoded) > MAX_TRACE_LINE_BYTES:
                        raise TraceError("TRACE_EVENT_TOO_LARGE")
                    file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
        except OSError as exc:
            raise TraceError("TRACE_WRITE_FAILED") from exc
        next_sequence = self._checkpoint_sequence
        if next_sequence == 0 or advance_checkpoint_sequence:
            next_sequence += 1
        _atomic_json(
            self.checkpoint_path,
            _checkpoint(
                state,
                phase,
                checkpoint_sequence=next_sequence,
                failure_code=failure_code,
                final_text_length=final_text_length,
                run_duration_ms=run_duration_ms,
            ),
        )
        self._event_count = len(state.event_log)
        self._checkpoint_sequence = next_sequence
        self.phase = phase


def cancel_run_record(state_dir: Path, run_id: str) -> dict[str, JSONValue]:
    """Atomically mark one non-terminal persisted run cancelled."""
    checkpoint = read_run_record(state_dir, run_id)["state"]
    try:
        phase = RunPhase(checkpoint["phase"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceError("CHECKPOINT_READ_FAILED") from exc
    if phase in TERMINAL_PHASES:
        raise TraceError("RUN_ALREADY_TERMINAL")
    validate_transition(phase, RunPhase.CANCELLED)
    sequence = checkpoint.get("checkpoint_sequence", 0)
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise TraceError("CHECKPOINT_READ_FAILED")
    updated = dict(checkpoint)
    updated.update(
        phase=RunPhase.CANCELLED.value,
        checkpoint_sequence=sequence + 1,
        failure_code="CANCELLED_BY_OPERATOR",
        resume_allowed=False,
        recovery_action="none",
        updated_at=_now(),
    )
    delete_continuation(state_dir, run_id)
    _atomic_json(RunRecorder(state_dir, run_id).checkpoint_path, updated)
    return to_json_value(updated)


def _read_json(path: Path, maximum: int, error_code: str) -> object:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise TraceError(error_code) from exc
    if not data or len(data) > maximum:
        raise TraceError(error_code)
    try:
        return json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TraceError(error_code) from exc


def read_run_record(state_dir: Path, run_id: str) -> dict[str, JSONValue]:
    """Read one bounded checkpoint and trace without trusting persisted fields."""

    recorder = RunRecorder(state_dir=state_dir, run_id=run_id)
    checkpoint = read_run_checkpoint(state_dir, run_id)
    events: list[JSONValue] = []
    try:
        with recorder.trace_path.open("rb") as file:
            for sequence, line in enumerate(file, start=1):
                if not line or len(line) > MAX_TRACE_LINE_BYTES:
                    raise TraceError("TRACE_READ_FAILED")
                try:
                    event = json.loads(line)
                except (UnicodeError, json.JSONDecodeError) as exc:
                    raise TraceError("TRACE_READ_FAILED") from exc
                if (
                    not isinstance(event, dict)
                    or event.get("run_id") != run_id
                    or event.get("sequence") != sequence
                    or event.get("trace_version") != TRACE_VERSION
                ):
                    raise TraceError("TRACE_READ_FAILED")
                events.append(to_json_value(event))
    except OSError as exc:
        raise TraceError("TRACE_READ_FAILED") from exc
    if checkpoint.get("event_count") != len(events):
        raise TraceError("RUN_RECORD_INCOMPLETE")
    return {"state": to_json_value(checkpoint), "events": events}


def read_run_checkpoint(state_dir: Path, run_id: str) -> dict[str, JSONValue]:
    """Read one bounded atomic checkpoint without opening its JSONL trace."""

    recorder = RunRecorder(state_dir=state_dir, run_id=run_id)
    if recorder.checkpoint_path.is_symlink():
        raise TraceError("CHECKPOINT_READ_FAILED")
    checkpoint = _read_json(
        recorder.checkpoint_path, MAX_CHECKPOINT_BYTES, "CHECKPOINT_READ_FAILED"
    )
    if not isinstance(checkpoint, dict):
        raise TraceError("CHECKPOINT_READ_FAILED")
    if checkpoint.get("run_id") != run_id or checkpoint.get("checkpoint_version") != 1:
        raise TraceError("CHECKPOINT_READ_FAILED")
    return to_json_value(checkpoint)


def advance_recovery_checkpoint(
    state_dir: Path,
    run_id: str,
    *,
    expected_sequence: int,
    new_sequence: int,
    phase: RunPhase,
    budgets: Mapping[str, JSONValue],
    observation_epoch: int,
    verified_observation_epoch: int | None,
    recovery_status: str,
) -> dict[str, JSONValue]:
    """Compare-and-replace the safe half of one locked recovery boundary.

    The caller owns the cross-file run lock and writes ``continuation.json``
    first.  A crash between the two atomic replacements therefore leaves a
    sequence mismatch that recovery rejects instead of replaying work.
    """

    if (
        isinstance(expected_sequence, bool)
        or not isinstance(expected_sequence, int)
        or expected_sequence < 1
        or isinstance(new_sequence, bool)
        or not isinstance(new_sequence, int)
        or new_sequence != expected_sequence + 1
    ):
        raise ValueError("recovery checkpoint sequences must advance by one")
    if not isinstance(phase, RunPhase) or phase in TERMINAL_PHASES - {
        RunPhase.UNKNOWN_OUTCOME
    }:
        raise ValueError("unsupported recovery checkpoint phase")
    checkpoint = read_run_checkpoint(state_dir, run_id)
    if checkpoint.get("checkpoint_sequence") != expected_sequence:
        raise TraceError("RECOVERY_CHECKPOINT_SEQUENCE_MISMATCH")
    try:
        current_phase = RunPhase(checkpoint["phase"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceError("CHECKPOINT_READ_FAILED") from exc
    if current_phase in TERMINAL_PHASES:
        raise TraceError("RUN_ALREADY_TERMINAL")
    if not isinstance(budgets, Mapping):
        raise ValueError("budgets must be a mapping")
    updated = dict(checkpoint)
    metrics = updated.get("metrics")
    if isinstance(metrics, Mapping):
        updated_metrics = dict(metrics)
        updated_metrics["model_calls"] = budgets.get("model_turns_used", 0)
        updated_metrics["tool_calls"] = budgets.get("tool_calls_used", 0)
        updated_metrics["input_tokens"] = budgets.get("input_tokens_used", 0)
        updated["metrics"] = to_json_value(updated_metrics)
    updated.update(
        checkpoint_sequence=new_sequence,
        phase=phase.value,
        budgets=to_json_value(budgets),
        observation_epoch=observation_epoch,
        verified_observation_epoch=verified_observation_epoch,
        recovery_status=recovery_status,
        resume_allowed=False,
        recovery_action=(
            "human_reobserve_then_start_new_run"
            if phase is RunPhase.UNKNOWN_OUTCOME
            else "continue_read_only_recovery"
        ),
        updated_at=_now(),
    )
    _atomic_json(RunRecorder(state_dir, run_id).checkpoint_path, updated)
    return to_json_value(updated)


def finalize_recovery_success(
    state_dir: Path,
    run_id: str,
    *,
    expected_sequence: int,
    final_text_length: int,
) -> dict[str, JSONValue]:
    """Atomically close one validated final-provider recovery boundary."""

    if (
        isinstance(expected_sequence, bool)
        or not isinstance(expected_sequence, int)
        or expected_sequence < 1
        or isinstance(final_text_length, bool)
        or not isinstance(final_text_length, int)
        or final_text_length < 0
    ):
        raise ValueError("invalid recovery success fields")
    checkpoint = read_run_checkpoint(state_dir, run_id)
    if checkpoint.get("checkpoint_sequence") != expected_sequence:
        raise TraceError("RECOVERY_CHECKPOINT_SEQUENCE_MISMATCH")
    try:
        current_phase = RunPhase(checkpoint["phase"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TraceError("CHECKPOINT_READ_FAILED") from exc
    if current_phase is not RunPhase.PLANNING:
        raise TraceError("RECOVERY_SUCCESS_PHASE_INVALID")
    validate_transition(current_phase, RunPhase.SUCCESS)
    updated = dict(checkpoint)
    updated.update(
        checkpoint_sequence=expected_sequence + 1,
        phase=RunPhase.SUCCESS.value,
        recovery_status="ready",
        final_text_length=final_text_length,
        resume_allowed=False,
        recovery_action="none",
        updated_at=_now(),
    )
    updated.pop("failure_code", None)
    _atomic_json(RunRecorder(state_dir, run_id).checkpoint_path, updated)
    delete_continuation(state_dir, run_id)
    return to_json_value(updated)


__all__ = [
    "RecoveryDecision",
    "RunPhase",
    "RunRecorder",
    "advance_recovery_checkpoint",
    "cancel_run_record",
    "classify_run_recovery",
    "finalize_recovery_success",
    "TraceError",
    "read_run_checkpoint",
    "read_run_record",
    "validate_transition",
]
