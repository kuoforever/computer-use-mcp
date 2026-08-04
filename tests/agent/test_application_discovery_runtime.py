from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.application_discovery_runtime import (
    APPLICATION_DISCOVERY_CALL_ID,
    APPLICATION_DISCOVERY_TURN_ID,
    ApplicationDiscoveryRuntimeError,
    execute_application_discovery_pass,
    prepare_application_discovery_campaign,
)
from computer_use_agent.campaign import CampaignStore, campaign_dir
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.discovery_adapters import DISCOVERY_OBSERVATION_TOOL
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import RunPhase, read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    MCPCallCancelled,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


NOW = datetime(2026, 7, 26, 5, 0, tzinfo=timezone.utc)
KIND = "enterprise_incident"


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
        state_dir=(local / "computer-use-agent" / "discovery-runtime").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "test-model"),
        mcp=MCPLaunchConfig(tmp_path / "computer-use-mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(max_model_turns=1, max_tool_calls=1),
    )


def _queue(*public_ids: str, marker: str = "Incident queue - open") -> str:
    header = f'ref_1 | text "{marker}" | (0,0,10,10) | enabled'
    rows = [
        f'ref_{index} | listitem "{public_id} bounded row" | (0,0,10,10) | enabled'
        for index, public_id in enumerate(public_ids, start=2)
    ]
    return "\n".join([header, *rows])


def _result(run_id: str, text: str, *, success: bool = True) -> ToolResult:
    return ToolResult(
        identity=CallIdentity(
            run_id,
            APPLICATION_DISCOVERY_TURN_ID,
            APPLICATION_DISCOVERY_CALL_ID,
        ),
        tool_name=DISCOVERY_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS if success else ToolResultStatus.ACTION_ERROR,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text=text,
        code=None if success else "DRIVER_ERROR",
    )


def _runner(config: AgentConfig, result: ToolResult, presence=None) -> AgentRunner:
    return AgentRunner(
        config,
        RunnerPorts(
            provider=FakeModelProvider(turns=deque()),
            desktop=FakeDesktopMCP(results=deque([result])),
            approvals=FakeApprovalPort(),
            presence=presence,
        ),
    )


def _read_ledger(config: AgentConfig, campaign_id: str = "campaign_1"):
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        return CampaignStore(config.state_dir, lock).read_ledger(campaign_id)
    finally:
        lock.release()


def test_preparation_creates_only_the_registered_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)

    outcome = prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=KIND,
        campaign_id="campaign_1",
        run_id="prepare_1",
        now=NOW,
    )

    assert outcome.campaign_kind == KIND
    assert outcome.adapter_id == "incident_queue_rows"
    assert outcome.run_id == "prepare_1"
    assert _read_ledger(config).discovered_count == 0
    assert not (config.state_dir / "runs" / "prepare_1.json").exists()


def test_preparation_refuses_an_unregistered_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(
        ApplicationDiscoveryRuntimeError, match="^DISCOVERY_ADAPTER_UNSUPPORTED$"
    ):
        prepare_application_discovery_campaign(
            AgentRunner(config),
            campaign_kind="google_docs_section_review",
            campaign_id="campaign_1",
            run_id="prepare_1",
            now=NOW,
        )


def test_preparation_refuses_open_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(
        ApplicationDiscoveryRuntimeError, match="^APPLICATION_DISCOVERY_INPUT_INVALID$"
    ):
        prepare_application_discovery_campaign(
            _runner(config, _result("run_1", _queue("INC-004821"))),
            campaign_kind=KIND,
            campaign_id="campaign_1",
            run_id="prepare_1",
            now=NOW,
        )


def test_one_pass_dispatches_once_and_persists_only_public_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=KIND,
        campaign_id="campaign_1",
        run_id="prepare_1",
        now=NOW,
    )
    presence = _RecordingLifecycle()
    runner = _runner(
        config,
        _result("run_1", _queue("INC-004821", "INC-004822")),
        presence=presence,
    )

    outcome = asyncio.run(
        execute_application_discovery_pass(
            runner,
            campaign_id="campaign_1",
            run_id="run_1",
            now=NOW,
        )
    )

    assert outcome.discovery.new_item_keys == (
        "incident:ticket:INC-004821",
        "incident:ticket:INC-004822",
    )
    assert outcome.discovery.adapter_id == "incident_queue_rows"
    assert outcome.state.budgets.tool_calls_used == 1
    assert outcome.state.budgets.model_turns_used == 0
    assert runner.ports.desktop.tool_calls == [
        ToolCall(
            CallIdentity("run_1", APPLICATION_DISCOVERY_TURN_ID, APPLICATION_DISCOVERY_CALL_ID),
            DISCOVERY_OBSERVATION_TOOL,
            {"scope": "foreground"},
            ToolCallStatus.AUTHORIZED,
        )
    ]
    assert runner.ports.desktop.close_calls == 1
    assert runner.ports.provider.calls == []
    assert runner.ports.approvals.requests == []
    persisted = (campaign_dir(config.state_dir, "campaign_1") / "items.jsonl").read_text(
        encoding="utf-8"
    )
    assert "bounded row" not in persisted
    assert "Incident queue" not in persisted
    assert read_run_record(config.state_dir, "run_1")["state"]["phase"] == "SUCCESS"
    assert presence.events[-1] == "release"
    assert RunPhase.SUCCESS in presence.events


def test_post_dispatch_cancellation_keeps_shared_runtime_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=KIND,
        campaign_id="campaign_1",
        run_id="prepare_1",
        now=NOW,
    )

    class CancellingDesktop(FakeDesktopMCP):
        async def call_tool(self, call: ToolCall) -> ToolResult:
            self.tool_calls.append(call)
            raise MCPCallCancelled(
                ToolResult(
                    call.identity,
                    call.name,
                    ToolResultStatus.UNKNOWN_OUTCOME,
                    DispatchCertainty.UNKNOWN,
                    code="MCP_TRANSPORT_ERROR",
                )
            ) from None

    desktop = CancellingDesktop()
    runner = AgentRunner(
        config,
        RunnerPorts(FakeModelProvider(), desktop, FakeApprovalPort()),
    )

    with pytest.raises(MCPCallCancelled):
        asyncio.run(
            execute_application_discovery_pass(
                runner,
                campaign_id="campaign_1",
                run_id="run_1",
                now=NOW,
            )
        )

    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "UNKNOWN_OUTCOME"
    assert record["state"]["failure_code"] == "UNKNOWN_OUTCOME"
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1


def test_a_second_pass_reuses_the_campaign_with_a_fresh_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=KIND,
        campaign_id="campaign_1",
        run_id="prepare_1",
        now=NOW,
    )
    asyncio.run(
        execute_application_discovery_pass(
            _runner(config, _result("run_1", _queue("INC-004821"))),
            campaign_id="campaign_1",
            run_id="run_1",
            now=NOW,
        )
    )

    outcome = asyncio.run(
        execute_application_discovery_pass(
            _runner(config, _result("run_2", _queue("INC-004821", "INC-004822"))),
            campaign_id="campaign_1",
            run_id="run_2",
            now=NOW.replace(minute=1),
        )
    )

    assert outcome.discovery.new_item_keys == ("incident:ticket:INC-004822",)
    assert outcome.discovery.duplicate_count == 1
    assert outcome.discovery.discovered_count == 2
    assert outcome.discovery.pass_sequence == 2


def test_an_unchanged_source_fails_the_run_without_persisting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=KIND,
        campaign_id="campaign_1",
        run_id="prepare_1",
        now=NOW,
    )
    snapshot = _queue("INC-004821")
    asyncio.run(
        execute_application_discovery_pass(
            _runner(config, _result("run_1", snapshot)),
            campaign_id="campaign_1",
            run_id="run_1",
            now=NOW,
        )
    )
    runner = _runner(config, _result("run_2", snapshot))

    with pytest.raises(
        ApplicationDiscoveryRuntimeError,
        match="^APPLICATION_DISCOVERY_SOURCE_UNCHANGED$",
    ):
        asyncio.run(
            execute_application_discovery_pass(
                runner,
                campaign_id="campaign_1",
                run_id="run_2",
                now=NOW.replace(minute=1),
            )
        )

    assert _read_ledger(config).discovered_count == 1
    assert runner.ports.desktop.close_calls == 1
    assert read_run_record(config.state_dir, "run_2")["state"]["phase"] == "FAILED"


def test_a_failed_observation_persists_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_application_discovery_campaign(
        AgentRunner(config),
        campaign_kind=KIND,
        campaign_id="campaign_1",
        run_id="prepare_1",
        now=NOW,
    )
    runner = _runner(config, _result("run_1", "", success=False))

    with pytest.raises(ApplicationDiscoveryRuntimeError):
        asyncio.run(
            execute_application_discovery_pass(
                runner,
                campaign_id="campaign_1",
                run_id="run_1",
                now=NOW,
            )
        )

    assert _read_ledger(config).discovered_count == 0
    assert runner.ports.desktop.close_calls == 1


def test_observation_requires_a_registered_durable_kind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from computer_use_agent.application_campaign_runtime import prepare_application_campaign
    from computer_use_agent.application_worker_catalog import APPLICATION_WORKERS_BY_SCENARIO

    config = _config(tmp_path, monkeypatch)
    prepare_application_campaign(
        AgentRunner(config),
        spec=APPLICATION_WORKERS_BY_SCENARIO["A2"],
        campaign_id="campaign_unregistered",
        run_id="prepare_1",
        item_keys=("fixture:item_1",),
        now=NOW,
    )
    runner = _runner(config, _result("run_1", _queue("INC-004821")))

    with pytest.raises(
        ApplicationDiscoveryRuntimeError, match="^DISCOVERY_ADAPTER_UNSUPPORTED$"
    ):
        asyncio.run(
            execute_application_discovery_pass(
                runner,
                campaign_id="campaign_unregistered",
                run_id="run_1",
                now=NOW,
            )
        )

    assert runner.ports.desktop.tool_calls == []
    assert runner.ports.desktop.close_calls == 1


def test_observation_requires_open_ports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(
        ApplicationDiscoveryRuntimeError, match="^APPLICATION_DISCOVERY_PORTS_REQUIRED$"
    ):
        asyncio.run(
            execute_application_discovery_pass(
                AgentRunner(config),
                campaign_id="campaign_1",
                run_id="run_1",
                now=NOW,
            )
        )
