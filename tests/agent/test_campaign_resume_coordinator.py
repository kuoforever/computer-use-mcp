from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.batching import BatchPolicy, BatchStopReason
from computer_use_agent.batch_coordinator import (
    BatchCoordinator,
    BatchCoordinatorError,
    BatchSession,
)
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_resume import CampaignResumeState
from computer_use_agent.campaign_resume_planning import CampaignResumePlan
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _store(
    tmp_path: Path,
    *,
    status: CampaignStatus = CampaignStatus.RUNNING,
    item_ordinals: tuple[int, ...] = (),
) -> tuple[CampaignStore, RunLock]:
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
            status=status,
        )
    )
    for sequence, ordinal in enumerate(item_ordinals, start=1):
        store.append(
            "campaign_1",
            ItemTransition(
                sequence,
                ordinal,
                f"item_{ordinal}",
                ItemStatus.DISCOVERED,
                0,
                "2026-07-16T00:01:00+00:00",
            ),
        )
    store.write_heartbeat(
        "campaign_1",
        CampaignHeartbeat(
            campaign_id="campaign_1",
            run_id="run_new",
            started_at="2026-07-16T00:00:00+00:00",
            heartbeat_at="2026-07-16T00:08:00+00:00",
            fresh_until="2026-07-16T00:12:00+00:00",
        ),
    )
    store.write_handoff("campaign_1", last_run_id="run_old")
    return store, lock


def test_ready_nonempty_resume_plan_persists_exact_started_batch(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path, item_ordinals=(2, 1, 3))
    try:
        ledger_before = store.read_ledger("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        handoff_before = store.read_handoff("campaign_1")

        opened = BatchCoordinator(store).open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(max_items=2),
        )

        assert isinstance(opened, BatchSession)
        assert opened.plan.item_keys == ("item_1", "item_2")
        active = store.read_batches("campaign_1").active
        assert active is not None
        assert active.batch_id == "batch_1"
        assert active.run_id == "run_new"
        assert active.at == "2026-07-16T00:10:00+00:00"
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_handoff("campaign_1") == handoff_before
    finally:
        lock.release()


def test_empty_resume_plan_does_not_write_started(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        result = BatchCoordinator(store).open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )

        assert isinstance(result, CampaignResumePlan)
        assert result.preflight.state is CampaignResumeState.READY
        assert result.batch is not None
        assert result.batch.stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS
        assert store.read_batches("campaign_1").transitions == ()
    finally:
        lock.release()


def test_blocked_resume_does_not_write_started(tmp_path: Path) -> None:
    store, lock = _store(
        tmp_path,
        status=CampaignStatus.PAUSED,
        item_ordinals=(1,),
    )
    try:
        result = BatchCoordinator(store).open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )

        assert isinstance(result, CampaignResumePlan)
        assert result.preflight.state is CampaignResumeState.HANDOFF_NOT_RESUMABLE
        assert result.batch is None
        assert store.read_batches("campaign_1").transitions == ()
    finally:
        lock.release()


def test_second_resume_open_observes_active_batch_and_does_not_append(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path, item_ordinals=(1, 2))
    try:
        coordinator = BatchCoordinator(store)
        first = coordinator.open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )
        second = coordinator.open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_2",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )

        assert isinstance(first, BatchSession)
        assert isinstance(second, CampaignResumePlan)
        assert second.preflight.state is CampaignResumeState.ACTIVE_BATCH
        assert len(store.read_batches("campaign_1").transitions) == 1
    finally:
        lock.release()


def test_resumed_batch_claims_only_its_first_planned_item(tmp_path: Path) -> None:
    store, lock = _store(tmp_path, item_ordinals=(2, 1, 3))
    try:
        coordinator = BatchCoordinator(store)
        opened = coordinator.open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(max_items=2),
        )
        assert isinstance(opened, BatchSession)

        claimed = coordinator.claim_first_item(opened, now=NOW, lease_seconds=300)

        assert claimed.item_key == "item_1"
        assert claimed.status is ItemStatus.CLAIMED
        assert claimed.attempt == 1
        assert claimed.run_id == "run_new"
        assert claimed.lease_expires_at == "2026-07-16T00:15:00+00:00"
        assert claimed.boundary == "claim"
        assert store.read_ledger("campaign_1").items["item_2"].status is ItemStatus.DISCOVERED
        assert store.read_batches("campaign_1").active is not None
    finally:
        lock.release()


def test_resumed_batch_refuses_a_second_claim_without_mutation(tmp_path: Path) -> None:
    store, lock = _store(tmp_path, item_ordinals=(1, 2))
    try:
        coordinator = BatchCoordinator(store)
        opened = coordinator.open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )
        assert isinstance(opened, BatchSession)
        coordinator.claim_first_item(opened, now=NOW, lease_seconds=300)
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(BatchCoordinatorError, match="BATCH_ITEM_CLAIM_ACTIVE"):
            coordinator.claim_first_item(opened, now=NOW, lease_seconds=300)

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("claim_now", "lease_seconds", "code"),
    [
        (datetime(2026, 7, 16, 0, 10), 300, "BATCH_CLOCK_INVALID"),
        (NOW, 0, "BATCH_LEASE_INVALID"),
        (NOW, 3601, "BATCH_LEASE_INVALID"),
        (
            datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            300,
            "BATCH_HEARTBEAT_NOT_FRESH",
        ),
    ],
)
def test_resumed_batch_claim_fails_closed_for_invalid_time_or_lease(
    tmp_path: Path,
    claim_now: datetime,
    lease_seconds: int,
    code: str,
) -> None:
    store, lock = _store(tmp_path, item_ordinals=(1,))
    try:
        coordinator = BatchCoordinator(store)
        opened = coordinator.open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )
        assert isinstance(opened, BatchSession)
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(BatchCoordinatorError, match=code):
            coordinator.claim_first_item(
                opened,
                now=claim_now,
                lease_seconds=lease_seconds,
            )

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_resumed_batch_refuses_a_forged_or_drifted_plan(tmp_path: Path) -> None:
    store, lock = _store(tmp_path, item_ordinals=(1, 2))
    try:
        coordinator = BatchCoordinator(store)
        opened = coordinator.open_resumed_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )
        assert isinstance(opened, BatchSession)
        forged = BatchSession(
            campaign_id=opened.campaign_id,
            batch_id=opened.batch_id,
            run_id=opened.run_id,
            policy=BatchPolicy(max_items=1),
            plan=opened.plan,
        )
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(BatchCoordinatorError, match="BATCH_PLAN_DRIFT"):
            coordinator.claim_first_item(forged, now=NOW, lease_seconds=300)

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()
