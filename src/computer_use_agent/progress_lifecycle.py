"""Fail-silent background lifecycle for the passive progress window."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from .progress_poller import ProgressPoller
from .trace import RunPhase


@dataclass
class RunProgressCoordinator:
    """Poll checkpoints on one UI-owning thread without affecting the run.

    Durable phase notifications only wake the worker; they never scan state or
    call Win32 on the Runner thread. The worker owns every open, repaint,
    message-pump, and close operation so native thread affinity is preserved.
    """

    poller: ProgressPoller
    pump: Callable[[], None]
    join_timeout_seconds: float = 2.0
    _wake: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _guard: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _suppressed: bool = field(default=False, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)
    _error_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.poller, ProgressPoller):
            raise ValueError("poller must be a ProgressPoller")
        if not callable(self.pump):
            raise ValueError("pump must be callable")
        if (
            isinstance(self.join_timeout_seconds, bool)
            or not isinstance(self.join_timeout_seconds, (int, float))
            or self.join_timeout_seconds <= 0
        ):
            raise ValueError("join_timeout_seconds must be positive")

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def on_phase(self, phase: RunPhase) -> None:
        """Start or wake the passive worker after a durable phase checkpoint."""

        if not isinstance(phase, RunPhase):
            self._fail_before_start()
            return
        self.wake()

    def wake(self) -> None:
        """Start or wake the worker for validated non-run state such as campaigns."""

        with self._guard:
            if self._suppressed or self._failed:
                return
            thread = self._thread
            if thread is None:
                thread = threading.Thread(
                    target=self._run,
                    name="guarded-progress-window",
                    daemon=True,
                )
                self._thread = thread
                try:
                    thread.start()
                except Exception:
                    self._thread = None
                    self._failed = True
                    self._error_count = 1
                    return
            self._wake.set()

    def estop(self) -> None:
        self._release()

    def release(self) -> None:
        self._release()

    def _release(self) -> None:
        with self._guard:
            if self._suppressed:
                return
            self._suppressed = True
            thread = self._thread
            self._stop.set()
            self._wake.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=float(self.join_timeout_seconds))
            if thread.is_alive():
                self._record_failure()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.poller.poll_once()
                self.pump()
                self._wake.wait(self.poller.interval_seconds)
                self._wake.clear()
        except Exception:
            self._record_failure()
        finally:
            try:
                self.poller.window.close()
                self.pump()
            except Exception:
                self._record_failure()

    def _fail_before_start(self) -> None:
        with self._guard:
            if self._suppressed or self._failed:
                return
            self._failed = True
            self._error_count = 1

    def _record_failure(self) -> None:
        with self._guard:
            self._failed = True
            self._error_count = 1
            self._stop.set()
            self._wake.set()


__all__ = ["RunProgressCoordinator"]
