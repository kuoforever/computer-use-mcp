"""Offline one-attempt coordination for a Formal Demo TaskIntent candidate.

This module owns only the Host-side ordering seam behind the process-local
``IntentCompileGate``. It has no provider implementation, provider factory,
credential/configuration access, network transport, CLI, persistence, Runner,
MCP, desktop, or application port. Production wiring remains a later,
separately authorized slice.

The injected port is deliberately narrow so deterministic fakes can prove that
the permit is consumed before the single call and that every terminal outcome
is non-retryable. A passing fake does not establish provider evidence.
"""

from __future__ import annotations

import json
import re
from asyncio import CancelledError
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
from typing import Never, Protocol, SupportsIndex

from .formal_demo_contract import (
    MAX_SOURCE_TASK_BYTES,
    TASK_INTENT_VERSION,
    DemoScenarioSpec,
    FormalDemoContractError,
    TaskIntent,
    decode_demo_scenario_spec,
    decode_task_intent,
    resolve_reviewed_formal_demo_scenario,
    validate_task_intent_for_reviewed_scenario,
)
from .formal_demo_intent_gate import (
    INTENT_COMPILE_OPERATION,
    INTENT_COMPILE_REQUEST_LIMIT,
    FormalDemoIntentDisclosure,
    IntentCompileConsumption,
    IntentCompileGate,
    IntentCompilePermit,
    ProviderIntentRoute,
)


INTENT_CANDIDATE_REQUEST_VERSION = 1
INTENT_CANDIDATE_ATTEMPT_VERSION = 1

_BOUND_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")


class FormalDemoIntentRequestError(ValueError):
    """Fixed, content-free failure at the offline intent-attempt boundary."""


class IntentCandidateStatus(str, Enum):
    COMPLETED = "completed"
    REFUSED = "refused"
    TRUNCATED = "truncated"


class _PortTerminal(str, Enum):
    INVALID = "invalid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
    EXITED = "exited"
    GENERATOR_CLOSED = "generator_closed"


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
        raise FormalDemoIntentRequestError(
            "FORMAL_DEMO_INTENT_REQUEST_INVALID"
        ) from None


def _content_digest(domain: str, payload: object) -> str:
    return sha256(
        _canonical_json_bytes({"domain": domain, "payload": payload})
    ).hexdigest()


def _require_digest(value: object) -> str:
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
    return value


def _require_bound_identity(value: object) -> str:
    if type(value) is not str or _BOUND_IDENTITY.fullmatch(value) is None:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
    return value


def _source_task_digest(value: object) -> str:
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        raise FormalDemoIntentRequestError(
            "FORMAL_DEMO_INTENT_REQUEST_INVALID"
        ) from None
    if len(encoded) > MAX_SOURCE_TASK_BYTES:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
    return sha256(encoded).hexdigest()


def _snapshot_route(route: object) -> ProviderIntentRoute:
    if type(route) is not ProviderIntentRoute:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
    try:
        snapshot = ProviderIntentRoute(
            provider_id=route.provider_id,
            region=route.region,
            model_id=route.model_id,
            protocol=route.protocol,
            endpoint=route.endpoint,
            workspace_id=route.workspace_id,
        )
        if snapshot.canonical_payload() != route.canonical_payload():
            raise FormalDemoIntentRequestError(
                "FORMAL_DEMO_INTENT_REQUEST_INVALID"
            )
    except FormalDemoIntentRequestError:
        raise
    except Exception:
        raise FormalDemoIntentRequestError(
            "FORMAL_DEMO_INTENT_REQUEST_INVALID"
        ) from None
    return snapshot


def _resolve_scenario(scenario: object) -> DemoScenarioSpec:
    if type(scenario) is not DemoScenarioSpec:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_SCENARIO_INVALID")
    invalid = False
    snapshot: DemoScenarioSpec | None = None
    try:
        selected_digest = scenario.content_digest
        resolved = resolve_reviewed_formal_demo_scenario(
            scenario.scenario_id,
            version=scenario.version,
            digest=selected_digest,
        )
        if resolved is not scenario and resolved != scenario:
            invalid = True
        else:
            snapshot = decode_demo_scenario_spec(resolved.canonical_json())
            if (
                snapshot.content_digest != selected_digest
                or resolved.content_digest != selected_digest
                or scenario.content_digest != selected_digest
            ):
                invalid = True
    except BaseException:
        invalid = True
    if invalid or snapshot is None:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_SCENARIO_INVALID")
    return snapshot


@dataclass(frozen=True, slots=True, repr=False)
class IntentCandidateRequest:
    """Sensitive in-process request for one injected candidate port call."""

    disclosure_id: str
    resume_identity: str
    source_task: str = field(repr=False)
    source_task_digest: str
    disclosure_digest: str
    route: ProviderIntentRoute
    profile_digest: str
    scenario_id: str
    scenario_version: int
    scenario_digest: str
    task_intent_version: int = TASK_INTENT_VERSION
    operation: str = INTENT_COMPILE_OPERATION
    request_limit: int = INTENT_COMPILE_REQUEST_LIMIT
    tools_allowed: bool = False
    automatic_retry: bool = False
    version: int = INTENT_CANDIDATE_REQUEST_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.version) is not int
            or self.version != INTENT_CANDIDATE_REQUEST_VERSION
            or type(self.task_intent_version) is not int
            or self.task_intent_version != TASK_INTENT_VERSION
            or self.operation != INTENT_COMPILE_OPERATION
            or type(self.request_limit) is not int
            or self.request_limit != INTENT_COMPILE_REQUEST_LIMIT
            or self.tools_allowed is not False
            or self.automatic_retry is not False
        ):
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
        _require_bound_identity(self.disclosure_id)
        _require_bound_identity(self.resume_identity)
        if _source_task_digest(self.source_task) != self.source_task_digest:
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
        for digest in (
            self.source_task_digest,
            self.disclosure_digest,
            self.profile_digest,
            self.scenario_digest,
        ):
            _require_digest(digest)
        _snapshot_route(self.route)
        if type(self.scenario_id) is not str:
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
        try:
            resolved = resolve_reviewed_formal_demo_scenario(
                self.scenario_id,
                version=self.scenario_version,
                digest=self.scenario_digest,
            )
        except Exception:
            raise FormalDemoIntentRequestError(
                "FORMAL_DEMO_INTENT_SCENARIO_INVALID"
            ) from None
        if resolved.scenario_id != self.scenario_id:
            raise FormalDemoIntentRequestError(
                "FORMAL_DEMO_INTENT_SCENARIO_INVALID"
            )

    def bound_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "disclosure_id": self.disclosure_id,
            "resume_identity": self.resume_identity,
            "source_task_digest": self.source_task_digest,
            "disclosure_digest": self.disclosure_digest,
            "route": self.route.canonical_payload(),
            "route_digest": self.route.content_digest,
            "profile_digest": self.profile_digest,
            "scenario": {
                "scenario_id": self.scenario_id,
                "version": self.scenario_version,
                "digest": self.scenario_digest,
            },
            "task_intent_version": self.task_intent_version,
            "operation": self.operation,
            "request_limit": self.request_limit,
            "tools_allowed": self.tools_allowed,
            "automatic_retry": self.automatic_retry,
            "contains_credential_value": False,
            "grants_scope_or_start": False,
            "grants_execution_authority": False,
            "grants_retry_or_replay": False,
        }

    @property
    def content_digest(self) -> str:
        if _source_task_digest(self.source_task) != self.source_task_digest:
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")
        _snapshot_route(self.route)
        return _content_digest(
            "formal-demo-intent-candidate-request-v1",
            self.bound_payload(),
        )

    def __repr__(self) -> str:
        return "<IntentCandidateRequest local-sensitive>"

    def __copy__(self) -> IntentCandidateRequest:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_OPAQUE")

    def __deepcopy__(self, _memo: object) -> IntentCandidateRequest:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_OPAQUE")


@dataclass(frozen=True, slots=True, repr=False)
class IntentCandidateResponse:
    """Strict transient result envelope returned by an injected port."""

    status: IntentCandidateStatus
    candidate: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if type(self.status) is not IntentCandidateStatus:
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_INVALID")
        if self.status is IntentCandidateStatus.COMPLETED:
            if type(self.candidate) is not str:
                raise FormalDemoIntentRequestError(
                    "FORMAL_DEMO_INTENT_RESPONSE_INVALID"
                )
        elif self.candidate is not None:
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_INVALID")

    def __repr__(self) -> str:
        return f"<IntentCandidateResponse {self.status.value}>"

    def __copy__(self) -> IntentCandidateResponse:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_OPAQUE")

    def __deepcopy__(self, _memo: object) -> IntentCandidateResponse:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_OPAQUE")


class IntentCandidatePort(Protocol):
    """Injected one-call candidate compiler; no implementation is shipped here."""

    def create_candidate(
        self,
        request: IntentCandidateRequest,
        /,
    ) -> IntentCandidateResponse: ...


@dataclass(frozen=True, slots=True)
class IntentCandidateAttempt:
    """Content-free terminal binding plus validated non-authoritative intent."""

    intent: TaskIntent
    consumption: IntentCompileConsumption
    request_digest: str
    scenario_digest: str
    port_calls: int = 1
    tools_allowed: bool = False
    automatic_retry: bool = False
    grants_execution_authority: bool = False
    version: int = INTENT_CANDIDATE_ATTEMPT_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.intent) is not TaskIntent
            or type(self.consumption) is not IntentCompileConsumption
            or type(self.version) is not int
            or self.version != INTENT_CANDIDATE_ATTEMPT_VERSION
            or type(self.port_calls) is not int
            or self.port_calls != 1
            or self.tools_allowed is not False
            or self.automatic_retry is not False
            or self.grants_execution_authority is not False
        ):
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_ATTEMPT_INVALID")
        _require_digest(self.request_digest)
        _require_digest(self.scenario_digest)
        if self.intent.source_task_digest != self.consumption.source_task_digest:
            raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_ATTEMPT_INVALID")


def _response_snapshot(response: object) -> IntentCandidateResponse:
    if type(response) is not IntentCandidateResponse:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_INVALID")
    return IntentCandidateResponse(
        status=response.status,
        candidate=response.candidate,
    )


def _classify_port_exception(exc: BaseException) -> _PortTerminal:
    if isinstance(exc, CancelledError):
        return _PortTerminal.CANCELLED
    if isinstance(exc, KeyboardInterrupt):
        return _PortTerminal.INTERRUPTED
    if isinstance(exc, SystemExit):
        return _PortTerminal.EXITED
    if isinstance(exc, GeneratorExit):
        return _PortTerminal.GENERATOR_CLOSED
    return _PortTerminal.FAILED


def _raise_port_terminal(terminal: _PortTerminal) -> Never:
    """Raise only sanitized control flow or a fixed port error."""

    if terminal is _PortTerminal.CANCELLED:
        raise CancelledError()
    if terminal is _PortTerminal.INTERRUPTED:
        raise KeyboardInterrupt()
    if terminal is _PortTerminal.EXITED:
        raise SystemExit(1)
    if terminal is _PortTerminal.GENERATOR_CLOSED:
        raise GeneratorExit()
    if terminal is _PortTerminal.INVALID:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_PORT_INVALID")
    raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_PORT_FAILED")


def _validate_candidate_without_error_context(
    candidate: str,
    *,
    source_task: str,
    scenario: DemoScenarioSpec,
) -> tuple[TaskIntent | None, str | None]:
    """Return a validated snapshot or a fixed code, never a nested raw error."""

    try:
        decoded = decode_task_intent(candidate, source_task=source_task)
        return validate_task_intent_for_reviewed_scenario(decoded, scenario), None
    except FormalDemoContractError as exc:
        code = str(exc)
        if _ERROR_CODE.fullmatch(code) is None:
            code = "FORMAL_DEMO_INTENT_CANDIDATE_INVALID"
        return None, code
    except BaseException:
        return None, "FORMAL_DEMO_INTENT_CANDIDATE_INVALID"


def _raise_contract_error(code: str) -> Never:
    if _ERROR_CODE.fullmatch(code) is None:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_CANDIDATE_INVALID")
    raise FormalDemoContractError(code)


def compile_task_intent_once(
    *,
    gate: IntentCompileGate,
    permit: IntentCompilePermit,
    current_disclosure: FormalDemoIntentDisclosure,
    scenario: DemoScenarioSpec,
    port: IntentCandidatePort,
) -> IntentCandidateAttempt:
    """Consume one permit before one injected call and validate its candidate.

    Port failures are normalized without their text. Cancellation and process
    control signals are re-raised as sanitized built-in instances after
    consumption, so callers still cannot replay the terminal gate.
    """

    if type(gate) is not IntentCompileGate:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_GATE_INVALID")
    reviewed_scenario = _resolve_scenario(scenario)

    disclosure_invalid = type(current_disclosure) is not FormalDemoIntentDisclosure
    if not disclosure_invalid:
        try:
            source_task = current_disclosure.source_task
            disclosure_id = current_disclosure.disclosure_id
            resume_identity = current_disclosure.resume_identity
            source_digest = current_disclosure.source_task_digest
            disclosure_digest = current_disclosure.content_digest
            route = _snapshot_route(current_disclosure.route)
            profile_digest = current_disclosure.profile_digest
        except BaseException:
            disclosure_invalid = True
    if disclosure_invalid:
        # Let the issuing gate own the terminal classification for binding drift.
        gate.consume(permit, current_disclosure=current_disclosure)
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_INVALID")

    consumption = gate.consume(permit, current_disclosure=current_disclosure)
    request = IntentCandidateRequest(
        disclosure_id=disclosure_id,
        resume_identity=resume_identity,
        source_task=source_task,
        source_task_digest=source_digest,
        disclosure_digest=disclosure_digest,
        route=route,
        profile_digest=profile_digest,
        scenario_id=reviewed_scenario.scenario_id,
        scenario_version=reviewed_scenario.version,
        scenario_digest=reviewed_scenario.content_digest,
    )
    if (
        consumption.disclosure_digest != request.disclosure_digest
        or consumption.resume_identity != request.resume_identity
        or consumption.source_task_digest != request.source_task_digest
        or consumption.route_digest != request.route.content_digest
        or consumption.profile_digest != request.profile_digest
    ):
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_BINDING_INVALID")

    request_digest = request.content_digest
    response: object | None = None
    port_terminal: _PortTerminal | None = None
    try:
        create_candidate = getattr(port, "create_candidate", None)
        if not callable(create_candidate):
            port_terminal = _PortTerminal.INVALID
        else:
            response = create_candidate(request)
    except BaseException as exc:
        port_terminal = _classify_port_exception(exc)
    if port_terminal is not None:
        _raise_port_terminal(port_terminal)

    request_stale = False
    try:
        request_stale = request.content_digest != request_digest
    except BaseException:
        request_stale = True
    if request_stale:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_REQUEST_STALE")

    scenario_stale = False
    try:
        current_scenario = resolve_reviewed_formal_demo_scenario(
            request.scenario_id,
            version=request.scenario_version,
            digest=request.scenario_digest,
        )
        scenario_stale = current_scenario.content_digest != request.scenario_digest
    except BaseException:
        scenario_stale = True
    if scenario_stale:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_SCENARIO_STALE")

    result = _response_snapshot(response)
    if result.status is IntentCandidateStatus.REFUSED:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_CANDIDATE_REFUSED")
    if result.status is IntentCandidateStatus.TRUNCATED:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_CANDIDATE_TRUNCATED")
    if result.candidate is None:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_RESPONSE_INVALID")

    intent, validation_error = _validate_candidate_without_error_context(
        result.candidate,
        source_task=source_task,
        scenario=reviewed_scenario,
    )
    if validation_error is not None:
        _raise_contract_error(validation_error)
    if intent is None:
        raise FormalDemoIntentRequestError("FORMAL_DEMO_INTENT_CANDIDATE_INVALID")
    return IntentCandidateAttempt(
        intent=intent,
        consumption=consumption,
        request_digest=request_digest,
        scenario_digest=request.scenario_digest,
    )


__all__ = [
    "INTENT_CANDIDATE_ATTEMPT_VERSION",
    "INTENT_CANDIDATE_REQUEST_VERSION",
    "FormalDemoIntentRequestError",
    "IntentCandidateAttempt",
    "IntentCandidatePort",
    "IntentCandidateRequest",
    "IntentCandidateResponse",
    "IntentCandidateStatus",
    "compile_task_intent_once",
]
