"""Strict checkpoint-only aggregate reports for local Agent runs."""
from __future__ import annotations

import re
from pathlib import Path

from .trace import RunPhase, TraceError, read_run_checkpoint
from .types import JSONValue


REPORT_VERSION = 1
MAX_REPORT_RUNS = 10_000
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_FAILURE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
_METRIC_FIELDS = (
    "model_calls",
    "tool_calls",
    "input_tokens",
    "output_tokens",
    "provider_latency_ms",
    "tool_latency_ms",
    "tool_failures",
    "image_results",
    "retry_count",
    "run_duration_ms",
)
_OPTIONAL_CHECKPOINT_METRIC_FIELDS = frozenset(
    {"screenshot_results", "provider_usage_report_count"}
)


class RunReportError(RuntimeError):
    """Fixed report failure that never embeds checkpoint content."""


def _nonnegative_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def _validated_checkpoint(state_dir: Path, run_id: str) -> dict[str, JSONValue]:
    try:
        checkpoint = read_run_checkpoint(state_dir, run_id)
    except (OSError, TraceError, ValueError) as exc:
        raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID") from exc
    phase = checkpoint.get("phase")
    if not isinstance(phase, str):
        raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID")
    try:
        RunPhase(phase)
    except ValueError as exc:
        raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID") from exc
    if not _nonnegative_int(checkpoint.get("event_count")):
        raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID")
    failure_code = checkpoint.get("failure_code")
    if failure_code is not None and (
        not isinstance(failure_code, str) or _FAILURE_CODE.fullmatch(failure_code) is None
    ):
        raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID")
    metrics = checkpoint.get("metrics")
    if metrics is not None:
        if not isinstance(metrics, dict):
            raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID")
        for name, value in metrics.items():
            if (
                name not in _METRIC_FIELDS
                and name not in _OPTIONAL_CHECKPOINT_METRIC_FIELDS
            ) or not _nonnegative_int(value):
                raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID")
        required = set(_METRIC_FIELDS) - {"run_duration_ms"}
        if not required.issubset(metrics):
            raise RunReportError("RUN_REPORT_CHECKPOINT_INVALID")
    return checkpoint


def build_run_report(state_dir: Path) -> dict[str, JSONValue]:
    """Aggregate bounded safe checkpoints without reading trace event files."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    runs_dir = state_dir / "runs"
    phase_counts = {phase.value: 0 for phase in RunPhase}
    failure_codes: dict[str, int] = {}
    totals = {name: 0 for name in _METRIC_FIELDS}
    if not runs_dir.exists():
        entries: list[Path] = []
    else:
        if runs_dir.is_symlink() or not runs_dir.is_dir():
            raise RunReportError("RUN_REPORT_DIRECTORY_INVALID")
        try:
            entries = sorted(runs_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise RunReportError("RUN_REPORT_DIRECTORY_INVALID") from exc
    if len(entries) > MAX_REPORT_RUNS:
        raise RunReportError("RUN_REPORT_LIMIT_EXCEEDED")

    metrics_run_count = 0
    duration_run_count = 0
    for entry in entries:
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or _RUN_ID.fullmatch(entry.name) is None
        ):
            raise RunReportError("RUN_REPORT_DIRECTORY_INVALID")
        checkpoint = _validated_checkpoint(state_dir, entry.name)
        phase = checkpoint["phase"]
        assert isinstance(phase, str)
        phase_counts[phase] += 1
        failure_code = checkpoint.get("failure_code")
        if isinstance(failure_code, str):
            failure_codes[failure_code] = failure_codes.get(failure_code, 0) + 1
        metrics = checkpoint.get("metrics")
        if isinstance(metrics, dict):
            metrics_run_count += 1
            for name in _METRIC_FIELDS:
                value = metrics.get(name)
                if isinstance(value, int) and not isinstance(value, bool):
                    totals[name] += value
            if "run_duration_ms" in metrics:
                duration_run_count += 1

    run_count = len(entries)
    success_count = phase_counts[RunPhase.SUCCESS.value]
    terminal_count = sum(
        phase_counts[phase.value]
        for phase in (
            RunPhase.SUCCESS,
            RunPhase.FAILED,
            RunPhase.UNKNOWN_OUTCOME,
            RunPhase.CANCELLED,
        )
    )
    model_calls = totals["model_calls"]
    tool_calls = totals["tool_calls"]
    return {
        "report_version": REPORT_VERSION,
        "run_count": run_count,
        "terminal_run_count": terminal_count,
        "incomplete_run_count": run_count - terminal_count,
        "metrics_run_count": metrics_run_count,
        "duration_run_count": duration_run_count,
        "success_rate": 0.0 if terminal_count == 0 else success_count / terminal_count,
        "phase_counts": dict(phase_counts),
        "failure_codes": dict(sorted(failure_codes.items())),
        "totals": dict(totals),
        "averages": {
            "provider_latency_ms": (
                0.0 if model_calls == 0 else totals["provider_latency_ms"] / model_calls
            ),
            "tool_latency_ms": (
                0.0 if tool_calls == 0 else totals["tool_latency_ms"] / tool_calls
            ),
            "run_duration_ms": (
                0.0
                if duration_run_count == 0
                else totals["run_duration_ms"] / duration_run_count
            ),
        },
    }


__all__ = ["RunReportError", "build_run_report"]
