from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.progress_view import (
    ProgressViewError,
    build_progress_projection,
    checkpoint_to_view,
)
from computer_use_agent.trace import RunPhase, RunRecorder
from computer_use_agent.types import (
    LedgerEvent,
    LedgerEventKind,
    ModelUsage,
    RunBudget,
    RunState,
)

FORBIDDEN = "PROGRESS_TASK_SECRET"


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


def test_success_view_reports_terminal_facts(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_ok", RunPhase.SUCCESS))

    assert view.display_state == "Complete"
    assert view.is_terminal is True
    assert view.liveness_known is True
    assert view.needs_reobserve is False
    assert view.model_calls.used == 1 and view.model_calls.limit == 3
    assert view.tool_calls.used == 2 and view.tool_calls.limit == 4
    assert view.input_tokens == 11 and view.output_tokens == 5
    assert view.duration_ms == 20
    assert view.failure_code is None


def test_v1_never_claims_token_coverage_or_elapsed_time(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_ok", RunPhase.SUCCESS))

    # Acceptance check 6: unknown coverage and liveness are never shown as facts.
    assert view.token_coverage_known is False
    assert view.elapsed_known is False


def test_nonterminal_phase_is_not_reported_as_running(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_mid", RunPhase.PLANNING))

    assert view.display_state == "In progress at last checkpoint; liveness unknown"
    assert view.is_terminal is False
    assert view.liveness_known is False
    assert view.duration_ms is None


def test_waiting_approval_has_a_definite_but_nonterminal_label(tmp_path: Path) -> None:
    view = checkpoint_to_view(_checkpoint(tmp_path.resolve(), "run_wait", RunPhase.WAITING_APPROVAL))

    assert view.display_state == "Waiting approval"
    assert view.is_terminal is False
    assert view.liveness_known is False


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
        "tool_failures",
        "elapsed_known",
        "duration_ms",
        "failure_code",
    }


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
        lambda c: c.__setitem__("failure_code", "lowercase bad"),
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
