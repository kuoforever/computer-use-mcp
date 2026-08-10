"""Strict, private persisted-continuation envelope.

This module deliberately has no runner or provider integration.  Reading a
valid envelope does not make a run resumable or perform external I/O.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from base64 import b64encode
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping

from .provider_catalog import (
    ProviderProtocol,
    provider_profile,
    resolve_provider_base_url,
)
from .reconstruction import (
    OperationEffect,
    OperationKind,
    OperationRecord,
    OperationResult,
    OperationStage,
    OperationState,
)
from .types import JSONValue, ModelTurn, RunState, ToolCall, ToolEffect, ToolResult, to_json_value


CONTINUATION_VERSION = 7
LEGACY_CONTINUATION_VERSION = 6
MAX_CONTINUATION_BYTES = 48 * 1024 * 1024
MAX_LEDGER_EVENTS = 512
MAX_JSON_DEPTH = 32
_RUN_ID = __import__("re").compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_TOP_LEVEL_FIELDS = frozenset(
    {
        "continuation_version",
        "run_id",
        "checkpoint_sequence",
        "policy_version",
        "provider",
        "registry_digest",
        "advertised_tool_names",
        "task",
        "budget",
        "observation",
        "ledger",
        "boundary",
        "provider_state",
        "created_at",
        "expires_at",
        "payload_digest",
    }
)
_BUDGET_FIELDS = frozenset(
    {
        "max_model_turns",
        "max_tool_calls",
        "max_side_effects",
        "max_input_tokens",
        "model_turns_used",
        "tool_calls_used",
        "side_effects_used",
        "input_tokens_used",
    }
)
_LEDGER_KINDS = frozenset(
    {
        "user_task",
        "model_turn",
        "tool_call",
        "tool_result",
        "policy_decision",
        "observation",
        "recovery",
    }
)


class ContinuationError(RuntimeError):
    """Fixed persistence failure that never embeds sensitive content."""


def _object(value: object, fields: frozenset[str], code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ContinuationError(code)
    return value


def _nonempty(value: object, *, maximum: int, code: str) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContinuationError(code)
    return value


def _uint(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContinuationError(code)
    return value


def _digest(value: object, code: str) -> str:
    text = _nonempty(value, maximum=64, code=code)
    if len(text) != 64:
        raise ContinuationError(code)
    try:
        int(text, 16)
    except ValueError as exc:
        raise ContinuationError(code) from exc
    return text.lower()


def _reviewed_tool_names() -> tuple[str, ...]:
    from .tool_registry import ALL_REVIEWED_TOOLS

    return tuple(tool.name for tool in ALL_REVIEWED_TOOLS)


def _persisted_advertised_tool_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
        raise ContinuationError("CONTINUATION_INVALID")
    supplied = tuple(value)
    supplied_set = frozenset(supplied)
    canonical = tuple(name for name in _reviewed_tool_names() if name in supplied_set)
    if len(supplied) != len(supplied_set) or supplied != canonical:
        raise ContinuationError("CONTINUATION_INVALID")
    return supplied


def _timestamp(value: object, code: str) -> datetime:
    text = _nonempty(value, maximum=64, code=code)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContinuationError(code) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContinuationError(code)
    return parsed.astimezone(UTC)


def _validate_json(value: object, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ContinuationError("CONTINUATION_INVALID")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ContinuationError("CONTINUATION_INVALID")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json(item, depth=depth + 1)
        return
    if isinstance(value, Mapping) and all(isinstance(key, str) for key in value):
        for item in value.values():
            _validate_json(item, depth=depth + 1)
        return
    raise ContinuationError("CONTINUATION_INVALID")


def _canonical(payload: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContinuationError("CONTINUATION_INVALID") from exc


def _payload_digest(payload: Mapping[str, object]) -> str:
    unsigned = {key: value for key, value in payload.items() if key != "payload_digest"}
    return hashlib.sha256(_canonical(unsigned)).hexdigest()


def _is_unsafe_path(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse)


@dataclass(frozen=True)
class ContinuationEnvelope:
    """Validated v7 or legacy v6 recovery data; never executable authority."""

    payload: Mapping[str, JSONValue]

    @property
    def operation_state(self) -> OperationState:
        """Return the non-executable operation snapshot at the durable boundary."""

        boundary = self.payload["boundary"]
        assert isinstance(boundary, Mapping)
        kind = OperationKind(str(boundary["operation_kind"]))
        stage = OperationStage(str(boundary["stage"]))
        raw_effect = boundary["effect"]
        effect = (
            OperationEffect(str(raw_effect))
            if kind is OperationKind.TOOL and raw_effect is not None
            else None
        )
        result = None
        if stage is OperationStage.COMPLETED:
            completed_status = None
            if kind is OperationKind.TOOL:
                ledger = self.payload["ledger"]
                assert isinstance(ledger, list)
                for raw_event in reversed(ledger):
                    if not isinstance(raw_event, Mapping) or raw_event.get("kind") != "tool_result":
                        continue
                    data = raw_event.get("data")
                    if isinstance(data, Mapping) and isinstance(data.get("status"), str):
                        completed_status = data["status"]
                    break
            result = (
                OperationResult.UNKNOWN_OUTCOME
                if boundary["dispatch"] == "unknown"
                or completed_status == "unknown_outcome"
                else OperationResult.SUCCESS
            )
        return OperationState(
            operation_id=str(boundary["operation_id"]),
            kind=kind,
            stage=stage,
            effect=effect,
            result=result,
        )

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        *,
        expected_run_id: str | None = None,
        now: datetime | None = None,
        verify_digest: bool = True,
    ) -> "ContinuationEnvelope":
        if not isinstance(payload, Mapping):
            raise ContinuationError("CONTINUATION_INVALID")
        version = payload.get("continuation_version")
        if isinstance(version, bool) or not isinstance(version, int):
            raise ContinuationError("CONTINUATION_INVALID")
        if version not in {LEGACY_CONTINUATION_VERSION, CONTINUATION_VERSION}:
            raise ContinuationError("CONTINUATION_VERSION_UNSUPPORTED")
        root = _object(payload, _TOP_LEVEL_FIELDS, "CONTINUATION_INVALID")
        run_id = _nonempty(root.get("run_id"), maximum=128, code="CONTINUATION_INVALID")
        if _RUN_ID.fullmatch(run_id) is None or (
            expected_run_id is not None and run_id != expected_run_id
        ):
            raise ContinuationError("CONTINUATION_IDENTITY_MISMATCH")
        _uint(root.get("checkpoint_sequence"), "CONTINUATION_INVALID")
        _nonempty(root.get("policy_version"), maximum=128, code="CONTINUATION_INVALID")
        _digest(root.get("registry_digest"), "CONTINUATION_INVALID")
        _persisted_advertised_tool_names(root.get("advertised_tool_names"))
        task = _nonempty(
            root.get("task"), maximum=1_000_000, code="CONTINUATION_INVALID"
        )

        provider_fields = (
            frozenset({"name", "model"})
            if version == LEGACY_CONTINUATION_VERSION
            else frozenset({"name", "model", "protocol", "base_url"})
        )
        provider = _object(root.get("provider"), provider_fields, "CONTINUATION_INVALID")
        provider_name = provider.get("name")
        if not isinstance(provider_name, str):
            raise ContinuationError("CONTINUATION_INVALID")
        try:
            profile = provider_profile(provider_name)
        except ValueError as exc:
            raise ContinuationError("CONTINUATION_INVALID") from exc
        if version == LEGACY_CONTINUATION_VERSION:
            if provider_name not in {"openai", "anthropic"}:
                raise ContinuationError("CONTINUATION_INVALID")
        else:
            base_url = provider.get("base_url")
            if (
                provider.get("protocol") != profile.protocol.value
                or not isinstance(base_url, str)
            ):
                raise ContinuationError("CONTINUATION_INVALID")
            try:
                expected_base_url = (
                    resolve_provider_base_url(provider_name, base_url)
                    if profile.requires_configured_base_url
                    else profile.fixed_base_url
                )
            except ValueError as exc:
                raise ContinuationError("CONTINUATION_INVALID") from exc
            if base_url != expected_base_url:
                raise ContinuationError("CONTINUATION_INVALID")
        _nonempty(provider.get("model"), maximum=256, code="CONTINUATION_INVALID")

        budget = _object(root.get("budget"), _BUDGET_FIELDS, "CONTINUATION_INVALID")
        for name in _BUDGET_FIELDS:
            _uint(budget.get(name), "CONTINUATION_INVALID")
        for used, maximum in (
            ("model_turns_used", "max_model_turns"),
            ("tool_calls_used", "max_tool_calls"),
            ("side_effects_used", "max_side_effects"),
        ):
            if budget[used] > budget[maximum]:
                raise ContinuationError("CONTINUATION_INVALID")

        observation = _object(
            root.get("observation"),
            frozenset({"epoch", "verified_epoch", "mcp_generation"}),
            "CONTINUATION_INVALID",
        )
        epoch = _uint(observation.get("epoch"), "CONTINUATION_INVALID")
        verified = observation.get("verified_epoch")
        if verified is not None and _uint(verified, "CONTINUATION_INVALID") > epoch:
            raise ContinuationError("CONTINUATION_INVALID")
        _uint(observation.get("mcp_generation"), "CONTINUATION_INVALID")

        ledger = root.get("ledger")
        if not isinstance(ledger, list) or len(ledger) > MAX_LEDGER_EVENTS:
            raise ContinuationError("CONTINUATION_INVALID")
        event_ids: set[str] = set()
        for event in ledger:
            item = _object(
                event, frozenset({"kind", "event_id", "data"}), "CONTINUATION_INVALID"
            )
            if item.get("kind") not in _LEDGER_KINDS:
                raise ContinuationError("CONTINUATION_INVALID")
            event_id = _nonempty(
                item.get("event_id"), maximum=256, code="CONTINUATION_INVALID"
            )
            if event_id in event_ids or not isinstance(item.get("data"), Mapping):
                raise ContinuationError("CONTINUATION_INVALID")
            event_ids.add(event_id)
            _validate_json(item["data"])
            if _contains_raw_type_text(item["data"]):
                raise ContinuationError("CONTINUATION_SENSITIVE_FIELD")

        boundary = _object(
            root.get("boundary"),
            frozenset(
                {"operation_kind", "stage", "operation_id", "effect", "dispatch", "next_step"}
            ),
            "CONTINUATION_INVALID",
        )
        if boundary.get("operation_kind") not in {"provider", "tool"}:
            raise ContinuationError("CONTINUATION_INVALID")
        if boundary.get("stage") not in {"prepared", "dispatch_intent", "completed"}:
            raise ContinuationError("CONTINUATION_INVALID")
        _nonempty(boundary.get("operation_id"), maximum=384, code="CONTINUATION_INVALID")
        if boundary.get("effect") not in {None, "observation", "side_effect"}:
            raise ContinuationError("CONTINUATION_INVALID")
        if boundary.get("dispatch") not in {
            None,
            "not_dispatched",
            "dispatched",
            "unknown",
        }:
            raise ContinuationError("CONTINUATION_INVALID")
        if boundary.get("next_step") not in {
            "provider_continue",
            "dispatch_observation",
            "mandatory_reobserve",
            "stop",
        }:
            raise ContinuationError("CONTINUATION_INVALID")
        stage = boundary["stage"]
        dispatch = boundary["dispatch"]
        effect = boundary["effect"]
        kind = boundary["operation_kind"]
        if (
            (stage == "prepared" and dispatch != "not_dispatched")
            or (stage == "dispatch_intent" and dispatch != "unknown")
            or (stage == "completed" and dispatch not in {"dispatched", "unknown"})
            or (kind == "tool" and effect is None)
            or (kind == "provider" and stage != "completed" and effect is not None)
        ):
            raise ContinuationError("CONTINUATION_INVALID")

        provider_state = root.get("provider_state")
        if not isinstance(provider_state, Mapping):
            raise ContinuationError("CONTINUATION_INVALID")
        _validate_json(provider_state)
        if profile.protocol is ProviderProtocol.OPENAI_RESPONSES:
            openai_state = _object(
                provider_state,
                frozenset(
                    {
                        "response_id",
                        "prior_context_tokens",
                        "request_contract_digest",
                        "memory_context_used",
                        "initial_input",
                        "output_batches",
                    }
                ),
                "CONTINUATION_INVALID",
            )
            response_id = openai_state["response_id"]
            contract_digest = openai_state["request_contract_digest"]
            memory_context_used = openai_state["memory_context_used"]
            initial_input = openai_state["initial_input"]
            output_batches = openai_state["output_batches"]
            if not isinstance(memory_context_used, bool):
                raise ContinuationError("CONTINUATION_INVALID")
            if response_id is not None:
                _nonempty(response_id, maximum=256, code="CONTINUATION_INVALID")
                _digest(contract_digest, "CONTINUATION_INVALID")
                _nonempty(
                    initial_input, maximum=2_000_000, code="CONTINUATION_INVALID"
                )
                _validate_openai_initial_input(
                    task, initial_input, memory_context_used
                )
                _validate_openai_output_batches(output_batches, response_id)
            elif (
                contract_digest is not None
                or memory_context_used
                or initial_input is not None
                or output_batches != []
            ):
                raise ContinuationError("CONTINUATION_INVALID")
            prior_context_tokens = _uint(
                openai_state["prior_context_tokens"], "CONTINUATION_INVALID"
            )
            if response_id is None and prior_context_tokens != 0:
                raise ContinuationError("CONTINUATION_INVALID")
        else:
            anthropic_state = _object(
                provider_state, frozenset({"messages"}), "CONTINUATION_INVALID"
            )
            messages = anthropic_state["messages"]
            if not isinstance(messages, list) or len(messages) > 512:
                raise ContinuationError("CONTINUATION_INVALID")
        created = _timestamp(root.get("created_at"), "CONTINUATION_INVALID")
        expires = _timestamp(root.get("expires_at"), "CONTINUATION_INVALID")
        if expires <= created:
            raise ContinuationError("CONTINUATION_INVALID")
        current = datetime.now(UTC) if now is None else now.astimezone(UTC)
        if expires <= current:
            raise ContinuationError("CONTINUATION_EXPIRED")
        supplied_digest = _digest(root.get("payload_digest"), "CONTINUATION_INVALID")
        if verify_digest and supplied_digest != _payload_digest(root):
            raise ContinuationError("CONTINUATION_DIGEST_MISMATCH")
        return cls(to_json_value(root))


def _validate_openai_initial_input(
    task: str, initial_input: object, memory_context_used: bool
) -> None:
    if not isinstance(initial_input, str):
        raise ContinuationError("CONTINUATION_INVALID")
    if not memory_context_used:
        if initial_input != task:
            raise ContinuationError("CONTINUATION_INVALID")
        return
    prefix = task + "\n\nOptional memory context (JSON data):\n"
    if not initial_input.startswith(prefix):
        raise ContinuationError("CONTINUATION_INVALID")
    encoded = initial_input[len(prefix) :]
    try:
        memories = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise ContinuationError("CONTINUATION_INVALID") from exc
    if (
        not isinstance(memories, list)
        or not memories
        or len(memories) > 8
        or json.dumps(memories, separators=(",", ":"), sort_keys=True) != encoded
    ):
        raise ContinuationError("CONTINUATION_INVALID")
    total_content = 0
    for value in memories:
        item = _object(
            value,
            frozenset({"kind", "content", "source", "scope"}),
            "CONTINUATION_INVALID",
        )
        if item["kind"] not in {"preference", "verified_procedure"}:
            raise ContinuationError("CONTINUATION_INVALID")
        content = _nonempty(
            item["content"], maximum=4096, code="CONTINUATION_INVALID"
        )
        if any(ord(char) < 32 for char in content):
            raise ContinuationError("CONTINUATION_INVALID")
        total_content += len(content)
        if item["source"] != "user_confirmed":
            raise ContinuationError("CONTINUATION_INVALID")
        _nonempty(item["scope"], maximum=128, code="CONTINUATION_INVALID")
    if total_content > 8192:
        raise ContinuationError("CONTINUATION_INVALID")


def _validate_openai_output_batches(value: object, response_id: object) -> None:
    if not isinstance(value, list) or not value or len(value) > 64:
        raise ContinuationError("CONTINUATION_INVALID")
    response_ids: list[str] = []
    for raw_batch in value:
        batch = _object(
            raw_batch,
            frozenset({"response_id", "items"}),
            "CONTINUATION_INVALID",
        )
        batch_response_id = _nonempty(
            batch["response_id"], maximum=256, code="CONTINUATION_INVALID"
        )
        if batch_response_id in response_ids:
            raise ContinuationError("CONTINUATION_INVALID")
        response_ids.append(batch_response_id)
        items = batch["items"]
        if not isinstance(items, list) or len(items) > 256:
            raise ContinuationError("CONTINUATION_INVALID")
        for raw_item in items:
            if not isinstance(raw_item, Mapping):
                raise ContinuationError("CONTINUATION_INVALID")
            _nonempty(raw_item.get("type"), maximum=128, code="CONTINUATION_INVALID")
    if response_ids[-1] != response_id:
        raise ContinuationError("CONTINUATION_INVALID")


def _contains_raw_type_text(data: object) -> bool:
    if not isinstance(data, Mapping):
        return False
    if data.get("tool_name") == "type":
        arguments = data.get("arguments")
        if isinstance(arguments, Mapping) and "text" in arguments:
            return True
    tool_calls = data.get("tool_calls")
    return isinstance(tool_calls, list) and any(
        _contains_raw_type_text(call) for call in tool_calls
    )


def continuation_path(state_dir: Path, run_id: str) -> Path:
    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ValueError("run_id must be a path-safe identifier")
    return state_dir / "runs" / run_id / "continuation.json"


def write_continuation(state_dir: Path, payload: Mapping[str, object]) -> ContinuationEnvelope:
    """Validate and atomically write a private envelope; never enables resume."""
    if not isinstance(payload, Mapping):
        raise ValueError("payload must be a mapping")
    unsigned = dict(payload)
    unsigned.pop("payload_digest", None)
    unsigned["payload_digest"] = _payload_digest(unsigned)
    envelope = ContinuationEnvelope.from_payload(unsigned)
    encoded = _canonical(envelope.payload) + b"\n"
    if len(encoded) > MAX_CONTINUATION_BYTES:
        raise ContinuationError("CONTINUATION_TOO_LARGE")
    path = continuation_path(state_dir, str(envelope.payload["run_id"]))
    if _is_unsafe_path(state_dir / "runs") or _is_unsafe_path(path.parent) or _is_unsafe_path(path):
        raise ContinuationError("CONTINUATION_UNSAFE_PATH")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".continuation-", suffix=".tmp", dir=path.parent
        )
        temporary = Path(raw_path)
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(descriptor, "wb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        temporary = None
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        raise ContinuationError("CONTINUATION_WRITE_FAILED") from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass
    return envelope


def read_continuation(
    state_dir: Path, run_id: str, *, now: datetime | None = None
) -> ContinuationEnvelope:
    """Read and strictly validate one bounded private envelope."""
    path = continuation_path(state_dir, run_id)
    if _is_unsafe_path(state_dir / "runs") or _is_unsafe_path(path.parent) or _is_unsafe_path(path):
        raise ContinuationError("CONTINUATION_UNSAFE_PATH")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContinuationError("CONTINUATION_READ_FAILED") from exc
    if not data or len(data) > MAX_CONTINUATION_BYTES:
        raise ContinuationError("CONTINUATION_READ_FAILED")
    try:
        payload = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContinuationError("CONTINUATION_READ_FAILED") from exc
    if not isinstance(payload, Mapping):
        raise ContinuationError("CONTINUATION_INVALID")
    return ContinuationEnvelope.from_payload(payload, expected_run_id=run_id, now=now)


def delete_continuation(state_dir: Path, run_id: str) -> None:
    """Delete a terminal run's private continuation without following links."""

    path = continuation_path(state_dir, run_id)
    if _is_unsafe_path(state_dir / "runs") or _is_unsafe_path(path.parent) or _is_unsafe_path(path):
        raise ContinuationError("CONTINUATION_UNSAFE_PATH")
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise ContinuationError("CONTINUATION_DELETE_FAILED") from exc


class RuntimeContinuationRecorder:
    """Build and persist sensitive write-ahead envelopes for one live run."""

    def __init__(
        self,
        *,
        state_dir: Path,
        state: RunState,
        provider_name: str,
        provider_model: str,
        provider_base_url: str | None = None,
        registry_digest: str,
        advertised_tool_names: frozenset[str],
        ttl_seconds: int,
        mcp_generation: int,
    ) -> None:
        try:
            profile = provider_profile(provider_name)
            effective_base_url = (
                resolve_provider_base_url(provider_name, provider_base_url)
                if profile.requires_configured_base_url
                else profile.fixed_base_url
            )
        except ValueError as exc:
            raise ValueError("provider identity must be reviewed") from exc
        if effective_base_url is None:
            raise ValueError("provider endpoint must be reviewed")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 60 <= ttl_seconds <= 86_400
        ):
            raise ValueError("ttl_seconds must be between 60 and 86400")
        self.state_dir = state_dir
        self.run_id = state.run_id
        self.task = state.task
        self.policy_version = state.policy_version
        self.provider_name = provider_name
        self.provider_model = provider_model
        self.provider_protocol = profile.protocol
        self.provider_base_url = effective_base_url
        self.registry_digest = _digest(registry_digest, "CONTINUATION_INVALID")
        if not isinstance(advertised_tool_names, frozenset) or not all(
            isinstance(name, str) for name in advertised_tool_names
        ):
            raise ValueError("advertised_tool_names must be an immutable reviewed-name set")
        canonical_names = tuple(
            name for name in _reviewed_tool_names() if name in advertised_tool_names
        )
        if len(canonical_names) != len(advertised_tool_names):
            raise ValueError("advertised_tool_names must be an immutable reviewed-name set")
        self.advertised_tool_names = canonical_names
        self.mcp_generation = _uint(mcp_generation, "CONTINUATION_INVALID")
        self.ttl_seconds = ttl_seconds
        self.created_at = datetime.now(UTC)
        self.expires_at = self.created_at + timedelta(seconds=ttl_seconds)
        self.ledger: list[dict[str, JSONValue]] = [
            {
                "kind": "user_task",
                "event_id": f"{state.run_id}:recovery:1",
                "data": {"task": state.task},
            }
        ]
        self.provider_state: Mapping[str, JSONValue] = (
            {
                "response_id": None,
                "prior_context_tokens": 0,
                "request_contract_digest": None,
                "memory_context_used": False,
                "initial_input": None,
                "output_batches": [],
            }
            if profile.protocol is ProviderProtocol.OPENAI_RESPONSES
            else {"messages": []}
        )
        self._current: OperationState | None = None
        self._completed_tool_dispatch: str | None = None

    def _event(self, kind: str, data: Mapping[str, object]) -> None:
        self.ledger.append(
            {
                "kind": kind,
                "event_id": f"{self.run_id}:recovery:{len(self.ledger) + 1}",
                "data": to_json_value(data),
            }
        )

    @staticmethod
    def _identity(call: ToolCall | ToolResult) -> dict[str, str]:
        return {
            "run_id": call.identity.run_id,
            "turn_id": call.identity.turn_id,
            "call_id": call.identity.call_id,
        }

    def _provider_state(self) -> dict[str, JSONValue]:
        state = to_json_value(self.provider_state)
        if not isinstance(state, dict):
            raise ContinuationError("CONTINUATION_INVALID")
        return state

    def _payload(
        self,
        state: RunState,
        *,
        checkpoint_sequence: int,
        operation: OperationState,
        pending_effect: ToolEffect | None,
    ) -> dict[str, object]:
        budget = state.budgets
        if operation.stage is OperationStage.PREPARED:
            dispatch = "not_dispatched"
        elif operation.stage is OperationStage.DISPATCH_INTENT:
            dispatch = "unknown"
        elif operation.result is OperationResult.UNKNOWN_OUTCOME:
            dispatch = self._completed_tool_dispatch or "unknown"
        else:
            dispatch = "dispatched"
        effect = operation.effect.value if operation.effect is not None else None
        if operation.kind is OperationKind.PROVIDER and pending_effect is not None:
            effect = pending_effect.value
        if operation.stage is not OperationStage.COMPLETED:
            next_step = "stop"
        elif operation.kind is OperationKind.PROVIDER:
            next_step = "dispatch_observation" if effect == "observation" else "stop"
        elif operation.result is OperationResult.UNKNOWN_OUTCOME:
            next_step = "stop"
        elif effect == "observation":
            next_step = "provider_continue"
        else:
            next_step = "mandatory_reobserve"
        return {
            "continuation_version": CONTINUATION_VERSION,
            "run_id": state.run_id,
            "checkpoint_sequence": checkpoint_sequence,
            "policy_version": state.policy_version,
            "provider": {
                "name": self.provider_name,
                "model": self.provider_model,
                "protocol": self.provider_protocol.value,
                "base_url": self.provider_base_url,
            },
            "registry_digest": self.registry_digest,
            "advertised_tool_names": list(self.advertised_tool_names),
            "task": state.task,
            "budget": {
                "max_model_turns": budget.max_model_turns,
                "max_tool_calls": budget.max_tool_calls,
                "max_side_effects": budget.max_side_effects,
                "max_input_tokens": budget.max_input_tokens,
                "model_turns_used": budget.model_turns_used,
                "tool_calls_used": budget.tool_calls_used,
                "side_effects_used": budget.side_effects_used,
                "input_tokens_used": budget.input_tokens_used,
            },
            "observation": {
                "epoch": state.observation_epoch,
                "verified_epoch": state.verified_observation_epoch,
                "mcp_generation": self.mcp_generation,
            },
            "ledger": self.ledger,
            "boundary": {
                "operation_kind": operation.kind.value,
                "stage": operation.stage.value,
                "operation_id": operation.operation_id,
                "effect": effect,
                "dispatch": dispatch,
                "next_step": next_step,
            },
            "provider_state": self._provider_state(),
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }

    def _write(
        self,
        state: RunState,
        *,
        checkpoint_sequence: int,
        pending_effect: ToolEffect | None = None,
    ) -> ContinuationEnvelope:
        if state.run_id != self.run_id or state.task != self.task:
            raise ContinuationError("CONTINUATION_IDENTITY_MISMATCH")
        if self._current is None:
            raise ContinuationError("CONTINUATION_INVALID")
        self.expires_at = datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
        return write_continuation(
            self.state_dir,
            self._payload(
                state,
                checkpoint_sequence=checkpoint_sequence,
                operation=self._current,
                pending_effect=pending_effect,
            ),
        )

    def prepare_provider(
        self, state: RunState, turn_id: str, *, checkpoint_sequence: int
    ) -> ContinuationEnvelope:
        operation_id = f"{state.run_id}:{turn_id}:provider"
        self._completed_tool_dispatch = None
        self._current = OperationState.prepare(operation_id, OperationKind.PROVIDER)
        return self._write(state, checkpoint_sequence=checkpoint_sequence)

    def dispatch_provider(
        self, state: RunState, *, checkpoint_sequence: int
    ) -> ContinuationEnvelope:
        if self._current is None:
            raise ContinuationError("CONTINUATION_INVALID")
        self._current = self._current.apply(
            OperationRecord(
                self._current.operation_id,
                OperationKind.PROVIDER,
                OperationStage.DISPATCH_INTENT,
            )
        )
        return self._write(state, checkpoint_sequence=checkpoint_sequence)

    def complete_provider(
        self,
        state: RunState,
        turn: ModelTurn,
        *,
        provider_state: Mapping[str, JSONValue],
        checkpoint_sequence: int,
    ) -> ContinuationEnvelope:
        if self._current is None:
            raise ContinuationError("CONTINUATION_INVALID")
        self._current = self._current.apply(
            OperationRecord(
                self._current.operation_id,
                OperationKind.PROVIDER,
                OperationStage.COMPLETED,
                result=OperationResult.SUCCESS,
            )
        )
        self.provider_state = provider_state
        self._event(
            "model_turn",
            {
                "run_id": turn.run_id,
                "turn_id": turn.turn_id,
                "provider_response_id": turn.provider_response_id,
                "text": turn.text,
                "usage": {
                    "input_tokens": turn.usage.input_tokens,
                    "output_tokens": turn.usage.output_tokens,
                },
                "tool_calls": [
                    {
                        "identity": self._identity(call),
                        "tool_name": call.name,
                        "arguments": to_json_value(call.arguments),
                        "call_digest": call.digest,
                    }
                    for call in turn.tool_calls
                ],
            },
        )
        effects = [getattr(call, "name", "") for call in turn.tool_calls]
        pending = None
        if effects:
            from .tool_registry import get_tool_spec

            pending = (
                ToolEffect.OBSERVATION
                if all(get_tool_spec(name).effect is ToolEffect.OBSERVATION for name in effects)
                else ToolEffect.SIDE_EFFECT
            )
        return self._write(
            state, checkpoint_sequence=checkpoint_sequence, pending_effect=pending
        )

    def prepare_tool(
        self,
        state: RunState,
        call: ToolCall,
        *,
        effect: ToolEffect,
        checkpoint_sequence: int,
    ) -> ContinuationEnvelope:
        self._completed_tool_dispatch = None
        self._current = OperationState.prepare(
            f"{call.identity.run_id}:{call.identity.turn_id}:{call.identity.call_id}",
            OperationKind.TOOL,
            effect=OperationEffect(effect.value),
        )
        self._event(
            "tool_call",
            {
                "identity": self._identity(call),
                "tool_name": call.name,
                "arguments": to_json_value(call.arguments),
                "call_digest": call.digest,
                "effect": effect.value,
            },
        )
        return self._write(state, checkpoint_sequence=checkpoint_sequence)

    def dispatch_tool(
        self, state: RunState, *, checkpoint_sequence: int
    ) -> ContinuationEnvelope:
        if self._current is None or self._current.kind is not OperationKind.TOOL:
            raise ContinuationError("CONTINUATION_INVALID")
        self._current = self._current.apply(
            OperationRecord(
                self._current.operation_id,
                OperationKind.TOOL,
                OperationStage.DISPATCH_INTENT,
                self._current.effect,
            )
        )
        return self._write(state, checkpoint_sequence=checkpoint_sequence)

    def complete_tool(
        self, state: RunState, result: ToolResult, *, checkpoint_sequence: int
    ) -> ContinuationEnvelope:
        if self._current is None or self._current.kind is not OperationKind.TOOL:
            raise ContinuationError("CONTINUATION_INVALID")
        outcome = (
            OperationResult.UNKNOWN_OUTCOME
            if result.status.value == "unknown_outcome"
            else OperationResult.SUCCESS if result.ok else OperationResult.ERROR
        )
        self._completed_tool_dispatch = (
            result.dispatch.value
            if outcome is OperationResult.UNKNOWN_OUTCOME
            else None
        )
        self._current = self._current.apply(
            OperationRecord(
                self._current.operation_id,
                OperationKind.TOOL,
                OperationStage.COMPLETED,
                self._current.effect,
                outcome,
            )
        )
        self._event(
            "tool_result",
            {
                "identity": self._identity(result),
                "tool_name": result.tool_name,
                "status": result.status.value,
                "dispatch": result.dispatch.value,
                "code": result.code,
                "sanitized_text": result.sanitized_text,
                "images": [
                    {
                        "mime_type": image.mime_type,
                        "data": b64encode(image.data).decode("ascii"),
                        "width": image.width,
                        "height": image.height,
                    }
                    for image in result.images
                ],
            },
        )
        return self._write(state, checkpoint_sequence=checkpoint_sequence)

    def close(self) -> None:
        delete_continuation(self.state_dir, self.run_id)


__all__ = [
    "CONTINUATION_VERSION",
    "MAX_CONTINUATION_BYTES",
    "ContinuationEnvelope",
    "ContinuationError",
    "RuntimeContinuationRecorder",
    "continuation_path",
    "delete_continuation",
    "read_continuation",
    "write_continuation",
]
