from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.batching import BatchPolicy, BatchUsage
from computer_use_agent.batch_coordinator import BatchCoordinator, BatchSession
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
    campaign_dir,
)
from computer_use_agent.campaign_item_progress import (
    CampaignItemProgressError,
    record_item_committed,
    record_item_extracted,
    record_item_observed,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
CONTENT_DIGEST = "b" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _claimed_store(tmp_path: Path) -> tuple[CampaignStore, RunLock, BatchSession]:
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
    return store, lock, opened


def _record(store: CampaignStore, **overrides: object) -> ItemTransition:
    arguments: dict[str, object] = {
        "campaign_id": "campaign_1",
        "batch_id": "batch_1",
        "run_id": "run_1",
        "item_key": "item_1",
        "now": NOW,
        "application_state_verified": True,
        "item_identity_verified": True,
        **overrides,
    }
    return record_item_observed(store, **arguments)  # type: ignore[arg-type]


def _extract(store: CampaignStore, **overrides: object) -> ItemTransition:
    arguments: dict[str, object] = {
        "campaign_id": "campaign_1",
        "batch_id": "batch_1",
        "run_id": "run_1",
        "item_key": "item_1",
        "now": NOW,
        "read_only_extraction_completed": True,
        **overrides,
    }
    return record_item_extracted(store, **arguments)  # type: ignore[arg-type]


def _commit(store: CampaignStore, **overrides: object) -> ItemTransition:
    arguments: dict[str, object] = {
        "campaign_id": "campaign_1",
        "batch_id": "batch_1",
        "run_id": "run_1",
        "item_key": "item_1",
        "now": NOW,
        "bounded_result_verified": True,
        "content_digest": CONTENT_DIGEST,
        **overrides,
    }
    return record_item_committed(store, **arguments)  # type: ignore[arg-type]


def test_confirmed_observation_appends_only_the_fixed_observed_boundary(
    tmp_path: Path,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        manifest_before = store.read_manifest("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        batches_before = store.read_batches("campaign_1")

        observed = _record(store)

        assert observed.status is ItemStatus.OBSERVED
        assert observed.attempt == 1
        assert observed.run_id == "run_1"
        assert observed.boundary == "reobserved"
        assert observed.code == "APPLICATION_AND_ITEM_VERIFIED"
        assert observed.lease_expires_at is None
        assert store.read_manifest("campaign_1") == manifest_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()

@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("application_state_verified", False),
        ("item_identity_verified", False),
        ("application_state_verified", 1),
    ],
)
def test_both_exact_observation_attestations_are_required_without_mutation(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(CampaignItemProgressError, match="ITEM_OBSERVATION_REQUIRED"):
            _record(store, **{field: value})
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_stale_lease_or_repeated_observation_is_never_written(tmp_path: Path) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
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
        stale_now = datetime(2026, 7, 16, 0, 15, tzinfo=timezone.utc)
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(
            CampaignItemProgressError,
            match="ITEM_OBSERVATION_BLOCKED_CLAIM_LEASE_STALE",
        ):
            _record(store, now=stale_now)
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()

    store, lock, _opened = _claimed_store(tmp_path / "repeated")
    try:
        _record(store)
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(
            CampaignItemProgressError,
            match="ITEM_OBSERVATION_BLOCKED_ITEM_NOT_CLAIMED",
        ):
            _record(store)
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_confirmed_read_only_extraction_appends_only_the_fixed_boundary(
    tmp_path: Path,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        manifest_before = store.read_manifest("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        batches_before = store.read_batches("campaign_1")

        extracted = _extract(store)

        assert extracted.status is ItemStatus.EXTRACTED
        assert extracted.attempt == 1
        assert extracted.run_id == "run_1"
        assert extracted.boundary == "extracted"
        assert extracted.code == "READ_ONLY_EXTRACTION_COMPLETED"
        assert extracted.content_digest is None
        assert store.read_manifest("campaign_1") == manifest_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


@pytest.mark.parametrize("confirmation", [False, 1, None])
def test_exact_read_only_extraction_confirmation_is_required_without_mutation(
    tmp_path: Path,
    confirmation: object,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(CampaignItemProgressError, match="ITEM_EXTRACTION_REQUIRED"):
            _extract(store, read_only_extraction_completed=confirmation)

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_repeated_extraction_is_never_written(tmp_path: Path) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        _extract(store)
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(
            CampaignItemProgressError,
            match="ITEM_EXTRACTION_BLOCKED_ITEM_NOT_OBSERVED",
        ):
            _extract(store)

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_verified_result_appends_only_fixed_commit_and_advances_projection_cursor(
    tmp_path: Path,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        _extract(store)
        store.write_handoff("campaign_1", last_run_id="run_1")
        handoff_path = campaign_dir(store.state_dir, "campaign_1") / "handoff.json"
        handoff_before = handoff_path.read_bytes()
        manifest_before = store.read_manifest("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        batches_before = store.read_batches("campaign_1")

        committed = _commit(store)
        projection = store.read_ledger("campaign_1")

        assert committed.status is ItemStatus.COMMITTED
        assert committed.attempt == 1
        assert committed.run_id == "run_1"
        assert committed.boundary == "result_verified"
        assert committed.code == "READ_ONLY_RESULT_VERIFIED"
        assert committed.content_digest == CONTENT_DIGEST
        assert projection.completed_count == 1
        assert projection.next_ordinal == 2
        assert store.read_manifest("campaign_1") == manifest_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_batches("campaign_1") == batches_before
        assert handoff_path.read_bytes() == handoff_before
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_HANDOFF_INVALID"):
            store.read_handoff("campaign_1")
    finally:
        lock.release()


@pytest.mark.parametrize("confirmation", [False, 1, None])
def test_exact_result_verification_is_required_without_mutation(
    tmp_path: Path,
    confirmation: object,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        _extract(store)
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(
            CampaignItemProgressError,
            match="ITEM_COMMIT_VERIFICATION_REQUIRED",
        ):
            _commit(store, bounded_result_verified=confirmation)

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


@pytest.mark.parametrize("digest", ["b" * 63, "B" * 64, 1, None])
def test_commit_requires_exact_sha256_digest_without_mutation(
    tmp_path: Path,
    digest: object,
) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        _extract(store)
        ledger_before = store.read_ledger("campaign_1")

        with pytest.raises(CampaignItemProgressError, match="ITEM_COMMIT_DIGEST_INVALID"):
            _commit(store, content_digest=digest)

        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_stale_or_repeated_commit_is_never_written(tmp_path: Path) -> None:
    store, lock, _opened = _claimed_store(tmp_path)
    try:
        _record(store)
        _extract(store)
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(
            CampaignItemProgressError,
            match="ITEM_COMMIT_BLOCKED_HEARTBEAT_STALE",
        ):
            _commit(
                store,
                now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()

    store, lock, _opened = _claimed_store(tmp_path / "repeated")
    try:
        _record(store)
        _extract(store)
        _commit(store)
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(
            CampaignItemProgressError,
            match="ITEM_COMMIT_BLOCKED_ITEM_NOT_EXTRACTED",
        ):
            _commit(store)
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()
