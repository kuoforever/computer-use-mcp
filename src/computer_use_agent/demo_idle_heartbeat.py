"""Bounded approval-to-dispatch idle heartbeat for the visible GUI Demo."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class HumanIdleHeartbeat:
    """Require several consecutive healthy idle samples before dispatch."""

    required_idle_seconds: float
    poll_interval_seconds: float = 0.25
    consecutive_healthy_samples: int = 3
    max_wait_seconds: float = 60.0

    def __post_init__(self) -> None:
        for value, name in (
            (self.required_idle_seconds, "required_idle_seconds"),
            (self.poll_interval_seconds, "poll_interval_seconds"),
            (self.max_wait_seconds, "max_wait_seconds"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        if (
            isinstance(self.consecutive_healthy_samples, bool)
            or not isinstance(self.consecutive_healthy_samples, int)
            or self.consecutive_healthy_samples <= 0
        ):
            raise ValueError("consecutive_healthy_samples must be positive")

    async def wait_until_stable(
        self,
        probe: Callable[[], float],
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> bool:
        """Return true only after a stable idle streak; probe failures deny."""

        max_samples = max(1, math.ceil(self.max_wait_seconds / self.poll_interval_seconds))
        healthy_samples = 0
        for sample_index in range(max_samples):
            try:
                idle_seconds = float(probe())
            except (OSError, TypeError, ValueError):
                return False
            if math.isfinite(idle_seconds) and idle_seconds >= self.required_idle_seconds:
                healthy_samples += 1
                if healthy_samples >= self.consecutive_healthy_samples:
                    return True
            else:
                healthy_samples = 0
            if sample_index + 1 < max_samples:
                await sleep(self.poll_interval_seconds)
        return False


__all__ = ["HumanIdleHeartbeat"]
