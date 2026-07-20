"""Repeated reliability benchmark over the deterministic demo campaign.

This is a *reliability* experiment, not a throughput contest. The business work
is fake on purpose; what is being measured is whether the durability semantics
hold at every fault point, repeatedly, with no cherry-picking:

* every scenario runs several times and the report states median and p95,
  never the best observed run;
* a duplicate side effect anywhere fails the whole benchmark;
* an item parked for human attention is a **correct** outcome and is counted as
  neither a success nor a failure.

It orchestrates :mod:`computer_use_agent.demo_campaign` and adds no execution
path of its own. No desktop, provider, credential, or network is involved.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Callable, Sequence

from .campaign import CampaignStore
from .demo_campaign import (
    DEMO_ITEM_LEASE_SECONDS,
    DemoFaultPoint,
    DemoReport,
    DurableFakeSideEffectSink,
    InjectedDemoFault,
    NoFaultInjector,
    ScriptedFaultInjector,
    prepare_demo_campaign,
    project_demo_report,
    run_demo_campaign,
    synthetic_demo_plan,
)
from .run_lock import RunLock

__all__ = [
    "BENCHMARK_REPORT_VERSION",
    "DEFAULT_ITEM_COUNT",
    "DEFAULT_REPETITIONS",
    "BenchmarkError",
    "BenchmarkReport",
    "ScenarioResult",
    "ScenarioSpec",
    "default_scenarios",
    "render_markdown",
    "resume_delay_for",
    "run_benchmark",
]

BENCHMARK_REPORT_VERSION = 1
DEFAULT_ITEM_COUNT = 100
DEFAULT_REPETITIONS = 5
POLICY_DIGEST = "0" * 64

# A fixed clock. Wall-clock time must not change what the benchmark asserts.
BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
#: Simulated seconds the campaign consumes per item, matching the demo's clock.
SIMULATED_SECONDS_PER_ITEM = 3
#: Margin past the last possible lease and heartbeat expiry.
TAKEOVER_MARGIN = timedelta(seconds=120)


def resume_delay_for(item_count: int) -> timedelta:
    """How long the recovering process waits before taking over.

    A takeover is only legal once the previous owner's lease and heartbeat are
    *provably* expired -- that rule is what stops two processes from working the
    same item. A fixed delay quietly stops satisfying it as the item count
    grows, so the wait scales with the work instead.
    """

    return timedelta(
        seconds=item_count * SIMULATED_SECONDS_PER_ITEM + DEMO_ITEM_LEASE_SECONDS
    ) + TAKEOVER_MARGIN


class BenchmarkError(RuntimeError):
    """A fixed benchmark failure that embeds no content."""


@dataclass(frozen=True)
class ScenarioSpec:
    """One fault to inject, and what recovery is expected to do about it."""

    name: str
    fault_point: DemoFaultPoint | None
    #: Fraction of the way through the run to inject, so the ordinal scales
    #: with the item count instead of being pinned to a small fixed number.
    position: float
    expectation: str

    def ordinal_for(self, item_count: int) -> int:
        if self.fault_point is None:
            return 0
        return max(1, min(item_count, round(item_count * self.position)))


def default_scenarios() -> tuple[ScenarioSpec, ...]:
    """The reviewed fault matrix.

    Each entry sits on one side of a specific durability boundary, so its
    expected outcome is a fixed claim rather than a lucky result.
    """

    return (
        ScenarioSpec(
            name="clean",
            fault_point=None,
            position=0.0,
            expectation="every item commits; no fault is injected",
        ),
        ScenarioSpec(
            name="crash_after_claim",
            fault_point=DemoFaultPoint.AFTER_ITEM_CLAIM,
            position=0.10,
            expectation="the lease exists but no work was done; the item is re-claimed",
        ),
        ScenarioSpec(
            name="crash_after_dispatch_intent",
            fault_point=DemoFaultPoint.AFTER_DISPATCH_INTENT,
            position=0.25,
            expectation="outcome unknown; the item is parked UNCERTAIN and never replayed",
        ),
        ScenarioSpec(
            name="crash_after_side_effect_completion",
            fault_point=DemoFaultPoint.AFTER_SIDE_EFFECT_COMPLETION,
            position=0.50,
            expectation="an exact receipt exists; reconcile bookkeeping without dispatching again",
        ),
        ScenarioSpec(
            name="crash_after_commit",
            fault_point=DemoFaultPoint.AFTER_ITEM_COMMIT,
            position=0.75,
            expectation="the item is already COMMITTED; recovery skips it entirely",
        ),
        ScenarioSpec(
            name="crash_before_projection",
            fault_point=DemoFaultPoint.BEFORE_FINAL_PROJECTION,
            position=1.0,
            expectation="every item is durable; the report is a projection and is rebuilt",
        ),
    )


@dataclass(frozen=True)
class ScenarioResult:
    """One repetition of one scenario."""

    scenario: str
    repetition: int
    report: DemoReport
    wall_ms: int
    recovery_ms: int

    @property
    def duplicates(self) -> int:
        return self.report.duplicate_side_effects


def _percentile(values: Sequence[int], fraction: float) -> int:
    """Nearest-rank percentile. Small samples make interpolation misleading."""

    if not values:
        return 0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), round(fraction * len(ordered) + 0.5)))
    return ordered[rank - 1]


def _summarize(values: Sequence[int]) -> dict[str, int]:
    if not values:
        return {"median": 0, "p95": 0, "max": 0, "min": 0}
    return {
        "median": int(statistics.median(values)),
        "p95": _percentile(values, 0.95),
        "max": max(values),
        "min": min(values),
    }


@dataclass(frozen=True)
class BenchmarkReport:
    """Aggregated results. Stable schema; safe to diff across commits."""

    item_count: int
    repetitions: int
    results: tuple[ScenarioResult, ...]

    @property
    def passed(self) -> bool:
        """Fail on any duplicate, or on an item neither committed nor parked.

        An UNCERTAIN item is a correct outcome, so it is not a failure. What is
        a failure is an item that simply vanished.
        """

        for result in self.results:
            if result.duplicates:
                return False
            accounted = result.report.committed_items + result.report.uncertain_items
            if accounted != result.report.total_items:
                return False
        return True

    def scenario_names(self) -> tuple[str, ...]:
        seen: list[str] = []
        for result in self.results:
            if result.scenario not in seen:
                seen.append(result.scenario)
        return tuple(seen)

    def for_scenario(self, name: str) -> tuple[ScenarioResult, ...]:
        return tuple(result for result in self.results if result.scenario == name)

    def as_json(self) -> dict[str, object]:
        scenarios: list[dict[str, object]] = []
        for name in self.scenario_names():
            runs = self.for_scenario(name)
            scenarios.append(
                {
                    "scenario": name,
                    "repetitions": len(runs),
                    "committed_items": sorted({run.report.committed_items for run in runs}),
                    "uncertain_items": sorted({run.report.uncertain_items for run in runs}),
                    "duplicate_side_effects": max(run.duplicates for run in runs),
                    "accepted_side_effects": sorted(
                        {run.report.accepted_side_effects for run in runs}
                    ),
                    "resumed_runs": sorted({run.report.resumed_runs for run in runs}),
                    "fault_points_exercised": sorted(
                        {point for run in runs for point in run.report.fault_points_exercised}
                    ),
                    "wall_ms": _summarize([run.wall_ms for run in runs]),
                    "recovery_ms": _summarize([run.recovery_ms for run in runs]),
                    "deterministic": len({run.report.campaign_digest for run in runs}) == 1,
                }
            )
        return {
            "report_version": BENCHMARK_REPORT_VERSION,
            "item_count": self.item_count,
            "repetitions": self.repetitions,
            "passed": self.passed,
            "total_runs": len(self.results),
            "total_duplicate_side_effects": sum(run.duplicates for run in self.results),
            "scenarios": scenarios,
        }


def _open(state_dir: Path) -> tuple[CampaignStore, DurableFakeSideEffectSink, RunLock]:
    """Open durable state exactly the way a fresh process would."""

    lock = RunLock(state_dir / "lock")
    lock.acquire()
    store = CampaignStore((state_dir / "campaign").resolve(), lock)
    sink = DurableFakeSideEffectSink((state_dir / "sink" / "side-effects.jsonl").resolve())
    return store, sink, lock


def _run_once(
    state_dir: Path,
    *,
    campaign_id: str,
    item_count: int,
    scenario: ScenarioSpec,
) -> tuple[DemoReport, int, int]:
    """Run one campaign, inject at most one fault, then resume in fresh state."""

    started_ns = perf_counter_ns()
    recovery_ns = 0
    fault_points: tuple[DemoFaultPoint, ...] = ()
    resumed_runs = 0

    store, sink, lock = _open(state_dir)
    try:
        prepare_demo_campaign(
            store,
            campaign_id=campaign_id,
            run_id="run-1",
            plan=synthetic_demo_plan(item_count),
            now=BASE_TIME,
            policy_digest=POLICY_DIGEST,
        )
        injector = (
            ScriptedFaultInjector(scenario.fault_point, scenario.ordinal_for(item_count))
            if scenario.fault_point is not None
            else NoFaultInjector()
        )
        try:
            run_demo_campaign(
                store,
                sink,
                campaign_id=campaign_id,
                run_id="run-1",
                now=BASE_TIME,
                injector=injector,
            )
        except InjectedDemoFault as injected:
            fault_points = (injected.point,)
    finally:
        lock.release()

    if fault_points:
        # A second process with nothing in memory from the first. Recovery time
        # is measured across this boundary only.
        recovery_started_ns = perf_counter_ns()
        store, sink, lock = _open(state_dir)
        try:
            run_demo_campaign(
                store,
                sink,
                campaign_id=campaign_id,
                run_id="run-2",
                now=BASE_TIME + resume_delay_for(item_count),
                resumed=True,
            )
            resumed_runs = 1
        finally:
            lock.release()
        recovery_ns = perf_counter_ns() - recovery_started_ns

    store, sink, lock = _open(state_dir)
    try:
        report = project_demo_report(
            store,
            sink,
            campaign_id=campaign_id,
            fault_points=fault_points,
            resumed_runs=resumed_runs,
        )
    finally:
        lock.release()

    wall_ns = perf_counter_ns() - started_ns
    return report, wall_ns // 1_000_000, recovery_ns // 1_000_000


def run_benchmark(
    root: Path,
    *,
    item_count: int = DEFAULT_ITEM_COUNT,
    repetitions: int = DEFAULT_REPETITIONS,
    scenarios: Sequence[ScenarioSpec] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> BenchmarkReport:
    """Run every scenario ``repetitions`` times under ``root``.

    Each repetition gets its own empty state directory, so a run can never
    inherit durable state from a previous one.
    """

    if isinstance(item_count, bool) or not isinstance(item_count, int) or item_count < 1:
        raise BenchmarkError("BENCHMARK_ITEM_COUNT_INVALID")
    if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
        raise BenchmarkError("BENCHMARK_REPETITIONS_INVALID")
    selected = tuple(scenarios) if scenarios is not None else default_scenarios()
    if not selected:
        raise BenchmarkError("BENCHMARK_SCENARIOS_EMPTY")

    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    results: list[ScenarioResult] = []
    for scenario in selected:
        for repetition in range(1, repetitions + 1):
            state_dir = root / scenario.name / f"run-{repetition:02d}"
            if state_dir.exists() and any(state_dir.iterdir()):
                raise BenchmarkError("BENCHMARK_STATE_DIR_NOT_EMPTY")
            state_dir.mkdir(parents=True, exist_ok=True)
            report, wall_ms, recovery_ms = _run_once(
                state_dir,
                # A fixed id per scenario: each repetition has its own empty
                # state directory, so reusing the id makes the campaign digest
                # a real determinism check across repetitions rather than a
                # value that differs by construction.
                campaign_id=f"bench-{scenario.name}",
                item_count=item_count,
                scenario=scenario,
            )
            results.append(
                ScenarioResult(
                    scenario=scenario.name,
                    repetition=repetition,
                    report=report,
                    wall_ms=wall_ms,
                    recovery_ms=recovery_ms,
                )
            )
            if progress is not None:
                progress(scenario.name, repetition)
    return BenchmarkReport(
        item_count=item_count, repetitions=repetitions, results=tuple(results)
    )


def render_markdown(
    report: BenchmarkReport, *, scenarios: Sequence[ScenarioSpec] | None = None
) -> str:
    """Render a summary that states median and p95, never a best run."""

    expectations = {
        scenario.name: scenario.expectation
        for scenario in (scenarios if scenarios is not None else default_scenarios())
    }
    payload = report.as_json()
    lines = [
        "# Reliability benchmark",
        "",
        f"{report.item_count} synthetic items per run, "
        f"{report.repetitions} repetitions per scenario, "
        f"{payload['total_runs']} runs total.",
        "",
        f"**Result: {'PASS' if report.passed else 'FAIL'}** — "
        f"{payload['total_duplicate_side_effects']} duplicate side effects across all runs.",
        "",
        "Every number below is a median with p95 in parentheses, computed across "
        "all repetitions. No run is selected for being the best one. An item "
        "parked for human attention is a correct outcome, not a failure.",
        "",
        "| Scenario | Committed | Uncertain | Duplicates | Wall ms | Recovery ms |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for entry in payload["scenarios"]:  # type: ignore[union-attr]
        wall = entry["wall_ms"]  # type: ignore[index]
        recovery = entry["recovery_ms"]  # type: ignore[index]
        committed = entry["committed_items"]  # type: ignore[index]
        uncertain = entry["uncertain_items"]  # type: ignore[index]
        lines.append(
            f"| `{entry['scenario']}` "  # type: ignore[index]
            f"| {', '.join(str(value) for value in committed)} "
            f"| {', '.join(str(value) for value in uncertain)} "
            f"| {entry['duplicate_side_effects']} "  # type: ignore[index]
            f"| {wall['median']} ({wall['p95']}) "
            f"| {recovery['median']} ({recovery['p95']}) |"
        )
    lines.extend(["", "## What each scenario asserts", ""])
    for entry in payload["scenarios"]:  # type: ignore[union-attr]
        name = entry["scenario"]  # type: ignore[index]
        lines.append(f"- **`{name}`** — {expectations.get(str(name), 'unknown')}")
    lines.extend(
        [
            "",
            "## Boundaries",
            "",
            "- Synthetic items and a fake durable side-effect sink. This is a "
            "reliability experiment, not application acceptance, and it says "
            "nothing about any real application.",
            "- 0 tokens means this path has no provider, not that an Agent run "
            "is free.",
            "- Timings come from one machine and one Python runtime. Treat them "
            "as a regression baseline, not a hardware claim.",
            "",
        ]
    )
    return "\n".join(lines)
