from __future__ import annotations

import asyncio
import json
import traceback
from dataclasses import dataclass, field, replace
from hashlib import sha256
from threading import Lock
from types import SimpleNamespace
from typing import Callable

import pytest

import computer_use_agent.formal_demo_provider_scope as provider_scope_module
import computer_use_agent.providers.openai_intent as openai_intent_module
from computer_use_agent.formal_demo_contract import (
    FORMAL_DEMO_V1_SCENARIO,
    MAX_TASK_INTENT_JSON_BYTES,
    TASK_INTENT_VERSION,
)
from computer_use_agent.formal_demo_intent_gate import (
    INTENT_COMPILE_TOKEN,
    FormalDemoIntentDisclosure,
    IntentCompileGate,
    IntentCompileGateState,
    IntentCompilePermit,
    ProviderIntentRoute,
    ProviderProtocol,
    ReviewedIntentDisclosureProfile,
    compile_intent_disclosure,
    resolve_reviewed_intent_disclosure_profile,
    reviewed_intent_disclosure_profiles,
)
from computer_use_agent.formal_demo_intent_request import (
    FormalDemoIntentRequestError,
    IntentCandidateRequest,
    IntentCandidateResponse,
    IntentCandidateStatus,
    compile_task_intent_once,
)
from computer_use_agent.formal_demo_provider_scope import (
    FormalDemoProviderScopeError,
    ProviderScopeCompilation,
    compile_openai_provider_scope_once,
)
from computer_use_agent.providers.openai_intent import (
    FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN,
    FORMAL_DEMO_OPENAI_CREDENTIAL_ENVIRONMENT,
    FORMAL_DEMO_OPENAI_MODEL,
    FORMAL_DEMO_OPENAI_PROVIDER,
    FORMAL_DEMO_OPENAI_REGION,
    OPENAI_FORMAL_DEMO_INTENT_INSTRUCTIONS,
    OpenAIFormalDemoIntentError,
    OpenAIIntentActivation,
    OpenAIResponsesIntentCandidatePort,
    bind_openai_intent_activation,
    task_intent_candidate_schema,
)


SOURCE_TASK = (
    "Use only the dedicated fixtures to create a verified analysis, report, "
    "and unsent test-account draft."
)
DISCLOSURE_ID = "formal-demo-openai-007f"
RESUME_IDENTITY = "formal-demo-review-007f"
ACCOUNT_SCOPE_DIGEST = "a" * 64


def _route(*, model_id: str = FORMAL_DEMO_OPENAI_MODEL) -> ProviderIntentRoute:
    return ProviderIntentRoute(
        provider_id=FORMAL_DEMO_OPENAI_PROVIDER,
        region=FORMAL_DEMO_OPENAI_REGION,
        model_id=model_id,
        protocol=ProviderProtocol.OPENAI_RESPONSES,
        endpoint="https://api.openai.com/v1",
    )


def _profile() -> ReviewedIntentDisclosureProfile:
    selected = next(
        profile
        for profile in reviewed_intent_disclosure_profiles()
        if profile.provider_id == FORMAL_DEMO_OPENAI_PROVIDER
    )
    return resolve_reviewed_intent_disclosure_profile(
        selected.profile_id,
        version=selected.version,
        expected_digest=selected.content_digest,
    )


def _disclosure(
    *,
    source_task: str = SOURCE_TASK,
    resume_identity: str = RESUME_IDENTITY,
) -> FormalDemoIntentDisclosure:
    profile = _profile()
    return compile_intent_disclosure(
        disclosure_id=DISCLOSURE_ID,
        resume_identity=resume_identity,
        source_task=source_task,
        route=_route(),
        profile_id=profile.profile_id,
        profile_version=profile.version,
        expected_profile_digest=profile.content_digest,
    )


def _activation(
    disclosure: FormalDemoIntentDisclosure,
    *,
    account_scope_digest: str = ACCOUNT_SCOPE_DIGEST,
) -> OpenAIIntentActivation:
    return bind_openai_intent_activation(
        disclosure,
        account_scope_digest=account_scope_digest,
        acknowledgement=FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN,
    )


def _request(disclosure: FormalDemoIntentDisclosure) -> IntentCandidateRequest:
    return IntentCandidateRequest(
        disclosure_id=disclosure.disclosure_id,
        resume_identity=disclosure.resume_identity,
        source_task=disclosure.source_task,
        source_task_digest=disclosure.source_task_digest,
        disclosure_digest=disclosure.content_digest,
        route=disclosure.route,
        profile_digest=disclosure.profile_digest,
        scenario_id=FORMAL_DEMO_V1_SCENARIO.scenario_id,
        scenario_version=FORMAL_DEMO_V1_SCENARIO.version,
        scenario_digest=FORMAL_DEMO_V1_SCENARIO.content_digest,
    )


def _candidate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": TASK_INTENT_VERSION,
        "scenario_id": FORMAL_DEMO_V1_SCENARIO.scenario_id,
        "outcome_id": "verified_analysis_report_and_draft",
        "requested_roles": [
            role.value for role in FORMAL_DEMO_V1_SCENARIO.required_roles
        ],
        "requested_outputs": list(FORMAL_DEMO_V1_SCENARIO.required_outputs),
        "constraint_ids": list(FORMAL_DEMO_V1_SCENARIO.required_constraints),
        "risk_ceiling": FORMAL_DEMO_V1_SCENARIO.risk_ceiling.value,
        "budgets": {
            "provider_calls": 1,
            "tool_calls": FORMAL_DEMO_V1_SCENARIO.budget_ceilings.tool_calls,
            "side_effects": (
                FORMAL_DEMO_V1_SCENARIO.budget_ceilings.side_effects
            ),
            "retries": 0,
            "artifacts": FORMAL_DEMO_V1_SCENARIO.budget_ceilings.artifacts,
        },
    }
    payload.update(overrides)
    return payload


def _candidate_json(**overrides: object) -> str:
    return json.dumps(
        _candidate_payload(**overrides),
        sort_keys=True,
        separators=(",", ":"),
    )


def _completed_response(
    candidate: str | None = None,
    *,
    reasoning_before: bool = False,
    reasoning_after: bool = False,
) -> dict[str, object]:
    output: list[object] = []
    if reasoning_before:
        output.append({"type": "reasoning", "summary": []})
    output.append(
        {
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": _candidate_json() if candidate is None else candidate,
                }
            ],
        }
    )
    if reasoning_after:
        output.append({"type": "reasoning", "summary": []})
    return {
        "status": "completed",
        "model": FORMAL_DEMO_OPENAI_MODEL,
        "output": output,
    }


ScriptItem = object | BaseException | Callable[[dict[str, object]], object]


@dataclass
class ScriptedResponses:
    script: list[ScriptItem]
    requests: list[dict[str, object]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    async def create(self, **kwargs: object) -> object:
        request = dict(kwargs)
        with self._lock:
            self.requests.append(request)
            if not self.script:
                raise AssertionError("unexpected extra fake provider call")
            item = self.script.pop(0)
        await asyncio.sleep(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request)
        return item


@dataclass
class CountingFactory:
    responses: object
    before_return: Callable[[], None] | None = None
    calls: int = 0

    def __call__(self) -> object:
        self.calls += 1
        if self.before_return is not None:
            self.before_return()
        return self.responses


def _gate_and_permit(
    disclosure: FormalDemoIntentDisclosure,
) -> tuple[IntentCompileGate, IntentCompilePermit]:
    gate = IntentCompileGate(disclosure)
    return gate, gate.acknowledge(INTENT_COMPILE_TOKEN)


def _consumed_gate(disclosure: FormalDemoIntentDisclosure) -> IntentCompileGate:
    gate, permit = _gate_and_permit(disclosure)
    gate.consume(permit, current_disclosure=disclosure)
    assert gate.state is IntentCompileGateState.CONSUMED
    return gate


def _run_candidate(
    port: OpenAIResponsesIntentCandidatePort,
    request: IntentCandidateRequest,
) -> IntentCandidateResponse:
    return asyncio.run(port.create_candidate(request))


def _assert_sanitized(
    caught: pytest.ExceptionInfo[BaseException],
    *,
    code: str,
    secret: str,
) -> None:
    assert str(caught.value) == code
    assert caught.value.__context__ is None
    rendered = "".join(
        traceback.format_exception(
            type(caught.value),
            caught.value,
            caught.value.__traceback__,
        )
    )
    assert secret not in rendered


def test_activation_requires_exact_account_review_and_binds_exact_tuple() -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)

    assert activation.account_scope_digest == ACCOUNT_SCOPE_DIGEST
    assert activation.disclosure_digest == disclosure.content_digest
    assert activation.resume_identity == disclosure.resume_identity
    assert activation.source_task_digest == disclosure.source_task_digest
    assert activation.route_digest == disclosure.route.content_digest
    assert activation.profile_digest == disclosure.profile_digest
    assert activation.scenario_digest == FORMAL_DEMO_V1_SCENARIO.content_digest
    assert activation.provider_id == FORMAL_DEMO_OPENAI_PROVIDER == "openai"
    assert activation.region == FORMAL_DEMO_OPENAI_REGION == "global"
    assert activation.model_id == FORMAL_DEMO_OPENAI_MODEL == "gpt-5.6-terra"
    assert (
        activation.credential_environment
        == FORMAL_DEMO_OPENAI_CREDENTIAL_ENVIRONMENT
        == "OPENAI_API_KEY"
    )
    assert activation.data_controls_reviewed is True
    assert activation.raw_task_disclosure_authorized is True
    assert activation.canonical_payload()["contains_credential_value"] is False
    assert activation.canonical_payload()["grants_execution_authority"] is False
    assert SOURCE_TASK not in json.dumps(activation.canonical_payload())


@pytest.mark.parametrize(
    "acknowledgement",
    (
        None,
        True,
        "",
        "COMPILE",
        "openai_account_data_controls_reviewed",
        FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN + " ",
    ),
)
def test_activation_rejects_every_non_exact_account_review_ack(
    acknowledgement: object,
) -> None:
    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_ACCOUNT_REVIEW_REQUIRED$",
    ):
        bind_openai_intent_activation(
            _disclosure(),
            account_scope_digest=ACCOUNT_SCOPE_DIGEST,
            acknowledgement=acknowledgement,
        )


def test_activation_rejects_equality_spoofed_account_review_ack() -> None:
    class EqualitySpoof:
        def __eq__(self, _other: object) -> bool:
            return True

    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_ACCOUNT_REVIEW_REQUIRED$",
    ):
        bind_openai_intent_activation(
            _disclosure(),
            account_scope_digest=ACCOUNT_SCOPE_DIGEST,
            acknowledgement=EqualitySpoof(),
        )


@pytest.mark.parametrize(
    "digest",
    (None, True, "", "a" * 63, "A" * 64, "g" * 64),
)
def test_activation_rejects_non_exact_account_scope_digest(digest: object) -> None:
    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_INTENT_ACTIVATION_INVALID$",
    ):
        bind_openai_intent_activation(
            _disclosure(),
            account_scope_digest=digest,  # type: ignore[arg-type]
            acknowledgement=FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN,
        )


def test_activation_and_port_construction_are_inert_without_key_or_sdk_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(FORMAL_DEMO_OPENAI_CREDENTIAL_ENVIRONMENT, raising=False)
    disclosure = _disclosure()
    activation = _activation(disclosure)
    factory = CountingFactory(ScriptedResponses([_completed_response()]))
    gate, _permit = _gate_and_permit(disclosure)

    port = OpenAIResponsesIntentCandidatePort(
        activation=activation,
        gate=gate,
        responses_factory=factory,  # type: ignore[arg-type]
    )

    assert factory.calls == 0
    assert "OPENAI_API_KEY" not in repr(port)
    assert SOURCE_TASK not in repr(port)


def test_default_factory_explicitly_disables_sdk_automatic_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses([_completed_response()])
    calls: list[tuple[str, dict[str, object]]] = []

    def client_from_environment(
        provider: str,
        **kwargs: object,
    ) -> object:
        calls.append((provider, kwargs))
        return SimpleNamespace(responses=scripted)

    monkeypatch.setattr(
        openai_intent_module,
        "openai_client_from_environment",
        client_from_environment,
    )
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=_consumed_gate(disclosure),
    )

    result = _run_candidate(port, _request(disclosure))

    assert result.status is IntentCandidateStatus.COMPLETED
    assert calls == [
        (
            FORMAL_DEMO_OPENAI_PROVIDER,
            {
                "region": FORMAL_DEMO_OPENAI_REGION,
                "legacy_credentials": False,
                "max_retries": 0,
            },
        )
    ]
    assert len(scripted.requests) == 1


def test_exact_schema_is_strict_and_bounded_to_the_reviewed_scenario() -> None:
    scenario = FORMAL_DEMO_V1_SCENARIO
    schema = task_intent_candidate_schema()

    assert schema == {
        "type": "object",
        "properties": {
            "version": {"type": "integer", "const": TASK_INTENT_VERSION},
            "scenario_id": {
                "type": "string",
                "const": scenario.scenario_id,
            },
            "outcome_id": {
                "type": "string",
                "enum": list(scenario.outcomes),
            },
            "requested_roles": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [role.value for role in scenario.allowed_roles],
                },
                "minItems": len(scenario.required_roles),
                "maxItems": len(scenario.allowed_roles),
            },
            "requested_outputs": {
                "type": "array",
                "items": {"type": "string", "enum": list(scenario.outputs)},
                "minItems": len(scenario.required_outputs),
                "maxItems": len(scenario.outputs),
            },
            "constraint_ids": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": list(scenario.constraints),
                },
                "minItems": len(scenario.required_constraints),
                "maxItems": len(scenario.constraints),
            },
            "risk_ceiling": {
                "type": "string",
                "enum": ["read_only", "draft"],
            },
            "budgets": {
                "type": "object",
                "properties": {
                    name: {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": getattr(scenario.budget_ceilings, name),
                    }
                    for name in (
                        "provider_calls",
                        "tool_calls",
                        "side_effects",
                        "retries",
                        "artifacts",
                    )
                },
                "required": [
                    "provider_calls",
                    "tool_calls",
                    "side_effects",
                    "retries",
                    "artifacts",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "version",
            "scenario_id",
            "outcome_id",
            "requested_roles",
            "requested_outputs",
            "constraint_ids",
            "risk_ceiling",
            "budgets",
        ],
        "additionalProperties": False,
    }


def test_gate_is_consumed_before_lazy_factory_and_exact_tool_free_request() -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)
    responses = ScriptedResponses([_completed_response()])
    factory = CountingFactory(
        responses,
        before_return=lambda: (
            gate.state is IntentCompileGateState.CONSUMED
            or pytest.fail("client factory ran before exact permit consumption")
        ),
    )
    port = OpenAIResponsesIntentCandidatePort(
        activation=activation,
        gate=gate,
        responses_factory=factory,  # type: ignore[arg-type]
    )

    assert factory.calls == 0
    attempt = asyncio.run(
        compile_task_intent_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
            scenario=FORMAL_DEMO_V1_SCENARIO,
            port=port,
        )
    )

    assert gate.state is IntentCompileGateState.CONSUMED
    assert factory.calls == 1
    assert len(responses.requests) == 1
    request = responses.requests[0]
    assert set(request) == {
        "model",
        "instructions",
        "input",
        "text",
        "max_output_tokens",
        "store",
    }
    assert request["model"] == FORMAL_DEMO_OPENAI_MODEL
    assert request["instructions"] == OPENAI_FORMAL_DEMO_INTENT_INSTRUCTIONS
    assert request["max_output_tokens"] == 4_096
    assert request["store"] is False
    assert "tools" not in request
    assert "tool_choice" not in request
    assert "previous_response_id" not in request
    assert "conversation" not in request
    assert "metadata" not in request
    assert request["text"] == {
        "format": {
            "type": "json_schema",
            "name": "formal_demo_task_intent_v1",
            "strict": True,
            "schema": task_intent_candidate_schema(),
        }
    }
    assert isinstance(request["input"], str)
    provider_input = json.loads(request["input"])
    assert provider_input == {
        "source_task": SOURCE_TASK,
        "task_intent_contract": {
            "version": TASK_INTENT_VERSION,
            "source_task_digest_is_host_owned": True,
            "model_output_is_untrusted": True,
            "grants_execution_authority": False,
        },
        "reviewed_scenario": FORMAL_DEMO_V1_SCENARIO.canonical_payload(),
    }
    wire = json.dumps(request, sort_keys=True)
    for forbidden in (
        activation.account_scope_digest,
        disclosure.content_digest,
        disclosure.source_task_digest,
        disclosure.route.content_digest,
        disclosure.profile_digest,
        disclosure.resume_identity,
        disclosure.disclosure_id,
        FORMAL_DEMO_OPENAI_CREDENTIAL_ENVIRONMENT,
    ):
        assert forbidden not in wire
    assert attempt.port_calls == 1
    assert attempt.automatic_retry is False
    assert attempt.tools_allowed is False


def test_direct_port_call_cannot_bypass_the_bound_permitted_gate() -> None:
    disclosure = _disclosure()
    gate, _permit = _gate_and_permit(disclosure)
    scripted = ScriptedResponses([_completed_response()])
    factory = CountingFactory(scripted)
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=gate,
        responses_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_INTENT_CONSUMPTION_REQUIRED$",
    ):
        _run_candidate(port, _request(disclosure))

    assert gate.state is IntentCompileGateState.PERMITTED
    assert factory.calls == 0
    assert scripted.requests == []


@pytest.mark.parametrize(
    ("reasoning_before", "reasoning_after"),
    ((False, False), (True, False), (False, True), (True, True)),
)
def test_completed_response_accepts_only_reasoning_plus_one_assistant_message(
    reasoning_before: bool,
    reasoning_after: bool,
) -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses(
        [
            _completed_response(
                reasoning_before=reasoning_before,
                reasoning_after=reasoning_after,
            )
        ]
    )
    result = _run_candidate(
        OpenAIResponsesIntentCandidatePort(
            _activation(disclosure),
            gate=_consumed_gate(disclosure),
            responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
        ),
        _request(disclosure),
    )

    assert result.status is IntentCandidateStatus.COMPLETED
    assert result.candidate == _candidate_json()
    assert len(scripted.requests) == 1


@pytest.mark.parametrize(
    ("response", "status"),
    (
        (
            {
                "status": "completed",
                "model": FORMAL_DEMO_OPENAI_MODEL,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "no"}],
                    }
                ],
            },
            IntentCandidateStatus.REFUSED,
        ),
        (
            {
                "status": "incomplete",
                "model": FORMAL_DEMO_OPENAI_MODEL,
                "output": [],
            },
            IntentCandidateStatus.TRUNCATED,
        ),
    ),
)
def test_refusal_and_truncation_are_explicit_terminal_results(
    response: object,
    status: IntentCandidateStatus,
) -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses([response])
    result = _run_candidate(
        OpenAIResponsesIntentCandidatePort(
            _activation(disclosure),
            gate=_consumed_gate(disclosure),
            responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
        ),
        _request(disclosure),
    )

    assert result.status is status
    assert result.candidate is None
    assert len(scripted.requests) == 1


@pytest.mark.parametrize(
    ("model", "message_status", "content_type"),
    (
        ("gpt-drifted", "completed", "output_text"),
        (None, "completed", "output_text"),
        (FORMAL_DEMO_OPENAI_MODEL, "incomplete", "output_text"),
        (FORMAL_DEMO_OPENAI_MODEL, None, "output_text"),
        (FORMAL_DEMO_OPENAI_MODEL, "incomplete", "refusal"),
    ),
)
def test_response_model_and_nested_message_status_are_exactly_bound(
    model: object,
    message_status: object,
    content_type: str,
) -> None:
    disclosure = _disclosure()
    content = (
        {"type": "refusal", "refusal": "no"}
        if content_type == "refusal"
        else {"type": "output_text", "text": _candidate_json()}
    )
    response = {
        "status": "completed",
        "model": model,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": message_status,
                "content": [content],
            }
        ],
    }
    scripted = ScriptedResponses([response])

    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_INTENT_RESPONSE_INVALID$",
    ):
        _run_candidate(
            OpenAIResponsesIntentCandidatePort(
                _activation(disclosure),
                gate=_consumed_gate(disclosure),
                responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
            ),
            _request(disclosure),
        )

    assert len(scripted.requests) == 1


@pytest.mark.parametrize(
    "response",
    (
        None,
        {},
        {"status": "queued", "output": []},
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [],
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": "message",
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [{"type": "tool_call"}],
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "user",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "{}"}],
                }
            ],
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [],
                }
            ],
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": 1}],
                }
            ],
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "input_text", "text": "{}"}],
                }
            ],
        },
        {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "{}"}],
                },
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": "{}"}],
                },
            ],
        },
    ),
)
def test_invalid_provider_envelopes_fail_closed_after_exactly_one_call(
    response: object,
) -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses([response])
    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_INTENT_RESPONSE_INVALID$",
    ) as caught:
        _run_candidate(
            OpenAIResponsesIntentCandidatePort(
                _activation(disclosure),
                gate=_consumed_gate(disclosure),
                responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
            ),
            _request(disclosure),
        )

    assert caught.value.__context__ is None
    assert len(scripted.requests) == 1


def test_unexpected_response_accessor_exception_is_content_free() -> None:
    disclosure = _disclosure()
    secret = "secret-response-accessor-context"

    class ExplodingResponse:
        model = FORMAL_DEMO_OPENAI_MODEL

        @property
        def status(self) -> object:
            raise RuntimeError(secret)

    scripted = ScriptedResponses([ExplodingResponse()])
    with pytest.raises(OpenAIFormalDemoIntentError) as caught:
        _run_candidate(
            OpenAIResponsesIntentCandidatePort(
                _activation(disclosure),
                gate=_consumed_gate(disclosure),
                responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
            ),
            _request(disclosure),
        )

    _assert_sanitized(
        caught,
        code="OPENAI_FORMAL_DEMO_INTENT_RESPONSE_INVALID",
        secret=secret,
    )
    assert len(scripted.requests) == 1


def test_oversized_candidate_fails_closed_after_one_call() -> None:
    disclosure = _disclosure()
    oversized = "x" * (MAX_TASK_INTENT_JSON_BYTES + 1)
    scripted = ScriptedResponses([_completed_response(oversized)])
    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_INTENT_RESPONSE_TOO_LARGE$",
    ):
        _run_candidate(
            OpenAIResponsesIntentCandidatePort(
                _activation(disclosure),
                gate=_consumed_gate(disclosure),
                responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
            ),
            _request(disclosure),
        )
    assert len(scripted.requests) == 1


@pytest.mark.parametrize("terminal", ("refused", "truncated", "malformed"))
def test_host_coordinator_does_not_retry_terminal_provider_output(
    terminal: str,
) -> None:
    disclosure = _disclosure()
    gate, permit = _gate_and_permit(disclosure)
    if terminal == "refused":
        response: object = {
            "status": "completed",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "refusal", "refusal": "no"}],
                }
            ],
        }
        code = "FORMAL_DEMO_INTENT_CANDIDATE_REFUSED"
    elif terminal == "truncated":
        response = {
            "status": "incomplete",
            "model": FORMAL_DEMO_OPENAI_MODEL,
            "output": [],
        }
        code = "FORMAL_DEMO_INTENT_CANDIDATE_TRUNCATED"
    else:
        response = _completed_response("not json")
        code = "FORMAL_DEMO_JSON_INVALID"
    scripted = ScriptedResponses([response, _completed_response()])
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=gate,
        responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
    )

    with pytest.raises((FormalDemoIntentRequestError, ValueError), match=f"^{code}$"):
        asyncio.run(
            compile_task_intent_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                scenario=FORMAL_DEMO_V1_SCENARIO,
                port=port,
            )
        )

    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(scripted.requests) == 1
    assert len(scripted.script) == 1


def test_port_replay_is_terminal_without_second_factory_or_provider_call() -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses([_completed_response(), _completed_response()])
    factory = CountingFactory(scripted)
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=_consumed_gate(disclosure),
        responses_factory=factory,  # type: ignore[arg-type]
    )
    request = _request(disclosure)

    assert _run_candidate(port, request).status is IntentCandidateStatus.COMPLETED
    with pytest.raises(
        OpenAIFormalDemoIntentError,
        match="^OPENAI_FORMAL_DEMO_INTENT_PORT_REPLAY$",
    ):
        _run_candidate(port, request)

    assert factory.calls == 1
    assert len(scripted.requests) == 1
    assert len(scripted.script) == 1


def test_concurrent_port_entry_has_one_winner_and_one_terminal_loser() -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses([_completed_response(), _completed_response()])
    factory = CountingFactory(scripted)
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=_consumed_gate(disclosure),
        responses_factory=factory,  # type: ignore[arg-type]
    )
    request = _request(disclosure)

    async def race() -> list[object]:
        return await asyncio.gather(
            port.create_candidate(request),
            port.create_candidate(request),
            return_exceptions=True,
        )

    results = asyncio.run(race())
    successes = [item for item in results if isinstance(item, IntentCandidateResponse)]
    failures = [item for item in results if isinstance(item, BaseException)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert str(failures[0]) == "OPENAI_FORMAL_DEMO_INTENT_PORT_REPLAY"
    assert factory.calls == 1
    assert len(scripted.requests) == 1
    assert len(scripted.script) == 1


@pytest.mark.parametrize("drift", ("route", "profile", "task", "draft", "disclosure"))
def test_route_profile_task_and_draft_drift_fail_before_factory_or_io(
    drift: str,
) -> None:
    disclosure = _disclosure()
    request = _request(disclosure)
    if drift == "route":
        request = replace(request, route=_route(model_id="gpt-attacker"))
    elif drift == "profile":
        request = replace(request, profile_digest="0" * 64)
    elif drift == "task":
        altered = "Different task that was never activated."
        request = replace(
            request,
            source_task=altered,
            source_task_digest=sha256(altered.encode()).hexdigest(),
        )
    elif drift == "draft":
        request = replace(request, resume_identity="different-draft")
    else:
        request = replace(request, disclosure_digest="0" * 64)
    scripted = ScriptedResponses([_completed_response()])
    factory = CountingFactory(scripted)
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=_consumed_gate(disclosure),
        responses_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(OpenAIFormalDemoIntentError):
        _run_candidate(port, request)

    assert factory.calls == 0
    assert scripted.requests == []


@pytest.mark.parametrize("preflight", ("bytes", "tokens"))
def test_request_byte_and_token_preflight_fail_before_factory_or_io(
    preflight: str,
) -> None:
    disclosure = _disclosure()
    scripted = ScriptedResponses([_completed_response()])
    factory = CountingFactory(scripted)
    kwargs: dict[str, object] = {
        "activation": _activation(disclosure),
        "gate": _consumed_gate(disclosure),
        "responses_factory": factory,
    }
    if preflight == "bytes":
        kwargs["max_request_bytes"] = 1
        code = "OPENAI_FORMAL_DEMO_INTENT_REQUEST_TOO_LARGE"
    else:
        kwargs["context_window_tokens"] = 4_097
        kwargs["output_token_reserve"] = 4_096
        code = "OPENAI_FORMAL_DEMO_INTENT_TOKEN_WINDOW_EXCEEDED"
    port = OpenAIResponsesIntentCandidatePort(**kwargs)  # type: ignore[arg-type]

    with pytest.raises(OpenAIFormalDemoIntentError, match=f"^{code}$"):
        _run_candidate(port, _request(disclosure))

    assert factory.calls == 0
    assert scripted.requests == []


@pytest.mark.parametrize("failure_site", ("factory", "request"))
def test_provider_exception_is_sanitized_and_never_retried(
    failure_site: str,
) -> None:
    disclosure = _disclosure()
    secret = "sk-secret-provider-error"
    scripted = ScriptedResponses([RuntimeError(secret), _completed_response()])

    def fail_factory() -> object:
        raise RuntimeError(secret)

    factory: object = fail_factory if failure_site == "factory" else CountingFactory(scripted)
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=_consumed_gate(disclosure),
        responses_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(OpenAIFormalDemoIntentError) as caught:
        _run_candidate(port, _request(disclosure))

    _assert_sanitized(
        caught,
        code="OPENAI_FORMAL_DEMO_INTENT_REQUEST_FAILED",
        secret=secret,
    )
    assert len(scripted.requests) == (0 if failure_site == "factory" else 1)


@pytest.mark.parametrize("failure_site", ("factory", "request", "response"))
@pytest.mark.parametrize(
    "terminal_type",
    (
        asyncio.CancelledError,
        KeyboardInterrupt,
        SystemExit,
        GeneratorExit,
    ),
)
def test_direct_port_sanitizes_process_control_from_every_sdk_phase(
    failure_site: str,
    terminal_type: type[BaseException],
) -> None:
    disclosure = _disclosure()
    secret = f"secret-{failure_site}-{terminal_type.__name__}"
    terminal = terminal_type(secret)

    class ExplodingResponse:
        @property
        def model(self) -> object:
            raise terminal

    scripted = ScriptedResponses(
        [
            terminal if failure_site == "request" else ExplodingResponse(),
            _completed_response(),
        ]
    )

    def fail_factory() -> object:
        raise terminal

    factory: object = (
        fail_factory
        if failure_site == "factory"
        else CountingFactory(scripted)
    )
    port = OpenAIResponsesIntentCandidatePort(
        _activation(disclosure),
        gate=_consumed_gate(disclosure),
        responses_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(terminal_type) as caught:
        _run_candidate(port, _request(disclosure))

    assert caught.value.__context__ is None
    assert caught.value.args == ((1,) if terminal_type is SystemExit else ())
    rendered = "".join(
        traceback.format_exception(
            type(caught.value),
            caught.value,
            caught.value.__traceback__,
        )
    )
    assert secret not in rendered
    assert len(scripted.requests) == (0 if failure_site == "factory" else 1)
    assert len(scripted.script) == (2 if failure_site == "factory" else 1)


def test_activation_drift_during_await_fails_terminally_before_scope_binding() -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)

    def drift_activation(_request: dict[str, object]) -> object:
        object.__setattr__(activation, "account_scope_digest", "b" * 64)
        return _completed_response()

    scripted = ScriptedResponses([drift_activation, _completed_response()])
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=gate,
        responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
    )

    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_PORT_FAILED$",
    ) as caught:
        asyncio.run(
            compile_openai_provider_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                activation=activation,
                port=port,
            )
        )

    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(scripted.requests) == 1
    assert len(scripted.script) == 1


def test_gate_disclosure_drift_during_await_fails_before_scope_binding() -> None:
    disclosure = _disclosure()
    replacement = _disclosure(
        source_task="Use a different reviewed non-sensitive fixture set."
    )
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)

    def drift_gate(_request: dict[str, object]) -> object:
        gate._disclosure = replacement  # type: ignore[attr-defined]
        return _completed_response()

    scripted = ScriptedResponses([drift_gate, _completed_response()])
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=gate,
        responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
    )

    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_PORT_FAILED$",
    ) as caught:
        asyncio.run(
            compile_openai_provider_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                activation=activation,
                port=port,
            )
        )

    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED
    assert gate.disclosure.source_task_digest != disclosure.source_task_digest
    assert len(scripted.requests) == 1
    assert len(scripted.script) == 1


def test_provider_scope_success_is_exactly_bound_and_never_enables_start() -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)
    scripted = ScriptedResponses([_completed_response()])
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=gate,
        responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
    )

    result = asyncio.run(
        compile_openai_provider_scope_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
            activation=activation,
            port=port,
        )
    )

    assert isinstance(result, ProviderScopeCompilation)
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(scripted.requests) == 1
    assert result.account_scope_digest == ACCOUNT_SCOPE_DIGEST
    assert result.activation_digest == activation.content_digest
    assert result.provider_id == "openai"
    assert result.region == "global"
    assert result.model_id == "gpt-5.6-terra"
    assert result.provider_calls == result.attempt.port_calls == 1
    assert result.retries == 0
    assert result.attempt.automatic_retry is False
    assert result.external_work_occurred is True
    assert result.start_enabled is False
    assert result.grants_execution_authority is False
    assert result.scope.task_intent_digest == result.attempt.intent.content_digest
    assert result.scope.scenario_digest == result.attempt.scenario_digest
    assert result.scope.resume_identity == disclosure.resume_identity
    assert not hasattr(result, "start")
    bound = result.bound_payload()
    assert bound["activation_digest"] == activation.content_digest
    assert bound["start_enabled"] is False
    assert bound["grants_execution_authority"] is False
    assert bound["contains_source_task"] is False
    assert bound["contains_credential_value"] is False
    assert bound["contains_model_prose"] is False
    assert SOURCE_TASK not in json.dumps(bound)


def test_provider_scope_rejects_mismatched_activation_and_port_before_consumption() -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    other_activation = _activation(disclosure, account_scope_digest="b" * 64)
    gate, permit = _gate_and_permit(disclosure)
    factory = CountingFactory(ScriptedResponses([_completed_response()]))
    port = OpenAIResponsesIntentCandidatePort(
        other_activation,
        gate=gate,
        responses_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(
        FormalDemoProviderScopeError,
        match="^FORMAL_DEMO_PROVIDER_SCOPE_PORT_INVALID$",
    ):
        asyncio.run(
            compile_openai_provider_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                activation=activation,
                port=port,
            )
        )

    assert gate.state is IntentCompileGateState.PERMITTED
    assert factory.calls == 0


def test_provider_scope_rejects_port_bound_to_a_different_consumed_gate() -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)
    other_gate = _consumed_gate(disclosure)
    factory = CountingFactory(ScriptedResponses([_completed_response()]))
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=other_gate,
        responses_factory=factory,  # type: ignore[arg-type]
    )

    with pytest.raises(
        FormalDemoProviderScopeError,
        match="^FORMAL_DEMO_PROVIDER_SCOPE_PORT_INVALID$",
    ):
        asyncio.run(
            compile_openai_provider_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                activation=activation,
                port=port,
            )
        )

    assert gate.state is IntentCompileGateState.PERMITTED
    assert factory.calls == 0


def test_provider_scope_compilation_exception_is_sanitized_after_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)
    scripted = ScriptedResponses([_completed_response()])
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=gate,
        responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
    )
    secret = "secret-scope-compiler-context"

    def fail_scope(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError(secret)

    monkeypatch.setattr(provider_scope_module, "compile_generic_scope_sheet", fail_scope)

    with pytest.raises(FormalDemoProviderScopeError) as caught:
        asyncio.run(
            compile_openai_provider_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                activation=activation,
                port=port,
            )
        )

    _assert_sanitized(
        caught,
        code="FORMAL_DEMO_PROVIDER_SCOPE_COMPILATION_FAILED",
        secret=secret,
    )
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(scripted.requests) == 1


@pytest.mark.parametrize(
    "terminal",
    (
        asyncio.CancelledError(),
        KeyboardInterrupt("secret interrupt"),
        SystemExit("secret exit"),
        GeneratorExit("secret generator close"),
    ),
)
def test_provider_scope_compiler_preserves_sanitized_process_control(
    monkeypatch: pytest.MonkeyPatch,
    terminal: BaseException,
) -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)
    scripted = ScriptedResponses([_completed_response()])
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=gate,
        responses_factory=CountingFactory(scripted),  # type: ignore[arg-type]
    )

    def stop_scope(*_args: object, **_kwargs: object) -> object:
        raise terminal

    monkeypatch.setattr(provider_scope_module, "compile_generic_scope_sheet", stop_scope)

    expected_type = type(terminal)
    with pytest.raises(expected_type) as caught:
        asyncio.run(
            compile_openai_provider_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
                activation=activation,
                port=port,
            )
        )

    assert caught.value.__context__ is None
    if isinstance(terminal, SystemExit):
        assert caught.value.args == (1,)
    else:
        assert caught.value.args == ()
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(scripted.requests) == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("provider_calls", 2),
        ("retries", 1),
        ("external_work_occurred", False),
        ("start_enabled", True),
        ("grants_execution_authority", True),
    ),
)
def test_provider_scope_result_cannot_be_rebuilt_with_wider_authority(
    field_name: str,
    value: object,
) -> None:
    disclosure = _disclosure()
    activation = _activation(disclosure)
    gate, permit = _gate_and_permit(disclosure)
    port = OpenAIResponsesIntentCandidatePort(
        activation,
        gate=gate,
        responses_factory=CountingFactory(
            ScriptedResponses([_completed_response()])
        ),  # type: ignore[arg-type]
    )
    result = asyncio.run(
        compile_openai_provider_scope_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
            activation=activation,
            port=port,
        )
    )

    with pytest.raises(
        FormalDemoProviderScopeError,
        match="^FORMAL_DEMO_PROVIDER_SCOPE_INVALID$",
    ):
        replace(result, **{field_name: value})
