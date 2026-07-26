from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.boss_campaign_observation_runtime import (
    BOSS_DISCOVERY_CALL_ID,
    BOSS_DISCOVERY_TOOL,
    BOSS_DISCOVERY_TURN_ID,
    BossCampaignObservationRuntimeError,
    execute_boss_discovery_page,
    prepare_boss_discovery_campaign,
)
from computer_use_agent.campaign import CampaignStore, campaign_dir
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


NOW = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)


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
        state_dir=(local / "computer-use-agent" / "boss-runtime").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "test-model"),
        mcp=MCPLaunchConfig(
            tmp_path / "computer-use-mcp.exe",
            (),
            tmp_path,
            {"CUMCP_ALLOWLIST": "chrome.exe"},
        ),
        policy=PolicyConfig(max_model_turns=1, max_tool_calls=1),
    )


def _snapshot(*public_ids: str) -> str:
    return "\n".join(
        f'ref_{index} | link "Bounded role" | (1,2,3,4) | enabled '
        f'| value="https://www.zhipin.com/job_detail/{public_id}.html'
        f'?ka=personal_interest_brand&securityId=discard-me"'
        for index, public_id in enumerate(public_ids, start=1)
    )


def _result(run_id: str, text: str, *, success: bool = True) -> ToolResult:
    return ToolResult(
        identity=CallIdentity(run_id, BOSS_DISCOVERY_TURN_ID, BOSS_DISCOVERY_CALL_ID),
        tool_name=BOSS_DISCOVERY_TOOL,
        status=ToolResultStatus.SUCCESS if success else ToolResultStatus.ACTION_ERROR,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text=text,
        code=None if success else "DRIVER_ERROR",
    )


def _read_ledger(config: AgentConfig):
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        return CampaignStore(config.state_dir, lock).read_ledger("campaign_1")
    finally:
        lock.release()


def test_preparation_creates_only_the_fixed_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)

    outcome = prepare_boss_discovery_campaign(
        AgentRunner(config), campaign_id="campaign_1", run_id="prepare_1", now=NOW
    )

    assert outcome.campaign_id == "campaign_1"
    assert outcome.campaign_kind == "boss_saved_job_read_only"
    assert outcome.run_id == "prepare_1"
    assert _read_ledger(config).discovered_count == 0
    assert not (config.state_dir / "runs" / "prepare_1.json").exists()


def test_fixed_page_observation_dispatches_once_and_persists_only_public_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_boss_discovery_campaign(
        AgentRunner(config), campaign_id="campaign_1", run_id="prepare_1", now=NOW
    )
    desktop = FakeDesktopMCP(
        results=deque([_result("run_1", _snapshot("publicjob001", "publicjob002"))])
    )
    provider = FakeModelProvider(turns=deque())
    approvals = FakeApprovalPort()
    presence = _RecordingLifecycle()
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=approvals,
            presence=presence,
        ),
    )

    outcome = asyncio.run(
        execute_boss_discovery_page(runner, campaign_id="campaign_1", run_id="run_1", now=NOW)
    )

    assert outcome.discovery.new_item_keys == (
        "boss:job:publicjob001",
        "boss:job:publicjob002",
    )
    assert outcome.discovery.discovered_count == 2
    assert outcome.state.budgets.tool_calls_used == 1
    assert outcome.state.budgets.model_turns_used == 0
    assert desktop.tool_calls == [
        ToolCall(
            CallIdentity("run_1", BOSS_DISCOVERY_TURN_ID, BOSS_DISCOVERY_CALL_ID),
            BOSS_DISCOVERY_TOOL,
            {"scope": "foreground"},
            ToolCallStatus.AUTHORIZED,
        )
    ]
    assert desktop.close_calls == 1
    assert provider.calls == []
    assert approvals.requests == []
    ledger_path = campaign_dir(config.state_dir, "campaign_1") / "items.jsonl"
    persisted = ledger_path.read_text(encoding="utf-8")
    assert "securityId" not in persisted
    assert "discard-me" not in persisted
    assert "Bounded role" not in persisted
    assert "https://" not in persisted
    record = read_run_record(config.state_dir, "run_1")
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
    assert record["state"]["metrics"]["model_calls"] == 0
    assert record["state"]["metrics"]["tool_calls"] == 1


def test_second_page_reuses_campaign_with_a_fresh_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_boss_discovery_campaign(
        AgentRunner(config), campaign_id="campaign_1", run_id="prepare_1", now=NOW
    )
    first = AgentRunner(
        config,
        RunnerPorts(
            FakeModelProvider(turns=deque()),
            FakeDesktopMCP(results=deque([_result("run_1", _snapshot("publicjob001"))])),
            FakeApprovalPort(),
        ),
    )
    asyncio.run(
        execute_boss_discovery_page(first, campaign_id="campaign_1", run_id="run_1", now=NOW)
    )
    second = AgentRunner(
        config,
        RunnerPorts(
            FakeModelProvider(turns=deque()),
            FakeDesktopMCP(
                results=deque([_result("run_2", _snapshot("publicjob001", "publicjob002"))])
            ),
            FakeApprovalPort(),
        ),
    )

    outcome = asyncio.run(
        execute_boss_discovery_page(
            second,
            campaign_id="campaign_1",
            run_id="run_2",
            now=NOW.replace(minute=1),
        )
    )

    assert outcome.discovery.new_item_keys == ("boss:job:publicjob002",)
    assert outcome.discovery.duplicate_count == 1
    assert outcome.discovery.discovered_count == 2


def test_wrong_foreground_page_fails_without_campaign_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_boss_discovery_campaign(
        AgentRunner(config), campaign_id="campaign_1", run_id="prepare_1", now=NOW
    )
    desktop = FakeDesktopMCP(results=deque([_result("run_1", 'ref_1 | button "OK"')]))
    runner = AgentRunner(
        config,
        RunnerPorts(FakeModelProvider(turns=deque()), desktop, FakeApprovalPort()),
    )

    with pytest.raises(BossCampaignObservationRuntimeError, match="^BOSS_DISCOVERY_NO_IDENTITIES$"):
        asyncio.run(
            execute_boss_discovery_page(runner, campaign_id="campaign_1", run_id="run_1", now=NOW)
        )

    assert _read_ledger(config).discovered_count == 0
    assert desktop.close_calls == 1
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "BOSS_DISCOVERY_NO_IDENTITIES"


def test_failed_snapshot_result_is_terminal_and_does_not_parse_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_boss_discovery_campaign(
        AgentRunner(config), campaign_id="campaign_1", run_id="prepare_1", now=NOW
    )
    desktop = FakeDesktopMCP(
        results=deque([_result("run_1", _snapshot("publicjob001"), success=False)])
    )
    runner = AgentRunner(
        config,
        RunnerPorts(FakeModelProvider(turns=deque()), desktop, FakeApprovalPort()),
    )

    with pytest.raises(BossCampaignObservationRuntimeError, match="^BOSS_OBSERVATION_TOOL_FAILED$"):
        asyncio.run(
            execute_boss_discovery_page(runner, campaign_id="campaign_1", run_id="run_1", now=NOW)
        )

    assert _read_ledger(config).discovered_count == 0
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "BOSS_OBSERVATION_TOOL_FAILED"


@pytest.mark.parametrize(
    ("code", "teardown"),
    [("ABORTED", "estop"), ("HUMAN_ACTIVE", "release")],
)
def test_desktop_authority_loss_closes_campaign_presence_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    teardown: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_boss_discovery_campaign(
        AgentRunner(config), campaign_id="campaign_1", run_id="prepare_1", now=NOW
    )
    result = ToolResult(
        identity=CallIdentity(
            "run_1",
            BOSS_DISCOVERY_TURN_ID,
            BOSS_DISCOVERY_CALL_ID,
        ),
        tool_name=BOSS_DISCOVERY_TOOL,
        status=ToolResultStatus.REJECTED,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code=code,
    )
    presence = _RecordingLifecycle()
    runner = AgentRunner(
        config,
        RunnerPorts(
            FakeModelProvider(turns=deque()),
            FakeDesktopMCP(results=deque([result])),
            FakeApprovalPort(),
            presence=presence,
        ),
    )

    with pytest.raises(
        BossCampaignObservationRuntimeError,
        match="^BOSS_OBSERVATION_TOOL_FAILED$",
    ):
        asyncio.run(
            execute_boss_discovery_page(
                runner,
                campaign_id="campaign_1",
                run_id="run_1",
                now=NOW,
            )
        )

    assert presence.events == [
        RunPhase.CREATED,
        RunPhase.OBSERVING,
        RunPhase.PLANNING,
        RunPhase.EXECUTING,
        teardown,
    ]


def test_invalid_campaign_state_stops_before_mcp_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    desktop = FakeDesktopMCP(results=deque([_result("run_1", _snapshot("publicjob001"))]))
    runner = AgentRunner(
        config,
        RunnerPorts(FakeModelProvider(turns=deque()), desktop, FakeApprovalPort()),
    )

    with pytest.raises(BossCampaignObservationRuntimeError, match="^BOSS_DISCOVERY_STATE_INVALID$"):
        asyncio.run(
            execute_boss_discovery_page(
                runner, campaign_id="missing_campaign", run_id="run_1", now=NOW
            )
        )

    assert desktop.discovery_calls == 0
    assert desktop.tool_calls == []
    assert desktop.close_calls == 1
