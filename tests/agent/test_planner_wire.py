from __future__ import annotations

import json

import pytest

from computer_use_agent.planner_wire import (
    PlannerWireError,
    compile_planner_wire_candidate,
    planner_output_schema,
)


def test_shared_schema_rejects_ambiguous_or_excessive_tool_scope() -> None:
    for scope in ("find", ("find", "find"), tuple(f"tool_{index}" for index in range(9))):
        with pytest.raises(PlannerWireError, match="PLANNER_WIRE_SCOPE_INVALID"):
            planner_output_schema(scope)  # type: ignore[arg-type]


def test_shared_compiler_enforces_step_bound_outside_provider_grammar() -> None:
    text = json.dumps(
        {"version": 1, "steps": [{"action": "final_response"}] * 17}
    )

    with pytest.raises(PlannerWireError, match="PLANNER_WIRE_INVALID"):
        compile_planner_wire_candidate(text, allowed_tools=frozenset())


def test_shared_compiler_rejects_invalid_utf8_text() -> None:
    with pytest.raises(PlannerWireError, match="PLANNER_WIRE_INVALID"):
        compile_planner_wire_candidate("\ud800", allowed_tools=frozenset())
