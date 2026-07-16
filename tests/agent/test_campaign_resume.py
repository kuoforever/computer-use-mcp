from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    BatchStatus,
    BatchTransition,
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_resume import (
    CampaignResumeError,
    CampaignResumeState,
    inspect_campaign_resume,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _store(
    tmp_path: Path,
    *,
    status: CampaignStatus = CampaignStatus.RUNNING,
    heartbeat: bool = True,
    heartbeat_run_id: str = "run_new",
    fresh_until: str = "2026-07-16T00:12:00+00:00",
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
    if heartbeat:
        heartbeat_at = (
            "2026-07-16T00:08:00+00:00"
            if fresh_until == "2026-07-16T00:12:00+00:00"
            else "2026-07-16T00:05:00+00:00"
        )
        store.write_heartbeat(
            "campaign_1",
            CampaignHeartbeat(
                campaign_id="campaign_1",
                run_id=heartbeat_run_id,
                started_at="2026-07-16T00:00:00+00:00",
                heartbeat_at=heartbeat_at,
                fresh_until=fresh_until,
            ),
        )
    store.write_handoff("campaign_1", last_run_id="run_old")
    return store, lock


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
            run_id="run_new",
            lease_expires_at=lease_expires_at,
            boundary="claim",
        ),
    )


def test_preflight_is_ready_only_with_current_fresh_idle_control_state(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        preflight = inspect_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
        )

        assert preflight.state is CampaignResumeState.READY
        assert preflight.ready
        assert preflight.next_item_ordinal == 1
        assert preflight.required_observation == "verify_current_page_and_account_state"
    finally:
        lock.release()


def test_non_resumable_handoff_blocks_before_liveness_state(tmp_path: Path) -> None:
    store, lock = _store(
        tmp_path, status=CampaignStatus.PAUSED, heartbeat=False
    )
    try:
        preflight = inspect_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
        )

        assert preflight.state is CampaignResumeState.HANDOFF_NOT_RESUMABLE
        assert preflight.required_observation == "none_until_resumed"
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("heartbeat", "heartbeat_run_id", "fresh_until", "expected"),
    [
        (False, "run_new", "2026-07-16T00:12:00+00:00", CampaignResumeState.HEARTBEAT_MISSING),
        (True, "run_other", "2026-07-16T00:12:00+00:00", CampaignResumeState.HEARTBEAT_OWNER_MISMATCH),
        (True, "run_new", "2026-07-16T00:09:00+00:00", CampaignResumeState.HEARTBEAT_STALE),
    ],
)
def test_heartbeat_state_blocks_resume(
    tmp_path: Path,
    heartbeat: bool,
    heartbeat_run_id: str,
    fresh_until: str,
    expected: CampaignResumeState,
) -> None:
    store, lock = _store(
        tmp_path,
        heartbeat=heartbeat,
        heartbeat_run_id=heartbeat_run_id,
        fresh_until=fresh_until,
    )
    try:
        preflight = inspect_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
        )
        assert preflight.state is expected
        assert preflight.ready is False
    finally:
        lock.release()


def test_active_batch_blocks_resume(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        store.append_batch(
            "campaign_1",
            BatchTransition(
                sequence=1,
                batch_id="batch_1",
                run_id="run_new",
                status=BatchStatus.STARTED,
                at="2026-07-16T00:09:00+00:00",
            ),
        )

        preflight = inspect_campaign_resume(
            store, campaign_id="campaign_1", run_id="run_new", now=NOW
        )
        assert preflight.state is CampaignResumeState.ACTIVE_BATCH
    finally:
        lock.release()


@pytest.mark.parametrize(
    "lease_expires_at",
    ["2026-07-16T00:09:00+00:00", "2026-07-16T00:11:00+00:00"],
)
def test_any_current_claim_blocks_resume(
    tmp_path: Path, lease_expires_at: str
) -> None:
    store, lock = _store(tmp_path)
    try:
        _claim(store, lease_expires_at=lease_expires_at)

        preflight = inspect_campaign_resume(
            store, campaign_id="campaign_1", run_id="run_new", now=NOW
        )
        assert preflight.state is CampaignResumeState.CLAIMS_REMAIN
    finally:
        lock.release()


def test_preflight_requires_valid_input_and_the_store_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    with pytest.raises(CampaignResumeError, match="run_id"):
        inspect_campaign_resume(
            store, campaign_id="campaign_1", run_id="bad run", now=NOW
        )
    with pytest.raises(CampaignResumeError, match="CAMPAIGN_RESUME_INVALID"):
        inspect_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=datetime(2026, 7, 16, 0, 10),
        )

    lock.release()
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        inspect_campaign_resume(
            store, campaign_id="campaign_1", run_id="run_new", now=NOW
        )
