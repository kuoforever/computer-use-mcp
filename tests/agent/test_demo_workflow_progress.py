"""Deterministic tests for the Demo-only workflow HUD lifecycle.

These prove the properties `GDA-HUD-005` and `GDA-HUD-006` require *before* any
live run: the Runner thread never touches the native window, chapters only move
forward, the Decision Card breadcrumb comes from the validated checklist rather
than provider prose, an operator's collapse survives refreshes, and a state that
contradicts the fixed mapping is discarded instead of rendered.

Nothing here promotes desktop, application, or release evidence.
"""
from __future__ import annotations

import threading
import time

import pytest

from computer_use_agent.decision_card_window import WorkflowBreadcrumb
from computer_use_agent.demo_workflow_progress import (
    DEMO_TERMINAL_PROVIDER_STEP,
    DemoWorkflowProgress,
)
from computer_use_agent.fakes import FakeProgressWindowApi
from computer_use_agent.progress_window import PassiveProgressWindow
from computer_use_agent.trace import RunPhase
from computer_use_agent.workflow_checklist import (
    WorkflowStatus,
    WorkflowStepStatus,
)


def _coordinator(
    api: FakeProgressWindowApi | None = None,
) -> tuple[DemoWorkflowProgress, FakeProgressWindowApi]:
    resolved = api or FakeProgressWindowApi()
    coordinator = DemoWorkflowProgress(
        PassiveProgressWindow(resolved),
        pump=lambda: None,
        interval_seconds=0.01,
        join_timeout_seconds=1.0,
    )
    return coordinator, resolved


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _current(coordinator: DemoWorkflowProgress) -> tuple[str | None, WorkflowStatus]:
    checklist = coordinator.checklist
    assert checklist is not None
    return checklist.current_step_id, checklist.status


class _ThreadRecordingApi(FakeProgressWindowApi):
    """Record which thread made each native call.

    Asserting that no call happened at all was wrong: a durable phase starts
    the worker, so the check raced it and passed only when the worker had not
    scheduled yet. The property that actually matters is *which thread* calls
    Win32, and that is what this records.
    """

    def __init__(self) -> None:
        super().__init__()
        self.call_threads: list[int] = []

    def _record(self) -> None:
        self.call_threads.append(threading.get_ident())

    def create(self, **kwargs: object) -> int:
        self._record()
        return super().create(**kwargs)  # type: ignore[arg-type]

    def set_lines(self, hwnd: int, lines: object) -> None:
        self._record()
        super().set_lines(hwnd, lines)  # type: ignore[arg-type]

    def set_workflow_lines(self, hwnd: int, **kwargs: object) -> None:
        self._record()
        super().set_workflow_lines(hwnd, **kwargs)  # type: ignore[arg-type]

    def show_noactivate(self, hwnd: int) -> None:
        self._record()
        super().show_noactivate(hwnd)

    def reposition_noactivate(self, hwnd: int, **kwargs: object) -> None:
        self._record()
        super().reposition_noactivate(hwnd, **kwargs)  # type: ignore[arg-type]

    def destroy(self, hwnd: int) -> None:
        self._record()
        super().destroy(hwnd)


def test_runner_thread_notifications_never_touch_the_native_window() -> None:
    """The Runner thread may only mutate state; the worker owns every Win32 call."""

    api = _ThreadRecordingApi()
    coordinator = DemoWorkflowProgress(
        PassiveProgressWindow(api),
        pump=lambda: None,
        interval_seconds=0.01,
        join_timeout_seconds=1.0,
    )
    runner_thread = threading.get_ident()

    for step in range(0, 16):
        coordinator.on_provider_step(step)
    # A provider boundary is a display notification and must not start the UI.
    assert api.call_threads == []
    assert coordinator.window.hwnd is None

    coordinator.on_phase(RunPhase.OBSERVING)
    coordinator.on_phase(RunPhase.WAITING_APPROVAL)
    assert _wait_until(lambda: coordinator.window.hwnd is not None)

    coordinator.release()
    assert api.call_threads, "the worker never drew, so the check is vacuous"
    assert runner_thread not in api.call_threads
    assert api.kinds()[:3] == ["create", "set_workflow_lines", "show_noactivate"]


def test_first_open_shows_every_chapter_and_operator_collapse_survives() -> None:
    coordinator, api = _coordinator()
    coordinator.on_provider_step(6)
    coordinator.render_once()
    hwnd = coordinator.window.hwnd
    assert hwnd is not None

    compact, expanded = api.workflow_lines[hwnd]
    assert api.lines[hwnd] == expanded, "first open must show all steps"
    assert "WORKFLOW CHECKLIST" in expanded
    assert "WORKFLOW CHECKLIST" not in compact

    api.click_workflow_toggle(hwnd)
    assert coordinator.window.expanded is False

    coordinator.on_provider_step(9)
    assert coordinator.render_once() is True
    assert api.lines[hwnd] == api.workflow_lines[hwnd][0]
    assert coordinator.window.expanded is False, "operator collapse must survive"
    coordinator.release()


def test_chapters_only_move_forward() -> None:
    coordinator, _ = _coordinator()
    coordinator.on_provider_step(9)
    assert _current(coordinator)[0] == "add_verified_note"

    coordinator.on_provider_step(2)
    assert _current(coordinator)[0] == "add_verified_note"
    assert coordinator.rejected_count == 1

    coordinator.on_provider_step(15)
    assert _current(coordinator)[0] == "save_research_brief"
    assert coordinator.rejected_count == 1


def test_known_host_rejection_is_visible_only_while_agent_replans() -> None:
    coordinator, _ = _coordinator()
    coordinator.on_provider_step(9)

    coordinator.on_proposal_rejected(1, 2)

    checklist = coordinator.checklist
    assert checklist is not None
    current = next(
        step for step in checklist.steps if step.step_id == checklist.current_step_id
    )
    assert current.label == "Replanning after Host blocked a proposal"
    assert current.application == "Safety guard · correction 1/2"

    coordinator.on_phase(RunPhase.EXECUTING)
    checklist = coordinator.checklist
    assert checklist is not None
    current = next(
        step for step in checklist.steps if step.step_id == checklist.current_step_id
    )
    assert current.label == "Add the verified source note"
    assert current.application == "Microsoft Word"


def test_approval_wait_and_terminal_success_use_distinct_statuses() -> None:
    coordinator, _ = _coordinator()
    coordinator.on_provider_step(4)
    coordinator.on_phase(RunPhase.WAITING_APPROVAL)

    checklist = coordinator.checklist
    assert checklist is not None
    assert checklist.status is WorkflowStatus.NEEDS_INPUT
    current = next(
        step for step in checklist.steps if step.step_id == checklist.current_step_id
    )
    assert current.status is WorkflowStepStatus.WAITING_APPROVAL

    coordinator.on_phase(RunPhase.EXECUTING)
    assert _current(coordinator)[1] is WorkflowStatus.RUNNING

    coordinator.on_provider_step(DEMO_TERMINAL_PROVIDER_STEP)
    coordinator.on_phase(RunPhase.VERIFYING)
    checklist = coordinator.checklist
    assert checklist is not None
    assert checklist.status is WorkflowStatus.VERIFYING
    assert checklist.current_step_id == "verify_saved_document", (
        "the last chapter stays open until the durable run says otherwise"
    )

    coordinator.on_phase(RunPhase.SUCCESS)
    checklist = coordinator.checklist
    assert checklist is not None
    assert checklist.status is WorkflowStatus.READY
    assert checklist.current_step_id is None
    assert all(
        step.status is WorkflowStepStatus.COMPLETED for step in checklist.steps
    )
    coordinator.release()


def test_failure_and_cancellation_never_complete_the_current_chapter() -> None:
    for phase, status in (
        (RunPhase.FAILED, WorkflowStatus.FAILED),
        (RunPhase.UNKNOWN_OUTCOME, WorkflowStatus.UNCERTAIN),
    ):
        coordinator, _ = _coordinator()
        coordinator.on_provider_step(DEMO_TERMINAL_PROVIDER_STEP)
        coordinator.on_phase(phase)
        checklist = coordinator.checklist
        assert checklist is not None
        assert checklist.status is status
        assert checklist.current_step_id == "verify_saved_document"
        assert checklist.completed_count == 5
        coordinator.release()

    coordinator, _ = _coordinator()
    coordinator.on_provider_step(9)
    coordinator.on_phase(RunPhase.CANCELLED)
    checklist = coordinator.checklist
    assert checklist is not None
    assert checklist.status is WorkflowStatus.CANCELLED
    assert checklist.current_step_id is None
    assert checklist.completed_count == 3
    assert checklist.not_started_count == 3
    coordinator.release()


def test_contradictory_state_is_discarded_instead_of_rendered() -> None:
    coordinator, api = _coordinator()
    coordinator.on_provider_step(9)
    coordinator.render_once()
    hwnd = coordinator.window.hwnd
    assert hwnd is not None
    drawn = api.lines[hwnd]

    # Durable success cannot precede the last provider boundary.
    coordinator.on_phase(RunPhase.SUCCESS)
    assert _current(coordinator) == ("add_verified_note", WorkflowStatus.RUNNING)

    for invalid in (-1, 19, True, "9", None):
        coordinator.on_provider_step(invalid)  # type: ignore[arg-type]
    coordinator.on_phase("EXECUTING")  # type: ignore[arg-type]

    assert coordinator.rejected_count == 7
    assert coordinator.render_once() is False
    assert api.lines[hwnd] == drawn
    coordinator.release()


def test_breadcrumb_tracks_the_validated_current_chapter_only() -> None:
    coordinator, _ = _coordinator()
    coordinator.on_provider_step(6)

    breadcrumb = coordinator.breadcrumb()
    assert breadcrumb == WorkflowBreadcrumb(
        current=3,
        total=6,
        label="Open the research brief",
    )

    coordinator.on_provider_step(DEMO_TERMINAL_PROVIDER_STEP)
    coordinator.on_phase(RunPhase.SUCCESS)
    assert coordinator.breadcrumb() is None, "a resolved workflow has no current step"
    coordinator.release()


def test_worker_thread_owns_open_repaint_and_close() -> None:
    api = FakeProgressWindowApi()
    pumped: list[int] = []
    coordinator = DemoWorkflowProgress(
        PassiveProgressWindow(api),
        pump=lambda: pumped.append(threading.get_ident()),
        interval_seconds=0.01,
        join_timeout_seconds=1.0,
    )
    main_thread = threading.get_ident()

    coordinator.on_phase(RunPhase.OBSERVING)
    assert _wait_until(lambda: coordinator.window.hwnd is not None)
    hwnd = coordinator.window.hwnd
    assert hwnd is not None
    assert coordinator.running is True

    coordinator.on_provider_step(9)
    assert _wait_until(
        lambda: "Add the verified source note" in "".join(api.lines[hwnd])
    )

    coordinator.release()
    assert _wait_until(lambda: coordinator.running is False)
    assert hwnd not in api.alive
    assert pumped and main_thread not in pumped, "no pump ran on the Runner thread"
    assert coordinator.error_count == 0


def test_construction_rejects_an_unusable_surface() -> None:
    api = FakeProgressWindowApi()
    with pytest.raises(ValueError, match="window must be"):
        DemoWorkflowProgress(api, pump=lambda: None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="pump must be callable"):
        DemoWorkflowProgress(PassiveProgressWindow(api), pump=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        DemoWorkflowProgress(
            PassiveProgressWindow(api), pump=lambda: None, interval_seconds=0
        )
