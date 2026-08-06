from __future__ import annotations

import json
from pathlib import Path

import pytest

import computer_use_agent.fullcycle_export as fullcycle_module
import computer_use_agent.trace as trace_module
from computer_use_agent.fullcycle_export import (
    build_fullcycle_manifest,
    build_fullcycle_run_export,
    canonical_json_bytes,
    fullcycle_manifest_digest,
    write_new_fullcycle_json,
)
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.trace import RunRecorder, TraceError
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


def _redacted_run(state_dir: Path) -> RunState:
    identity = CallIdentity("run_fullcycle", "turn_1", "call_1")
    call = ToolCall(identity=identity, name="type", arguments={"text": "TYPED_SECRET"})
    result = ToolResult(
        identity=identity,
        tool_name="type",
        status=ToolResultStatus.REJECTED,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code="POLICY_DENIED",
    )
    state = RunState(
        run_id="run_fullcycle",
        task="TASK_SECRET",
        policy_version="trace-v1",
        observation_epoch=0,
        budgets=RunBudget(1, 1, 0, tool_calls_used=1),
        event_log=(
            LedgerEvent(
                "event_1",
                LedgerEventKind.USER_TASK,
                payload={"task_length": len("TASK_SECRET")},
            ),
            LedgerEvent(
                "event_2",
                LedgerEventKind.TOOL_CALL,
                identity=identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=("text",)
                ),
            ),
            LedgerEvent(
                "event_3",
                LedgerEventKind.TOOL_RESULT,
                identity=identity,
                tool_result=result,
            ),
        ),
    )
    RunRecorder(state_dir, state.run_id).start(state)
    return state


def test_manifest_is_exactly_versioned_and_derived_from_reviewed_tools() -> None:
    manifest = build_fullcycle_manifest()

    assert {
        key: value for key, value in manifest.items() if key != "tools"
    } == {
        "fullcycle_manifest_version": 1,
        "agent_contract_version": "0.1.0",
        "driver_contract_version": "1.0.0",
        "trace_version": 1,
        "checkpoint_version": 1,
        "plan_contract_version": 1,
        "automatic_export": {
            "contains_raw_task": False,
            "contains_model_text": False,
            "contains_tool_result_text": False,
            "contains_images": False,
            "contains_memory": False,
            "contains_continuation": False,
        },
    }
    assert [tool["name"] for tool in manifest["tools"]] == [
        tool.name for tool in REVIEWED_TOOLS
    ]
    assert manifest["tools"][0] == {
        "name": "ui_snapshot",
        "description": "List interactive UI elements and session-scoped refs.",
        "input_schema": {
            "additionalProperties": False,
                "properties": {
                    "scope": {
                        "pattern": r"^(?:foreground|all|[1-9][0-9]*)$",
                        "type": "string",
                    }
                },
            "required": [],
            "type": "object",
        },
        "effect": "observation",
        "result_content": "text",
        "result_sensitivity": "normal",
        "redaction_policy": "none",
        "grounding": "none",
        "requires_host_approval": False,
        "invalidates_observation": False,
        "sensitive_arguments": [],
        "required_safety_baselines": [],
    }
    assert fullcycle_manifest_digest().startswith("sha256:")
    assert len(fullcycle_manifest_digest()) == 71


def test_run_export_is_exact_redacted_record_and_manifest_binding(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    state = _redacted_run(state_dir)

    payload = build_fullcycle_run_export(state_dir, state.run_id)

    recorder = RunRecorder(state_dir, state.run_id)
    assert payload == {
        "fullcycle_run_export_version": 1,
        "manifest_digest": fullcycle_manifest_digest(),
        "run_id": state.run_id,
        "checkpoint": json.loads(recorder.checkpoint_path.read_text(encoding="utf-8")),
        "events": [
            json.loads(line)
            for line in recorder.trace_path.read_text(encoding="utf-8").splitlines()
        ],
        "data_class": "redacted_runtime_evidence",
        "training_use": "reliability_and_verifier_only",
    }
    serialized = canonical_json_bytes(payload)
    assert b"TASK_SECRET" not in serialized
    assert b"TYPED_SECRET" not in serialized


def test_output_is_canonical_non_overwriting_and_absolute(tmp_path: Path) -> None:
    output = tmp_path.resolve() / "manifest.json"
    payload = build_fullcycle_manifest()

    write_new_fullcycle_json(output, payload)

    assert output.read_bytes() == canonical_json_bytes(payload)
    with pytest.raises(ValueError, match="FULLCYCLE_OUTPUT_ALREADY_EXISTS"):
        write_new_fullcycle_json(output, payload)
    with pytest.raises(ValueError, match="FULLCYCLE_OUTPUT_MUST_BE_ABSOLUTE"):
        write_new_fullcycle_json(Path("manifest.json"), payload)


def test_export_rejects_incomplete_and_symlinked_trace(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    state = _redacted_run(state_dir)
    recorder = RunRecorder(state_dir, state.run_id)
    recorder.trace_path.write_text("", encoding="utf-8")
    with pytest.raises(TraceError, match="RUN_RECORD_INCOMPLETE"):
        build_fullcycle_run_export(state_dir, state.run_id)

    recorder.trace_path.unlink()
    target = tmp_path / "redirected.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    try:
        recorder.trace_path.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable")
    with pytest.raises(TraceError, match="TRACE_READ_FAILED"):
        build_fullcycle_run_export(state_dir, state.run_id)


def test_export_rejects_oversized_trace_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_dir = tmp_path.resolve()
    state = _redacted_run(state_dir)
    monkeypatch.setattr(trace_module, "MAX_TRACE_BYTES", 1)

    with pytest.raises(TraceError, match="TRACE_READ_FAILED"):
        build_fullcycle_run_export(state_dir, state.run_id)


def test_export_rejects_unknown_or_rich_injected_fields(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    state = _redacted_run(state_dir)
    recorder = RunRecorder(state_dir, state.run_id)
    lines = recorder.trace_path.read_text(encoding="utf-8").splitlines()
    injected = json.loads(lines[0])
    injected["raw_task"] = "INJECTED_SECRET"
    lines[0] = json.dumps(injected, sort_keys=True, separators=(",", ":"))
    recorder.trace_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="FULLCYCLE_RUN_RECORD_UNSAFE"):
        build_fullcycle_run_export(state_dir, state.run_id)


def test_output_size_limit_fails_before_file_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path.resolve() / "too-large.json"
    monkeypatch.setattr(fullcycle_module, "MAX_FULLCYCLE_OUTPUT_BYTES", 1)

    with pytest.raises(ValueError, match="FULLCYCLE_OUTPUT_TOO_LARGE"):
        write_new_fullcycle_json(output, {"value": "bounded"})
    assert not output.exists()
