"""Run the deterministic demo campaign: crash at a named fault point, then resume.

This orchestrates the library in :mod:`computer_use_agent.demo_campaign`. It adds
no execution path of its own and touches no desktop: the side effect is a fake
durable sink, so the whole run is offline and repeatable.

Usage::

    python scripts/demo_reliability_campaign.py --state-dir out/demo --items 5 \\
        --fault-point after_item_commit --fault-ordinal 2

It prints one sanitized JSON report on stdout. Identities are hashes; no page
text, URL, or account content is ever recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from computer_use_agent.campaign import CampaignStore  # noqa: E402
from computer_use_agent.demo_campaign import (  # noqa: E402
    DemoFaultPoint,
    DurableFakeSideEffectSink,
    InjectedDemoFault,
    NoFaultInjector,
    ScriptedFaultInjector,
    prepare_demo_campaign,
    project_demo_report,
    run_demo_campaign,
    synthetic_demo_plan,
)
from computer_use_agent.run_lock import RunLock  # noqa: E402

POLICY_DIGEST = "0" * 64


def _open(state_dir: Path) -> tuple[CampaignStore, DurableFakeSideEffectSink, RunLock]:
    """Open durable state exactly the way a fresh process would."""

    lock = RunLock(state_dir / "lock")
    lock.acquire()
    store = CampaignStore((state_dir / "campaign").resolve(), lock)
    sink = DurableFakeSideEffectSink((state_dir / "sink" / "side-effects.jsonl").resolve())
    return store, sink, lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--campaign-id", default="demo-campaign")
    parser.add_argument("--items", type=int, default=5)
    parser.add_argument(
        "--fault-point",
        choices=[point.value for point in DemoFaultPoint],
        help="Where to kill the first process. Omit for a clean run.",
    )
    parser.add_argument("--fault-ordinal", type=int, default=1)
    arguments = parser.parse_args()

    state_dir = arguments.state_dir.resolve()
    if state_dir.exists() and any(state_dir.iterdir()):
        parser.error(f"{state_dir} is not empty; use a fresh directory for a clean run")
    state_dir.mkdir(parents=True, exist_ok=True)

    start = datetime.now(timezone.utc).replace(microsecond=0)
    fault_points: tuple[DemoFaultPoint, ...] = ()
    resumed_runs = 0

    store, sink, lock = _open(state_dir)
    try:
        prepare_demo_campaign(
            store,
            campaign_id=arguments.campaign_id,
            run_id="run-1",
            plan=synthetic_demo_plan(arguments.items),
            now=start,
            policy_digest=POLICY_DIGEST,
        )
        injector = (
            ScriptedFaultInjector(
                DemoFaultPoint(arguments.fault_point), arguments.fault_ordinal
            )
            if arguments.fault_point
            else NoFaultInjector()
        )
        try:
            run_demo_campaign(
                store,
                sink,
                campaign_id=arguments.campaign_id,
                run_id="run-1",
                now=start,
                injector=injector,
            )
        except InjectedDemoFault as injected:
            fault_points = (injected.point,)
            print(f"injected fault: {injected}", file=sys.stderr)
    finally:
        lock.release()

    if fault_points:
        # A second process, with nothing in memory from the first.
        resume_at = start + timedelta(seconds=600)
        store, sink, lock = _open(state_dir)
        try:
            run_demo_campaign(
                store,
                sink,
                campaign_id=arguments.campaign_id,
                run_id="run-2",
                now=resume_at,
                resumed=True,
            )
            resumed_runs = 1
        finally:
            lock.release()

    store, sink, lock = _open(state_dir)
    try:
        report = project_demo_report(
            store,
            sink,
            campaign_id=arguments.campaign_id,
            fault_points=fault_points,
            resumed_runs=resumed_runs,
        )
    finally:
        lock.release()

    print(json.dumps(report.as_json(), indent=2, sort_keys=True))
    return 0 if report.duplicate_side_effects == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
