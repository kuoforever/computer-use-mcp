from __future__ import annotations

from datetime import datetime, timezone

import pytest

from computer_use_agent.campaign import ItemStatus, ItemTransition, reduce_item_ledger
from computer_use_agent.lease_inspection import LeaseInspectionError, inspect_claim_leases


def _projection():
    return reduce_item_ledger(
        (
            ItemTransition(1, 2, "item_2", ItemStatus.DISCOVERED, 0, "2026-07-16T00:00:00+00:00"),
            ItemTransition(2, 1, "item_1", ItemStatus.DISCOVERED, 0, "2026-07-16T00:00:00+00:00"),
            ItemTransition(
                3, 1, "item_1", ItemStatus.CLAIMED, 1, "2026-07-16T00:00:00+00:00",
                run_id="run_1", lease_expires_at="2026-07-16T00:10:00+00:00", boundary="claim",
            ),
            ItemTransition(
                4, 2, "item_2", ItemStatus.CLAIMED, 1, "2026-07-16T00:00:00+00:00",
                run_id="run_2", lease_expires_at="2026-07-16T00:01:00+00:00", boundary="claim",
            ),
        )
    )


def test_inspection_sorts_active_and_stale_claims_without_mutating_projection() -> None:
    projection = _projection()
    inspection = inspect_claim_leases(
        projection, now=datetime(2026, 7, 16, 0, 1, tzinfo=timezone.utc)
    )

    assert [claim.item_key for claim in inspection.active] == ["item_1"]
    assert [claim.item_key for claim in inspection.stale] == ["item_2"]
    assert inspection.has_active_claim
    assert projection.items["item_2"].status is ItemStatus.CLAIMED


def test_lease_expiring_at_observation_time_is_stale() -> None:
    inspection = inspect_claim_leases(
        _projection(), now=datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)
    )

    assert inspection.active == ()
    assert [claim.item_key for claim in inspection.stale] == ["item_1", "item_2"]


def test_inspection_requires_an_aware_clock_and_valid_projection() -> None:
    with pytest.raises(LeaseInspectionError, match="timezone-aware"):
        inspect_claim_leases(_projection(), now=datetime(2026, 7, 16, 0, 1))
    with pytest.raises(LeaseInspectionError, match="CampaignProjection"):
        inspect_claim_leases(object(), now=datetime(2026, 7, 16, tzinfo=timezone.utc))  # type: ignore[arg-type]
