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
from computer_use_agent.campaign_extraction_preflight import (
    CampaignExtractionPreflightState,
    inspect_observed_item,
)
from computer_use_agent.campaign_item_progress import record_item_observed
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _observed_store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
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
    return store, lock


def _inspect(store: CampaignStore, *, now: datetime = NOW, **overrides: str):
    arguments = {
        "campaign_id": "campaign_1",
        "batch_id": "batch_1",
        "run_id": "run_1",
        "item_key": "item_1",
        **overrides,
    }
    return inspect_observed_item(store, now=now, **arguments)


def test_exact_observed_item_is_ready_only_for_bounded_read_only_extraction(
    tmp_path: Path,
) -> None:
    store, lock = _observed_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        batches_before = store.read_batches("campaign_1")

        result = _inspect(store)

        assert result.state is CampaignExtractionPreflightState.READY
        assert result.ready
        assert result.ordinal == 1
        assert result.required_extraction == "perform_bounded_read_only_extraction"
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_wrong_batch_or_stale_heartbeat_blocks_extraction_without_writes(
    tmp_path: Path,
) -> None:
    store, lock = _observed_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        assert (
            _inspect(store, batch_id="batch_other").state
            is CampaignExtractionPreflightState.BATCH_OWNER_MISMATCH
        )
        assert (
            _inspect(
                store,
                now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            ).state
            is CampaignExtractionPreflightState.HEARTBEAT_STALE
        )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_another_inflight_item_blocks_extraction_without_writes(tmp_path: Path) -> None:
    store, lock = _observed_store(tmp_path)
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

        assert result.state is CampaignExtractionPreflightState.IN_FLIGHT_SET_MISMATCH
        assert not result.ready
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()
