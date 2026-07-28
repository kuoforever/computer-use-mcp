"""Bounded, redacted exports for the external LLM Full Cycle project."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from computer_use_mcp.contract import CONTRACT_VERSION as DRIVER_CONTRACT_VERSION

from .planning import PLAN_CONTRACT_VERSION
from .tool_registry import REVIEWED_TOOLS
from .trace import CHECKPOINT_VERSION, TRACE_VERSION, read_run_record
from .types import AGENT_CONTRACT_VERSION, JSONValue, to_json_value

FULLCYCLE_MANIFEST_VERSION = 1
FULLCYCLE_RUN_EXPORT_VERSION = 1
FULLCYCLE_DATA_CLASS = "redacted_runtime_evidence"
FULLCYCLE_TRAINING_USE = "reliability_and_verifier_only"
MAX_FULLCYCLE_OUTPUT_BYTES = 24 * 1024 * 1024
_CHECKPOINT_FIELDS = frozenset(
    {
        "checkpoint_version",
        "checkpoint_sequence",
        "run_id",
        "phase",
        "policy_version",
        "recovery_status",
        "task_length",
        "observation_epoch",
        "verified_observation_epoch",
        "event_count",
        "budgets",
        "updated_at",
        "created_at",
        "metrics",
        "failure_code",
        "final_text_length",
        "resume_allowed",
        "recovery_action",
    }
)
_BUDGET_FIELDS = frozenset(
    {
        "max_model_turns",
        "max_tool_calls",
        "max_side_effects",
        "model_turns_used",
        "tool_calls_used",
        "side_effects_used",
        "max_input_tokens",
        "input_tokens_used",
    }
)
_METRIC_FIELDS = frozenset(
    {
        "model_calls",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "provider_latency_ms",
        "tool_latency_ms",
        "tool_failures",
        "image_results",
        "screenshot_results",
        "provider_usage_report_count",
        "retry_count",
        "run_duration_ms",
    }
)
_EVENT_BASE_FIELDS = frozenset({"trace_version", "sequence", "run_id", "kind"})
_EVENT_FIELDS = {
    "user_task": frozenset({"task_length"}),
    "model_turn": frozenset(
        {"text_length", "tool_call_count", "input_tokens", "output_tokens", "latency_ms"}
    ),
    "tool_call": frozenset({"tool", "arguments", "redacted_fields"}),
    "tool_result": frozenset(
        {"tool", "status", "dispatch", "text_length", "image_count", "latency_ms", "code"}
    ),
    "observation": frozenset({"tool", "observation_epoch"}),
    "policy_decision": frozenset({"decision"}),
    "recovery": frozenset({"status"}),
}
_FORBIDDEN_RICH_FIELDS = frozenset(
    {
        "task",
        "raw_task",
        "model_text",
        "tool_result",
        "tool_result_text",
        "screenshot",
        "screenshots",
        "image",
        "images",
        "image_bytes",
        "memory",
        "continuation",
        "response",
        "content",
        "text",
    }
)


def canonical_json_bytes(payload: Mapping[str, JSONValue]) -> bytes:
    """Encode one deterministic JSON object without presentation whitespace."""

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_fullcycle_manifest() -> dict[str, JSONValue]:
    """Derive the public Full Cycle runtime manifest from reviewed contracts."""

    tools: list[JSONValue] = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": to_json_value(tool.input_schema),
            "effect": tool.effect.value,
            "result_content": tool.result_content.value,
            "result_sensitivity": tool.result_sensitivity.value,
            "redaction_policy": tool.redaction_policy.value,
            "grounding": tool.grounding.value,
            "requires_host_approval": tool.requires_host_approval,
            "invalidates_observation": tool.invalidates_observation,
            "sensitive_arguments": list(tool.sensitive_arguments),
            "required_safety_baselines": list(tool.required_safety_baselines),
        }
        for tool in REVIEWED_TOOLS
    ]
    return {
        "fullcycle_manifest_version": FULLCYCLE_MANIFEST_VERSION,
        "agent_contract_version": AGENT_CONTRACT_VERSION,
        "driver_contract_version": DRIVER_CONTRACT_VERSION,
        "trace_version": TRACE_VERSION,
        "checkpoint_version": CHECKPOINT_VERSION,
        "plan_contract_version": PLAN_CONTRACT_VERSION,
        "tools": tools,
        "automatic_export": {
            "contains_raw_task": False,
            "contains_model_text": False,
            "contains_tool_result_text": False,
            "contains_images": False,
            "contains_memory": False,
            "contains_continuation": False,
        },
    }


def fullcycle_manifest_digest() -> str:
    """Return the digest that binds a run export to the current manifest."""

    digest = hashlib.sha256(canonical_json_bytes(build_fullcycle_manifest())).hexdigest()
    return f"sha256:{digest}"


def build_fullcycle_run_export(
    state_dir: Path,
    run_id: str,
) -> dict[str, JSONValue]:
    """Validate and package one existing redacted run without other data sources."""

    record = read_run_record(state_dir, run_id)
    _validate_redacted_record(record)
    return {
        "fullcycle_run_export_version": FULLCYCLE_RUN_EXPORT_VERSION,
        "manifest_digest": fullcycle_manifest_digest(),
        "run_id": run_id,
        "checkpoint": record["state"],
        "events": record["events"],
        "data_class": FULLCYCLE_DATA_CLASS,
        "training_use": FULLCYCLE_TRAINING_USE,
    }


def _validate_redacted_record(record: Mapping[str, JSONValue]) -> None:
    checkpoint = record.get("state")
    events = record.get("events")
    if not isinstance(checkpoint, dict) or not isinstance(events, list):
        raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
    if not set(checkpoint).issubset(_CHECKPOINT_FIELDS):
        raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
    budgets = checkpoint.get("budgets")
    metrics = checkpoint.get("metrics")
    if (
        not isinstance(budgets, dict)
        or set(budgets) != _BUDGET_FIELDS
        or not isinstance(metrics, dict)
        or not set(metrics).issubset(_METRIC_FIELDS)
    ):
        raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
        kind = event.get("kind")
        if not isinstance(kind, str) or kind not in _EVENT_FIELDS:
            raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
        if not set(event).issubset(_EVENT_BASE_FIELDS | _EVENT_FIELDS[kind]):
            raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
    _reject_rich_fields(checkpoint)
    _reject_rich_fields(events)


def _reject_rich_fields(value: JSONValue) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key.lower() in _FORBIDDEN_RICH_FIELDS:
                raise ValueError("FULLCYCLE_RUN_RECORD_UNSAFE")
            _reject_rich_fields(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_rich_fields(nested)


def write_new_fullcycle_json(
    output: Path,
    payload: Mapping[str, JSONValue],
) -> None:
    """Write a bounded export once, rejecting relative, redirected, or existing paths."""

    if not isinstance(output, Path) or not output.is_absolute():
        raise ValueError("FULLCYCLE_OUTPUT_MUST_BE_ABSOLUTE")
    parent = output.parent
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("FULLCYCLE_OUTPUT_PARENT_UNSAFE")
    current = parent
    while current != current.parent:
        if current.is_symlink():
            raise ValueError("FULLCYCLE_OUTPUT_PARENT_UNSAFE")
        current = current.parent
    encoded = canonical_json_bytes(payload)
    if not encoded or len(encoded) > MAX_FULLCYCLE_OUTPUT_BYTES:
        raise ValueError("FULLCYCLE_OUTPUT_TOO_LARGE")

    binary = getattr(os, "O_BINARY", 0)
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | binary,
            0o600,
        )
        created = True
        with os.fdopen(descriptor, "wb") as file:
            descriptor = None
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError as exc:
        raise ValueError("FULLCYCLE_OUTPUT_ALREADY_EXISTS") from exc
    except OSError:
        if created:
            try:
                output.unlink()
            except OSError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)


__all__ = [
    "FULLCYCLE_DATA_CLASS",
    "FULLCYCLE_MANIFEST_VERSION",
    "FULLCYCLE_RUN_EXPORT_VERSION",
    "FULLCYCLE_TRAINING_USE",
    "build_fullcycle_manifest",
    "build_fullcycle_run_export",
    "canonical_json_bytes",
    "fullcycle_manifest_digest",
    "write_new_fullcycle_json",
]
