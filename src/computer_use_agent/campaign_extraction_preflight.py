"""Read-only readiness inspection for one observed campaign item.

This module only decides whether a future worker may begin bounded read-only
extraction. It does not extract content, advance the item ledger, invoke a
provider, dispatch MCP, or perform desktop work.
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


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_ITEM_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
REQUIRED_EXTRACTION = "perform_bounded_read_only_extraction"
_IN_FLIGHT_STATUSES = frozenset(
    {ItemStatus.CLAIMED, ItemStatus.OBSERVED, ItemStatus.EXTRACTED}
)


class CampaignExtractionPreflightError(ValueError):
    """Raised when observed-item readiness cannot be inspected safely."""


class CampaignExtractionPreflightState(str, Enum):
    READY = "READY"
    CAMPAIGN_NOT_RUNNING = "CAMPAIGN_NOT_RUNNING"
    BATCH_NOT_ACTIVE = "BATCH_NOT_ACTIVE"
    BATCH_OWNER_MISMATCH = "BATCH_OWNER_MISMATCH"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_OWNER_MISMATCH = "HEARTBEAT_OWNER_MISMATCH"
    ITEM_NOT_OBSERVED = "ITEM_NOT_OBSERVED"
    IN_FLIGHT_SET_MISMATCH = "IN_FLIGHT_SET_MISMATCH"
    ITEM_OWNER_MISMATCH = "ITEM_OWNER_MISMATCH"


@dataclass(frozen=True)
class CampaignExtractionPreflight:
    state: CampaignExtractionPreflightState
    campaign_id: str
    batch_id: str
    run_id: str
    item_key: str
    ordinal: int | None
    required_extraction: str

    @property
    def ready(self) -> bool:
        return self.state is CampaignExtractionPreflightState.READY


def inspect_observed_item(
    store: CampaignStore,
    *,
    campaign_id: str,
    batch_id: str,
    run_id: str,
    item_key: str,
    now: datetime,
) -> CampaignExtractionPreflight:
    """Report whether one exact observed item is ready for read-only extraction."""

    if not isinstance(store, CampaignStore):
        raise CampaignExtractionPreflightError("store must be a CampaignStore")
    for name, value in (("batch_id", batch_id), ("run_id", run_id)):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise CampaignExtractionPreflightError(f"{name} is invalid")
    if not isinstance(item_key, str) or _ITEM_KEY.fullmatch(item_key) is None:
        raise CampaignExtractionPreflightError("item_key is invalid")

    manifest = store.read_manifest(campaign_id)
    active_batch = store.read_batches(campaign_id).active
    projection = store.read_ledger(campaign_id)
    try:
        heartbeat = inspect_heartbeat(store.read_heartbeat(campaign_id), now=now)
    except HeartbeatInspectionError as exc:
        raise CampaignExtractionPreflightError(
            "CAMPAIGN_EXTRACTION_PREFLIGHT_INVALID"
        ) from exc

    item = projection.items.get(item_key)
    in_flight = tuple(
        candidate
        for candidate in projection.items.values()
        if candidate.status in _IN_FLIGHT_STATUSES
    )
    if manifest.status is not CampaignStatus.RUNNING:
        state = CampaignExtractionPreflightState.CAMPAIGN_NOT_RUNNING
    elif active_batch is None:
        state = CampaignExtractionPreflightState.BATCH_NOT_ACTIVE
    elif active_batch.batch_id != batch_id or active_batch.run_id != run_id:
        state = CampaignExtractionPreflightState.BATCH_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.MISSING:
        state = CampaignExtractionPreflightState.HEARTBEAT_MISSING
    elif heartbeat.run_id != run_id:
        state = CampaignExtractionPreflightState.HEARTBEAT_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.STALE:
        state = CampaignExtractionPreflightState.HEARTBEAT_STALE
    elif item is None or item.status is not ItemStatus.OBSERVED:
        state = CampaignExtractionPreflightState.ITEM_NOT_OBSERVED
    elif len(in_flight) != 1 or in_flight[0].item_key != item_key:
        state = CampaignExtractionPreflightState.IN_FLIGHT_SET_MISMATCH
    elif item.run_id != run_id:
        state = CampaignExtractionPreflightState.ITEM_OWNER_MISMATCH
    else:
        state = CampaignExtractionPreflightState.READY
    return CampaignExtractionPreflight(
        state=state,
        campaign_id=campaign_id,
        batch_id=batch_id,
        run_id=run_id,
        item_key=item_key,
        ordinal=None if item is None else item.ordinal,
        required_extraction=REQUIRED_EXTRACTION,
    )


__all__ = [
    "REQUIRED_EXTRACTION",
    "CampaignExtractionPreflight",
    "CampaignExtractionPreflightError",
    "CampaignExtractionPreflightState",
    "inspect_observed_item",
]
