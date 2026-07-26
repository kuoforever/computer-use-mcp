from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.boss_campaign_batch_runtime import start_boss_read_only_batch
from computer_use_agent.boss_campaign_discovery import (
    create_boss_discovery_campaign,
    record_boss_snapshot_discoveries,
)
from computer_use_agent.boss_campaign_item_runtime import (
    BOSS_ITEM_CALL_ID,
    BOSS_ITEM_TOOL,
    BOSS_ITEM_TURN_ID,
    BossCampaignItemRuntimeError,
    boss_identity_presence_digest,
    execute_claimed_boss_identity_through_handoff,
)
from computer_use_agent.boss_campaign_restart_runtime import (
    BossCampaignRestartRuntimeError,
    resume_finished_boss_batch_after_restart,
)
from computer_use_agent.campaign import CampaignStore, ItemStatus, campaign_dir
from computer_use_agent.config import AgentConfig, MCPLaunchConfig, PolicyConfig, ProviderConfig
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import RunPhase, read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


NOW = datetime(2026, 7, 23, 15, 0, tzinfo=timezone.utc)


class _RecordingLifecycle:
    def __init__(self) -> None:
        self.events: list[RunPhase | str] = []

    def on_phase(self, phase: RunPhase) -> None:
        self.events.append(phase)

    def estop(self) -> None:
        self.events.append("estop")

    def release(self) -> None:
        self.events.append("release")


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=(local / "computer-use-agent" / "boss-item").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "unused-boss-item"),
        mcp=MCPLaunchConfig(
            tmp_path / "computer-use-mcp.exe",
            (),
            tmp_path,
            {"CUMCP_ALLOWLIST": "chrome.exe"},
        ),
        policy=PolicyConfig(
            max_model_turns=0,
            max_tool_calls=1,
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


def _prepare(config: AgentConfig) -> None:
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
            snapshot_text=_snapshot(
                "publicjob001",
                "publicjob002",
                marker_suffix="abc123",
            ),
            observed_at=NOW.isoformat(timespec="seconds"),
        )
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_snapshot(
                "publicjob003",
                "publicjob004",
                marker_suffix="def456",
            ),
            observed_at=NOW.replace(minute=1).isoformat(timespec="seconds"),
        )
    finally:
        lock.release()
    start_boss_read_only_batch(
        AgentRunner(config),
        campaign_id="campaign_1",
        run_id="boss_run_1",
        now=NOW.replace(minute=2),
    )


def _result(
    text: str,
    *,
    success: bool = True,
    run_id: str = "boss_run_1",
) -> ToolResult:
    return ToolResult(
        identity=CallIdentity(
            run_id,
            BOSS_ITEM_TURN_ID,
            BOSS_ITEM_CALL_ID,
        ),
        tool_name=BOSS_ITEM_TOOL,
        status=(
            ToolResultStatus.SUCCESS
            if success
            else ToolResultStatus.ACTION_ERROR
        ),
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text=text,
        code=None if success else "DRIVER_ERROR",
    )


def _read_store(config: AgentConfig) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    return CampaignStore(config.state_dir, lock), lock


def test_exact_claimed_identity_commits_and_finishes_one_tool_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    snapshot = _snapshot(
        "publicjob001",
        "publicjob002",
        marker_suffix="fedcba",
    )
    desktop = FakeDesktopMCP(results=deque([_result(snapshot)]))
    provider = FakeModelProvider(turns=deque())
    approvals = FakeApprovalPort()
    presence = _RecordingLifecycle()

    outcome = asyncio.run(
        execute_claimed_boss_identity_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, approvals, presence=presence),
            ),
            campaign_id="campaign_1",
            run_id="boss_run_1",
            now=NOW.replace(minute=3),
        )
    )

    assert outcome.claimed_item_ordinal == 1
    assert outcome.stop_code == "TOOL_CALL_LIMIT"
    assert outcome.usage.items_completed == 1
    assert outcome.usage.tool_calls == 1
    assert outcome.usage.provider_turns == 0
    assert outcome.handoff["completed_count"] == 1
    assert outcome.handoff["next_item_ordinal"] == 2
    assert outcome.content_digest == boss_identity_presence_digest(
        item_key="boss:job:publicjob001",
        source_digest=outcome.source_digest,
    )
    assert desktop.tool_calls == [
        ToolCall(
            CallIdentity(
                "boss_run_1",
                BOSS_ITEM_TURN_ID,
                BOSS_ITEM_CALL_ID,
            ),
            BOSS_ITEM_TOOL,
            {"scope": "foreground"},
            ToolCallStatus.AUTHORIZED,
        )
    ]
    assert desktop.close_calls == 1
    assert provider.calls == []
    assert approvals.requests == []

    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        assert projection.items["boss:job:publicjob001"].status is ItemStatus.COMMITTED
        assert projection.items["boss:job:publicjob001"].content_digest == (
            outcome.content_digest
        )
        assert projection.items["boss:job:publicjob002"].status is ItemStatus.DISCOVERED
        assert store.read_batches("campaign_1").active is None
        assert store.read_handoff("campaign_1")["last_run_id"] == "boss_run_1"
    finally:
        lock.release()

    trace = (
        config.trace_dir / "boss_run_1.jsonl"
    ).read_text(encoding="utf-8")
    assert "publicjob001" not in trace
    assert "securityId" not in trace
    assert "https://" not in trace
    record = read_run_record(config.state_dir, "boss_run_1")
    assert record["state"]["phase"] == "SUCCESS"
    assert presence.events == [
        RunPhase.CREATED,
        RunPhase.OBSERVING,
        RunPhase.PLANNING,
        RunPhase.EXECUTING,
        RunPhase.OBSERVING,
        RunPhase.PLANNING,
        RunPhase.SUCCESS,
        "release",
    ]


def test_wrong_visible_identity_fails_closed_and_leaves_claim_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(
                    _snapshot(
                        "publicjob999",
                        marker_suffix="fedcba",
                    )
                )
            ]
        )
    )

    with pytest.raises(
        BossCampaignItemRuntimeError,
        match="^BOSS_ITEM_IDENTITY_NOT_PRESENT$",
    ):
        asyncio.run(
            execute_claimed_boss_identity_through_handoff(
                AgentRunner(
                    config,
                    RunnerPorts(
                        FakeModelProvider(turns=deque()),
                        desktop,
                        FakeApprovalPort(),
                    ),
                ),
                campaign_id="campaign_1",
                run_id="boss_run_1",
                now=NOW.replace(minute=3),
            )
        )

    store, lock = _read_store(config)
    try:
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].status is ItemStatus.CLAIMED
        assert store.read_batches("campaign_1").active is not None
        assert not (campaign_dir(config.state_dir, "campaign_1") / "handoff.json").exists()
    finally:
        lock.release()
    assert desktop.close_calls == 1
    record = read_run_record(config.state_dir, "boss_run_1")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "BOSS_ITEM_IDENTITY_NOT_PRESENT"


def test_failed_snapshot_does_not_advance_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    desktop = FakeDesktopMCP(
        results=deque(
            [
                _result(
                    _snapshot("publicjob001", marker_suffix="fedcba"),
                    success=False,
                )
            ]
        )
    )

    with pytest.raises(
        BossCampaignItemRuntimeError,
        match="^BOSS_ITEM_OBSERVATION_TOOL_FAILED$",
    ):
        asyncio.run(
            execute_claimed_boss_identity_through_handoff(
                AgentRunner(
                    config,
                    RunnerPorts(
                        FakeModelProvider(turns=deque()),
                        desktop,
                        FakeApprovalPort(),
                    ),
                ),
                campaign_id="campaign_1",
                run_id="boss_run_1",
                now=NOW.replace(minute=3),
            )
        )

    store, lock = _read_store(config)
    try:
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].status is ItemStatus.CLAIMED
    finally:
        lock.release()


def test_identity_digest_rejects_unbounded_or_wrong_inputs() -> None:
    with pytest.raises(
        BossCampaignItemRuntimeError,
        match="^BOSS_ITEM_RESULT_INVALID$",
    ):
        boss_identity_presence_digest(
            item_key="other:item",
            source_digest="a" * 64,
        )
    with pytest.raises(
        BossCampaignItemRuntimeError,
        match="^BOSS_ITEM_RESULT_INVALID$",
    ):
        boss_identity_presence_digest(
            item_key="boss:job:publicjob001",
            source_digest="not-a-digest",
        )


def test_finished_batch_transfers_to_fresh_run_and_claims_exact_next_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    asyncio.run(
        execute_claimed_boss_identity_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(
                    FakeModelProvider(turns=deque()),
                    FakeDesktopMCP(
                        results=deque(
                            [
                                _result(
                                    _snapshot(
                                        "publicjob001",
                                        "publicjob002",
                                        marker_suffix="fedcba",
                                    )
                                )
                            ]
                        )
                    ),
                    FakeApprovalPort(),
                ),
            ),
            campaign_id="campaign_1",
            run_id="boss_run_1",
            now=NOW.replace(minute=3),
        )
    )

    outcome = resume_finished_boss_batch_after_restart(
        AgentRunner(config),
        campaign_id="campaign_1",
        replacement_run_id="boss_run_2",
        now=NOW.replace(minute=10),
    )

    assert outcome.prior_run_id == "boss_run_1"
    assert outcome.replacement_run_id == "boss_run_2"
    assert outcome.claimed_item_ordinal == 2
    assert outcome.planned_item_count == 3
    assert outcome.resume.item_keys[0] == "boss:job:publicjob002"
    assert outcome.heartbeat.run_id == "boss_run_2"
    assert outcome.prior_handoff["last_run_id"] == "boss_run_1"

    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        assert projection.items["boss:job:publicjob001"].status is ItemStatus.COMMITTED
        claimed = projection.items["boss:job:publicjob002"]
        assert claimed.status is ItemStatus.CLAIMED
        assert claimed.run_id == "boss_run_2"
        active = store.read_batches("campaign_1").active
        assert active is not None
        assert (active.batch_id, active.run_id) == (
            outcome.batch_id,
            "boss_run_2",
        )
        assert store.read_heartbeat("campaign_1") == outcome.heartbeat
    finally:
        lock.release()
    assert not (config.trace_dir / "boss_run_2.jsonl").exists()
    assert not (
        config.state_dir / "runs" / "boss_run_2" / "state.json"
    ).exists()

    second = asyncio.run(
        execute_claimed_boss_identity_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(
                    FakeModelProvider(turns=deque()),
                    FakeDesktopMCP(
                        results=deque(
                            [
                                _result(
                                    _snapshot(
                                        "publicjob002",
                                        "publicjob003",
                                        marker_suffix="abcdef",
                                    ),
                                    run_id="boss_run_2",
                                )
                            ]
                        )
                    ),
                    FakeApprovalPort(),
                ),
            ),
            campaign_id="campaign_1",
            run_id="boss_run_2",
            now=NOW.replace(minute=11),
        )
    )
    assert second.claimed_item_ordinal == 2
    assert second.handoff["completed_count"] == 2
    assert second.handoff["next_item_ordinal"] == 3
    store, lock = _read_store(config)
    try:
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob002"
        ].status is ItemStatus.COMMITTED
        assert store.read_batches("campaign_1").active is None
    finally:
        lock.release()


def test_restart_before_finished_handoff_fails_without_transferring_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)

    with pytest.raises(
        BossCampaignRestartRuntimeError,
        match="^BOSS_RESTART_STATE_INVALID$",
    ):
        resume_finished_boss_batch_after_restart(
            AgentRunner(config),
            campaign_id="campaign_1",
            replacement_run_id="boss_run_2",
            now=NOW.replace(minute=3),
        )

    store, lock = _read_store(config)
    try:
        assert store.read_heartbeat("campaign_1").run_id == "boss_run_1"
        assert len(store.read_batches("campaign_1").transitions) == 1
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].status is ItemStatus.CLAIMED
    finally:
        lock.release()
