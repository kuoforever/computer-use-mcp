"""The fixed, reviewed MCP tool registry for the planned Agent Host.

The registry has two schemas per tool: a strict host schema advertised to model
providers and the exact currently reviewed MCP discovery schema. The host never
widens either surface from dynamic discovery.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from .types import (
    JSONValue,
    MCPToolDescriptor,
    ToolCall,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
    _frozen_json_object,
    to_json_value,
)


class ResultContentKind(str, Enum):
    TEXT = "text"
    IMAGE = "image"


class ResultSensitivity(str, Enum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"


class RedactionPolicy(str, Enum):
    NONE = "none"
    TITLE_MATCHED_ONLY = "title_matched_only"


class GroundingRequirement(str, Enum):
    NONE = "none"
    RECENT_OBSERVATION = "recent_observation"
    OBSERVED_WINDOW = "observed_window"
    REF_OR_SCREENSHOT = "ref_or_screenshot"


class ToolValidationError(ValueError):
    """Raised before dispatch for an unknown or structurally invalid call."""


class ToolRegistryMismatchError(RuntimeError):
    """Raised when MCP discovery is not the exact reviewed tool contract."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, JSONValue]
    mcp_input_schema: Mapping[str, JSONValue]
    effect: ToolEffect
    result_content: ResultContentKind
    result_sensitivity: ResultSensitivity
    redaction_policy: RedactionPolicy
    grounding: GroundingRequirement
    requires_host_approval: bool
    invalidates_observation: bool
    sensitive_arguments: tuple[str, ...] = ()
    required_safety_baselines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name or not self.name.replace("_", "").isalnum():
            raise ValueError("tool names must be non-empty snake_case identifiers")
        if not self.description.strip():
            raise ValueError("tool descriptions must be non-empty")
        if not isinstance(self.input_schema, Mapping):
            raise ValueError("input_schema must be a JSON object")
        if not isinstance(self.mcp_input_schema, Mapping):
            raise ValueError("mcp_input_schema must be a JSON object")
        if self.effect is ToolEffect.OBSERVATION:
            if self.requires_host_approval or self.invalidates_observation:
                raise ValueError("observation tools cannot require approval or invalidate grounding")
        elif not self.requires_host_approval or not self.invalidates_observation:
            raise ValueError("side-effect tools require approval and invalidate grounding")
        if self.result_content is ResultContentKind.IMAGE:
            if self.result_sensitivity is not ResultSensitivity.SENSITIVE:
                raise ValueError("image output must be marked sensitive")
            if self.redaction_policy is not RedactionPolicy.TITLE_MATCHED_ONLY:
                raise ValueError("current screenshot output has title-matched-only redaction")
        elif self.redaction_policy is not RedactionPolicy.NONE:
            raise ValueError("text tools cannot claim an image redaction policy")
        if not isinstance(self.required_safety_baselines, tuple) or not all(
            isinstance(baseline, str) and baseline for baseline in self.required_safety_baselines
        ):
            raise ValueError("required_safety_baselines must be a tuple of non-empty strings")
        object.__setattr__(self, "input_schema", _frozen_json_object(self.input_schema, "input_schema"))
        object.__setattr__(
            self,
            "mcp_input_schema",
            _frozen_json_object(self.mcp_input_schema, "mcp_input_schema"),
        )


def _host_schema(
    properties: dict[str, JSONValue],
    required: tuple[str, ...] = (),
    **extra: JSONValue,
) -> dict[str, JSONValue]:
    schema: dict[str, JSONValue] = {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }
    schema.update(extra)
    return schema


def _mcp_schema(
    title: str,
    properties: dict[str, JSONValue],
    required: tuple[str, ...] = (),
) -> dict[str, JSONValue]:
    schema: dict[str, JSONValue] = {"properties": properties, "title": title, "type": "object"}
    if required:
        schema["required"] = list(required)
    return schema


_SCOPE = {"type": "string", "minLength": 1}
_NONEMPTY_STRING = {"type": "string", "minLength": 1}
_OPTIONAL_REF = {"type": "string", "minLength": 1}
_INTEGER = {"type": "integer"}
_MCP_INTEGER = {"type": "integer"}
_MCP_SCOPE = {"default": "foreground", "title": "Scope", "type": "string"}
_MCP_STRING = {"type": "string"}
_MCP_OPTIONAL_REF = {
    "anyOf": [{"type": "string"}, {"type": "null"}],
    "default": None,
    "title": "Ref",
}
_MCP_OPTIONAL_X = {
    "anyOf": [{"type": "integer"}, {"type": "null"}],
    "default": None,
    "title": "X",
}
_MCP_OPTIONAL_Y = {
    "anyOf": [{"type": "integer"}, {"type": "null"}],
    "default": None,
    "title": "Y",
}


REVIEWED_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="ui_snapshot",
        description="List interactive UI elements and session-scoped refs.",
        input_schema=_host_schema({"scope": _SCOPE}),
        mcp_input_schema=_mcp_schema("ui_snapshotArguments", {"scope": _MCP_SCOPE}),
        effect=ToolEffect.OBSERVATION,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.NONE,
        requires_host_approval=False,
        invalidates_observation=False,
    ),
    ToolSpec(
        name="find",
        description="Find interactive UI elements by query within a scope.",
        input_schema=_host_schema({"query": _NONEMPTY_STRING, "scope": _SCOPE}, ("query",)),
        mcp_input_schema=_mcp_schema(
            "findArguments",
            {"query": {"title": "Query", "type": "string"}, "scope": _MCP_SCOPE},
            ("query",),
        ),
        effect=ToolEffect.OBSERVATION,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.NONE,
        requires_host_approval=False,
        invalidates_observation=False,
    ),
    ToolSpec(
        name="list_windows",
        description="List visible top-level windows and their current identifiers.",
        input_schema=_host_schema({}),
        mcp_input_schema=_mcp_schema("list_windowsArguments", {}),
        effect=ToolEffect.OBSERVATION,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.NONE,
        requires_host_approval=False,
        invalidates_observation=False,
    ),
    ToolSpec(
        name="screenshot",
        description="Capture a primary-display PNG with configured title-based blackouts.",
        input_schema=_host_schema({}),
        mcp_input_schema=_mcp_schema("screenshotArguments", {}),
        effect=ToolEffect.OBSERVATION,
        result_content=ResultContentKind.IMAGE,
        result_sensitivity=ResultSensitivity.SENSITIVE,
        redaction_policy=RedactionPolicy.TITLE_MATCHED_ONLY,
        grounding=GroundingRequirement.NONE,
        requires_host_approval=False,
        invalidates_observation=False,
    ),
    ToolSpec(
        name="ocr",
        description=(
            "Recognize bounded text runs inside one explicit primary-display region."
        ),
        input_schema=_host_schema(
            {"x": _INTEGER, "y": _INTEGER, "w": _INTEGER, "h": _INTEGER},
            ("x", "y", "w", "h"),
        ),
        mcp_input_schema=_mcp_schema(
            "ocrArguments",
            {
                "x": {**_MCP_INTEGER, "title": "X"},
                "y": {**_MCP_INTEGER, "title": "Y"},
                "w": {**_MCP_INTEGER, "title": "W"},
                "h": {**_MCP_INTEGER, "title": "H"},
            },
            ("x", "y", "w", "h"),
        ),
        effect=ToolEffect.OBSERVATION,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.SENSITIVE,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.NONE,
        requires_host_approval=False,
        invalidates_observation=False,
        required_safety_baselines=("title_matched_image_redaction",),
    ),
    ToolSpec(
        name="activate_window",
        description="Bring a recently listed window to the foreground.",
        input_schema=_host_schema({"window_id": _NONEMPTY_STRING}, ("window_id",)),
        mcp_input_schema=_mcp_schema(
            "activate_windowArguments",
            {"window_id": {"title": "Window Id", "type": "string"}},
            ("window_id",),
        ),
        effect=ToolEffect.SIDE_EFFECT,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.OBSERVED_WINDOW,
        requires_host_approval=True,
        invalidates_observation=True,
    ),
    ToolSpec(
        name="click",
        description="Click exactly one UI ref or one primary-display coordinate pair.",
        input_schema=_host_schema(
            {"ref": _OPTIONAL_REF, "x": _INTEGER, "y": _INTEGER},
            oneOf=[
                {
                    "required": ["ref"],
                    "not": {"anyOf": [{"required": ["x"]}, {"required": ["y"]}]},
                },
                {"required": ["x", "y"], "not": {"required": ["ref"]}},
            ],
        ),
        mcp_input_schema=_mcp_schema(
            "clickArguments",
            {"ref": _MCP_OPTIONAL_REF, "x": _MCP_OPTIONAL_X, "y": _MCP_OPTIONAL_Y},
        ),
        effect=ToolEffect.SIDE_EFFECT,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.REF_OR_SCREENSHOT,
        requires_host_approval=True,
        invalidates_observation=True,
    ),
    ToolSpec(
        name="type",
        description="Enter text through a UI ref or the current foreground focus.",
        input_schema=_host_schema({"text": {"type": "string"}, "ref": _OPTIONAL_REF}, ("text",)),
        mcp_input_schema=_mcp_schema(
            "type_textArguments",
            {"text": {"title": "Text", "type": "string"}, "ref": _MCP_OPTIONAL_REF},
            ("text",),
        ),
        effect=ToolEffect.SIDE_EFFECT,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.RECENT_OBSERVATION,
        requires_host_approval=True,
        invalidates_observation=True,
        sensitive_arguments=("text",),
        required_safety_baselines=("typed_text_audit_redaction",),
    ),
    ToolSpec(
        name="key",
        description="Send one key chord to the current foreground window.",
        input_schema=_host_schema({"combo": _NONEMPTY_STRING}, ("combo",)),
        mcp_input_schema=_mcp_schema(
            "keyArguments",
            {"combo": {"title": "Combo", "type": "string"}},
            ("combo",),
        ),
        effect=ToolEffect.SIDE_EFFECT,
        result_content=ResultContentKind.TEXT,
        result_sensitivity=ResultSensitivity.NORMAL,
        redaction_policy=RedactionPolicy.NONE,
        grounding=GroundingRequirement.RECENT_OBSERVATION,
        requires_host_approval=True,
        invalidates_observation=True,
    ),
)

_TOOLS_BY_NAME = {tool.name: tool for tool in REVIEWED_TOOLS}
EXPECTED_TOOL_NAMES = frozenset(_TOOLS_BY_NAME)


def get_tool_spec(name: str) -> ToolSpec:
    if not isinstance(name, str):
        raise ToolValidationError("tool name must be a string")
    try:
        return _TOOLS_BY_NAME[name]
    except KeyError as exc:
        raise ToolValidationError(f"unknown tool: {name}") from exc


def reviewed_tool_schemas() -> tuple[dict[str, JSONValue], ...]:
    """Return fresh JSON-serializable provider schemas without shared mutability."""

    return tuple(to_json_value(tool.input_schema) for tool in REVIEWED_TOOLS)  # type: ignore[return-value]


def reviewed_registry_digest() -> str:
    """Return a stable digest of every reviewed provider and MCP tool contract."""

    material = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": to_json_value(tool.input_schema),
            "mcp_input_schema": to_json_value(tool.mcp_input_schema),
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
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def reviewed_mcp_descriptors() -> tuple[MCPToolDescriptor, ...]:
    """Return immutable expected descriptors for a local MCP discovery check."""

    return tuple(
        MCPToolDescriptor(
            name=tool.name,
            input_schema=tool.mcp_input_schema,
            output_schema=(
                None
                if tool.result_content is ResultContentKind.IMAGE
                else _mcp_text_output_schema(tool.name)
            ),
        )
        for tool in REVIEWED_TOOLS
    )


def _mcp_text_output_schema(tool_name: str) -> dict[str, JSONValue]:
    function_name = "type_text" if tool_name == "type" else tool_name
    return {
        "properties": {"result": {"title": "Result", "type": "string"}},
        "required": ["result"],
        "title": f"{function_name}Output",
        "type": "object",
    }


def verify_discovered_tools(discovered_tools: Sequence[object]) -> None:
    """Fail closed unless local discovery exactly matches names and schemas."""

    descriptors = tuple(discovered_tools)
    if not all(isinstance(tool, MCPToolDescriptor) for tool in descriptors):
        raise ToolRegistryMismatchError("MCP discovery returned malformed tool descriptors")
    names = tuple(tool.name for tool in descriptors)
    if len(set(names)) != len(names):
        raise ToolRegistryMismatchError("MCP discovery returned duplicate tool names")
    actual = frozenset(names)
    if actual != EXPECTED_TOOL_NAMES:
        missing = sorted(EXPECTED_TOOL_NAMES - actual)
        unexpected = sorted(actual - EXPECTED_TOOL_NAMES)
        details: list[str] = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if unexpected:
            details.append(f"unexpected={','.join(unexpected)}")
        raise ToolRegistryMismatchError("MCP tool set mismatch: " + "; ".join(details))
    for descriptor in descriptors:
        reviewed = _TOOLS_BY_NAME[descriptor.name]
        if to_json_value(descriptor.input_schema) != to_json_value(reviewed.mcp_input_schema):
            raise ToolRegistryMismatchError(f"MCP input schema mismatch for tool {descriptor.name}")
        expected_output = (
            None
            if reviewed.result_content is ResultContentKind.IMAGE
            else _mcp_text_output_schema(reviewed.name)
        )
        if to_json_value(descriptor.output_schema) != to_json_value(expected_output):
            raise ToolRegistryMismatchError(f"MCP output schema mismatch for tool {descriptor.name}")


def validate_tool_result(call: ToolCall, result: ToolResult) -> None:
    """Validate correlation and result content against the reviewed tool contract."""

    if call.identity != result.identity:
        raise ToolValidationError("tool result identity does not match the dispatched call")
    if call.name != result.tool_name:
        raise ToolValidationError("tool result name does not match the dispatched call")
    spec = get_tool_spec(call.name)
    if spec.result_content is ResultContentKind.TEXT and result.images:
        raise ToolValidationError(f"{call.name} must not return image content")
    if spec.result_content is ResultContentKind.IMAGE:
        if result.status is ToolResultStatus.SUCCESS and len(result.images) != 1:
            raise ToolValidationError(f"{call.name} must return exactly one image on success")
        if result.status is not ToolResultStatus.SUCCESS and result.images:
            raise ToolValidationError(f"{call.name} must not retain image content on failure")
    if call.name == "type" and result.sanitized_text:
        raise ToolValidationError("type results must not retain text content after result conversion")


def _validate_scalar(name: str, value: object, schema: Mapping[str, object]) -> JSONValue:
    expected_type = schema.get("type")
    if expected_type == "string":
        if not isinstance(value, str):
            raise ToolValidationError(f"{name} must be a string")
        minimum = schema.get("minLength")
        if isinstance(minimum, int) and len(value) < minimum:
            raise ToolValidationError(f"{name} must not be empty")
    elif expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ToolValidationError(f"{name} must be an integer")
    else:
        raise ToolValidationError(f"reviewed schema for {name} has unsupported type")
    return value


def validate_tool_arguments(name: str, arguments: Mapping[str, object]) -> dict[str, JSONValue]:
    """Validate fixed schemas before dispatch; dynamic grounding is later policy."""

    if not isinstance(arguments, Mapping):
        raise ToolValidationError("tool arguments must be an object")
    spec = get_tool_spec(name)
    schema = spec.input_schema
    properties = schema["properties"]
    if not isinstance(properties, Mapping):  # Defensive against accidental registry edits.
        raise ToolValidationError(f"reviewed schema for {name} is malformed")
    non_string_keys = [key for key in arguments if not isinstance(key, str)]
    if non_string_keys:
        raise ToolValidationError(f"{name} argument names must be strings")
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ToolValidationError(f"{name} received unknown argument(s): {', '.join(unknown)}")
    required = schema.get("required", ())
    if not isinstance(required, (list, tuple)):
        raise ToolValidationError(f"reviewed schema for {name} is malformed")
    missing = [field for field in required if field not in arguments]
    if missing:
        raise ToolValidationError(f"{name} is missing required argument(s): {', '.join(missing)}")

    validated: dict[str, JSONValue] = {}
    for field_name, value in arguments.items():
        field_schema = properties[field_name]
        if not isinstance(field_schema, Mapping):
            raise ToolValidationError(f"reviewed schema for {name}.{field_name} is malformed")
        validated[field_name] = _validate_scalar(field_name, value, field_schema)

    if name == "click":
        has_ref = "ref" in validated
        has_coordinates = "x" in validated or "y" in validated
        if has_ref == has_coordinates:
            raise ToolValidationError("click requires exactly one of ref or the x,y coordinate pair")
        if has_coordinates and not {"x", "y"}.issubset(validated):
            raise ToolValidationError("click coordinates require both x and y")
    if name == "ocr":
        x, y, w, h = (validated[field] for field in ("x", "y", "w", "h"))
        if x < 0 or y < 0 or w <= 0 or h <= 0:
            raise ToolValidationError("ocr region must be positive and within the primary display")
        if w * h > 4_000_000:
            raise ToolValidationError("ocr region exceeds the 4000000 pixel limit")
    return validated
