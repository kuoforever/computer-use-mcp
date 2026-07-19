from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.batch_coordinator import BatchCoordinator, BatchSession
from computer_use_agent.batching import BatchPolicy, BatchUsage
from computer_use_agent.campaign import (
    BatchProjection,
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.campaign_observation_runtime import (
    CampaignObservationRuntimeError,
    CampaignPreparationOutcome,
    CampaignRestartResumeOutcome,
    MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS,
    SYNTHETIC_CALL_ID,
    SYNTHETIC_BATCH_ID,
    SYNTHETIC_CAMPAIGN_KIND,
    SYNTHETIC_ITEM_KEY,
    SYNTHETIC_OBSERVATION_TOOL,
    SYNTHETIC_RESUME_TASK,
    SYNTHETIC_TURN_ID,
    execute_claimed_synthetic_observation,
    execute_claimed_synthetic_observation_and_extraction,
    execute_claimed_synthetic_item_through_commit,
    execute_claimed_synthetic_item_through_handoff,
    execute_persisted_claimed_synthetic_item_through_handoff,
    prepare_synthetic_campaign,
    resume_finished_synthetic_campaign_after_restart,
    synthetic_window_count_digest,
    synthetic_campaign_policy_digest,
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
from computer_use_agent.tool_registry import reviewed_registry_digest
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


def _assert_single_item_usage(usage: BatchUsage) -> None:
    assert 0 <= usage.elapsed_seconds < BatchPolicy().max_elapsed_seconds
    assert usage == BatchUsage(
        items_completed=1,
        elapsed_seconds=usage.elapsed_seconds,
        tool_calls=1,
    )


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


def _read_finished_campaign(
    config: AgentConfig,
) -> tuple[BatchProjection, dict[str, object], CampaignHeartbeat | None]:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        store = CampaignStore(config.state_dir, lock)
        return (
            store.read_batches("campaign_1"),
            store.read_handoff("campaign_1"),
            store.read_heartbeat("campaign_1"),
        )
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


def test_fixed_preparation_creates_only_one_exact_durable_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    runner = AgentRunner(config)

    outcome = prepare_synthetic_campaign(
        runner,
        campaign_id="campaign_1",
        run_id="run_1",
        now=NOW,
    )

    assert isinstance(outcome, CampaignPreparationOutcome)
    assert outcome.manifest.kind == SYNTHETIC_CAMPAIGN_KIND
    assert outcome.manifest.policy_digest == synthetic_campaign_policy_digest(runner)
    assert outcome.manifest.schema_digest == reviewed_registry_digest()
    assert outcome.discovered.status is ItemStatus.DISCOVERED
    assert outcome.session.batch_id == SYNTHETIC_BATCH_ID
    assert outcome.session.plan.item_keys == (SYNTHETIC_ITEM_KEY,)
    assert outcome.claimed.status is ItemStatus.CLAIMED
    assert outcome.claimed.item_key == SYNTHETIC_ITEM_KEY
    assert outcome.claimed.run_id == "run_1"
    assert outcome.heartbeat.run_id == "run_1"
    assert not (config.state_dir / "runs" / "run_1").exists()
    assert not (config.state_dir / "traces" / "run_1.jsonl").exists()

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        store = CampaignStore(config.state_dir, lock)
        assert store.read_manifest("campaign_1") == outcome.manifest
        assert store.read_ledger("campaign_1").items == {
            SYNTHETIC_ITEM_KEY: outcome.claimed
        }
        assert store.read_batches("campaign_1").active is not None
        assert store.read_heartbeat("campaign_1") == outcome.heartbeat
    finally:
        lock.release()


def test_fixed_preparation_rejects_campaign_reuse_without_overwriting_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    runner = AgentRunner(config)
    outcome = prepare_synthetic_campaign(
        runner,
        campaign_id="campaign_1",
        run_id="run_1",
        now=NOW,
    )
    campaign_dir = config.state_dir / "campaigns" / "campaign_1"
    before = {
        path.name: path.read_bytes()
        for path in campaign_dir.iterdir()
        if path.is_file()
    }

    with pytest.raises(CampaignStoreError, match="CAMPAIGN_ALREADY_EXISTS"):
        prepare_synthetic_campaign(
            runner,
            campaign_id="campaign_1",
            run_id="run_2",
            now=NOW,
        )

    after = {
        path.name: path.read_bytes()
        for path in campaign_dir.iterdir()
        if path.is_file()
    }
    assert after == before
    assert outcome.claimed.run_id == "run_1"
    replacement = runner.prepare(
        "Prove duplicate preparation released the lock",
        run_id="run_after_duplicate",
    )
    replacement.close()


def test_exact_observation_extracts_only_bounded_window_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad\n\nwindow_2 | Browser\n",
    )
    runner, prepared, session, desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )

    outcome = asyncio.run(
        execute_claimed_synthetic_observation_and_extraction(
            runner, prepared, session, now=NOW
        )
    )

    assert outcome.window_count == 2
    assert outcome.observed.status is ItemStatus.OBSERVED
    assert outcome.extracted.status is ItemStatus.EXTRACTED
    assert outcome.extracted.boundary == "extracted"
    assert outcome.extracted.code == "READ_ONLY_EXTRACTION_COMPLETED"
    assert outcome.extracted.content_digest is None
    assert len(desktop.tool_calls) == 1
    assert _read_item(config).status is ItemStatus.EXTRACTED
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "SUCCESS"
    encoded_record = json.dumps(record, sort_keys=True)
    assert "Notepad" not in encoded_record
    assert "Browser" not in encoded_record


def test_oversized_extraction_stops_after_observed_without_extracted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="x" * (MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS + 1),
    )
    runner, prepared, session, desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )

    with pytest.raises(
        CampaignObservationRuntimeError,
        match="CAMPAIGN_EXTRACTION_RESULT_TOO_LARGE",
    ):
        asyncio.run(
            execute_claimed_synthetic_observation_and_extraction(
                runner, prepared, session, now=NOW
            )
        )

    assert len(desktop.tool_calls) == 1
    assert _read_item(config).status is ItemStatus.OBSERVED
    assert read_run_record(config.state_dir, "run_1")["state"]["phase"] == "FAILED"


def test_exact_count_is_verified_and_committed_with_canonical_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad\nwindow_2 | Browser\n",
    )
    runner, prepared, session, desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )

    outcome = asyncio.run(
        execute_claimed_synthetic_item_through_commit(
            runner, prepared, session, now=NOW
        )
    )

    expected_digest = (
        "cd53d46573cc732039e324edd1a9fd3301df8629210efdecb67af9864d098882"
    )
    assert synthetic_window_count_digest(2) == expected_digest
    assert outcome.window_count == 2
    assert outcome.content_digest == expected_digest
    assert outcome.committed.status is ItemStatus.COMMITTED
    assert outcome.committed.boundary == "result_verified"
    assert outcome.committed.code == "READ_ONLY_RESULT_VERIFIED"
    assert outcome.committed.content_digest == expected_digest
    assert len(desktop.tool_calls) == 1
    durable = _read_item(config)
    assert durable.status is ItemStatus.COMMITTED
    assert durable.content_digest == expected_digest
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "SUCCESS"
    encoded_record = json.dumps(record, sort_keys=True)
    assert "Notepad" not in encoded_record
    assert "Browser" not in encoded_record


@pytest.mark.parametrize("value", [-1, True, "2", None])
def test_canonical_count_digest_rejects_non_counts(value: object) -> None:
    with pytest.raises(
        CampaignObservationRuntimeError,
        match="CAMPAIGN_COMMIT_RESULT_INVALID",
    ):
        synthetic_window_count_digest(value)  # type: ignore[arg-type]


def test_committed_item_finishes_batch_and_writes_deterministic_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad\nwindow_2 | Browser\n",
    )
    runner, prepared, session, desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )

    outcome = asyncio.run(
        execute_claimed_synthetic_item_through_handoff(
            runner, prepared, session, now=NOW
        )
    )

    assert outcome.stop_code == "ITEM_LIMIT"
    _assert_single_item_usage(outcome.usage)
    assert outcome.handoff["campaign_id"] == "campaign_1"
    assert outcome.handoff["last_run_id"] == "run_1"
    assert outcome.handoff["next_item_ordinal"] == 2
    assert outcome.handoff["completed_count"] == 1
    assert outcome.handoff["next_action"] == "resume_batch"
    assert (
        outcome.handoff["required_observation"]
        == "verify_current_page_and_account_state"
    )
    assert len(desktop.tool_calls) == 1

    batches, handoff, heartbeat = _read_finished_campaign(config)
    assert batches.active is None
    finished = batches.transitions[-1]
    assert finished.status.value == "FINISHED"
    assert finished.stop_code == "ITEM_LIMIT"
    assert finished.items_completed == 1
    assert finished.provider_turns == 0
    assert finished.tool_calls == 1
    assert finished.input_tokens == 0
    assert handoff == dict(outcome.handoff)
    assert heartbeat is not None
    assert heartbeat.run_id == "run_1"
    assert heartbeat.fresh_until == "2026-07-17T00:12:00+00:00"
    encoded = json.dumps(handoff, sort_keys=True)
    assert "Notepad" not in encoded
    assert "Browser" not in encoded


def test_persisted_claim_executes_without_prior_batch_session_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad\nwindow_2 | Browser",
    )
    _runner, prepared, _session, original_desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )
    prepared.close()
    desktop = FakeDesktopMCP(results=deque([result]))
    provider = FakeModelProvider(turns=deque())
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=FakeApprovalPort(),
        ),
    )

    outcome = asyncio.run(
        execute_persisted_claimed_synthetic_item_through_handoff(
            runner,
            campaign_id="campaign_1",
            run_id="run_1",
            now=NOW,
        )
    )

    assert outcome.committed.status is ItemStatus.COMMITTED
    assert outcome.window_count == 2
    _assert_single_item_usage(outcome.usage)
    assert outcome.handoff["last_run_id"] == "run_1"
    assert provider.calls == []
    assert desktop.discovery_calls == 1
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1
    assert original_desktop.discovery_calls == 0
    assert original_desktop.tool_calls == []


def test_persisted_claim_drift_fails_before_desktop_discovery_and_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
    )
    _runner, prepared, _session, _original_desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )
    store = prepared.campaign_store(config.state_dir)
    store.append(
        "campaign_1",
        ItemTransition(
            1,
            2,
            "synthetic:unexpected",
            ItemStatus.DISCOVERED,
            0,
            NOW.isoformat(timespec="seconds"),
        ),
    )
    prepared.close()
    desktop = FakeDesktopMCP()
    provider = FakeModelProvider(turns=deque())
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=FakeApprovalPort(),
        ),
    )

    with pytest.raises(
        CampaignObservationRuntimeError,
        match="CAMPAIGN_CLAIMED_STATE_INVALID",
    ):
        asyncio.run(
            execute_persisted_claimed_synthetic_item_through_handoff(
                runner,
                campaign_id="campaign_1",
                run_id="run_1",
                now=NOW,
            )
        )

    assert provider.calls == []
    assert desktop.discovery_calls == 0
    assert desktop.tool_calls == []
    assert desktop.close_calls == 1
    replacement = AgentRunner(config).prepare(
        "Prove the durable-claim lock was released",
        run_id="run_after_drift",
    )
    replacement.close()


def test_fresh_runner_resumes_only_from_durable_finished_handoff(
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
    handoff_outcome = asyncio.run(
        execute_claimed_synthetic_item_through_handoff(
            runner, prepared, session, now=NOW
        )
    )
    fresh_runner = AgentRunner(config)

    outcome = resume_finished_synthetic_campaign_after_restart(
        fresh_runner,
        campaign_id="campaign_1",
        replacement_run_id="run_2",
        now=NOW,
    )

    assert isinstance(outcome, CampaignRestartResumeOutcome)
    assert outcome.state.run_id == "run_2"
    assert outcome.state.task == SYNTHETIC_RESUME_TASK
    assert outcome.state.budgets.model_turns_used == 0
    assert outcome.state.budgets.tool_calls_used == 0
    assert outcome.handoff == handoff_outcome.handoff
    assert outcome.resume.state.value == "NO_ELIGIBLE_ITEMS"
    assert outcome.resume.item_keys == ()
    assert outcome.resume.finished_run_id == "run_1"
    assert outcome.resume.replacement_run_id == "run_2"
    assert outcome.heartbeat.run_id == "run_2"
    assert outcome.heartbeat.started_at == NOW.isoformat(timespec="seconds")
    assert desktop.tool_calls and len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        store = CampaignStore(config.state_dir, lock)
        assert store.read_heartbeat("campaign_1") == outcome.heartbeat
        assert store.read_handoff("campaign_1") == dict(handoff_outcome.handoff)
        assert store.read_batches("campaign_1").active is None
        assert store.read_manifest("campaign_1").status.value == "RUNNING"
    finally:
        lock.release()
    record = read_run_record(config.state_dir, "run_2")
    assert record["state"]["phase"] == "SUCCESS"
    assert record["state"]["metrics"]["model_calls"] == 0
    assert record["state"]["metrics"]["tool_calls"] == 0


def test_resume_only_cli_enters_the_real_durable_boundary_without_external_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import computer_use_agent.cli as agent_cli

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
    asyncio.run(
        execute_claimed_synthetic_item_through_handoff(
            runner, prepared, session, now=NOW
        )
    )
    config_path = tmp_path / "agent.toml"
    config_path.write_text(
        f'''\
[agent]
state_dir = "{config.state_dir.as_posix()}"
policy_version = "{config.policy_version}"

[provider]
name = "{config.provider.name}"
model = "{config.provider.model}"
context_window_tokens = {config.provider.context_window_tokens}
output_token_reserve = {config.provider.output_token_reserve}

[mcp]
executable = "{config.mcp.executable.as_posix()}"
args = []
cwd = "{config.mcp.cwd.as_posix()}"
environment = {{ CUMCP_ALLOWLIST = "notepad.exe" }}
''',
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: NOW)

    assert agent_cli.main(
        [
            "campaign",
            "resume-synthetic",
            "--config",
            str(config_path),
            "--campaign-id",
            "campaign_1",
            "--run-id",
            "run_2",
        ]
    ) == 0

    raw = capsys.readouterr().out
    assert json.loads(raw) == {
        "campaign_id": "campaign_1",
        "finished_run_id": "run_1",
        "next_item_ordinal": 2,
        "replacement_run_id": "run_2",
        "resume_state": "NO_ELIGIBLE_ITEMS",
    }
    assert "Notepad" not in raw
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        heartbeat = CampaignStore(config.state_dir, lock).read_heartbeat(
            "campaign_1"
        )
        assert heartbeat is not None
        assert heartbeat.run_id == "run_2"
    finally:
        lock.release()


def test_three_fixed_cli_commands_complete_one_synthetic_campaign_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import computer_use_agent.cli as agent_cli

    config = _config(tmp_path, monkeypatch)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(
        f'''\
[agent]
state_dir = "{config.state_dir.as_posix()}"
policy_version = "{config.policy_version}"

[provider]
name = "{config.provider.name}"
model = "{config.provider.model}"
context_window_tokens = {config.provider.context_window_tokens}
output_token_reserve = {config.provider.output_token_reserve}

[mcp]
executable = "{config.mcp.executable.as_posix()}"
args = []
cwd = "{config.mcp.cwd.as_posix()}"
environment = {{ CUMCP_ALLOWLIST = "notepad.exe" }}
''',
        encoding="utf-8",
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=_identity(),
                    tool_name=SYNTHETIC_OBSERVATION_TOOL,
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    sanitized_text="window_1 | Notepad",
                )
            ]
        )
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: NOW)
    monkeypatch.setattr(
        "computer_use_agent.desktop_mcp.StdioDesktopMCP",
        lambda _config: desktop,
    )

    shared = [
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
    ]
    assert agent_cli.main(
        ["campaign", "prepare-synthetic", *shared, "--run-id", "run_1"]
    ) == 0
    prepared_output = json.loads(capsys.readouterr().out)
    assert prepared_output == {
        "batch_id": SYNTHETIC_BATCH_ID,
        "campaign_id": "campaign_1",
        "campaign_kind": SYNTHETIC_CAMPAIGN_KIND,
        "item_key": SYNTHETIC_ITEM_KEY,
        "item_ordinal": 1,
        "item_status": "CLAIMED",
        "run_id": "run_1",
    }

    assert agent_cli.main(
        ["campaign", "run-claimed-synthetic", *shared, "--run-id", "run_1"]
    ) == 0
    executed_output = json.loads(capsys.readouterr().out)
    assert executed_output["item_status"] == "COMMITTED"
    assert executed_output["usage"]["provider_turns"] == 0
    assert executed_output["usage"]["tool_calls"] == 1
    assert executed_output["window_count"] == 1

    assert agent_cli.main(
        ["campaign", "resume-synthetic", *shared, "--run-id", "run_2"]
    ) == 0
    resumed_output = json.loads(capsys.readouterr().out)
    assert resumed_output == {
        "campaign_id": "campaign_1",
        "finished_run_id": "run_1",
        "next_item_ordinal": 2,
        "replacement_run_id": "run_2",
        "resume_state": "NO_ELIGIBLE_ITEMS",
    }
    assert desktop.discovery_calls == 1
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "SUCCESS"
    assert record["state"]["metrics"]["model_calls"] == 0
    assert record["state"]["metrics"]["tool_calls"] == 1
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        store = CampaignStore(config.state_dir, lock)
        item = store.read_ledger("campaign_1").items[SYNTHETIC_ITEM_KEY]
        assert item.status is ItemStatus.COMMITTED
        assert store.read_batches("campaign_1").active is None
        heartbeat = store.read_heartbeat("campaign_1")
        assert heartbeat is not None
        assert heartbeat.run_id == "run_2"
    finally:
        lock.release()


def test_restart_rejects_non_exact_durable_state_before_owner_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = ToolResult(
        identity=_identity(),
        tool_name=SYNTHETIC_OBSERVATION_TOOL,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad",
    )
    runner, prepared, session, _desktop, config = _claimed_runtime(
        tmp_path, monkeypatch, result
    )
    asyncio.run(
        execute_claimed_synthetic_item_through_handoff(
            runner, prepared, session, now=NOW
        )
    )
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        store = CampaignStore(config.state_dir, lock)
        store.append(
            "campaign_1",
            ItemTransition(
                1,
                2,
                "synthetic:unexpected",
                ItemStatus.DISCOVERED,
                0,
                NOW.isoformat(timespec="seconds"),
            ),
        )
        heartbeat_before = store.read_heartbeat("campaign_1")
    finally:
        lock.release()

    with pytest.raises(
        CampaignObservationRuntimeError,
        match="CAMPAIGN_RESTART_STATE_INVALID",
    ):
        resume_finished_synthetic_campaign_after_restart(
            AgentRunner(config),
            campaign_id="campaign_1",
            replacement_run_id="run_2",
            now=NOW,
        )

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        from computer_use_agent.campaign import CampaignStore

        assert (
            CampaignStore(config.state_dir, lock).read_heartbeat("campaign_1")
            == heartbeat_before
        )
    finally:
        lock.release()
    assert read_run_record(config.state_dir, "run_2")["state"]["phase"] == "FAILED"


def test_restart_rejects_invalid_new_run_identity_without_leaking_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    runner = AgentRunner(config)

    with pytest.raises(
        CampaignObservationRuntimeError,
        match="CAMPAIGN_RESTART_INPUT_INVALID",
    ):
        resume_finished_synthetic_campaign_after_restart(
            runner,
            campaign_id="campaign_1",
            replacement_run_id="invalid/run",
            now=NOW,
        )

    prepared = runner.prepare("Prove the lock remains available", run_id="run_3")
    prepared.close()


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
