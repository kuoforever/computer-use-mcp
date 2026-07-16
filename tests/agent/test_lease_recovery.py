from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CampaignManifest,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.lease_recovery import LeaseRecoveryError, release_stale_claim
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64


def _claimed_store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
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
            lease_expires_at="2026-07-16T00:10:00+00:00",
            boundary="claim",
        ),
    )
    return store, lock


def test_release_stale_claim_appends_retryable_without_reclaiming(tmp_path: Path) -> None:
    store, lock = _claimed_store(tmp_path)
    try:
        projection = release_stale_claim(
            store,
            campaign_id="campaign_1",
            item_key="item_1",
            recovery_run_id="run_recovery",
            now=datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc),
        )

        released = projection.items["item_1"]
        assert released.status is ItemStatus.RETRYABLE
        assert released.attempt == 1
        assert released.run_id == "run_recovery"
        assert released.boundary == "lease_expired"
        assert released.code == "LEASE_EXPIRED"
        assert released.lease_expires_at is None
        assert [entry.status for entry in projection.transitions] == [
            ItemStatus.DISCOVERED,
            ItemStatus.CLAIMED,
            ItemStatus.RETRYABLE,
        ]
    finally:
        lock.release()


def test_release_refuses_an_active_or_non_claimed_item_without_mutation(tmp_path: Path) -> None:
    store, lock = _claimed_store(tmp_path)
    try:
        with pytest.raises(LeaseRecoveryError, match="LEASE_RECOVERY_ACTIVE"):
            release_stale_claim(
                store,
                campaign_id="campaign_1",
                item_key="item_1",
                recovery_run_id="run_recovery",
                now=datetime(2026, 7, 16, 0, 9, tzinfo=timezone.utc),
            )
        with pytest.raises(LeaseRecoveryError, match="LEASE_RECOVERY_NOT_CLAIMED"):
            release_stale_claim(
                store,
                campaign_id="campaign_1",
                item_key="missing",
                recovery_run_id="run_recovery",
                now=datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc),
            )

        assert len(store.read_ledger("campaign_1").transitions) == 2
    finally:
        lock.release()


def test_release_requires_the_store_run_lock(tmp_path: Path) -> None:
    store, lock = _claimed_store(tmp_path)
    lock.release()

    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        release_stale_claim(
            store,
            campaign_id="campaign_1",
            item_key="item_1",
            recovery_run_id="run_recovery",
            now=datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc),
        )


def test_reducer_rejects_early_or_noncanonical_claim_release(tmp_path: Path) -> None:
    store, lock = _claimed_store(tmp_path)
    try:
        for at, boundary, code in (
            ("2026-07-16T00:09:59+00:00", "lease_expired", "LEASE_EXPIRED"),
            ("2026-07-16T00:10:00+00:00", "retry", "LEASE_EXPIRED"),
            ("2026-07-16T00:10:00+00:00", "lease_expired", "RETRY"),
        ):
            with pytest.raises(CampaignStoreError, match="CAMPAIGN_LEDGER_INVALID"):
                store.append(
                    "campaign_1",
                    ItemTransition(
                        3,
                        1,
                        "item_1",
                        ItemStatus.RETRYABLE,
                        1,
                        at,
                        run_id="run_recovery",
                        boundary=boundary,
                        code=code,
                    ),
                )
        assert len(store.read_ledger("campaign_1").transitions) == 2
    finally:
        lock.release()
