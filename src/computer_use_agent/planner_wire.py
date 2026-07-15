"""Shared structured-output envelope for isolated Planner adapters.

Provider grammars constrain only the non-authoritative plan shape. Tool
arguments travel as JSON text so provider-specific schema subsets cannot drift
from the reviewed host registry; the existing TaskPlan compiler remains the
only exact tool-argument validator.
"""
from __future__ import annotations

import json
from typing import Sequence

from .planning import MAX_PLAN_CANDIDATE_BYTES, MAX_PLAN_STEPS, PLAN_CONTRACT_VERSION


class PlannerWireError(ValueError):
    """Fixed wire-envelope failure that never embeds provider output."""


def planner_output_schema(tool_names: Sequence[str]) -> dict[str, object]:
    """Build the small JSON Schema shared by structured-output providers."""

    names = tuple(tool_names)
    if (
        isinstance(tool_names, (str, bytes))
        or not all(isinstance(name, str) and name for name in names)
        or len(names) != len(set(names))
        or len(names) > 8
    ):
        raise PlannerWireError("PLANNER_WIRE_SCOPE_INVALID")
    final_step: dict[str, object] = {
        "type": "object",
        "properties": {"action": {"type": "string", "const": "final_response"}},
        "required": ["action"],
        "additionalProperties": False,
    }
    step_variants = [final_step]
    if names:
        step_variants.insert(
            0,
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "const": "tool"},
                    "tool": {"type": "string", "enum": list(names)},
                    "arguments_json": {"type": "string"},
                },
                "required": ["action", "tool", "arguments_json"],
                "additionalProperties": False,
            },
        )
    return {
        "type": "object",
        "properties": {
            "version": {"type": "integer", "const": PLAN_CONTRACT_VERSION},
            "steps": {
                "type": "array",
                "minItems": 1,
                "items": {"anyOf": step_variants},
            },
        },
        "required": ["version", "steps"],
        "additionalProperties": False,
    }


def compile_planner_wire_candidate(
    text: str, *, allowed_tools: frozenset[str]
) -> str:
    """Losslessly convert one bounded provider envelope to candidate JSON."""

    if not isinstance(text, str) or not text:
        raise PlannerWireError("PLANNER_WIRE_INVALID")
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        raise PlannerWireError("PLANNER_WIRE_INVALID") from None
    if len(encoded) > MAX_PLAN_CANDIDATE_BYTES:
        raise PlannerWireError("PLANNER_WIRE_TOO_LARGE")
    try:
        envelope = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        raise PlannerWireError("PLANNER_WIRE_INVALID") from None
    if not isinstance(envelope, dict) or set(envelope) != {"version", "steps"}:
        raise PlannerWireError("PLANNER_WIRE_INVALID")
    version = envelope["version"]
    if version != PLAN_CONTRACT_VERSION or isinstance(version, bool):
        raise PlannerWireError("PLANNER_WIRE_INVALID")
    steps = envelope["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_PLAN_STEPS:
        raise PlannerWireError("PLANNER_WIRE_INVALID")
    candidate_steps: list[dict[str, object]] = []
    for step in steps:
        if not isinstance(step, dict):
            raise PlannerWireError("PLANNER_WIRE_INVALID")
        if step == {"action": "final_response"}:
            candidate_steps.append(step)
            continue
        if set(step) != {"action", "tool", "arguments_json"} or step.get("action") != "tool":
            raise PlannerWireError("PLANNER_WIRE_INVALID")
        tool = step["tool"]
        raw_arguments = step["arguments_json"]
        if not isinstance(tool, str) or tool not in allowed_tools:
            raise PlannerWireError("PLANNER_WIRE_INVALID")
        if not isinstance(raw_arguments, str):
            raise PlannerWireError("PLANNER_WIRE_INVALID")
        try:
            arguments = json.loads(raw_arguments)
        except (json.JSONDecodeError, RecursionError):
            raise PlannerWireError("PLANNER_WIRE_INVALID") from None
        if not isinstance(arguments, dict):
            raise PlannerWireError("PLANNER_WIRE_INVALID")
        candidate_steps.append({"action": "tool", "tool": tool, "arguments": arguments})
    try:
        candidate = json.dumps(
            {"version": PLAN_CONTRACT_VERSION, "steps": candidate_steps},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError, UnicodeError):
        raise PlannerWireError("PLANNER_WIRE_INVALID") from None
    if len(candidate.encode("utf-8")) > MAX_PLAN_CANDIDATE_BYTES:
        raise PlannerWireError("PLANNER_WIRE_TOO_LARGE")
    return candidate


__all__ = [
    "PlannerWireError",
    "compile_planner_wire_candidate",
    "planner_output_schema",
]
