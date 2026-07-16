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


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _store(
    tmp_path: Path,
    *,
    status: CampaignStatus = CampaignStatus.RUNNING,
    heartbeat_at: str = "2026-07-16T00:05:00+00:00",
    fresh_until: str = "2026-07-16T00:09:00+00:00",
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
    store.write_heartbeat(
        "campaign_1",
        CampaignHeartbeat(
            campaign_id="campaign_1",
            run_id="run_old",
            started_at="2026-07-16T00:00:00+00:00",
            heartbeat_at=heartbeat_at,
            fresh_until=fresh_until,
        ),
    )
    return store, lock


def _replacement(
    *,
    run_id: str = "run_new",
    started_at: str = "2026-07-16T00:10:00+00:00",
    heartbeat_at: str = "2026-07-16T00:10:00+00:00",
) -> CampaignHeartbeat:
    return CampaignHeartbeat(
        campaign_id="campaign_1",
        run_id=run_id,
        started_at=started_at,
        heartbeat_at=heartbeat_at,
        fresh_until="2026-07-16T00:15:00+00:00",
    )


def _claim(store: CampaignStore, *, lease_expires_at: str) -> None:
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
            run_id="run_old",
            lease_expires_at=lease_expires_at,
            boundary="claim",
        ),
    )


def test_recovery_atomically_replaces_only_the_stale_heartbeat_owner(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        manifest = store.read_manifest("campaign_1")
        ledger = store.read_ledger("campaign_1")
        replacement = _replacement()

        recovered = store.recover_stale_heartbeat(
            "campaign_1",
            stale_run_id="run_old",
            replacement=replacement,
            now=NOW,
        )

        assert recovered == replacement
        assert store.read_heartbeat("campaign_1") == replacement
        assert store.read_manifest("campaign_1") == manifest
        assert store.read_ledger("campaign_1") == ledger
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("status", "fresh_until"),
    [
        (CampaignStatus.PAUSED, "2026-07-16T00:09:00+00:00"),
        (CampaignStatus.RUNNING, "2026-07-16T00:11:00+00:00"),
    ],
)
def test_paused_campaign_or_fresh_heartbeat_blocks_recovery(
    tmp_path: Path, status: CampaignStatus, fresh_until: str
) -> None:
    heartbeat_at = (
        "2026-07-16T00:06:00+00:00"
        if fresh_until == "2026-07-16T00:11:00+00:00"
        else "2026-07-16T00:05:00+00:00"
    )
    store, lock = _store(
        tmp_path,
        status=status,
        heartbeat_at=heartbeat_at,
        fresh_until=fresh_until,
    )
    try:
        before = store.read_heartbeat("campaign_1")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HEARTBEAT_RECOVERY_BLOCKED"):
            store.recover_stale_heartbeat(
                "campaign_1",
                stale_run_id="run_old",
                replacement=_replacement(),
                now=NOW,
            )
        assert store.read_heartbeat("campaign_1") == before
    finally:
        lock.release()


@pytest.mark.parametrize(
    "lease_expires_at",
    ["2026-07-16T00:09:00+00:00", "2026-07-16T00:11:00+00:00"],
)
def test_every_claim_must_be_released_before_heartbeat_owner_recovery(
    tmp_path: Path, lease_expires_at: str
) -> None:
    store, lock = _store(tmp_path)
    try:
        _claim(store, lease_expires_at=lease_expires_at)
        before = store.read_ledger("campaign_1")

        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HEARTBEAT_RECOVERY_BLOCKED"):
            store.recover_stale_heartbeat(
                "campaign_1",
                stale_run_id="run_old",
                replacement=_replacement(),
                now=NOW,
            )

        assert store.read_ledger("campaign_1") == before
        assert store.read_heartbeat("campaign_1").run_id == "run_old"  # type: ignore[union-attr]
    finally:
        lock.release()


def test_recovery_requires_expected_owner_and_a_new_heartbeat_at_now(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        invalid_cases = (
            ("run_other", _replacement()),
            ("run_old", _replacement(run_id="run_old")),
            (
                "run_old",
                _replacement(
                    started_at="2026-07-16T00:10:01+00:00",
                    heartbeat_at="2026-07-16T00:10:01+00:00",
                ),
            ),
        )
        for stale_run_id, replacement in invalid_cases:
            with pytest.raises(CampaignStoreError):
                store.recover_stale_heartbeat(
                    "campaign_1",
                    stale_run_id=stale_run_id,
                    replacement=replacement,
                    now=NOW,
                )
        assert store.read_heartbeat("campaign_1").run_id == "run_old"  # type: ignore[union-attr]
    finally:
        lock.release()


def test_recovery_requires_the_store_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    lock.release()

    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        store.recover_stale_heartbeat(
            "campaign_1",
            stale_run_id="run_old",
            replacement=_replacement(),
            now=NOW,
        )
