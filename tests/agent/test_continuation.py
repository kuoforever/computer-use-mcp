from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from computer_use_agent.continuation import (
    ContinuationEnvelope,
    ContinuationError,
    continuation_path,
    read_continuation,
    write_continuation,
)
from computer_use_agent.reconstruction import (
    OperationEffect,
    OperationKind,
    OperationResult,
    OperationStage,
)


NOW = datetime(2030, 1, 1, tzinfo=UTC)


def _payload(run_id: str = "run_1") -> dict[str, object]:
    return {
        "continuation_version": 6,
        "run_id": run_id,
        "checkpoint_sequence": 7,
        "policy_version": "phase0",
        "provider": {"name": "openai", "model": "gpt-test"},
        "registry_digest": "a" * 64,
        "advertised_tool_names": ["ui_snapshot", "list_windows"],
        "task": "Inspect the window",
        "budget": {
            "max_model_turns": 3,
            "max_tool_calls": 3,
            "max_side_effects": 0,
            "max_input_tokens": 1000,
            "model_turns_used": 1,
            "tool_calls_used": 1,
            "side_effects_used": 0,
            "input_tokens_used": 12,
        },
        "observation": {"epoch": 1, "verified_epoch": 1, "mcp_generation": 1},
        "ledger": [
            {"kind": "user_task", "event_id": "event_1", "data": {"task_length": 18}},
            {
                "kind": "tool_result",
                "event_id": "event_2",
                "data": {"tool_name": "ui_snapshot", "status": "success"},
            },
        ],
        "boundary": {
            "operation_kind": "tool",
            "stage": "completed",
            "operation_id": "run_1:turn_1:call_1",
            "effect": "observation",
            "dispatch": "dispatched",
            "next_step": "provider_continue",
        },
        "provider_state": {
            "response_id": "response_1",
            "prior_context_tokens": 12,
            "request_contract_digest": "b" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect the window",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        "created_at": "2030-01-01T00:00:00Z",
        "expires_at": "2030-01-01T01:00:00Z",
    }


def test_private_continuation_round_trip_is_canonical_and_bounded(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    written = write_continuation(state_dir, _payload())
    path = continuation_path(state_dir, "run_1")
    read = read_continuation(state_dir, "run_1", now=NOW)

    assert read == written
    disk = path.read_bytes()
    assert disk.endswith(b"\n")
    assert json.loads(disk)["payload_digest"] == written.payload["payload_digest"]
    assert path.stat().st_mode & 0o777 in {0o600, 0o666}  # Windows chmod is limited.
    operation = read.operation_state
    assert operation.kind is OperationKind.TOOL
    assert operation.stage is OperationStage.COMPLETED
    assert operation.effect is OperationEffect.OBSERVATION
    assert operation.result is OperationResult.SUCCESS


@pytest.mark.parametrize("unsupported_version", [1, 2, 3, 4])
def test_v1_to_v4_continuations_are_rejected_after_schema_upgrades(
    tmp_path: Path,
    unsupported_version: int,
) -> None:
    payload = _payload()
    payload["continuation_version"] = unsupported_version

    with pytest.raises(ContinuationError, match="CONTINUATION_VERSION_UNSUPPORTED"):
        write_continuation(tmp_path.resolve(), payload)

    assert not continuation_path(tmp_path.resolve(), "run_1").exists()


def test_genuine_v5_continuation_without_tool_scope_is_rejected(
    tmp_path: Path,
) -> None:
    payload = _payload()
    payload["continuation_version"] = 5
    payload.pop("advertised_tool_names")

    with pytest.raises(ContinuationError, match="CONTINUATION_VERSION_UNSUPPORTED"):
        write_continuation(tmp_path.resolve(), payload)

    assert not continuation_path(tmp_path.resolve(), "run_1").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("advertised_tool_names"),
        lambda value: value.update(
            advertised_tool_names=["ui_snapshot", "ui_snapshot"]
        ),
        lambda value: value.update(advertised_tool_names=["browser_eval"]),
        lambda value: value.update(
            advertised_tool_names=["list_windows", "ui_snapshot"]
        ),
    ],
)
def test_v6_tool_scope_is_exact_reviewed_unique_and_canonical(
    tmp_path: Path,
    mutation: object,
) -> None:
    payload = _payload()
    mutation(payload)  # type: ignore[operator]

    with pytest.raises(ContinuationError, match="CONTINUATION_INVALID"):
        write_continuation(tmp_path.resolve(), payload)

    assert not continuation_path(tmp_path.resolve(), "run_1").exists()


def test_v6_empty_advertised_tool_scope_is_valid(tmp_path: Path) -> None:
    payload = _payload()
    payload["advertised_tool_names"] = []

    written = write_continuation(tmp_path.resolve(), payload)

    assert written.payload["advertised_tool_names"] == []


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda value: value.update(extra=True), "CONTINUATION_INVALID"),
        (
            lambda value: value["budget"].update(model_turns_used=4),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["observation"].update(verified_epoch=2),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["ledger"].append(value["ledger"][0]),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["boundary"].update(
                stage="dispatch_intent", dispatch="not_dispatched"
            ),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["provider_state"].pop("prior_context_tokens"),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["provider_state"].update(
                initial_input="different task"
            ),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["provider_state"].update(output_batches=[]),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["provider_state"]["output_batches"][0].update(
                response_id="different_response"
            ),
            "CONTINUATION_INVALID",
        ),
        (
            lambda value: value["provider_state"]["output_batches"][0][
                "items"
            ].append({"id": "missing_type"}),
            "CONTINUATION_INVALID",
        ),
    ],
)
def test_writer_rejects_invalid_schema_without_creating_file(
    tmp_path: Path, mutation: object, code: str
) -> None:
    payload = _payload()
    mutation(payload)  # type: ignore[operator]
    with pytest.raises(ContinuationError, match=code):
        write_continuation(tmp_path.resolve(), payload)
    assert not continuation_path(tmp_path.resolve(), "run_1").exists()


def test_reader_rejects_expiry_digest_corruption_and_identity(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    write_continuation(state_dir, _payload())
    with pytest.raises(ContinuationError, match="CONTINUATION_EXPIRED"):
        read_continuation(
            state_dir, "run_1", now=datetime(2030, 1, 1, 1, tzinfo=UTC)
        )

    path = continuation_path(state_dir, "run_1")
    persisted = json.loads(path.read_text(encoding="utf-8"))
    persisted["policy_version"] = "tampered"
    path.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(ContinuationError, match="CONTINUATION_DIGEST_MISMATCH"):
        read_continuation(state_dir, "run_1", now=NOW)

    valid = _payload("run_other")
    valid["payload_digest"] = "0" * 64
    with pytest.raises(ContinuationError, match="CONTINUATION_IDENTITY_MISMATCH"):
        ContinuationEnvelope.from_payload(valid, expected_run_id="run_1", now=NOW)


def test_raw_type_text_is_rejected(tmp_path: Path) -> None:
    payload = _payload()
    payload["ledger"] = [
        {
            "kind": "tool_call",
            "event_id": "event_1",
            "data": {"tool_name": "type", "arguments": {"text": "secret"}},
        }
    ]
    with pytest.raises(ContinuationError, match="CONTINUATION_SENSITIVE_FIELD"):
        write_continuation(tmp_path.resolve(), payload)


def test_openai_initial_input_accepts_only_canonical_reviewed_memory_data(
    tmp_path: Path,
) -> None:
    payload = _payload()
    provider_state = payload["provider_state"]
    assert isinstance(provider_state, dict)
    provider_state["memory_context_used"] = True
    provider_state["initial_input"] = (
        "Inspect the window\n\nOptional memory context (JSON data):\n"
        '[{"content":"concise","kind":"preference","scope":"global",'
        '"source":"user_confirmed"}]'
    )

    written = write_continuation(tmp_path.resolve(), payload)

    assert written.payload["provider_state"] == provider_state


def test_provider_state_is_provider_specific(tmp_path: Path) -> None:
    invalid_openai = _payload()
    invalid_openai["provider_state"] = {"messages": []}
    with pytest.raises(ContinuationError, match="CONTINUATION_INVALID"):
        write_continuation(tmp_path.resolve(), invalid_openai)

    anthropic = _payload("run_anthropic")
    anthropic["provider"] = {"name": "anthropic", "model": "claude-test"}
    anthropic["provider_state"] = {"messages": []}
    assert write_continuation(tmp_path.resolve(), anthropic).payload["run_id"] == "run_anthropic"


def test_symlinked_run_directory_fails_closed(tmp_path: Path) -> None:
    state_dir = tmp_path.resolve()
    target = state_dir / "target"
    target.mkdir()
    run_dir = state_dir / "runs" / "run_1"
    run_dir.parent.mkdir()
    try:
        run_dir.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    with pytest.raises(ContinuationError, match="CONTINUATION_UNSAFE_PATH"):
        write_continuation(state_dir, _payload())


def test_path_validation_rejects_traversal_and_relative_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="path-safe"):
        continuation_path(tmp_path.resolve(), "../escape")
    with pytest.raises(ValueError, match="absolute"):
        continuation_path(Path("relative"), "run_1")
