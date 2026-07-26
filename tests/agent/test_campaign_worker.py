from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from computer_use_agent.campaign import CampaignManifest, CampaignStore
from computer_use_agent.campaign_worker import (
    CampaignWorker,
    CampaignWorkerError,
    CampaignWorkerRegistry,
    application_campaign_worker,
    default_campaign_worker_registry,
    execute_claimed_campaign_item,
    resume_campaign_batch,
    start_campaign_batch,
)
from computer_use_agent.application_worker_catalog import ApplicationWorkerSpec
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=(local / "computer-use-agent" / "worker").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "unused-worker"),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(
            max_model_turns=0,
            max_tool_calls=1,
            max_side_effects=0,
        ),
    )


def _create_manifest(config: AgentConfig, *, kind: str) -> None:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        CampaignStore(config.state_dir, lock).create(
            CampaignManifest(
                campaign_id="campaign_1",
                kind=kind,
                policy_digest="a" * 64,
                schema_digest="b" * 64,
                created_at=NOW.isoformat(timespec="seconds"),
                updated_at=NOW.isoformat(timespec="seconds"),
            )
        )
    finally:
        lock.release()


def _worker(calls: list[tuple[str, str, str]]) -> CampaignWorker:
    def start(runner, *, campaign_id, run_id, now):
        calls.append(("start", campaign_id, run_id))
        return SimpleNamespace(campaign_id=campaign_id, run_id=run_id)

    async def execute(runner, *, campaign_id, run_id, now):
        calls.append(("execute", campaign_id, run_id))
        return SimpleNamespace(campaign_id=campaign_id, run_id=run_id)

    def resume(runner, *, campaign_id, replacement_run_id, now):
        calls.append(("resume", campaign_id, replacement_run_id))
        return SimpleNamespace(
            campaign_id=campaign_id,
            run_id=replacement_run_id,
        )

    def summarize(value):
        return {
            "campaign_id": value.campaign_id,
            "run_id": value.run_id,
        }

    return CampaignWorker(
        kind="reviewed_test_worker",
        start=start,
        execute=execute,
        resume=resume,
        summarize_start=summarize,
        summarize_execute=summarize,
        summarize_resume=summarize,
    )


def test_manifest_kind_routes_all_operations_without_caller_selector(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _create_manifest(config, kind="reviewed_test_worker")
    calls: list[tuple[str, str, str]] = []
    registry = CampaignWorkerRegistry((_worker(calls),))
    runner = AgentRunner(config)

    started = start_campaign_batch(
        runner,
        campaign_id="campaign_1",
        run_id="run_1",
        now=NOW,
        registry=registry,
    )
    executed = asyncio.run(
        execute_claimed_campaign_item(
            runner,
            campaign_id="campaign_1",
            run_id="run_1",
            now=NOW,
            registry=registry,
        )
    )
    resumed = resume_campaign_batch(
        runner,
        campaign_id="campaign_1",
        replacement_run_id="run_2",
        now=NOW,
        registry=registry,
    )

    assert calls == [
        ("start", "campaign_1", "run_1"),
        ("execute", "campaign_1", "run_1"),
        ("resume", "campaign_1", "run_2"),
    ]
    assert started.operation == "start"
    assert executed.operation == "execute"
    assert resumed.operation == "resume"
    assert resumed.campaign_kind == "reviewed_test_worker"
    assert dict(resumed.summary) == {
        "campaign_id": "campaign_1",
        "run_id": "run_2",
    }


def test_unregistered_manifest_kind_fails_closed_before_worker_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _create_manifest(config, kind="unregistered_kind")
    calls: list[tuple[str, str, str]] = []

    with pytest.raises(
        CampaignWorkerError,
        match="^CAMPAIGN_WORKER_KIND_UNSUPPORTED$",
    ):
        start_campaign_batch(
            AgentRunner(config),
            campaign_id="campaign_1",
            run_id="run_1",
            now=NOW,
            registry=CampaignWorkerRegistry((_worker(calls),)),
        )

    assert calls == []


def test_registry_rejects_duplicate_kind() -> None:
    worker = _worker([])
    with pytest.raises(ValueError, match="campaign workers are invalid"):
        CampaignWorkerRegistry((worker, worker))


def test_default_registry_contains_legacy_boss_and_all_matrix_workers() -> None:
    registry = default_campaign_worker_registry()
    assert len(registry.kinds) == 20
    assert "boss_saved_job_read_only" in registry.kinds
    assert "boss_saved_job_review" in registry.kinds
    assert registry.resolve("boss_saved_job_read_only").provider_required is False
    assert registry.resolve("enterprise_finance").provider_required is True


def test_new_scenario_composes_reviewed_capabilities_without_core_changes() -> None:
    spec = ApplicationWorkerSpec(
        scenario_id="custom_portal_review",
        kind="custom_portal_review",
        name="Custom portal review",
        identity_dimensions=("tenant", "record_id"),
        result_fields=("summary", "status"),
        observation_ladder=("ui_snapshot", "document_text", "ocr"),
        navigation_tools=("activate_window", "click", "key"),
        optional_effects=(),
        maximum_risk="read_only",
        capability_names=(
            "window_topology",
            "structured_observation",
            "semantic_document_observation",
            "stable_identity_revalidation",
            "challenge_detection",
            "window_activation",
            "pointer_navigation",
            "keyboard_navigation",
            "post_action_verification",
        ),
    )
    worker = application_campaign_worker(spec)
    registry = CampaignWorkerRegistry((worker,))

    assert registry.kinds == ("custom_portal_review",)
    assert registry.resolve("custom_portal_review").provider_required
