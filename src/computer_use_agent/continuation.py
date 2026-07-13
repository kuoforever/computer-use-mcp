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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Mapping

from .types import JSONValue, to_json_value


CONTINUATION_VERSION = 1
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
    """Validated v1 recovery data, still non-authoritative and non-executable."""

    payload: Mapping[str, JSONValue]

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, object],
        *,
        expected_run_id: str | None = None,
        now: datetime | None = None,
        verify_digest: bool = True,
    ) -> "ContinuationEnvelope":
        root = _object(payload, _TOP_LEVEL_FIELDS, "CONTINUATION_INVALID")
        if root.get("continuation_version") != CONTINUATION_VERSION:
            raise ContinuationError("CONTINUATION_VERSION_UNSUPPORTED")
        run_id = _nonempty(root.get("run_id"), maximum=128, code="CONTINUATION_INVALID")
        if _RUN_ID.fullmatch(run_id) is None or (
            expected_run_id is not None and run_id != expected_run_id
        ):
            raise ContinuationError("CONTINUATION_IDENTITY_MISMATCH")
        _uint(root.get("checkpoint_sequence"), "CONTINUATION_INVALID")
        _nonempty(root.get("policy_version"), maximum=128, code="CONTINUATION_INVALID")
        _digest(root.get("registry_digest"), "CONTINUATION_INVALID")
        _nonempty(root.get("task"), maximum=1_000_000, code="CONTINUATION_INVALID")

        provider = _object(
            root.get("provider"), frozenset({"name", "model"}), "CONTINUATION_INVALID"
        )
        if provider.get("name") not in {"openai", "anthropic"}:
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
            if item["kind"] == "tool_call" and _contains_raw_type_text(item["data"]):
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

        provider_state = root.get("provider_state")
        if not isinstance(provider_state, Mapping):
            raise ContinuationError("CONTINUATION_INVALID")
        _validate_json(provider_state)
        if provider["name"] == "openai":
            openai_state = _object(
                provider_state, frozenset({"response_id"}), "CONTINUATION_INVALID"
            )
            response_id = openai_state["response_id"]
            if response_id is not None:
                _nonempty(response_id, maximum=256, code="CONTINUATION_INVALID")
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


def _contains_raw_type_text(data: object) -> bool:
    if not isinstance(data, Mapping) or data.get("tool_name") != "type":
        return False
    arguments = data.get("arguments")
    return isinstance(arguments, Mapping) and "text" in arguments


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


__all__ = [
    "CONTINUATION_VERSION",
    "MAX_CONTINUATION_BYTES",
    "ContinuationEnvelope",
    "ContinuationError",
    "continuation_path",
    "read_continuation",
    "write_continuation",
]
