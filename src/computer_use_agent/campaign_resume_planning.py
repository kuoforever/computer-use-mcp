"""Read-only bounded batch planning after campaign resume preflight.

This module does not persist a batch lifecycle, claim an item, invoke a
provider, or perform desktop work.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .batching import BatchPlan, BatchPolicy, BatchUsage, plan_batch
from .campaign import CampaignStore
from .campaign_resume import CampaignResumePreflight, inspect_campaign_resume


class CampaignResumePlanningError(ValueError):
    """Raised when a resume planning request is not bounded."""


@dataclass(frozen=True)
class CampaignResumePlan:
    preflight: CampaignResumePreflight
    batch: BatchPlan | None

    @property
    def has_nonempty_plan(self) -> bool:
        return (
            self.preflight.ready
            and self.batch is not None
            and bool(self.batch.item_keys)
            and self.batch.stop_reason is None
        )


def plan_campaign_resume(
    store: CampaignStore,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
    policy: BatchPolicy,
) -> CampaignResumePlan:
    """Return a deterministic initial batch selection without persistence."""

    if not isinstance(policy, BatchPolicy):
        raise CampaignResumePlanningError("policy must be a BatchPolicy")
    preflight = inspect_campaign_resume(
        store,
        campaign_id=campaign_id,
        run_id=run_id,
        now=now,
    )
    if not preflight.ready:
        return CampaignResumePlan(preflight=preflight, batch=None)
    batch = plan_batch(store.read_ledger(campaign_id), policy, BatchUsage())
    return CampaignResumePlan(preflight=preflight, batch=batch)


__all__ = [
    "CampaignResumePlan",
    "CampaignResumePlanningError",
    "plan_campaign_resume",
]
