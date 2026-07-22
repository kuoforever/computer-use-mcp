"""Pure checkpoint-to-view-model reducer for the passive operator progress viewer.

This implements delivery steps 1 and 4 of the
[operator progress viewer](../../docs/PROGRESS_VIEWER.md): a read-only projection
of validated run checkpoints into the small, honest set of facts and fixed
multi-run groups a passive window may show. It reads nothing but checkpoints
the `agent report` reader already trusts, copies only a fixed allowlist of
scalar fields, and never infers liveness a checkpoint-v1 record cannot prove.

The reducer is the only place that decides what a viewer is allowed to display,
so redaction is structural: forbidden content (task text, titles, model prose,
typed values, arbitrary errors) is never read, not merely dropped later.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .campaign import (
    CampaignStoreError,
    campaign_dir,
    campaign_path_is_unsafe,
    read_campaign_control_snapshot,
)
from .campaign_host_status import (
    HostStatusProjectionError,
    HostTaskStatus,
    project_campaign_control_snapshot,
)
from .trace import RunPhase, TraceError, read_run_checkpoint
from .types import JSONValue

MAX_PROGRESS_RUNS = 10_000
MAX_PROGRESS_CAMPAIGNS = 10_000

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
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_ATTENTION_PHASES = frozenset({RunPhase.WAITING_APPROVAL, RunPhase.UNKNOWN_OUTCOME})

_CAMPAIGN_DISPLAY_STATE: dict[HostTaskStatus, str] = {
    HostTaskStatus.RUNNING: "Running",
    HostTaskStatus.WAITING_APPROVAL: "Waiting approval",
    HostTaskStatus.PAUSED: "Paused; operator attention",
    HostTaskStatus.CHALLENGE: "Challenge; operator attention",
    HostTaskStatus.COMPLETED: "Complete",
    HostTaskStatus.FAILED: "Failed; inspect before resume",
    HostTaskStatus.CANCELLED: "Cancelled",
    HostTaskStatus.UNCERTAIN: "Uncertain; re-observe before retry",
    HostTaskStatus.STALE: "Stale; inspect before reclaim",
    HostTaskStatus.NEEDS_INSPECTION: "State invalid; inspect",
}
_CAMPAIGN_TERMINAL = frozenset(
    {HostTaskStatus.COMPLETED, HostTaskStatus.FAILED, HostTaskStatus.CANCELLED}
)
_CAMPAIGN_ATTENTION = frozenset(
    status
    for status in HostTaskStatus
    if status not in {HostTaskStatus.RUNNING, HostTaskStatus.COMPLETED}
)


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
    # Internal, redaction-safe ordering key derived from the validated
    # checkpoint timestamp. It is not rendered or included in display output.
    updated_at_us: int = 0

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
    campaigns: tuple[CampaignProgressView, ...] = ()
    unavailable_campaign_ids: tuple[str, ...] = ()
    unavailable_campaign_unnamed: int = 0


@dataclass(frozen=True)
class RunProgressGroup:
    """One fixed, non-authoritative status group for independent runs."""

    key: str
    label: str
    views: tuple[RunProgressView, ...]


@dataclass(frozen=True)
class CampaignProgressView:
    """Redaction-safe progress facts for one validated campaign snapshot."""

    campaign_id: str
    status: str
    display_state: str
    is_terminal: bool
    needs_attention: bool
    discovered_count: int
    completed_count: int
    retryable_count: int
    uncertain_count: int
    updated_at_us: int

    def as_display_dict(self) -> dict[str, JSONValue]:
        return {
            "campaign_id": self.campaign_id,
            "status": self.status,
            "display_state": self.display_state,
            "is_terminal": self.is_terminal,
            "needs_attention": self.needs_attention,
            "discovered_count": self.discovered_count,
            "completed_count": self.completed_count,
            "retryable_count": self.retryable_count,
            "uncertain_count": self.uncertain_count,
        }


@dataclass(frozen=True)
class CampaignProgressGroup:
    key: str
    label: str
    views: tuple[CampaignProgressView, ...]


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


def validated_timestamp_us(value: object) -> int:
    """Validate one bounded timezone-aware timestamp and return a stable key."""

    if not isinstance(value, str) or not value or len(value) > 64:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
    delta = parsed.astimezone(UTC) - _EPOCH
    if delta.days < 0:
        raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def group_progress_views(views: tuple[RunProgressView, ...]) -> tuple[RunProgressGroup, ...]:
    """Group independent runs by operator relevance with stable newest-first order.

    These labels describe checkpoint state, not liveness. In particular,
    ``In progress`` means only that the last checkpoint was nonterminal.
    """

    buckets: dict[str, list[RunProgressView]] = {
        "attention": [],
        "in_progress": [],
        "history": [],
    }
    seen_run_ids: set[str] = set()
    for view in views:
        if not isinstance(view, RunProgressView) or view.run_id in seen_run_ids:
            raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
        seen_run_ids.add(view.run_id)
        if (
            isinstance(view.updated_at_us, bool)
            or not isinstance(view.updated_at_us, int)
            or view.updated_at_us < 0
        ):
            raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
        try:
            phase = RunPhase(view.phase)
        except ValueError as exc:
            raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID") from exc
        if view.is_terminal != (phase in _TERMINAL_PHASES):
            raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
        if view.needs_reobserve != (phase is RunPhase.UNKNOWN_OUTCOME):
            raise ProgressViewError("PROGRESS_VIEW_CHECKPOINT_INVALID")
        if phase in _ATTENTION_PHASES:
            buckets["attention"].append(view)
        elif view.is_terminal:
            buckets["history"].append(view)
        else:
            buckets["in_progress"].append(view)

    groups: list[RunProgressGroup] = []
    for key, label in (
        ("attention", "Attention"),
        ("in_progress", "In progress"),
        ("history", "History"),
    ):
        ordered = tuple(
            sorted(buckets[key], key=lambda view: (-view.updated_at_us, view.run_id))
        )
        if ordered:
            groups.append(RunProgressGroup(key=key, label=label, views=ordered))
    return tuple(groups)


def campaign_status_to_view(
    status: object,
) -> CampaignProgressView:
    """Reduce the existing bounded host campaign status into viewer-safe facts."""

    from .campaign_host_status import CampaignHostStatus

    if not isinstance(status, CampaignHostStatus):
        raise ProgressViewError("PROGRESS_VIEW_CAMPAIGN_INVALID")
    timestamp = 0
    if status.last_checkpoint_at is not None:
        timestamp = validated_timestamp_us(status.last_checkpoint_at)
    return CampaignProgressView(
        campaign_id=status.campaign_id,
        status=status.status.value,
        display_state=_CAMPAIGN_DISPLAY_STATE[status.status],
        is_terminal=status.status in _CAMPAIGN_TERMINAL,
        needs_attention=status.status in _CAMPAIGN_ATTENTION,
        discovered_count=_nonnegative_int(status.discovered_count),
        completed_count=_nonnegative_int(status.completed_count),
        retryable_count=_nonnegative_int(status.retryable_count),
        uncertain_count=_nonnegative_int(status.uncertain_count),
        updated_at_us=timestamp,
    )


def group_campaign_views(
    views: tuple[CampaignProgressView, ...],
) -> tuple[CampaignProgressGroup, ...]:
    """Group campaigns by attention, active work, then completed history."""

    buckets: dict[str, list[CampaignProgressView]] = {
        "attention": [],
        "active": [],
        "history": [],
    }
    seen: set[str] = set()
    for view in views:
        if not isinstance(view, CampaignProgressView) or view.campaign_id in seen:
            raise ProgressViewError("PROGRESS_VIEW_CAMPAIGN_INVALID")
        seen.add(view.campaign_id)
        try:
            status = HostTaskStatus(view.status)
        except ValueError as exc:
            raise ProgressViewError("PROGRESS_VIEW_CAMPAIGN_INVALID") from exc
        if (
            view.is_terminal != (status in _CAMPAIGN_TERMINAL)
            or view.needs_attention != (status in _CAMPAIGN_ATTENTION)
            or isinstance(view.updated_at_us, bool)
            or not isinstance(view.updated_at_us, int)
            or view.updated_at_us < 0
        ):
            raise ProgressViewError("PROGRESS_VIEW_CAMPAIGN_INVALID")
        if view.needs_attention:
            buckets["attention"].append(view)
        elif status is HostTaskStatus.RUNNING:
            buckets["active"].append(view)
        else:
            buckets["history"].append(view)

    groups: list[CampaignProgressGroup] = []
    for key, label in (
        ("attention", "Campaign attention"),
        ("active", "Active campaigns"),
        ("history", "Campaign history"),
    ):
        ordered = tuple(
            sorted(buckets[key], key=lambda view: (-view.updated_at_us, view.campaign_id))
        )
        if ordered:
            groups.append(CampaignProgressGroup(key, label, ordered))
    return tuple(groups)


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
        updated_at_us=validated_timestamp_us(checkpoint.get("updated_at")),
    )


def _scan_campaigns(
    state_dir: Path, *, now: datetime
) -> tuple[tuple[CampaignProgressView, ...], tuple[str, ...], int]:
    campaigns_dir = state_dir / "campaigns"
    if not campaigns_dir.exists():
        return (), (), 0
    if campaign_path_is_unsafe(campaigns_dir) or not campaigns_dir.is_dir():
        raise ProgressViewError("PROGRESS_VIEW_DIRECTORY_INVALID")
    try:
        entries = sorted(campaigns_dir.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise ProgressViewError("PROGRESS_VIEW_DIRECTORY_INVALID") from exc
    if len(entries) > MAX_PROGRESS_CAMPAIGNS:
        raise ProgressViewError("PROGRESS_VIEW_LIMIT_EXCEEDED")

    views: list[CampaignProgressView] = []
    unavailable_ids: list[str] = []
    unavailable_unnamed = 0
    for entry in entries:
        try:
            campaign_dir(state_dir, entry.name)
            safe_name = True
        except (CampaignStoreError, TypeError, ValueError):
            safe_name = False
        if (
            not safe_name
            or campaign_path_is_unsafe(entry)
            or not entry.is_dir()
        ):
            unavailable_unnamed += 1
            continue
        try:
            snapshot = read_campaign_control_snapshot(state_dir, entry.name)
            status = project_campaign_control_snapshot(snapshot, now=now)
            views.append(campaign_status_to_view(status))
        except (
            CampaignStoreError,
            HostStatusProjectionError,
            OSError,
            TypeError,
            ValueError,
            ProgressViewError,
        ):
            unavailable_ids.append(entry.name)
    return tuple(views), tuple(unavailable_ids), unavailable_unnamed


def build_progress_projection(
    state_dir: Path, *, now: datetime | None = None
) -> ProgressProjection:
    """Project every bounded run checkpoint under ``state_dir`` for the viewer.

    Directory-level tampering (a symlinked runs directory, an oversized scan)
    fails the whole scan closed. A single unreadable or corrupt run only makes
    that run unavailable.
    """

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    observed_at = datetime.now(UTC) if now is None else now
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")

    runs_dir = state_dir / "runs"
    views: list[RunProgressView] = []
    unavailable_run_ids: list[str] = []
    unavailable_unnamed = 0
    if runs_dir.exists():
        if runs_dir.is_symlink() or not runs_dir.is_dir():
            raise ProgressViewError("PROGRESS_VIEW_DIRECTORY_INVALID")
        try:
            entries = sorted(runs_dir.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise ProgressViewError("PROGRESS_VIEW_DIRECTORY_INVALID") from exc
        if len(entries) > MAX_PROGRESS_RUNS:
            raise ProgressViewError("PROGRESS_VIEW_LIMIT_EXCEEDED")

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

    campaigns, unavailable_campaign_ids, unavailable_campaign_unnamed = _scan_campaigns(
        state_dir,
        now=observed_at,
    )

    return ProgressProjection(
        views=tuple(views),
        unavailable_run_ids=tuple(unavailable_run_ids),
        unavailable_unnamed=unavailable_unnamed,
        campaigns=campaigns,
        unavailable_campaign_ids=unavailable_campaign_ids,
        unavailable_campaign_unnamed=unavailable_campaign_unnamed,
    )


__all__ = [
    "CallBudget",
    "CampaignProgressGroup",
    "CampaignProgressView",
    "MAX_PROGRESS_CAMPAIGNS",
    "ProgressProjection",
    "RunProgressGroup",
    "ProgressViewError",
    "RunProgressView",
    "build_progress_projection",
    "checkpoint_to_view",
    "campaign_status_to_view",
    "group_campaign_views",
    "group_progress_views",
    "validated_timestamp_us",
]
