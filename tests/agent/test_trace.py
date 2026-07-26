from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent import trace as trace_module

from computer_use_agent.trace import (
    RunPhase,
    RunRecorder,
    TraceError,
    classify_run_recovery,
    cancel_run_record,
    read_run_record,
    validate_transition,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
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
    created_at = json.loads(recorder.checkpoint_path.read_text(encoding="utf-8"))[
        "created_at"
    ]
    recorder.record(state, RunPhase.OBSERVING)
    recorder.record(state, RunPhase.FAILED, failure_code="POLICY_DENIED")
    record = read_run_record(tmp_path.resolve(), state.run_id)

    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "POLICY_DENIED"
    assert record["state"]["resume_allowed"] is False
    assert record["state"]["event_count"] == 3
    assert record["state"]["created_at"] == created_at
    assert record["state"]["metrics"]["provider_usage_report_count"] == 0
    assert record["state"]["metrics"]["screenshot_results"] == 0
    assert record["events"][1]["arguments"] == {
        "text_present": True,
        "text_length": len("TRACE_TYPED_SECRET"),
        "ref_supplied": False,
    }
    serialized = json.dumps(record)
    assert "TASK_SECRET" not in serialized
    assert "TRACE_TYPED_SECRET" not in serialized
    assert not list(recorder.run_dir.glob("*.tmp"))


def test_checkpoint_distinguishes_usage_coverage_and_screenshots(
    tmp_path: Path,
) -> None:
    screenshot_identity = CallIdentity("run_metrics", "turn_1", "call_1")
    screenshot_call = ToolCall(
        identity=screenshot_identity,
        name="screenshot",
        arguments={},
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01"
    )
    screenshot_result = ToolResult(
        identity=screenshot_identity,
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(ImageContent("image/png", png, 1, 1),),
    )
    state = RunState(
        run_id="run_metrics",
        task="metrics",
        policy_version="trace-v1",
        observation_epoch=0,
        budgets=RunBudget(2, 1, 0, model_turns_used=2, tool_calls_used=1),
        event_log=(
            LedgerEvent(
                event_id="event_1",
                kind=LedgerEventKind.USER_TASK,
                payload={"task_length": 7},
            ),
            LedgerEvent(
                event_id="event_2",
                kind=LedgerEventKind.MODEL_TURN,
                payload={
                    "text_length": 0,
                    "tool_call_count": 0,
                    "input_tokens": 3,
                    "output_tokens": 2,
                },
            ),
            LedgerEvent(
                event_id="event_3",
                kind=LedgerEventKind.MODEL_TURN,
                payload={
                    "text_length": 0,
                    "tool_call_count": 1,
                    "input_tokens": None,
                    "output_tokens": None,
                },
            ),
            LedgerEvent(
                event_id="event_4",
                kind=LedgerEventKind.TOOL_CALL,
                identity=screenshot_identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    screenshot_call,
                    sensitive_arguments=(),
                ),
            ),
            LedgerEvent(
                event_id="event_5",
                kind=LedgerEventKind.TOOL_RESULT,
                identity=screenshot_identity,
                tool_result=screenshot_result,
            ),
        ),
    )
    recorder = RunRecorder(tmp_path.resolve(), state.run_id)

    recorder.start(state)
    checkpoint = json.loads(recorder.checkpoint_path.read_text(encoding="utf-8"))

    assert checkpoint["metrics"]["provider_usage_report_count"] == 1
    assert checkpoint["metrics"]["input_tokens"] == 3
    assert checkpoint["metrics"]["output_tokens"] == 2
    assert checkpoint["metrics"]["image_results"] == 1
    assert checkpoint["metrics"]["screenshot_results"] == 1


def test_phase_observer_runs_only_after_durable_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _state(tmp_path)
    observed: list[tuple[RunPhase, str]] = []
    recorder = RunRecorder(
        tmp_path.resolve(),
        state.run_id,
        phase_observer=lambda phase: observed.append(
            (phase, recorder.checkpoint_path.read_text(encoding="utf-8"))
        ),
    )
    recorder.start(state)
    assert [phase for phase, _checkpoint in observed] == [RunPhase.CREATED]
    assert '"phase":"CREATED"' in observed[0][1]

    def fail_checkpoint(_path: Path, _payload: object) -> None:
        raise TraceError("CHECKPOINT_WRITE_FAILED")

    monkeypatch.setattr(trace_module, "_atomic_json", fail_checkpoint)
    with pytest.raises(TraceError, match="CHECKPOINT_WRITE_FAILED"):
        recorder.record(state, RunPhase.OBSERVING)
    assert [phase for phase, _checkpoint in observed] == [RunPhase.CREATED]


def test_phase_observer_failure_cannot_fail_recording(tmp_path: Path) -> None:
    state = _state(tmp_path)

    def fail_observer(_phase: RunPhase) -> None:
        raise RuntimeError("passive observer failed")

    recorder = RunRecorder(
        tmp_path.resolve(), state.run_id, phase_observer=fail_observer
    )
    recorder.start(state)
    assert read_run_record(tmp_path.resolve(), state.run_id)["state"]["phase"] == "CREATED"


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


def test_initial_record_can_attach_but_progressed_record_cannot_resume(tmp_path: Path) -> None:
    state = _state(tmp_path)
    initial = RunState(
        run_id=state.run_id,
        task=state.task,
        policy_version=state.policy_version,
        observation_epoch=0,
        budgets=RunBudget(2, 2, 0),
        event_log=(state.event_log[0],),
    )
    recorder = RunRecorder(tmp_path.resolve(), initial.run_id)
    recorder.start(initial)

    attached = RunRecorder(tmp_path.resolve(), initial.run_id)
    attached.attach_initial(initial)
    assert attached.phase is RunPhase.CREATED

    recorder.record(initial, RunPhase.OBSERVING)
    recorder.record(initial, RunPhase.PLANNING)
    with pytest.raises(TraceError, match="RUN_NOT_RESUMABLE"):
        RunRecorder(tmp_path.resolve(), initial.run_id).attach_initial(initial)


@pytest.mark.parametrize(
    ("phase", "action", "reason"),
    [
        ("PLANNING", "start_new_run", "PROVIDER_OR_TOOL_PROGRESS"),
        ("WAITING_APPROVAL", "start_new_run", "PROVIDER_OR_TOOL_PROGRESS"),
        ("PAUSED", "start_new_run", "OPERATOR_DEFERRED"),
        ("EXECUTING", "start_new_run", "PROVIDER_OR_TOOL_PROGRESS"),
        ("VERIFYING", "start_new_run", "PROVIDER_OR_TOOL_PROGRESS"),
        ("FAILED", "start_new_run", "RUN_TERMINAL"),
        ("CANCELLED", "start_new_run", "RUN_TERMINAL"),
        ("UNKNOWN_OUTCOME", "human_reobserve", "UNKNOWN_OUTCOME"),
        ("SUCCESS", "none", "RUN_SUCCEEDED"),
    ],
)
def test_recovery_classification_fails_closed_after_progress(
    phase: str, action: str, reason: str
) -> None:
    checkpoint = {
        "phase": phase,
        "resume_allowed": False,
        "event_count": 2,
        "task_length": 4,
        "policy_version": "v1",
        "recovery_status": "ready",
        "observation_epoch": 0,
        "verified_observation_epoch": None,
        "budgets": {
            "model_turns_used": 1,
            "tool_calls_used": 0,
            "side_effects_used": 0,
            "input_tokens_used": 1,
        },
    }

    decision = classify_run_recovery(checkpoint, task_length=4, policy_version="v1")

    assert decision.action == action
    assert decision.reason == reason
    assert decision.resume_allowed is False


def test_cancel_atomically_closes_nonterminal_record(tmp_path: Path) -> None:
    state = _state(tmp_path)
    recorder = RunRecorder(tmp_path.resolve(), state.run_id)
    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING)

    checkpoint = cancel_run_record(tmp_path.resolve(), state.run_id)

    assert checkpoint["phase"] == "CANCELLED"
    assert checkpoint["failure_code"] == "CANCELLED_BY_OPERATOR"
    assert checkpoint["resume_allowed"] is False
    with pytest.raises(TraceError, match="RUN_ALREADY_TERMINAL"):
        cancel_run_record(tmp_path.resolve(), state.run_id)


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
