"""Pure-local disclosure and exact acknowledgement for Formal Demo intent data.

This module owns no provider, network, Runner, MCP, desktop, application,
persistence, clock, or launcher port.  It holds the exact task text only so a
local operator can review what one future intent-compilation request would
disclose.  Its permit is opaque, process-local, and inert.  Consuming a permit
marks one gate instance terminal and returns a content-free receipt; it never
returns a replayable request envelope or dispatches external work.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from threading import Lock
from types import MappingProxyType
from typing import Mapping, Never, SupportsIndex, TypeVar, cast

from .formal_demo_contract import MAX_SOURCE_TASK_BYTES, TASK_INTENT_VERSION
from .provider_catalog import (
    ProviderProtocol,
    provider_profile,
    resolve_provider_route,
)


INTENT_DISCLOSURE_VERSION = 1
INTENT_COMPILE_PERMIT_VERSION = 1
INTENT_COMPILE_TOKEN = "COMPILE"
INTENT_COMPILE_OPERATION = "compile_untrusted_task_intent_candidate"
INTENT_COMPILE_REQUEST_LIMIT = 1

MAX_MODEL_ID_CHARS = 160
MAX_ENDPOINT_CHARS = 512
MAX_NOTICE_CHARS = 1024

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")
_BOUND_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_WORKSPACE_ID = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_T = TypeVar("_T")

_PURPOSE = (
    "Compile one untrusted TaskIntent v1 candidate from the exact disclosed "
    "task text without tools or desktop authority."
)
_EXTERNAL_DATA_USE = (
    "The exact task text would be sent to the selected provider API route only "
    "to request one untrusted TaskIntent v1 candidate. GDA would not append "
    "credentials, tools, screenshots, files, desktop observations, or application "
    "content, but anything the operator included in the exact displayed task text "
    "would be disclosed. Transport authentication and account controls are "
    "outside this slice."
)
_EXTERNAL_RETENTION = (
    "GDA has not verified a no-retention guarantee for this route. A future "
    "live slice must revalidate the selected account's current provider terms "
    "and data controls before sending."
)
_LOCAL_DATA_USE = (
    "The exact task text would be sent only to the configured loopback endpoint "
    "to request one untrusted TaskIntent v1 candidate. GDA would not append "
    "credentials, tools, screenshots, files, desktop observations, or application "
    "content, but anything the operator included in the exact displayed task text "
    "would be disclosed. Loopback server authentication and controls are outside "
    "this slice."
)
_LOCAL_RETENTION = (
    "The configured loopback server, not GDA, controls storage and retention. "
    "This contract does not verify that server's behavior."
)


class FormalDemoIntentGateError(ValueError):
    """Fixed, content-free failure at the local disclosure boundary."""


class IntentCompileGateState(str, Enum):
    READY = "ready"
    PERMITTED = "permitted"
    CONSUMED = "consumed"
    CANCELLED = "cancelled"


def _canonical_json_bytes(payload: object) -> bytes:
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_GATE_CANONICAL_JSON_INVALID"
        ) from None


def _content_digest(domain: str, payload: object) -> str:
    return sha256(
        _canonical_json_bytes({"domain": domain, "payload": payload})
    ).hexdigest()


def _require_exact_type(
    value: object,
    expected: type[_T],
    *,
    code: str,
) -> _T:
    if type(value) is not expected:
        raise FormalDemoIntentGateError(code)
    return cast(_T, value)


def _has_unsafe_display_character(value: str) -> bool:
    return any(
        unicodedata.category(char) in {"Cc", "Cf", "Zl", "Zp"}
        for char in value
    )


def _require_text(value: object, *, limit: int, code: str) -> str:
    text = _require_exact_type(value, str, code=code)
    if (
        not text
        or text != text.strip()
        or len(text) > limit
        or _CONTROL.search(text) is not None
        or _has_unsafe_display_character(text)
    ):
        raise FormalDemoIntentGateError(code)
    try:
        text.encode("utf-8")
    except UnicodeError:
        raise FormalDemoIntentGateError(code) from None
    return text


def _require_identifier(value: object, *, code: str) -> str:
    selected = _require_exact_type(value, str, code=code)
    if _IDENTIFIER.fullmatch(selected) is None:
        raise FormalDemoIntentGateError(code)
    return selected


def _require_bound_identity(value: object, *, code: str) -> str:
    selected = _require_exact_type(value, str, code=code)
    if _BOUND_IDENTITY.fullmatch(selected) is None:
        raise FormalDemoIntentGateError(code)
    return selected


def _require_digest(value: object, *, code: str) -> str:
    selected = _require_exact_type(value, str, code=code)
    if _DIGEST.fullmatch(selected) is None:
        raise FormalDemoIntentGateError(code)
    return selected


def _source_task_digest(source_task: object) -> str:
    task = _require_exact_type(
        source_task,
        str,
        code="FORMAL_DEMO_INTENT_DISCLOSURE_TASK_INVALID",
    )
    if not task.strip() or "\x00" in task:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_TASK_INVALID"
        )
    try:
        encoded = task.encode("utf-8")
    except UnicodeError:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_TASK_INVALID"
        ) from None
    if len(encoded) > MAX_SOURCE_TASK_BYTES:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_TASK_TOO_LARGE"
        )
    return sha256(encoded).hexdigest()


def _display_json_string(value: str) -> str:
    """Render exact text without allowing terminal or line-boundary spoofing."""

    try:
        rendered = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, UnicodeError):
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_TASK_INVALID"
        ) from None
    output: list[str] = []
    for char in rendered:
        category = unicodedata.category(char)
        if category in {"Cc", "Cf", "Zl", "Zp"}:
            output.append(json.dumps(char, ensure_ascii=True)[1:-1])
        else:
            output.append(char)
    return "".join(output)


@dataclass(frozen=True, slots=True)
class ProviderIntentRoute:
    """Exact inert identity validated against the reviewed provider catalog."""

    provider_id: str
    region: str
    model_id: str
    protocol: ProviderProtocol
    endpoint: str
    workspace_id: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(
            self.provider_id,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        _require_identifier(self.region, code="FORMAL_DEMO_INTENT_ROUTE_INVALID")
        _require_text(
            self.model_id,
            limit=MAX_MODEL_ID_CHARS,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        if type(self.protocol) is not ProviderProtocol:
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
        _require_text(
            self.endpoint,
            limit=MAX_ENDPOINT_CHARS,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        if self.workspace_id is not None and (
            type(self.workspace_id) is not str
            or _WORKSPACE_ID.fullmatch(self.workspace_id) is None
        ):
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
        try:
            resolved = resolve_provider_route(
                self.provider_id,
                region=self.region,
                workspace_id=self.workspace_id,
                base_url=self.endpoint,
            )
            reviewed_protocol = provider_profile(self.provider_id).protocol
        except ValueError:
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID") from None
        if (
            resolved.name != self.provider_id
            or resolved.region != self.region
            or resolved.base_url != self.endpoint
            or resolved.workspace_id != self.workspace_id
            or reviewed_protocol is not self.protocol
        ):
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "region": self.region,
            "model_id": self.model_id,
            "protocol": self.protocol.value,
            "endpoint": self.endpoint,
            "workspace_id": self.workspace_id,
        }

    @property
    def content_digest(self) -> str:
        return _content_digest(
            "formal-demo-intent-route-v1",
            self.canonical_payload(),
        )


def _verify_reviewed_route(route: object) -> ProviderIntentRoute:
    if type(route) is not ProviderIntentRoute:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
    try:
        provider_id = _require_identifier(
            route.provider_id,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        region = _require_identifier(
            route.region,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        _require_text(
            route.model_id,
            limit=MAX_MODEL_ID_CHARS,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        if type(route.protocol) is not ProviderProtocol:
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
        endpoint = _require_text(
            route.endpoint,
            limit=MAX_ENDPOINT_CHARS,
            code="FORMAL_DEMO_INTENT_ROUTE_INVALID",
        )
        if route.workspace_id is not None and (
            type(route.workspace_id) is not str
            or _WORKSPACE_ID.fullmatch(route.workspace_id) is None
        ):
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
        resolved = resolve_provider_route(
            provider_id,
            region=region,
            workspace_id=route.workspace_id,
            base_url=endpoint,
        )
        reviewed_protocol = provider_profile(provider_id).protocol
        if (
            resolved.name != provider_id
            or resolved.region != region
            or resolved.base_url != endpoint
            or resolved.workspace_id != route.workspace_id
            or reviewed_protocol is not route.protocol
        ):
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
        route.content_digest
    except FormalDemoIntentGateError:
        raise
    except Exception:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID") from None
    return route


@dataclass(frozen=True, slots=True)
class ReviewedIntentDisclosureProfile:
    """Host-reviewed warning text, not provider availability or legal advice."""

    profile_id: str
    provider_id: str
    data_use_notice: str
    retention_notice: str
    version: int = INTENT_DISCLOSURE_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != INTENT_DISCLOSURE_VERSION:
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_VERSION_UNSUPPORTED"
            )
        _require_identifier(
            self.profile_id,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_INVALID",
        )
        _require_identifier(
            self.provider_id,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_INVALID",
        )
        _require_text(
            self.data_use_notice,
            limit=MAX_NOTICE_CHARS,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_NOTICE_INVALID",
        )
        _require_text(
            self.retention_notice,
            limit=MAX_NOTICE_CHARS,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_NOTICE_INVALID",
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "data_use_notice": self.data_use_notice,
            "retention_notice": self.retention_notice,
        }

    @property
    def content_digest(self) -> str:
        return _content_digest(
            "formal-demo-intent-disclosure-profile-v1",
            self.canonical_payload(),
        )


def _disclosure_profile_payload(provider_id: str) -> tuple[str, str, str, str, int]:
    local = provider_id == "local_openai"
    return (
        f"formal_demo_{provider_id}_disclosure_v1",
        provider_id,
        _LOCAL_DATA_USE if local else _EXTERNAL_DATA_USE,
        _LOCAL_RETENTION if local else _EXTERNAL_RETENTION,
        INTENT_DISCLOSURE_VERSION,
    )


_REVIEWED_DISCLOSURE_PROFILE_PAYLOADS = tuple(
    _disclosure_profile_payload(provider_id)
    for provider_id in (
        "anthropic",
        "deepseek",
        "doubao",
        "glm",
        "kimi",
        "local_openai",
        "minimax",
        "openai",
        "qwen",
    )
)
_REVIEWED_DISCLOSURE_PROFILE_PAYLOADS_BY_ID: Mapping[
    str, tuple[str, str, str, str, int]
] = MappingProxyType(
    {payload[0]: payload for payload in _REVIEWED_DISCLOSURE_PROFILE_PAYLOADS}
)


def _profile_from_payload(
    payload: tuple[str, str, str, str, int],
) -> ReviewedIntentDisclosureProfile:
    profile_id, provider_id, data_use_notice, retention_notice, version = payload
    return ReviewedIntentDisclosureProfile(
        profile_id=profile_id,
        provider_id=provider_id,
        data_use_notice=data_use_notice,
        retention_notice=retention_notice,
        version=version,
    )


def reviewed_intent_disclosure_profiles() -> tuple[ReviewedIntentDisclosureProfile, ...]:
    """Return fresh immutable snapshots; private literals remain authoritative."""

    return tuple(
        _profile_from_payload(payload)
        for payload in _REVIEWED_DISCLOSURE_PROFILE_PAYLOADS
    )


def resolve_reviewed_intent_disclosure_profile(
    profile_id: object,
    *,
    version: object,
    expected_digest: object,
) -> ReviewedIntentDisclosureProfile:
    """Resolve one exact code-reviewed warning pin without latest fallback."""

    selected_id = _require_identifier(
        profile_id,
        code="FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_INVALID",
    )
    if type(version) is not int or version != INTENT_DISCLOSURE_VERSION:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_VERSION_UNSUPPORTED"
        )
    selected_digest = _require_digest(
        expected_digest,
        code="FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_INVALID",
    )
    payload = _REVIEWED_DISCLOSURE_PROFILE_PAYLOADS_BY_ID.get(selected_id)
    if payload is None:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_UNAVAILABLE"
        )
    profile = _profile_from_payload(payload)
    if profile.version != version or profile.content_digest != selected_digest:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_PIN_MISMATCH"
        )
    return _profile_from_payload(payload)


@dataclass(frozen=True, slots=True, repr=False)
class FormalDemoIntentDisclosure:
    """Exact local review of data one future tool-free request would expose."""

    disclosure_id: str
    resume_identity: str
    source_task: str = field(repr=False)
    route: ProviderIntentRoute
    profile_id: str
    profile_version: int
    profile_digest: str
    data_use_notice: str
    retention_notice: str
    purpose: str = _PURPOSE
    task_intent_version: int = TASK_INTENT_VERSION
    version: int = INTENT_DISCLOSURE_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != INTENT_DISCLOSURE_VERSION:
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_VERSION_UNSUPPORTED"
            )
        if (
            type(self.task_intent_version) is not int
            or self.task_intent_version != TASK_INTENT_VERSION
        ):
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_SCHEMA_INVALID"
            )
        _require_bound_identity(
            self.disclosure_id,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_ID_INVALID",
        )
        _require_bound_identity(
            self.resume_identity,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_ID_INVALID",
        )
        _source_task_digest(self.source_task)
        _verify_reviewed_route(self.route)
        _require_identifier(
            self.profile_id,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_INVALID",
        )
        if (
            type(self.profile_version) is not int
            or self.profile_version != INTENT_DISCLOSURE_VERSION
        ):
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_VERSION_UNSUPPORTED"
            )
        _require_digest(
            self.profile_digest,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_INVALID",
        )
        _require_text(
            self.data_use_notice,
            limit=MAX_NOTICE_CHARS,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_NOTICE_INVALID",
        )
        _require_text(
            self.retention_notice,
            limit=MAX_NOTICE_CHARS,
            code="FORMAL_DEMO_INTENT_DISCLOSURE_NOTICE_INVALID",
        )
        if self.purpose != _PURPOSE:
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_PURPOSE_INVALID"
            )
        profile = resolve_reviewed_intent_disclosure_profile(
            self.profile_id,
            version=self.profile_version,
            expected_digest=self.profile_digest,
        )
        if (
            self.route.provider_id != profile.provider_id
            or self.data_use_notice != profile.data_use_notice
            or self.retention_notice != profile.retention_notice
        ):
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_MISMATCH"
            )

    @property
    def source_task_digest(self) -> str:
        return _source_task_digest(self.source_task)

    def bound_payload(self) -> dict[str, object]:
        """Return digest input only; the exact task remains local display data."""

        return {
            "version": self.version,
            "disclosure_id": self.disclosure_id,
            "resume_identity": self.resume_identity,
            "source_task_digest": self.source_task_digest,
            "route": self.route.canonical_payload(),
            "route_digest": self.route.content_digest,
            "profile": {
                "profile_id": self.profile_id,
                "version": self.profile_version,
                "digest": self.profile_digest,
            },
            "purpose": self.purpose,
            "task_intent_version": self.task_intent_version,
            "data_use_notice": self.data_use_notice,
            "retention_notice": self.retention_notice,
            "contains_credential_value": False,
            "provider_readiness_checked": False,
            "external_work_started": False,
            "provider_request_started": False,
            "durable_workflow_started": False,
            "grants_provider_request": False,
            "grants_execution_authority": False,
            "grants_scope_or_start": False,
            "grants_action_approval": False,
            "grants_retry_or_replay": False,
        }

    @property
    def content_digest(self) -> str:
        return _content_digest(
            "formal-demo-intent-disclosure-v1",
            self.bound_payload(),
        )

    def render(self) -> str:
        workspace = (
            "none" if self.route.workspace_id is None else self.route.workspace_id
        )
        return "\n".join(
            (
                "Formal Demo intent disclosure - nothing external has started",
                f"Disclosure: {self.disclosure_id}",
                f"Draft identity: {self.resume_identity}",
                f"Provider: {self.route.provider_id}",
                f"Region: {self.route.region}",
                f"Model: {self.route.model_id}",
                f"Protocol: {self.route.protocol.value}",
                f"Endpoint: {self.route.endpoint}",
                f"Workspace: {workspace}",
                "Exact text that a future request would disclose "
                "(UTF-8 JSON string literal):",
                _display_json_string(self.source_task),
                f"Purpose: {self.purpose}",
                f"Data use: {self.data_use_notice}",
                f"Retention: {self.retention_notice}",
                "No credential readiness check or provider request has occurred.",
                "No MCP, desktop, application, durable run, Scope Sheet, START, "
                "action approval, retry, or replay has been authorized.",
                "Type COMPILE exactly to issue one process-local inert permit; "
                "this gate will still make no provider request.",
            )
        ) + "\n"

    def __repr__(self) -> str:
        return "<FormalDemoIntentDisclosure local-sensitive>"

    def __copy__(self) -> FormalDemoIntentDisclosure:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_DISCLOSURE_OPAQUE")

    def __deepcopy__(self, _memo: object) -> FormalDemoIntentDisclosure:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_DISCLOSURE_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_DISCLOSURE_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_DISCLOSURE_OPAQUE")


@dataclass(frozen=True, slots=True, repr=False, eq=False)
class IntentCompilePermit:
    """Opaque process-local permit; only its issuing gate instance may consume it."""

    permit_id: str
    disclosure_id: str
    resume_identity: str
    disclosure_digest: str
    source_task_digest: str
    route_digest: str
    profile_digest: str
    task_intent_version: int
    _gate_identity: object = field(repr=False, compare=False)
    version: int = INTENT_COMPILE_PERMIT_VERSION

    def __post_init__(self) -> None:
        if type(self.version) is not int or self.version != INTENT_COMPILE_PERMIT_VERSION:
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_PERMIT_VERSION_UNSUPPORTED"
            )
        _require_digest(self.permit_id, code="FORMAL_DEMO_INTENT_PERMIT_INVALID")
        _require_bound_identity(
            self.disclosure_id,
            code="FORMAL_DEMO_INTENT_PERMIT_INVALID",
        )
        _require_bound_identity(
            self.resume_identity,
            code="FORMAL_DEMO_INTENT_PERMIT_INVALID",
        )
        for value in (
            self.disclosure_digest,
            self.source_task_digest,
            self.route_digest,
            self.profile_digest,
        ):
            _require_digest(value, code="FORMAL_DEMO_INTENT_PERMIT_INVALID")
        if (
            type(self.task_intent_version) is not int
            or self.task_intent_version != TASK_INTENT_VERSION
        ):
            raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_PERMIT_INVALID")

    def _canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "permit_id": self.permit_id,
            "disclosure_id": self.disclosure_id,
            "resume_identity": self.resume_identity,
            "disclosure_digest": self.disclosure_digest,
            "source_task_digest": self.source_task_digest,
            "route_digest": self.route_digest,
            "profile_digest": self.profile_digest,
            "operation": INTENT_COMPILE_OPERATION,
            "request_limit": INTENT_COMPILE_REQUEST_LIMIT,
            "task_intent_version": self.task_intent_version,
            "tools_allowed": False,
            "provider_request_started": False,
            "desktop_authority": False,
            "durable_workflow_authority": False,
            "scope_start_authority": False,
            "action_approval_authority": False,
            "retry_authority": False,
            "replay_authority": False,
            "state": "issued",
        }

    @property
    def content_digest(self) -> str:
        return _content_digest(
            "formal-demo-intent-compile-permit-v1",
            self._canonical_payload(),
        )

    def __repr__(self) -> str:
        return "<IntentCompilePermit opaque>"

    def __copy__(self) -> IntentCompilePermit:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_PERMIT_OPAQUE")

    def __deepcopy__(self, _memo: object) -> IntentCompilePermit:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_PERMIT_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_PERMIT_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_PERMIT_OPAQUE")


@dataclass(frozen=True, slots=True)
class IntentCompileConsumption:
    """Content-free terminal receipt; it is not a request or bearer credential."""

    permit_digest: str
    disclosure_digest: str
    resume_identity: str
    source_task_digest: str
    route_digest: str
    profile_digest: str
    state: IntentCompileGateState = IntentCompileGateState.CONSUMED
    provider_request_started: bool = False
    grants_execution_authority: bool = False
    grants_retry_or_replay: bool = False

    def __post_init__(self) -> None:
        for value in (
            self.permit_digest,
            self.disclosure_digest,
            self.source_task_digest,
            self.route_digest,
            self.profile_digest,
        ):
            _require_digest(value, code="FORMAL_DEMO_INTENT_CONSUMPTION_INVALID")
        _require_bound_identity(
            self.resume_identity,
            code="FORMAL_DEMO_INTENT_CONSUMPTION_INVALID",
        )
        if (
            self.state is not IntentCompileGateState.CONSUMED
            or self.provider_request_started is not False
            or self.grants_execution_authority is not False
            or self.grants_retry_or_replay is not False
        ):
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_CONSUMPTION_INVALID"
            )


def compile_intent_disclosure(
    *,
    disclosure_id: str,
    resume_identity: str,
    source_task: str,
    route: ProviderIntentRoute,
    profile_id: str,
    profile_version: int,
    expected_profile_digest: str,
) -> FormalDemoIntentDisclosure:
    """Compile one exact local disclosure from a code-reviewed warning pin."""

    if type(route) is not ProviderIntentRoute:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_ROUTE_INVALID")
    _verify_reviewed_route(route)
    profile = resolve_reviewed_intent_disclosure_profile(
        profile_id,
        version=profile_version,
        expected_digest=expected_profile_digest,
    )
    if route.provider_id != profile.provider_id:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_MISMATCH"
        )
    return FormalDemoIntentDisclosure(
        disclosure_id=disclosure_id,
        resume_identity=resume_identity,
        source_task=source_task,
        route=route,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        profile_digest=profile.content_digest,
        data_use_notice=profile.data_use_notice,
        retention_notice=profile.retention_notice,
    )


def _verify_reviewed_disclosure(disclosure: object) -> FormalDemoIntentDisclosure:
    """Reconstruct every bound field so frozen-object tamper cannot be re-signed."""

    if type(disclosure) is not FormalDemoIntentDisclosure:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_DISCLOSURE_INVALID")
    try:
        snapshot = FormalDemoIntentDisclosure(
            disclosure_id=disclosure.disclosure_id,
            resume_identity=disclosure.resume_identity,
            source_task=disclosure.source_task,
            route=disclosure.route,
            profile_id=disclosure.profile_id,
            profile_version=disclosure.profile_version,
            profile_digest=disclosure.profile_digest,
            data_use_notice=disclosure.data_use_notice,
            retention_notice=disclosure.retention_notice,
            purpose=disclosure.purpose,
            task_intent_version=disclosure.task_intent_version,
            version=disclosure.version,
        )
        if snapshot.bound_payload() != disclosure.bound_payload():
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_STALE"
            )
    except FormalDemoIntentGateError:
        raise
    except Exception:
        raise FormalDemoIntentGateError(
            "FORMAL_DEMO_INTENT_DISCLOSURE_STALE"
        ) from None
    return disclosure


class IntentCompileGate:
    """Thread-safe process-local state machine for exact acknowledgement."""

    def __init__(self, disclosure: FormalDemoIntentDisclosure) -> None:
        self._disclosure = _verify_reviewed_disclosure(disclosure)
        self._disclosure_digest = disclosure.content_digest
        self._identity = object()
        self._state = IntentCompileGateState.READY
        self._issued_permit: IntentCompilePermit | None = None
        self._issued_permit_digest: str | None = None
        self._lock = Lock()

    def __copy__(self) -> IntentCompileGate:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_OPAQUE")

    def __deepcopy__(self, _memo: object) -> IntentCompileGate:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_OPAQUE")

    @property
    def state(self) -> IntentCompileGateState:
        with self._lock:
            return self._state

    @property
    def disclosure(self) -> FormalDemoIntentDisclosure:
        return self._disclosure

    def _verify_current_disclosure(self) -> None:
        _verify_reviewed_disclosure(self._disclosure)
        if self._disclosure.content_digest != self._disclosure_digest:
            raise FormalDemoIntentGateError(
                "FORMAL_DEMO_INTENT_DISCLOSURE_STALE"
            )

    def acknowledge(self, token: object) -> IntentCompilePermit:
        with self._lock:
            if self._state is not IntentCompileGateState.READY:
                raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_TERMINAL")
            if type(token) is not str or token != INTENT_COMPILE_TOKEN:
                self._state = IntentCompileGateState.CANCELLED
                raise FormalDemoIntentGateError(
                    "FORMAL_DEMO_INTENT_ACKNOWLEDGEMENT_INVALID"
                )
            try:
                self._verify_current_disclosure()
            except Exception:
                self._state = IntentCompileGateState.CANCELLED
                raise FormalDemoIntentGateError(
                    "FORMAL_DEMO_INTENT_DISCLOSURE_STALE"
                ) from None
            permit_id = _content_digest(
                "formal-demo-intent-compile-permit-id-v1",
                {"disclosure_digest": self._disclosure_digest},
            )
            permit = IntentCompilePermit(
                permit_id=permit_id,
                disclosure_id=self._disclosure.disclosure_id,
                resume_identity=self._disclosure.resume_identity,
                disclosure_digest=self._disclosure_digest,
                source_task_digest=self._disclosure.source_task_digest,
                route_digest=self._disclosure.route.content_digest,
                profile_digest=self._disclosure.profile_digest,
                task_intent_version=self._disclosure.task_intent_version,
                _gate_identity=self._identity,
            )
            self._issued_permit = permit
            self._issued_permit_digest = permit.content_digest
            self._state = IntentCompileGateState.PERMITTED
            return permit

    def cancel(self) -> None:
        with self._lock:
            if self._state is not IntentCompileGateState.READY:
                raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_TERMINAL")
            self._state = IntentCompileGateState.CANCELLED

    def consume(
        self,
        permit: IntentCompilePermit,
        *,
        current_disclosure: FormalDemoIntentDisclosure,
    ) -> IntentCompileConsumption:
        with self._lock:
            if self._state is not IntentCompileGateState.PERMITTED:
                raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_GATE_TERMINAL")
            try:
                self._verify_current_disclosure()
                _verify_reviewed_disclosure(current_disclosure)
                matches = (
                    type(current_disclosure) is FormalDemoIntentDisclosure
                    and current_disclosure.content_digest == self._disclosure_digest
                    and
                    type(permit) is IntentCompilePermit
                    and permit is self._issued_permit
                    and permit._gate_identity is self._identity
                    and permit.disclosure_id == self._disclosure.disclosure_id
                    and permit.resume_identity == self._disclosure.resume_identity
                    and permit.disclosure_digest == self._disclosure_digest
                    and permit.source_task_digest
                    == self._disclosure.source_task_digest
                    and permit.route_digest == self._disclosure.route.content_digest
                    and permit.profile_digest == self._disclosure.profile_digest
                    and permit.task_intent_version
                    == self._disclosure.task_intent_version
                    and permit.content_digest == self._issued_permit_digest
                )
            except BaseException:
                matches = False
            if not matches:
                self._state = IntentCompileGateState.CANCELLED
                raise FormalDemoIntentGateError("FORMAL_DEMO_INTENT_PERMIT_MISMATCH")
            self._state = IntentCompileGateState.CONSUMED
            return IntentCompileConsumption(
                permit_digest=permit.content_digest,
                disclosure_digest=permit.disclosure_digest,
                resume_identity=permit.resume_identity,
                source_task_digest=permit.source_task_digest,
                route_digest=permit.route_digest,
                profile_digest=permit.profile_digest,
            )


__all__ = [
    "FormalDemoIntentDisclosure",
    "FormalDemoIntentGateError",
    "INTENT_COMPILE_OPERATION",
    "INTENT_COMPILE_PERMIT_VERSION",
    "INTENT_COMPILE_REQUEST_LIMIT",
    "INTENT_COMPILE_TOKEN",
    "INTENT_DISCLOSURE_VERSION",
    "IntentCompileConsumption",
    "IntentCompileGate",
    "IntentCompileGateState",
    "IntentCompilePermit",
    "ProviderProtocol",
    "ProviderIntentRoute",
    "ReviewedIntentDisclosureProfile",
    "compile_intent_disclosure",
    "resolve_reviewed_intent_disclosure_profile",
    "reviewed_intent_disclosure_profiles",
]
