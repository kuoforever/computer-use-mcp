from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.config import (
    AGENTIC_ACTIONS_MODE,
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.policy import HostPolicy, PolicyDisposition
from computer_use_agent.run_lock import RunLockedError
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.tool_registry import get_tool_spec
from computer_use_agent.types import LedgerEventKind


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "read_only",
    state_name: str = "test-state",
) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / state_name,
        policy_version="phase2",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            mode=mode,
            require_approval_for_actions=mode != AGENTIC_ACTIONS_MODE,
        ),
    )


def test_host_policy_allows_observation_and_denies_read_only_actions() -> None:
    policy = HostPolicy.from_config("phase2", PolicyConfig())

    assert policy.disposition(get_tool_spec("ui_snapshot")) is PolicyDisposition.ALLOW
    assert policy.disposition(get_tool_spec("click")) is PolicyDisposition.DENY
    assert policy.initial_budget().max_model_turns == 12


def test_application_lock_root_is_frozen_with_the_validated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    original_root = config.application_state_dir

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "DifferentLocalAppData"))

    assert config.application_state_dir == original_root


def test_approved_actions_policy_still_requires_approval() -> None:
    policy = HostPolicy.from_config("phase2", PolicyConfig(mode=APPROVED_ACTIONS_MODE))

    assert policy.disposition(get_tool_spec("click")) is PolicyDisposition.APPROVAL_REQUIRED
    assert policy.disposition(get_tool_spec("type")) is PolicyDisposition.DENY
    assert (
        policy.disposition(
            get_tool_spec("type"),
            satisfied_safety_baselines=frozenset(
                {"typed_text_audit_redaction"}
            ),
        )
        is PolicyDisposition.APPROVAL_REQUIRED
    )


def test_agentic_actions_policy_allows_only_safety_ready_actions() -> None:
    policy = HostPolicy.from_config(
        "phase2",
        PolicyConfig(
            mode=AGENTIC_ACTIONS_MODE,
            require_approval_for_actions=False,
        ),
    )

    assert policy.disposition(get_tool_spec("click")) is PolicyDisposition.ALLOW
    assert policy.disposition(get_tool_spec("type")) is PolicyDisposition.DENY
    assert (
        policy.disposition(
            get_tool_spec("type"),
            satisfied_safety_baselines=frozenset({"typed_text_audit_redaction"}),
        )
        is PolicyDisposition.ALLOW
    )


def test_prepare_builds_bounded_state_without_calling_any_external_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    approvals = FakeApprovalPort()
    runner = AgentRunner(
        config,
        RunnerPorts(provider=provider, desktop=desktop, approvals=approvals),
    )
    task = "inspect secret task text"

    with runner.prepare(task, run_id="run_test") as prepared:
        state = prepared.state
        assert state.run_id == "run_test"
        assert state.task == task
        assert state.observation_epoch == 0
        assert state.budgets.max_tool_calls == config.policy.max_tool_calls
        assert state.event_log[0].kind is LedgerEventKind.USER_TASK
        assert state.event_log[0].payload == {"task_length": len(task)}
        assert task not in repr(state.event_log[0].payload)
        assert (config.application_state_dir / "active-run.lock").exists()
        assert provider.calls == []
        assert desktop.discovery_calls == 0
        assert desktop.tool_calls == []
        assert approvals.requests == []

    lock_path = config.application_state_dir / "active-run.lock"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == {"released": True}


def test_prepare_fails_when_another_run_holds_the_state_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = AgentRunner(_config(tmp_path, monkeypatch))
    first = runner.prepare("first", run_id="run_1")

    with pytest.raises(RunLockedError):
        runner.prepare("second", run_id="run_2")

    first.close()


def test_different_state_subdirectories_still_share_one_desktop_run_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_runner = AgentRunner(_config(tmp_path, monkeypatch, state_name="one"))
    second_runner = AgentRunner(_config(tmp_path, monkeypatch, state_name="two"))
    first = first_runner.prepare("first", run_id="run_1")

    with pytest.raises(RunLockedError):
        second_runner.prepare("second", run_id="run_2")

    first.close()


def test_invalid_task_fails_before_creating_state_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    runner = AgentRunner(config)

    with pytest.raises(ValueError, match="non-empty"):
        runner.prepare("   ")

    assert not config.state_dir.exists()
