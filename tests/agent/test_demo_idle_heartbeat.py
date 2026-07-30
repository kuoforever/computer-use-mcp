from __future__ import annotations

import asyncio
from collections import deque

from computer_use_agent.demo_idle_heartbeat import HumanIdleHeartbeat


def test_idle_heartbeat_requires_a_consecutive_healthy_streak() -> None:
    samples = deque((0.1, 3.4, 0.2, 3.4, 3.6, 3.8))
    sleeps: list[float] = []

    async def no_wait(seconds: float) -> None:
        sleeps.append(seconds)

    heartbeat = HumanIdleHeartbeat(
        required_idle_seconds=3.25,
        poll_interval_seconds=0.25,
        consecutive_healthy_samples=3,
        max_wait_seconds=2,
    )

    assert asyncio.run(
        heartbeat.wait_until_stable(samples.popleft, sleep=no_wait)
    )
    assert sleeps == [0.25] * 5


def test_idle_heartbeat_fails_closed_on_probe_error() -> None:
    heartbeat = HumanIdleHeartbeat(required_idle_seconds=3.25)

    def failed_probe() -> float:
        raise OSError("unavailable")

    assert not asyncio.run(heartbeat.wait_until_stable(failed_probe))


def test_idle_heartbeat_times_out_without_a_healthy_streak() -> None:
    async def no_wait(_seconds: float) -> None:
        pass

    heartbeat = HumanIdleHeartbeat(
        required_idle_seconds=3.25,
        poll_interval_seconds=0.25,
        consecutive_healthy_samples=3,
        max_wait_seconds=1,
    )

    assert not asyncio.run(
        heartbeat.wait_until_stable(lambda: 0.0, sleep=no_wait)
    )
