from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from computer_use_agent.boss_campaign_batch_runtime import (
    BOSS_BATCH_LEASE_SECONDS,
    BOSS_BATCH_POLICY,
    BossCampaignBatchRuntimeError,
    start_boss_read_only_batch,
)
from computer_use_agent.boss_campaign_discovery import (
    create_boss_discovery_campaign,
    record_boss_snapshot_discoveries,
)
from computer_use_agent.campaign import CampaignStore, ItemStatus
from computer_use_agent.config import AgentConfig, MCPLaunchConfig, PolicyConfig, ProviderConfig
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner


NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy_mode: str = "read_only",
) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=(local / "computer-use-agent" / "boss-batch").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "unused-boss-batch"),
        mcp=MCPLaunchConfig(
            tmp_path / "computer-use-mcp.exe",
            (),
            tmp_path,
            {"CUMCP_ALLOWLIST": "chrome.exe"},
        ),
        policy=PolicyConfig(
            mode=policy_mode,
            require_approval_for_actions=True,
            max_model_turns=0,
            max_tool_calls=0,
            max_side_effects=0,
        ),
    )


def _snapshot(*public_ids: str, marker_suffix: str) -> str:
    return "\n".join(
        (
            f'ref_{index} | hyperlink "Bounded role" | (1,2,3,4) | enabled '
            f'| value="https://www.zhipin.com/job_detail/{public_id}.html'
            f'?ka=personal_interest_brand_{marker_suffix}&securityId=discard-me"'
        )
        for index, public_id in enumerate(public_ids, start=1)
    )


def _discover(
    config: AgentConfig,
    *,
    first: tuple[str, ...],
    second: tuple[str, ...] | None,
) -> None:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        store = CampaignStore(config.state_dir, lock)
        create_boss_discovery_campaign(
            store,
            campaign_id="campaign_1",
            created_at=NOW.isoformat(timespec="seconds"),
        )
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_snapshot(*first, marker_suffix="abc123"),
            observed_at=NOW.isoformat(timespec="seconds"),
        )
        if second is not None:
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=_snapshot(*second, marker_suffix="def456"),
                observed_at=NOW.replace(minute=1).isoformat(timespec="seconds"),
            )
    finally:
        lock.release()


def _read_store(config: AgentConfig) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    return CampaignStore(config.state_dir, lock), lock


def test_start_opens_fixed_batch_and_claims_only_first_selected_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _discover(
        config,
        first=("publicjob001", "publicjob002"),
        second=("publicjob003", "publicjob004"),
    )

    outcome = start_boss_read_only_batch(
        AgentRunner(config),
        campaign_id="campaign_1",
        run_id="boss_run_1",
        now=NOW.replace(minute=2),
    )

    assert outcome.campaign_id == "campaign_1"
    assert outcome.run_id == "boss_run_1"
    assert outcome.batch_id.startswith("boss_batch_")
    assert outcome.discovered_count == 4
    assert outcome.discovery_pass_count == 2
    assert outcome.planned_item_count == 4
    assert outcome.claimed_item_ordinal == 1
    assert datetime.fromisoformat(outcome.lease_expires_at) == NOW.replace(
        minute=2
    ) + timedelta(seconds=BOSS_BATCH_LEASE_SECONDS)

    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        first = projection.items["boss:job:publicjob001"]
        assert first.status is ItemStatus.CLAIMED
        assert first.run_id == "boss_run_1"
        assert all(
            projection.items[f"boss:job:publicjob00{ordinal}"].status
            is ItemStatus.DISCOVERED
            for ordinal in (2, 3, 4)
        )
        batches = store.read_batches("campaign_1")
        assert batches.active is not None
        assert batches.active.batch_id == outcome.batch_id
        assert batches.active.run_id == "boss_run_1"
        heartbeat = store.read_heartbeat("campaign_1")
        assert heartbeat is not None
        assert heartbeat.run_id == "boss_run_1"
    finally:
        lock.release()
    assert not (config.state_dir / "runs" / "boss_run_1" / "state.json").exists()
    assert not (config.trace_dir / "boss_run_1.jsonl").exists()


def test_start_caps_first_batch_at_twenty_stable_ordinals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    first = tuple(f"publicjob{ordinal:03d}" for ordinal in range(1, 16))
    second = tuple(f"publicjob{ordinal:03d}" for ordinal in range(16, 26))
    _discover(config, first=first, second=second)

    outcome = start_boss_read_only_batch(
        AgentRunner(config),
        campaign_id="campaign_1",
        run_id="boss_run_1",
        now=NOW.replace(minute=2),
    )

    assert outcome.discovered_count == 25
    assert outcome.planned_item_count == BOSS_BATCH_POLICY.max_items == 20
    assert outcome.claimed_item_ordinal == 1


def test_start_requires_two_complete_discovery_passes_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _discover(config, first=("publicjob001",), second=None)

    with pytest.raises(BossCampaignBatchRuntimeError, match="^BOSS_BATCH_STATE_INVALID$"):
        start_boss_read_only_batch(
            AgentRunner(config),
            campaign_id="campaign_1",
            run_id="boss_run_1",
            now=NOW.replace(minute=2),
        )

    store, lock = _read_store(config)
    try:
        assert store.read_heartbeat("campaign_1") is None
        assert store.read_batches("campaign_1").transitions == ()
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].status is ItemStatus.DISCOVERED
    finally:
        lock.release()


def test_start_requires_read_only_host_policy_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch, policy_mode="approved_actions")
    _discover(
        config,
        first=("publicjob001",),
        second=("publicjob002",),
    )

    with pytest.raises(
        BossCampaignBatchRuntimeError,
        match="^BOSS_BATCH_READ_ONLY_REQUIRED$",
    ):
        start_boss_read_only_batch(
            AgentRunner(config),
            campaign_id="campaign_1",
            run_id="boss_run_1",
            now=NOW.replace(minute=2),
        )

    store, lock = _read_store(config)
    try:
        assert store.read_heartbeat("campaign_1") is None
        assert store.read_batches("campaign_1").transitions == ()
    finally:
        lock.release()


def test_second_start_refuses_existing_owner_and_active_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _discover(
        config,
        first=("publicjob001",),
        second=("publicjob002",),
    )
    start_boss_read_only_batch(
        AgentRunner(config),
        campaign_id="campaign_1",
        run_id="boss_run_1",
        now=NOW.replace(minute=2),
    )

    with pytest.raises(BossCampaignBatchRuntimeError, match="^BOSS_BATCH_STATE_INVALID$"):
        start_boss_read_only_batch(
            AgentRunner(config),
            campaign_id="campaign_1",
            run_id="boss_run_2",
            now=NOW.replace(minute=3),
        )

    store, lock = _read_store(config)
    try:
        assert len(store.read_batches("campaign_1").transitions) == 1
        assert store.read_heartbeat("campaign_1").run_id == "boss_run_1"  # type: ignore[union-attr]
    finally:
        lock.release()
