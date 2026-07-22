"""Bounded, read-only campaign status for a future Codex or Claude host.

This module projects only validated campaign control records.  It has no
provider, MCP, desktop, approval, or worker ports and grants no execution
authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .campaign import (
    CAMPAIGN_VERSION,
    CampaignControlSnapshot,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    campaign_dir,
)
from .stale_run_inspection import (
    StaleRunInspectionError,
    StaleRunState,
    inspect_stale_control_state,
)


class HostStatusProjectionError(ValueError):
    """Raised when the projection request itself violates the host contract."""


class HostTaskStatus(str, Enum):
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    CHALLENGE = "CHALLENGE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"
    NEEDS_INSPECTION = "NEEDS_INSPECTION"


class HostEventKind(str, Enum):
    NONE = "NONE"
    NEEDS_ATTENTION = "NEEDS_ATTENTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


_ATTENTION_CODES = {
    HostTaskStatus.WAITING_APPROVAL: "WAITING_APPROVAL",
    HostTaskStatus.PAUSED: "CAMPAIGN_PAUSED",
    HostTaskStatus.CHALLENGE: "CAMPAIGN_CHALLENGE",
    HostTaskStatus.UNCERTAIN: "UNKNOWN_DISPATCH_OUTCOME",
    HostTaskStatus.STALE: "CAMPAIGN_STALE",
    HostTaskStatus.NEEDS_INSPECTION: "CAMPAIGN_STATE_INVALID",
}


@dataclass(frozen=True)
class CampaignHostStatus:
    campaign_id: str
    status: HostTaskStatus
    discovered_count: int
    completed_count: int
    retryable_count: int
    uncertain_count: int
    last_checkpoint_at: str | None
    attention_code: str | None = None

    @property
    def event_id(self) -> str | None:
        if self.status is HostTaskStatus.RUNNING:
            return None
        return _event_id(self)

    def as_json(self) -> dict[str, object]:
        return {
            "campaign_version": CAMPAIGN_VERSION,
            "campaign_id": self.campaign_id,
            "status": self.status.value,
            "discovered_count": self.discovered_count,
            "completed_count": self.completed_count,
            "retryable_count": self.retryable_count,
            "uncertain_count": self.uncertain_count,
            "last_checkpoint_at": self.last_checkpoint_at,
            "attention_code": self.attention_code,
            "event_id": self.event_id,
        }


@dataclass(frozen=True)
class HostPollState:
    """Host-retained fixed event identities used across context restarts."""

    emitted_event_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.emitted_event_ids, frozenset) or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in self.emitted_event_ids
        ):
            raise HostStatusProjectionError("HOST_STATUS_POLL_STATE_INVALID")


@dataclass(frozen=True)
class HostPollDecision:
    projection: CampaignHostStatus
    event_kind: HostEventKind
    should_continue_polling: bool
    emitted: bool
    state: HostPollState


def _event_id(status: CampaignHostStatus) -> str:
    payload = {
        "campaign_version": CAMPAIGN_VERSION,
        "campaign_id": status.campaign_id,
        "status": status.status.value,
        "discovered_count": status.discovered_count,
        "completed_count": status.completed_count,
        "retryable_count": status.retryable_count,
        "uncertain_count": status.uncertain_count,
        "last_checkpoint_at": status.last_checkpoint_at,
        "attention_code": status.attention_code,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _projection(
    *,
    campaign_id: str,
    status: HostTaskStatus,
    discovered_count: int,
    completed_count: int,
    retryable_count: int,
    uncertain_count: int,
    last_checkpoint_at: str | None,
    attention_code: str | None = None,
) -> CampaignHostStatus:
    return CampaignHostStatus(
        campaign_id=campaign_id,
        status=status,
        discovered_count=discovered_count,
        completed_count=completed_count,
        retryable_count=retryable_count,
        uncertain_count=uncertain_count,
        last_checkpoint_at=last_checkpoint_at,
        attention_code=attention_code,
    )


def _invalid_projection(campaign_id: str) -> CampaignHostStatus:
    return _projection(
        campaign_id=campaign_id,
        status=HostTaskStatus.NEEDS_INSPECTION,
        discovered_count=0,
        completed_count=0,
        retryable_count=0,
        uncertain_count=0,
        last_checkpoint_at=None,
        attention_code=_ATTENTION_CODES[HostTaskStatus.NEEDS_INSPECTION],
    )


def project_campaign_host_status(
    store: CampaignStore, *, campaign_id: str, now: datetime
) -> CampaignHostStatus:
    """Read one bounded status projection while the caller holds the run lock."""

    if not isinstance(store, CampaignStore):
        raise HostStatusProjectionError("HOST_STATUS_STORE_INVALID")
    if not store.lock.acquired:
        raise HostStatusProjectionError("HOST_STATUS_LOCK_REQUIRED")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise HostStatusProjectionError("HOST_STATUS_TIME_INVALID")
    try:
        campaign_dir(store.state_dir, campaign_id)
    except (CampaignStoreError, TypeError, ValueError) as exc:
        raise HostStatusProjectionError("HOST_STATUS_CAMPAIGN_ID_INVALID") from exc

    try:
        manifest = store.read_manifest(campaign_id)
        items = store.read_ledger(campaign_id)
        batches = store.read_batches(campaign_id)
        heartbeat = store.read_heartbeat(campaign_id)
        handoff = (
            store.read_handoff(campaign_id)
            if manifest.status in {CampaignStatus.COMPLETED, CampaignStatus.FAILED}
            else None
        )
    except (CampaignStoreError, StaleRunInspectionError, TypeError, ValueError):
        return _invalid_projection(campaign_id)
    snapshot = CampaignControlSnapshot(manifest, items, batches, heartbeat, handoff)
    return project_campaign_control_snapshot(snapshot, now=now)


def project_campaign_control_snapshot(
    snapshot: CampaignControlSnapshot, *, now: datetime
) -> CampaignHostStatus:
    """Project one stable decoded snapshot without acquiring execution authority."""

    if not isinstance(snapshot, CampaignControlSnapshot):
        raise HostStatusProjectionError("HOST_STATUS_SNAPSHOT_INVALID")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise HostStatusProjectionError("HOST_STATUS_TIME_INVALID")
    manifest = snapshot.manifest
    items = snapshot.items
    batches = snapshot.batches
    campaign_id = manifest.campaign_id
    try:
        liveness = inspect_stale_control_state(
            manifest,
            snapshot.heartbeat,
            items,
            now=now,
        )
    except (StaleRunInspectionError, TypeError, ValueError):
        return _invalid_projection(campaign_id)

    checkpoint_times = [manifest.updated_at]
    checkpoint_times.extend(item.at for item in items.transitions)
    checkpoint_times.extend(batch.at for batch in batches.transitions)
    if liveness.heartbeat.heartbeat_at is not None:
        checkpoint_times.append(liveness.heartbeat.heartbeat_at.isoformat())
    last_checkpoint_at = max(checkpoint_times, key=datetime.fromisoformat)
    counts = {
        "discovered_count": items.discovered_count,
        "completed_count": items.completed_count,
        "retryable_count": items.retryable_count,
        "uncertain_count": items.uncertain_count,
        "last_checkpoint_at": last_checkpoint_at,
    }

    if items.uncertain_count:
        status = HostTaskStatus.UNCERTAIN
    elif manifest.status is CampaignStatus.PAUSED:
        status = HostTaskStatus.PAUSED
    elif manifest.status is CampaignStatus.CHALLENGE:
        status = HostTaskStatus.CHALLENGE
    elif manifest.status is CampaignStatus.COMPLETED:
        handoff = snapshot.handoff
        if (
            handoff is None
            or batches.active is not None
            or items.completed_count != items.discovered_count
            or handoff["next_action"] != "none_completed"
        ):
            return _invalid_projection(campaign_id)
        status = HostTaskStatus.COMPLETED
        last_checkpoint_at = max(
            last_checkpoint_at,
            str(handoff["updated_at"]),
            key=datetime.fromisoformat,
        )
        counts["last_checkpoint_at"] = last_checkpoint_at
    elif manifest.status is CampaignStatus.FAILED:
        handoff = snapshot.handoff
        if (
            handoff is None
            or batches.active is not None
            or handoff["next_action"] != "human_review_failed"
        ):
            return _invalid_projection(campaign_id)
        status = HostTaskStatus.FAILED
    elif liveness.state is StaleRunState.FRESH_HEARTBEAT:
        status = HostTaskStatus.RUNNING
    else:
        status = HostTaskStatus.STALE

    attention_code = _ATTENTION_CODES.get(status)
    if status is HostTaskStatus.FAILED:
        attention_code = "CAMPAIGN_FAILED"
    return _projection(
        campaign_id=campaign_id,
        status=status,
        attention_code=attention_code,
        **counts,
    )


def evaluate_host_poll(
    projection: CampaignHostStatus, state: HostPollState = HostPollState()
) -> HostPollDecision:
    """Map one projection to a deduplicated fake-host event decision."""

    if not isinstance(projection, CampaignHostStatus) or not isinstance(state, HostPollState):
        raise HostStatusProjectionError("HOST_STATUS_POLL_INVALID")
    if projection.status is HostTaskStatus.RUNNING:
        return HostPollDecision(projection, HostEventKind.NONE, True, False, state)

    event_kind = {
        HostTaskStatus.COMPLETED: HostEventKind.COMPLETED,
        HostTaskStatus.FAILED: HostEventKind.FAILED,
        HostTaskStatus.CANCELLED: HostEventKind.FAILED,
        HostTaskStatus.UNCERTAIN: HostEventKind.UNCERTAIN,
    }.get(projection.status, HostEventKind.NEEDS_ATTENTION)
    if projection.event_id is None:
        raise HostStatusProjectionError("HOST_STATUS_EVENT_ID_MISSING")
    if projection.event_id in state.emitted_event_ids:
        return HostPollDecision(projection, HostEventKind.NONE, False, False, state)
    next_state = HostPollState(state.emitted_event_ids | {projection.event_id})
    return HostPollDecision(projection, event_kind, False, True, next_state)


__all__ = [
    "CampaignHostStatus",
    "HostEventKind",
    "HostPollDecision",
    "HostPollState",
    "HostStatusProjectionError",
    "HostTaskStatus",
    "evaluate_host_poll",
    "project_campaign_control_snapshot",
    "project_campaign_host_status",
]
