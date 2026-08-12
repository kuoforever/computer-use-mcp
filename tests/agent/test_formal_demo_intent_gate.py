from __future__ import annotations

import ast
import copy
import json
import pickle
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

import computer_use_agent.formal_demo_intent_gate as gate_module
from computer_use_agent.formal_demo_contract import (
    MAX_SOURCE_TASK_BYTES,
    TASK_INTENT_VERSION,
    decode_task_intent,
)
from computer_use_agent.formal_demo_intent_gate import (
    FormalDemoIntentDisclosure,
    FormalDemoIntentGateError,
    INTENT_COMPILE_REQUEST_LIMIT,
    INTENT_COMPILE_TOKEN,
    INTENT_DISCLOSURE_VERSION,
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


SOURCE_TASK = "Create a fixture-grounded report and an unsent test draft."
DISCLOSURE_ID = "formal-demo-draft-001"
RESUME_IDENTITY = "formal-demo-review-001"


def _openai_route(**overrides: object) -> ProviderIntentRoute:
    values: dict[str, object] = {
        "provider_id": "openai",
        "region": "global",
        "model_id": "gpt-reviewed",
        "protocol": ProviderProtocol.OPENAI_RESPONSES,
        "endpoint": "https://api.openai.com/v1",
        "workspace_id": None,
    }
    values.update(overrides)
    return ProviderIntentRoute(**values)  # type: ignore[arg-type]


def _profile(provider_id: str = "openai") -> ReviewedIntentDisclosureProfile:
    selected = next(
        profile
        for profile in reviewed_intent_disclosure_profiles()
        if profile.provider_id == provider_id
    )
    return resolve_reviewed_intent_disclosure_profile(
        selected.profile_id,
        version=selected.version,
        expected_digest=selected.content_digest,
    )


def _disclosure(
    *,
    source_task: str = SOURCE_TASK,
    route: ProviderIntentRoute | None = None,
    profile: ReviewedIntentDisclosureProfile | None = None,
    disclosure_id: str = DISCLOSURE_ID,
    resume_identity: str = RESUME_IDENTITY,
) -> FormalDemoIntentDisclosure:
    selected = _profile() if profile is None else profile
    return compile_intent_disclosure(
        disclosure_id=disclosure_id,
        resume_identity=resume_identity,
        source_task=source_task,
        route=_openai_route() if route is None else route,
        profile_id=selected.profile_id,
        profile_version=selected.version,
        expected_profile_digest=selected.content_digest,
    )


def _intent_payload() -> str:
    return json.dumps(
        {
            "version": TASK_INTENT_VERSION,
            "scenario_id": "formal_demo_v1",
            "outcome_id": "verified_analysis_report_and_draft",
            "requested_roles": ["source", "report", "handoff"],
            "requested_outputs": ["word_report", "email_draft"],
            "constraint_ids": ["fixture_only", "email_draft_only"],
            "risk_ceiling": "draft",
            "budgets": {
                "provider_calls": 1,
                "tool_calls": 0,
                "side_effects": 0,
                "retries": 0,
                "artifacts": 0,
            },
        }
    )


def test_reviewed_profiles_are_exact_versioned_immutable_and_conservative() -> None:
    profiles = reviewed_intent_disclosure_profiles()
    assert tuple(profile.provider_id for profile in profiles) == (
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
    assert len({profile.profile_id for profile in profiles}) == 9
    assert len({profile.content_digest for profile in profiles}) == 9
    for profile in profiles:
        assert profile.version == INTENT_DISCLOSURE_VERSION == 1
        assert "not verified" in profile.retention_notice.lower() or "does not verify" in profile.retention_notice.lower()
        with pytest.raises(AttributeError):
            profile.profile_id = "changed"  # type: ignore[misc]


def test_exported_profile_snapshot_mutation_cannot_rewrite_reviewed_truth() -> None:
    snapshot = _profile()
    original_digest = snapshot.content_digest
    object.__setattr__(snapshot, "data_use_notice", "ATTACKER NOTICE")
    assert snapshot.content_digest != original_digest

    reviewed = resolve_reviewed_intent_disclosure_profile(
        snapshot.profile_id,
        version=snapshot.version,
        expected_digest=original_digest,
    )
    assert reviewed.data_use_notice != "ATTACKER NOTICE"
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_DISCLOSURE_PROFILE_PIN_MISMATCH$",
    ):
        resolve_reviewed_intent_disclosure_profile(
            snapshot.profile_id,
            version=snapshot.version,
            expected_digest=snapshot.content_digest,
        )


def test_profile_resolution_requires_exact_id_version_and_digest() -> None:
    profile = _profile()
    resolved = resolve_reviewed_intent_disclosure_profile(
        profile.profile_id,
        version=profile.version,
        expected_digest=profile.content_digest,
    )
    assert resolved == profile
    assert resolved is not profile

    cases = (
        ("unknown_profile", profile.version, profile.content_digest),
        (profile.profile_id, 2, profile.content_digest),
        (profile.profile_id, profile.version, "0" * 64),
        (True, profile.version, profile.content_digest),
        (profile.profile_id, True, profile.content_digest),
        (profile.profile_id, profile.version, None),
    )
    for profile_id, version, digest in cases:
        with pytest.raises(FormalDemoIntentGateError):
            resolve_reviewed_intent_disclosure_profile(
                profile_id,
                version=version,
                expected_digest=digest,
            )


def test_route_is_exactly_validated_against_the_static_provider_catalog() -> None:
    route = _openai_route()
    assert route.content_digest == _openai_route().content_digest
    assert route.canonical_payload() == {
        "provider_id": "openai",
        "region": "global",
        "model_id": "gpt-reviewed",
        "protocol": "openai_responses",
        "endpoint": "https://api.openai.com/v1",
        "workspace_id": None,
    }

    invalid = (
        {"provider_id": "unknown"},
        {"region": "cn"},
        {"protocol": ProviderProtocol.ANTHROPIC_MESSAGES},
        {"endpoint": "https://attacker.example/v1"},
        {"endpoint": "https://user:secret@api.openai.com/v1"},
        {"workspace_id": "not-allowed"},
        {"model_id": True},
    )
    for overrides in invalid:
        with pytest.raises(
            FormalDemoIntentGateError,
            match="^FORMAL_DEMO_INTENT_ROUTE_INVALID$",
        ):
            _openai_route(**overrides)

    qwen = ProviderIntentRoute(
        provider_id="qwen",
        region="ap-southeast-1",
        model_id="qwen-reviewed",
        protocol=ProviderProtocol.OPENAI_RESPONSES,
        endpoint=(
            "https://workspace-demo.ap-southeast-1.maas.aliyuncs.com/"
            "compatible-mode/v1"
        ),
        workspace_id="workspace-demo",
    )
    assert qwen.workspace_id == "workspace-demo"
    local = ProviderIntentRoute(
        provider_id="local_openai",
        region="local",
        model_id="local-reviewed",
        protocol=ProviderProtocol.OPENAI_CHAT_COMPLETIONS,
        endpoint="http://127.0.0.1:11434/v1",
    )
    assert local.endpoint.startswith("http://127.0.0.1:")


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("provider_id", "qwen"),
        ("region", "cn"),
        ("model_id", True),
        ("protocol", ProviderProtocol.ANTHROPIC_MESSAGES),
        ("endpoint", "https://attacker.example/v1"),
        ("workspace_id", "attacker"),
    ),
)
def test_post_construction_route_tamper_cannot_be_resigned(
    field_name: str,
    value: object,
) -> None:
    route = _openai_route()
    object.__setattr__(route, field_name, value)
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_ROUTE_INVALID$",
    ):
        _disclosure(route=route)


def test_direct_disclosure_construction_revalidates_a_tampered_route() -> None:
    route = _openai_route()
    object.__setattr__(route, "endpoint", "https://attacker.example/v1")
    profile = _profile()

    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_ROUTE_INVALID$",
    ):
        FormalDemoIntentDisclosure(
            disclosure_id=DISCLOSURE_ID,
            resume_identity=RESUME_IDENTITY,
            source_task=SOURCE_TASK,
            route=route,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            profile_digest=profile.content_digest,
            data_use_notice=profile.data_use_notice,
            retention_notice=profile.retention_notice,
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("disclosure_id", "bad identity with spaces"),
        ("resume_identity", "bad identity with spaces"),
        ("source_task", "\x00"),
        ("purpose", "Attacker-selected purpose"),
        ("task_intent_version", 2),
        ("version", 2),
        ("profile_digest", "0" * 64),
        ("data_use_notice", "Attacker notice"),
    ),
)
def test_gate_revalidates_every_disclosure_field_after_tamper(
    field_name: str,
    value: object,
) -> None:
    disclosure = _disclosure()
    object.__setattr__(disclosure, field_name, value)

    with pytest.raises(FormalDemoIntentGateError):
        IntentCompileGate(disclosure)


def test_disclosure_renders_exact_sensitive_text_but_binding_does_not_copy_it() -> None:
    disclosure = _disclosure()
    rendered = disclosure.render()
    payload = disclosure.bound_payload()

    assert SOURCE_TASK in rendered
    assert "Provider: openai" in rendered
    assert f"Draft identity: {RESUME_IDENTITY}" in rendered
    assert "Region: global" in rendered
    assert "Model: gpt-reviewed" in rendered
    assert "Endpoint: https://api.openai.com/v1" in rendered
    assert "Type COMPILE exactly" in rendered
    assert "nothing external has started" in rendered
    assert SOURCE_TASK not in json.dumps(payload)
    assert payload["source_task_digest"] == disclosure.source_task_digest
    assert payload["route_digest"] == disclosure.route.content_digest
    assert payload["contains_credential_value"] is False
    assert payload["provider_readiness_checked"] is False
    assert payload["provider_request_started"] is False
    assert payload["external_work_started"] is False
    assert payload["durable_workflow_started"] is False
    assert payload["grants_provider_request"] is False
    assert payload["grants_execution_authority"] is False
    assert payload["grants_scope_or_start"] is False
    assert payload["grants_action_approval"] is False
    assert payload["grants_retry_or_replay"] is False
    assert SOURCE_TASK not in repr(disclosure)
    for disclosure_operation in (
        lambda: copy.copy(disclosure),
        lambda: copy.deepcopy(disclosure),
        lambda: pickle.dumps(disclosure),
    ):
        with pytest.raises(
            FormalDemoIntentGateError,
            match="^FORMAL_DEMO_INTENT_DISCLOSURE_OPAQUE$",
        ):
            disclosure_operation()


def test_operator_supplied_secret_like_text_is_disclosed_but_not_copied_to_artifacts() -> None:
    source = "Use pasted key sk-test-secret and summarize this email body."
    disclosure = _disclosure(source_task=source)
    rendered = disclosure.render()
    gate = IntentCompileGate(disclosure)
    permit = gate.acknowledge(INTENT_COMPILE_TOKEN)
    consumed = gate.consume(permit, current_disclosure=_disclosure(source_task=source))

    assert source in rendered
    assert "anything the operator included" in rendered
    assert source not in json.dumps(disclosure.bound_payload())
    assert source not in repr(permit)
    assert source not in repr(consumed)


def test_disclosure_source_digest_matches_task_intent_contract() -> None:
    disclosure = _disclosure()
    intent = decode_task_intent(_intent_payload(), source_task=SOURCE_TASK)
    assert disclosure.source_task_digest == intent.source_task_digest


@pytest.mark.parametrize(
    "token",
    (
        "compile",
        "Compile",
        " COMPILE",
        "COMPILE ",
        "COMPILE\n",
        "",
        b"COMPILE",
        None,
        True,
        1,
    ),
)
def test_only_exact_builtin_compile_token_can_issue_a_permit(token: object) -> None:
    gate = IntentCompileGate(_disclosure())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_ACKNOWLEDGEMENT_INVALID$",
    ):
        gate.acknowledge(token)
    assert gate.state is IntentCompileGateState.CANCELLED
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_GATE_TERMINAL$",
    ):
        gate.acknowledge(INTENT_COMPILE_TOKEN)


def test_exact_compile_issues_one_opaque_non_authoritative_permit() -> None:
    disclosure = _disclosure()
    gate = IntentCompileGate(disclosure)
    permit = gate.acknowledge(INTENT_COMPILE_TOKEN)

    assert gate.state is IntentCompileGateState.PERMITTED
    assert permit.disclosure_id == DISCLOSURE_ID
    assert permit.resume_identity == RESUME_IDENTITY
    assert permit.disclosure_digest == disclosure.content_digest
    assert permit.source_task_digest == disclosure.source_task_digest
    assert permit.route_digest == disclosure.route.content_digest
    assert permit.profile_digest == disclosure.profile_digest
    assert permit.task_intent_version == TASK_INTENT_VERSION
    assert INTENT_COMPILE_REQUEST_LIMIT == 1
    assert SOURCE_TASK not in repr(permit)
    assert not hasattr(permit, "dispatch")
    assert not hasattr(permit, "request")
    assert not hasattr(permit, "retry")
    assert not hasattr(permit, "replay")
    with pytest.raises(FormalDemoIntentGateError):
        gate.acknowledge(INTENT_COMPILE_TOKEN)


def test_permit_consumption_is_process_local_terminal_and_content_free() -> None:
    disclosure = _disclosure()
    gate = IntentCompileGate(disclosure)
    permit = gate.acknowledge(INTENT_COMPILE_TOKEN)
    consumed = gate.consume(permit, current_disclosure=_disclosure())

    assert gate.state is IntentCompileGateState.CONSUMED
    assert consumed.state is IntentCompileGateState.CONSUMED
    assert consumed.provider_request_started is False
    assert consumed.resume_identity == RESUME_IDENTITY
    assert consumed.grants_execution_authority is False
    assert consumed.grants_retry_or_replay is False
    assert consumed.permit_digest == permit.content_digest
    assert SOURCE_TASK not in repr(consumed)
    assert not hasattr(consumed, "source_task")
    assert not hasattr(consumed, "provider_id")
    assert not hasattr(consumed, "model_id")
    assert not hasattr(consumed, "endpoint")
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_GATE_TERMINAL$",
    ):
        gate.consume(permit, current_disclosure=disclosure)


def test_cancel_is_terminal_and_issues_nothing() -> None:
    gate = IntentCompileGate(_disclosure())
    gate.cancel()
    assert gate.state is IntentCompileGateState.CANCELLED
    with pytest.raises(FormalDemoIntentGateError):
        gate.acknowledge(INTENT_COMPILE_TOKEN)
    with pytest.raises(FormalDemoIntentGateError):
        gate.cancel()


def test_cross_gate_copy_pickle_forgery_and_tamper_fail_closed() -> None:
    disclosure = _disclosure()
    first = IntentCompileGate(disclosure)
    second = IntentCompileGate(disclosure)
    permit = first.acknowledge(INTENT_COMPILE_TOKEN)
    second_permit = second.acknowledge(INTENT_COMPILE_TOKEN)

    for gate_operation in (
        lambda: copy.copy(first),
        lambda: copy.deepcopy(first),
        lambda: pickle.dumps(first),
    ):
        with pytest.raises(
            FormalDemoIntentGateError,
            match="^FORMAL_DEMO_INTENT_GATE_OPAQUE$",
        ):
            gate_operation()

    with pytest.raises(FormalDemoIntentGateError):
        first.consume(second_permit, current_disclosure=disclosure)
    assert first.state is IntentCompileGateState.CANCELLED

    for permit_operation in (
        lambda: copy.copy(permit),
        lambda: copy.deepcopy(permit),
        lambda: pickle.dumps(permit),
    ):
        with pytest.raises(
            FormalDemoIntentGateError,
            match="^FORMAL_DEMO_INTENT_PERMIT_OPAQUE$",
        ):
            permit_operation()

    forged = object.__new__(IntentCompilePermit)
    with pytest.raises(FormalDemoIntentGateError):
        second.consume(forged, current_disclosure=disclosure)  # type: ignore[arg-type]
    assert second.state is IntentCompileGateState.CANCELLED

    third = IntentCompileGate(disclosure)
    changed = third.acknowledge(INTENT_COMPILE_TOKEN)
    object.__setattr__(changed, "route_digest", "0" * 64)
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ):
        third.consume(changed, current_disclosure=disclosure)
    assert third.state is IntentCompileGateState.CANCELLED


def test_arbitrary_structural_profile_and_notice_are_not_reviewed_authority() -> None:
    reviewed = _profile()
    attacker = replace(reviewed, data_use_notice="Attacker-selected data use.")
    with pytest.raises(FormalDemoIntentGateError):
        FormalDemoIntentDisclosure(
            disclosure_id=DISCLOSURE_ID,
            resume_identity=RESUME_IDENTITY,
            source_task=SOURCE_TASK,
            route=_openai_route(),
            profile_id=attacker.profile_id,
            profile_version=attacker.version,
            profile_digest=attacker.content_digest,
            data_use_notice=attacker.data_use_notice,
            retention_notice=attacker.retention_notice,
        )


def test_every_semantic_binding_change_requires_a_new_disclosure_digest() -> None:
    original = _disclosure()
    variants = (
        _disclosure(source_task=SOURCE_TASK + " More."),
        _disclosure(disclosure_id="formal-demo-draft-002"),
        _disclosure(resume_identity="formal-demo-review-002"),
        _disclosure(route=_openai_route(model_id="gpt-other")),
        _disclosure(
            route=ProviderIntentRoute(
                provider_id="qwen",
                region="ap-southeast-1",
                model_id="qwen-reviewed",
                protocol=ProviderProtocol.OPENAI_RESPONSES,
                endpoint=(
                    "https://workspace-demo.ap-southeast-1.maas.aliyuncs.com/"
                    "compatible-mode/v1"
                ),
                workspace_id="workspace-demo",
            ),
            profile=_profile("qwen"),
        ),
    )
    assert all(item.content_digest != original.content_digest for item in variants)


@pytest.mark.parametrize(
    "current_disclosure",
    (
        lambda: _disclosure(source_task=SOURCE_TASK + " changed"),
        lambda: _disclosure(resume_identity="formal-demo-review-002"),
        lambda: _disclosure(route=_openai_route(model_id="gpt-other")),
    ),
)
def test_consume_rejects_current_task_route_or_identity_drift(
    current_disclosure,
) -> None:
    gate = IntentCompileGate(_disclosure())
    permit = gate.acknowledge(INTENT_COMPILE_TOKEN)
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ):
        gate.consume(permit, current_disclosure=current_disclosure())
    assert gate.state is IntentCompileGateState.CANCELLED


def test_source_task_uses_exact_utf8_byte_bound_and_errors_are_content_free() -> None:
    exact = "界" * (MAX_SOURCE_TASK_BYTES // 3)
    assert len(exact.encode("utf-8")) <= MAX_SOURCE_TASK_BYTES
    assert _disclosure(source_task=exact).source_task_digest

    sentinel = "SECRET_SHOULD_NOT_LEAK"
    invalid = (
        "",
        " ",
        "bad\x00task",
        "界" * (MAX_SOURCE_TASK_BYTES // 3 + 1),
        "\ud800",
        True,
        1,
    )
    for value in invalid:
        try:
            _disclosure(source_task=value)  # type: ignore[arg-type]
        except FormalDemoIntentGateError as exc:
            rendered = "".join(traceback.format_exception(exc))
            assert sentinel not in rendered
            if isinstance(value, str) and value:
                assert value not in str(exc)
        else:
            raise AssertionError("invalid task was accepted")


def test_multiline_and_unicode_separators_are_exact_but_rendered_as_one_literal() -> None:
    source = "first line\nsecond\u0085line\u2028third\u2029fourth\U000e0001"
    disclosure = _disclosure(source_task=source)
    rendered = disclosure.render()

    assert source not in rendered
    assert (
        '"first line\\nsecond\\u0085line\\u2028third\\u2029fourth'
        '\\udb40\\udc01"'
    ) in rendered
    assert disclosure.source_task == source


def test_malicious_in_memory_tamper_is_content_free_and_terminal() -> None:
    disclosure = _disclosure()
    ready = IntentCompileGate(disclosure)
    object.__setattr__(disclosure, "route", object())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_DISCLOSURE_STALE$",
    ):
        ready.acknowledge(INTENT_COMPILE_TOKEN)
    assert ready.state is IntentCompileGateState.CANCELLED

    disclosure = _disclosure()
    permitted = IntentCompileGate(disclosure)
    permit = permitted.acknowledge(INTENT_COMPILE_TOKEN)
    object.__setattr__(disclosure, "profile_id", object())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ):
        permitted.consume(permit, current_disclosure=disclosure)
    assert permitted.state is IntentCompileGateState.CANCELLED


def test_concurrent_acknowledgement_and_consumption_have_one_winner() -> None:
    gate = IntentCompileGate(_disclosure())

    def acknowledge() -> object:
        try:
            return gate.acknowledge(INTENT_COMPILE_TOKEN)
        except FormalDemoIntentGateError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: acknowledge(), range(8)))
    permits = [item for item in results if isinstance(item, IntentCompilePermit)]
    assert len(permits) == 1
    assert results.count("FORMAL_DEMO_INTENT_GATE_TERMINAL") == 7

    permit = permits[0]

    def consume() -> object:
        try:
            return gate.consume(permit, current_disclosure=gate.disclosure)
        except FormalDemoIntentGateError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        consumed = list(pool.map(lambda _index: consume(), range(8)))
    assert sum(not isinstance(item, str) for item in consumed) == 1
    assert consumed.count("FORMAL_DEMO_INTENT_GATE_TERMINAL") == 7
    assert gate.state is IntentCompileGateState.CONSUMED


def test_module_has_no_execution_persistence_or_dynamic_import_port() -> None:
    source_path = Path(gate_module.__file__ or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    forbidden_import_fragments = {
        "asyncio",
        "cli",
        "config",
        "continuation",
        "desktop",
        "driver",
        "mcp",
        "pathlib",
        "provider_factory",
        "providers",
        "runner",
        "socket",
        "subprocess",
    }
    forbidden_calls = {
        "__import__",
        "connect",
        "dispatch",
        "exec",
        "invoke",
        "open",
        "request",
        "send",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {item.name.lower() for item in node.names}
            assert not any(
                fragment in name
                for name in names
                for fragment in forbidden_import_fragments
            )
        if isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert node.level in {0, 1}
            assert not any(fragment in module for fragment in forbidden_import_fragments)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_calls
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_calls

    source = source_path.read_text(encoding="utf-8")
    for value in (
        "create_planner",
        "create_final_response_adapter",
        "AgentRunner",
        "StdioDesktopMCP",
        "FastMCP",
        "WindowsDriver",
    ):
        assert value not in source
