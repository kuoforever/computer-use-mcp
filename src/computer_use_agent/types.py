"""Canonical, provider-neutral types and ports for the Agent Host.

The host uses these types above the provider and MCP boundaries. They are
stdlib-only so contract tests run without a provider key, desktop, or MCP child.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from json import dumps
from math import isfinite
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, Protocol, Sequence, TypeAlias, runtime_checkable

if TYPE_CHECKING:
    from .tool_registry import ToolSpec


AGENT_CONTRACT_VERSION = "0.1.0"
DEFAULT_PROVIDER_REQUEST_BYTES = 8 * 1024 * 1024
MIN_PROVIDER_REQUEST_BYTES = 1024
MAX_PROVIDER_REQUEST_BYTES = 48 * 1024 * 1024
MAX_IMAGE_BYTES = 32 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
REVIEWED_RESULT_CODES = frozenset(
    {
        "ABORTED",
        "APPROVAL_DENIED",
        "BUDGET_EXHAUSTED",
        "DENIED_BY_GATE",
        "DENIED_BY_USER",
        "DRIVER_ERROR",
        "HUMAN_ACTIVE",
        "MCP_CHILD_EXITED_BEFORE_DISPATCH",
        "MCP_PROTOCOL_ERROR",
        "MCP_TIMEOUT_BEFORE_DISPATCH",
        "MCP_TRANSPORT_ERROR",
        "NOT_INVOKABLE",
        "OUT_OF_BOUNDS",
        "PERMISSION_DENIED",
        "POLICY_DENIED",
        "SCHEMA_MISMATCH",
        "STALE_ELEMENT",
    }
)

JSONValue: TypeAlias = (
    None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
)


class ToolEffect(str, Enum):
    """Whether a tool is observational or can change desktop state."""

    OBSERVATION = "observation"
    SIDE_EFFECT = "side_effect"


class ToolCallStatus(str, Enum):
    """Host lifecycle state for a normalized requested tool call."""

    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    REJECTED = "rejected"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ToolResultStatus(str, Enum):
    """Semantic desktop outcome, explicitly separate from a transport failure."""

    SUCCESS = "success"
    ACTION_ERROR = "action_error"
    TRANSPORT_ERROR = "transport_error"
    REJECTED = "rejected"
    UNKNOWN_OUTCOME = "unknown_outcome"


class DispatchCertainty(str, Enum):
    """Whether a desktop call definitely was, was not, or may have been sent."""

    NOT_DISPATCHED = "not_dispatched"
    DISPATCHED = "dispatched"
    UNKNOWN = "unknown"


class RecoveryStatus(str, Enum):
    """Whether a run may continue without human recovery or re-observation."""

    READY = "ready"
    REQUIRES_REOBSERVATION = "requires_reobservation"
    UNKNOWN_OUTCOME = "unknown_outcome"
    STOPPED = "stopped"


class PolicyDecisionKind(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class LedgerEventKind(str, Enum):
    USER_TASK = "user_task"
    MODEL_TURN = "model_turn"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    POLICY_DECISION = "policy_decision"
    OBSERVATION = "observation"
    RECOVERY = "recovery"


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_sha256_digest(value: str, field_name: str = "call_digest") -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a SHA-256 hex digest") from exc


def _copy_json(value: object, field_name: str = "value") -> JSONValue:
    """Return a JSON-compatible defensive copy and reject lossy coercions."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(f"{field_name} must not contain NaN or infinity")
        return value
    if isinstance(value, (list, tuple)):
        return [_copy_json(item, field_name) for item in value]
    if isinstance(value, Mapping):
        copied: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{field_name} object keys must be strings")
            copied[key] = _copy_json(item, field_name)
        return copied
    raise ValueError(f"{field_name} must be JSON-compatible, not {type(value).__name__}")


def _freeze_json(value: JSONValue) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _frozen_json_object(value: Mapping[str, object], field_name: str) -> Mapping[str, object]:
    copied = _copy_json(value, field_name)
    if not isinstance(copied, dict):  # Defensive: Mapping input always becomes a dict.
        raise ValueError(f"{field_name} must be a JSON object")
    frozen = _freeze_json(copied)
    if not isinstance(frozen, Mapping):  # Defensive: a JSON object freezes to a Mapping.
        raise ValueError(f"{field_name} must be a JSON object")
    return frozen


def to_json_value(value: object) -> JSONValue:
    """Return a fresh mutable JSON value for provider wire serialization."""

    return _copy_json(value)


def _contains_key(value: object, prohibited_key: str) -> bool:
    if isinstance(value, Mapping):
        return any(
            key == prohibited_key or _contains_key(item, prohibited_key)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_key(item, prohibited_key) for item in value)
    return False


@dataclass(frozen=True)
class CallIdentity:
    """Run-qualified identifier used for every call/result/approval correlation."""

    run_id: str
    turn_id: str
    call_id: str

    def __post_init__(self) -> None:
        _require_nonempty(self.run_id, "run_id")
        _require_nonempty(self.turn_id, "turn_id")
        _require_nonempty(self.call_id, "call_id")


@dataclass(frozen=True)
class ModelUsage:
    """Normalized usage reported by a provider, when available."""

    input_tokens: int | None = None
    output_tokens: int | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("input_tokens", self.input_tokens),
            ("output_tokens", self.output_tokens),
        ):
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative integer or None")


@dataclass(frozen=True)
class MemoryContextItem:
    """Explicit user-confirmed memory supplied as non-authoritative model context."""

    kind: str
    content: str
    source: str
    scope: str

    def __post_init__(self) -> None:
        if self.kind not in {"preference", "verified_procedure"}:
            raise ValueError("memory context kind is not reviewed")
        _require_nonempty(self.content, "memory context content")
        if len(self.content) > 4096 or any(ord(char) < 32 for char in self.content):
            raise ValueError("memory context content is not bounded text")
        if self.source != "user_confirmed":
            raise ValueError("memory context source must be user_confirmed")
        _require_nonempty(self.scope, "memory context scope")
        if len(self.scope) > 128:
            raise ValueError("memory context scope is too long")


@dataclass(frozen=True)
class ToolCall:
    """A provider request normalized before policy evaluation or dispatch."""

    identity: CallIdentity
    name: str
    arguments: Mapping[str, JSONValue]
    status: ToolCallStatus = ToolCallStatus.REQUESTED

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CallIdentity):
            raise ValueError("identity must be a CallIdentity")
        _require_nonempty(self.name, "name")
        if not isinstance(self.status, ToolCallStatus):
            raise ValueError("status must be a ToolCallStatus")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("arguments must be a JSON object")
        object.__setattr__(self, "arguments", _frozen_json_object(self.arguments, "arguments"))

    @property
    def digest(self) -> str:
        """Stable call fingerprint for approval binding; lifecycle state is excluded."""

        material = {
            "run_id": self.identity.run_id,
            "turn_id": self.identity.turn_id,
            "call_id": self.identity.call_id,
            "name": self.name,
            "arguments": to_json_value(self.arguments),
        }
        encoded = dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ImageContent:
    """Bounded PNG content with parsed dimensions for the current screenshot tool."""

    mime_type: str
    data: bytes
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.mime_type != "image/png":
            raise ValueError("the reviewed MCP surface permits only image/png")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("data must be non-empty bytes")
        if len(self.data) > MAX_IMAGE_BYTES:
            raise ValueError(f"image data exceeds the {MAX_IMAGE_BYTES}-byte contract limit")
        if len(self.data) < 24 or self.data[:8] != PNG_SIGNATURE or self.data[12:16] != b"IHDR":
            raise ValueError("image/png data must begin with a PNG IHDR header")
        parsed_width = int.from_bytes(self.data[16:20], "big")
        parsed_height = int.from_bytes(self.data[20:24], "big")
        for field_name, value in (("width", self.width), ("height", self.height)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if (self.width, self.height) != (parsed_width, parsed_height):
            raise ValueError("PNG dimensions must match the parsed IHDR dimensions")


@dataclass(frozen=True)
class ToolResult:
    """A structured MCP outcome after result conversion and redaction."""

    identity: CallIdentity
    tool_name: str
    status: ToolResultStatus
    dispatch: DispatchCertainty
    sanitized_text: str = ""
    code: str | None = None
    images: tuple[ImageContent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CallIdentity):
            raise ValueError("identity must be a CallIdentity")
        _require_nonempty(self.tool_name, "tool_name")
        if not isinstance(self.status, ToolResultStatus):
            raise ValueError("status must be a ToolResultStatus")
        if not isinstance(self.dispatch, DispatchCertainty):
            raise ValueError("dispatch must be a DispatchCertainty")
        if not isinstance(self.sanitized_text, str):
            raise ValueError("sanitized_text must be a string")
        if self.code is not None:
            _require_nonempty(self.code, "code")
            if self.code not in REVIEWED_RESULT_CODES:
                raise ValueError("code must be one of the reviewed non-sensitive result codes")
        allowed_dispatch = {
            ToolResultStatus.SUCCESS: {DispatchCertainty.DISPATCHED},
            ToolResultStatus.ACTION_ERROR: {DispatchCertainty.DISPATCHED},
            ToolResultStatus.TRANSPORT_ERROR: {DispatchCertainty.NOT_DISPATCHED},
            ToolResultStatus.REJECTED: {DispatchCertainty.NOT_DISPATCHED},
            ToolResultStatus.UNKNOWN_OUTCOME: {
                DispatchCertainty.DISPATCHED,
                DispatchCertainty.UNKNOWN,
            },
        }[self.status]
        if self.dispatch not in allowed_dispatch:
            choices = ", ".join(sorted(value.value for value in allowed_dispatch))
            raise ValueError(f"{self.status.value} requires dispatch in: {choices}")
        if self.status is ToolResultStatus.SUCCESS and self.code is not None:
            raise ValueError("a successful result must not carry an error code")
        if self.status in {
            ToolResultStatus.ACTION_ERROR,
            ToolResultStatus.TRANSPORT_ERROR,
        } and self.code is None:
            raise ValueError("an action or transport error result must carry an error code")
        if not isinstance(self.images, tuple) or not all(
            isinstance(image, ImageContent) for image in self.images
        ):
            raise ValueError("images must be a tuple of ImageContent")
        if self.status is ToolResultStatus.SUCCESS and self.tool_name == "screenshot" and not self.images:
            raise ValueError("a successful screenshot result requires parsed image content")
        if self.tool_name == "type" and self.sanitized_text:
            raise ValueError("a type result must not retain text content")

    @property
    def ok(self) -> bool:
        return self.status is ToolResultStatus.SUCCESS


@dataclass(frozen=True)
class ModelTurn:
    """A provider response independent of its provider wire format."""

    run_id: str
    turn_id: str
    provider_response_id: str
    text: str
    tool_calls: tuple[ToolCall, ...] = ()
    usage: ModelUsage = field(default_factory=ModelUsage)

    def __post_init__(self) -> None:
        _require_nonempty(self.run_id, "run_id")
        _require_nonempty(self.turn_id, "turn_id")
        _require_nonempty(self.provider_response_id, "provider_response_id")
        if not isinstance(self.text, str):
            raise ValueError("text must be a string")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(call, ToolCall) for call in self.tool_calls
        ):
            raise ValueError("tool_calls must be a tuple of ToolCall")
        if not isinstance(self.usage, ModelUsage):
            raise ValueError("usage must be a ModelUsage")
        call_ids = [call.identity.call_id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call identifiers must be unique within a model turn")
        for call in self.tool_calls:
            if call.identity.run_id != self.run_id or call.identity.turn_id != self.turn_id:
                raise ValueError("tool calls must use this model turn's run and turn identity")
            if call.status is not ToolCallStatus.REQUESTED:
                raise ValueError("a provider-returned tool call must have requested status")


@dataclass(frozen=True)
class RunBudget:
    """Hard bounds tracked by the host, never by an untrusted provider."""

    max_model_turns: int
    max_tool_calls: int
    max_side_effects: int
    model_turns_used: int = 0
    tool_calls_used: int = 0
    side_effects_used: int = 0
    max_input_tokens: int = 1_000_000
    input_tokens_used: int = 0

    def __post_init__(self) -> None:
        limits = (
            ("max_model_turns", self.max_model_turns),
            ("max_tool_calls", self.max_tool_calls),
            ("max_side_effects", self.max_side_effects),
            ("max_input_tokens", self.max_input_tokens),
        )
        used = (
            ("model_turns_used", self.model_turns_used, self.max_model_turns),
            ("tool_calls_used", self.tool_calls_used, self.max_tool_calls),
            ("side_effects_used", self.side_effects_used, self.max_side_effects),
        )
        for field_name, value in limits:
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        for field_name, value, limit in used:
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
                raise ValueError(f"{field_name} must be between zero and its configured limit")
        if (
            isinstance(self.input_tokens_used, bool)
            or not isinstance(self.input_tokens_used, int)
            or self.input_tokens_used < 0
        ):
            raise ValueError("input_tokens_used must be a non-negative integer")


@dataclass(frozen=True)
class SafeArgumentSummary:
    """Non-reversible argument metadata suitable for approval and ledger events."""

    tool_name: str
    values: Mapping[str, JSONValue]
    redacted_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty(self.tool_name, "tool_name")
        if not isinstance(self.values, Mapping):
            raise ValueError("values must be a JSON object")
        if not isinstance(self.redacted_fields, tuple) or not all(
            isinstance(field, str) and field for field in self.redacted_fields
        ):
            raise ValueError("redacted_fields must be a tuple of non-empty strings")
        if len(set(self.redacted_fields)) != len(self.redacted_fields):
            raise ValueError("redacted_fields must not contain duplicates")
        frozen_values = _frozen_json_object(self.values, "values")
        for field_name in self.redacted_fields:
            if _contains_key(frozen_values, field_name):
                raise ValueError(f"safe summary must not retain redacted field {field_name}")
        object.__setattr__(self, "values", frozen_values)
        if self.tool_name == "type":
            if "text" not in self.redacted_fields:
                raise ValueError("a type summary must redact text")
            allowed_keys = {"text_present", "text_length", "ref_supplied"}
            unexpected_keys = set(self.values) - allowed_keys
            if unexpected_keys:
                raise ValueError("a type summary may contain only reviewed non-reversible metadata")
            text_length = self.values.get("text_length")
            if isinstance(text_length, bool) or not isinstance(text_length, int) or text_length < 0:
                raise ValueError("a type summary requires non-negative text_length metadata")
            if self.values.get("text_present") is not True:
                raise ValueError("a type summary requires text_present metadata")
            ref_supplied = self.values.get("ref_supplied")
            if not isinstance(ref_supplied, bool):
                raise ValueError("a type summary requires boolean ref_supplied metadata")

    @classmethod
    def from_tool_call(
        cls,
        call: ToolCall,
        *,
        sensitive_arguments: Sequence[str],
    ) -> "SafeArgumentSummary":
        sensitive = frozenset(sensitive_arguments)
        if call.name == "type":
            text = call.arguments.get("text")
            if "text" not in sensitive or not isinstance(text, str):
                raise ValueError("type summaries require text to be a declared sensitive string")
            return cls(
                tool_name="type",
                values={
                    "text_present": True,
                    "text_length": len(text),
                    "ref_supplied": "ref" in call.arguments,
                },
                redacted_fields=("text",),
            )
        values: dict[str, JSONValue] = {}
        redacted: list[str] = []
        for field_name, value in call.arguments.items():
            if field_name in sensitive:
                redacted.append(field_name)
                values[f"{field_name}_present"] = True
                if isinstance(value, str):
                    values[f"{field_name}_length"] = len(value)
                continue
            values[field_name] = to_json_value(value)
        return cls(tool_name=call.name, values=values, redacted_fields=tuple(redacted))


@dataclass(frozen=True)
class PolicyDecision:
    """An approval-bound host policy decision; provider text cannot create one."""

    request_id: str
    identity: CallIdentity
    call_digest: str
    kind: PolicyDecisionKind
    reason: str

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        if not isinstance(self.identity, CallIdentity):
            raise ValueError("identity must be a CallIdentity")
        _require_sha256_digest(self.call_digest)
        if not isinstance(self.kind, PolicyDecisionKind):
            raise ValueError("kind must be a PolicyDecisionKind")
        _require_nonempty(self.reason, "reason")


@dataclass(frozen=True)
class ApprovalRequest:
    """A human request bound to one call without retaining raw sensitive input."""

    request_id: str
    identity: CallIdentity
    tool_name: str
    call_digest: str
    reason: str
    safe_argument_summary: SafeArgumentSummary

    def __post_init__(self) -> None:
        _require_nonempty(self.request_id, "request_id")
        if not isinstance(self.identity, CallIdentity):
            raise ValueError("identity must be a CallIdentity")
        _require_nonempty(self.tool_name, "tool_name")
        _require_sha256_digest(self.call_digest)
        if not isinstance(self.safe_argument_summary, SafeArgumentSummary):
            raise ValueError("safe_argument_summary must be a SafeArgumentSummary")
        if self.safe_argument_summary.tool_name != self.tool_name:
            raise ValueError("safe_argument_summary must describe the requested tool")
        _require_nonempty(self.reason, "reason")

    @classmethod
    def from_tool_call(
        cls,
        *,
        request_id: str,
        call: ToolCall,
        reason: str,
        sensitive_arguments: Sequence[str],
    ) -> "ApprovalRequest":
        return cls(
            request_id=request_id,
            identity=call.identity,
            tool_name=call.name,
            call_digest=call.digest,
            reason=reason,
            safe_argument_summary=SafeArgumentSummary.from_tool_call(
                call, sensitive_arguments=sensitive_arguments
            ),
        )

    def matches(self, decision: PolicyDecision) -> bool:
        return (
            self.request_id == decision.request_id
            and self.identity == decision.identity
            and self.call_digest == decision.call_digest
        )


@dataclass(frozen=True)
class LedgerEvent:
    """One canonical, sanitized event in the host-owned replay ledger."""

    event_id: str
    kind: LedgerEventKind
    payload: Mapping[str, JSONValue] = field(default_factory=dict)
    identity: CallIdentity | None = None
    safe_argument_summary: SafeArgumentSummary | None = None
    tool_result: ToolResult | None = None
    policy_decision: PolicyDecision | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.event_id, "event_id")
        if not isinstance(self.kind, LedgerEventKind):
            raise ValueError("kind must be a LedgerEventKind")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a JSON object")
        frozen_payload = _frozen_json_object(self.payload, "payload")
        object.__setattr__(self, "payload", frozen_payload)
        if self.identity is not None and not isinstance(self.identity, CallIdentity):
            raise ValueError("identity must be a CallIdentity or None")
        if self.safe_argument_summary is not None and not isinstance(
            self.safe_argument_summary, SafeArgumentSummary
        ):
            raise ValueError("safe_argument_summary must be a SafeArgumentSummary or None")
        if self.tool_result is not None and not isinstance(self.tool_result, ToolResult):
            raise ValueError("tool_result must be a ToolResult or None")
        if self.policy_decision is not None and not isinstance(
            self.policy_decision, PolicyDecision
        ):
            raise ValueError("policy_decision must be a PolicyDecision or None")
        if self.kind is LedgerEventKind.TOOL_CALL:
            if self.identity is None or self.safe_argument_summary is None:
                raise ValueError("a tool-call event requires identity and a safe argument summary")
            if self.tool_result is not None or self.policy_decision is not None:
                raise ValueError("a tool-call event cannot carry a result or policy decision")
            for field_name in self.safe_argument_summary.redacted_fields:
                if _contains_key(frozen_payload, field_name):
                    raise ValueError("tool-call payload must not retain a redacted argument")
            if self.safe_argument_summary.tool_name == "type" and frozen_payload:
                raise ValueError("a typed-text tool-call event must not carry arbitrary payload data")
        if self.kind is LedgerEventKind.TOOL_RESULT:
            if self.identity is None or self.tool_result is None:
                raise ValueError("a tool-result event requires identity and a ToolResult")
            if self.identity != self.tool_result.identity:
                raise ValueError("tool-result event identity must match its ToolResult")
        if self.kind is LedgerEventKind.POLICY_DECISION:
            if self.identity is None or self.policy_decision is None:
                raise ValueError("a policy event requires identity and a PolicyDecision")
            if self.identity != self.policy_decision.identity:
                raise ValueError("policy event identity must match its PolicyDecision")


@dataclass(frozen=True)
class RunState:
    """All state required to resume or audit a bounded Agent run."""

    run_id: str
    task: str
    policy_version: str
    observation_epoch: int
    budgets: RunBudget
    event_log: tuple[LedgerEvent, ...] = ()
    recovery_status: RecoveryStatus = RecoveryStatus.READY
    verified_observation_epoch: int | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.run_id, "run_id")
        _require_nonempty(self.task, "task")
        _require_nonempty(self.policy_version, "policy_version")
        if (
            isinstance(self.observation_epoch, bool)
            or not isinstance(self.observation_epoch, int)
            or self.observation_epoch < 0
        ):
            raise ValueError("observation_epoch must be a non-negative integer")
        if self.verified_observation_epoch is not None and (
            isinstance(self.verified_observation_epoch, bool)
            or not isinstance(self.verified_observation_epoch, int)
            or not 0 <= self.verified_observation_epoch <= self.observation_epoch
        ):
            raise ValueError("verified_observation_epoch must be within the observation epoch range")
        if not isinstance(self.budgets, RunBudget):
            raise ValueError("budgets must be a RunBudget")
        if not isinstance(self.event_log, tuple) or not all(
            isinstance(event, LedgerEvent) for event in self.event_log
        ):
            raise ValueError("event_log must be a tuple of LedgerEvent")
        if not isinstance(self.recovery_status, RecoveryStatus):
            raise ValueError("recovery_status must be a RecoveryStatus")
        issued_calls: dict[CallIdentity, SafeArgumentSummary] = {}
        has_unknown_outcome = False
        for event in self.event_log:
            if event.identity is not None and event.identity.run_id != self.run_id:
                raise ValueError("ledger call identity must belong to this run")
            if event.kind is LedgerEventKind.TOOL_CALL:
                if event.identity in issued_calls:
                    raise ValueError("ledger cannot issue the same call identity twice")
                issued_calls[event.identity] = event.safe_argument_summary
            elif event.kind in {LedgerEventKind.TOOL_RESULT, LedgerEventKind.POLICY_DECISION}:
                if event.identity not in issued_calls:
                    raise ValueError("ledger result or policy decision must follow its tool call")
                if (
                    event.kind is LedgerEventKind.TOOL_RESULT
                    and event.tool_result.tool_name != issued_calls[event.identity].tool_name
                ):
                    raise ValueError("ledger tool result must match its issued tool name")
                if (
                    event.kind is LedgerEventKind.TOOL_RESULT
                    and event.tool_result.status is ToolResultStatus.UNKNOWN_OUTCOME
                ):
                    has_unknown_outcome = True
        if has_unknown_outcome and self.recovery_status is not RecoveryStatus.UNKNOWN_OUTCOME:
            raise ValueError("an unknown tool outcome requires unknown_outcome recovery status")


@dataclass(frozen=True)
class MCPToolDescriptor:
    """Normalized input/output schemas returned by local stdio MCP discovery."""

    name: str
    input_schema: Mapping[str, JSONValue]
    output_schema: Mapping[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        _require_nonempty(self.name, "name")
        if not isinstance(self.input_schema, Mapping):
            raise ValueError("input_schema must be a JSON object")
        object.__setattr__(
            self,
            "input_schema",
            _frozen_json_object(self.input_schema, "input_schema"),
        )
        if self.output_schema is not None:
            if not isinstance(self.output_schema, Mapping):
                raise ValueError("output_schema must be a JSON object or None")
            object.__setattr__(
                self,
                "output_schema",
                _frozen_json_object(self.output_schema, "output_schema"),
            )


@runtime_checkable
class ModelProviderPort(Protocol):
    """Provider adapter boundary. Implementations compile the reviewed registry."""

    name: str

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence["ToolSpec"],
        memories: Sequence[MemoryContextItem] = (),
    ) -> ModelTurn: ...

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]: ...

    def restore_continuation(
        self, run_id: str, state: Mapping[str, JSONValue]
    ) -> None: ...


@runtime_checkable
class DesktopMCPPort(Protocol):
    """The only permitted desktop execution boundary for the Agent Host."""

    @property
    def generation(self) -> int: ...

    async def discover_tools(self) -> tuple[MCPToolDescriptor, ...]: ...

    async def call_tool(self, call: ToolCall) -> ToolResult: ...

    async def close(self) -> None: ...


@runtime_checkable
class ApprovalPort(Protocol):
    """Local approval boundary; an adapter cannot approve its own action."""

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision: ...
