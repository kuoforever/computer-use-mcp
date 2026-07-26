from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.progress_view import (
    campaign_status_to_view,
    group_campaign_views,
    ProgressViewError,
    build_progress_projection,
    checkpoint_to_view,
    group_progress_views,
)
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
)
from computer_use_agent.campaign_host_status import CampaignHostStatus, HostTaskStatus
from computer_use_agent.run_lock import RunLock
from computer_use_agent.trace import RunPhase, RunRecorder
from computer_use_agent.types import (
    LedgerEvent,
    LedgerEventKind,
    ModelUsage,
    RunBudget,
    RunState,
)

FORBIDDEN = "PROGRESS_TASK_SECRET"
CAMPAIGN_SECRET = "progress_task_secret"
DIGEST = "a" * 64
NOW = datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc)


def _state(run_id: str) -> RunState:
    return RunState(
        run_id=run_id,
        task=FORBIDDEN,
        policy_version="progress-v1",
        observation_epoch=0,
        budgets=RunBudget(3, 4, 0, model_turns_used=1, tool_calls_used=2),
        event_log=(
            LedgerEvent(
                event_id=f"{run_id}:event:1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len(FORBIDDEN)},
            ),
            LedgerEvent(
                event_id=f"{run_id}:event:2",
                kind=LedgerEventKind.MODEL_TURN,
                payload={
                    "text_length": 0,
                    "tool_call_count": 0,
                    "input_tokens": ModelUsage(11, 5).input_tokens,
                    "output_tokens": ModelUsage(11, 5).output_tokens,
                    "latency_ms": 4,
                },
            ),
        ),
    )


def _record(state_dir: Path, run_id: str, phase: RunPhase) -> RunRecorder:
    """Drive a recorder to ``phase`` through valid transitions only."""

    state = _state(run_id)
    recorder = RunRecorder(state_dir, run_id)
    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING)
    if phase is RunPhase.OBSERVING:
        return recorder
    if phase is RunPhase.UNKNOWN_OUTCOME:
        recorder.record(state, RunPhase.UNKNOWN_OUTCOME, run_duration_ms=9)
        return recorder
    recorder.record(state, RunPhase.PLANNING)
    if phase is RunPhase.PLANNING:
        return recorder
    if phase is RunPhase.WAITING_APPROVAL:
        recorder.record(state, RunPhase.WAITING_APPROVAL)
        return recorder
    if phase is RunPhase.PAUSED:
        recorder.record(state, RunPhase.WAITING_APPROVAL)
        recorder.record(state, RunPhase.PAUSED)
        return recorder
    if phase is RunPhase.SUCCESS:
        recorder.record(state, RunPhase.SUCCESS, run_duration_ms=20)
        return recorder
    if phase is RunPhase.FAILED:
        recorder.record(state, RunPhase.FAILED, failure_code="POLICY_DENIED", run_duration_ms=15)
        return recorder
    raise AssertionError(f"unhandled phase {phase}")


def _checkpoint(state_dir: Path, run_id: str, phase: RunPhase) -> dict:
    recorder = _record(state_dir, run_id, phase)
    return json.loads(recorder.checkpoint_path.read_text(encoding="utf-8"))


def _campaign(state_dir: Path, campaign_id: str = "campaign_1") -> RunLock:
    lock = RunLock(state_dir.parent / f"lock_{campaign_id}")
    lock.acquire()
    store = CampaignStore(state_dir, lock)
    store.create(
        CampaignManifest(
            campaign_id=campaign_id,
            kind=CAMPAIGN_SECRET,
            policy_digest=DIGEST,
            schema_digest=DIGEST,
            created_at="2026-07-22T08:00:00+00:00",
            updated_at="2026-07-22T08:00:00+00:00",
        )
    )
    store.write_heartbeat(
        campaign_id,
        CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id="private_worker_run",
            started_at="2026-07-22T08:00:00+00:00",
            heartbeat_at="2026-07-22T08:59:00+00:00",
            fresh_until="2026-07-22T09:04:00+00:00",
        ),
    )
    return lock


def test_success_view_reports_terminal_facts(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_ok", RunPhase.SUCCESS))

    assert view.display_state == "Complete"
    assert view.is_terminal is True
    assert view.liveness_known is True
    assert view.needs_reobserve is False
    assert view.model_calls.used == 1 and view.model_calls.limit == 3
    assert view.tool_calls.used == 2 and view.tool_calls.limit == 4
    assert view.input_tokens == 11 and view.output_tokens == 5
    assert view.token_coverage_known is True
    assert view.screenshot_results == 0
    assert view.screenshot_count_known is True
    assert view.elapsed_known is True
    assert view.duration_ms == 20
    assert view.failure_code is None


def test_legacy_checkpoint_keeps_new_progress_facts_unknown(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path.resolve(), "run_mid", RunPhase.PLANNING)
    checkpoint.pop("created_at")
    checkpoint["metrics"].pop("provider_usage_report_count")
    checkpoint["metrics"].pop("screenshot_results")

    view = checkpoint_to_view(checkpoint)

    # Acceptance check 6: a legacy checkpoint never turns missing facts into zero.
    assert view.token_coverage_known is False
    assert view.elapsed_known is False
    assert view.duration_ms is None
    assert view.screenshot_count_known is False
    assert view.screenshot_results == 0


def test_nonterminal_phase_is_not_reported_as_running(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_mid", RunPhase.PLANNING))

    assert view.display_state == "In progress at last checkpoint; liveness unknown"
    assert view.is_terminal is False
    assert view.liveness_known is False
    assert view.elapsed_known is True
    assert view.duration_ms is not None and view.duration_ms >= 0


def test_waiting_approval_has_a_definite_but_nonterminal_label(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_wait", RunPhase.WAITING_APPROVAL))

    assert view.display_state == "Waiting approval"
    assert view.is_terminal is False
    assert view.liveness_known is False


def test_paused_has_known_liveness_and_requires_operator_attention(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_paused", RunPhase.PAUSED))

    assert view.display_state == "Paused; operator attention"
    assert view.is_terminal is False
    assert view.liveness_known is True
    assert view.needs_reobserve is False


def test_unknown_outcome_is_distinct_and_flags_reobservation(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_uncertain", RunPhase.UNKNOWN_OUTCOME))

    # Acceptance check 7: UNKNOWN_OUTCOME is distinct and never a retry affordance.
    # The view model is pure data: it carries a re-observe flag and no action or
    # retry field a window could wire to a button.
    assert view.display_state == "Uncertain; re-observe before retry"
    assert view.needs_reobserve is True
    assert view.is_terminal is True
    assert set(view.as_display_dict()) == {
        "run_id",
        "phase",
        "display_state",
        "is_terminal",
        "liveness_known",
        "needs_reobserve",
        "model_calls",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "token_coverage_known",
        "image_results",
        "screenshot_results",
        "screenshot_count_known",
        "tool_failures",
        "elapsed_known",
        "duration_ms",
        "failure_code",
    }


def test_groups_attention_in_progress_and_history_with_stable_order(tmp_path: Path) -> None:
    attention_old = replace(
        checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_wait", RunPhase.WAITING_APPROVAL)),
        updated_at_us=10,
    )
    attention_new = replace(
        checkpoint_to_view(
            _checkpoint(tmp_path.resolve(), "run_uncertain", RunPhase.UNKNOWN_OUTCOME)
        ),
        updated_at_us=20,
    )
    current = replace(
        checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_current", RunPhase.PLANNING)),
        updated_at_us=30,
    )
    history = replace(
        checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_done", RunPhase.SUCCESS)),
        updated_at_us=40,
    )

    groups = group_progress_views((history, attention_old, current, attention_new))

    assert [group.key for group in groups] == ["attention", "in_progress", "history"]
    assert [view.run_id for view in groups[0].views] == ["run_uncertain", "run_wait"]
    assert [view.run_id for view in groups[1].views] == ["run_current"]
    assert [view.run_id for view in groups[2].views] == ["run_done"]


def test_grouping_rejects_duplicate_or_inconsistent_views(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_one", RunPhase.PLANNING))

    with pytest.raises(ProgressViewError):
        group_progress_views((view, view))
    with pytest.raises(ProgressViewError):
        group_progress_views((replace(view, is_terminal=True),))


def test_failed_view_carries_only_the_fixed_code(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_bad", RunPhase.FAILED))

    assert view.display_state == "Failed"
    assert view.failure_code == "POLICY_DENIED"


def test_display_dict_excludes_forbidden_checkpoint_content(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path.resolve(), "run_ok", RunPhase.SUCCESS)
    # Inject content the reducer must never surface even if it appears on disk.
    checkpoint["task_preview"] = FORBIDDEN
    checkpoint["window_title"] = "Secret Window Title"
    checkpoint["failure_message"] = "boom: PROGRESS_TASK_SECRET"

    rendered = json.dumps(checkpoint_to_view(checkpoint).as_display_dict())

    assert FORBIDDEN not in rendered
    assert "Secret Window Title" not in rendered
    assert "boom" not in rendered


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c.__setitem__("phase", "NOT_A_PHASE"),
        lambda c: c.__setitem__("run_id", "../escape"),
        lambda c: c.pop("budgets"),
        lambda c: c.pop("metrics"),
        lambda c: c["metrics"].__setitem__("input_tokens", -1),
        lambda c: c["budgets"].__setitem__("tool_calls_used", 99),
        lambda c: c["metrics"].__setitem__("provider_usage_report_count", 99),
        lambda c: c["metrics"].__setitem__("screenshot_results", 1),
        lambda c: c.__setitem__("failure_code", "lowercase bad"),
        lambda c: c.__setitem__("created_at", "not-a-timestamp"),
        lambda c: c.__setitem__("created_at", "9999-01-01T00:00:00+00:00"),
        lambda c: c.__setitem__("updated_at", "not-a-timestamp"),
        lambda c: c.__setitem__("updated_at", "2026-07-22T09:00:00"),
    ],
)
def test_corrupt_checkpoint_fails_closed(tmp_path: Path, mutate) -> None:
    checkpoint = _checkpoint(tmp_path.resolve(), "run_ok", RunPhase.SUCCESS)
    mutate(checkpoint)

    with pytest.raises(ProgressViewError):
        checkpoint_to_view(checkpoint)


def test_failure_code_on_a_nonterminal_checkpoint_is_rejected(tmp_path: Path) -> None:
    checkpoint = _checkpoint(tmp_path.resolve(), "run_mid", RunPhase.PLANNING)
    checkpoint["failure_code"] = "POLICY_DENIED"

    with pytest.raises(ProgressViewError):
        checkpoint_to_view(checkpoint)


def test_projection_keeps_valid_runs_separate_and_isolates_corruption(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_ok", RunPhase.SUCCESS)
    _record(state_dir, "run_wait", RunPhase.WAITING_APPROVAL)
    corrupt = _record(state_dir, "run_corrupt", RunPhase.SUCCESS)
    corrupt.checkpoint_path.write_text('{"checkpoint_version":1}', encoding="utf-8")

    projection = build_progress_projection(state_dir)

    assert {view.run_id for view in projection.views} == {"run_ok", "run_wait"}
    assert projection.unavailable_run_ids == ("run_corrupt",)
    assert projection.unavailable_unnamed == 0


def test_projection_counts_unsafe_directory_names_without_naming_them(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    _record(state_dir, "run_ok", RunPhase.SUCCESS)
    (state_dir / "runs" / "..unsafe").mkdir()
    (state_dir / "runs" / "loose_file").write_text("x", encoding="utf-8")

    projection = build_progress_projection(state_dir)

    assert {view.run_id for view in projection.views} == {"run_ok"}
    assert projection.unavailable_unnamed == 2
    assert projection.unavailable_run_ids == ()


def test_projection_is_empty_and_read_only_without_a_runs_directory(tmp_path: Path) -> None:
    state_dir = (tmp_path / "missing").resolve()

    projection = build_progress_projection(state_dir)

    assert projection.views == ()
    assert not state_dir.exists()


def test_campaign_projection_is_lock_free_bounded_and_redacted(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    lock = _campaign(state_dir)
    try:
        projection = build_progress_projection(state_dir, now=NOW)
    finally:
        lock.release()

    assert len(projection.campaigns) == 1
    view = projection.campaigns[0]
    assert view.campaign_id == "campaign_1"
    assert view.status == "RUNNING"
    assert view.display_state == "Running"
    assert view.discovered_count == view.completed_count == 0
    rendered = json.dumps(view.as_display_dict())
    assert CAMPAIGN_SECRET not in rendered
    assert DIGEST not in rendered
    assert "private_worker_run" not in rendered


def test_campaign_corruption_is_isolated_from_valid_campaign(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    good_lock = _campaign(state_dir, "campaign_good")
    good_lock.release()
    bad_lock = _campaign(state_dir, "campaign_bad")
    bad_lock.release()
    (state_dir / "campaigns" / "campaign_bad" / "manifest.json").write_text(
        "{ not json", encoding="utf-8"
    )

    projection = build_progress_projection(state_dir, now=NOW)

    assert [view.campaign_id for view in projection.campaigns] == ["campaign_good"]
    assert projection.unavailable_campaign_ids == ("campaign_bad",)


def test_campaign_groups_attention_before_active_and_history() -> None:
    def view(campaign_id: str, status: HostTaskStatus, at: str):
        return campaign_status_to_view(
            CampaignHostStatus(campaign_id, status, 3, 1, 1, 0, at)
        )

    groups = group_campaign_views(
        (
            view("done", HostTaskStatus.COMPLETED, "2026-07-22T09:03:00+00:00"),
            view("active", HostTaskStatus.RUNNING, "2026-07-22T09:02:00+00:00"),
            view("paused", HostTaskStatus.PAUSED, "2026-07-22T09:01:00+00:00"),
            view("stale", HostTaskStatus.STALE, "2026-07-22T09:04:00+00:00"),
        )
    )

    assert [group.key for group in groups] == ["attention", "active", "history"]
    assert [view.campaign_id for view in groups[0].views] == ["stale", "paused"]
