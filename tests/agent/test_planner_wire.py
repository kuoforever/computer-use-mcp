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


def test_reviewed_short_arguments_field_compiles_to_the_same_host_candidate() -> None:
    schema = planner_output_schema(("list_windows",), arguments_field="arguments")
    variants = schema["properties"]["steps"]["items"]["anyOf"]  # type: ignore[index]
    tool_schema = variants[0]  # type: ignore[index]
    assert set(tool_schema["properties"]) == {"action", "tool", "arguments"}
    wire = json.dumps(
        {
            "version": 1,
            "steps": [
                {"action": "tool", "tool": "list_windows", "arguments": "{}"},
                {"action": "final_response"},
            ],
        }
    )

    candidate = compile_planner_wire_candidate(
        wire,
        allowed_tools=frozenset({"list_windows"}),
        arguments_field="arguments",
    )

    assert json.loads(candidate)["steps"][0] == {
        "action": "tool",
        "tool": "list_windows",
        "arguments": {},
    }


def test_short_arguments_field_rejects_unreviewed_or_model_invented_aliases() -> None:
    with pytest.raises(
        PlannerWireError, match="PLANNER_WIRE_ARGUMENT_FIELD_INVALID"
    ):
        planner_output_schema(("list_windows",), arguments_field="arguments_")
    invalid_short_steps = (
        {"action": "tool", "tool": "list_windows", "arguments_": "{}"},
        {"action": "tool", "tool": "list_windows", "arguments_json": "{}"},
        {"action": "tool", "tool": "list_windows", "arguments": {}},
        {
            "action": "tool",
            "tool": "list_windows",
            "arguments": "{}",
            "arguments_": "{}",
        },
        {
            "action": "tool",
            "tool": "list_windows",
            "arguments": "{}",
            "arguments_json": "{}",
        },
    )
    for step in invalid_short_steps:
        wire = json.dumps(
            {
                "version": 1,
                "steps": [step, {"action": "final_response"}],
            }
        )
        with pytest.raises(PlannerWireError, match="PLANNER_WIRE_INVALID"):
            compile_planner_wire_candidate(
                wire,
                allowed_tools=frozenset({"list_windows"}),
                arguments_field="arguments",
            )

    default_wire = json.dumps(
        {
            "version": 1,
            "steps": [
                {"action": "tool", "tool": "list_windows", "arguments": "{}"},
                {"action": "final_response"},
            ],
        }
    )
    with pytest.raises(PlannerWireError, match="PLANNER_WIRE_INVALID"):
        compile_planner_wire_candidate(
            default_wire, allowed_tools=frozenset({"list_windows"})
        )


def test_shared_compiler_enforces_step_bound_outside_provider_grammar() -> None:
    text = json.dumps(
        {"version": 1, "steps": [{"action": "final_response"}] * 17}
    )

    with pytest.raises(PlannerWireError, match="PLANNER_WIRE_INVALID"):
        compile_planner_wire_candidate(text, allowed_tools=frozenset())


def test_shared_compiler_rejects_invalid_utf8_text() -> None:
    with pytest.raises(PlannerWireError, match="PLANNER_WIRE_INVALID"):
        compile_planner_wire_candidate("\ud800", allowed_tools=frozenset())
