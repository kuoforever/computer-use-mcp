"""Fail-silent Host ownership of the passive desktop presence surface."""

from __future__ import annotations

import threading
from collections.abc import Callable
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

    def yield_authority(self) -> None:
        """Relinquish desktop authority to the operator, reversibly.

        Optional. A surface that does not implement it is released instead,
        because giving the desktop back is the property that matters and a
        closed surface has certainly given it back.
        """


@runtime_checkable
class ProgressLifecyclePort(PresenceLifecyclePort, Protocol):
    """Passive progress lifecycle that may start without a run phase."""

    def wake(self) -> None: ...


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

    def wake(self) -> None:
        if self._port is None or self._suppressed:
            return
        method = getattr(self._port, "wake", None)
        if not callable(method):
            self._suppressed = True
            return
        try:
            method()
        except Exception:
            self._suppressed = True

    def release(self) -> None:
        self._suppress("release")

    def yield_authority(self) -> None:
        """Yield the desktop without ending the surface.

        This exists because ``release`` was being used to express a transient
        yield before a focus-taking approval. ``release`` latches, so the halo
        was torn down at the first approval and never returned for the rest of
        the run -- the operator saw no halo at all during a complete Demo.
        """

        if self._port is None or self._suppressed:
            return
        method = getattr(self._port, "yield_authority", None)
        if not callable(method):
            # Unknown surface: fall back to the previous behaviour. Yielding is
            # the safety property, and a closed surface has certainly yielded.
            self._suppress("release")
            return
        try:
            method()
        except Exception:
            self._suppressed = True

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
    #: Message pump for the thread that owns the native halo. A Win32 window
    #: that is never pumped never receives ``WM_PAINT``, so it exists, is
    #: visible, and draws nothing -- which for a colour-keyed layered window
    #: means fully transparent. That is why no operator ever saw the halo
    #: during a complete Demo: the Runner projected every phase correctly and
    #: nothing ever painted them. When a pump is supplied this coordinator owns
    #: a worker thread and every native call happens there, preserving Win32
    #: thread affinity. When it is omitted the caller must pump; only tests and
    #: smokes that drive the surface themselves should do that.
    pump: Callable[[], None] | None = None
    interval_seconds: float = 0.1
    join_timeout_seconds: float = 2.0
    _suppressed: bool = field(default=False, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)
    _error_count: int = field(default=0, init=False)
    _guard: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False
    )
    _wake: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _stop: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _pending: PresenceSnapshot | None = field(default=None, init=False, repr=False)
    _pending_close: bool = field(default=False, init=False, repr=False)

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
        snapshot = PresenceSnapshot(
            phase=presence_phase,
            authority=authority,
            preferences=self.preferences,
        )
        if self.pump is not None:
            self._enqueue(snapshot)
            return
        try:
            self.surface.sync(snapshot)
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

    def yield_authority(self) -> None:
        """Show the operator that the desktop is theirs, and stay up.

        The projection this needs already existed: `RunPhase.WAITING_APPROVAL`
        maps to `PresencePhase.WAITING_APPROVAL` with
        `DesktopAuthority.WAITING`. Nothing here ends the surface, so the halo
        returns to the run's phase as soon as the next one is recorded.
        """

        self.on_phase(RunPhase.WAITING_APPROVAL)

    def _enqueue(self, snapshot: PresenceSnapshot) -> None:
        """Hand one projection to the UI-owning worker and start it if needed."""

        with self._guard:
            if self._suppressed or self._failed:
                return
            self._pending = snapshot
            # A projection supersedes a pending close of a stale surface.
            self._pending_close = False
            thread = self._thread
            if thread is None:
                thread = threading.Thread(
                    target=self._run,
                    name="guarded-presence-window",
                    daemon=True,
                )
                self._thread = thread
                try:
                    thread.start()
                except Exception:
                    self._thread = None
                    self._fail_closed_locked()
                    return
            self._wake.set()

    def _run(self) -> None:
        pump = self.pump
        assert pump is not None
        try:
            while not self._stop.is_set():
                with self._guard:
                    snapshot = self._pending
                    close_requested = self._pending_close
                    self._pending = None
                    self._pending_close = False
                if close_requested:
                    self.surface.close()
                if snapshot is not None:
                    self.surface.sync(snapshot)
                pump()
                self._wake.wait(self.interval_seconds)
                self._wake.clear()
        except Exception:
            self._fail_closed()
        finally:
            try:
                self.surface.close()
                pump()
            except Exception:
                self._fail_closed()

    def _stop_worker(self) -> None:
        with self._guard:
            thread = self._thread
            self._stop.set()
            self._wake.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=float(self.join_timeout_seconds))

    def _close(self) -> None:
        if self.pump is None:
            try:
                self.surface.close()
            except Exception:
                self._error_count = min(self._error_count + 1, 1)
                self._failed = True
            return
        # The worker owns every native call, including the close. Closing the
        # window is not the same as ending the lifecycle: RunPhase.CREATED
        # closes a stale surface at the start of every run, and stopping the
        # worker there would mean the halo is never created at all.
        with self._guard:
            terminal = self._suppressed or self._failed
            running = self._thread is not None
            if not terminal:
                if not running:
                    # Nothing was ever created, so there is nothing to close.
                    return
                self._pending_close = True
                self._wake.set()
                return
        if running:
            self._stop_worker()

    def _fail_closed(self) -> None:
        self._fail_closed_locked()
        try:
            self.surface.close()
        except Exception:
            pass

    def _fail_closed_locked(self) -> None:
        self._error_count = min(self._error_count + 1, 1)
        self._failed = True


__all__ = [
    "FailSilentLifecycle",
    "PresenceLifecyclePort",
    "ProgressLifecyclePort",
    "RunPresenceCoordinator",
]
