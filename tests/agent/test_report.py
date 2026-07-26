from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.report import RunReportError, build_run_report
from computer_use_agent.trace import RunPhase, RunRecorder
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    ModelUsage,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def _state(run_id: str, *, failed: bool = False) -> RunState:
    identity = CallIdentity(run_id, "turn_1", "call_1")
    result = ToolResult(
        identity,
        "list_windows",
        ToolResultStatus.REJECTED if failed else ToolResultStatus.SUCCESS,
        DispatchCertainty.NOT_DISPATCHED if failed else DispatchCertainty.DISPATCHED,
        code="POLICY_DENIED" if failed else None,
    )
    call = ToolCall(identity, "list_windows", {})
    return RunState(
        run_id=run_id,
        task="REPORT_TASK_SECRET",
        policy_version="report-v1",
        observation_epoch=0,
        budgets=RunBudget(2, 2, 0, model_turns_used=1, tool_calls_used=1),
        event_log=(
            LedgerEvent(
                event_id=f"{run_id}:event:1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len("REPORT_TASK_SECRET")},
            ),
            LedgerEvent(
                event_id=f"{run_id}:event:2",
                kind=LedgerEventKind.MODEL_TURN,
                payload={
                    "text_length": 0,
                    "tool_call_count": 1,
                    "input_tokens": ModelUsage(3, 2).input_tokens,
                    "output_tokens": ModelUsage(3, 2).output_tokens,
                    "latency_ms": 7,
                },
            ),
            LedgerEvent(
                event_id=f"{run_id}:event:3",
                kind=LedgerEventKind.TOOL_CALL,
                identity=identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=()
                ),
            ),
            LedgerEvent(
                event_id=f"{run_id}:event:4",
                kind=LedgerEventKind.TOOL_RESULT,
                identity=identity,
                tool_result=result,
                payload={"latency_ms": 5},
            ),
        ),
    )


def _record(state_dir: Path, run_id: str, phase: RunPhase) -> RunRecorder:
    state = _state(run_id, failed=phase is RunPhase.FAILED)
    recorder = RunRecorder(state_dir, run_id)
    recorder.start(state)
    if phase is RunPhase.SUCCESS:
        recorder.record(state, RunPhase.OBSERVING)
        recorder.record(state, RunPhase.PLANNING)
        recorder.record(state, RunPhase.SUCCESS, run_duration_ms=20)
    else:
        recorder.record(
            state,
            RunPhase.FAILED,
            failure_code="POLICY_DENIED",
            run_duration_ms=15,
        )
    return recorder


def test_report_aggregates_checkpoints_without_reading_trace_content(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    success = _record(state_dir, "run_success", RunPhase.SUCCESS)
    _record(state_dir, "run_failed", RunPhase.FAILED)
    success.trace_path.write_text("not-json and REPORT_TRACE_SECRET", encoding="utf-8")

    report = build_run_report(state_dir)

    assert report["run_count"] == 2
    assert report["terminal_run_count"] == 2
    assert report["incomplete_run_count"] == 0
    assert report["metrics_run_count"] == 2
    assert report["duration_run_count"] == 2
    assert report["success_rate"] == 0.5
    assert report["phase_counts"]["SUCCESS"] == 1
    assert report["phase_counts"]["FAILED"] == 1
    assert report["failure_codes"] == {"POLICY_DENIED": 1}
    assert report["totals"] == {
        "model_calls": 2,
        "tool_calls": 2,
        "input_tokens": 6,
        "output_tokens": 4,
        "provider_latency_ms": 14,
        "tool_latency_ms": 10,
        "tool_failures": 1,
        "image_results": 0,
        "retry_count": 0,
        "run_duration_ms": 35,
    }
    assert report["averages"] == {
        "provider_latency_ms": 7.0,
        "tool_latency_ms": 5.0,
        "run_duration_ms": 17.5,
    }
    assert "REPORT" not in json.dumps(report)


def test_report_counts_legacy_checkpoint_without_inventing_metrics(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    recorder = _record(state_dir, "run_legacy", RunPhase.SUCCESS)
    checkpoint = json.loads(recorder.checkpoint_path.read_text(encoding="utf-8"))
    del checkpoint["metrics"]
    recorder.checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    report = build_run_report(state_dir)

    assert report["run_count"] == 1
    assert report["metrics_run_count"] == 0
    assert report["duration_run_count"] == 0
    assert report["totals"]["input_tokens"] == 0


def test_report_accepts_legacy_metrics_without_new_coverage_fields(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path.resolve()
    recorder = _record(state_dir, "run_legacy_metrics", RunPhase.SUCCESS)
    checkpoint = json.loads(recorder.checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["metrics"].pop("provider_usage_report_count")
    checkpoint["metrics"].pop("screenshot_results")
    recorder.checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    report = build_run_report(state_dir)

    assert report["metrics_run_count"] == 1
    assert "provider_usage_report_count" not in report["totals"]
    assert "screenshot_results" not in report["totals"]


def test_report_fails_closed_on_corrupt_checkpoint(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    recorder = _record(state_dir, "run_corrupt", RunPhase.SUCCESS)
    recorder.checkpoint_path.write_text('{"checkpoint_version":1}', encoding="utf-8")

    with pytest.raises(RunReportError, match="RUN_REPORT_CHECKPOINT_INVALID"):
        build_run_report(state_dir)


def test_empty_report_is_read_only(tmp_path: Path) -> None:
    state_dir = (tmp_path / "missing").resolve()

    report = build_run_report(state_dir)

    assert report["run_count"] == 0
    assert report["success_rate"] == 0.0
    assert not state_dir.exists()
