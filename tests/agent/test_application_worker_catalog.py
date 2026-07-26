from __future__ import annotations

import pytest

from computer_use_agent.application_worker_catalog import (
    APPLICATION_WORKERS_BY_KIND,
    APPLICATION_WORKERS_BY_SCENARIO,
    APPLICATION_WORKER_SPECS,
    ApplicationWorkerSpec,
    get_application_worker,
)


def test_catalog_covers_every_application_matrix_scenario_once() -> None:
    assert tuple(spec.scenario_id for spec in APPLICATION_WORKER_SPECS) == tuple(
        f"A{index}" for index in range(1, 20)
    )
    assert len(APPLICATION_WORKERS_BY_KIND) == 19
    assert len(APPLICATION_WORKERS_BY_SCENARIO) == 19
    assert len({spec.kind for spec in APPLICATION_WORKER_SPECS}) == 19
    assert all(spec.identity_dimensions for spec in APPLICATION_WORKER_SPECS)
    assert all(spec.result_fields for spec in APPLICATION_WORKER_SPECS)
    assert all(spec.observation_ladder for spec in APPLICATION_WORKER_SPECS)


@pytest.mark.parametrize("spec", APPLICATION_WORKER_SPECS)
def test_every_worker_has_fail_closed_recovery_states(
    spec: ApplicationWorkerSpec,
) -> None:
    assert {
        "IDENTITY_DRIFT",
        "OWNERSHIP_STALE",
        "POLICY_DENIED",
        "UNKNOWN_OUTCOME",
        "HUMAN_HANDOFF_REQUIRED",
    } <= set(spec.stop_states)
    assert get_application_worker(spec.kind) is spec


def test_catalog_keeps_high_risk_boundaries_explicit() -> None:
    assert APPLICATION_WORKERS_BY_SCENARIO["A13"].maximum_risk == "critical"
    assert APPLICATION_WORKERS_BY_SCENARIO["A16"].maximum_risk == "critical"
    assert APPLICATION_WORKERS_BY_SCENARIO["A19"].maximum_risk == "critical"
    assert "MAKER_CHECKER_REQUIRED" in APPLICATION_WORKERS_BY_SCENARIO["A16"].stop_states
    assert "SECURE_DESKTOP" in APPLICATION_WORKERS_BY_SCENARIO["A13"].stop_states
    assert "TENANT_MISMATCH" in APPLICATION_WORKERS_BY_SCENARIO["A19"].stop_states


def test_unknown_worker_kind_is_not_dynamically_resolved() -> None:
    with pytest.raises(KeyError, match="APPLICATION_WORKER_UNSUPPORTED"):
        get_application_worker("caller_supplied.module:worker")


def test_invalid_or_unreviewed_tool_is_rejected() -> None:
    with pytest.raises(ValueError, match="tool boundary"):
        ApplicationWorkerSpec(
            scenario_id="A20",
            kind="invalid_worker",
            name="Invalid worker",
            identity_dimensions=("item_id",),
            result_fields=("value",),
            observation_ladder=("browser_eval",),
            navigation_tools=(),
            optional_effects=(),
            maximum_risk="read_only",
        )
