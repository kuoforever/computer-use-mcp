"""Fail-silent Host ownership of the passive desktop presence surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .presence import (
    DesktopAuthority,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
)
from .trace import RunPhase


@runtime_checkable
class PresenceLifecyclePort(Protocol):
    """Non-authoritative lifecycle notifications accepted by AgentRunner."""

    def on_phase(self, phase: RunPhase) -> None: ...

    def estop(self) -> None: ...

    def release(self) -> None: ...


class FailSilentLifecycle:
    """Latch a failed passive lifecycle surface outside Agent authority."""

    __slots__ = ("_port", "_suppressed")

    def __init__(self, port: PresenceLifecyclePort | None) -> None:
        self._port = port
        self._suppressed = False

    def on_phase(self, phase: RunPhase) -> None:
        if self._port is None or self._suppressed:
            return
        try:
            self._port.on_phase(phase)
        except Exception:
            self._suppressed = True

    def estop(self) -> None:
        self._suppress("estop")

    def release(self) -> None:
        self._suppress("release")

    def _suppress(self, method: str) -> None:
        if self._suppressed:
            return
        self._suppressed = True
        if self._port is None:
            return
        try:
            getattr(self._port, method)()
        except Exception:
            pass


class PresenceSurface(Protocol):
    def sync(self, snapshot: PresenceSnapshot) -> object: ...

    def close(self) -> None: ...


_ACTIVE_PHASES: dict[RunPhase, tuple[PresencePhase, DesktopAuthority]] = {
    RunPhase.OBSERVING: (PresencePhase.OBSERVING, DesktopAuthority.HELD),
    RunPhase.PLANNING: (PresencePhase.PLANNING, DesktopAuthority.HELD),
    RunPhase.WAITING_APPROVAL: (
        PresencePhase.WAITING_APPROVAL,
        DesktopAuthority.WAITING,
    ),
    RunPhase.EXECUTING: (PresencePhase.EXECUTING, DesktopAuthority.HELD),
    RunPhase.VERIFYING: (PresencePhase.VERIFYING, DesktopAuthority.HELD),
}
_TERMINAL_PHASES = frozenset(
    {
        RunPhase.SUCCESS,
        RunPhase.FAILED,
        RunPhase.UNKNOWN_OUTCOME,
        RunPhase.CANCELLED,
    }
)


@dataclass
class RunPresenceCoordinator:
    """Project durable run phases to one passive surface without run content."""

    surface: PresenceSurface
    preferences: PresencePreferences = PresencePreferences()
    _suppressed: bool = field(default=False, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)
    _error_count: int = field(default=0, init=False)

    @property
    def error_count(self) -> int:
        return self._error_count

    def on_phase(self, phase: RunPhase) -> None:
        if self._suppressed or self._failed:
            return
        if not isinstance(phase, RunPhase):
            self._fail_closed()
            return
        if phase is RunPhase.CREATED:
            self._close()
            return
        if phase is RunPhase.PAUSED:
            self._suppressed = True
            self._close()
            return
        if phase in _TERMINAL_PHASES:
            self._suppressed = True
            self._close()
            return
        projected = _ACTIVE_PHASES.get(phase)
        if projected is None:
            self._fail_closed()
            return
        presence_phase, authority = projected
        try:
            self.surface.sync(
                PresenceSnapshot(
                    phase=presence_phase,
                    authority=authority,
                    preferences=self.preferences,
                )
            )
        except Exception:
            self._fail_closed()

    def estop(self) -> None:
        if self._failed:
            return
        self._suppressed = True
        self._close()

    def release(self) -> None:
        if self._failed:
            return
        self._suppressed = True
        self._close()

    def _close(self) -> None:
        try:
            self.surface.close()
        except Exception:
            self._error_count = min(self._error_count + 1, 1)
            self._failed = True

    def _fail_closed(self) -> None:
        self._error_count = min(self._error_count + 1, 1)
        self._failed = True
        try:
            self.surface.close()
        except Exception:
            pass


__all__ = [
    "FailSilentLifecycle",
    "PresenceLifecyclePort",
    "RunPresenceCoordinator",
]
