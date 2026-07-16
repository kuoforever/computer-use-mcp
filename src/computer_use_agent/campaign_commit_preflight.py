"""Read-only commit readiness inspection for one extracted campaign item.

This module only decides whether a future worker may verify and prepare one
bounded read-only extraction result for commit. It does not inspect result
content, calculate a digest, advance the item ledger, invoke a provider,
dispatch MCP, or perform desktop work.
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
REQUIRED_RESULT_VERIFICATION = "verify_bounded_extraction_result"
REQUIRED_COMMIT_PREPARATION = "prepare_content_digest_and_fixed_result_code"
_IN_FLIGHT_STATUSES = frozenset(
    {ItemStatus.CLAIMED, ItemStatus.OBSERVED, ItemStatus.EXTRACTED}
)


class CampaignCommitPreflightError(ValueError):
    """Raised when extracted-item commit readiness cannot be inspected safely."""


class CampaignCommitPreflightState(str, Enum):
    READY = "READY"
    CAMPAIGN_NOT_RUNNING = "CAMPAIGN_NOT_RUNNING"
    BATCH_NOT_ACTIVE = "BATCH_NOT_ACTIVE"
    BATCH_OWNER_MISMATCH = "BATCH_OWNER_MISMATCH"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_OWNER_MISMATCH = "HEARTBEAT_OWNER_MISMATCH"
    ITEM_NOT_EXTRACTED = "ITEM_NOT_EXTRACTED"
    IN_FLIGHT_SET_MISMATCH = "IN_FLIGHT_SET_MISMATCH"
    ITEM_OWNER_MISMATCH = "ITEM_OWNER_MISMATCH"


@dataclass(frozen=True)
class CampaignCommitPreflight:
    state: CampaignCommitPreflightState
    campaign_id: str
    batch_id: str
    run_id: str
    item_key: str
    ordinal: int | None
    required_result_verification: str
    required_commit_preparation: str

    @property
    def ready(self) -> bool:
        return self.state is CampaignCommitPreflightState.READY


def inspect_extracted_item(
    store: CampaignStore,
    *,
    campaign_id: str,
    batch_id: str,
    run_id: str,
    item_key: str,
    now: datetime,
) -> CampaignCommitPreflight:
    """Report whether one exact extracted item is ready for commit preparation."""

    if not isinstance(store, CampaignStore):
        raise CampaignCommitPreflightError("store must be a CampaignStore")
    for name, value in (("batch_id", batch_id), ("run_id", run_id)):
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise CampaignCommitPreflightError(f"{name} is invalid")
    if not isinstance(item_key, str) or _ITEM_KEY.fullmatch(item_key) is None:
        raise CampaignCommitPreflightError("item_key is invalid")

    manifest = store.read_manifest(campaign_id)
    active_batch = store.read_batches(campaign_id).active
    projection = store.read_ledger(campaign_id)
    try:
        heartbeat = inspect_heartbeat(store.read_heartbeat(campaign_id), now=now)
    except HeartbeatInspectionError as exc:
        raise CampaignCommitPreflightError(
            "CAMPAIGN_COMMIT_PREFLIGHT_INVALID"
        ) from exc

    item = projection.items.get(item_key)
    in_flight = tuple(
        candidate
        for candidate in projection.items.values()
        if candidate.status in _IN_FLIGHT_STATUSES
    )
    if manifest.status is not CampaignStatus.RUNNING:
        state = CampaignCommitPreflightState.CAMPAIGN_NOT_RUNNING
    elif active_batch is None:
        state = CampaignCommitPreflightState.BATCH_NOT_ACTIVE
    elif active_batch.batch_id != batch_id or active_batch.run_id != run_id:
        state = CampaignCommitPreflightState.BATCH_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.MISSING:
        state = CampaignCommitPreflightState.HEARTBEAT_MISSING
    elif heartbeat.run_id != run_id:
        state = CampaignCommitPreflightState.HEARTBEAT_OWNER_MISMATCH
    elif heartbeat.freshness is HeartbeatFreshness.STALE:
        state = CampaignCommitPreflightState.HEARTBEAT_STALE
    elif item is None or item.status is not ItemStatus.EXTRACTED:
        state = CampaignCommitPreflightState.ITEM_NOT_EXTRACTED
    elif len(in_flight) != 1 or in_flight[0].item_key != item_key:
        state = CampaignCommitPreflightState.IN_FLIGHT_SET_MISMATCH
    elif item.run_id != run_id:
        state = CampaignCommitPreflightState.ITEM_OWNER_MISMATCH
    else:
        state = CampaignCommitPreflightState.READY
    return CampaignCommitPreflight(
        state=state,
        campaign_id=campaign_id,
        batch_id=batch_id,
        run_id=run_id,
        item_key=item_key,
        ordinal=None if item is None else item.ordinal,
        required_result_verification=REQUIRED_RESULT_VERIFICATION,
        required_commit_preparation=REQUIRED_COMMIT_PREPARATION,
    )


__all__ = [
    "REQUIRED_COMMIT_PREPARATION",
    "REQUIRED_RESULT_VERIFICATION",
    "CampaignCommitPreflight",
    "CampaignCommitPreflightError",
    "CampaignCommitPreflightState",
    "inspect_extracted_item",
]
