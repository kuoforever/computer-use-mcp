"""Read-only readiness inspection for one durably claimed campaign item.

This module does not observe the application, advance the item ledger, invoke
a provider, dispatch MCP, or perform desktop work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .campaign import CampaignStatus, CampaignStore, ItemStatus
from .heartbeat_inspection import (
    HeartbeatFreshness,
    HeartbeatInspectionError,
    inspect_heartbeat,
)
from .lease_inspection import LeaseInspectionError, inspect_claim_leases


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_ITEM_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
REQUIRED_APPLICATION_OBSERVATION = "verify_current_page_and_account_state"
REQUIRED_ITEM_OBSERVATION = "verify_claimed_item_identity"


class CampaignItemPreflightError(ValueError):
    """Raised when claimed-item readiness cannot be inspected safely."""


class CampaignItemPreflightState(str, Enum):
    READY = "READY"
    CAMPAIGN_NOT_RUNNING = "CAMPAIGN_NOT_RUNNING"
    BATCH_NOT_ACTIVE = "BATCH_NOT_ACTIVE"
    BATCH_OWNER_MISMATCH = "BATCH_OWNER_MISMATCH"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_OWNER_MISMATCH = "HEARTBEAT_OWNER_MISMATCH"
    ITEM_NOT_CLAIMED = "ITEM_NOT_CLAIMED"
    CLAIM_SET_MISMATCH = "CLAIM_SET_MISMATCH"
    CLAIM_OWNER_MISMATCH = "CLAIM_OWNER_MISMATCH"
    CLAIM_LEASE_STALE = "CLAIM_LEASE_STALE"


@dataclass(frozen=True)
class CampaignItemPreflight:
    state: CampaignItemPreflightState
    campaign_id: str
    batch_id: str
    run_id: str
    item_key: str
    ordinal: int | None
    required_application_observation: str
    required_item_observation: str

    @property
    def ready(self) -> bool:
        return self.state is CampaignItemPreflightState.READY


def inspect_claimed_item(
    store: CampaignStore,
    *,
    campaign_id: str,
    batch_id: str,
    run_id: str,
    item_key: str,
    now: datetime,
) -> CampaignItemPreflight:
    """Report whether exactly one active claim is ready for re-observation."""

    if not isinstance(store, CampaignStore):
        raise CampaignItemPreflightError("store must be a CampaignStore")
    for name, value in (("batch_id", batch_id), ("run_id", run_id)):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise CampaignItemPreflightError(f"{name} is invalid")
    if not isinstance(item_key, str) or _ITEM_KEY.fullmatch(item_key) is None:
        raise CampaignItemPreflightError("item_key is invalid")

    manifest = store.read_manifest(campaign_id)
    active_batch = store.read_batches(campaign_id).active
    heartbeat_record = store.read_heartbeat(campaign_id)
    projection = store.read_ledger(campaign_id)
    try:
        heartbeat = inspect_heartbeat(heartbeat_record, now=now)
        leases = inspect_claim_leases(projection, now=now)
    except (HeartbeatInspectionError, LeaseInspectionError) as exc:
        raise CampaignItemPreflightError("CAMPAIGN_ITEM_PREFLIGHT_INVALID") from exc

    item = projection.items.get(item_key)
    claims = (*leases.active, *leases.stale)
    claim = next((candidate for candidate in claims if candidate.item_key == item_key), None)
    if manifest.status is not CampaignStatus.RUNNING:
        state = CampaignItemPreflightState.CAMPAIGN_NOT_RUNNING
    elif active_batch is None:
        state = CampaignItemPreflightState.BATCH_NOT_ACTIVE
    elif active_batch.batch_id != batch_id or active_batch.run_id != run_id:
        state = CampaignItemPreflightState.BATCH_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.MISSING:
        state = CampaignItemPreflightState.HEARTBEAT_MISSING
    elif heartbeat.run_id != run_id:
        state = CampaignItemPreflightState.HEARTBEAT_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.STALE:
        state = CampaignItemPreflightState.HEARTBEAT_STALE
    elif item is None or item.status is not ItemStatus.CLAIMED or claim is None:
        state = CampaignItemPreflightState.ITEM_NOT_CLAIMED
    elif len(claims) != 1:
        state = CampaignItemPreflightState.CLAIM_SET_MISMATCH
    elif claim.run_id != run_id:
        state = CampaignItemPreflightState.CLAIM_OWNER_MISMATCH
    elif claim in leases.stale:
        state = CampaignItemPreflightState.CLAIM_LEASE_STALE
    else:
        state = CampaignItemPreflightState.READY
    return CampaignItemPreflight(
        state=state,
        campaign_id=campaign_id,
        batch_id=batch_id,
        run_id=run_id,
        item_key=item_key,
        ordinal=None if item is None else item.ordinal,
        required_application_observation=REQUIRED_APPLICATION_OBSERVATION,
        required_item_observation=REQUIRED_ITEM_OBSERVATION,
    )


__all__ = [
    "REQUIRED_APPLICATION_OBSERVATION",
    "REQUIRED_ITEM_OBSERVATION",
    "CampaignItemPreflight",
    "CampaignItemPreflightError",
    "CampaignItemPreflightState",
    "inspect_claimed_item",
]
