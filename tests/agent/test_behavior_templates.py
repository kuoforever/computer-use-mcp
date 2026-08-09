from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

import computer_use_agent.behavior_templates as template_module
import computer_use_agent.boss_semantic_item_runtime as boss_runtime_module
from computer_use_agent.behavior_templates import (
    BOSS_PER_ITEM_OBSERVATION_TEMPLATE,
    BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID,
    BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN,
    BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION,
    REVIEWED_BEHAVIOR_TEMPLATES,
    REVIEWED_BEHAVIOR_TEMPLATES_BY_KEY,
    BehaviorArgumentBinding,
    BehaviorTemplateError,
    BehaviorTemplatePin,
    BehaviorTemplateRung,
    ReviewedBehaviorTemplate,
    bind_boss_observation_request,
    boss_per_item_observation_sources,
    decide_pinned_boss_observation,
    resolve_reviewed_behavior_template,
    reviewed_behavior_registry_digest,
    reviewed_subtree_node,
)
from computer_use_agent.boss_semantic_extraction import (
    BOSS_OBSERVATION_LADDER,
    BossIncompleteReason,
    BossObservationAttempt,
    BossObservationDecisionState,
    BossObservationSource,
    BossObservationStatus,
    BossSemanticContractError,
    decide_next_boss_observation,
)
from computer_use_agent.hierarchical_control import TreeBudget, TreeNodeKind
from computer_use_agent.tool_registry import get_tool_spec
from computer_use_agent.types import ToolEffect


CONTENT_DIGEST = "a" * 64
TEMPLATE_DIGEST = "59f728c4232f2e1570f49247ff62303f05244c124a61aeaad6d0dc76372d33e1"
REGISTRY_DIGEST = "18a88741aed37f35f7105c10c9aa7e9db19d4b0c3144a6b240cc8f6470d0ea78"
REGION = {"x": 10, "y": 20, "w": 300, "h": 400}


def _incomplete(source: BossObservationSource) -> BossObservationAttempt:
    return BossObservationAttempt(
        source=source,
        status=BossObservationStatus.INCOMPLETE,
        content_digest=CONTENT_DIGEST,
        incomplete_reason=BossIncompleteReason.REQUIRED_FIELDS_MISSING,
    )


def _terminal(
    source: BossObservationSource,
    status: BossObservationStatus,
) -> BossObservationAttempt:
    return BossObservationAttempt(
        source=source,
        status=status,
        content_digest=CONTENT_DIGEST,
    )


def test_registry_contains_one_exact_immutable_template_version() -> None:
    assert REVIEWED_BEHAVIOR_TEMPLATES == (BOSS_PER_ITEM_OBSERVATION_TEMPLATE,)
    assert REVIEWED_BEHAVIOR_TEMPLATES_BY_KEY == {
        (
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID,
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION,
        ): BOSS_PER_ITEM_OBSERVATION_TEMPLATE
    }
    assert (
        resolve_reviewed_behavior_template(BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN)
        is BOSS_PER_ITEM_OBSERVATION_TEMPLATE
    )
    with pytest.raises(TypeError):
        REVIEWED_BEHAVIOR_TEMPLATES_BY_KEY[("another", 1)] = (  # type: ignore[index]
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE
        )


def test_template_and_registry_digests_are_frozen() -> None:
    assert BOSS_PER_ITEM_OBSERVATION_TEMPLATE.digest == TEMPLATE_DIGEST
    assert BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN.digest == TEMPLATE_DIGEST
    assert reviewed_behavior_registry_digest() == REGISTRY_DIGEST
    assert BOSS_PER_ITEM_OBSERVATION_TEMPLATE.to_payload() == {
        "budget": {
            "tool_calls": 5,
            "tokens": 0,
            "side_effects": 0,
            "retries": 0,
        },
        "contract_version": 1,
        "control": "selector",
        "exhaustion_stop_code": "BOSS_OBSERVATION_LADDER_EXHAUSTED",
        "requires_explicit_incomplete": True,
        "rungs": [
            {
                "argument_binding": "foreground_scope",
                "required_safety_baselines": [],
                "source": "uia",
                "tool_name": "ui_snapshot",
            },
            {
                "argument_binding": "foreground_scope",
                "required_safety_baselines": [],
                "source": "document_text",
                "tool_name": "document_text",
            },
            {
                "argument_binding": "claimed_region",
                "required_safety_baselines": ["title_matched_image_redaction"],
                "source": "ocr",
                "tool_name": "ocr",
            },
            {
                "argument_binding": "claimed_region",
                "required_safety_baselines": [],
                "source": "cropped_image",
                "tool_name": "capture_region",
            },
            {
                "argument_binding": "empty",
                "required_safety_baselines": [],
                "source": "screenshot",
                "tool_name": "screenshot",
            },
        ],
        "template_id": BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID,
        "terminal_statuses": [
            "AUTH_REQUIRED",
            "CHALLENGE_REQUIRED",
            "RATE_LIMITED",
            "SITE_BLOCKED",
            "CONTENT_UNAVAILABLE",
        ],
        "version": BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION,
    }


def test_rungs_reproduce_the_existing_ladder_without_effect_authority() -> None:
    template = BOSS_PER_ITEM_OBSERVATION_TEMPLATE
    assert boss_per_item_observation_sources(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN
    ) == BOSS_OBSERVATION_LADDER
    assert template.budget == TreeBudget(tool_calls=5)
    for rung in template.rungs:
        spec = get_tool_spec(rung.tool_name)
        assert spec.effect is ToolEffect.OBSERVATION
        assert spec.required_safety_baselines == rung.required_safety_baselines
        assert not spec.requires_host_approval
        assert not spec.invalidates_observation


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (BossObservationSource.UIA, ("ui_snapshot", {"scope": "foreground"})),
        (
            BossObservationSource.DOCUMENT_TEXT,
            ("document_text", {"scope": "foreground"}),
        ),
        (BossObservationSource.OCR, ("ocr", REGION)),
        (BossObservationSource.CROPPED_IMAGE, ("capture_region", REGION)),
        (BossObservationSource.SCREENSHOT, ("screenshot", {})),
    ],
)
def test_request_binding_is_the_existing_fixed_tool_and_arguments(
    source: BossObservationSource,
    expected: tuple[str, dict[str, object]],
) -> None:
    assert bind_boss_observation_request(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN,
        source,
        region=REGION,
    ) == expected


@pytest.mark.parametrize(
    "region",
    [
        {},
        {"x": 0, "y": 0, "w": 0, "h": 1},
        {"x": -1, "y": 0, "w": 1, "h": 1},
        {"x": 0, "y": 0, "w": 2_001, "h": 2_000},
        {"x": True, "y": 0, "w": 1, "h": 1},
    ],
)
def test_region_boundaries_fail_closed(region: dict[str, int]) -> None:
    with pytest.raises(BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_REGION_INVALID$"):
        bind_boss_observation_request(
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN,
            BossObservationSource.OCR,
            region=region,
        )


@pytest.mark.parametrize(
    "pin",
    [
        BehaviorTemplatePin("unknown.template", 1, TEMPLATE_DIGEST),
        BehaviorTemplatePin(BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID, 2, TEMPLATE_DIGEST),
        BehaviorTemplatePin(
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID,
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION,
            "b" * 64,
        ),
    ],
)
def test_lookup_has_no_unknown_version_digest_or_latest_fallback(
    pin: BehaviorTemplatePin,
) -> None:
    with pytest.raises(BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_PIN_MISMATCH$"):
        resolve_reviewed_behavior_template(pin)


def test_pinned_reducer_is_identical_for_every_ladder_progression() -> None:
    attempts: tuple[BossObservationAttempt, ...] = ()
    assert decide_pinned_boss_observation(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN, attempts
    ) == decide_next_boss_observation(attempts)
    for source in BOSS_OBSERVATION_LADDER:
        attempts += (_incomplete(source),)
        assert decide_pinned_boss_observation(
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN, attempts
        ) == decide_next_boss_observation(attempts)
    decision = decide_pinned_boss_observation(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN, attempts
    )
    assert decision.state is BossObservationDecisionState.HANDOFF
    assert decision.stop_code == "BOSS_OBSERVATION_LADDER_EXHAUSTED"


@pytest.mark.parametrize("source", BOSS_OBSERVATION_LADDER)
def test_sufficient_result_extracts_at_every_reviewed_rung(
    source: BossObservationSource,
) -> None:
    index = BOSS_OBSERVATION_LADDER.index(source)
    attempts = tuple(_incomplete(item) for item in BOSS_OBSERVATION_LADDER[:index])
    attempts += (
        BossObservationAttempt(
            source=source,
            status=BossObservationStatus.SUFFICIENT,
            content_digest=CONTENT_DIGEST,
        ),
    )
    assert decide_pinned_boss_observation(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN, attempts
    ) == decide_next_boss_observation(attempts)


@pytest.mark.parametrize(
    "status",
    [
        BossObservationStatus.AUTH_REQUIRED,
        BossObservationStatus.CHALLENGE_REQUIRED,
        BossObservationStatus.RATE_LIMITED,
        BossObservationStatus.SITE_BLOCKED,
        BossObservationStatus.CONTENT_UNAVAILABLE,
    ],
)
def test_existing_terminal_states_handoff_without_escalation(
    status: BossObservationStatus,
) -> None:
    attempts = (_terminal(BossObservationSource.UIA, status),)
    assert decide_pinned_boss_observation(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN, attempts
    ) == decide_next_boss_observation(attempts)


def test_existing_invalid_sequence_still_fails_closed() -> None:
    attempts = (_incomplete(BossObservationSource.OCR),)
    with pytest.raises(BossSemanticContractError, match="BOSS_OBSERVATION_SEQUENCE_INVALID"):
        decide_pinned_boss_observation(
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN, attempts
        )


def test_reviewed_rung_rejects_side_effects_and_baseline_drift() -> None:
    with pytest.raises(
        BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_AUTHORITY_INVALID$"
    ):
        BehaviorTemplateRung(
            BossObservationSource.UIA,
            "click",
            BehaviorArgumentBinding.FOREGROUND_SCOPE,
        )
    with pytest.raises(
        BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_AUTHORITY_INVALID$"
    ):
        BehaviorTemplateRung(
            BossObservationSource.OCR,
            "ocr",
            BehaviorArgumentBinding.CLAIMED_REGION,
        )
    with pytest.raises(
        BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_BINDING_INVALID$"
    ):
        BehaviorTemplateRung(
            BossObservationSource.UIA,
            "screenshot",
            BehaviorArgumentBinding.EMPTY,
        )


def test_template_rejects_duplicate_rungs_and_budget_widening() -> None:
    rung = BOSS_PER_ITEM_OBSERVATION_TEMPLATE.rungs[0]
    with pytest.raises(BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_INVALID$"):
        replace(
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE,
            rungs=(rung, rung),
            budget=TreeBudget(tool_calls=2),
        )
    with pytest.raises(BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_INVALID$"):
        replace(
            BOSS_PER_ITEM_OBSERVATION_TEMPLATE,
            budget=TreeBudget(tool_calls=5, side_effects=1),
        )


def test_exact_pin_can_bind_only_an_inert_h1_subtree_leaf() -> None:
    node = reviewed_subtree_node(
        BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN,
        node_id="boss_observation",
        parent_id="root",
    )
    assert node.kind is TreeNodeKind.SUBTREE
    assert node.template_id == BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID
    assert node.template_version == BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION
    assert node.template_digest == TEMPLATE_DIGEST
    assert node.budget == TreeBudget(tool_calls=5)
    assert not hasattr(node, "tool_name")
    assert not hasattr(node, "arguments")
    assert not hasattr(node, "dispatch")


def test_registry_and_runtime_add_no_execution_port_or_second_ladder() -> None:
    assert not hasattr(template_module, "AgentRunner")
    assert not hasattr(template_module, "ToolCall")
    assert not hasattr(template_module, "MCPClient")
    runtime_source = inspect.getsource(boss_runtime_module)
    assert "decide_next_boss_observation" not in runtime_source
    assert "BOSS_OBSERVATION_LADDER" not in runtime_source
    assert "BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN" in runtime_source


def test_invalid_template_object_cannot_enter_the_registry_contract() -> None:
    with pytest.raises(BehaviorTemplateError, match="^BEHAVIOR_TEMPLATE_INVALID$"):
        ReviewedBehaviorTemplate(
            template_id="boss.invalid",
            version=1,
            control=BOSS_PER_ITEM_OBSERVATION_TEMPLATE.control,
            rungs=BOSS_PER_ITEM_OBSERVATION_TEMPLATE.rungs,
            terminal_statuses=BOSS_PER_ITEM_OBSERVATION_TEMPLATE.terminal_statuses,
            exhaustion_stop_code="BOSS_INVALID",
            budget=TreeBudget(tool_calls=4),
        )
