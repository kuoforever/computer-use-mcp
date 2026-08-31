from __future__ import annotations

import asyncio
import os
import re

import pytest

from computer_use_agent.formal_demo_contract import FORMAL_DEMO_V1_SCENARIO
from computer_use_agent.formal_demo_intent_gate import (
    INTENT_COMPILE_TOKEN,
    IntentCompileGate,
    ProviderIntentRoute,
    ProviderProtocol,
    compile_intent_disclosure,
    resolve_reviewed_intent_disclosure_profile,
    reviewed_intent_disclosure_profiles,
)
from computer_use_agent.formal_demo_provider_scope import (
    compile_openai_provider_scope_once,
)
from computer_use_agent.providers.openai_intent import (
    FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN,
    FORMAL_DEMO_OPENAI_MODEL,
    OpenAIResponsesIntentCandidatePort,
    bind_openai_intent_activation,
)


pytestmark = pytest.mark.formal_demo_openai_integration

_LIVE_ENVIRONMENT = "CUMCP_RUN_FORMAL_DEMO_OPENAI_LIVE"
_ACCOUNT_SCOPE_DIGEST_ENVIRONMENT = (
    "CUMCP_FORMAL_DEMO_OPENAI_ACCOUNT_SCOPE_DIGEST"
)
_ACCOUNT_REVIEW_TOKEN_ENVIRONMENT = (
    "CUMCP_FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN"
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_TASK = (
    "Use only the dedicated non-sensitive fixtures to create a verified "
    "analysis, report, and unsent test-account draft."
)


def _live_preflight() -> tuple[str, str]:
    if os.environ.get(_LIVE_ENVIRONMENT) != "1":
        pytest.skip(f"set {_LIVE_ENVIRONMENT}=1 for the explicit live gate")
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is absent")
    account_scope_digest = os.environ.get(
        _ACCOUNT_SCOPE_DIGEST_ENVIRONMENT,
        "",
    )
    if _DIGEST.fullmatch(account_scope_digest) is None:
        pytest.skip(
            f"{_ACCOUNT_SCOPE_DIGEST_ENVIRONMENT} is not lowercase 64hex"
        )
    acknowledgement = os.environ.get(_ACCOUNT_REVIEW_TOKEN_ENVIRONMENT, "")
    if acknowledgement != FORMAL_DEMO_OPENAI_ACCOUNT_REVIEW_TOKEN:
        pytest.skip(
            f"{_ACCOUNT_REVIEW_TOKEN_ENVIRONMENT} does not contain the exact "
            "current account review token"
        )
    pytest.importorskip("openai", reason="OpenAI SDK is not installed")
    return account_scope_digest, acknowledgement


def test_exact_openai_formal_demo_intent_and_scope_live_gate() -> None:
    account_scope_digest, acknowledgement = _live_preflight()
    selected = next(
        profile
        for profile in reviewed_intent_disclosure_profiles()
        if profile.provider_id == "openai"
    )
    profile = resolve_reviewed_intent_disclosure_profile(
        selected.profile_id,
        version=selected.version,
        expected_digest=selected.content_digest,
    )
    disclosure = compile_intent_disclosure(
        disclosure_id="formal-demo-openai-live-007f",
        resume_identity="formal-demo-openai-live-review-007f",
        source_task=_SOURCE_TASK,
        route=ProviderIntentRoute(
            provider_id="openai",
            region="global",
            model_id=FORMAL_DEMO_OPENAI_MODEL,
            protocol=ProviderProtocol.OPENAI_RESPONSES,
            endpoint="https://api.openai.com/v1",
        ),
        profile_id=profile.profile_id,
        profile_version=profile.version,
        expected_profile_digest=profile.content_digest,
    )
    gate = IntentCompileGate(disclosure)
    permit = gate.acknowledge(INTENT_COMPILE_TOKEN)
    activation = bind_openai_intent_activation(
        disclosure,
        account_scope_digest=account_scope_digest,
        acknowledgement=acknowledgement,
    )
    port = OpenAIResponsesIntentCandidatePort(activation, gate=gate)

    result = asyncio.run(
        compile_openai_provider_scope_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
            activation=activation,
            port=port,
        )
    )

    assert result.provider_id == "openai"
    assert result.region == "global"
    assert result.model_id == FORMAL_DEMO_OPENAI_MODEL
    assert result.account_scope_digest == account_scope_digest
    assert result.provider_calls == result.attempt.port_calls == 1
    assert result.retries == 0
    assert result.scope.task_intent_digest == result.attempt.intent.content_digest
    assert result.scope.scenario_digest == FORMAL_DEMO_V1_SCENARIO.content_digest
    assert result.scope.resume_identity == disclosure.resume_identity
    assert result.start_enabled is False
    assert result.grants_execution_authority is False
    assert not hasattr(result, "start")
