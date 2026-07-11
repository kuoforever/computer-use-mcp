from __future__ import annotations

import asyncio
import json

import pytest

from computer_use_agent.tool_registry import (
    EXPECTED_TOOL_NAMES,
    REVIEWED_TOOLS,
    ResultSensitivity,
    ToolRegistryMismatchError,
    ToolValidationError,
    get_tool_spec,
    reviewed_mcp_descriptors,
    reviewed_tool_schemas,
    validate_tool_arguments,
    validate_tool_result,
    verify_discovered_tools,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    MCPToolDescriptor,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
    to_json_value,
)


def _call(name: str) -> ToolCall:
    arguments = {"query": "Save"} if name == "find" else {}
    return ToolCall(
        identity=CallIdentity(run_id="run_1", turn_id="turn_1", call_id="call_1"),
        name=name,
        arguments=arguments,
    )


def _png(width: int = 1, height: int = 1) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
        + b"\x00\x00\x00\x00"
    )


def test_registry_contains_the_exact_eight_reviewed_mcp_tools() -> None:
    assert EXPECTED_TOOL_NAMES == {
        "ui_snapshot",
        "find",
        "list_windows",
        "screenshot",
        "activate_window",
        "click",
        "type",
        "key",
    }
    assert len(REVIEWED_TOOLS) == 8
    assert all(tool.input_schema["additionalProperties"] is False for tool in REVIEWED_TOOLS)
    assert get_tool_spec("screenshot").result_sensitivity is ResultSensitivity.SENSITIVE


def test_every_side_effect_requires_approval_and_invalidates_observation() -> None:
    actions = [tool for tool in REVIEWED_TOOLS if tool.effect is ToolEffect.SIDE_EFFECT]

    assert {tool.name for tool in actions} == {"activate_window", "click", "type", "key"}
    assert all(tool.requires_host_approval for tool in actions)
    assert all(tool.invalidates_observation for tool in actions)


def test_exact_mcp_discovery_with_reviewed_schemas_is_accepted() -> None:
    verify_discovered_tools(reviewed_mcp_descriptors())


def test_reviewed_mcp_schemas_match_the_current_server_generation() -> None:
    from computer_use_mcp.server import build_server

    server = build_server(driver=object(), start_estop=False)
    discovered = asyncio.run(server.list_tools())

    verify_discovered_tools(
        tuple(
            MCPToolDescriptor(tool.name, tool.inputSchema, tool.outputSchema)
            for tool in discovered
        )
    )


def test_mcp_schema_mismatch_fails_closed_even_when_names_match() -> None:
    descriptors = list(reviewed_mcp_descriptors())
    descriptors[0] = MCPToolDescriptor(
        name="ui_snapshot",
        input_schema={"type": "object", "properties": {}},
    )

    with pytest.raises(ToolRegistryMismatchError, match="schema mismatch"):
        verify_discovered_tools(descriptors)


def test_mcp_output_schema_mismatch_fails_closed() -> None:
    descriptors = list(reviewed_mcp_descriptors())
    reviewed = descriptors[0]
    descriptors[0] = MCPToolDescriptor(
        name=reviewed.name,
        input_schema=reviewed.input_schema,
        output_schema={"type": "object", "properties": {}},
    )

    with pytest.raises(ToolRegistryMismatchError, match="output schema mismatch"):
        verify_discovered_tools(descriptors)


@pytest.mark.parametrize(
    ("discovered", "message"),
    [
        ((MCPToolDescriptor("find", {"type": "object"}),), "missing"),
        ((*reviewed_mcp_descriptors(), MCPToolDescriptor("shell", {"type": "object"})), "unexpected"),
        ((*reviewed_mcp_descriptors(), reviewed_mcp_descriptors()[1]), "duplicate"),
        (("not-a-descriptor",), "malformed"),
    ],
)
def test_mcp_discovery_mismatches_fail_closed(discovered: tuple[object, ...], message: str) -> None:
    with pytest.raises(ToolRegistryMismatchError, match=message):
        verify_discovered_tools(discovered)


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"x": 1},
        {"y": 2},
        {"ref": "ref_1", "x": 1, "y": 2},
        {"ref": "ref_1", "x": 1},
        {"ref": ""},
        {"x": True, "y": 2},
        {"x": 1, "y": "2"},
    ],
)
def test_click_rejects_every_ambiguous_or_invalid_target_form(arguments: dict[str, object]) -> None:
    with pytest.raises(ToolValidationError):
        validate_tool_arguments("click", arguments)


def test_click_provider_schema_excludes_the_other_target_form_in_each_oneof_branch() -> None:
    branches = get_tool_spec("click").input_schema["oneOf"]

    assert to_json_value(branches[0]["not"]) == {
        "anyOf": [{"required": ["x"]}, {"required": ["y"]}]
    }
    assert to_json_value(branches[1]["not"]) == {"required": ["ref"]}


def test_click_accepts_exactly_one_valid_target_form() -> None:
    assert validate_tool_arguments("click", {"ref": "ref_1"}) == {"ref": "ref_1"}
    assert validate_tool_arguments("click", {"x": 10, "y": 20}) == {"x": 10, "y": 20}


def test_unknown_tool_and_argument_fail_before_dispatch() -> None:
    with pytest.raises(ToolValidationError, match="unknown tool"):
        get_tool_spec("shell")
    with pytest.raises(ToolValidationError, match="unknown argument"):
        validate_tool_arguments("find", {"query": "Save", "limit": 10})


def test_provider_schema_exports_are_json_copies_and_cannot_mutate_the_registry() -> None:
    schemas = reviewed_tool_schemas()
    json.dumps(schemas)
    schemas[0]["properties"]["scope"]["type"] = "integer"

    assert get_tool_spec("ui_snapshot").input_schema["properties"]["scope"]["type"] == "string"


def test_result_contract_rejects_image_content_for_text_tools() -> None:
    call = _call("find")
    result = ToolResult(
        identity=call.identity,
        tool_name="find",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(ImageContent(mime_type="image/png", data=_png(), width=1, height=1),),
    )

    with pytest.raises(ToolValidationError, match="must not return image"):
        validate_tool_result(call, result)


def test_type_result_cannot_retain_text_or_an_arbitrary_code_after_conversion() -> None:
    call = ToolCall(
        identity=CallIdentity(run_id="run_1", turn_id="turn_1", call_id="call_1"),
        name="type",
        arguments={"text": "secret-value"},
    )
    with pytest.raises(ValueError, match="must not retain text"):
        ToolResult(
            identity=call.identity,
            tool_name="type",
            status=ToolResultStatus.SUCCESS,
            dispatch=DispatchCertainty.DISPATCHED,
            sanitized_text="ok",
        )
    with pytest.raises(ValueError, match="reviewed non-sensitive"):
        ToolResult(
            identity=call.identity,
            tool_name="type",
            status=ToolResultStatus.ACTION_ERROR,
            dispatch=DispatchCertainty.DISPATCHED,
            code="secret-value",
        )


def test_type_is_the_only_registry_argument_marked_sensitive() -> None:
    assert get_tool_spec("type").sensitive_arguments == ("text",)
    assert get_tool_spec("type").required_safety_baselines == ("typed_text_audit_redaction",)
