"""Read-only campaign resume preflight over durable control state.

This module reports whether control state is ready for a future runner. It does
not create a batch, claim an item, invoke a provider, or perform desktop work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .campaign import CampaignStore
from .heartbeat_inspection import (
    HeartbeatFreshness,
    HeartbeatInspectionError,
    inspect_heartbeat,
)
from .lease_inspection import LeaseInspectionError, inspect_claim_leases


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")


class CampaignResumeError(ValueError):
    """Raised when resume readiness cannot be inspected safely."""


class CampaignResumeState(str, Enum):
    READY = "READY"
    HANDOFF_NOT_RESUMABLE = "HANDOFF_NOT_RESUMABLE"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_OWNER_MISMATCH = "HEARTBEAT_OWNER_MISMATCH"
    ACTIVE_BATCH = "ACTIVE_BATCH"
    CLAIMS_REMAIN = "CLAIMS_REMAIN"


@dataclass(frozen=True)
class CampaignResumePreflight:
    state: CampaignResumeState
    campaign_id: str
    run_id: str
    next_item_ordinal: int
    required_observation: str

    @property
    def ready(self) -> bool:
        return self.state is CampaignResumeState.READY


def inspect_campaign_resume(
    store: CampaignStore,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> CampaignResumePreflight:
    """Combine validated handoff, heartbeat, batch, and claim readiness."""

    if not isinstance(store, CampaignStore):
        raise CampaignResumeError("store must be a CampaignStore")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise CampaignResumeError("run_id is invalid")

    handoff = store.read_handoff(campaign_id)
    heartbeat_record = store.read_heartbeat(campaign_id)
    batches = store.read_batches(campaign_id)
    projection = store.read_ledger(campaign_id)
    try:
        heartbeat = inspect_heartbeat(heartbeat_record, now=now)
        leases = inspect_claim_leases(projection, now=now)
    except (HeartbeatInspectionError, LeaseInspectionError) as exc:
        raise CampaignResumeError("CAMPAIGN_RESUME_INVALID") from exc

    if handoff["next_action"] != "resume_batch":
        state = CampaignResumeState.HANDOFF_NOT_RESUMABLE
    elif heartbeat.freshness is HeartbeatFreshness.MISSING:
        state = CampaignResumeState.HEARTBEAT_MISSING
    elif heartbeat.run_id != run_id:
        state = CampaignResumeState.HEARTBEAT_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.STALE:
        state = CampaignResumeState.HEARTBEAT_STALE
    elif batches.active is not None:
        state = CampaignResumeState.ACTIVE_BATCH
    elif leases.active or leases.stale:
        state = CampaignResumeState.CLAIMS_REMAIN
    else:
        state = CampaignResumeState.READY
    return CampaignResumePreflight(
        state=state,
        campaign_id=campaign_id,
        run_id=run_id,
        next_item_ordinal=handoff["next_item_ordinal"],
        required_observation=handoff["required_observation"],
    )


__all__ = [
    "CampaignResumeError",
    "CampaignResumePreflight",
    "CampaignResumeState",
    "inspect_campaign_resume",
]
