from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

import computer_use_agent.formal_demo_contract as contract_module
from computer_use_agent.formal_demo_contract import (
    APPLICATION_ROLE_PROFILE_VERSION,
    DEMO_SCENARIO_SPEC_VERSION,
    FORMAL_DEMO_V1_ROLE_PROFILES,
    FORMAL_DEMO_V1_ROLE_PROFILES_BY_ID,
    FORMAL_DEMO_V1_SCENARIO,
    GENERIC_SCOPE_SHEET_VERSION,
    MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES,
    MAX_SOURCE_TASK_BYTES,
    MAX_TASK_INTENT_JSON_BYTES,
    TASK_INTENT_VERSION,
    ApplicationRoleProfile,
    DemoRiskCeiling,
    FormalDemoContractError,
    ProfileBindingState,
    SemanticRole,
    compile_generic_scope_sheet as compile_reviewed_generic_scope_sheet,
    decode_application_role_profile,
    decode_demo_scenario_spec,
    decode_generic_scope_sheet as decode_reviewed_generic_scope_sheet,
    decode_task_intent,
    decode_task_intent_artifact,
    resolve_reviewed_formal_demo_profile,
)


SOURCE_TASK = "Build the fixture-grounded analysis, report, and unsent draft."
RESUME_IDENTITY = "formal-demo-review-001"
OUTCOME = "verified_analysis_report_and_draft"
OUTPUTS = ("excel_analysis", "word_report", "email_draft")
CONSTRAINTS = (
    "cleanup_required",
    "create_new_only",
    "email_draft_only",
    "fixture_only",
    "verify_reopen",
)


def _intent_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": TASK_INTENT_VERSION,
        "scenario_id": "formal_demo_v1",
        "outcome_id": OUTCOME,
        "requested_roles": [role.value for role in SemanticRole],
        "requested_outputs": list(OUTPUTS),
        "constraint_ids": list(CONSTRAINTS),
        "risk_ceiling": "draft",
        "budgets": {
            "provider_calls": 10,
            "tool_calls": 100,
            "side_effects": 20,
            "retries": 4,
            "artifacts": 3,
        },
    }
    payload.update(overrides)
    return payload


def _intent(
    *,
    source_task: str = SOURCE_TASK,
    **overrides: object,
):
    return decode_task_intent(
        json.dumps(_intent_payload(**overrides)),
        source_task=source_task,
    )


def _synthetic_profiles() -> tuple[ApplicationRoleProfile, ...]:
    return (
        ApplicationRoleProfile(
            profile_id="synthetic_source_v1",
            role=SemanticRole.SOURCE,
            application_label="Synthetic source fixture",
            adapter_id="synthetic_source",
            binding_state=ProfileBindingState.SELECTED,
            test_data_boundary="One synthetic source fixture.",
            reads=("Read synthetic source facts.",),
            changes=(),
            output_ids=(),
            fixture_ids=("github_issues_fixture_v1",),
            risk_ceiling=DemoRiskCeiling.READ_ONLY,
            forbidden_effects=("github_write",),
        ),
        ApplicationRoleProfile(
            profile_id="synthetic_evidence_v1",
            role=SemanticRole.EVIDENCE,
            application_label="Synthetic evidence fixture",
            adapter_id="synthetic_evidence",
            binding_state=ProfileBindingState.SELECTED,
            test_data_boundary="One synthetic evidence fixture.",
            reads=("Read synthetic evidence facts.",),
            changes=(),
            output_ids=(),
            fixture_ids=("pdf_evidence_fixture_v1",),
            risk_ceiling=DemoRiskCeiling.READ_ONLY,
            forbidden_effects=("arbitrary_file_access",),
        ),
        ApplicationRoleProfile(
            profile_id="synthetic_analysis_v1",
            role=SemanticRole.ANALYSIS,
            application_label="Synthetic analysis sink",
            adapter_id="synthetic_analysis",
            binding_state=ProfileBindingState.SELECTED,
            test_data_boundary="One synthetic analysis artifact.",
            reads=("Read admitted synthetic facts.",),
            changes=("Create and verify a synthetic analysis artifact.",),
            output_ids=("excel_analysis",),
            fixture_ids=("excel_disposable_v1",),
            risk_ceiling=DemoRiskCeiling.DRAFT,
            forbidden_effects=("overwrite_existing",),
        ),
        ApplicationRoleProfile(
            profile_id="synthetic_report_v1",
            role=SemanticRole.REPORT,
            application_label="Synthetic report sink",
            adapter_id="synthetic_report",
            binding_state=ProfileBindingState.SELECTED,
            test_data_boundary="One synthetic report artifact.",
            reads=("Read admitted synthetic analysis facts.",),
            changes=("Create and verify a synthetic report artifact.",),
            output_ids=("word_report",),
            fixture_ids=("word_disposable_v1",),
            risk_ceiling=DemoRiskCeiling.DRAFT,
            forbidden_effects=("overwrite_existing",),
        ),
        ApplicationRoleProfile(
            profile_id="synthetic_handoff_v1",
            role=SemanticRole.HANDOFF,
            application_label="Synthetic draft sink",
            adapter_id="synthetic_handoff",
            binding_state=ProfileBindingState.SELECTED,
            test_data_boundary="One synthetic unsent draft artifact.",
            reads=("Read the admitted synthetic report identity.",),
            changes=("Create, verify, and clean up a synthetic unsent draft.",),
            output_ids=("email_draft",),
            fixture_ids=("test_email_boundary_v1",),
            risk_ceiling=DemoRiskCeiling.DRAFT,
            forbidden_effects=(
                "email_forward",
                "email_schedule",
                "email_send",
                "external_delivery",
            ),
        ),
    )


def compile_generic_scope_sheet(
    intent,
    scenario,
    profiles,
    *,
    resume_identity: str,
    expected_binding_digest: str | None = None,
):
    """Exercise the private structural layer without claiming registry review."""

    return contract_module._compile_generic_scope_sheet(
        intent,
        scenario,
        profiles,
        resume_identity=resume_identity,
        expected_binding_digest=expected_binding_digest,
        reviewed_registry_pins_verified=False,
    )


def decode_generic_scope_sheet(
    text: str,
    *,
    intent,
    scenario,
    profiles,
    resume_identity: str,
    expected_binding_digest: str,
):
    """Exercise structural artifact verification with no reviewed-registry claim."""

    return contract_module._decode_generic_scope_sheet(
        text,
        intent=intent,
        scenario=scenario,
        profiles=profiles,
        resume_identity=resume_identity,
        expected_binding_digest=expected_binding_digest,
        reviewed_registry_pins_verified=False,
    )


def _compiled(*, profiles: tuple[ApplicationRoleProfile, ...] | None = None):
    return compile_generic_scope_sheet(
        _intent(),
        FORMAL_DEMO_V1_SCENARIO,
        _synthetic_profiles() if profiles is None else profiles,
        resume_identity=RESUME_IDENTITY,
    )


def test_four_versioned_contracts_round_trip_and_compile_without_raw_task() -> None:
    intent = _intent()
    reloaded_intent = decode_task_intent_artifact(
        intent.canonical_json(),
        source_task=SOURCE_TASK,
        expected_intent_digest=intent.content_digest,
    )
    scenario = decode_demo_scenario_spec(FORMAL_DEMO_V1_SCENARIO.canonical_json())
    profiles = tuple(
        decode_application_role_profile(profile.canonical_json())
        for profile in _synthetic_profiles()
    )
    sheet = compile_generic_scope_sheet(
        reloaded_intent,
        scenario,
        tuple(reversed(profiles)),
        resume_identity=RESUME_IDENTITY,
    )
    reloaded_sheet = decode_generic_scope_sheet(
        sheet.canonical_json(),
        intent=reloaded_intent,
        scenario=scenario,
        profiles=profiles,
        resume_identity=RESUME_IDENTITY,
        expected_binding_digest=sheet.binding_digest,
    )

    assert reloaded_intent == intent
    assert scenario == FORMAL_DEMO_V1_SCENARIO
    assert reloaded_sheet == sheet
    assert intent.version == TASK_INTENT_VERSION == 1
    assert scenario.version == DEMO_SCENARIO_SPEC_VERSION == 1
    assert all(profile.version == APPLICATION_ROLE_PROFILE_VERSION == 1 for profile in profiles)
    assert sheet.version == GENERIC_SCOPE_SHEET_VERSION == 1
    assert tuple(item.role for item in sheet.applications) == tuple(SemanticRole)
    assert SOURCE_TASK not in intent.canonical_json()
    assert SOURCE_TASK not in sheet.canonical_json()


def test_scope_sheet_is_complete_host_compiled_and_non_authoritative() -> None:
    sheet = _compiled()
    payload = sheet.canonical_payload()

    assert payload["source"] == "host_compiled_from_validated_task_intent"
    assert payload["contains_model_prose"] is False
    assert payload["compilation_starts_external_work"] is False
    assert payload["grants_execution_authority"] is False
    assert payload["reviewed_registry_pins_verified"] is False
    assert payload["goal"] == FORMAL_DEMO_V1_SCENARIO.outcomes[OUTCOME]
    assert len(payload["applications"]) == 5
    assert payload["reads"]
    assert payload["changes"]
    assert set(payload["outputs"]) == set(OUTPUTS)
    assert set(payload["constraints"]) == set(CONSTRAINTS)
    assert payload["risk_ceiling"] == "draft"
    assert payload["budgets"] == _intent().budgets.canonical_payload()
    assert payload["approvals"]
    assert payload["stop_conditions"]
    assert payload["possible_residue"]
    assert {
        "email_send",
        "email_schedule",
        "email_forward",
        "external_delivery",
        "overwrite_existing",
    } <= set(payload["forbidden_effects"])
    assert payload["acknowledgement"] == {
        "interactive_token": "START",
        "starts_bound_scope_only": True,
        "grants_action_approval": False,
        "grants_retry_or_replay": False,
    }
    assert payload["digests"] == {
        "task_intent": sheet.task_intent_digest,
        "scenario": sheet.scenario_digest,
        "profiles": dict(sheet.profile_digests),
        "binding": sheet.binding_digest,
    }
    assert not hasattr(sheet, "start")
    assert not hasattr(sheet, "authorize")
    assert not hasattr(sheet, "dispatch")


def test_reviewed_product_records_are_exact_inert_and_email_is_unselected() -> None:
    profiles = FORMAL_DEMO_V1_ROLE_PROFILES
    handoff = next(profile for profile in profiles if profile.role is SemanticRole.HANDOFF)

    assert tuple(profile.role for profile in profiles) == tuple(SemanticRole)
    assert len({profile.profile_id for profile in profiles}) == len(profiles) == 5
    assert set(FORMAL_DEMO_V1_ROLE_PROFILES_BY_ID) == {
        profile.profile_id for profile in profiles
    }
    assert handoff.binding_state is ProfileBindingState.UNSELECTED
    assert handoff.adapter_id is None
    assert {
        "email_send",
        "email_schedule",
        "email_forward",
        "external_delivery",
    } <= set(handoff.forbidden_effects)
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_PROFILE_UNAVAILABLE$",
    ):
        compile_reviewed_generic_scope_sheet(
            _intent(),
            FORMAL_DEMO_V1_SCENARIO,
            profiles,
            resume_identity=RESUME_IDENTITY,
        )


def test_reviewed_profile_resolution_requires_exact_id_version_and_digest() -> None:
    profile = FORMAL_DEMO_V1_ROLE_PROFILES[0]
    assert (
        resolve_reviewed_formal_demo_profile(
            profile.profile_id,
            version=profile.version,
            digest=profile.content_digest,
        )
        is profile
    )

    for profile_id, version, digest in (
        ("unknown_profile", 1, profile.content_digest),
        (profile.profile_id, 2, profile.content_digest),
        (profile.profile_id, 1, "0" * 64),
    ):
        with pytest.raises(FormalDemoContractError):
            resolve_reviewed_formal_demo_profile(
                profile_id,
                version=version,
                digest=digest,
            )


def test_public_compiler_requires_exact_reviewed_registry_pins() -> None:
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_PROFILE_PIN_MISMATCH$",
    ):
        compile_reviewed_generic_scope_sheet(
            _intent(),
            FORMAL_DEMO_V1_SCENARIO,
            _synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
        )

    changed_scenario = replace(
        FORMAL_DEMO_V1_SCENARIO,
        outcomes={OUTCOME: "Attacker-selected goal."},
    )
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_SCENARIO_PIN_MISMATCH$",
    ):
        compile_reviewed_generic_scope_sheet(
            _intent(),
            changed_scenario,
            FORMAL_DEMO_V1_ROLE_PROFILES,
            resume_identity=RESUME_IDENTITY,
        )

    for bad_scenario, bad_profiles in (
        (object(), FORMAL_DEMO_V1_ROLE_PROFILES),
        (FORMAL_DEMO_V1_SCENARIO, None),
        (FORMAL_DEMO_V1_SCENARIO, "profiles"),
        (FORMAL_DEMO_V1_SCENARIO, [object()]),
    ):
        with pytest.raises(FormalDemoContractError):
            compile_reviewed_generic_scope_sheet(
                _intent(),
                bad_scenario,  # type: ignore[arg-type]
                bad_profiles,  # type: ignore[arg-type]
                resume_identity=RESUME_IDENTITY,
            )

    structural_sheet = _compiled()
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_PROFILE_PIN_MISMATCH$",
    ):
        decode_reviewed_generic_scope_sheet(
            structural_sheet.canonical_json(),
            intent=_intent(),
            scenario=FORMAL_DEMO_V1_SCENARIO,
            profiles=_synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
            expected_binding_digest=structural_sheet.binding_digest,
        )


def test_canonical_digest_ignores_object_and_set_order_but_binds_semantics() -> None:
    payload = _intent_payload()
    reordered_payload = dict(reversed(tuple(payload.items())))
    reordered_payload["requested_roles"] = list(reversed(reordered_payload["requested_roles"]))
    reordered_payload["requested_outputs"] = list(
        reversed(reordered_payload["requested_outputs"])
    )
    reordered_payload["constraint_ids"] = list(reversed(reordered_payload["constraint_ids"]))
    first_intent = _intent()
    reordered_intent = decode_task_intent(
        json.dumps(reordered_payload),
        source_task=SOURCE_TASK,
    )
    first_sheet = compile_generic_scope_sheet(
        first_intent,
        FORMAL_DEMO_V1_SCENARIO,
        _synthetic_profiles(),
        resume_identity=RESUME_IDENTITY,
    )
    reordered_sheet = compile_generic_scope_sheet(
        reordered_intent,
        FORMAL_DEMO_V1_SCENARIO,
        tuple(reversed(_synthetic_profiles())),
        resume_identity=RESUME_IDENTITY,
    )

    assert reordered_intent.content_digest == first_intent.content_digest
    assert reordered_sheet.binding_digest == first_sheet.binding_digest

    changed_task = _intent(source_task=SOURCE_TASK + " Changed.")
    changed_budget = replace(
        first_intent,
        budgets=replace(first_intent.budgets, tool_calls=99),
    )
    changed_profile = replace(
        _synthetic_profiles()[0],
        application_label="Changed synthetic source fixture",
    )
    changed_profiles = (changed_profile, *_synthetic_profiles()[1:])
    changed_scenario = replace(
        FORMAL_DEMO_V1_SCENARIO,
        fixtures={
            **FORMAL_DEMO_V1_SCENARIO.fixtures,
            "github_issues_fixture_v1": "Changed fixture boundary.",
        },
    )

    variants = (
        compile_generic_scope_sheet(
            changed_task,
            FORMAL_DEMO_V1_SCENARIO,
            _synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
        ),
        compile_generic_scope_sheet(
            changed_budget,
            FORMAL_DEMO_V1_SCENARIO,
            _synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
        ),
        compile_generic_scope_sheet(
            first_intent,
            FORMAL_DEMO_V1_SCENARIO,
            changed_profiles,
            resume_identity=RESUME_IDENTITY,
        ),
        compile_generic_scope_sheet(
            first_intent,
            changed_scenario,
            _synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
        ),
        compile_generic_scope_sheet(
            first_intent,
            FORMAL_DEMO_V1_SCENARIO,
            _synthetic_profiles(),
            resume_identity="formal-demo-review-002",
        ),
    )
    assert all(item.binding_digest != first_sheet.binding_digest for item in variants)
    assert len(first_sheet.binding_digest) == 64

    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_BINDING_DIGEST_MISMATCH$",
    ):
        compile_generic_scope_sheet(
            changed_task,
            FORMAL_DEMO_V1_SCENARIO,
            _synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
            expected_binding_digest=first_sheet.binding_digest,
        )


@pytest.mark.parametrize(
    "extra_field",
    [
        "tools",
        "tool_calls",
        "arguments",
        "application",
        "adapter_id",
        "approval",
        "permission",
        "start",
        "retry",
        "replay",
        "coordinates",
        "ref",
        "executable",
        "recipient",
        "requested_effects",
    ],
)
def test_task_intent_rejects_authority_bearing_or_application_fields(
    extra_field: str,
) -> None:
    secret = "SECRET-CANDIDATE-CONTENT"
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_INTENT_SHAPE_INVALID$",
    ) as captured:
        _intent(**{extra_field: secret})
    assert secret not in str(captured.value)


def test_free_text_never_grants_email_send_authority() -> None:
    source_task = "Send the email now, although the typed contract still requests draft only."
    sheet = compile_generic_scope_sheet(
        _intent(source_task=source_task),
        FORMAL_DEMO_V1_SCENARIO,
        _synthetic_profiles(),
        resume_identity=RESUME_IDENTITY,
    )

    assert "email_send" in sheet.forbidden_effects
    assert source_task not in sheet.canonical_json()
    assert sheet.goal == FORMAL_DEMO_V1_SCENARIO.outcomes[OUTCOME]


@pytest.mark.parametrize(
    "candidate",
    [
        "",
        "not-json",
        "[]",
        json.dumps({**_intent_payload(), "unknown": True}),
        json.dumps({key: value for key, value in _intent_payload().items() if key != "budgets"}),
        json.dumps(_intent_payload(version=True)),
        json.dumps(_intent_payload(version=2)),
        json.dumps(_intent_payload(version=1.0)),
        json.dumps(_intent_payload(budgets={**_intent_payload()["budgets"], "extra": 1})),
        json.dumps(_intent_payload(budgets={**_intent_payload()["budgets"], "retries": True})),
        json.dumps(_intent_payload(budgets={**_intent_payload()["budgets"], "retries": 10_001})),
        json.dumps(_intent_payload()).replace('"retries": 4', '"retries": 9999999'),
        json.dumps(_intent_payload(requested_roles=["source", "source"])),
        json.dumps(_intent_payload(requested_outputs=["word_report", "word_report"])),
        json.dumps(_intent_payload(constraint_ids=["fixture_only", "fixture_only"])),
        json.dumps(_intent_payload(risk_ceiling="unknown")),
        json.dumps(_intent_payload(requested_outputs=[f"output_{index}" for index in range(17)])),
        json.dumps(_intent_payload(scenario_id="UPPERCASE_NOT_ALLOWED")),
        json.dumps(_intent_payload(budgets={**_intent_payload()["budgets"], "retries": float("nan")})),
    ],
)
def test_task_intent_malformed_shape_version_bounds_and_duplicates_fail_closed(
    candidate: str,
) -> None:
    with pytest.raises(FormalDemoContractError):
        decode_task_intent(candidate, source_task=SOURCE_TASK)


def test_duplicate_json_keys_non_utf8_and_byte_bounds_fail_closed() -> None:
    candidate = json.dumps(_intent_payload())
    duplicate = candidate.replace(
        '"version": 1,',
        '"version": 1, "version": 1,',
        1,
    )
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_JSON_DUPLICATE_KEY$",
    ):
        decode_task_intent(duplicate, source_task=SOURCE_TASK)
    with pytest.raises(FormalDemoContractError, match="^FORMAL_DEMO_JSON_INVALID$"):
        decode_task_intent("\ud800", source_task=SOURCE_TASK)
    with pytest.raises(FormalDemoContractError, match="^FORMAL_DEMO_JSON_TOO_LARGE$"):
        decode_task_intent(
            candidate + (" " * MAX_TASK_INTENT_JSON_BYTES),
            source_task=SOURCE_TASK,
        )
    with pytest.raises(FormalDemoContractError, match="^FORMAL_DEMO_SOURCE_TASK_TOO_LARGE$"):
        decode_task_intent(candidate, source_task="x" * (MAX_SOURCE_TASK_BYTES + 1))
    huge_integer = candidate.replace('"retries": 4', '"retries": ' + ("9" * 5000))
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_JSON_NUMBER_INVALID$",
    ):
        decode_task_intent(huge_integer, source_task=SOURCE_TASK)


def test_unicode_canonical_json_remains_bounded_and_round_trips() -> None:
    scenario = replace(
        FORMAL_DEMO_V1_SCENARIO,
        outcomes={
            f"outcome_{index}": "验" * 512
            for index in range(16)
        },
        outputs={
            **FORMAL_DEMO_V1_SCENARIO.outputs,
            **{f"output_{index}": "据" * 512 for index in range(8)},
        },
    )
    canonical = scenario.canonical_json()

    assert len(canonical.encode("utf-8")) <= MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES
    assert decode_demo_scenario_spec(canonical) == scenario

    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_CANONICAL_JSON_TOO_LARGE$",
    ):
        replace(
            FORMAL_DEMO_V1_SCENARIO,
            outcomes={
                f"outcome_{index}": "验" * 512
                for index in range(16)
            },
            outputs={
                f"output_{index}": "据" * 512
                for index in range(16)
            },
            required_outputs=("output_0",),
            constraints={
                f"constraint_{index}": "界" * 512
                for index in range(16)
            },
            required_constraints=("constraint_0",),
            fixtures={
                f"fixture_{index}": "限" * 512
                for index in range(16)
            },
        )


def test_scenario_profile_and_scope_loaders_reject_unknown_fields_and_versions() -> None:
    scenario_payload = FORMAL_DEMO_V1_SCENARIO.canonical_payload()
    for mutation in (
        {**scenario_payload, "unknown": True},
        {**scenario_payload, "version": 2},
        {key: value for key, value in scenario_payload.items() if key != "fixtures"},
    ):
        with pytest.raises(FormalDemoContractError):
            decode_demo_scenario_spec(json.dumps(mutation))

    profile_payload = _synthetic_profiles()[0].canonical_payload()
    for mutation in (
        {**profile_payload, "unknown": True},
        {**profile_payload, "version": 2},
        {key: value for key, value in profile_payload.items() if key != "reads"},
    ):
        with pytest.raises(FormalDemoContractError):
            decode_application_role_profile(json.dumps(mutation))

    sheet = _compiled()
    scope_payload = sheet.canonical_payload()
    for mutation in (
        {**scope_payload, "unknown": True},
        {**scope_payload, "version": 2},
        {key: value for key, value in scope_payload.items() if key != "digests"},
    ):
        with pytest.raises(FormalDemoContractError):
            decode_generic_scope_sheet(
                json.dumps(mutation),
                intent=_intent(),
                scenario=FORMAL_DEMO_V1_SCENARIO,
                profiles=_synthetic_profiles(),
                resume_identity=RESUME_IDENTITY,
                expected_binding_digest=_compiled().binding_digest,
            )


def test_scenario_and_profile_collection_bounds_and_duplicate_values_fail_closed() -> None:
    scenario_payload = FORMAL_DEMO_V1_SCENARIO.canonical_payload()
    invalid_scenarios = (
        {**scenario_payload, "required_roles": ["source", "source"]},
        {
            **scenario_payload,
            "fixtures": {f"fixture_{index}": "fixture" for index in range(17)},
        },
        {**scenario_payload, "required_outputs": ["word_report", "word_report"]},
    )
    for payload in invalid_scenarios:
        with pytest.raises(FormalDemoContractError):
            decode_demo_scenario_spec(json.dumps(payload))

    profile_payload = _synthetic_profiles()[2].canonical_payload()
    invalid_profiles = (
        {**profile_payload, "output_ids": ["excel_analysis", "excel_analysis"]},
        {**profile_payload, "reads": [f"Read {index}." for index in range(17)]},
        {**profile_payload, "binding_state": "unselected"},
    )
    for payload in invalid_profiles:
        with pytest.raises(FormalDemoContractError):
            decode_application_role_profile(json.dumps(payload))

    oversized_scope = json.dumps({**_compiled().canonical_payload(), "padding": "x"})
    oversized_scope += " " * MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES
    with pytest.raises(FormalDemoContractError, match="^FORMAL_DEMO_JSON_TOO_LARGE$"):
        decode_generic_scope_sheet(
            oversized_scope,
            intent=_intent(),
            scenario=FORMAL_DEMO_V1_SCENARIO,
            profiles=_synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
            expected_binding_digest=_compiled().binding_digest,
        )


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        (_intent(outcome_id="unknown_outcome"), "FORMAL_DEMO_SCOPE_EXPANSION"),
        (_intent(requested_roles=["source", "evidence"]), "FORMAL_DEMO_SCOPE_EXPANSION"),
        (_intent(requested_outputs=[*OUTPUTS, "unknown_output"]), "FORMAL_DEMO_SCOPE_EXPANSION"),
        (_intent(constraint_ids=[*CONSTRAINTS, "unknown_constraint"]), "FORMAL_DEMO_SCOPE_EXPANSION"),
        (_intent(risk_ceiling="critical"), "FORMAL_DEMO_SCOPE_EXPANSION"),
        (
            _intent(
                budgets={
                    **_intent_payload()["budgets"],
                    "tool_calls": 129,
                }
            ),
            "FORMAL_DEMO_BUDGET_EXCEEDED",
        ),
        (
            _intent(
                budgets={
                    **_intent_payload()["budgets"],
                    "artifacts": 2,
                }
            ),
            "FORMAL_DEMO_BUDGET_EXCEEDED",
        ),
    ],
)
def test_outcome_role_output_constraint_risk_and_budget_expansion_fail_closed(
    intent: object,
    expected: str,
) -> None:
    with pytest.raises(FormalDemoContractError, match=f"^{expected}$"):
        compile_generic_scope_sheet(
            intent,  # type: ignore[arg-type]
            FORMAL_DEMO_V1_SCENARIO,
            _synthetic_profiles(),
            resume_identity=RESUME_IDENTITY,
        )


def test_profile_set_must_be_exact_available_and_unambiguous() -> None:
    profiles = _synthetic_profiles()
    invalid_sets = (
        profiles[:-1],
        (profiles[0], profiles[0], *profiles[2:]),
        (*profiles, profiles[0]),
        (*profiles[:-1], replace(profiles[-1], binding_state=ProfileBindingState.UNSELECTED, adapter_id=None)),
        (*profiles[:-1], replace(profiles[-1], fixture_ids=("unknown_fixture",))),
        (*profiles[:-1], replace(profiles[-1], risk_ceiling=DemoRiskCeiling.CRITICAL)),
        (
            profiles[0],
            profiles[1],
            replace(profiles[2], output_ids=("word_report",)),
            profiles[3],
            profiles[4],
        ),
    )
    for invalid in invalid_sets:
        with pytest.raises(FormalDemoContractError):
            compile_generic_scope_sheet(
                _intent(),
                FORMAL_DEMO_V1_SCENARIO,
                invalid,
                resume_identity=RESUME_IDENTITY,
            )


def test_scope_artifact_rejects_tamper_authority_flip_and_stale_binding() -> None:
    intent = _intent()
    profiles = _synthetic_profiles()
    sheet = compile_generic_scope_sheet(
        intent,
        FORMAL_DEMO_V1_SCENARIO,
        profiles,
        resume_identity=RESUME_IDENTITY,
    )
    payload = sheet.canonical_payload()

    tampered = {**payload, "goal": "Attacker-replaced goal."}
    with pytest.raises(FormalDemoContractError, match="^FORMAL_DEMO_SCOPE_TAMPERED$"):
        decode_generic_scope_sheet(
            json.dumps(tampered),
            intent=intent,
            scenario=FORMAL_DEMO_V1_SCENARIO,
            profiles=profiles,
            resume_identity=RESUME_IDENTITY,
            expected_binding_digest=sheet.binding_digest,
        )

    authority_flip = {
        **payload,
        "acknowledgement": {
            **payload["acknowledgement"],
            "grants_action_approval": True,
        },
    }
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_SCOPE_AUTHORITY_INVALID$",
    ):
        decode_generic_scope_sheet(
            json.dumps(authority_flip),
            intent=intent,
            scenario=FORMAL_DEMO_V1_SCENARIO,
            profiles=profiles,
            resume_identity=RESUME_IDENTITY,
            expected_binding_digest=sheet.binding_digest,
        )

    for field, value in (
        ("starts_bound_scope_only", 1),
        ("grants_action_approval", 0),
        ("grants_retry_or_replay", 0),
    ):
        numeric_authority = {
            **payload,
            "acknowledgement": {
                **payload["acknowledgement"],
                field: value,
            },
        }
        with pytest.raises(
            FormalDemoContractError,
            match="^FORMAL_DEMO_SCOPE_AUTHORITY_INVALID$",
        ):
            decode_generic_scope_sheet(
                json.dumps(numeric_authority),
                intent=intent,
                scenario=FORMAL_DEMO_V1_SCENARIO,
                profiles=profiles,
                resume_identity=RESUME_IDENTITY,
                expected_binding_digest=sheet.binding_digest,
            )

    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_BINDING_DIGEST_MISMATCH$",
    ):
        decode_generic_scope_sheet(
            sheet.canonical_json(),
            intent=replace(intent, budgets=replace(intent.budgets, tool_calls=99)),
            scenario=FORMAL_DEMO_V1_SCENARIO,
            profiles=profiles,
            resume_identity=RESUME_IDENTITY,
            expected_binding_digest=sheet.binding_digest,
        )

    with pytest.raises(TypeError):
        contract_module._decode_generic_scope_sheet(
            sheet.canonical_json(),
            intent=intent,
            scenario=FORMAL_DEMO_V1_SCENARIO,
            profiles=profiles,
            resume_identity=RESUME_IDENTITY,
            reviewed_registry_pins_verified=False,
        )

    for invalid_pin in (None, True, 1, "short", "0" * 64):
        with pytest.raises(
            FormalDemoContractError,
            match="^FORMAL_DEMO_BINDING_DIGEST_MISMATCH$",
        ):
            contract_module._decode_generic_scope_sheet(
                sheet.canonical_json(),
                intent=intent,
                scenario=FORMAL_DEMO_V1_SCENARIO,
                profiles=profiles,
                resume_identity=RESUME_IDENTITY,
                expected_binding_digest=invalid_pin,  # type: ignore[arg-type]
                reviewed_registry_pins_verified=False,
            )


def test_host_normalized_intent_artifact_rejects_source_task_tamper() -> None:
    intent = _intent()
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_SOURCE_TASK_DIGEST_MISMATCH$",
    ):
        decode_task_intent_artifact(
            intent.canonical_json(),
            source_task=SOURCE_TASK + " changed",
            expected_intent_digest=intent.content_digest,
        )

    payload = intent.canonical_payload()
    payload["budgets"] = {**payload["budgets"], "tool_calls": 99}
    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_INTENT_DIGEST_MISMATCH$",
    ):
        decode_task_intent_artifact(
            json.dumps(payload),
            source_task=SOURCE_TASK,
            expected_intent_digest=intent.content_digest,
        )


def test_contract_values_are_immutable_and_defensively_copied() -> None:
    outcomes = {"fixture_outcome": "Fixture outcome."}
    scenario = replace(FORMAL_DEMO_V1_SCENARIO, outcomes=outcomes)
    digest = scenario.content_digest
    outcomes["fixture_outcome"] = "Mutated outside value."

    assert scenario.outcomes["fixture_outcome"] == "Fixture outcome."
    assert scenario.content_digest == digest
    with pytest.raises(TypeError):
        scenario.outcomes["new"] = "value"  # type: ignore[index]
    sheet = _compiled()
    with pytest.raises(TypeError):
        sheet.outputs["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        sheet.constraints["new"] = "value"  # type: ignore[index]
    with pytest.raises(TypeError):
        sheet.profile_digests["source"] = "0" * 64  # type: ignore[index]


def test_contract_module_is_stdlib_only_and_has_no_execution_port_import() -> None:
    source_path = Path(contract_module.__file__ or "")
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots <= {
        "__future__",
        "dataclasses",
        "enum",
        "hashlib",
        "json",
        "re",
        "types",
        "typing",
    }
    assert not {
        "computer_use_mcp",
        "subprocess",
        "socket",
        "threading",
        "pathlib",
        "openai",
        "anthropic",
    } & imported_roots
