"""Pure checkpoint-to-view-model reducer for the passive operator progress viewer.

This is delivery step 1 of the [operator progress viewer](../../docs/PROGRESS_VIEWER.md):
a read-only projection of a validated run checkpoint into the small, honest set
of facts a passive window may show. It reads nothing but the checkpoint the
`agent report` reader already trusts, copies only a fixed allowlist of scalar
fields, and never infers liveness a checkpoint-v1 record cannot prove.

The reducer is the only place that decides what a viewer is allowed to display,
so redaction is structural: forbidden content (task text, titles, model prose,
typed values, arbitrary errors) is never read, not merely dropped later.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .trace import RunPhase, TraceError, read_run_checkpoint
from .types import JSONValue

MAX_PROGRESS_RUNS = 10_000

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_FAILURE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")

_TERMINAL_PHASES = frozenset(
    {
        RunPhase.SUCCESS,
        RunPhase.FAILED,
        RunPhase.UNKNOWN_OUTCOME,
        RunPhase.CANCELLED,
    }
)

# The fixed, honest projection from a source phase to an operator-facing label.
# A nonterminal phase never maps to "running" or "blocked": a checkpoint-v1
# record cannot prove whether that run is alive, waiting, or crashed.
_DISPLAY_STATE: dict[RunPhase, str] = {
    RunPhase.WAITING_APPROVAL: "Waiting approval",
    RunPhase.SUCCESS: "Complete",
    RunPhase.FAILED: "Failed",
    RunPhase.UNKNOWN_OUTCOME: "Uncertain; re-observe before retry",
    RunPhase.CANCELLED: "Cancelled",
}
_IN_PROGRESS_LABEL = "In progress at last checkpoint; liveness unknown"

_BUDGET_USED = {"model_calls": "model_turns_used", "tool_calls": "tool_calls_used"}
_BUDGET_LIMIT = {"model_calls": "max_model_turns", "tool_calls": "max_tool_calls"}
_METRIC_TOKENS = ("input_tokens", "output_tokens")
_METRIC_COUNTS = ("image_results", "tool_failures")


class ProgressViewError(RuntimeError):
    """A fixed reducer failure that never embeds checkpoint content."""


@dataclass(frozen=True)
class CallBudget:
    """Used and configured limit for one call kind."""

    used: int
    limit: int


@dataclass(frozen=True)
class RunProgressView:
    """The complete set of facts a passive viewer may show for one run.

    Every field is either a fixed enum/label or a bounded non-negative integer.
    ``*_known`` flags record where checkpoint v1 cannot supply a fact, so the
    window can render "unknown" instead of a misleading zero or "running".
    """

    run_id: str
    phase: str
    display_state: str
    is_terminal: bool
    liveness_known: bool
    needs_reobserve: bool
    model_calls: CallBudget
    tool_calls: CallBudget
    input_tokens: int
    output_tokens: int
    token_coverage_known: bool
    image_results: int
    tool_failures: int
    elapsed_known: bool
    duration_ms: int | None
    failure_code: str | None

    def as_display_dict(self) -> dict[str, JSONValue]:
        """Return only the whitelisted display fields, for a window or a test."""

        return {
            "run_id": self.run_id,
            "phase": self.phase,
            "display_state": self.display_state,
            "is_terminal": self.is_terminal,
            "liveness_known": self.liveness_known,
            "needs_reobserve": self.needs_reobserve,
            "model_calls": {"used": self.model_calls.used, "limit": self.model_calls.limit},
            "tool_calls": {"used": self.tool_calls.used, "limit": self.tool_calls.limit},
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "token_coverage_known": self.token_coverage_known,
            "image_results": self.image_results,
            "tool_failures": self.tool_failures,
            "elapsed_known": self.elapsed_known,
            "duration_ms": self.duration_ms,
            "failure_code": self.failure_code,
        }


@dataclass(frozen=True)
class ProgressProjection:
    """A bounded scan result: trustworthy views plus honest unavailability.

    A corrupt record never contaminates a valid one. A record whose run-id
    directory name is itself unsafe is counted but never named, because an
    unsafe name is exactly what the viewer must not surface.
    """

    views: tuple[RunProgressView, ...]
    unavailable_run_ids: tuple[str, ...]
    unavailable_unnamed: int


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
    return value


def _call_budget(budgets: Mapping[str, object], kind: str) -> CallBudget:
    used = _nonnegative_int(budgets.get(_BUDGET_USED[kind]))
    limit = _nonnegative_int(budgets.get(_BUDGET_LIMIT[kind]))
    if used > limit:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
    return CallBudget(used=used, limit=limit)


def checkpoint_to_view(checkpoint: Mapping[str, object]) -> RunProgressView:
    """Reduce one validated checkpoint mapping to a redaction-safe view model.

    The mapping is treated as untrusted: every field the view exposes is
    re-validated here, and no field outside the fixed allowlist is ever read.
    """

    if not isinstance(checkpoint, Mapping):
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")

    run_id = checkpoint.get("run_id")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")

    raw_phase = checkpoint.get("phase")
    if not isinstance(raw_phase, str):
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
    try:
        phase = RunPhase(raw_phase)
    except ValueError as exc:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID") from exc

    budgets = checkpoint.get("budgets")
    metrics = checkpoint.get("metrics")
    if not isinstance(budgets, Mapping) or not isinstance(metrics, Mapping):
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")

    is_terminal = phase in _TERMINAL_PHASES
    failure_code = checkpoint.get("failure_code")
    if failure_code is not None:
        if (
            not is_terminal
            or not isinstance(failure_code, str)
            or _FAILURE_CODE.fullmatch(failure_code) is None
        ):
            raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")

    duration = metrics.get("run_duration_ms")
    duration_ms = None if duration is None else _nonnegative_int(duration)

    return RunProgressView(
        run_id=run_id,
        phase=phase.value,
        display_state=_DISPLAY_STATE.get(phase, _IN_PROGRESS_LABEL),
        is_terminal=is_terminal,
        # Only a terminal checkpoint proves a run stopped; everything else is a
        # last-known intent that may already be dead.
        liveness_known=is_terminal,
        needs_reobserve=phase is RunPhase.UNKNOWN_OUTCOME,
        model_calls=_call_budget(budgets, "model_calls"),
        tool_calls=_call_budget(budgets, "tool_calls"),
        input_tokens=_nonnegative_int(metrics.get(_METRIC_TOKENS[0])),
        output_tokens=_nonnegative_int(metrics.get(_METRIC_TOKENS[1])),
        # Checkpoint v1 has no provider-usage report count, so a zero token
        # total is indistinguishable from missing provider usage.
        token_coverage_known=False,
        image_results=_nonnegative_int(metrics.get(_METRIC_COUNTS[0])),
        tool_failures=_nonnegative_int(metrics.get(_METRIC_COUNTS[1])),
        # Checkpoint v1 has no created_at, so active elapsed time is unknowable.
        elapsed_known=False,
        duration_ms=duration_ms,
        failure_code=failure_code if is_terminal else None,
    )


def build_progress_projection(state_dir: Path) -> ProgressProjection:
    """Project every bounded run checkpoint under ``state_dir`` for the viewer.

    Directory-level tampering (a symlinked runs directory, an oversized scan)
    fails the whole scan closed. A single unreadable or corrupt run only makes
    that run unavailable.
    """

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    runs_dir = state_dir / "runs"
    if not runs_dir.exists():
        return ProgressProjection(views=(), unavailable_run_ids=(), unavailable_unnamed=0)
    if runs_dir.is_symlink() or not runs_dir.is_dir():
        raise ProgressViewError("PROGRESS_VIEW_DIRECTORY_INVALID")
    try:
        entries = sorted(runs_dir.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise ProgressViewError("PROGRESS_VIEW_DIRECTORY_INVALID") from exc
    if len(entries) > MAX_PROGRESS_RUNS:
        raise ProgressViewError("PROGRESS_VIEW_LIMIT_EXCEEDED")

    views: list[RunProgressView] = []
    unavailable_run_ids: list[str] = []
    unavailable_unnamed = 0
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir() or _RUN_ID.fullmatch(entry.name) is None:
            # An unsafe or non-directory name is exactly what must not be shown.
            unavailable_unnamed += 1
            continue
        try:
            checkpoint = read_run_checkpoint(state_dir, entry.name)
            views.append(checkpoint_to_view(checkpoint))
        except (OSError, TraceError, ValueError, ProgressViewError):
            unavailable_run_ids.append(entry.name)

    return ProgressProjection(
        views=tuple(views),
        unavailable_run_ids=tuple(unavailable_run_ids),
        unavailable_unnamed=unavailable_unnamed,
    )


__all__ = [
    "CallBudget",
    "ProgressProjection",
    "ProgressViewError",
    "RunProgressView",
    "build_progress_projection",
    "checkpoint_to_view",
]
