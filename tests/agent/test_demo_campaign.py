"""Fault matrix for the deterministic multi-item demo campaign.

Each test kills the driver at one named durability boundary, starts a fresh
store and sink over the same paths, and asserts what recovery is allowed to do.
The invariant under test is never "it finished"; it is *which* states may resume
and which must stop.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.campaign import CampaignStore, ItemStatus
from computer_use_agent.demo_campaign import (
    DemoCampaignError,
    DemoFaultPoint,
    DurableFakeSideEffectSink,
    InjectedDemoFault,
    NoFaultInjector,
    ScriptedFaultInjector,
    SideEffectOutcome,
    fault_injector_from_env,
    idempotency_key,
    prepare_demo_campaign,
    project_demo_report,
    run_demo_campaign,
    synthetic_demo_plan,
)
from computer_use_agent.run_lock import RunLock

DIGEST = "b" * 64
CAMPAIGN_ID = "demo-campaign-1"
START = datetime(2026, 7, 20, 9, 0, 0, tzinfo=timezone.utc)
RESUME = datetime(2026, 7, 20, 9, 30, 0, tzinfo=timezone.utc)


def _open(tmp_path: Path) -> tuple[CampaignStore, DurableFakeSideEffectSink, RunLock]:
    """Open durable state the way a fresh process would."""

    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    sink = DurableFakeSideEffectSink((tmp_path / "sink" / "side-effects.jsonl").resolve())
    return store, sink, lock


def _statuses(store: CampaignStore) -> dict[str, ItemStatus]:
    projection = store.read_ledger(CAMPAIGN_ID)
    return {key: item.status for key, item in projection.items.items()}


def _prepare(tmp_path: Path, count: int) -> tuple[CampaignStore, DurableFakeSideEffectSink, RunLock]:
    store, sink, lock = _open(tmp_path)
    prepare_demo_campaign(
        store,
        campaign_id=CAMPAIGN_ID,
        run_id="run-1",
        plan=synthetic_demo_plan(count),
        now=START,
        policy_digest=DIGEST,
    )
    return store, sink, lock


def test_clean_run_commits_every_item_exactly_once(tmp_path: Path) -> None:
    store, sink, lock = _prepare(tmp_path, 5)
    try:
        outcome = run_demo_campaign(
            store,
            sink,
            campaign_id=CAMPAIGN_ID,
            run_id="run-1",
            now=START,
            injector=NoFaultInjector(),
        )
        assert len(outcome.committed) == 5
        assert sink.duplicate_attempts() == ()
        assert len(sink.accepted_keys()) == 5
        assert set(_statuses(store).values()) == {ItemStatus.COMMITTED}
    finally:
        lock.release()


def test_crash_after_commit_does_not_reprocess_the_committed_item(tmp_path: Path) -> None:
    """F1: the dead process finished item 2; recovery must start at item 3."""

    store, sink, lock = _prepare(tmp_path, 5)
    try:
        with pytest.raises(InjectedDemoFault):
            run_demo_campaign(
                store,
                sink,
                campaign_id=CAMPAIGN_ID,
                run_id="run-1",
                now=START,
                injector=ScriptedFaultInjector(DemoFaultPoint.AFTER_ITEM_COMMIT, 2),
            )
        assert len(sink.accepted_keys()) == 2
    finally:
        lock.release()

    store, sink, lock = _open(tmp_path)
    try:
        outcome = run_demo_campaign(
            store,
            sink,
            campaign_id=CAMPAIGN_ID,
            run_id="run-2",
            now=RESUME,
            resumed=True,
        )
        assert len(outcome.skipped_already_committed) == 2
        assert {item.ordinal for item in outcome.committed} == {3, 4, 5}
        assert sink.duplicate_attempts() == ()
        assert len(sink.accepted_keys()) == 5
        assert set(_statuses(store).values()) == {ItemStatus.COMMITTED}
    finally:
        lock.release()


def test_crash_after_dispatch_intent_parks_the_item_and_never_replays(tmp_path: Path) -> None:
    """F2: the effect may or may not have happened, so nothing may be retried."""

    store, sink, lock = _prepare(tmp_path, 5)
    try:
        with pytest.raises(InjectedDemoFault):
            run_demo_campaign(
                store,
                sink,
                campaign_id=CAMPAIGN_ID,
                run_id="run-1",
                now=START,
                injector=ScriptedFaultInjector(DemoFaultPoint.AFTER_DISPATCH_INTENT, 3),
            )
        pending_key = idempotency_key(CAMPAIGN_ID, "demo-item-0003")
        assert sink.outcome_for(pending_key) is SideEffectOutcome.PENDING
    finally:
        lock.release()

    store, sink, lock = _open(tmp_path)
    try:
        outcome = run_demo_campaign(
            store,
            sink,
            campaign_id=CAMPAIGN_ID,
            run_id="run-2",
            now=RESUME,
            resumed=True,
        )
        statuses = _statuses(store)
        assert outcome.parked_uncertain == ("demo-item-0003",)
        assert statuses["demo-item-0003"] is ItemStatus.UNCERTAIN
        # The uncertain item was never dispatched a second time.
        assert sink.duplicate_attempts() == ()
        assert idempotency_key(CAMPAIGN_ID, "demo-item-0003") not in sink.accepted_keys()
        # Attention is scoped to the affected item. The rest of the campaign is
        # unaffected by one unknown outcome and still completes, which is why
        # UNCERTAIN is a terminal item state rather than a campaign-wide halt.
        assert statuses["demo-item-0001"] is ItemStatus.COMMITTED
        assert statuses["demo-item-0002"] is ItemStatus.COMMITTED
        assert {item.ordinal for item in outcome.committed} == {4, 5}
        assert statuses["demo-item-0004"] is ItemStatus.COMMITTED
        assert statuses["demo-item-0005"] is ItemStatus.COMMITTED
    finally:
        lock.release()


def test_crash_after_side_effect_reconciles_from_the_exact_receipt(tmp_path: Path) -> None:
    """F3: the effect provably happened, so bookkeeping catches up without redispatch."""

    store, sink, lock = _prepare(tmp_path, 4)
    try:
        with pytest.raises(InjectedDemoFault):
            run_demo_campaign(
                store,
                sink,
                campaign_id=CAMPAIGN_ID,
                run_id="run-1",
                now=START,
                injector=ScriptedFaultInjector(
                    DemoFaultPoint.AFTER_SIDE_EFFECT_COMPLETION, 2
                ),
            )
        assert len(sink.accepted_keys()) == 2
        assert _statuses(store)["demo-item-0002"] is ItemStatus.OBSERVED
    finally:
        lock.release()

    store, sink, lock = _open(tmp_path)
    try:
        outcome = run_demo_campaign(
            store,
            sink,
            campaign_id=CAMPAIGN_ID,
            run_id="run-2",
            now=RESUME,
            resumed=True,
        )
        assert outcome.reconciled == ("demo-item-0002",)
        assert _statuses(store)["demo-item-0002"] is ItemStatus.COMMITTED
        assert sink.duplicate_attempts() == ()
        assert len(sink.accepted_keys()) == 4
    finally:
        lock.release()


def test_crash_before_projection_leaves_durable_state_intact(tmp_path: Path) -> None:
    """F6: the report is a projection; losing it costs nothing."""

    store, sink, lock = _prepare(tmp_path, 3)
    try:
        with pytest.raises(InjectedDemoFault):
            run_demo_campaign(
                store,
                sink,
                campaign_id=CAMPAIGN_ID,
                run_id="run-1",
                now=START,
                injector=ScriptedFaultInjector(DemoFaultPoint.BEFORE_FINAL_PROJECTION, 3),
            )
    finally:
        lock.release()

    store, sink, lock = _open(tmp_path)
    try:
        report = project_demo_report(
            store,
            sink,
            campaign_id=CAMPAIGN_ID,
            fault_points=(DemoFaultPoint.BEFORE_FINAL_PROJECTION,),
            resumed_runs=1,
        )
        assert report.committed_items == 3
        assert report.duplicate_side_effects == 0
        assert report.uncertain_items == 0
        payload = report.as_json()
        assert payload["campaign_digest"] != CAMPAIGN_ID
        assert CAMPAIGN_ID not in str(payload)
    finally:
        lock.release()


def test_sink_rejects_and_records_a_duplicate_dispatch(tmp_path: Path) -> None:
    """The sink must expose a duplicate, never absorb it."""

    _store, sink, lock = _open(tmp_path)
    try:
        key = idempotency_key(CAMPAIGN_ID, "demo-item-0001")
        sink.dispatch(key)
        with pytest.raises(DemoCampaignError, match="DEMO_SINK_DUPLICATE_REJECTED"):
            sink.dispatch(key)
        assert sink.duplicate_attempts() == (key,)
        assert len(sink.accepted_keys()) == 1
    finally:
        lock.release()


def test_fault_injector_defaults_to_no_fault() -> None:
    assert isinstance(fault_injector_from_env({}), NoFaultInjector)
    assert isinstance(fault_injector_from_env({"CUA_DEMO_FAULT_POINT": " "}), NoFaultInjector)


def test_fault_injector_rejects_unknown_configuration() -> None:
    with pytest.raises(DemoCampaignError, match="DEMO_FAULT_POINT_INVALID"):
        fault_injector_from_env({"CUA_DEMO_FAULT_POINT": "after_everything"})
    with pytest.raises(DemoCampaignError, match="DEMO_FAULT_ORDINAL_INVALID"):
        fault_injector_from_env(
            {"CUA_DEMO_FAULT_POINT": "after_item_commit", "CUA_DEMO_FAULT_ORDINAL": "x"}
        )


def test_scripted_injector_fires_once_at_the_named_point() -> None:
    injector = ScriptedFaultInjector(DemoFaultPoint.AFTER_ITEM_COMMIT, 2)
    injector.check(DemoFaultPoint.AFTER_ITEM_COMMIT, ordinal=1)
    injector.check(DemoFaultPoint.AFTER_ITEM_CLAIM, ordinal=2)
    with pytest.raises(InjectedDemoFault):
        injector.check(DemoFaultPoint.AFTER_ITEM_COMMIT, ordinal=2)
    injector.check(DemoFaultPoint.AFTER_ITEM_COMMIT, ordinal=2)
