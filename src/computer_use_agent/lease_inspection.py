"""Read-only claim-lease inspection for campaign recovery decisions.

Expired leases are reported as stale control state.  This module intentionally
does not reclaim an item, mutate a ledger, or authorize replay of an action.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .campaign import CampaignProjection, ItemStatus


class LeaseInspectionError(ValueError):
    """Raised when a recovery observation cannot be compared safely."""


@dataclass(frozen=True)
class LeaseClaim:
    item_key: str
    ordinal: int
    run_id: str
    expires_at: datetime


@dataclass(frozen=True)
class LeaseInspection:
    active: tuple[LeaseClaim, ...]
    stale: tuple[LeaseClaim, ...]

    @property
    def has_active_claim(self) -> bool:
        return bool(self.active)


def inspect_claim_leases(
    projection: CampaignProjection, *, now: datetime
) -> LeaseInspection:
    """Classify only current CLAIMED items against an injected aware timestamp."""

    if not isinstance(projection, CampaignProjection):
        raise LeaseInspectionError("projection must be a CampaignProjection")
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise LeaseInspectionError("now must be a timezone-aware datetime")
    active: list[LeaseClaim] = []
    stale: list[LeaseClaim] = []
    for item in sorted(projection.items.values(), key=lambda value: (value.ordinal, value.item_key)):
        if item.status is not ItemStatus.CLAIMED:
            continue
        if item.run_id is None or item.lease_expires_at is None:
            raise LeaseInspectionError("claimed item has no valid lease")
        claim = LeaseClaim(
            item_key=item.item_key,
            ordinal=item.ordinal,
            run_id=item.run_id,
            expires_at=datetime.fromisoformat(item.lease_expires_at),
        )
        if claim.expires_at <= now:
            stale.append(claim)
        else:
            active.append(claim)
    return LeaseInspection(active=tuple(active), stale=tuple(stale))


__all__ = ["LeaseClaim", "LeaseInspection", "LeaseInspectionError", "inspect_claim_leases"]
