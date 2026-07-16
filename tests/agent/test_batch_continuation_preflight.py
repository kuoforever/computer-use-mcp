from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from computer_use_agent.batch_coordinator import (
    BatchContinuationState,
    BatchCoordinator,
    BatchSession,
)
from computer_use_agent.batching import BatchPlan, BatchPolicy, BatchStopReason, BatchUsage
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_item_progress import (
    record_item_committed,
    record_item_extracted,
    record_item_observed,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
CONTENT_DIGEST = "b" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _committed_prefix_store(
    tmp_path: Path,
    *,
    ordinals: tuple[int, ...] = (1, 2),
    max_items: int = 2,
) -> tuple[CampaignStore, RunLock, BatchCoordinator, BatchSession]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    store.create(
        CampaignManifest(
            campaign_id="campaign_1",
            kind="saved_job_review",
            policy_digest=DIGEST,
            schema_digest=DIGEST,
            created_at="2026-07-16T00:00:00+00:00",
            updated_at="2026-07-16T00:00:00+00:00",
        )
    )
    for ordinal in ordinals:
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                ordinal,
                f"item_{ordinal}",
                ItemStatus.DISCOVERED,
                0,
                f"2026-07-16T00:0{ordinal}:00+00:00",
            ),
        )
    store.write_heartbeat(
        "campaign_1",
        CampaignHeartbeat(
            campaign_id="campaign_1",
            run_id="run_1",
            started_at="2026-07-16T00:00:00+00:00",
            heartbeat_at="2026-07-16T00:08:00+00:00",
            fresh_until="2026-07-16T00:12:00+00:00",
        ),
    )
    coordinator = BatchCoordinator(store)
    opened = coordinator.open_batch(
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        policy=BatchPolicy(max_items=max_items),
    )
    assert isinstance(opened, BatchSession)
    first_key = opened.plan.item_keys[0]
    coordinator.claim_first_item(opened, now=NOW, lease_seconds=300)
    record_item_observed(
        store,
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        item_key=first_key,
        now=NOW,
        application_state_verified=True,
        item_identity_verified=True,
    )
    record_item_extracted(
        store,
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        item_key=first_key,
        now=NOW,
        read_only_extraction_completed=True,
    )
    record_item_committed(
        store,
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        item_key=first_key,
        now=NOW,
        bounded_result_verified=True,
        content_digest=CONTENT_DIGEST,
    )
    return store, lock, coordinator, opened


def test_committed_prefix_is_ready_only_for_exact_next_planned_claim(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")

        result = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )

        assert result.state is BatchContinuationState.READY
        assert result.ready
        assert result.completed_items == 1
        assert result.next_item_key == "item_2"
        assert result.next_item_ordinal == 2
        assert result.stop_reason is None
        assert result.required_claim == "claim_exact_next_planned_item"
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_usage_mismatch_or_stale_heartbeat_blocks_continuation_without_writes(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        assert (
            coordinator.inspect_continuation(session, usage=BatchUsage(), now=NOW).state
            is BatchContinuationState.USAGE_MISMATCH
        )
        assert (
            coordinator.inspect_continuation(
                session,
                usage=BatchUsage(items_completed=1),
                now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            ).state
            is BatchContinuationState.HEARTBEAT_STALE
        )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_newly_discovered_earlier_item_is_plan_drift(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 3),
    )
    try:
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                2,
                "item_2",
                ItemStatus.DISCOVERED,
                0,
                "2026-07-16T00:09:00+00:00",
            ),
        )
        ledger_before = store.read_ledger("campaign_1")

        result = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )

        assert result.state is BatchContinuationState.PLAN_DRIFT
        assert not result.ready
        assert result.next_item_key is None
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_forged_session_cannot_omit_the_committed_prefix(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        forged = BatchSession(
            campaign_id=session.campaign_id,
            batch_id=session.batch_id,
            run_id=session.run_id,
            policy=session.policy,
            plan=BatchPlan(item_keys=("item_2",), stop_reason=None),
        )
        ledger_before = store.read_ledger("campaign_1")

        result = coordinator.inspect_continuation(
            forged,
            usage=BatchUsage(),
            now=NOW,
        )

        assert result.state is BatchContinuationState.PLAN_DRIFT
        assert not result.ready
        assert result.next_item_key is None
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_reached_limit_and_completed_plan_return_fixed_terminal_states(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 2),
        max_items=1,
    )
    try:
        limited = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )
        assert limited.state is BatchContinuationState.LIMIT_REACHED
        assert limited.stop_reason is BatchStopReason.ITEM_LIMIT
        assert limited.next_item_key is None
    finally:
        lock.release()

    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "complete",
        ordinals=(1,),
        max_items=2,
    )
    try:
        complete = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )
        assert complete.state is BatchContinuationState.PLAN_COMPLETE
        assert complete.stop_reason is None
        assert complete.next_item_key is None
    finally:
        lock.release()
