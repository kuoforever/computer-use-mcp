from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from computer_use_agent.disposable_process import DisposableCleanup
from computer_use_agent.product_receipt import (
    product_receipt_path,
    write_public_web_word_receipt,
)
from computer_use_agent.progress_view import (
    CallBudget,
    CampaignProgressView,
    ProgressProjection,
    RunProgressView,
)
from computer_use_agent.task_center import (
    build_task_center,
    project_task_center,
    render_task_center,
)


DIGEST = "b" * 64
FORBIDDEN = "TASK_CENTER_RAW_TASK_SECRET"


def _run(run_id: str, phase: str, *, at: int, **over: object) -> RunProgressView:
    terminal = phase in {"SUCCESS", "FAILED", "UNKNOWN_OUTCOME", "CANCELLED"}
    base: dict[str, object] = {
        "run_id": run_id,
        "phase": phase,
        "display_state": {
            "SUCCESS": "Ready",
            "FAILED": "Failed",
            "UNKNOWN_OUTCOME": "Needs inspection; re-observe before retry",
        }.get(phase, "In progress at last checkpoint; liveness unknown"),
        "is_terminal": terminal,
        "liveness_known": terminal,
        "needs_reobserve": phase == "UNKNOWN_OUTCOME",
        "model_calls": CallBudget(1, 3),
        "tool_calls": CallBudget(2, 4),
        "input_tokens": 11,
        "output_tokens": 5,
        "token_coverage_known": True,
        "image_results": 0,
        "screenshot_results": 0,
        "screenshot_count_known": True,
        "tool_failures": 0,
        "elapsed_known": terminal,
        "duration_ms": 20 if terminal else None,
        "failure_code": "POLICY_DENIED" if phase == "FAILED" else None,
        "updated_at_us": at,
    }
    base.update(over)
    return RunProgressView(**base)  # type: ignore[arg-type]


def _campaign(campaign_id: str, status: str, *, at: int) -> CampaignProgressView:
    return CampaignProgressView(
        campaign_id=campaign_id,
        status=status,
        display_state="Ready" if status == "COMPLETED" else "In progress",
        is_terminal=status in {"COMPLETED", "FAILED", "CANCELLED"},
        needs_attention=status not in {"RUNNING", "COMPLETED"},
        discovered_count=3,
        completed_count=3 if status == "COMPLETED" else 1,
        retryable_count=0,
        uncertain_count=0,
        updated_at_us=at,
    )


def _progress(*runs: RunProgressView, campaigns=()) -> ProgressProjection:
    return ProgressProjection(
        views=tuple(runs),
        unavailable_run_ids=(),
        unavailable_unnamed=0,
        campaigns=tuple(campaigns),
    )


def _verified_result(tmp_path: Path) -> SimpleNamespace:
    cleanup = DisposableCleanup("word", 1, "graceful", 0, 1, True, False)
    return SimpleNamespace(
        run_id="workflow_1",
        artifact=(tmp_path / "brief.docx").resolve(),
        artifact_sha256=DIGEST,
        post_save_verified=True,
        reopen_verified=True,
        fixture_cleanup=(cleanup,),
        verifier_cleanup=(cleanup,),
    )


def test_center_groups_attention_before_active_and_history(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    center = project_task_center(
        state_dir,
        _progress(
            _run("done", "SUCCESS", at=30),
            _run("active", "PLANNING", at=40),
            _run("failed", "FAILED", at=25),
            _run("uncertain", "UNKNOWN_OUTCOME", at=20),
            campaigns=(_campaign("campaign_done", "COMPLETED", at=10),),
        ),
    )

    assert [group.key for group in center.groups] == [
        "attention",
        "in_progress",
        "history",
    ]
    assert [item.task_id for item in center.groups[0].items] == [
        "failed",
        "uncertain",
    ]
    assert center.groups[0].items[0].receipt.kind == "failure"
    assert center.groups[0].items[1].receipt.kind == "uncertain"
    assert center.groups[1].items[0].task_id == "active"
    assert {item.task_id for item in center.groups[2].items} == {
        "done",
        "campaign_done",
    }


def test_unknown_outcome_has_no_retry_affordance_or_raw_content(tmp_path: Path) -> None:
    center = project_task_center(
        tmp_path.resolve(),
        _progress(_run("uncertain", "UNKNOWN_OUTCOME", at=1)),
    )
    payload = center.as_json()
    rendered = json.dumps(payload)
    text = render_task_center(center)

    assert payload["read_only"] is True
    assert all(value is False for value in payload["capabilities"].values())
    assert "do not retry automatically" in rendered
    assert "cannot approve, resume, retry, cancel, or advance" in text
    assert FORBIDDEN not in rendered + text


def test_verified_workflow_receipt_supplies_only_artifact_facts(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    receipt_path = product_receipt_path(state_dir, "workflow_1")
    receipt_path.parent.mkdir(parents=True)
    write_public_web_word_receipt(state_dir, _verified_result(tmp_path))
    center = project_task_center(
        state_dir,
        _progress(_run("workflow_1", "SUCCESS", at=1)),
    )
    item = center.groups[0].items[0]

    assert center.groups[0].key == "history"
    assert item.receipt.headline == "Document saved and verified"
    assert item.receipt.artifact_path == str((tmp_path / "brief.docx").resolve())
    assert item.receipt.artifact_sha256 == DIGEST
    assert item.receipt.artifact_verification == "VERIFIED_AT_COMPLETION"
    assert item.receipt.cleanup_verification == "VERIFIED"


def test_missing_or_corrupt_workflow_receipt_never_claims_completion(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    path = product_receipt_path(state_dir, "workflow_1")
    path.parent.mkdir(parents=True)
    run = _run("workflow_1", "SUCCESS", at=1)

    missing = project_task_center(state_dir, _progress(run))
    assert missing.groups[0].key == "attention"
    assert missing.groups[0].items[0].receipt.kind == "needs_inspection"
    assert "not claimed" in missing.groups[0].items[0].receipt.detail

    path.write_text("{not json", encoding="utf-8")
    corrupt = project_task_center(state_dir, _progress(run))
    assert corrupt.groups[0].key == "attention"
    assert "not trusted" in corrupt.groups[0].items[0].receipt.detail


def test_limit_allocates_attention_first_and_reports_total(tmp_path: Path) -> None:
    progress = _progress(
        _run("history", "SUCCESS", at=30),
        _run("active", "PLANNING", at=20),
        _run("attention", "UNKNOWN_OUTCOME", at=10),
    )
    center = project_task_center(tmp_path.resolve(), progress, limit=1)

    assert center.total_items == 3
    assert center.displayed_items == 1
    assert center.groups[0].key == "attention"
    assert center.groups[0].items[0].task_id == "attention"


def test_cancelled_campaign_is_history_with_fixed_receipt(tmp_path: Path) -> None:
    center = project_task_center(
        tmp_path.resolve(),
        _progress(campaigns=(_campaign("stopped", "CANCELLED", at=1),)),
    )

    assert center.groups[0].key == "history"
    assert center.groups[0].items[0].receipt.kind == "cancelled"
    assert center.groups[0].items[0].receipt.headline == "Campaign cancelled"


def test_empty_center_is_read_only_and_does_not_create_state(tmp_path: Path) -> None:
    state_dir = (tmp_path / "missing").resolve()

    center = build_task_center(state_dir)

    assert center.total_items == 0
    assert not state_dir.exists()
    assert "No validated local tasks found" in render_task_center(center)


def test_product_receipt_validation_failure_does_not_contaminate_other_runs(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path.resolve()
    bad_path = product_receipt_path(state_dir, "bad")
    bad_path.parent.mkdir(parents=True)
    bad_path.write_text("{}", encoding="utf-8")
    center = project_task_center(
        state_dir,
        _progress(_run("good", "SUCCESS", at=2), _run("bad", "SUCCESS", at=1)),
    )

    items = {item.task_id: item for group in center.groups for item in group.items}
    assert items["good"].receipt.kind == "completion"
    assert items["bad"].receipt.kind == "needs_inspection"


def test_replacing_run_metrics_cannot_add_raw_text_to_receipt(tmp_path: Path) -> None:
    run = _run("done", "SUCCESS", at=1)
    altered = replace(run, failure_code=None)
    center = project_task_center(tmp_path.resolve(), _progress(altered))

    assert FORBIDDEN not in json.dumps(center.as_json())
