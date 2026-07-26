"""Bounded provider task and result contract for application workers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping

from .application_worker_catalog import ApplicationWorkerSpec
from .types import JSONValue
from .worker_capabilities import capabilities_for_composition, tools_for_composition


APPLICATION_WORKER_RESULT_VERSION = 1
MAX_APPLICATION_WORKER_TASK_CHARS = 8 * 1024
MAX_APPLICATION_WORKER_RESULT_CHARS = 32 * 1024
MAX_APPLICATION_WORKER_VALUE_CHARS = 4 * 1024
_OUTCOMES = frozenset({"EXTRACTED", "BLOCKED"})


class ApplicationWorkerContractError(ValueError):
    """Fixed failure from the application-worker wire contract."""


def _bounded_identifier(value: object, *, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 256
        or any(ord(character) < 32 for character in value)
    ):
        raise ApplicationWorkerContractError(code)
    return value


def _bounded_json(value: object, *, depth: int = 0) -> JSONValue:
    if depth > 4:
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > MAX_APPLICATION_WORKER_VALUE_CHARS:
            raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_TOO_LARGE")
        return value
    if isinstance(value, list):
        if len(value) > 50:
            raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_TOO_LARGE")
        return [_bounded_json(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 50 or any(
            not isinstance(key, str) or not key or len(key) > 128 for key in value
        ):
            raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
        return {
            key: _bounded_json(item, depth=depth + 1)
            for key, item in value.items()
        }
    raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")


@dataclass(frozen=True)
class ApplicationWorkerResult:
    scenario_id: str
    item_key: str
    outcome: str
    identity: Mapping[str, JSONValue]
    result: Mapping[str, JSONValue]
    observation_tools: tuple[str, ...]
    application_state_verified: bool
    item_identity_verified: bool
    stop_code: str | None
    content_digest: str


def compile_application_worker_task(
    spec: ApplicationWorkerSpec,
    *,
    item_key: str,
    item_ordinal: int,
) -> str:
    """Compile one exact item into a fixed, bounded provider instruction."""

    if (
        not isinstance(spec, ApplicationWorkerSpec)
        or not isinstance(item_ordinal, int)
        or isinstance(item_ordinal, bool)
        or item_ordinal <= 0
    ):
        raise ApplicationWorkerContractError("APPLICATION_WORKER_TASK_INVALID")
    selected_key = _bounded_identifier(
        item_key,
        code="APPLICATION_WORKER_TASK_INVALID",
    )
    contract = {
        "scenario_id": spec.scenario_id,
        "item_key": selected_key,
        "item_ordinal": item_ordinal,
        "identity_dimensions": list(spec.identity_dimensions),
        "result_fields": list(spec.result_fields),
        "observation_ladder": list(spec.observation_ladder),
        "navigation_tools": list(spec.navigation_tools),
        "optional_effects": list(spec.optional_effects),
        "maximum_risk": spec.maximum_risk,
        "stop_states": list(spec.stop_states),
        "capabilities": [
            capability.name
            for capability in capabilities_for_composition(
                spec.scenario_id,
                spec.capability_names,
            )
        ],
        "allowed_tools": sorted(
            tools_for_composition(spec.scenario_id, spec.capability_names)
        ),
    }
    task = (
        "Execute exactly one durable application campaign item. "
        "Re-establish every stable identity dimension before extraction and "
        "after any action. Use only the listed observation/navigation tools. "
        "Optional effects require the host approval boundary; never infer "
        "approval, replay an uncertain effect, bypass a challenge, or substitute "
        "another item. Escalate observations in the listed order. Return exactly "
        "one JSON object with keys version, scenario_id, item_key, outcome, "
        "identity, result, evidence, and stop_code. outcome is EXTRACTED or "
        "BLOCKED. EXTRACTED requires every identity/result field plus verified "
        "application and item identity evidence; BLOCKED requires one listed "
        "stop_code and empty result.\nCONTRACT="
        + json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    )
    if len(task) > MAX_APPLICATION_WORKER_TASK_CHARS:
        raise ApplicationWorkerContractError("APPLICATION_WORKER_TASK_TOO_LARGE")
    return task


def parse_application_worker_result(
    spec: ApplicationWorkerSpec,
    *,
    item_key: str,
    text: str,
) -> ApplicationWorkerResult:
    """Validate a provider result against the exact reviewed scenario schema."""

    selected_key = _bounded_identifier(
        item_key,
        code="APPLICATION_WORKER_RESULT_INVALID",
    )
    if (
        not isinstance(spec, ApplicationWorkerSpec)
        or not isinstance(text, str)
        or not text
    ):
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
    if len(text) > MAX_APPLICATION_WORKER_RESULT_CHARS:
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_TOO_LARGE")
    try:
        raw = json.loads(text)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "scenario_id",
        "item_key",
        "outcome",
        "identity",
        "result",
        "evidence",
        "stop_code",
    }:
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
    if (
        raw["version"] != APPLICATION_WORKER_RESULT_VERSION
        or raw["scenario_id"] != spec.scenario_id
        or raw["item_key"] != selected_key
        or raw["outcome"] not in _OUTCOMES
        or not isinstance(raw["identity"], dict)
        or not isinstance(raw["result"], dict)
        or not isinstance(raw["evidence"], dict)
        or set(raw["evidence"])
        != {
            "observation_tools",
            "application_state_verified",
            "item_identity_verified",
        }
    ):
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
    evidence = raw["evidence"]
    tools = evidence["observation_tools"]
    if (
        not isinstance(tools, list)
        or not tools
        or len(tools) > len(spec.observation_ladder)
        or len(set(tools)) != len(tools)
        or any(tool not in spec.observation_ladder for tool in tools)
        or not isinstance(evidence["application_state_verified"], bool)
        or not isinstance(evidence["item_identity_verified"], bool)
    ):
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")

    identity = _bounded_json(raw["identity"])
    result = _bounded_json(raw["result"])
    if not isinstance(identity, dict) or not isinstance(result, dict):
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
    outcome = raw["outcome"]
    stop_code = raw["stop_code"]
    if outcome == "EXTRACTED":
        if (
            set(identity) != set(spec.identity_dimensions)
            or set(result) != set(spec.result_fields)
            or evidence["application_state_verified"] is not True
            or evidence["item_identity_verified"] is not True
            or stop_code is not None
        ):
            raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")
    elif (
        result
        or not isinstance(stop_code, str)
        or stop_code not in spec.stop_states
    ):
        raise ApplicationWorkerContractError("APPLICATION_WORKER_RESULT_INVALID")

    canonical = json.dumps(
        {
            "version": APPLICATION_WORKER_RESULT_VERSION,
            "scenario_id": spec.scenario_id,
            "item_key": selected_key,
            "outcome": outcome,
            "identity": identity,
            "result": result,
            "evidence": {
                "observation_tools": tools,
                "application_state_verified": evidence["application_state_verified"],
                "item_identity_verified": evidence["item_identity_verified"],
            },
            "stop_code": stop_code,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return ApplicationWorkerResult(
        scenario_id=spec.scenario_id,
        item_key=selected_key,
        outcome=outcome,
        identity=MappingProxyType(identity),
        result=MappingProxyType(result),
        observation_tools=tuple(tools),
        application_state_verified=evidence["application_state_verified"],
        item_identity_verified=evidence["item_identity_verified"],
        stop_code=stop_code,
        content_digest=sha256(canonical).hexdigest(),
    )


__all__ = [
    "APPLICATION_WORKER_RESULT_VERSION",
    "ApplicationWorkerContractError",
    "ApplicationWorkerResult",
    "compile_application_worker_task",
    "parse_application_worker_result",
]
