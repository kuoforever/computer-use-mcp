from __future__ import annotations

import pytest

from computer_use_agent.application_worker_catalog import APPLICATION_WORKER_SPECS
from computer_use_agent.worker_capabilities import (
    SCENARIO_CAPABILITY_COMPOSITIONS,
    WORKER_CAPABILITIES,
    WORKER_CAPABILITIES_BY_NAME,
    WorkerCapability,
    capabilities_for_scenario,
    tools_for_scenario,
)


def test_capability_registry_is_unique_and_covers_every_scenario() -> None:
    assert len(WORKER_CAPABILITIES) == len(WORKER_CAPABILITIES_BY_NAME)
    assert len(SCENARIO_CAPABILITY_COMPOSITIONS) == 19
    assert set(SCENARIO_CAPABILITY_COMPOSITIONS) == {
        spec.scenario_id for spec in APPLICATION_WORKER_SPECS
    }
    for spec in APPLICATION_WORKER_SPECS:
        capabilities = capabilities_for_scenario(spec.scenario_id)
        assert capabilities
        assert {
            "stable_identity_revalidation",
            "challenge_detection",
            "post_action_verification",
        } <= {capability.name for capability in capabilities}
        assert set(spec.observation_ladder) <= tools_for_scenario(spec.scenario_id)


def test_critical_scenarios_compose_critical_commit_explicitly() -> None:
    for scenario_id in ("A13", "A16", "A19"):
        capabilities = capabilities_for_scenario(scenario_id)
        critical = [
            capability
            for capability in capabilities
            if capability.name == "critical_commit"
        ]
        assert len(critical) == 1
        assert critical[0].requires_approval
        assert "maker_checker_verified" in critical[0].preconditions


def test_capability_composition_derives_tools_without_new_dispatch_surface() -> None:
    assert tools_for_scenario("A1") == frozenset(
        {
            "list_windows",
            "ui_snapshot",
            "document_text",
            "ocr",
            "capture_region",
            "activate_window",
            "click",
            "key",
        }
    )
    assert "type" in tools_for_scenario("A3")
    assert "screenshot" in tools_for_scenario("A9")


def test_external_capability_without_approval_is_invalid() -> None:
    with pytest.raises(ValueError, match="require approval"):
        WorkerCapability(
            name="unsafe_send",
            effect="external",
            tools=("click",),
            preconditions=(),
            postconditions=(),
            stop_states=("UNKNOWN_OUTCOME",),
        )


def test_unknown_scenario_has_no_dynamic_composition() -> None:
    with pytest.raises(KeyError, match="WORKER_SCENARIO_UNSUPPORTED"):
        capabilities_for_scenario("A20")
