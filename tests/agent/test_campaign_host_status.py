from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
    campaign_dir,
)
from computer_use_agent.campaign_host_status import (
    CampaignHostStatus,
    HostEventKind,
    HostPollState,
    HostStatusProjectionError,
    HostTaskStatus,
    evaluate_host_poll,
    project_campaign_host_status,
)
from computer_use_agent.run_lock import RunLock


NOW = datetime(2026, 7, 19, 1, 0, tzinfo=timezone.utc)
DIGEST = "a" * 64


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    store.create(
        CampaignManifest(
            campaign_id="campaign_1",
            kind="synthetic",
            policy_digest=DIGEST,
            schema_digest=DIGEST,
            created_at="2026-07-19T00:00:00+00:00",
            updated_at="2026-07-19T00:00:00+00:00",
        )
    )
    return store, lock


def _heartbeat(*, fresh: bool) -> CampaignHeartbeat:
    return CampaignHeartbeat(
        campaign_id="campaign_1",
        run_id="run_1",
        started_at="2026-07-19T00:00:00+00:00",
        heartbeat_at=("2026-07-19T00:59:00+00:00" if fresh else "2026-07-19T00:30:00+00:00"),
        fresh_until=("2026-07-19T01:04:00+00:00" if fresh else "2026-07-19T00:35:00+00:00"),
    )


def _append_item(store: CampaignStore, status: ItemStatus) -> None:
    transitions = [
        ItemTransition(1, 1, "item_1", ItemStatus.DISCOVERED, 0, "2026-07-19T00:10:00+00:00"),
        ItemTransition(
            2,
            1,
            "item_1",
            ItemStatus.CLAIMED,
            1,
            "2026-07-19T00:11:00+00:00",
            "run_1",
            "2026-07-19T00:40:00+00:00",
            "claim",
        ),
        ItemTransition(
            3,
            1,
            "item_1",
            ItemStatus.OBSERVED,
            1,
            "2026-07-19T00:12:00+00:00",
            "run_1",
            None,
            "identity_verified",
        ),
    ]
    if status is ItemStatus.COMMITTED:
        transitions.extend(
            [
                ItemTransition(
                    4,
                    1,
                    "item_1",
                    ItemStatus.EXTRACTED,
                    1,
                    "2026-07-19T00:13:00+00:00",
                    "run_1",
                    None,
                    "read_only_extract",
                ),
                ItemTransition(
                    5,
                    1,
                    "item_1",
                    ItemStatus.COMMITTED,
                    1,
                    "2026-07-19T00:14:00+00:00",
                    "run_1",
                    None,
                    "result_verified",
                    "OK",
                    "b" * 64,
                ),
            ]
        )
    else:
        transitions.append(
            ItemTransition(
                4,
                1,
                "item_1",
                status,
                1,
                "2026-07-19T00:13:00+00:00",
                "run_1",
                None,
                "unknown_outcome",
                "UNKNOWN",
            )
        )
    for transition in transitions:
        store.append("campaign_1", transition)


def test_running_projection_is_bounded_and_emits_nothing(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        store.write_heartbeat("campaign_1", _heartbeat(fresh=True))
        projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)
        decision = evaluate_host_poll(projection)

        assert projection == CampaignHostStatus(
            campaign_id="campaign_1",
            status=HostTaskStatus.RUNNING,
            discovered_count=0,
            completed_count=0,
            retryable_count=0,
            uncertain_count=0,
            last_checkpoint_at="2026-07-19T00:59:00+00:00",
        )
        assert decision.event_kind is HostEventKind.NONE
        assert decision.should_continue_polling
        assert not decision.emitted
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("status", "expected_event"),
    [
        (HostTaskStatus.WAITING_APPROVAL, HostEventKind.NEEDS_ATTENTION),
        (HostTaskStatus.PAUSED, HostEventKind.NEEDS_ATTENTION),
        (HostTaskStatus.CHALLENGE, HostEventKind.NEEDS_ATTENTION),
        (HostTaskStatus.STALE, HostEventKind.NEEDS_ATTENTION),
        (HostTaskStatus.NEEDS_INSPECTION, HostEventKind.NEEDS_ATTENTION),
        (HostTaskStatus.UNCERTAIN, HostEventKind.UNCERTAIN),
        (HostTaskStatus.FAILED, HostEventKind.FAILED),
        (HostTaskStatus.CANCELLED, HostEventKind.FAILED),
    ],
)
def test_nonrunning_states_never_emit_completion(
    status: HostTaskStatus, expected_event: HostEventKind
) -> None:
    projection = CampaignHostStatus("campaign_1", status, 1, 0, 0, 0, NOW.isoformat(), "CODE")

    decision = evaluate_host_poll(projection)

    assert decision.event_kind is expected_event
    assert decision.event_kind is not HostEventKind.COMPLETED
    assert not decision.should_continue_polling


def test_completed_projection_emits_exactly_once_across_host_restart(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        _append_item(store, ItemStatus.COMMITTED)
        store.complete_campaign("campaign_1", at="2026-07-19T00:20:00+00:00")
        store.write_handoff("campaign_1", last_run_id="run_2")

        projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)
        first = evaluate_host_poll(projection)
        restarted_state = HostPollState(frozenset(first.state.emitted_event_ids))
        second = evaluate_host_poll(
            project_campaign_host_status(store, campaign_id="campaign_1", now=NOW),
            restarted_state,
        )

        assert projection.status is HostTaskStatus.COMPLETED
        assert projection.completed_count == projection.discovered_count == 1
        assert first.event_kind is HostEventKind.COMPLETED
        assert first.emitted
        assert second.event_kind is HostEventKind.NONE
        assert not second.emitted
        assert not second.should_continue_polling
    finally:
        lock.release()


def test_uncertain_and_stale_durable_state_fail_closed(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        _append_item(store, ItemStatus.UNCERTAIN)
        store.write_heartbeat("campaign_1", _heartbeat(fresh=False))

        projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)

        assert projection.status is HostTaskStatus.UNCERTAIN
        assert projection.uncertain_count == 1
        assert evaluate_host_poll(projection).event_kind is HostEventKind.UNCERTAIN
    finally:
        lock.release()


def test_stale_heartbeat_requests_attention_without_completion(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        store.write_heartbeat("campaign_1", _heartbeat(fresh=False))

        projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)
        decision = evaluate_host_poll(projection)

        assert projection.status is HostTaskStatus.STALE
        assert decision.event_kind is HostEventKind.NEEDS_ATTENTION
        assert decision.event_kind is not HostEventKind.COMPLETED
    finally:
        lock.release()


def test_completed_manifest_without_valid_handoff_cannot_complete(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        _append_item(store, ItemStatus.COMMITTED)
        store.complete_campaign("campaign_1", at="2026-07-19T00:20:00+00:00")

        projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)
        decision = evaluate_host_poll(projection)

        assert projection.status is HostTaskStatus.NEEDS_INSPECTION
        assert decision.event_kind is HostEventKind.NEEDS_ATTENTION
        assert decision.event_kind is not HostEventKind.COMPLETED
    finally:
        lock.release()


def test_missing_or_malformed_state_returns_inspection_not_completion(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        directory = campaign_dir(store.state_dir, "campaign_1")
        (directory / "manifest.json").write_text("{}", encoding="utf-8")

        projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)

        assert projection.status is HostTaskStatus.NEEDS_INSPECTION
        assert projection.attention_code == "CAMPAIGN_STATE_INVALID"
        assert evaluate_host_poll(projection).event_kind is HostEventKind.NEEDS_ATTENTION
    finally:
        lock.release()


def test_projection_requires_the_existing_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    lock.release()

    with pytest.raises(HostStatusProjectionError, match="HOST_STATUS_LOCK_REQUIRED"):
        project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)


def test_repeated_polling_is_read_only(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        store.write_heartbeat("campaign_1", _heartbeat(fresh=True))
        directory = campaign_dir(store.state_dir, "campaign_1")
        before = {path.name: path.read_bytes() for path in directory.iterdir()}

        for _ in range(3):
            projection = project_campaign_host_status(store, campaign_id="campaign_1", now=NOW)
            assert evaluate_host_poll(projection).should_continue_polling

        after = {path.name: path.read_bytes() for path in directory.iterdir()}
        assert after == before
    finally:
        lock.release()
