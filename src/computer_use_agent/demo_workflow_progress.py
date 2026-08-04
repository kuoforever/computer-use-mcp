"""Demo-only workflow HUD lifecycle for the bounded Chrome-to-Word Demo.

This connects the two halves that already exist separately: the pure
``project_demo_workflow`` mapper, which turns one fixed provider boundary into
the six Host-owned chapters, and :class:`PassiveProgressWindow`, which can
already draw a validated checklist. Nothing between them owned a UI thread, so
the checklist was unreachable during a real Demo.

The coordinator is deliberately narrow:

* It accepts exactly two inputs — the fixed provider boundary and the durable
  Runner phase. Provider prose, task text, tool-call budgets, approval counts,
  window ids, and typed content have no way in.
* It has no policy, approval, grounding, budget, or dispatch authority. A
  provider-step callback is a display notification, never execution evidence.
* Every native call happens on the worker thread it owns, so Win32 thread
  affinity holds. The Runner-thread entry points only mutate guarded state and
  set an event.
* It fails closed. An input that contradicts the fixed mapping is rejected and
  the last valid checklist stays on screen; a contradiction never invents a
  chapter transition, and no entry point raises into the Runner.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from .decision_card_window import WorkflowBreadcrumb
from .demo_cross_app import project_demo_workflow
from .progress_view import ProgressProjection
from .progress_window import PassiveProgressWindow
from .trace import RunPhase
from .workflow_checklist import WorkflowChecklist, WorkflowStatus

#: The last fixed provider boundary. Reaching it means the provider emitted its
#: final verified turn; it does not by itself mean the durable run succeeded.
DEMO_TERMINAL_PROVIDER_STEP = 18

#: The passive workflow HUD shows chapters, not run diagnostics, so it draws
#: against an empty run projection rather than scanning ``state_dir``.
_EMPTY_PROJECTION = ProgressProjection(
    views=(),
    unavailable_run_ids=(),
    unavailable_unnamed=0,
)

_PHASE_STATUS = {
    RunPhase.CREATED: WorkflowStatus.RUNNING,
    RunPhase.OBSERVING: WorkflowStatus.RUNNING,
    RunPhase.PLANNING: WorkflowStatus.RUNNING,
    RunPhase.WAITING_APPROVAL: WorkflowStatus.NEEDS_INPUT,
    RunPhase.PAUSED: WorkflowStatus.PAUSED,
    RunPhase.EXECUTING: WorkflowStatus.RUNNING,
    RunPhase.VERIFYING: WorkflowStatus.VERIFYING,
    RunPhase.SUCCESS: WorkflowStatus.READY,
    RunPhase.FAILED: WorkflowStatus.FAILED,
    RunPhase.UNKNOWN_OUTCOME: WorkflowStatus.UNCERTAIN,
    RunPhase.CANCELLED: WorkflowStatus.CANCELLED,
}

_TERMINAL_STATUSES = frozenset(
    {
        WorkflowStatus.READY,
        WorkflowStatus.FAILED,
        WorkflowStatus.UNCERTAIN,
        WorkflowStatus.CANCELLED,
    }
)


@dataclass
class DemoWorkflowProgress:
    """Project the bounded Demo onto one passive, non-activating checklist HUD.

    The public surface matches the passive progress lifecycle port the Runner
    already accepts (``on_phase``, ``wake``, ``estop``, ``release``), so this
    drops into ``RunnerPorts.progress`` without a second dispatch path.
    """

    window: PassiveProgressWindow
    pump: Callable[[], None]
    interval_seconds: float = 0.5
    join_timeout_seconds: float = 2.0
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
    _provider_step: int = field(default=0, init=False, repr=False)
    _status: WorkflowStatus = field(
        default=WorkflowStatus.RUNNING, init=False, repr=False
    )
    _checklist: WorkflowChecklist | None = field(default=None, init=False, repr=False)
    _drawn: WorkflowChecklist | None = field(default=None, init=False, repr=False)
    _suppressed: bool = field(default=False, init=False, repr=False)
    _failed: bool = field(default=False, init=False, repr=False)
    _error_count: int = field(default=0, init=False, repr=False)
    _rejected_count: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.window, PassiveProgressWindow):
            raise ValueError("window must be a PassiveProgressWindow")
        if not callable(self.pump):
            raise ValueError("pump must be callable")
        for name in ("interval_seconds", "join_timeout_seconds"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or value <= 0
            ):
                raise ValueError(f"{name} must be positive")
        self._checklist = project_demo_workflow(0, status=WorkflowStatus.RUNNING)

    @property
    def error_count(self) -> int:
        return self._error_count

    @property
    def rejected_count(self) -> int:
        """How many inputs contradicted the fixed mapping and were discarded."""

        return self._rejected_count

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def checklist(self) -> WorkflowChecklist | None:
        """The latest validated projection, for the Decision Card and tests."""

        with self._guard:
            return self._checklist

    # -- Runner-thread entry points ---------------------------------------
    # None of these touch Win32, open a window, or raise into the Runner.

    def on_provider_step(self, provider_step: int) -> None:
        """Advance the fixed chapter projection for one provider boundary."""

        if isinstance(provider_step, bool) or not isinstance(provider_step, int):
            # Checked here so a non-integer cannot reach the "unchanged"
            # sentinel in :meth:`_apply` and be silently treated as no news.
            self._reject()
            return
        # A display notification never starts the UI. Only the durable
        # lifecycle does, through on_phase or an explicit wake.
        self._apply(provider_step=provider_step, start=False)

    def on_proposal_rejected(self, attempt: int, max_attempts: int) -> None:
        """Show one bounded Host rejection while the model replans."""

        if (
            isinstance(attempt, bool)
            or not isinstance(attempt, int)
            or isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or not 1 <= attempt <= max_attempts <= 4
        ):
            self._reject()
            return
        with self._guard:
            checklist = self._checklist
            if (
                self._suppressed
                or self._failed
                or checklist is None
                or checklist.current_step_id is None
                or checklist.status in _TERMINAL_STATUSES
            ):
                self._reject_locked()
                return
            steps = tuple(
                replace(
                    step,
                    label="Replanning after Host blocked a proposal",
                    application=f"Safety guard · correction {attempt}/{max_attempts}",
                )
                if step.step_id == checklist.current_step_id
                else step
                for step in checklist.steps
            )
            self._checklist = replace(checklist, steps=steps)
            already_running = self._thread is not None
        if already_running:
            self.wake()

    def on_phase(self, phase: RunPhase) -> None:
        """Track the durable Runner phase; it owns overall workflow status."""

        if not isinstance(phase, RunPhase):
            self._reject()
            return
        self._apply(status=_PHASE_STATUS[phase])

    def wake(self) -> None:
        """Start or wake the worker that owns every native operation."""

        with self._guard:
            if self._suppressed or self._failed:
                return
            thread = self._thread
            if thread is None:
                thread = threading.Thread(
                    target=self._run,
                    name="guarded-demo-workflow-window",
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

    def breadcrumb(self) -> WorkflowBreadcrumb | None:
        """Derive the Decision Card breadcrumb from the current chapter only.

        This is read by the approval path, so an unavailable or terminal
        workflow returns ``None`` rather than raising: a display gap must never
        block an operator decision.
        """

        checklist = self.checklist
        if checklist is None or checklist.current_step_id is None:
            return None
        try:
            return WorkflowBreadcrumb.from_checklist(checklist)
        except Exception:
            self._reject()
            return None

    # -- Worker-thread operations -----------------------------------------

    def render_once(self) -> bool:
        """Draw the latest projection if it changed. Worker-owned; testable.

        Returns whether the window was actually repainted. An unchanged
        checklist is not redrawn, so a quiet workflow stays quiet.
        """

        with self._guard:
            checklist = self._checklist
            if checklist is None or checklist == self._drawn:
                return False
            self._drawn = checklist
        if self.window.hwnd is None:
            # First open shows every chapter; the operator may collapse it
            # afterwards and that choice survives later refreshes.
            self.window.open(_EMPTY_PROJECTION, workflow=checklist)
        else:
            self.window.update(_EMPTY_PROJECTION, workflow=checklist)
        return True

    # -- Internals ---------------------------------------------------------

    def _apply(
        self,
        *,
        provider_step: int | None = None,
        status: WorkflowStatus | None = None,
        start: bool = True,
    ) -> None:
        with self._guard:
            if self._suppressed or self._failed:
                return
            next_step = self._provider_step if provider_step is None else provider_step
            next_status = self._status if status is None else status
            if (
                isinstance(next_step, bool)
                or not isinstance(next_step, int)
                or not 0 <= next_step <= DEMO_TERMINAL_PROVIDER_STEP
                or next_step < self._provider_step
            ):
                # Chapters are monotonic. A boundary that moves backwards is a
                # contradiction, not a rewind, so nothing on screen changes.
                self._reject_locked()
                return
            if self._status in _TERMINAL_STATUSES and status is None:
                # A terminal workflow does not gain chapters afterwards.
                self._reject_locked()
                return
            checklist = self._project_locked(next_step, next_status)
            if checklist is None:
                return
            self._provider_step = next_step
            self._status = next_status
            self._checklist = checklist
            already_running = self._thread is not None
        if start or already_running:
            # Wake the UI-owning worker; it, not this thread, redraws.
            self.wake()

    def _project_locked(
        self, provider_step: int, status: WorkflowStatus
    ) -> WorkflowChecklist | None:
        effective = provider_step
        if (
            provider_step == DEMO_TERMINAL_PROVIDER_STEP
            and status is not WorkflowStatus.READY
            and status is not WorkflowStatus.CANCELLED
        ):
            # The provider finished its last turn but the durable run has not
            # said so yet. Hold the final chapter open instead of completing it,
            # and let a failure land on that chapter rather than on nothing.
            effective = DEMO_TERMINAL_PROVIDER_STEP - 1
        try:
            return project_demo_workflow(effective, status=status)
        except Exception:
            # Includes durable success claimed before the last provider
            # boundary: a contradiction the HUD must not smooth over.
            self._reject_locked()
            return None

    def _reject(self) -> None:
        with self._guard:
            self._reject_locked()

    def _reject_locked(self) -> None:
        self._rejected_count += 1

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                self.render_once()
                self.pump()
                self._wake.wait(self.interval_seconds)
                self._wake.clear()
        except Exception:
            self._record_failure()
        finally:
            try:
                self.window.close()
                self.pump()
            except Exception:
                self._record_failure()

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

    def _record_failure(self) -> None:
        with self._guard:
            self._failed = True
            self._error_count = 1
            self._stop.set()
            self._wake.set()


__all__ = [
    "DEMO_TERMINAL_PROVIDER_STEP",
    "DemoWorkflowProgress",
]
