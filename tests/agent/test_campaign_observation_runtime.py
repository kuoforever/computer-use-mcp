from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.batch_coordinator import BatchCoordinator, BatchSession
from computer_use_agent.batching import BatchPolicy
from computer_use_agent.campaign import (
    CampaignHeartbeat,
    CampaignManifest,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_observation_runtime import (
    CampaignObservationRuntimeError,
    SYNTHETIC_CALL_ID,
    SYNTHETIC_CAMPAIGN_KIND,
    SYNTHETIC_ITEM_KEY,
    SYNTHETIC_OBSERVATION_TOOL,
    SYNTHETIC_TURN_ID,
    execute_claimed_synthetic_observation,
)
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, PreparedRun, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


DIGEST = "a" * 64
NOW = datetime(2026, 7, 17, 0, 10, tzinfo=timezone.utc)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=(
            local_app_data / "computer-use-agent" / "runtime-test"
        ).resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(max_model_turns=1, max_tool_calls=1),
    )


def _claimed_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: ToolResult,
) -> tuple[AgentRunner, PreparedRun, BatchSession, FakeDesktopMCP, AgentConfig]:
    config = _config(tmp_path, monkeypatch)
    desktop = FakeDesktopMCP(results=deque([result]))
    provider = FakeModelProvider(turns=deque())
    runner = AgentRunner(
        config,
        RunnerPorts(provider=provider, desktop=desktop, approvals=FakeApprovalPort()),
    )
    prepared = runner.prepare("Observe the fixed synthetic campaign item", run_id="run_1")
    store = prepared.campaign_store(config.state_dir)
    store.create(
        CampaignManifest(
            campaign_id="campaign_1",
            kind=SYNTHETIC_CAMPAIGN_KIND,
            policy_digest=DIGEST,
            schema_digest=DIGEST,
            created_at="2026-07-17T00:00:00+00:00",
            updated_at="2026-07-17T00:00:00+00:00",
        )
    )
    store.append(
        "campaign_1",
        ItemTransition(
            1,
            1,
            SYNTHETIC_ITEM_KEY,
            ItemStatus.DISCOVERED,
            0,
            "2026-07-17T00:01:00+00:00",
        ),
    )
    store.write_heartbeat(
        "campaign_1",
        CampaignHeartbeat(
            campaign_id="campaign_1",
            run_id="run_1",
            started_at="2026-07-17T00:00:00+00:00",
            heartbeat_at="2026-07-17T00:08:00+00:00",
            fresh_until="2026-07-17T00:12:00+00:00",
        ),
    )
    coordinator = BatchCoordinator(store)
    session = coordinator.open_batch(
        campaign_id="campaign_1",
        batch_id="batch_1",
        run_id="run_1",
        policy=BatchPolicy(max_items=1),
    )
    assert isinstance(session, BatchSession)
    coordinator.claim_first_item(session, now=NOW, lease_seconds=300)
    return runner, prepared, session, desktop, config


def _identity() -> CallIdentity:
    return CallIdentity(
        run_id="run_1",
        turn_id=SYNTHETIC_TURN_ID,
        call_id=SYNTHETIC_CALL_ID,
    )


def _read_item(config: AgentConfig) -> ItemTransition:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        return CampaignStore(config.state_dir, lock).read_ledger("campaign_1").items[
            SYNTHETIC_ITEM_KEY
        ]
    finally:
        lock.release()


def test_exact_claim_dispatches_once_and_persists_only_observed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad",
    )
    runner, prepared, session, desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )

    outcome = asyncio.run(
        execute_claimed_synthetic_observation(
            runner, prepared, session, now=NOW
        )
    )

    assert outcome.result == result
    assert outcome.observed.status is ItemStatus.OBSERVED
    assert outcome.observed.item_key == SYNTHETIC_ITEM_KEY
    assert outcome.observed.boundary == "reobserved"
    assert outcome.observed.code == "APPLICATION_AND_ITEM_VERIFIED"
    assert outcome.state.budgets.tool_calls_used == 1
    assert outcome.state.budgets.model_turns_used == 0
    assert desktop.tool_calls == [
        ToolCall(
            identity=_identity(),
            name=SYNTHETIC_OBSERVATION_TOOL,
            arguments={},
            status=ToolCallStatus.AUTHORIZED,
        )
    ]
    assert desktop.close_calls == 1
    assert _read_item(config).status is ItemStatus.OBSERVED
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "SUCCESS"
    assert record["state"]["metrics"]["model_calls"] == 0
    assert record["state"]["metrics"]["tool_calls"] == 1


@pytest.mark.parametrize(
    "result",
    [
        ToolResult(
            identity=_identity(),
            tool_name=SYNTHETIC_OBSERVATION_TOOL,
            status=ToolResultStatus.ACTION_ERROR,
            dispatch=DispatchCertainty.DISPATCHED,
            code="DRIVER_ERROR",
        ),
        ToolResult(
            identity=CallIdentity("run_1", SYNTHETIC_TURN_ID, "wrong_call"),
            tool_name=SYNTHETIC_OBSERVATION_TOOL,
            status=ToolResultStatus.SUCCESS,
            dispatch=DispatchCertainty.DISPATCHED,
            sanitized_text="window_1 | Notepad",
        ),
    ],
)
def test_failed_or_uncorrelated_result_never_attests_observed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    result: ToolResult,
) -> None:
    runner, prepared, session, _desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )

    with pytest.raises(CampaignObservationRuntimeError):
        asyncio.run(
            execute_claimed_synthetic_observation(
                runner, prepared, session, now=NOW
            )
        )

    assert _read_item(config).status is ItemStatus.CLAIMED


def test_non_synthetic_item_binding_fails_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
    )
    runner, prepared, session, desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )
    forged = BatchSession(
        campaign_id=session.campaign_id,
        batch_id=session.batch_id,
        run_id=session.run_id,
        policy=session.policy,
        plan=type(session.plan)(
            item_keys=("synthetic:other",),
            stop_reason=session.plan.stop_reason,
        ),
    )

    with pytest.raises(
        CampaignObservationRuntimeError,
        match="CAMPAIGN_OBSERVATION_BINDING_INVALID",
    ):
        asyncio.run(
            execute_claimed_synthetic_observation(
                runner, prepared, forged, now=NOW
            )
        )

    assert desktop.tool_calls == []
    assert _read_item(config).status is ItemStatus.CLAIMED
