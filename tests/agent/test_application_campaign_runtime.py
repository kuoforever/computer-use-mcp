from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.application_campaign_runtime import (
    ApplicationCampaignRuntimeError,
    execute_claimed_application_item,
    prepare_application_campaign,
    resume_application_campaign_batch,
    start_application_campaign_batch,
)
from computer_use_agent.application_worker_catalog import APPLICATION_WORKER_SPECS
from computer_use_agent.campaign import CampaignStore, ItemStatus
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ModelTurn,
    ModelUsage,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


NOW = datetime(2026, 7, 25, 14, 0, tzinfo=timezone.utc)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=(local / "computer-use-agent" / "application-campaign").resolve(),
        policy_version="approved-v1",
        provider=ProviderConfig("openai", "test-application-worker"),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(
            mode="approved_actions",
            max_model_turns=12,
            max_tool_calls=32,
            max_side_effects=4,
        ),
    )


def test_every_catalog_scenario_can_prepare_and_start_through_shared_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)

    for index, spec in enumerate(APPLICATION_WORKER_SPECS, start=1):
        campaign_id = f"campaign_a{index}"
        prepare_run = f"prepare_a{index}"
        worker_run = f"worker_a{index}"
        prepared = prepare_application_campaign(
            AgentRunner(config),
            spec=spec,
            campaign_id=campaign_id,
            run_id=prepare_run,
            item_keys=(f"fixture:a{index}:item_1", f"fixture:a{index}:item_2"),
            now=NOW,
        )
        started = start_application_campaign_batch(
            AgentRunner(config),
            spec=spec,
            campaign_id=campaign_id,
            run_id=worker_run,
            now=NOW,
        )

        assert prepared.scenario_id == spec.scenario_id
        assert prepared.item_count == 2
        assert started.scenario_id == spec.scenario_id
        assert started.planned_item_count == 1
        assert started.claimed_item_ordinal == 1

        lock = RunLock(config.application_state_dir)
        lock.acquire()
        try:
            store = CampaignStore(config.state_dir, lock)
            projection = store.read_ledger(campaign_id)
            assert projection.items[f"fixture:a{index}:item_1"].status is ItemStatus.CLAIMED
            assert projection.items[f"fixture:a{index}:item_2"].status is ItemStatus.DISCOVERED
            assert store.read_heartbeat(campaign_id).run_id == worker_run
        finally:
            lock.release()


def test_preparation_refuses_duplicate_item_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    with pytest.raises(
        ApplicationCampaignRuntimeError,
        match="^APPLICATION_CAMPAIGN_INPUT_INVALID$",
    ):
        prepare_application_campaign(
            AgentRunner(config),
            spec=APPLICATION_WORKER_SPECS[0],
            campaign_id="campaign_duplicate",
            run_id="prepare_duplicate",
            item_keys=("fixture:item_1", "fixture:item_1"),
            now=NOW,
        )


def test_wrong_registered_spec_cannot_start_existing_campaign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    prepare_application_campaign(
        AgentRunner(config),
        spec=APPLICATION_WORKER_SPECS[0],
        campaign_id="campaign_1",
        run_id="prepare_1",
        item_keys=("fixture:item_1",),
        now=NOW,
    )

    with pytest.raises(
        ApplicationCampaignRuntimeError,
        match="^APPLICATION_CAMPAIGN_STATE_INVALID$",
    ):
        start_application_campaign_batch(
            AgentRunner(config),
            spec=APPLICATION_WORKER_SPECS[1],
            campaign_id="campaign_1",
            run_id="worker_1",
            now=NOW,
        )


def test_generic_worker_observes_extracts_commits_and_hands_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    spec = APPLICATION_WORKER_SPECS[0]
    item_key = "boss:job:publicjob001"
    prepare_application_campaign(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_1",
        run_id="prepare_1",
        item_keys=(item_key, "boss:job:publicjob002"),
        now=NOW,
    )
    start_application_campaign_batch(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_1",
        run_id="worker_1",
        now=NOW,
    )
    call = ToolCall(
        CallIdentity("worker_1", "turn_1", "call_1"),
        "ui_snapshot",
        {"scope": "foreground"},
    )
    result_text = json.dumps(
        {
            "version": 1,
            "scenario_id": "A1",
            "item_key": item_key,
            "outcome": "EXTRACTED",
            "identity": {
                "account": "dedicated-test-account",
                "public_job_id": "publicjob001",
            },
            "result": {
                "company": "Example",
                "role": "Engineer",
                "location": "Shanghai",
                "compensation": "fixture-band",
                "experience": "fixture-level",
                "classification": "review",
            },
            "evidence": {
                "observation_tools": ["ui_snapshot"],
                "application_state_verified": True,
                "item_identity_verified": True,
            },
            "stop_code": None,
        }
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "worker_1",
                    "turn_1",
                    "response_1",
                    "",
                    (call,),
                    ModelUsage(input_tokens=20, output_tokens=5),
                ),
                ModelTurn(
                    "worker_1",
                    "turn_2",
                    "response_2",
                    result_text,
                    usage=ModelUsage(input_tokens=30, output_tokens=25),
                ),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    call.identity,
                    "ui_snapshot",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="bounded fixture observation",
                )
            ]
        )
    )

    outcome = asyncio.run(
        execute_claimed_application_item(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, FakeApprovalPort()),
            ),
            spec=spec,
            campaign_id="campaign_1",
            run_id="worker_1",
            now=NOW,
        )
    )

    assert outcome.stop_code == "ITEM_LIMIT"
    assert outcome.claimed_item_ordinal == 1
    assert outcome.usage.provider_turns == 2
    assert outcome.usage.tool_calls == 1
    assert outcome.usage.input_tokens == 50
    assert outcome.usage.output_tokens == 30
    assert outcome.handoff["next_item_ordinal"] == 2
    resumed = resume_application_campaign_batch(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_1",
        replacement_run_id="worker_2",
        now=NOW,
    )
    assert resumed.prior_run_id == "worker_1"
    assert resumed.claimed_item_ordinal == 2
    assert resumed.planned_item_count == 1
    assert resumed.heartbeat.run_id == "worker_2"
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        store = CampaignStore(config.state_dir, lock)
        assert store.read_ledger("campaign_1").items[item_key].status is ItemStatus.COMMITTED
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob002"
        ].status is ItemStatus.CLAIMED
        assert store.read_batches("campaign_1").active is not None
    finally:
        lock.release()


def test_provider_cannot_claim_observation_evidence_it_did_not_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    spec = APPLICATION_WORKER_SPECS[0]
    item_key = "boss:job:publicjob001"
    prepare_application_campaign(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_1",
        run_id="prepare_1",
        item_keys=(item_key,),
        now=NOW,
    )
    start_application_campaign_batch(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_1",
        run_id="worker_1",
        now=NOW,
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "worker_1",
                    "turn_1",
                    "response_1",
                    json.dumps(
                        {
                            "version": 1,
                            "scenario_id": "A1",
                            "item_key": item_key,
                            "outcome": "EXTRACTED",
                            "identity": {
                                "account": "test",
                                "public_job_id": "publicjob001",
                            },
                            "result": {
                                field: "claimed"
                                for field in spec.result_fields
                            },
                            "evidence": {
                                "observation_tools": ["ui_snapshot"],
                                "application_state_verified": True,
                                "item_identity_verified": True,
                            },
                            "stop_code": None,
                        }
                    ),
                )
            ]
        )
    )

    with pytest.raises(
        ApplicationCampaignRuntimeError,
        match="^APPLICATION_CAMPAIGN_EVIDENCE_INVALID$",
    ):
        asyncio.run(
            execute_claimed_application_item(
                AgentRunner(
                    config,
                    RunnerPorts(provider, FakeDesktopMCP(), FakeApprovalPort()),
                ),
                spec=spec,
                campaign_id="campaign_1",
                run_id="worker_1",
                now=NOW,
            )
        )


def test_last_item_resume_completes_campaign_and_retires_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    spec = APPLICATION_WORKER_SPECS[0]
    item_key = "boss:job:publicjob001"
    prepare_application_campaign(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_terminal",
        run_id="prepare_terminal",
        item_keys=(item_key,),
        now=NOW,
    )
    start_application_campaign_batch(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_terminal",
        run_id="worker_terminal",
        now=NOW,
    )
    call = ToolCall(
        CallIdentity("worker_terminal", "turn_1", "call_1"),
        "ui_snapshot",
        {"scope": "foreground"},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "worker_terminal",
                    "turn_1",
                    "response_1",
                    "",
                    (call,),
                ),
                ModelTurn(
                    "worker_terminal",
                    "turn_2",
                    "response_2",
                    json.dumps(
                        {
                            "version": 1,
                            "scenario_id": "A1",
                            "item_key": item_key,
                            "outcome": "EXTRACTED",
                            "identity": {
                                "account": "test",
                                "public_job_id": "publicjob001",
                            },
                            "result": {
                                field: "fixture"
                                for field in spec.result_fields
                            },
                            "evidence": {
                                "observation_tools": ["ui_snapshot"],
                                "application_state_verified": True,
                                "item_identity_verified": True,
                            },
                            "stop_code": None,
                        }
                    ),
                ),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    call.identity,
                    "ui_snapshot",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="bounded fixture observation",
                )
            ]
        )
    )
    asyncio.run(
        execute_claimed_application_item(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, FakeApprovalPort()),
            ),
            spec=spec,
            campaign_id="campaign_terminal",
            run_id="worker_terminal",
            now=NOW,
        )
    )

    completed = resume_application_campaign_batch(
        AgentRunner(config),
        spec=spec,
        campaign_id="campaign_terminal",
        replacement_run_id="worker_terminal_finalize",
        now=NOW,
    )

    assert completed.completed
    assert completed.claimed_item_ordinal is None
    assert completed.batch_id is None
    assert completed.planned_item_count == 0
    assert completed.heartbeat is None
    assert completed.terminal_handoff is not None
    assert completed.terminal_handoff["next_action"] == "none_completed"
    assert completed.terminal_handoff["required_observation"] == "none"
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        store = CampaignStore(config.state_dir, lock)
        assert (
            store.read_manifest("campaign_terminal").status.value
            == "COMPLETED"
        )
        assert store.read_heartbeat("campaign_terminal") is None
        assert store.read_handoff("campaign_terminal") == completed.terminal_handoff
    finally:
        lock.release()
