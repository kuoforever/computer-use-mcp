from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    MAX_CAMPAIGN_HANDOFF_BYTES,
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
    campaign_dir,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock, Path]:
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
    path = campaign_dir(store.state_dir, "campaign_1") / "handoff.json"
    return store, lock, path


def test_handoff_round_trips_only_after_current_state_validation(tmp_path: Path) -> None:
    store, lock, _path = _store(tmp_path)
    try:
        written = store.write_handoff("campaign_1", last_run_id="run_1")

        assert store.read_handoff("campaign_1") == written
    finally:
        lock.release()


def test_manifest_status_drift_invalidates_handoff_until_rewritten(tmp_path: Path) -> None:
    store, lock, _path = _store(tmp_path)
    try:
        store.write_handoff("campaign_1", last_run_id="run_1")
        store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:00+00:00",
        )

        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_INVALID"):
            store.read_handoff("campaign_1")

        rewritten = store.write_handoff("campaign_1", last_run_id="run_1")
        assert store.read_handoff("campaign_1") == rewritten
        assert rewritten["next_action"] == "wait_for_resume"
    finally:
        lock.release()


def test_ledger_drift_invalidates_handoff_until_rewritten(tmp_path: Path) -> None:
    store, lock, _path = _store(tmp_path)
    try:
        store.write_handoff("campaign_1", last_run_id="run_1")
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                1,
                "item_1",
                ItemStatus.DISCOVERED,
                0,
                "2026-07-16T00:01:00+00:00",
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
                "2026-07-16T00:01:00+00:00",
                run_id="run_1",
                lease_expires_at="2026-07-16T00:11:00+00:00",
                boundary="claim",
            ),
        )
        store.append(
            "campaign_1",
            ItemTransition(
                3,
                1,
                "item_1",
                ItemStatus.OBSERVED,
                1,
                "2026-07-16T00:02:00+00:00",
                run_id="run_1",
                boundary="identity_verified",
            ),
        )
        store.append(
            "campaign_1",
            ItemTransition(
                4,
                1,
                "item_1",
                ItemStatus.RETRYABLE,
                1,
                "2026-07-16T00:03:00+00:00",
                run_id="run_1",
                boundary="read_only_retry",
                code="RETRY",
            ),
        )

        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_INVALID"):
            store.read_handoff("campaign_1")

        rewritten = store.write_handoff("campaign_1", last_run_id="run_1")
        assert store.read_handoff("campaign_1") == rewritten
        assert rewritten["next_item_ordinal"] == 1
        assert rewritten["retryable_count"] == 1
    finally:
        lock.release()


def test_handoff_reader_rejects_extra_malformed_and_oversized_state(tmp_path: Path) -> None:
    store, lock, path = _store(tmp_path)
    try:
        handoff = store.write_handoff("campaign_1", last_run_id="run_1")
        path.write_text(json.dumps({**handoff, "extra": True}), encoding="utf-8")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_INVALID"):
            store.read_handoff("campaign_1")

        path.write_text("{", encoding="utf-8")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_INVALID"):
            store.read_handoff("campaign_1")

        path.write_bytes(b"x" * (MAX_CAMPAIGN_HANDOFF_BYTES + 1))
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_READ_FAILED"):
            store.read_handoff("campaign_1")
    finally:
        lock.release()


def test_handoff_reader_requires_file_and_store_run_lock(tmp_path: Path) -> None:
    store, lock, _path = _store(tmp_path)
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_READ_FAILED"):
        store.read_handoff("campaign_1")

    lock.release()
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        store.read_handoff("campaign_1")
