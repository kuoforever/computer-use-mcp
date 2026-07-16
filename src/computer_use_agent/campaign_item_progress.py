"""Locked persistence for one explicitly confirmed item observation boundary.

The caller is responsible for performing both required observations. This
module only revalidates durable control state and records the fixed boundary;
it does not observe an application, invoke a provider, dispatch MCP, or perform
desktop work.
"""
from __future__ import annotations

from datetime import datetime

from .campaign import CampaignStore, ItemStatus, ItemTransition
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


__all__ = ["CampaignItemProgressError", "record_item_observed"]
