from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    BatchStatus,
    BatchTransition,
    CampaignManifest,
    CampaignStore,
    CampaignStoreError,
    campaign_dir,
    reduce_batch_ledger,
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


def _batch(
    status: BatchStatus, *, code: str | None = None, run_id: str = "run_1", **values: object
) -> BatchTransition:
    return BatchTransition(
        sequence=999,
        batch_id="batch_1",
        run_id=run_id,
        status=status,
        at="2026-07-15T00:00:00+00:00",
        stop_code=code,
        **values,  # type: ignore[arg-type]
    )


def test_batch_records_are_fixed_schema_append_only_and_recover_active_state(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        started = store.append_batch("campaign_1", _batch(BatchStatus.STARTED))
        finished = store.append_batch(
            "campaign_1",
            _batch(
                BatchStatus.FINISHED,
                code="ITEM_LIMIT",
                items_completed=20,
                elapsed_seconds=100,
                provider_turns=4,
                tool_calls=12,
            ),
        )
        active = store.append_batch(
            "campaign_1",
            BatchTransition(
                sequence=999,
                batch_id="batch_2",
                run_id="run_2",
                status=BatchStatus.STARTED,
                at="2026-07-15T00:01:00+00:00",
            ),
        )

        path = campaign_dir((tmp_path / "state").resolve(), "campaign_1") / "batches.jsonl"
        assert [event.sequence for event in started.transitions] == [1]
        assert finished.finished_count == 1
        assert active.active is not None and active.active.batch_id == "batch_2"
        assert store.read_batches("campaign_1") == active
        assert set(json.loads(path.read_text(encoding="utf-8").splitlines()[1])) == set(
            _batch(BatchStatus.FINISHED, code="ITEM_LIMIT").as_json()
        )
    finally:
        lock.release()


def test_batch_reducer_rejects_overlapping_or_mismatched_lifecycle() -> None:
    started = _batch(BatchStatus.STARTED)
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_BATCH_LEDGER_INVALID"):
        reduce_batch_ledger((started, _batch(BatchStatus.STARTED)))
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_BATCH_LEDGER_INVALID"):
        reduce_batch_ledger((started, _batch(BatchStatus.FINISHED, code="ITEM_LIMIT", run_id="run_2")))


@pytest.mark.parametrize(
    ("status", "code", "counters"),
    [
        (BatchStatus.STARTED, "ITEM_LIMIT", {}),
        (BatchStatus.STARTED, None, {"tool_calls": 1}),
        (BatchStatus.FINISHED, None, {}),
        (BatchStatus.FINISHED, "bad code", {}),
    ],
)
def test_batch_transition_rejects_ambiguous_start_or_finish(
    status: BatchStatus, code: str | None, counters: dict[str, int]
) -> None:
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_INVALID"):
        _batch(status, code=code, **counters)


def test_corrupt_batch_ledger_fails_closed(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        path = campaign_dir((tmp_path / "state").resolve(), "campaign_1") / "batches.jsonl"
        path.write_text("not-json\n", encoding="utf-8")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_BATCH_LEDGER_INVALID"):
            store.read_batches("campaign_1")
    finally:
        lock.release()
