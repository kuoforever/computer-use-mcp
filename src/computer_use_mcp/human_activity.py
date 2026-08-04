"""Serial yielding for shared-desktop human input.

This module polls the platform driver synchronously at action time. It never
starts a listener or background thread, so it cannot seize desktop control.
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass


DEFAULT_IDLE_SECONDS = 2.5
DEFAULT_STABLE_SAMPLES = 1
DEFAULT_POLL_INTERVAL_SECONDS = 0.25
DEFAULT_MAX_WAIT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class HumanInputCapture:
    """One call-scoped platform last-input observation."""

    tick: int


class HumanActivity:
    def __init__(
        self,
        driver,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        *,
        stable_samples: int = DEFAULT_STABLE_SAMPLES,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        max_wait_seconds: float = DEFAULT_MAX_WAIT_SECONDS,
    ) -> None:
        self.driver = driver
        self.idle_seconds = max(0.0, float(idle_seconds))
        if (
            isinstance(stable_samples, bool)
            or not isinstance(stable_samples, int)
            or stable_samples <= 0
        ):
            raise ValueError("stable_samples must be positive")
        for value, name in (
            (poll_interval_seconds, "poll_interval_seconds"),
            (max_wait_seconds, "max_wait_seconds"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and positive")
        self.stable_samples = stable_samples
        self.poll_interval_seconds = float(poll_interval_seconds)
        self.max_wait_seconds = float(max_wait_seconds)
        self._agent_input_tick: int | None = None

    def recent_input_age(self) -> float | None:
        """Return recent input age when the driver supports it, else None."""
        idle_seconds = getattr(self.driver, "last_input_idle_seconds", None)
        if not callable(idle_seconds):
            return None
        try:
            age = float(idle_seconds())
        except (TypeError, ValueError, OSError):
            return None
        return max(0.0, age)

    def capture(self) -> HumanInputCapture | None:
        """Capture the current platform input tick without retaining it."""

        input_tick = getattr(self.driver, "last_input_tick", None)
        if not callable(input_tick):
            return None
        try:
            return HumanInputCapture(int(input_tick()))
        except (TypeError, ValueError, OSError):
            return None

    def note_agent_action(self) -> None:
        """Record the input timestamp after known-successful native input.

        Windows counts injected SendKeys/keybd_event/mouse_event input in
        GetLastInputInfo. Remembering its tick avoids yielding to ourselves;
        callers must not invoke this for semantic UIA, activation, rejected,
        no-op, or failed actions. A later physical input changes the tick and
        is still detected.
        """
        captured = self.capture()
        self._agent_input_tick = None if captured is None else captured.tick

    def _blocking_reason(self, *, require_observation: bool) -> str | None:
        age = self.recent_input_age()
        if age is None:
            return (
                "human input idle state unavailable"
                if require_observation
                else None
            )
        if age >= self.idle_seconds:
            return None
        captured = self.capture()
        if captured is not None and captured.tick == self._agent_input_tick:
            return None
        return f"user input {age:.1f}s ago; wait {self.idle_seconds - age:.1f}s before retrying"

    def blocking_reason(self) -> str | None:
        """Return the legacy one-sample human-yield decision."""

        return self._blocking_reason(require_observation=False)

    def final_blocking_reason(
        self,
        readiness: HumanInputCapture | None,
        *,
        allowed_confirmation: HumanInputCapture | None = None,
    ) -> str | None:
        """Revalidate human-input authority once without waiting or retaining state."""

        before = self.capture()
        reason = self._blocking_reason(require_observation=True)
        after = self.capture()
        if readiness is None or before is None or after is None:
            return "human input idle state unavailable"
        if before != after:
            return "human input changed during final authority check"
        if reason == "human input idle state unavailable":
            return reason
        if allowed_confirmation is not None and after == allowed_confirmation:
            return None
        if after != readiness:
            return "human input changed after action readiness"
        return reason

    def wait_until_stable(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> str | None:
        """Gate one action call on a bounded consecutive idle streak.

        The action remains inside the same MCP call while this method samples.
        A timeout returns one known pre-dispatch rejection; the caller never
        needs to replay the action to finish a separately sampled handshake.
        """

        if self.stable_samples == 1:
            return self.blocking_reason()
        max_samples = max(
            1,
            math.floor(self.max_wait_seconds / self.poll_interval_seconds) + 1,
        )
        healthy_samples = 0
        last_reason: str | None = None
        for sample_index in range(max_samples):
            reason = self._blocking_reason(
                require_observation=self.stable_samples > 1,
            )
            if reason is None:
                healthy_samples += 1
                if healthy_samples >= self.stable_samples:
                    return None
            else:
                healthy_samples = 0
                last_reason = reason
                if reason == "human input idle state unavailable":
                    return reason
            if sample_index + 1 < max_samples:
                sleep(self.poll_interval_seconds)
        return last_reason or (
            "human input idle state did not remain stable for "
            f"{self.stable_samples} consecutive samples"
        )
