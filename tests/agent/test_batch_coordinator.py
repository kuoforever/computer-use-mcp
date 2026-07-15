from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.batch_coordinator import BatchCoordinator, BatchCoordinatorError, BatchSession
from computer_use_agent.batching import BatchPlan, BatchPolicy, BatchStopReason, BatchUsage
from computer_use_agent.campaign import CampaignManifest, CampaignStore, ItemStatus, ItemTransition
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64


def _store(tmp_path: Path, *, with_item: bool = True) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    store.create(
        CampaignManifest.create(
            campaign_id="campaign_1",
            kind="saved_job_review",
            policy_digest=DIGEST,
            schema_digest=DIGEST,
        )
    )
    if with_item:
        store.append(
            "campaign_1",
            ItemTransition(
                sequence=1,
                ordinal=1,
                item_key="item_1",
                status=ItemStatus.DISCOVERED,
                attempt=0,
                at="2026-07-15T00:00:00+00:00",
            ),
        )
    return store, lock


def test_open_and_finish_persist_a_complete_bounded_batch(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        coordinator = BatchCoordinator(store)
        session = coordinator.open_batch(
            campaign_id="campaign_1", batch_id="batch_1", run_id="run_1", policy=BatchPolicy(max_items=2)
        )
        assert isinstance(session, BatchSession)
        assert session.plan.item_keys == ("item_1",)
        assert coordinator.finish_batch(session, BatchUsage(items_completed=1)) == "PLAN_COMPLETE"
        persisted = store.read_batches("campaign_1")
        assert persisted.active is None
        assert persisted.transitions[-1].stop_code == "PLAN_COMPLETE"
    finally:
        lock.release()


def test_open_does_not_start_empty_or_already_active_batch(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        coordinator = BatchCoordinator(store)
        session = coordinator.open_batch(
            campaign_id="campaign_1", batch_id="batch_1", run_id="run_1", policy=BatchPolicy()
        )
        assert isinstance(session, BatchSession)
        with pytest.raises(BatchCoordinatorError, match="BATCH_ALREADY_ACTIVE"):
            coordinator.open_batch(
                campaign_id="campaign_1", batch_id="batch_2", run_id="run_2", policy=BatchPolicy()
            )
        coordinator.finish_batch(session, BatchUsage(items_completed=1))
    finally:
        lock.release()

    empty_store, empty_lock = _store(tmp_path / "empty", with_item=False)
    try:
        empty = BatchCoordinator(empty_store).open_batch(
            campaign_id="campaign_1", batch_id="batch_2", run_id="run_2", policy=BatchPolicy()
        )
        assert isinstance(empty, BatchPlan)
        assert empty.stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS
    finally:
        empty_lock.release()


def test_finish_requires_a_real_boundary_and_never_accepts_over_plan_usage(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        coordinator = BatchCoordinator(store)
        session = coordinator.open_batch(
            campaign_id="campaign_1", batch_id="batch_1", run_id="run_1", policy=BatchPolicy(max_items=2)
        )
        assert isinstance(session, BatchSession)
        with pytest.raises(BatchCoordinatorError, match="BATCH_BOUNDARY_REQUIRED"):
            coordinator.finish_batch(session, BatchUsage())
        with pytest.raises(BatchCoordinatorError, match="BATCH_USAGE_INVALID"):
            coordinator.finish_batch(session, BatchUsage(items_completed=2))
        assert coordinator.finish_batch(session, BatchUsage(items_completed=1)) == "PLAN_COMPLETE"
    finally:
        lock.release()


def test_limit_reason_is_derived_from_usage_not_caller_input(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        coordinator = BatchCoordinator(store)
        session = coordinator.open_batch(
            campaign_id="campaign_1", batch_id="batch_1", run_id="run_1", policy=BatchPolicy(max_items=1)
        )
        assert isinstance(session, BatchSession)
        assert coordinator.finish_batch(session, BatchUsage(items_completed=1)) == "ITEM_LIMIT"
    finally:
        lock.release()
