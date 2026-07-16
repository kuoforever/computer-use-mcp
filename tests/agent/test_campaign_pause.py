from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64


def _manifest(*, status: CampaignStatus = CampaignStatus.RUNNING) -> CampaignManifest:
    return CampaignManifest(
        campaign_id="campaign_1",
        kind="saved_job_review",
        policy_digest=DIGEST,
        schema_digest=DIGEST,
        created_at="2026-07-16T00:00:00+00:00",
        updated_at="2026-07-16T00:00:00+00:00",
        status=status,
    )


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    store.create(_manifest())
    return store, lock


def test_pause_and_resume_are_durable_identity_preserving_transitions(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        paused = store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:00+00:00",
        )
        resumed = store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.RUNNING,
            at="2026-07-16T00:02:00+00:00",
        )

        assert paused.status is CampaignStatus.PAUSED
        assert paused.updated_at == "2026-07-16T00:01:00+00:00"
        assert resumed.status is CampaignStatus.RUNNING
        assert resumed.updated_at == "2026-07-16T00:02:00+00:00"
        assert resumed.created_at == paused.created_at
        assert resumed.kind == paused.kind
        assert resumed.policy_digest == paused.policy_digest
        assert resumed.schema_digest == paused.schema_digest
        assert store.read_manifest("campaign_1") == resumed
    finally:
        lock.release()


def test_pause_and_resume_are_idempotent_without_rewriting_time(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        running = store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.RUNNING,
            at="2026-07-16T00:00:30+00:00",
        )
        paused = store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:00+00:00",
        )
        paused_again = store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:30+00:00",
        )

        assert running.updated_at == "2026-07-16T00:00:00+00:00"
        assert paused_again == paused
        assert store.read_manifest("campaign_1") == paused
    finally:
        lock.release()


def test_pause_transition_rejects_time_regression_and_other_statuses(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:00+00:00",
        )
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_PAUSE_INVALID"):
            store.transition_pause_state(
                "campaign_1",
                status=CampaignStatus.RUNNING,
                at="2026-07-16T00:00:59+00:00",
            )
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_PAUSE_INVALID"):
            store.transition_pause_state(
                "campaign_1",
                status=CampaignStatus.COMPLETED,
                at="2026-07-16T00:02:00+00:00",
            )
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_PAUSE_INVALID"):
            store.transition_pause_state(
                "campaign_1",
                status=CampaignStatus.RUNNING,
                at="2026-07-16T00:02:00",
            )
        assert store.read_manifest("campaign_1").status is CampaignStatus.PAUSED
    finally:
        lock.release()


def test_pause_transition_requires_the_store_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    lock.release()

    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:00+00:00",
        )
