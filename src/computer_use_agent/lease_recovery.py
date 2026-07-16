"""Locked control-state recovery for expired campaign item claims.

This module only releases a proven-stale claim back to ``RETRYABLE``. It does
not claim the item for a new run, re-observe application state, invoke a
provider, or replay an action.
"""
from __future__ import annotations

from datetime import datetime

from .campaign import (
    CampaignProjection,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from .lease_inspection import inspect_claim_leases


class LeaseRecoveryError(RuntimeError):
    """Raised when an item claim cannot be released safely."""


def release_stale_claim(
    store: CampaignStore,
    *,
    campaign_id: str,
    item_key: str,
    recovery_run_id: str,
    now: datetime,
) -> CampaignProjection:
    """Append one fixed stale-lease release under the store's acquired run lock."""

    if not isinstance(store, CampaignStore):
        raise LeaseRecoveryError("store must be a CampaignStore")
    projection = store.read_ledger(campaign_id)
    inspection = inspect_claim_leases(projection, now=now)
    stale = next((claim for claim in inspection.stale if claim.item_key == item_key), None)
    if stale is None:
        if any(claim.item_key == item_key for claim in inspection.active):
            raise LeaseRecoveryError("LEASE_RECOVERY_ACTIVE")
        raise LeaseRecoveryError("LEASE_RECOVERY_NOT_CLAIMED")

    current = projection.items[item_key]
    return store.append(
        campaign_id,
        ItemTransition(
            sequence=len(projection.transitions) + 1,
            ordinal=current.ordinal,
            item_key=current.item_key,
            status=ItemStatus.RETRYABLE,
            attempt=current.attempt,
            at=now.isoformat(timespec="seconds"),
            run_id=recovery_run_id,
            boundary="lease_expired",
            code="LEASE_EXPIRED",
        ),
    )


__all__ = ["LeaseRecoveryError", "release_stale_claim"]
