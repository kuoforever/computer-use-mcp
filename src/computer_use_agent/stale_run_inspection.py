"""Combined read-only stale-run inspection for campaign control state.

The caller must already hold the campaign store's OS run lock. A stale result
only permits a separately reviewed recovery step; it never authorizes action
replay or item execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .campaign import CampaignStatus, CampaignStore
from .heartbeat_inspection import (
    HeartbeatFreshness,
    HeartbeatInspection,
    HeartbeatInspectionError,
    inspect_heartbeat,
)
from .lease_inspection import (
    LeaseInspection,
    LeaseInspectionError,
    inspect_claim_leases,
)


class StaleRunInspectionError(ValueError):
    """Raised when combined recovery state cannot be inspected safely."""


class StaleRunState(str, Enum):
    PAUSED = "PAUSED"
    NOT_RUNNING = "NOT_RUNNING"
    MISSING_HEARTBEAT = "MISSING_HEARTBEAT"
    FRESH_HEARTBEAT = "FRESH_HEARTBEAT"
    ACTIVE_LEASE = "ACTIVE_LEASE"
    INCONSISTENT_OWNER = "INCONSISTENT_OWNER"
    STALE = "STALE"


@dataclass(frozen=True)
class StaleRunInspection:
    state: StaleRunState
    heartbeat: HeartbeatInspection
    leases: LeaseInspection

    @property
    def is_recovery_candidate(self) -> bool:
        return self.state is StaleRunState.STALE


def inspect_stale_run(
    store: CampaignStore, *, campaign_id: str, now: datetime
) -> StaleRunInspection:
    """Combine manifest, heartbeat, and claim leases under an acquired run lock."""

    if not isinstance(store, CampaignStore):
        raise StaleRunInspectionError("store must be a CampaignStore")
    manifest = store.read_manifest(campaign_id)
    heartbeat_record = store.read_heartbeat(campaign_id)
    projection = store.read_ledger(campaign_id)
    try:
        heartbeat = inspect_heartbeat(heartbeat_record, now=now)
        leases = inspect_claim_leases(projection, now=now)
    except (HeartbeatInspectionError, LeaseInspectionError) as exc:
        raise StaleRunInspectionError("STALE_RUN_INSPECTION_INVALID") from exc

    if manifest.status is CampaignStatus.PAUSED:
        state = StaleRunState.PAUSED
    elif manifest.status is not CampaignStatus.RUNNING:
        state = StaleRunState.NOT_RUNNING
    elif heartbeat.freshness is HeartbeatFreshness.MISSING:
        state = StaleRunState.MISSING_HEARTBEAT
    else:
        claim_run_ids = {
            claim.run_id for claim in (*leases.active, *leases.stale)
        }
        if heartbeat.run_id is None or any(
            run_id != heartbeat.run_id for run_id in claim_run_ids
        ):
            state = StaleRunState.INCONSISTENT_OWNER
        elif heartbeat.freshness is HeartbeatFreshness.FRESH:
            state = StaleRunState.FRESH_HEARTBEAT
        elif leases.has_active_claim:
            state = StaleRunState.ACTIVE_LEASE
        else:
            state = StaleRunState.STALE
    return StaleRunInspection(state=state, heartbeat=heartbeat, leases=leases)


__all__ = [
    "StaleRunInspection",
    "StaleRunInspectionError",
    "StaleRunState",
    "inspect_stale_run",
]
