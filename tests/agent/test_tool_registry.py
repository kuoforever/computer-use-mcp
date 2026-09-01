from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace

import pytest

from computer_use_agent.tool_registry import (
    EXPECTED_TOOL_NAMES,
    OPTIONAL_REVIEWED_TOOLS,
    OPTIONAL_TOOL_NAMES,
    REVIEWED_TOOLS,
    ResultSensitivity,
    ToolRegistryMismatchError,
    ToolValidationError,
    get_tool_spec,
    reviewed_mcp_descriptors,
    reviewed_registry_digest,
    reviewed_tool_schemas,
    reviewed_tools_with_optional,
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


class _MalformedDescriptorLookalike:
    @property
    def name(self) -> str:
        raise AssertionError("malformed descriptors must be rejected before attribute access")


def test_registry_contains_the_exact_thirteen_core_reviewed_mcp_tools() -> None:
    assert EXPECTED_TOOL_NAMES == {
        "ui_snapshot",
        "find",
        "list_windows",
        "screenshot",
        "capture_region",
        "ocr",
        "document_text",
        "activate_window",
        "click",
        "scroll",
        "drag",
        "type",
        "key",
    }
    assert len(REVIEWED_TOOLS) == 13
    assert all(tool.input_schema["additionalProperties"] is False for tool in REVIEWED_TOOLS)
    assert get_tool_spec("screenshot").result_sensitivity is ResultSensitivity.SENSITIVE
    assert (
        reviewed_registry_digest()
        == "3112fbb88ad1398d4dc466cd0b2adff7199ace387d281f9c952ead7b961ed2bb"
    )


def test_provider_schema_json_and_optional_registry_digest_are_pinned() -> None:
    canonical_schemas = json.dumps(
        reviewed_tool_schemas(),
        sort_keys=True,
        separators=(",", ":"),
    )

    assert hashlib.sha256(canonical_schemas.encode("utf-8")).hexdigest() == (
        "56b2531166b1856481a505f1cf2da5362c3a802c83b49787920abb56ff7e81ee"
    )
    assert reviewed_registry_digest(OPTIONAL_TOOL_NAMES) == (
        "8aae88ff4cb4265ba16f770615ccc2cbd84434e51e03a9569f493a88a443f042"
    )


def test_browser_snapshot_is_a_reviewed_optional_capability() -> None:
    assert OPTIONAL_TOOL_NAMES == {"browser_snapshot"}
    assert tuple(tool.name for tool in OPTIONAL_REVIEWED_TOOLS) == (
        "browser_snapshot",
    )
    assert tuple(
        tool.name
        for tool in reviewed_tools_with_optional(frozenset({"browser_snapshot"}))
    ) == (*tuple(tool.name for tool in REVIEWED_TOOLS), "browser_snapshot")
    assert reviewed_registry_digest(frozenset({"browser_snapshot"})) != (
        reviewed_registry_digest()
    )


def test_every_side_effect_requires_approval_and_invalidates_observation() -> None:
    actions = [tool for tool in REVIEWED_TOOLS if tool.effect is ToolEffect.SIDE_EFFECT]

    assert {tool.name for tool in actions} == {
        "activate_window",
        "click",
        "scroll",
        "drag",
        "type",
        "key",
    }
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


@pytest.mark.parametrize("malformed_index", [0, 6, 12])
def test_mcp_discovery_rejects_every_malformed_position_before_attribute_access(
    malformed_index: int,
) -> None:
    descriptors: list[object] = list(reviewed_mcp_descriptors())
    descriptors[malformed_index] = _MalformedDescriptorLookalike()

    with pytest.raises(
        ToolRegistryMismatchError,
        match="^MCP discovery returned malformed tool descriptors$",
    ):
        verify_discovered_tools(descriptors)


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


def test_browser_snapshot_is_read_only_bounded_and_has_no_action_ref_contract() -> None:
    tool = get_tool_spec("browser_snapshot")

    assert tool.effect is ToolEffect.OBSERVATION
    assert tool.requires_host_approval is False
    assert tool.invalidates_observation is False
    assert set(tool.input_schema["properties"]) == {"page_index", "detail"}
    assert validate_tool_arguments("browser_snapshot", {}) == {}
    assert validate_tool_arguments(
        "browser_snapshot", {"page_index": 3, "detail": "both"}
    ) == {"page_index": 3, "detail": "both"}
    for arguments in (
        {"page_index": -1},
        {"page_index": 32},
        {"detail": "evaluate"},
        {"ref": "e7"},
    ):
        with pytest.raises(ToolValidationError):
            validate_tool_arguments("browser_snapshot", arguments)


def test_optional_browser_discovery_is_exact_when_configured() -> None:
    optional = frozenset({"browser_snapshot"})

    verify_discovered_tools(
        reviewed_mcp_descriptors(optional),
        optional,
    )


def test_configured_optional_browser_schema_matches_server_generation() -> None:
    from computer_use_mcp.server import build_server

    server = build_server(
        driver=object(),
        start_estop=False,
        browser_observer=object(),
        browser_observation_enabled=True,
    )
    discovered = asyncio.run(server.list_tools())
    optional = frozenset({"browser_snapshot"})

    verify_discovered_tools(
        tuple(
            MCPToolDescriptor(tool.name, tool.inputSchema, tool.outputSchema)
            for tool in discovered
        ),
        optional,
    )
    with pytest.raises(ToolRegistryMismatchError, match="unexpected"):
        verify_discovered_tools(reviewed_mcp_descriptors(optional))


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("scroll", {"x": 10, "y": 20}),
        ("scroll", {"x": 10, "y": 20, "delta_x": 2401}),
        ("scroll", {"x": 10, "y": 20, "delta_y": -2401}),
        ("drag", {"x": 10, "y": 20, "to_x": 10, "to_y": 20}),
        (
            "drag",
            {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": 5001},
        ),
    ],
)
def test_scroll_and_drag_reject_unbounded_or_noop_input(
    name: str, arguments: dict[str, object]
) -> None:
    with pytest.raises(ToolValidationError):
        validate_tool_arguments(name, arguments)


def test_scroll_and_drag_accept_bounded_grounded_coordinates() -> None:
    scroll = {"x": 10, "y": 20, "delta_y": -120}
    drag = {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": 250}

    assert validate_tool_arguments("scroll", scroll) == scroll
    assert validate_tool_arguments("drag", drag) == drag


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        (
            "scroll",
            {"x": 10, "y": 20, "delta_x": True},
            "delta_x must be an integer",
        ),
        (
            "drag",
            {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": "250"},
            "duration_ms must be an integer",
        ),
        (
            "capture_region",
            {"x": "0", "y": 0, "w": 1, "h": 1},
            "x must be an integer",
        ),
    ],
)
def test_integer_argument_type_errors_keep_exact_public_messages(
    name: str,
    arguments: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ToolValidationError, match=f"^{message}$"):
        validate_tool_arguments(name, arguments)


def test_required_field_owner_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_schema = to_json_value(get_tool_spec("list_windows").input_schema)
    assert isinstance(input_schema, dict)
    input_schema["required"] = [1]
    malformed = replace(
        get_tool_spec("list_windows"),
        input_schema=input_schema,
    )
    monkeypatch.setattr("computer_use_agent.tool_registry.get_tool_spec", lambda _: malformed)

    with pytest.raises(
        ToolValidationError,
        match="^reviewed schema for list_windows is malformed$",
    ):
        validate_tool_arguments("list_windows", {})


@pytest.mark.parametrize(
    ("name", "arguments", "malformed_field"),
    [
        (
            "scroll",
            {"x": 10, "y": 20, "delta_x": "120"},
            "delta_x",
        ),
        (
            "drag",
            {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": "250"},
            "duration_ms",
        ),
        (
            "capture_region",
            {"x": "0", "y": 0, "w": 1, "h": 1},
            "x",
        ),
    ],
)
def test_integer_argument_owner_drift_fails_closed(
    name: str,
    arguments: dict[str, object],
    malformed_field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_schema = to_json_value(get_tool_spec(name).input_schema)
    assert isinstance(input_schema, dict)
    properties = input_schema.get("properties")
    assert isinstance(properties, dict)
    field_schema = properties.get(malformed_field)
    assert isinstance(field_schema, dict)
    field_schema["type"] = "string"
    malformed = replace(get_tool_spec(name), input_schema=input_schema)
    monkeypatch.setattr("computer_use_agent.tool_registry.get_tool_spec", lambda _: malformed)

    with pytest.raises(
        ToolValidationError,
        match=rf"^reviewed schema for {name}\.{malformed_field} is malformed$",
    ):
        validate_tool_arguments(name, arguments)


@pytest.mark.parametrize(
    "arguments",
    [
        {"x": 0, "y": 0, "w": 0, "h": 1},
        {"x": -1, "y": 0, "w": 1, "h": 1},
        {"x": 0, "y": 0, "w": 2001, "h": 2000},
        {"x": 0, "y": 0, "w": 1},
    ],
)
def test_region_host_validation_rejects_unbounded_regions(arguments: dict[str, object]) -> None:
    for name in ("ocr", "capture_region"):
        with pytest.raises(ToolValidationError):
            validate_tool_arguments(name, arguments)


def test_region_host_validation_accepts_one_bounded_region() -> None:
    arguments = {"x": 10, "y": 20, "w": 300, "h": 400}

    assert validate_tool_arguments("ocr", arguments) == arguments
    assert validate_tool_arguments("capture_region", arguments) == arguments


@pytest.mark.parametrize("name", ["ui_snapshot", "find", "document_text"])
def test_scope_contract_accepts_only_runtime_resolvable_values(name: str) -> None:
    base = {"query": "Save"} if name == "find" else {}

    assert validate_tool_arguments(name, base) == base
    for scope in ("foreground", "all", "5244578"):
        arguments = {**base, "scope": scope}
        assert validate_tool_arguments(name, arguments) == arguments
    for scope in ("", "foreground document", "window:42", "0"):
        with pytest.raises(ToolValidationError, match="reviewed format"):
            validate_tool_arguments(name, {**base, "scope": scope})

    scope_schema = get_tool_spec(name).input_schema["properties"]["scope"]
    assert scope_schema["pattern"] == r"^(?:foreground|all|[1-9][0-9]*)$"


def test_only_the_pixel_returning_tools_declare_image_output() -> None:
    """The privacy layer selects redaction targets from this property, not names."""

    assert {tool.name for tool in REVIEWED_TOOLS if tool.returns_image} == {
        "screenshot",
        "capture_region",
    }
    assert get_tool_spec("capture_region").result_sensitivity is ResultSensitivity.SENSITIVE
    assert get_tool_spec("capture_region").effect is ToolEffect.OBSERVATION


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


def test_provider_schema_export_fails_closed_if_copy_is_not_an_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("computer_use_agent.tool_registry.to_json_value", lambda _: [])

    with pytest.raises(ToolRegistryMismatchError, match="schema is not a JSON object"):
        reviewed_tool_schemas()


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
