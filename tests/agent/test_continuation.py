from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
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


class _MappingProbeError(RuntimeError):
    pass


class _StatefulMapping(Mapping[str, object]):
    def __init__(
        self,
        data: Mapping[str, object],
        *,
        sequences: Mapping[str, tuple[object, ...]] | None = None,
        failures: Mapping[str, tuple[int, str]] | None = None,
    ) -> None:
        self._data = data
        self._sequences = {} if sequences is None else sequences
        self._failures = {} if failures is None else failures
        self._reads: dict[str, int] = {}

    def __getitem__(self, key: str) -> object:
        read = self._reads.get(key, 0) + 1
        self._reads[key] = read
        failure = self._failures.get(key)
        if failure is not None and read == failure[0]:
            raise _MappingProbeError(failure[1])
        sequence = self._sequences.get(key)
        if sequence is not None:
            return sequence[min(read - 1, len(sequence) - 1)]
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


class _ExceptionalItemsMapping(_StatefulMapping):
    def items(self) -> object:
        raise _MappingProbeError("ROOT_ITEMS_FAILED")


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


def test_v7_qwen_identity_binds_protocol_and_workspace_endpoint(tmp_path: Path) -> None:
    payload = _payload()
    payload["continuation_version"] = 7
    payload["provider"] = {
        "name": "qwen",
        "model": "qwen3.7-plus",
        "protocol": "openai_responses",
        "base_url": (
            "https://ws1.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        ),
    }
    written = write_continuation(tmp_path.resolve(), payload)
    assert written.payload["provider"] == payload["provider"]

    for field, value in (
        ("protocol", "openai_chat_completions"),
        ("base_url", "https://example.com/compatible-mode/v1"),
    ):
        tampered = json.loads(json.dumps(payload))
        tampered["provider"][field] = value
        with pytest.raises(ContinuationError, match="CONTINUATION_INVALID"):
            write_continuation(tmp_path.resolve(), tampered)


def test_v8_provider_identity_binds_region_to_the_reviewed_endpoint(
    tmp_path: Path,
) -> None:
    payload = _payload("run_qwen_region")
    payload["continuation_version"] = 8
    payload["provider"] = {
        "name": "qwen",
        "model": "qwen3.7-plus",
        "protocol": "openai_responses",
        "region": "ap-southeast-1",
        "base_url": (
            "https://workspace-sg.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
        ),
    }

    written = write_continuation(tmp_path.resolve(), payload)

    assert written.payload["provider"] == payload["provider"]
    for field, value in (
        ("region", "cn-beijing"),
        (
            "base_url",
            "https://workspace-sg.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        ),
    ):
        tampered = json.loads(json.dumps(payload))
        tampered["provider"][field] = value
        with pytest.raises(ContinuationError, match="CONTINUATION_INVALID"):
            write_continuation(tmp_path.resolve(), tampered)


def test_v8_fixed_endpoint_region_identity_rejects_cross_region_recovery(
    tmp_path: Path,
) -> None:
    payload = _payload("run_minimax_global")
    payload["continuation_version"] = 8
    payload["provider"] = {
        "name": "minimax",
        "model": "MiniMax-M2.7",
        "protocol": "anthropic_messages",
        "region": "global",
        "base_url": "https://api.minimax.io/anthropic",
    }
    payload["provider_state"] = {"messages": []}

    assert write_continuation(tmp_path.resolve(), payload).payload["provider"] == payload[
        "provider"
    ]

    payload["provider"] = {
        **payload["provider"],
        "region": "cn",
    }
    with pytest.raises(ContinuationError, match="CONTINUATION_INVALID"):
        write_continuation(tmp_path.resolve(), payload)


def test_v8_local_openai_identity_accepts_only_a_loopback_v1_endpoint(
    tmp_path: Path,
) -> None:
    payload = _payload("run_local")
    payload["continuation_version"] = 8
    payload["provider"] = {
        "name": "local_openai",
        "model": "qwen3:8b",
        "protocol": "openai_chat_completions",
        "region": "local",
        "base_url": "http://127.0.0.1:11434/v1",
    }
    payload["provider_state"] = {"messages": []}

    written = write_continuation(tmp_path.resolve(), payload)
    assert written.payload["provider"] == payload["provider"]

    tampered = json.loads(json.dumps(payload))
    tampered["provider"]["base_url"] = "http://192.168.1.20:11434/v1"
    with pytest.raises(ContinuationError, match="CONTINUATION_INVALID"):
        write_continuation(tmp_path.resolve(), tampered)


def test_v7_chat_provider_uses_local_message_state(tmp_path: Path) -> None:
    payload = _payload("run_kimi")
    payload["continuation_version"] = 7
    payload["provider"] = {
        "name": "kimi",
        "model": "kimi-k2.6",
        "protocol": "openai_chat_completions",
        "base_url": "https://api.moonshot.ai/v1",
    }
    payload["provider_state"] = {
        "messages": [
            {"role": "user", "content": "Inspect the window"},
            {"role": "assistant", "content": "done"},
        ]
    }
    written = write_continuation(tmp_path.resolve(), payload)
    assert written.payload["provider_state"] == payload["provider_state"]


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
    ("field", "second_read", "accepted"),
    [
        ("model_turns_used", 2, True),
        ("model_turns_used", 4, False),
        ("max_model_turns", 2, True),
        ("max_model_turns", 0, False),
    ],
)
def test_budget_comparison_preserves_stateful_uint_results(
    field: str, second_read: int, accepted: bool
) -> None:
    payload = _payload()
    payload["payload_digest"] = "0" * 64
    budget = payload["budget"]
    assert isinstance(budget, dict)
    payload["budget"] = _StatefulMapping(
        budget,
        sequences={field: (budget[field], second_read, second_read)},
    )

    if not accepted:
        with pytest.raises(ContinuationError, match="^CONTINUATION_INVALID$"):
            ContinuationEnvelope.from_payload(payload, now=NOW, verify_digest=False)
        return

    envelope = ContinuationEnvelope.from_payload(
        payload, now=NOW, verify_digest=False
    )
    stored_budget = envelope.payload["budget"]
    assert isinstance(stored_budget, dict)
    assert stored_budget[field] == second_read


@pytest.mark.parametrize(
    "second_read",
    [False, -1, 1.5, "9", [1], None, {"unexpected": 1}, (1,)],
)
@pytest.mark.parametrize("field", ["model_turns_used", "max_model_turns"])
def test_budget_comparison_rejects_stateful_non_uint_second_reads(
    field: str,
    second_read: object,
) -> None:
    payload = _payload()
    payload["payload_digest"] = "0" * 64
    budget = payload["budget"]
    assert isinstance(budget, dict)
    payload["budget"] = _StatefulMapping(
        budget,
        sequences={field: (budget[field], second_read, second_read)},
    )

    with pytest.raises(ContinuationError, match="^CONTINUATION_INVALID$"):
        ContinuationEnvelope.from_payload(payload, now=NOW, verify_digest=False)


def test_budget_comparison_reads_both_values_before_narrowing() -> None:
    payload = _payload()
    payload["payload_digest"] = "0" * 64
    budget = payload["budget"]
    observation = payload["observation"]
    assert isinstance(budget, dict) and isinstance(observation, dict)
    payload["budget"] = _StatefulMapping(
        budget,
        sequences={"model_turns_used": (1, False)},
        failures={"max_model_turns": (2, "RIGHT_MAXIMUM_FAILED")},
    )
    observation["verified_epoch"] = 2

    with pytest.raises(_MappingProbeError, match="^RIGHT_MAXIMUM_FAILED$"):
        ContinuationEnvelope.from_payload(payload, now=NOW, verify_digest=False)


def test_stable_custom_mappings_preserve_canonical_persisted_bytes(
    tmp_path: Path,
) -> None:
    payload = _payload()
    ordinary_state = (tmp_path / "ordinary").resolve()
    custom_state = (tmp_path / "custom").resolve()

    ordinary = write_continuation(ordinary_state, payload)
    custom = write_continuation(custom_state, _StatefulMapping(payload))

    assert custom == ordinary
    assert continuation_path(custom_state, "run_1").read_bytes() == continuation_path(
        ordinary_state, "run_1"
    ).read_bytes()


def test_canonical_root_narrowing_preserves_mapping_items_failure() -> None:
    payload = _payload()
    payload["payload_digest"] = "0" * 64

    with pytest.raises(_MappingProbeError, match="^ROOT_ITEMS_FAILED$"):
        ContinuationEnvelope.from_payload(
            _ExceptionalItemsMapping(payload), now=NOW, verify_digest=False
        )


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
