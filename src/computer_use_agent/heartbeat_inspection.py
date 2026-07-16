"""Pure freshness inspection for persisted campaign heartbeat control state.

Freshness is only one recovery signal. This module does not inspect the OS run
lock, classify a process as alive, mutate campaign state, or authorize reclaim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .campaign import CampaignHeartbeat


class HeartbeatInspectionError(ValueError):
    """Raised when heartbeat freshness cannot be compared safely."""


class HeartbeatFreshness(str, Enum):
    MISSING = "MISSING"
    FRESH = "FRESH"
    STALE = "STALE"


@dataclass(frozen=True)
class HeartbeatInspection:
    freshness: HeartbeatFreshness
    run_id: str | None
    heartbeat_at: datetime | None
    fresh_until: datetime | None

    @property
    def is_fresh(self) -> bool:
        return self.freshness is HeartbeatFreshness.FRESH


def inspect_heartbeat(
    heartbeat: CampaignHeartbeat | None, *, now: datetime
) -> HeartbeatInspection:
    """Classify one optional heartbeat against an injected aware timestamp."""

    if not isinstance(now, datetime) or now.tzinfo is None:
        raise HeartbeatInspectionError("now must be a timezone-aware datetime")
    if heartbeat is None:
        return HeartbeatInspection(HeartbeatFreshness.MISSING, None, None, None)
    if not isinstance(heartbeat, CampaignHeartbeat):
        raise HeartbeatInspectionError("heartbeat must be a CampaignHeartbeat or None")

    heartbeat_at = datetime.fromisoformat(heartbeat.heartbeat_at)
    fresh_until = datetime.fromisoformat(heartbeat.fresh_until)
    if now < heartbeat_at:
        raise HeartbeatInspectionError("now precedes the recorded heartbeat")
    freshness = (
        HeartbeatFreshness.STALE
        if fresh_until <= now
        else HeartbeatFreshness.FRESH
    )
    return HeartbeatInspection(
        freshness=freshness,
        run_id=heartbeat.run_id,
        heartbeat_at=heartbeat_at,
        fresh_until=fresh_until,
    )


__all__ = [
    "HeartbeatFreshness",
    "HeartbeatInspection",
    "HeartbeatInspectionError",
    "inspect_heartbeat",
]
