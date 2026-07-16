from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.batching import BatchPolicy, BatchStopReason
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_resume import CampaignResumeState
from computer_use_agent.campaign_resume_planning import (
    CampaignResumePlanningError,
    plan_campaign_resume,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _store(
    tmp_path: Path,
    *,
    status: CampaignStatus = CampaignStatus.RUNNING,
    item_ordinals: tuple[int, ...] = (),
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
    for sequence, ordinal in enumerate(item_ordinals, start=1):
        store.append(
            "campaign_1",
            ItemTransition(
                sequence,
                ordinal,
                f"item_{ordinal}",
                ItemStatus.DISCOVERED,
                0,
                "2026-07-16T00:01:00+00:00",
            ),
        )
    store.write_heartbeat(
        "campaign_1",
        CampaignHeartbeat(
            campaign_id="campaign_1",
            run_id="run_new",
            started_at="2026-07-16T00:00:00+00:00",
            heartbeat_at="2026-07-16T00:08:00+00:00",
            fresh_until="2026-07-16T00:12:00+00:00",
        ),
    )
    store.write_handoff("campaign_1", last_run_id="run_old")
    return store, lock


def test_ready_preflight_produces_bounded_stable_plan_without_writes(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path, item_ordinals=(2, 1, 3))
    try:
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")

        planned = plan_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(max_items=2),
        )

        assert planned.preflight.state is CampaignResumeState.READY
        assert planned.batch is not None
        assert planned.batch.item_keys == ("item_1", "item_2")
        assert planned.batch.stop_reason is None
        assert planned.has_nonempty_plan
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_ready_preflight_with_no_eligible_items_returns_empty_plan(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        planned = plan_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )

        assert planned.preflight.state is CampaignResumeState.READY
        assert planned.batch is not None
        assert planned.batch.item_keys == ()
        assert planned.batch.stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS
        assert planned.has_nonempty_plan is False
    finally:
        lock.release()


def test_blocked_preflight_never_selects_items(tmp_path: Path) -> None:
    store, lock = _store(
        tmp_path,
        status=CampaignStatus.PAUSED,
        item_ordinals=(1, 2),
    )
    try:
        planned = plan_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )

        assert planned.preflight.state is CampaignResumeState.HANDOFF_NOT_RESUMABLE
        assert planned.batch is None
        assert planned.has_nonempty_plan is False
    finally:
        lock.release()


def test_resume_planning_requires_policy_and_store_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path, item_ordinals=(1,))
    with pytest.raises(CampaignResumePlanningError, match="BatchPolicy"):
        plan_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
            policy=object(),  # type: ignore[arg-type]
        )

    lock.release()
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        plan_campaign_resume(
            store,
            campaign_id="campaign_1",
            run_id="run_new",
            now=NOW,
            policy=BatchPolicy(),
        )
