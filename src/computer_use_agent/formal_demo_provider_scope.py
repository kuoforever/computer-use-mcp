"""Host composition from one live-capable intent attempt to reviewed Scope.

The provider call is external work, but the returned candidate remains data.
This module awaits the existing consume-before-call coordinator and then uses
only the built-in reviewed scenario and role profiles to compile a Scope Sheet.
It adds no Console, START, Runner, MCP, desktop, application, persistence, or
retry surface.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Never

from .formal_demo_contract import (
    FORMAL_DEMO_V1_ROLE_PROFILES,
    FORMAL_DEMO_V1_SCENARIO,
    GenericScopeSheet,
    compile_generic_scope_sheet,
)
from .formal_demo_intent_gate import (
    FormalDemoIntentDisclosure,
    IntentCompileGate,
    IntentCompileGateState,
    IntentCompilePermit,
)
from .formal_demo_intent_request import (
    IntentCandidateAttempt,
    compile_task_intent_once,
)
from .providers.openai_intent import (
    FORMAL_DEMO_OPENAI_MODEL,
    FORMAL_DEMO_OPENAI_PROVIDER,
    FORMAL_DEMO_OPENAI_REGION,
    OpenAIIntentActivation,
    OpenAIResponsesIntentCandidatePort,
)


PROVIDER_SCOPE_COMPILATION_VERSION = 1
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class FormalDemoProviderScopeError(ValueError):
    """Fixed content-free failure from the provider Scope boundary."""


@dataclass(frozen=True, slots=True)
class ProviderScopeCompilation:
    """Content-free call facts plus validated intent and reviewed Scope."""

    attempt: IntentCandidateAttempt
    scope: GenericScopeSheet
    account_scope_digest: str
    activation_digest: str
    provider_id: str = FORMAL_DEMO_OPENAI_PROVIDER
    region: str = FORMAL_DEMO_OPENAI_REGION
    model_id: str = FORMAL_DEMO_OPENAI_MODEL
    provider_calls: int = 1
    retries: int = 0
    external_work_occurred: bool = True
    start_enabled: bool = False
    grants_execution_authority: bool = False
    version: int = PROVIDER_SCOPE_COMPILATION_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.attempt) is not IntentCandidateAttempt
            or type(self.scope) is not GenericScopeSheet
            or type(self.account_scope_digest) is not str
            or _DIGEST.fullmatch(self.account_scope_digest) is None
            or type(self.activation_digest) is not str
            or _DIGEST.fullmatch(self.activation_digest) is None
            or self.provider_id != FORMAL_DEMO_OPENAI_PROVIDER
            or self.region != FORMAL_DEMO_OPENAI_REGION
            or self.model_id != FORMAL_DEMO_OPENAI_MODEL
            or type(self.provider_calls) is not int
            or self.provider_calls != 1
            or type(self.retries) is not int
            or self.retries != 0
            or self.external_work_occurred is not True
            or self.start_enabled is not False
            or self.grants_execution_authority is not False
            or type(self.version) is not int
            or self.version != PROVIDER_SCOPE_COMPILATION_VERSION
            or self.scope.task_intent_digest != self.attempt.intent.content_digest
            or self.scope.scenario_digest != self.attempt.scenario_digest
            or self.scope.resume_identity
            != self.attempt.consumption.resume_identity
            or self.attempt.port_calls != 1
            or self.attempt.automatic_retry is not False
        ):
            raise FormalDemoProviderScopeError(
                "FORMAL_DEMO_PROVIDER_SCOPE_INVALID"
            )

    def bound_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "provider": self.provider_id,
            "region": self.region,
            "model": self.model_id,
            "account_scope_digest": self.account_scope_digest,
            "activation_digest": self.activation_digest,
            "provider_calls": self.provider_calls,
            "retries": self.retries,
            "external_work_occurred": self.external_work_occurred,
            "start_enabled": self.start_enabled,
            "grants_execution_authority": self.grants_execution_authority,
            "request_digest": self.attempt.request_digest,
            "task_intent_digest": self.attempt.intent.content_digest,
            "scope_binding_digest": self.scope.binding_digest,
            "contains_source_task": False,
            "contains_credential_value": False,
            "contains_model_prose": False,
        }


async def compile_openai_provider_scope_once(
    *,
    gate: IntentCompileGate,
    permit: IntentCompilePermit,
    current_disclosure: FormalDemoIntentDisclosure,
    activation: OpenAIIntentActivation,
    port: OpenAIResponsesIntentCandidatePort,
) -> ProviderScopeCompilation:
    """Perform one exact intent call, then compile only the built-in Scope."""

    if (
        type(activation) is not OpenAIIntentActivation
        or type(port) is not OpenAIResponsesIntentCandidatePort
        or port.activation is not activation
        or port.gate is not gate
    ):
        raise FormalDemoProviderScopeError(
            "FORMAL_DEMO_PROVIDER_SCOPE_PORT_INVALID"
        )
    activation_invalid = False
    activation_digest = ""
    account_scope_digest = ""
    gate_disclosure_digest = ""
    current_disclosure_digest = ""
    try:
        activation_digest = activation.content_digest
        account_scope_digest = activation.account_scope_digest
        gate_disclosure_digest = gate.disclosure.content_digest
        current_disclosure_digest = current_disclosure.content_digest
        activation_invalid = (
            gate_disclosure_digest != activation.disclosure_digest
            or current_disclosure_digest != activation.disclosure_digest
        )
    except BaseException:
        activation_invalid = True
    if activation_invalid:
        raise FormalDemoProviderScopeError(
            "FORMAL_DEMO_PROVIDER_SCOPE_PORT_INVALID"
        )
    attempt = await compile_task_intent_once(
        gate=gate,
        permit=permit,
        current_disclosure=current_disclosure,
        scenario=FORMAL_DEMO_V1_SCENARIO,
        port=port,
    )
    activation_stale = False
    try:
        activation_stale = (
            activation.content_digest != activation_digest
            or activation.account_scope_digest != account_scope_digest
            or port.activation is not activation
            or port.gate is not gate
            or gate.state is not IntentCompileGateState.CONSUMED
            or gate.disclosure.content_digest != gate_disclosure_digest
            or current_disclosure.content_digest != current_disclosure_digest
        )
    except BaseException:
        activation_stale = True
    if activation_stale:
        raise FormalDemoProviderScopeError(
            "FORMAL_DEMO_PROVIDER_SCOPE_ACTIVATION_STALE"
        )
    compilation_failed = False
    compiler_terminal: str | None = None
    result: ProviderScopeCompilation | None = None
    try:
        scope = compile_generic_scope_sheet(
            attempt.intent,
            FORMAL_DEMO_V1_SCENARIO,
            FORMAL_DEMO_V1_ROLE_PROFILES,
            resume_identity=attempt.consumption.resume_identity,
        )
        result = ProviderScopeCompilation(
            attempt=attempt,
            scope=scope,
            account_scope_digest=account_scope_digest,
            activation_digest=activation_digest,
        )
    except FormalDemoProviderScopeError:
        raise
    except asyncio.CancelledError:
        compiler_terminal = "cancelled"
    except KeyboardInterrupt:
        compiler_terminal = "interrupted"
    except SystemExit:
        compiler_terminal = "exited"
    except GeneratorExit:
        compiler_terminal = "generator_closed"
    except Exception:
        compilation_failed = True
    if compiler_terminal is not None:
        _raise_compiler_terminal(compiler_terminal)
    if compilation_failed or result is None:
        raise FormalDemoProviderScopeError(
            "FORMAL_DEMO_PROVIDER_SCOPE_COMPILATION_FAILED"
        )
    return result


def _raise_compiler_terminal(terminal: str) -> Never:
    """Re-raise process control without retaining compiler exception data."""

    if terminal == "cancelled":
        raise asyncio.CancelledError()
    if terminal == "interrupted":
        raise KeyboardInterrupt()
    if terminal == "exited":
        raise SystemExit(1)
    if terminal == "generator_closed":
        raise GeneratorExit()
    raise FormalDemoProviderScopeError(
        "FORMAL_DEMO_PROVIDER_SCOPE_COMPILATION_FAILED"
    )


__all__ = [
    "PROVIDER_SCOPE_COMPILATION_VERSION",
    "FormalDemoProviderScopeError",
    "ProviderScopeCompilation",
    "compile_openai_provider_scope_once",
]
