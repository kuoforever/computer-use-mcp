from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.trace import (
    RunPhase,
    RunRecorder,
    TraceError,
    read_run_record,
    validate_transition,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def _state(tmp_path: Path, *, typed_value: str = "TRACE_TYPED_SECRET") -> RunState:
    del tmp_path
    identity = CallIdentity("run_trace", "turn_1", "call_1")
    call = ToolCall(identity=identity, name="type", arguments={"text": typed_value})
    result = ToolResult(
        identity=identity,
        tool_name="type",
        status=ToolResultStatus.REJECTED,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code="POLICY_DENIED",
    )
    return RunState(
        run_id="run_trace",
        task="TASK_SECRET",
        policy_version="trace-v1",
        observation_epoch=0,
        budgets=RunBudget(2, 2, 0, model_turns_used=1, tool_calls_used=1),
        event_log=(
            LedgerEvent(
                event_id="event_1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": len("TASK_SECRET")},
            ),
            LedgerEvent(
                event_id="event_2",
                kind=LedgerEventKind.TOOL_CALL,
                identity=identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=("text",)
                ),
            ),
            LedgerEvent(
                event_id="event_3",
                kind=LedgerEventKind.TOOL_RESULT,
                identity=identity,
                tool_result=result,
            ),
        ),
    )


def test_recorder_writes_atomic_checkpoint_and_redacted_trace(tmp_path: Path) -> None:
    state = _state(tmp_path)
    recorder = RunRecorder(tmp_path.resolve(), state.run_id)

    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING)
    recorder.record(state, RunPhase.FAILED, failure_code="POLICY_DENIED")
    record = read_run_record(tmp_path.resolve(), state.run_id)

    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "POLICY_DENIED"
    assert record["state"]["resume_allowed"] is False
    assert record["state"]["event_count"] == 3
    assert record["events"][1]["arguments"] == {
        "text_present": True,
        "text_length": len("TRACE_TYPED_SECRET"),
        "ref_supplied": False,
    }
    serialized = json.dumps(record)
    assert "TASK_SECRET" not in serialized
    assert "TRACE_TYPED_SECRET" not in serialized
    assert not list(recorder.run_dir.glob("*.tmp"))


def test_existing_record_and_illegal_transition_fail_closed(tmp_path: Path) -> None:
    state = _state(tmp_path)
    recorder = RunRecorder(tmp_path.resolve(), state.run_id)
    recorder.start(state)

    with pytest.raises(TraceError, match="RUN_RECORD_ALREADY_EXISTS"):
        RunRecorder(tmp_path.resolve(), state.run_id).start(state)
    with pytest.raises(TraceError, match="ILLEGAL_RUN_PHASE_TRANSITION"):
        recorder.record(state, RunPhase.SUCCESS)
    with pytest.raises(TraceError, match="ILLEGAL_RUN_PHASE_TRANSITION"):
        validate_transition(RunPhase.SUCCESS, RunPhase.PLANNING)


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "", ".", "x" * 129])
def test_run_id_must_be_path_safe(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ValueError, match="path-safe"):
        RunRecorder(tmp_path.resolve(), run_id)


def test_reader_rejects_truncation_sequence_drift_and_checkpoint_mismatch(
    tmp_path: Path,
) -> None:
    state = _state(tmp_path)
    recorder = RunRecorder(tmp_path.resolve(), state.run_id)
    recorder.start(state)
    lines = recorder.trace_path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    event["sequence"] = 99
    lines[0] = json.dumps(event)
    recorder.trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(TraceError, match="TRACE_READ_FAILED"):
        read_run_record(tmp_path.resolve(), state.run_id)
