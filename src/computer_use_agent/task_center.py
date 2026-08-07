"""Read-only Task Center and human-readable fixed outcome receipts.

This module composes the existing structurally redacted progress projection and
optional private product receipts.  It has no provider, MCP, desktop, policy,
approval, resume, retry, cancel, campaign-advance, or persistence port.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .campaign_host_status import HostTaskStatus
from .product_receipt import (
    ProductReceiptError,
    product_receipt_path,
    read_product_receipt,
)
from .progress_view import (
    CampaignProgressView,
    ProgressProjection,
    RunProgressView,
    build_progress_projection,
)
from .trace import RunPhase


TASK_CENTER_VERSION = 1
DEFAULT_TASK_CENTER_LIMIT = 20
MAX_TASK_CENTER_LIMIT = 100

_RUN_ATTENTION = frozenset(
    {
        RunPhase.WAITING_APPROVAL,
        RunPhase.PAUSED,
        RunPhase.FAILED,
        RunPhase.UNKNOWN_OUTCOME,
    }
)


class TaskCenterError(RuntimeError):
    """Fixed failure from the read-only Task Center projection."""


@dataclass(frozen=True)
class TaskReceiptView:
    """One fixed, human-readable outcome without raw task or model content."""

    kind: str
    headline: str
    detail: str
    next_action: str
    artifact_path: str | None = None
    artifact_sha256: str | None = None
    artifact_verification: str | None = None
    cleanup_verification: str | None = None
    verified_at: str | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "headline": self.headline,
            "detail": self.detail,
            "next_action": self.next_action,
            "artifact_path": self.artifact_path,
            "artifact_sha256": self.artifact_sha256,
            "artifact_verification": self.artifact_verification,
            "cleanup_verification": self.cleanup_verification,
            "verified_at": self.verified_at,
        }


@dataclass(frozen=True)
class TaskCenterItem:
    task_kind: str
    task_id: str
    status: str
    display_state: str
    updated_at: str | None
    is_terminal: bool
    needs_attention: bool
    receipt: TaskReceiptView
    metrics: dict[str, object]
    updated_at_us: int

    def as_json(self) -> dict[str, object]:
        return {
            "task_kind": self.task_kind,
            "task_id": self.task_id,
            "status": self.status,
            "display_state": self.display_state,
            "updated_at": self.updated_at,
            "is_terminal": self.is_terminal,
            "needs_attention": self.needs_attention,
            "receipt": self.receipt.as_json(),
            "metrics": self.metrics,
        }


@dataclass(frozen=True)
class TaskCenterGroup:
    key: str
    label: str
    items: tuple[TaskCenterItem, ...]

    def as_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "items": [item.as_json() for item in self.items],
        }


@dataclass(frozen=True)
class TaskCenterProjection:
    groups: tuple[TaskCenterGroup, ...]
    total_items: int
    displayed_items: int
    unavailable_run_ids: tuple[str, ...]
    unavailable_runs_unnamed: int
    unavailable_campaign_ids: tuple[str, ...]
    unavailable_campaigns_unnamed: int

    def as_json(self) -> dict[str, object]:
        return {
            "task_center_version": TASK_CENTER_VERSION,
            "source": "validated_local_state",
            "read_only": True,
            "capabilities": {
                "approve": False,
                "resume": False,
                "retry": False,
                "cancel": False,
                "campaign_advance": False,
            },
            "total_items": self.total_items,
            "displayed_items": self.displayed_items,
            "groups": [group.as_json() for group in self.groups],
            "unavailable": {
                "run_ids": list(self.unavailable_run_ids),
                "runs_unnamed": self.unavailable_runs_unnamed,
                "campaign_ids": list(self.unavailable_campaign_ids),
                "campaigns_unnamed": self.unavailable_campaigns_unnamed,
            },
        }


def _timestamp_text(value: int) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TaskCenterError("TASK_CENTER_TIMESTAMP_INVALID")
    if value == 0:
        return None
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=value)).isoformat()


def _public_web_word_receipt(state_dir: Path, run: RunProgressView) -> TaskReceiptView | None:
    path = product_receipt_path(state_dir, run.run_id)
    workflow_state_exists = path.parent.exists()
    if not path.exists():
        if workflow_state_exists and run.phase == RunPhase.SUCCESS.value:
            return TaskReceiptView(
                kind="needs_inspection",
                headline="Workflow verification receipt unavailable",
                detail=(
                    "The run checkpoint is successful, but Task Center has no complete "
                    "artifact-and-cleanup receipt. Output completion is not claimed."
                ),
                next_action="Inspect the workflow result and local trace; do not retry automatically.",
            )
        return None
    try:
        receipt = read_product_receipt(state_dir, run.run_id)
    except ProductReceiptError:
        return TaskReceiptView(
            kind="needs_inspection",
            headline="Workflow verification receipt unavailable",
            detail="The stored receipt failed fixed-schema validation and is not trusted.",
            next_action="Inspect local workflow state; do not trust or automatically retry the output.",
        )
    return TaskReceiptView(
        kind="completion",
        headline="Document saved and verified",
        detail=(
            "The fixed workflow verified durable save, exact artifact digest, fresh reopen, "
            "and both fixture window cleanups."
        ),
        next_action="Review the verified output before relying on or sharing it.",
        artifact_path=str(receipt.artifact_path),
        artifact_sha256=receipt.artifact_sha256,
        artifact_verification="VERIFIED_AT_COMPLETION",
        cleanup_verification="VERIFIED",
        verified_at=receipt.verified_at,
    )


def _run_receipt(state_dir: Path, run: RunProgressView) -> TaskReceiptView:
    try:
        phase = RunPhase(run.phase)
    except ValueError as exc:
        raise TaskCenterError("TASK_CENTER_RUN_INVALID") from exc
    product = _public_web_word_receipt(state_dir, run)
    if product is not None:
        return product
    if phase is RunPhase.SUCCESS:
        return TaskReceiptView(
            kind="completion",
            headline="Run completed",
            detail=(
                "The Host recorded a successful terminal checkpoint. No verified product "
                "artifact receipt is linked to this run."
            ),
            next_action="Review the result returned by the originating command.",
        )
    if phase is RunPhase.UNKNOWN_OUTCOME:
        return TaskReceiptView(
            kind="uncertain",
            headline="Result unknown — do not retry automatically",
            detail="A side effect may have been dispatched, so success or failure is not proven.",
            next_action="Re-observe the desktop and inspect the trace before starting new work.",
        )
    if phase is RunPhase.FAILED:
        code = run.failure_code or "UNAVAILABLE"
        return TaskReceiptView(
            kind="failure",
            headline="Run failed",
            detail=f"The Host recorded fixed failure code {code}.",
            next_action="Inspect the safe trace and failure code before starting a new run.",
        )
    if phase is RunPhase.CANCELLED:
        return TaskReceiptView(
            kind="cancelled",
            headline="Run cancelled",
            detail="The Host recorded a terminal operator cancellation.",
            next_action="Confirm the current desktop state before starting a new run.",
        )
    if phase is RunPhase.WAITING_APPROVAL:
        return TaskReceiptView(
            kind="needs_input",
            headline="Approval needed",
            detail="This read-only Task Center cannot approve or deny the pending effect.",
            next_action="Return to the bound approval surface and inspect the exact request.",
        )
    if phase is RunPhase.PAUSED:
        return TaskReceiptView(
            kind="paused",
            headline="Run paused",
            detail="The checkpoint records a paused state; no continuation is inferred here.",
            next_action="Inspect the run and use only an existing reviewed resume path.",
        )
    return TaskReceiptView(
        kind="status",
        headline="Last checkpoint recorded",
        detail="The checkpoint is nonterminal and does not prove the process is still alive.",
        next_action="Confirm process and desktop state before taking any action.",
    )


def _campaign_receipt(campaign: CampaignProgressView) -> TaskReceiptView:
    try:
        status = HostTaskStatus(campaign.status)
    except ValueError as exc:
        raise TaskCenterError("TASK_CENTER_CAMPAIGN_INVALID") from exc
    if status is HostTaskStatus.COMPLETED:
        return TaskReceiptView(
            kind="completion",
            headline="Campaign completed",
            detail=(
                f"Validated state records {campaign.completed_count} of "
                f"{campaign.discovered_count} items completed."
            ),
            next_action="Review any separately verified outputs before relying on them.",
        )
    if status is HostTaskStatus.UNCERTAIN:
        return TaskReceiptView(
            kind="uncertain",
            headline="Campaign result unknown — do not retry automatically",
            detail=f"Validated state contains {campaign.uncertain_count} uncertain item(s).",
            next_action="Inspect the exact item state and re-observe before new execution.",
        )
    if status is HostTaskStatus.FAILED:
        return TaskReceiptView(
            kind="failure",
            headline="Campaign failed",
            detail="The durable campaign handoff requires human review.",
            next_action="Inspect the campaign ledger; this Task Center cannot resume it.",
        )
    if status is HostTaskStatus.CANCELLED:
        return TaskReceiptView(
            kind="cancelled",
            headline="Campaign cancelled",
            detail="Validated state records a terminal operator cancellation.",
            next_action="Review any partial outputs before starting a new campaign.",
        )
    if status in {HostTaskStatus.STALE, HostTaskStatus.NEEDS_INSPECTION}:
        return TaskReceiptView(
            kind="needs_inspection",
            headline="Campaign needs inspection",
            detail="Validated state does not prove a safe active or completed campaign.",
            next_action="Inspect durable campaign state before reclaim or execution.",
        )
    if status in {
        HostTaskStatus.WAITING_APPROVAL,
        HostTaskStatus.PAUSED,
        HostTaskStatus.CHALLENGE,
    }:
        return TaskReceiptView(
            kind="needs_input",
            headline="Campaign needs operator attention",
            detail="Task Center reports the state but cannot approve, resume, or advance it.",
            next_action="Use the separately reviewed control path after inspection.",
        )
    return TaskReceiptView(
        kind="status",
        headline="Campaign checkpoint recorded",
        detail="Validated aggregate progress is available without item content.",
        next_action="Continue only through the existing reviewed campaign command.",
    )


def _run_item(state_dir: Path, run: RunProgressView) -> TaskCenterItem:
    phase = RunPhase(run.phase)
    receipt = _run_receipt(state_dir, run)
    receipt_attention = receipt.kind == "needs_inspection"
    return TaskCenterItem(
        task_kind="run",
        task_id=run.run_id,
        status=run.phase,
        display_state=run.display_state,
        updated_at=_timestamp_text(run.updated_at_us),
        is_terminal=run.is_terminal,
        needs_attention=phase in _RUN_ATTENTION or receipt_attention,
        receipt=receipt,
        metrics={
            "model_calls": {"used": run.model_calls.used, "limit": run.model_calls.limit},
            "tool_calls": {"used": run.tool_calls.used, "limit": run.tool_calls.limit},
            "input_tokens": run.input_tokens,
            "output_tokens": run.output_tokens,
            "tool_failures": run.tool_failures,
            "duration_ms": run.duration_ms,
        },
        updated_at_us=run.updated_at_us,
    )


def _campaign_item(campaign: CampaignProgressView) -> TaskCenterItem:
    status = HostTaskStatus(campaign.status)
    return TaskCenterItem(
        task_kind="campaign",
        task_id=campaign.campaign_id,
        status=campaign.status,
        display_state=campaign.display_state,
        updated_at=_timestamp_text(campaign.updated_at_us),
        is_terminal=campaign.is_terminal,
        # A cancelled campaign is terminal history. Other validated campaign
        # attention states, including FAILED, remain prioritized for review.
        needs_attention=(
            campaign.needs_attention and status is not HostTaskStatus.CANCELLED
        ),
        receipt=_campaign_receipt(campaign),
        metrics={
            "discovered_count": campaign.discovered_count,
            "completed_count": campaign.completed_count,
            "retryable_count": campaign.retryable_count,
            "uncertain_count": campaign.uncertain_count,
        },
        updated_at_us=campaign.updated_at_us,
    )


def project_task_center(
    state_dir: Path,
    progress: ProgressProjection,
    *,
    limit: int = DEFAULT_TASK_CENTER_LIMIT,
) -> TaskCenterProjection:
    """Build one bounded Task Center from an already validated projection."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_TASK_CENTER_LIMIT:
        raise ValueError("TASK_CENTER_LIMIT_INVALID")
    if not isinstance(progress, ProgressProjection):
        raise TaskCenterError("TASK_CENTER_PROJECTION_INVALID")

    items = [*(_run_item(state_dir, run) for run in progress.views)]
    items.extend(_campaign_item(campaign) for campaign in progress.campaigns)
    buckets: dict[str, list[TaskCenterItem]] = {
        "attention": [],
        "in_progress": [],
        "history": [],
    }
    for item in items:
        if item.needs_attention:
            buckets["attention"].append(item)
        elif item.is_terminal:
            buckets["history"].append(item)
        else:
            buckets["in_progress"].append(item)

    remaining = limit
    groups: list[TaskCenterGroup] = []
    for key, label in (
        ("attention", "Attention"),
        ("in_progress", "In progress"),
        ("history", "History"),
    ):
        ordered = sorted(
            buckets[key],
            key=lambda item: (-item.updated_at_us, item.task_kind, item.task_id),
        )
        selected = tuple(ordered[:remaining])
        if selected:
            groups.append(TaskCenterGroup(key, label, selected))
            remaining -= len(selected)
        if remaining == 0:
            break

    return TaskCenterProjection(
        groups=tuple(groups),
        total_items=len(items),
        displayed_items=sum(len(group.items) for group in groups),
        unavailable_run_ids=progress.unavailable_run_ids,
        unavailable_runs_unnamed=progress.unavailable_unnamed,
        unavailable_campaign_ids=progress.unavailable_campaign_ids,
        unavailable_campaigns_unnamed=progress.unavailable_campaign_unnamed,
    )


def build_task_center(
    state_dir: Path,
    *,
    limit: int = DEFAULT_TASK_CENTER_LIMIT,
    now: datetime | None = None,
) -> TaskCenterProjection:
    """Read validated local state and return one read-only Task Center."""

    progress = build_progress_projection(state_dir, now=now)
    return project_task_center(state_dir, progress, limit=limit)


def render_task_center(center: TaskCenterProjection) -> str:
    """Render bounded plain text for the installed CLI-first product surface."""

    if not isinstance(center, TaskCenterProjection):
        raise TaskCenterError("TASK_CENTER_PROJECTION_INVALID")
    lines = [
        "Guarded Desktop Agent Task Center",
        "Read-only status: cannot approve, resume, retry, cancel, or advance work.",
    ]
    if center.total_items == 0:
        lines.append("No validated local tasks found.")
    for group in center.groups:
        lines.append("")
        lines.append(f"{group.label} ({len(group.items)})")
        for item in group.items:
            updated = item.updated_at or "time unavailable"
            lines.append(
                f"- [{item.task_kind.upper()}] {item.task_id} · {item.display_state} · {updated}"
            )
            lines.append(f"  {item.receipt.headline}")
            lines.append(f"  {item.receipt.detail}")
            if item.receipt.artifact_path is not None:
                lines.append(f"  Output: {item.receipt.artifact_path}")
                lines.append(f"  SHA-256: {item.receipt.artifact_sha256}")
                lines.append(
                    "  Verification: "
                    f"{item.receipt.artifact_verification}; cleanup "
                    f"{item.receipt.cleanup_verification}"
                )
            lines.append(f"  Next: {item.receipt.next_action}")
    if center.displayed_items < center.total_items:
        lines.append("")
        lines.append(
            f"Showing {center.displayed_items} of {center.total_items} validated tasks."
        )
    unavailable = (
        len(center.unavailable_run_ids)
        + center.unavailable_runs_unnamed
        + len(center.unavailable_campaign_ids)
        + center.unavailable_campaigns_unnamed
    )
    if unavailable:
        lines.append("")
        lines.append(
            f"Unavailable local records: {unavailable}. They were excluded rather than trusted."
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_TASK_CENTER_LIMIT",
    "MAX_TASK_CENTER_LIMIT",
    "TASK_CENTER_VERSION",
    "TaskCenterError",
    "TaskCenterGroup",
    "TaskCenterItem",
    "TaskCenterProjection",
    "TaskReceiptView",
    "build_task_center",
    "project_task_center",
    "render_task_center",
]
