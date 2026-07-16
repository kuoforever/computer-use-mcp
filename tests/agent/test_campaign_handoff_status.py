from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    campaign_dir,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64


def _store(tmp_path: Path, *, status: CampaignStatus) -> tuple[CampaignStore, RunLock]:
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
    return store, lock


@pytest.mark.parametrize(
    ("status", "next_action", "required_observation"),
    [
        (
            CampaignStatus.RUNNING,
            "resume_batch",
            "verify_current_page_and_account_state",
        ),
        (
            CampaignStatus.PAUSED,
            "wait_for_resume",
            "none_until_resumed",
        ),
        (
            CampaignStatus.CHALLENGE,
            "wait_for_challenge_resolution",
            "resolve_challenge_then_reobserve",
        ),
        (
            CampaignStatus.COMPLETED,
            "none_completed",
            "none",
        ),
        (
            CampaignStatus.FAILED,
            "human_review_failed",
            "review_failure_before_any_resume",
        ),
    ],
)
def test_handoff_directives_are_derived_from_manifest_status(
    tmp_path: Path,
    status: CampaignStatus,
    next_action: str,
    required_observation: str,
) -> None:
    store, lock = _store(tmp_path, status=status)
    try:
        handoff = store.write_handoff("campaign_1", last_run_id="run_1")
        path = campaign_dir(store.state_dir, "campaign_1") / "handoff.json"

        assert handoff["next_action"] == next_action
        assert handoff["required_observation"] == required_observation
        assert json.loads(path.read_text(encoding="utf-8")) == handoff
    finally:
        lock.release()


def test_pause_and_resume_rewrite_only_the_fixed_handoff_directive(tmp_path: Path) -> None:
    store, lock = _store(tmp_path, status=CampaignStatus.RUNNING)
    try:
        running = store.write_handoff("campaign_1", last_run_id="run_1")
        store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.PAUSED,
            at="2026-07-16T00:01:00+00:00",
        )
        paused = store.write_handoff("campaign_1", last_run_id="run_1")
        store.transition_pause_state(
            "campaign_1",
            status=CampaignStatus.RUNNING,
            at="2026-07-16T00:02:00+00:00",
        )
        resumed = store.write_handoff("campaign_1", last_run_id="run_1")

        stable_fields = {
            "campaign_id",
            "campaign_version",
            "next_item_ordinal",
            "completed_count",
            "retryable_count",
            "uncertain_count",
            "last_run_id",
        }
        assert {key: running[key] for key in stable_fields} == {
            key: paused[key] for key in stable_fields
        }
        assert paused["next_action"] == "wait_for_resume"
        assert resumed["next_action"] == "resume_batch"
        assert resumed["required_observation"] == "verify_current_page_and_account_state"
    finally:
        lock.release()
