"""Reliability benchmark harness: honesty rules and per-scenario semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.benchmark import (
    BENCHMARK_REPORT_VERSION,
    BenchmarkError,
    default_scenarios,
    render_markdown,
    resume_delay_for,
    run_benchmark,
)

# Small but real: every scenario runs the full crash-and-resume cycle.
ITEMS = 6
REPETITIONS = 2


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("benchmark")
    return run_benchmark(root, item_count=ITEMS, repetitions=REPETITIONS)


def test_every_scenario_runs_every_repetition(report) -> None:
    assert report.passed
    assert len(report.results) == len(default_scenarios()) * REPETITIONS
    for scenario in default_scenarios():
        assert len(report.for_scenario(scenario.name)) == REPETITIONS


def test_no_duplicate_side_effect_at_any_fault_point(report) -> None:
    """The claim the whole benchmark exists to support."""
    assert all(result.duplicates == 0 for result in report.results)
    assert report.as_json()["total_duplicate_side_effects"] == 0


def test_every_item_is_either_committed_or_parked(report) -> None:
    """An item may stop for a human; it may never vanish."""
    for result in report.results:
        accounted = result.report.committed_items + result.report.uncertain_items
        assert accounted == result.report.total_items == ITEMS


def test_uncertain_dispatch_parks_exactly_one_item_and_never_replays(report) -> None:
    runs = report.for_scenario("crash_after_dispatch_intent")
    for run in runs:
        assert run.report.uncertain_items == 1
        assert run.report.committed_items == ITEMS - 1
        assert run.report.duplicate_side_effects == 0


@pytest.mark.parametrize(
    "scenario",
    [
        "clean",
        "crash_after_claim",
        "crash_after_side_effect_completion",
        "crash_after_commit",
        "crash_before_projection",
    ],
)
def test_recoverable_scenarios_commit_every_item(report, scenario: str) -> None:
    for run in report.for_scenario(scenario):
        assert run.report.committed_items == ITEMS
        assert run.report.uncertain_items == 0


def test_repetitions_are_deterministic(report) -> None:
    """Same inputs, same durable outcome, across independent state directories."""
    for scenario in report.scenario_names():
        digests = {run.report.campaign_digest for run in report.for_scenario(scenario)}
        assert len(digests) == 1


def test_faulted_scenarios_actually_injected_and_resumed(report) -> None:
    for scenario in report.scenario_names():
        if scenario == "clean":
            for run in report.for_scenario(scenario):
                assert run.report.fault_points_exercised == ()
                assert run.report.resumed_runs == 0
            continue
        for run in report.for_scenario(scenario):
            assert len(run.report.fault_points_exercised) == 1
            assert run.report.resumed_runs == 1


def test_report_schema_is_stable_and_json_serializable(report) -> None:
    payload = report.as_json()
    assert payload["report_version"] == BENCHMARK_REPORT_VERSION
    assert payload["item_count"] == ITEMS
    assert payload["repetitions"] == REPETITIONS
    round_tripped = json.loads(json.dumps(payload, sort_keys=True))
    assert round_tripped == payload
    for entry in payload["scenarios"]:
        assert set(entry["wall_ms"]) == {"median", "p95", "max", "min"}


def test_markdown_reports_median_and_p95_not_a_best_run(report) -> None:
    rendered = render_markdown(report)
    assert "median" in rendered
    assert "p95" in rendered
    assert "No run is selected for being the best one" in rendered
    # Every scenario and its expectation are stated, so a reader cannot see a
    # number without seeing what it is supposed to prove.
    for scenario in default_scenarios():
        assert f"`{scenario.name}`" in rendered
        assert scenario.expectation in rendered
    # Honesty boundaries the handbook requires.
    assert "not application acceptance" in rendered
    assert "0 tokens means this path has no provider" in rendered


def test_resume_delay_outlasts_the_lease_as_the_item_count_grows() -> None:
    """A takeover is only legal once the previous owner provably expired."""
    small = resume_delay_for(10)
    large = resume_delay_for(1000)
    assert large > small
    # The wait must exceed the simulated work plus the full lease.
    assert large.total_seconds() > 1000 * 3 + 300


def test_invalid_parameters_fail_closed(tmp_path: Path) -> None:
    for kwargs in ({"item_count": 0}, {"repetitions": 0}, {"item_count": True}):
        with pytest.raises(BenchmarkError):
            run_benchmark(tmp_path / "invalid", **kwargs)  # type: ignore[arg-type]
    with pytest.raises(BenchmarkError):
        run_benchmark(tmp_path / "empty-scenarios", scenarios=())


def test_a_non_empty_state_directory_is_refused(tmp_path: Path) -> None:
    """A run must never inherit durable state from a previous one."""
    root = tmp_path / "root"
    (root / "clean" / "run-01").mkdir(parents=True)
    (root / "clean" / "run-01" / "stale.txt").write_text("x", encoding="utf-8")
    with pytest.raises(BenchmarkError, match="STATE_DIR_NOT_EMPTY"):
        run_benchmark(root, item_count=2, repetitions=1)
