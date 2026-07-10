"""Serial yielding for shared-desktop human input.

This module polls the platform driver synchronously at action time. It never
starts a listener or background thread, so it cannot seize desktop control.
"""
from __future__ import annotations


DEFAULT_IDLE_SECONDS = 2.5


class HumanActivity:
    def __init__(self, driver, idle_seconds: float = DEFAULT_IDLE_SECONDS) -> None:
        self.driver = driver
        self.idle_seconds = max(0.0, float(idle_seconds))
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

    def note_agent_action(self) -> None:
        """Record the input timestamp after an action we just attempted.

        Windows counts injected SendKeys/keybd_event/mouse_event input in
        GetLastInputInfo. Remembering its tick avoids yielding to ourselves;
        a later physical input changes the tick and is still detected.
        """
        input_tick = getattr(self.driver, "last_input_tick", None)
        if not callable(input_tick):
            return
        try:
            self._agent_input_tick = int(input_tick())
        except (TypeError, ValueError, OSError):
            self._agent_input_tick = None

    def blocking_reason(self) -> str | None:
        age = self.recent_input_age()
        if age is None or age >= self.idle_seconds:
            return None
        input_tick = getattr(self.driver, "last_input_tick", None)
        if callable(input_tick):
            try:
                if int(input_tick()) == self._agent_input_tick:
                    return None
            except (TypeError, ValueError, OSError):
                pass
        return f"user input {age:.1f}s ago; wait {self.idle_seconds - age:.1f}s before retrying"
