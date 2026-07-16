from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    MAX_CAMPAIGN_HEARTBEAT_BYTES,
    MAX_HEARTBEAT_FRESHNESS_SECONDS,
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    CampaignStoreError,
    campaign_dir,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
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
    return store, lock


def _heartbeat(
    *,
    run_id: str = "run_1",
    started_at: str = "2026-07-16T00:00:00+00:00",
    heartbeat_at: str = "2026-07-16T00:01:00+00:00",
    fresh_until: str = "2026-07-16T00:06:00+00:00",
) -> CampaignHeartbeat:
    return CampaignHeartbeat(
        campaign_id="campaign_1",
        run_id=run_id,
        started_at=started_at,
        heartbeat_at=heartbeat_at,
        fresh_until=fresh_until,
    )


def test_heartbeat_is_fixed_bounded_and_advances_for_the_same_run(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        first = _heartbeat()
        second = _heartbeat(
            heartbeat_at="2026-07-16T00:02:00+00:00",
            fresh_until="2026-07-16T00:07:00+00:00",
        )

        assert store.write_heartbeat("campaign_1", first) == first
        assert store.write_heartbeat("campaign_1", second) == second
        assert store.read_heartbeat("campaign_1") == second

        path = campaign_dir(store.state_dir, "campaign_1") / "heartbeat.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert set(payload) == {
            "campaign_version",
            "campaign_id",
            "run_id",
            "started_at",
            "heartbeat_at",
            "fresh_until",
        }
        assert "task" not in path.read_text(encoding="utf-8")
    finally:
        lock.release()


def test_heartbeat_write_is_idempotent_but_rejects_regression_or_owner_change(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        current = _heartbeat()
        store.write_heartbeat("campaign_1", current)
        assert store.write_heartbeat("campaign_1", current) == current

        for invalid in (
            _heartbeat(
                heartbeat_at="2026-07-16T00:00:30+00:00",
                fresh_until="2026-07-16T00:05:30+00:00",
            ),
            _heartbeat(run_id="run_2"),
            _heartbeat(started_at="2026-07-15T23:59:00+00:00"),
            _heartbeat(fresh_until="2026-07-16T00:05:00+00:00"),
        ):
            with pytest.raises(CampaignStoreError, match="CAMPAIGN_HEARTBEAT_CONFLICT"):
                store.write_heartbeat("campaign_1", invalid)
        assert store.read_heartbeat("campaign_1") == current
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("started_at", "heartbeat_at", "fresh_until"),
    [
        (
            "2026-07-16T00:02:00+00:00",
            "2026-07-16T00:01:00+00:00",
            "2026-07-16T00:06:00+00:00",
        ),
        (
            "2026-07-16T00:00:00+00:00",
            "2026-07-16T00:01:00+00:00",
            "2026-07-16T00:01:00+00:00",
        ),
        (
            "2026-07-16T00:00:00+00:00",
            "2026-07-16T00:01:00+00:00",
            "2026-07-16T00:06:01+00:00",
        ),
        (
            "2026-07-16T00:00:00",
            "2026-07-16T00:01:00",
            "2026-07-16T00:06:00",
        ),
    ],
)
def test_heartbeat_rejects_invalid_or_overlong_freshness(
    started_at: str, heartbeat_at: str, fresh_until: str
) -> None:
    assert MAX_HEARTBEAT_FRESHNESS_SECONDS == 300
    with pytest.raises(CampaignStoreError):
        _heartbeat(
            started_at=started_at,
            heartbeat_at=heartbeat_at,
            fresh_until=fresh_until,
        )


def test_heartbeat_requires_run_lock_and_valid_campaign_identity(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    lock.release()
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        store.write_heartbeat("campaign_1", _heartbeat())

    lock.acquire()
    try:
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HEARTBEAT_INVALID"):
            store.write_heartbeat("campaign_other", _heartbeat())
    finally:
        lock.release()


def test_heartbeat_reader_rejects_malformed_and_oversized_state(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        path = campaign_dir(store.state_dir, "campaign_1") / "heartbeat.json"
        path.write_text("{}", encoding="utf-8")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HEARTBEAT_INVALID"):
            store.read_heartbeat("campaign_1")

        path.write_bytes(b"x" * (MAX_CAMPAIGN_HEARTBEAT_BYTES + 1))
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HEARTBEAT_READ_FAILED"):
            store.read_heartbeat("campaign_1")
    finally:
        lock.release()
