from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.stale_run_inspection import (
    StaleRunInspectionError,
    StaleRunState,
    inspect_stale_run,
)


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _store(
    tmp_path: Path, *, status: CampaignStatus = CampaignStatus.RUNNING
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
    return store, lock


def _write_heartbeat(
    store: CampaignStore,
    *,
    run_id: str = "run_1",
    fresh_until: str = "2026-07-16T00:09:00+00:00",
) -> None:
    store.write_heartbeat(
        "campaign_1",
        CampaignHeartbeat(
            campaign_id="campaign_1",
            run_id=run_id,
            started_at="2026-07-16T00:00:00+00:00",
            heartbeat_at="2026-07-16T00:06:00+00:00",
            fresh_until=fresh_until,
        ),
    )


def _claim(
    store: CampaignStore,
    *,
    run_id: str = "run_1",
    lease_expires_at: str = "2026-07-16T00:09:00+00:00",
) -> None:
    store.append(
        "campaign_1",
        ItemTransition(
            1,
            1,
            "item_1",
            ItemStatus.DISCOVERED,
            0,
            "2026-07-16T00:00:00+00:00",
        ),
    )
    store.append(
        "campaign_1",
        ItemTransition(
            2,
            1,
            "item_1",
            ItemStatus.CLAIMED,
            1,
            "2026-07-16T00:00:00+00:00",
            run_id=run_id,
            lease_expires_at=lease_expires_at,
            boundary="claim",
        ),
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CampaignStatus.PAUSED, StaleRunState.PAUSED),
        (CampaignStatus.COMPLETED, StaleRunState.NOT_RUNNING),
    ],
)
def test_manifest_state_blocks_recovery_before_liveness_signals(
    tmp_path: Path, status: CampaignStatus, expected: StaleRunState
) -> None:
    store, lock = _store(tmp_path, status=status)
    try:
        inspection = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)
        assert inspection.state is expected
        assert inspection.is_recovery_candidate is False
    finally:
        lock.release()


def test_missing_or_fresh_heartbeat_blocks_recovery(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        missing = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)
        assert missing.state is StaleRunState.MISSING_HEARTBEAT

        _write_heartbeat(store, fresh_until="2026-07-16T00:11:00+00:00")
        fresh = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)
        assert fresh.state is StaleRunState.FRESH_HEARTBEAT
        assert fresh.is_recovery_candidate is False
    finally:
        lock.release()


def test_stale_heartbeat_with_active_lease_is_not_recoverable(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        _write_heartbeat(store)
        _claim(store, lease_expires_at="2026-07-16T00:11:00+00:00")

        inspection = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)
        assert inspection.state is StaleRunState.ACTIVE_LEASE
        assert [claim.item_key for claim in inspection.leases.active] == ["item_1"]
    finally:
        lock.release()


def test_claim_owner_must_match_the_heartbeat_owner(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        _write_heartbeat(store)
        _claim(store, run_id="run_other")

        inspection = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)
        assert inspection.state is StaleRunState.INCONSISTENT_OWNER
        assert inspection.is_recovery_candidate is False
    finally:
        lock.release()


def test_stale_heartbeat_and_only_stale_claims_form_a_recovery_candidate(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        _write_heartbeat(store)
        _claim(store)
        before = store.read_ledger("campaign_1")

        inspection = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)

        assert inspection.state is StaleRunState.STALE
        assert inspection.is_recovery_candidate
        assert [claim.item_key for claim in inspection.leases.stale] == ["item_1"]
        assert store.read_ledger("campaign_1") == before
    finally:
        lock.release()


def test_stale_heartbeat_without_claims_is_a_control_state_recovery_candidate(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        _write_heartbeat(store)

        inspection = inspect_stale_run(store, campaign_id="campaign_1", now=NOW)

        assert inspection.state is StaleRunState.STALE
        assert inspection.is_recovery_candidate
        assert inspection.leases.active == ()
        assert inspection.leases.stale == ()
    finally:
        lock.release()


def test_inspection_requires_the_run_lock_and_an_aware_clock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    _write_heartbeat(store)
    with pytest.raises(StaleRunInspectionError, match="STALE_RUN_INSPECTION_INVALID"):
        inspect_stale_run(
            store,
            campaign_id="campaign_1",
            now=datetime(2026, 7, 16, 0, 10),
        )

    lock.release()
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        inspect_stale_run(store, campaign_id="campaign_1", now=NOW)
