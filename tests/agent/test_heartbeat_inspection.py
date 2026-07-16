from __future__ import annotations

from datetime import datetime, timezone

import pytest

from computer_use_agent.campaign import CampaignHeartbeat
from computer_use_agent.heartbeat_inspection import (
    HeartbeatFreshness,
    HeartbeatInspectionError,
    inspect_heartbeat,
)


def _heartbeat() -> CampaignHeartbeat:
    return CampaignHeartbeat(
        campaign_id="campaign_1",
        run_id="run_1",
        started_at="2026-07-16T00:00:00+00:00",
        heartbeat_at="2026-07-16T00:01:00+00:00",
        fresh_until="2026-07-16T00:06:00+00:00",
    )


def test_inspection_reports_missing_without_inventing_run_identity() -> None:
    inspection = inspect_heartbeat(
        None, now=datetime(2026, 7, 16, 0, 2, tzinfo=timezone.utc)
    )

    assert inspection.freshness is HeartbeatFreshness.MISSING
    assert inspection.run_id is None
    assert inspection.heartbeat_at is None
    assert inspection.fresh_until is None
    assert inspection.is_fresh is False


def test_inspection_reports_fresh_with_bounded_control_metadata() -> None:
    inspection = inspect_heartbeat(
        _heartbeat(), now=datetime(2026, 7, 16, 0, 5, 59, tzinfo=timezone.utc)
    )

    assert inspection.freshness is HeartbeatFreshness.FRESH
    assert inspection.run_id == "run_1"
    assert inspection.heartbeat_at == datetime(2026, 7, 16, 0, 1, tzinfo=timezone.utc)
    assert inspection.fresh_until == datetime(2026, 7, 16, 0, 6, tzinfo=timezone.utc)
    assert inspection.is_fresh


def test_heartbeat_expiring_at_observation_time_is_stale() -> None:
    inspection = inspect_heartbeat(
        _heartbeat(), now=datetime(2026, 7, 16, 0, 6, tzinfo=timezone.utc)
    )

    assert inspection.freshness is HeartbeatFreshness.STALE
    assert inspection.is_fresh is False


def test_inspection_rejects_naive_future_or_invalid_observations() -> None:
    with pytest.raises(HeartbeatInspectionError, match="timezone-aware"):
        inspect_heartbeat(_heartbeat(), now=datetime(2026, 7, 16, 0, 2))
    with pytest.raises(HeartbeatInspectionError, match="precedes"):
        inspect_heartbeat(
            _heartbeat(), now=datetime(2026, 7, 16, 0, 0, 59, tzinfo=timezone.utc)
        )
    with pytest.raises(HeartbeatInspectionError, match="CampaignHeartbeat"):
        inspect_heartbeat(
            object(),  # type: ignore[arg-type]
            now=datetime(2026, 7, 16, 0, 2, tzinfo=timezone.utc),
        )
