from __future__ import annotations

import pytest

from computer_use_agent.demo_cross_app import DEMO_WORKFLOW
from computer_use_agent.workflow_checklist import (
    WorkflowChecklist,
    WorkflowChecklistError,
    WorkflowStatus,
    WorkflowStepStatus,
    WorkflowStepView,
)


def test_demo_workflow_has_six_fixed_human_readable_chapters() -> None:
    assert [step.step_id for step in DEMO_WORKFLOW.steps] == [
        "prepare_workspace",
        "review_public_source",
        "open_research_brief",
        "add_verified_note",
        "save_research_brief",
        "verify_saved_document",
    ]
    assert [step.application for step in DEMO_WORKFLOW.steps] == [
        "Demo setup",
        "Google Chrome",
        "Microsoft Word",
        "Microsoft Word",
        "Microsoft Word",
        "Microsoft Word",
    ]


def test_running_projection_separates_completed_current_and_future_steps() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    assert checklist.completed_count == 2
    assert checklist.skipped_count == 0
    assert checklist.not_started_count == 3
    assert checklist.current_step_number == 3
    assert [step.status for step in checklist.steps] == [
        WorkflowStepStatus.COMPLETED,
        WorkflowStepStatus.COMPLETED,
        WorkflowStepStatus.IN_PROGRESS,
        WorkflowStepStatus.NOT_STARTED,
        WorkflowStepStatus.NOT_STARTED,
        WorkflowStepStatus.NOT_STARTED,
    ]


@pytest.mark.parametrize(
    ("workflow_status", "step_status"),
    [
        (WorkflowStatus.NEEDS_INPUT, WorkflowStepStatus.WAITING_APPROVAL),
        (WorkflowStatus.PAUSED, WorkflowStepStatus.IN_PROGRESS),
        (WorkflowStatus.VERIFYING, WorkflowStepStatus.IN_PROGRESS),
        (WorkflowStatus.FAILED, WorkflowStepStatus.FAILED),
        (WorkflowStatus.UNCERTAIN, WorkflowStepStatus.UNCERTAIN),
    ],
)
def test_attention_states_preserve_the_exact_current_chapter(
    workflow_status: WorkflowStatus,
    step_status: WorkflowStepStatus,
) -> None:
    checklist = DEMO_WORKFLOW.project(
        workflow_status,
        completed_step_ids=("prepare_workspace",),
        current_step_id="review_public_source",
    )

    assert checklist.current_step_number == 2
    assert checklist.steps[1].status is step_status


def test_ready_projection_counts_skipped_separately_from_completed() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.READY,
        completed_step_ids=tuple(step.step_id for step in DEMO_WORKFLOW.steps[:-1]),
        skipped_step_ids=("verify_saved_document",),
    )

    assert checklist.completed_count == 5
    assert checklist.skipped_count == 1
    assert checklist.not_started_count == 0
    assert checklist.current_step_number is None


def test_cancelled_projection_keeps_unstarted_suffix_truthful() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.CANCELLED,
        completed_step_ids=("prepare_workspace",),
    )

    assert checklist.completed_count == 1
    assert checklist.not_started_count == 5
    assert checklist.current_step_id is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "status": WorkflowStatus.RUNNING,
            "completed_step_ids": ("review_public_source",),
            "current_step_id": "open_research_brief",
        },
        {
            "status": WorkflowStatus.RUNNING,
            "completed_step_ids": ("prepare_workspace", "prepare_workspace"),
            "current_step_id": "review_public_source",
        },
        {
            "status": WorkflowStatus.RUNNING,
            "completed_step_ids": ("unknown_step",),
            "current_step_id": "review_public_source",
        },
        {
            "status": WorkflowStatus.READY,
            "completed_step_ids": ("prepare_workspace",),
        },
        {
            "status": WorkflowStatus.NEEDS_INPUT,
            "completed_step_ids": ("prepare_workspace",),
        },
    ],
)
def test_projection_rejects_untrusted_or_contradictory_state(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(WorkflowChecklistError):
        DEMO_WORKFLOW.project(**kwargs)  # type: ignore[arg-type]


def test_direct_snapshot_rejects_status_that_disagrees_with_current_row() -> None:
    with pytest.raises(
        WorkflowChecklistError,
        match="current workflow step does not match status",
    ):
        WorkflowChecklist(
            workflow_id="demo",
            title="Demo workflow",
            status=WorkflowStatus.NEEDS_INPUT,
            current_step_id="first",
            steps=(
                WorkflowStepView(
                    "first",
                    "First step",
                    "Demo app",
                    WorkflowStepStatus.IN_PROGRESS,
                ),
            ),
        )
