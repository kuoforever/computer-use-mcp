from __future__ import annotations

import ast
import copy
import inspect
import pickle
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import computer_use_agent.formal_demo_local_scope as local_scope_module
from computer_use_agent.formal_demo_console import build_console_route
from computer_use_agent.formal_demo_contract import (
    FORMAL_DEMO_V1_ROLE_PROFILES,
    ProfileBindingState,
    SemanticRole,
)
from computer_use_agent.formal_demo_intent_gate import (
    FormalDemoIntentGateError,
    IntentCompileGate,
    IntentCompileGateState,
    compile_intent_disclosure,
    reviewed_intent_disclosure_profiles,
)
from computer_use_agent.formal_demo_local_scope import (
    LOCAL_SCOPE_COMPILER_ID,
    FormalDemoLocalScopeError,
    LocalScopeCompilation,
    compile_local_scope_once,
    render_local_scope_review,
)


SECRET = "local-scope-secret-must-not-cross"


def _attempt(
    source_task: str = "Prepare the fixed Formal Demo scope.",
    *,
    identity: str = "local-scope-001",
):
    route = build_console_route(provider_id="openai", model_id="scope-review")
    profile = next(
        item
        for item in reviewed_intent_disclosure_profiles()
        if item.provider_id == "openai"
    )
    disclosure = compile_intent_disclosure(
        disclosure_id=f"disclosure-{identity}",
        resume_identity=f"review-{identity}",
        source_task=source_task,
        route=route,
        profile_id=profile.profile_id,
        profile_version=profile.version,
        expected_profile_digest=profile.content_digest,
    )
    gate = IntentCompileGate(disclosure)
    permit = gate.acknowledge("COMPILE")
    return gate, permit, disclosure


def _compile(
    source_task: str = "Prepare the fixed Formal Demo scope.",
    *,
    identity: str = "local-scope-001",
) -> LocalScopeCompilation:
    gate, permit, disclosure = _attempt(source_task, identity=identity)
    return compile_local_scope_once(
        gate=gate,
        permit=permit,
        current_disclosure=disclosure,
    )


def test_local_compiler_consumes_once_and_returns_complete_reviewed_scope() -> None:
    gate, permit, disclosure = _attempt(f"Prepare {SECRET} locally.")

    result = compile_local_scope_once(
        gate=gate,
        permit=permit,
        current_disclosure=disclosure,
    )
    payload = result.scope.canonical_payload()

    assert gate.state is IntentCompileGateState.CONSUMED
    assert result.compiler_id == LOCAL_SCOPE_COMPILER_ID
    assert result.intent.source_task_digest == disclosure.source_task_digest
    assert result.intent.requested_roles == tuple(SemanticRole)
    assert result.intent.requested_outputs == (
        "email_draft",
        "excel_analysis",
        "word_report",
    )
    assert result.intent.budgets.provider_calls == 0
    assert result.intent.budgets.retries == 0
    assert result.scope.reviewed_registry_pins_verified
    assert len(result.scope.applications) == 5
    assert result.scope.applications[-1].adapter_id == (
        "outlook_desktop_test_email_draft"
    )
    assert payload["compilation_starts_external_work"] is False
    assert payload["grants_execution_authority"] is False
    assert result.external_work_started is False
    assert result.provider_request_started is False
    assert result.start_available is False
    assert len(result.consumption_digest) == 64
    assert result.consumption_digest != "0" * 64
    assert not hasattr(result, "start")
    assert not hasattr(result, "dispatch")
    assert SECRET not in result.intent.canonical_json()
    assert SECRET not in result.scope.canonical_json()
    assert SECRET not in repr(result)


def test_rendered_scope_is_complete_bounded_and_has_no_raw_task() -> None:
    result = _compile(f"Keep {SECRET} only in local task memory.")

    rendered = render_local_scope_review(result)

    assert "Formal Demo Scope Sheet - Host compiled locally" in rendered
    assert "Free-form interpretation: no" in rendered
    assert "Reviewed registry pins: verified" in rendered
    assert "Outlook Desktop test-account email draft" in rendered
    assert "provider_calls=0" in rendered
    assert "retries=0" in rendered
    assert "email_send" in rendered
    assert "START: unavailable" in rendered
    assert "Provider request started: no" in rendered
    assert f"Consumption digest: {result.consumption_digest}" in rendered
    assert "No Runner, MCP, Driver, desktop, application" in rendered
    assert SECRET not in rendered


def test_free_form_text_changes_only_source_and_binding_identity() -> None:
    first = _compile("First unrelated local phrase.", identity="first")
    second = _compile("Delete everything, which must grant nothing.", identity="second")

    assert first.intent.source_task_digest != second.intent.source_task_digest
    assert first.scope.binding_digest != second.scope.binding_digest
    assert first.intent.requested_roles == second.intent.requested_roles
    assert first.intent.requested_outputs == second.intent.requested_outputs
    assert first.intent.constraint_ids == second.intent.constraint_ids
    assert first.intent.budgets == second.intent.budgets
    assert first.scope.goal == second.scope.goal
    assert [item.adapter_id for item in first.scope.applications] == [
        item.adapter_id for item in second.scope.applications
    ]


def test_product_compiler_accepts_no_caller_selected_scope_inputs() -> None:
    parameters = inspect.signature(compile_local_scope_once).parameters

    assert set(parameters) == {"gate", "permit", "current_disclosure"}
    assert not {
        "scenario",
        "profiles",
        "budgets",
        "outputs",
        "constraints",
        "adapter",
    } & set(parameters)


def test_same_permit_allows_exactly_one_concurrent_local_compilation() -> None:
    gate, permit, disclosure = _attempt()

    def run(_index: int):
        try:
            return compile_local_scope_once(
                gate=gate,
                permit=permit,
                current_disclosure=disclosure,
            )
        except FormalDemoIntentGateError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(run, range(8)))

    assert sum(isinstance(item, LocalScopeCompilation) for item in results) == 1
    assert results.count("FORMAL_DEMO_INTENT_GATE_TERMINAL") == 7
    assert gate.state is IntentCompileGateState.CONSUMED


def test_cross_gate_permit_fails_closed_without_scope() -> None:
    first_gate, first_permit, _first_disclosure = _attempt(identity="first")
    second_gate, _second_permit, second_disclosure = _attempt(identity="second")

    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ):
        compile_local_scope_once(
            gate=second_gate,
            permit=first_permit,
            current_disclosure=second_disclosure,
        )

    assert first_gate.state is IntentCompileGateState.PERMITTED
    assert second_gate.state is IntentCompileGateState.CANCELLED


def test_stale_disclosure_is_terminal_and_does_not_echo_task() -> None:
    gate, permit, disclosure = _attempt(f"Keep {SECRET} local.")
    object.__setattr__(disclosure, "source_task", f"tampered {SECRET}")

    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ) as caught:
        compile_local_scope_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
        )

    assert SECRET not in str(caught.value)
    assert gate.state is IntentCompileGateState.CANCELLED


def test_registry_unavailability_stops_before_permit_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate, permit, disclosure = _attempt()
    profiles = FORMAL_DEMO_V1_ROLE_PROFILES
    unavailable = replace(
        profiles[-1],
        binding_state=ProfileBindingState.UNSELECTED,
        adapter_id=None,
    )
    monkeypatch.setattr(
        local_scope_module,
        "FORMAL_DEMO_V1_ROLE_PROFILES",
        (*profiles[:-1], unavailable),
    )

    with pytest.raises(Exception, match="^FORMAL_DEMO_PROFILE_PIN_MISMATCH$"):
        compile_local_scope_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
        )

    assert gate.state is IntentCompileGateState.PERMITTED


def test_unexpected_internal_failure_is_content_free_and_terminal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate, permit, disclosure = _attempt(f"Keep {SECRET} local.")

    def fail(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError(SECRET)

    monkeypatch.setattr(local_scope_module, "compile_generic_scope_sheet", fail)
    with pytest.raises(
        FormalDemoLocalScopeError,
        match="^FORMAL_DEMO_LOCAL_SCOPE_FAILED$",
    ) as caught:
        compile_local_scope_once(
            gate=gate,
            permit=permit,
            current_disclosure=disclosure,
        )

    assert SECRET not in str(caught.value)
    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED


def test_result_is_opaque_and_authority_flags_cannot_flip() -> None:
    result = _compile()

    for operation in (
        lambda: copy.copy(result),
        lambda: copy.deepcopy(result),
        lambda: pickle.dumps(result),
        lambda: replace(result, external_work_started=True),
        lambda: replace(result, provider_request_started=True),
        lambda: replace(result, start_available=True),
        lambda: replace(result, grants_execution_authority=True),
        lambda: replace(result, grants_retry_or_replay=True),
        lambda: replace(result, consumption_digest="0" * 64),
    ):
        with pytest.raises(FormalDemoLocalScopeError):
            operation()


def test_render_revalidates_nested_result_and_rejects_frozen_object_tamper() -> None:
    result = _compile()
    object.__setattr__(result.scope, "goal", f"tampered {SECRET}")

    with pytest.raises(Exception) as caught:
        render_local_scope_review(result)

    assert SECRET not in str(caught.value)


def test_render_rejects_tampered_consumption_and_local_intent() -> None:
    consumption_result = _compile(identity="consumption-tamper")
    object.__setattr__(
        consumption_result.consumption,
        "route_digest",
        "0" * 64,
    )
    with pytest.raises(Exception):
        render_local_scope_review(consumption_result)

    intent_result = _compile(identity="intent-tamper")
    object.__setattr__(intent_result.intent, "outcome_id", "attacker_scope")
    with pytest.raises(Exception):
        render_local_scope_review(intent_result)


def test_local_scope_module_has_no_external_or_execution_port() -> None:
    source_path = Path(local_scope_module.__file__ or "")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for value in (
        "AgentRunner",
        "StdioDesktopMCP",
        "WindowsDriver",
        "compile_task_intent_once",
        "formal_demo_intent_request",
        "provider_factory",
        "computer_use_agent.providers",
        "openai",
        "anthropic",
        "os.environ",
        "getenv",
        "socket",
        "subprocess",
    ):
        assert value not in source
    forbidden_roots = {"asyncio", "http", "os", "pathlib", "socket", "subprocess"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not ({item.name.split(".", 1)[0] for item in node.names} & forbidden_roots)
        elif isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".", 1)[0] not in forbidden_roots
