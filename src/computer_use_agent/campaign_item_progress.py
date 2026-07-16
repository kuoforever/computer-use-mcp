"""Locked persistence for explicitly confirmed campaign item boundaries.

The caller is responsible for performing the required observation or bounded
read-only extraction. This module only revalidates durable control state and
records fixed boundaries; it does not observe or extract application content,
invoke a provider, dispatch MCP, or perform desktop work.
"""
from __future__ import annotations

from datetime import datetime

from .campaign import CampaignStore, ItemStatus, ItemTransition
from .campaign_extraction_preflight import inspect_observed_item
from .campaign_item_preflight import inspect_claimed_item


class CampaignItemProgressError(RuntimeError):
    """Fixed item-progression failure without application content."""


def record_item_observed(
    store: CampaignStore,
    *,
    campaign_id: str,
    batch_id: str,
    run_id: str,
    item_key: str,
    now: datetime,
    application_state_verified: bool,
    item_identity_verified: bool,
) -> ItemTransition:
    """Append OBSERVED only after both caller attestations and a fresh preflight."""

    if application_state_verified is not True or item_identity_verified is not True:
        raise CampaignItemProgressError("ITEM_OBSERVATION_REQUIRED")
    preflight = inspect_claimed_item(
        store,
        campaign_id=campaign_id,
        batch_id=batch_id,
        run_id=run_id,
        item_key=item_key,
        now=now,
    )
    if not preflight.ready:
        raise CampaignItemProgressError(f"ITEM_OBSERVATION_BLOCKED_{preflight.state.value}")
    projection = store.read_ledger(campaign_id)
    claimed = projection.items.get(item_key)
    if claimed is None or claimed.status is not ItemStatus.CLAIMED:
        raise CampaignItemProgressError("ITEM_OBSERVATION_STATE_DRIFT")
    if datetime.fromisoformat(claimed.at) > now:
        raise CampaignItemProgressError("ITEM_OBSERVATION_CLOCK_INVALID")
    updated = store.append(
        campaign_id,
        ItemTransition(
            sequence=1,
            ordinal=claimed.ordinal,
            item_key=claimed.item_key,
            status=ItemStatus.OBSERVED,
            attempt=claimed.attempt,
            at=now.isoformat(timespec="seconds"),
            run_id=run_id,
            boundary="reobserved",
            code="APPLICATION_AND_ITEM_VERIFIED",
        ),
    )
    return updated.items[item_key]


def record_item_extracted(
    store: CampaignStore,
    *,
    campaign_id: str,
    batch_id: str,
    run_id: str,
    item_key: str,
    now: datetime,
    read_only_extraction_completed: bool,
) -> ItemTransition:
    """Append EXTRACTED only after an exact caller attestation and fresh preflight."""

    if read_only_extraction_completed is not True:
        raise CampaignItemProgressError("ITEM_EXTRACTION_REQUIRED")
    preflight = inspect_observed_item(
        store,
        campaign_id=campaign_id,
        batch_id=batch_id,
        run_id=run_id,
        item_key=item_key,
        now=now,
    )
    if not preflight.ready:
        raise CampaignItemProgressError(f"ITEM_EXTRACTION_BLOCKED_{preflight.state.value}")
    projection = store.read_ledger(campaign_id)
    observed = projection.items.get(item_key)
    if observed is None or observed.status is not ItemStatus.OBSERVED:
        raise CampaignItemProgressError("ITEM_EXTRACTION_STATE_DRIFT")
    if datetime.fromisoformat(observed.at) > now:
        raise CampaignItemProgressError("ITEM_EXTRACTION_CLOCK_INVALID")
    updated = store.append(
        campaign_id,
        ItemTransition(
            sequence=1,
            ordinal=observed.ordinal,
            item_key=observed.item_key,
            status=ItemStatus.EXTRACTED,
            attempt=observed.attempt,
            at=now.isoformat(timespec="seconds"),
            run_id=run_id,
            boundary="extracted",
            code="READ_ONLY_EXTRACTION_COMPLETED",
        ),
    )
    return updated.items[item_key]


__all__ = [
    "CampaignItemProgressError",
    "record_item_extracted",
    "record_item_observed",
]
