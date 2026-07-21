from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from computer_use_agent.batching import BatchPolicy, BatchUsage
from computer_use_agent.batch_coordinator import BatchCoordinator, BatchSession
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_commit_preflight import (
    CampaignCommitPreflightState,
    inspect_extracted_item,
)
from computer_use_agent.campaign_item_progress import (
    record_item_extracted,
    record_item_observed,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _extracted_store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
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
    store.append(
        "campaign_1",
        ItemTransition(1, 1, "item_1", ItemStatus.DISCOVERED, 0, "2026-07-16T00:01:00+00:00"),
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
        policy=BatchPolicy(),
    )
    assert isinstance(opened, BatchSession)
    coordinator.claim_next_item(opened, usage=BatchUsage(), now=NOW, lease_seconds=300)
    record_item_observed(
        store,
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        item_key="item_1",
        now=NOW,
        application_state_verified=True,
        item_identity_verified=True,
    )
    record_item_extracted(
        store,
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        item_key="item_1",
        now=NOW,
        read_only_extraction_completed=True,
    )
    return store, lock


def _inspect(store: CampaignStore, *, now: datetime = NOW, **overrides: str):
    arguments = {
        "campaign_id": "campaign_1",
        "batch_id": "batch_1",
        "run_id": "run_1",
        "item_key": "item_1",
        **overrides,
    }
    return inspect_extracted_item(store, now=now, **arguments)


def test_exact_extracted_item_is_ready_only_for_result_verification_and_commit_preparation(
    tmp_path: Path,
) -> None:
    store, lock = _extracted_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        batches_before = store.read_batches("campaign_1")

        result = _inspect(store)

        assert result.state is CampaignCommitPreflightState.READY
        assert result.ready
        assert result.ordinal == 1
        assert result.required_result_verification == "verify_bounded_extraction_result"
        assert (
            result.required_commit_preparation
            == "prepare_content_digest_and_fixed_result_code"
        )
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_wrong_batch_or_stale_heartbeat_blocks_commit_preparation_without_writes(
    tmp_path: Path,
) -> None:
    store, lock = _extracted_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        assert (
            _inspect(store, batch_id="batch_other").state
            is CampaignCommitPreflightState.BATCH_OWNER_MISMATCH
        )
        assert (
            _inspect(
                store,
                now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            ).state
            is CampaignCommitPreflightState.HEARTBEAT_STALE
        )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_non_extracted_item_or_wrong_run_is_not_ready(tmp_path: Path) -> None:
    store, lock = _extracted_store(tmp_path)
    try:
        assert (
            _inspect(store, item_key="missing_item").state
            is CampaignCommitPreflightState.ITEM_NOT_EXTRACTED
        )
        ledger_before = store.read_ledger("campaign_1")
        assert (
            _inspect(store, run_id="run_other").state
            is CampaignCommitPreflightState.BATCH_OWNER_MISMATCH
        )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_another_inflight_item_blocks_commit_preparation_without_writes(
    tmp_path: Path,
) -> None:
    store, lock = _extracted_store(tmp_path)
    try:
        store.append(
            "campaign_1",
            ItemTransition(1, 2, "item_2", ItemStatus.DISCOVERED, 0, "2026-07-16T00:02:00+00:00"),
        )
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                2,
                "item_2",
                ItemStatus.CLAIMED,
                1,
                "2026-07-16T00:09:00+00:00",
                run_id="run_1",
                lease_expires_at="2026-07-16T00:14:00+00:00",
                boundary="claim",
            ),
        )
        ledger_before = store.read_ledger("campaign_1")

        result = _inspect(store)

        assert result.state is CampaignCommitPreflightState.IN_FLIGHT_SET_MISMATCH
        assert not result.ready
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()
