from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.batch_coordinator import (
    BatchContinuationState,
    BatchCoordinator,
    BatchCoordinatorError,
    BatchHandoffState,
    BatchRunTransferState,
    BatchSession,
)
from computer_use_agent.batching import BatchPlan, BatchPolicy, BatchStopReason, BatchUsage
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_item_progress import (
    record_item_committed,
    record_item_extracted,
    record_item_observed,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
CONTENT_DIGEST = "b" * 64
NOW = datetime(2026, 7, 16, 0, 10, tzinfo=timezone.utc)


def _committed_prefix_store(
    tmp_path: Path,
    *,
    ordinals: tuple[int, ...] = (1, 2),
    max_items: int = 2,
    commit_first: bool = True,
) -> tuple[CampaignStore, RunLock, BatchCoordinator, BatchSession]:
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
    for ordinal in ordinals:
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                ordinal,
                f"item_{ordinal}",
                ItemStatus.DISCOVERED,
                0,
                f"2026-07-16T00:0{ordinal}:00+00:00",
            ),
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
        policy=BatchPolicy(max_items=max_items),
    )
    assert isinstance(opened, BatchSession)
    if commit_first:
        first_key = opened.plan.item_keys[0]
        coordinator.claim_first_item(opened, now=NOW, lease_seconds=300)
        record_item_observed(
            store,
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_1",
            item_key=first_key,
            now=NOW,
            application_state_verified=True,
            item_identity_verified=True,
        )
        record_item_extracted(
            store,
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_1",
            item_key=first_key,
            now=NOW,
            read_only_extraction_completed=True,
        )
        record_item_committed(
            store,
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_1",
            item_key=first_key,
            now=NOW,
            bounded_result_verified=True,
            content_digest=CONTENT_DIGEST,
        )
    return store, lock, coordinator, opened


def test_committed_prefix_is_ready_only_for_exact_next_planned_claim(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")

        result = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )

        assert result.state is BatchContinuationState.READY
        assert result.ready
        assert result.completed_items == 1
        assert result.next_item_key == "item_2"
        assert result.next_item_ordinal == 2
        assert result.stop_reason is None
        assert result.required_claim == "claim_exact_next_planned_item"
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_continuation_requires_a_nonempty_committed_prefix(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        commit_first=False,
    )
    try:
        ledger_before = store.read_ledger("campaign_1")

        result = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(),
            now=NOW,
        )

        assert result.state is BatchContinuationState.COMMITTED_PREFIX_REQUIRED
        assert not result.ready
        assert result.next_item_key is None
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_ready_continuation_claims_only_the_exact_next_planned_item(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        manifest_before = store.read_manifest("campaign_1")
        batches_before = store.read_batches("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")

        claimed = coordinator.claim_next_item(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
            lease_seconds=300,
        )

        assert claimed.item_key == "item_2"
        assert claimed.ordinal == 2
        assert claimed.status is ItemStatus.CLAIMED
        assert claimed.attempt == 1
        assert claimed.run_id == "run_1"
        assert claimed.boundary == "claim"
        assert claimed.lease_expires_at == "2026-07-16T00:15:00+00:00"
        assert store.read_manifest("campaign_1") == manifest_before
        assert store.read_batches("campaign_1") == batches_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_repeated_or_limit_blocked_continuation_claim_never_writes(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.claim_next_item(session, usage=usage, now=NOW, lease_seconds=300)
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_CONTINUATION_BLOCKED_ITEMS_IN_FLIGHT",
        ):
            coordinator.claim_next_item(session, usage=usage, now=NOW, lease_seconds=300)
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()

    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "limited",
        max_items=1,
    )
    try:
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_CONTINUATION_BLOCKED_LIMIT_REACHED",
        ):
            coordinator.claim_next_item(
                session,
                usage=BatchUsage(items_completed=1),
                now=NOW,
                lease_seconds=300,
            )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


@pytest.mark.parametrize("lease_seconds", [0, 3601, True, "300"])
def test_continuation_claim_requires_a_bounded_lease_without_writes(
    tmp_path: Path,
    lease_seconds: object,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        with pytest.raises(BatchCoordinatorError, match="BATCH_LEASE_INVALID"):
            coordinator.claim_next_item(
                session,
                usage=BatchUsage(items_completed=1),
                now=NOW,
                lease_seconds=lease_seconds,  # type: ignore[arg-type]
            )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_usage_mismatch_or_stale_heartbeat_blocks_continuation_without_writes(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        ledger_before = store.read_ledger("campaign_1")
        assert (
            coordinator.inspect_continuation(session, usage=BatchUsage(), now=NOW).state
            is BatchContinuationState.USAGE_MISMATCH
        )
        assert (
            coordinator.inspect_continuation(
                session,
                usage=BatchUsage(items_completed=1),
                now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            ).state
            is BatchContinuationState.HEARTBEAT_STALE
        )
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_newly_discovered_earlier_item_is_plan_drift(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 3),
    )
    try:
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                2,
                "item_2",
                ItemStatus.DISCOVERED,
                0,
                "2026-07-16T00:09:00+00:00",
            ),
        )
        ledger_before = store.read_ledger("campaign_1")

        result = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )

        assert result.state is BatchContinuationState.PLAN_DRIFT
        assert not result.ready
        assert result.next_item_key is None
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_forged_session_cannot_omit_the_committed_prefix(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        forged = BatchSession(
            campaign_id=session.campaign_id,
            batch_id=session.batch_id,
            run_id=session.run_id,
            policy=session.policy,
            plan=BatchPlan(item_keys=("item_2",), stop_reason=None),
        )
        ledger_before = store.read_ledger("campaign_1")

        result = coordinator.inspect_continuation(
            forged,
            usage=BatchUsage(),
            now=NOW,
        )

        assert result.state is BatchContinuationState.PLAN_DRIFT
        assert not result.ready
        assert result.next_item_key is None
        assert store.read_ledger("campaign_1") == ledger_before
    finally:
        lock.release()


def test_forged_session_cannot_truncate_the_remaining_plan(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        forged = BatchSession(
            campaign_id=session.campaign_id,
            batch_id=session.batch_id,
            run_id=session.run_id,
            policy=session.policy,
            plan=BatchPlan(item_keys=("item_1",), stop_reason=None),
        )
        batches_before = store.read_batches("campaign_1")

        result = coordinator.inspect_continuation(
            forged,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )

        assert result.state is BatchContinuationState.PLAN_DRIFT
        assert not result.ready
        with pytest.raises(BatchCoordinatorError, match="BATCH_FINISH_BLOCKED_PLAN_DRIFT"):
            coordinator.finish_continued_batch(
                forged,
                usage=BatchUsage(items_completed=1),
                now=NOW,
            )
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_reached_limit_and_completed_plan_return_fixed_terminal_states(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 2),
        max_items=1,
    )
    try:
        limited = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )
        assert limited.state is BatchContinuationState.LIMIT_REACHED
        assert limited.stop_reason is BatchStopReason.ITEM_LIMIT
        assert limited.next_item_key is None
    finally:
        lock.release()


def test_continuation_validated_limit_finishes_with_exact_measured_usage(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 2),
        max_items=1,
    )
    try:
        ledger_before = store.read_ledger("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        usage = BatchUsage(
            items_completed=1,
            elapsed_seconds=30,
            provider_turns=2,
            tool_calls=4,
            input_tokens=100,
            output_tokens=20,
        )

        code = coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        finished = store.read_batches("campaign_1").transitions[-1]

        assert code == "ITEM_LIMIT"
        assert finished.status.value == "FINISHED"
        assert finished.stop_code == "ITEM_LIMIT"
        assert finished.at == "2026-07-16T00:10:00+00:00"
        assert finished.items_completed == 1
        assert finished.elapsed_seconds == 30
        assert finished.provider_turns == 2
        assert finished.tool_calls == 4
        assert finished.input_tokens == 100
        assert finished.output_tokens == 20
        assert store.read_batches("campaign_1").active is None
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_continuation_validated_complete_plan_finishes_without_handoff_write(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        campaign_path = store.state_dir / "campaigns" / "campaign_1"
        handoff_path = campaign_path / "handoff.json"

        code = coordinator.finish_continued_batch(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )

        assert code == "PLAN_COMPLETE"
        assert store.read_batches("campaign_1").transitions[-1].stop_code == "PLAN_COMPLETE"
        assert store.read_batches("campaign_1").active is None
        assert not handoff_path.exists()
    finally:
        lock.release()


def test_ready_inflight_or_repeated_finish_never_writes(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(tmp_path)
    try:
        batches_before = store.read_batches("campaign_1")
        with pytest.raises(BatchCoordinatorError, match="BATCH_FINISH_BLOCKED_READY"):
            coordinator.finish_continued_batch(
                session,
                usage=BatchUsage(items_completed=1),
                now=NOW,
            )
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_finished_plan_is_ready_only_for_fixed_handoff_write(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")
        handoff_path = store.state_dir / "campaigns" / "campaign_1" / "handoff.json"

        result = coordinator.inspect_finished_handoff(session, usage=usage, now=NOW)

        assert result.state is BatchHandoffState.READY
        assert result.ready
        assert result.completed_items == 1
        assert result.next_item_ordinal == 2
        assert result.stop_code == "PLAN_COMPLETE"
        assert result.required_handoff == "write_current_campaign_handoff"
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert not handoff_path.exists()
    finally:
        lock.release()


def test_finished_limit_preserves_next_item_for_handoff(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 2),
        max_items=1,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)

        result = coordinator.inspect_finished_handoff(session, usage=usage, now=NOW)

        assert result.state is BatchHandoffState.READY
        assert result.next_item_ordinal == 2
        assert result.stop_code == "ITEM_LIMIT"
    finally:
        lock.release()


def test_ready_finished_batch_writes_only_current_fixed_handoff(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        manifest_before = store.read_manifest("campaign_1")
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")
        heartbeat_before = store.read_heartbeat("campaign_1")

        written = coordinator.write_finished_handoff(session, usage=usage, now=NOW)

        assert written["campaign_id"] == "campaign_1"
        assert written["last_run_id"] == "run_1"
        assert written["next_item_ordinal"] == 2
        assert written["completed_count"] == 1
        assert written["retryable_count"] == 0
        assert written["uncertain_count"] == 0
        assert written["next_action"] == "resume_batch"
        assert written["required_observation"] == "verify_current_page_and_account_state"
        assert store.read_handoff("campaign_1") == written
        assert store.read_manifest("campaign_1") == manifest_before
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_limit_handoff_preserves_next_durable_item(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1, 2),
        max_items=1,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)

        written = coordinator.write_finished_handoff(session, usage=usage, now=NOW)

        assert written["next_item_ordinal"] == 2
        assert written["completed_count"] == 1
        assert store.read_handoff("campaign_1") == written
    finally:
        lock.release()


def test_blocked_finished_handoff_never_creates_or_replaces_state(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        handoff_path = store.state_dir / "campaigns" / "campaign_1" / "handoff.json"
        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_HANDOFF_BLOCKED_BATCH_STILL_ACTIVE",
        ):
            coordinator.write_finished_handoff(
                session,
                usage=BatchUsage(items_completed=1),
                now=NOW,
            )
        assert not handoff_path.exists()
    finally:
        lock.release()

    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "stale",
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        handoff_path = store.state_dir / "campaigns" / "campaign_1" / "handoff.json"
        handoff_path.write_bytes(b"existing-handoff-sentinel")
        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_HANDOFF_BLOCKED_HEARTBEAT_STALE",
        ):
            coordinator.write_finished_handoff(
                session,
                usage=usage,
                now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
            )
        assert handoff_path.read_bytes() == b"existing-handoff-sentinel"
    finally:
        lock.release()


def _replacement_heartbeat(
    *,
    campaign_id: str = "campaign_1",
    run_id: str = "run_2",
    started_at: str = "2026-07-16T00:10:00+00:00",
    heartbeat_at: str = "2026-07-16T00:10:00+00:00",
    fresh_until: str = "2026-07-16T00:15:00+00:00",
) -> CampaignHeartbeat:
    return CampaignHeartbeat(
        campaign_id=campaign_id,
        run_id=run_id,
        started_at=started_at,
        heartbeat_at=heartbeat_at,
        fresh_until=fresh_until,
    )


def test_finished_handoff_is_ready_for_exact_new_run_transfer(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        coordinator.write_finished_handoff(session, usage=usage, now=NOW)
        heartbeat_before = store.read_heartbeat("campaign_1")
        handoff_before = store.read_handoff("campaign_1")

        result = coordinator.inspect_finished_run_transfer(
            session,
            usage=usage,
            now=NOW,
            replacement=_replacement_heartbeat(),
        )

        assert result.state is BatchRunTransferState.READY
        assert result.ready
        assert result.finished_run_id == "run_1"
        assert result.replacement_run_id == "run_2"
        assert result.next_item_ordinal == 2
        assert result.required_transfer == "replace_finished_run_heartbeat_owner"
        assert store.read_heartbeat("campaign_1") == heartbeat_before
        assert store.read_handoff("campaign_1") == handoff_before
    finally:
        lock.release()


def test_ready_finished_run_transfer_atomically_replaces_only_heartbeat_owner(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        coordinator.write_finished_handoff(session, usage=usage, now=NOW)
        manifest_before = store.read_manifest("campaign_1")
        ledger_before = store.read_ledger("campaign_1")
        batches_before = store.read_batches("campaign_1")
        handoff_before = store.read_handoff("campaign_1")
        replacement = _replacement_heartbeat()

        transferred = coordinator.replace_finished_run_heartbeat_owner(
            session,
            usage=usage,
            now=NOW,
            replacement=replacement,
        )

        assert transferred == replacement
        assert store.read_heartbeat("campaign_1") == replacement
        assert store.read_manifest("campaign_1") == manifest_before
        assert store.read_ledger("campaign_1") == ledger_before
        assert store.read_batches("campaign_1") == batches_before
        assert store.read_handoff("campaign_1") == handoff_before
    finally:
        lock.release()


def test_blocked_finished_run_transfer_never_replaces_heartbeat(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        coordinator.write_finished_handoff(session, usage=usage, now=NOW)
        heartbeat_before = store.read_heartbeat("campaign_1")

        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_RUN_TRANSFER_BLOCKED_REPLACEMENT_RUN_REUSED",
        ):
            coordinator.replace_finished_run_heartbeat_owner(
                session,
                usage=usage,
                now=NOW,
                replacement=_replacement_heartbeat(run_id="run_1"),
            )

        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_finished_run_transfer_cannot_be_repeated(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        coordinator.write_finished_handoff(session, usage=usage, now=NOW)
        replacement = _replacement_heartbeat()
        coordinator.replace_finished_run_heartbeat_owner(
            session,
            usage=usage,
            now=NOW,
            replacement=replacement,
        )

        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_RUN_TRANSFER_BLOCKED_FINISHED_HANDOFF_NOT_READY",
        ):
            coordinator.replace_finished_run_heartbeat_owner(
                session,
                usage=usage,
                now=NOW,
                replacement=replacement,
            )

        assert store.read_heartbeat("campaign_1") == replacement
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("replacement", "state"),
    [
        (_replacement_heartbeat(run_id="run_1"), BatchRunTransferState.REPLACEMENT_RUN_REUSED),
        (
            _replacement_heartbeat(campaign_id="campaign_other"),
            BatchRunTransferState.REPLACEMENT_CAMPAIGN_MISMATCH,
        ),
        (
            _replacement_heartbeat(
                started_at="2026-07-16T00:09:00+00:00",
                heartbeat_at="2026-07-16T00:09:00+00:00",
                fresh_until="2026-07-16T00:14:00+00:00",
            ),
            BatchRunTransferState.REPLACEMENT_TIME_MISMATCH,
        ),
    ],
)
def test_reused_or_wrong_time_replacement_run_is_never_transferred(
    tmp_path: Path,
    replacement: CampaignHeartbeat,
    state: BatchRunTransferState,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        coordinator.write_finished_handoff(session, usage=usage, now=NOW)
        heartbeat_before = store.read_heartbeat("campaign_1")

        result = coordinator.inspect_finished_run_transfer(
            session,
            usage=usage,
            now=NOW,
            replacement=replacement,
        )

        assert result.state is state
        assert not result.ready
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_handoff_last_run_mismatch_blocks_clean_transfer(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        coordinator.write_finished_handoff(session, usage=usage, now=NOW)
        store.write_handoff("campaign_1", last_run_id="run_other")
        heartbeat_before = store.read_heartbeat("campaign_1")

        result = coordinator.inspect_finished_run_transfer(
            session,
            usage=usage,
            now=NOW,
            replacement=_replacement_heartbeat(),
        )

        assert result.state is BatchRunTransferState.HANDOFF_RUN_MISMATCH
        assert not result.ready
        assert store.read_heartbeat("campaign_1") == heartbeat_before
    finally:
        lock.release()


def test_active_batch_or_usage_drift_blocks_handoff_without_writes(tmp_path: Path) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path,
        ordinals=(1,),
        max_items=2,
    )
    try:
        batches_before = store.read_batches("campaign_1")
        assert (
            coordinator.inspect_finished_handoff(
                session,
                usage=BatchUsage(items_completed=1),
                now=NOW,
            ).state
            is BatchHandoffState.BATCH_STILL_ACTIVE
        )
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()

    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "stale",
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        batches_before = store.read_batches("campaign_1")

        result = coordinator.inspect_finished_handoff(
            session,
            usage=usage,
            now=datetime(2026, 7, 16, 0, 12, tzinfo=timezone.utc),
        )

        assert result.state is BatchHandoffState.HEARTBEAT_STALE
        assert not result.ready
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()

    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "usage",
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1, tool_calls=2)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        batches_before = store.read_batches("campaign_1")

        result = coordinator.inspect_finished_handoff(
            session,
            usage=BatchUsage(items_completed=1, tool_calls=3),
            now=NOW,
        )

        assert result.state is BatchHandoffState.FINISH_RECORD_MISMATCH
        assert not result.ready
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()


def test_repeated_finish_and_complete_continuation_states_are_stable(
    tmp_path: Path,
) -> None:
    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "repeated",
        ordinals=(1,),
        max_items=2,
    )
    try:
        usage = BatchUsage(items_completed=1)
        coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        batches_before = store.read_batches("campaign_1")
        with pytest.raises(
            BatchCoordinatorError,
            match="BATCH_FINISH_BLOCKED_BATCH_NOT_ACTIVE",
        ):
            coordinator.finish_continued_batch(session, usage=usage, now=NOW)
        assert store.read_batches("campaign_1") == batches_before
    finally:
        lock.release()

    store, lock, coordinator, session = _committed_prefix_store(
        tmp_path / "complete",
        ordinals=(1,),
        max_items=2,
    )
    try:
        complete = coordinator.inspect_continuation(
            session,
            usage=BatchUsage(items_completed=1),
            now=NOW,
        )
        assert complete.state is BatchContinuationState.PLAN_COMPLETE
        assert complete.stop_reason is None
        assert complete.next_item_key is None
    finally:
        lock.release()
