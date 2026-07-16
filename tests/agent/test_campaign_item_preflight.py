from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from computer_use_agent.batching import BatchPolicy
from computer_use_agent.batch_coordinator import BatchCoordinator, BatchSession
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_item_preflight import (
    CampaignItemPreflightState,
    inspect_claimed_item,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _opened_store(tmp_path: Path, *, claim: bool) -> tuple[CampaignStore, RunLock]:
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
    if claim:
        coordinator.claim_first_item(opened, now=NOW, lease_seconds=300)
    return store, lock


def _inspect(store: CampaignStore, *, now: datetime = NOW, **overrides: str):
    arguments = {
        "campaign_id": "campaign_1",
        "batch_id": "batch_1",
        "run_id": "run_1",
        "item_key": "item_1",
        **overrides,
    }
    return inspect_claimed_item(store, now=now, **arguments)


def test_exact_active_claim_is_ready_only_for_identity_reobservation(tmp_path: Path) -> None:
    store, lock = _opened_store(tmp_path, claim=True)
    try:
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")

        result = _inspect(store)

        assert result.state is CampaignItemPreflightState.READY
        assert result.ready
        assert result.ordinal == 1
        assert (
            result.required_application_observation
            == "verify_current_page_and_account_state"
        )
        assert result.required_item_observation == "verify_claimed_item_identity"
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_missing_claim_or_wrong_batch_fails_closed_without_writes(tmp_path: Path) -> None:
    store, lock = _opened_store(tmp_path, claim=False)
    try:
        ledger_before = store.read_ledger("campaign_1")
        assert _inspect(store).state is CampaignItemPreflightState.ITEM_NOT_CLAIMED
        assert (
            _inspect(store, batch_id="batch_other").state
            is CampaignItemPreflightState.BATCH_OWNER_MISMATCH
        )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_expired_claim_is_not_ready_for_item_operation(tmp_path: Path) -> None:
    store, lock = _opened_store(tmp_path, claim=True)
    try:
        store.write_heartbeat(
            "campaign_1",
            CampaignHeartbeat(
                campaign_id="campaign_1",
                run_id="run_1",
                started_at="2026-07-16T00:00:00+00:00",
                heartbeat_at="2026-07-16T00:14:00+00:00",
                fresh_until="2026-07-16T00:18:00+00:00",
            ),
        )
        result = _inspect(
            store,
            now=datetime(2026, 7, 16, 0, 15, tzinfo=timezone.utc),
        )

        assert result.state is CampaignItemPreflightState.CLAIM_LEASE_STALE
        assert not result.ready
    finally:
        lock.release()
