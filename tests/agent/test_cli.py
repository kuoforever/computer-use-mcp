from __future__ import annotations

import json
import os
import subprocess
import sys
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

import computer_use_agent.cli as agent_cli
from computer_use_agent.cli import main


def _config_text(tmp_path: Path) -> tuple[str, Path]:
    state_dir = tmp_path / "LocalAppData" / "computer-use-agent" / "cli-state"
    text = f'''\
[agent]
state_dir = "{state_dir.as_posix()}"
policy_version = "phase2"

[provider]
name = "openai"
model = "test-model"
context_window_tokens = 128000
output_token_reserve = 1024

[mcp]
executable = "{(tmp_path / "computer-use-mcp.exe").as_posix()}"
args = []
cwd = "{tmp_path.as_posix()}"
environment = {{ CUMCP_ALLOWLIST = "notepad.exe" }}
'''
    return text, state_dir


class RecordingProgress:
    def __init__(self) -> None:
        self.events: list[object] = []

    def wake(self) -> None:
        self.events.append("wake")

    def on_phase(self, phase: object) -> None:
        self.events.append(phase)

    def estop(self) -> None:
        self.events.append("estop")

    def release(self) -> None:
        self.events.append("release")


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("ABORTED", ["estop"]),
        ("HUMAN_ACTIVE", ["release"]),
        (None, []),
        ("MCP_TIMEOUT_BEFORE_DISPATCH", []),
    ],
)
def test_recovery_presence_closes_only_for_desktop_authority_loss(
    code: str | None,
    expected: list[str],
) -> None:
    from computer_use_agent.presence_lifecycle import FailSilentLifecycle
    from computer_use_agent.types import (
        CallIdentity,
        DispatchCertainty,
        ToolResult,
        ToolResultStatus,
    )

    presence = RecordingProgress()
    result = ToolResult(
        CallIdentity("run_1", "turn_1", "call_1"),
        "list_windows",
        (
            ToolResultStatus.REJECTED
            if code in {"ABORTED", "HUMAN_ACTIVE"}
            else ToolResultStatus.TRANSPORT_ERROR
            if code is not None
            else ToolResultStatus.SUCCESS
        ),
        (
            DispatchCertainty.NOT_DISPATCHED
            if code is not None
            else DispatchCertainty.DISPATCHED
        ),
        code=code,
    )

    agent_cli._apply_recovery_presence_result(
        FailSilentLifecycle(presence),
        result,
    )

    assert presence.events == expected


@pytest.mark.parametrize(
    "arguments",
    [
        ["--help"],
        ["run", "--help"],
        ["ask", "--help"],
        ["plan", "--help"],
        ["plan", "run", "--help"],
        ["eval", "--help"],
        ["release", "preflight", "--help"],
        ["trace", "--help"],
        ["report", "--help"],
        ["resume", "--help"],
        ["cancel", "--help"],
        ["recovery", "--help"],
        ["recover", "--help"],
        ["campaign", "--help"],
        ["campaign", "prepare-synthetic", "--help"],
        ["campaign", "resume-synthetic", "--help"],
        ["campaign", "run-claimed-synthetic", "--help"],
        ["campaign", "prepare-boss-discovery", "--help"],
        ["campaign", "observe-boss-page", "--help"],
        ["campaign", "start-boss-batch", "--help"],
        ["campaign", "run-claimed-boss", "--help"],
        ["campaign", "resume-boss-batch", "--help"],
        ["campaign", "start-boss-semantic-batch", "--help"],
        ["campaign", "run-claimed-boss-semantic", "--help"],
        ["campaign", "resume-boss-semantic-batch", "--help"],
        ["campaign", "start", "--help"],
        ["campaign", "run-claimed", "--help"],
        ["campaign", "resume", "--help"],
        ["campaign", "prepare-application", "--help"],
        ["campaign", "prepare-discovery", "--help"],
        ["campaign", "observe-discovery-page", "--help"],
        ["remember", "add", "--help"],
        ["remember", "list", "--help"],
        ["remember", "delete", "--help"],
        ["config", "validate", "--help"],
        ["config", "init", "--help"],
        ["config", "doctor", "--help"],
    ],
)
def test_cli_help_needs_no_config_provider_or_desktop(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(arguments)

    assert raised.value.code == 0


def test_cli_without_a_command_prints_help_and_returns_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    assert "Guarded Desktop Agent" in capsys.readouterr().out


def test_application_campaign_prepare_cli_persists_only_explicit_stable_items(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    items_path = tmp_path / "items.json"
    items_path.write_text(
        json.dumps(["doc:fixture:section_1", "doc:fixture:section_2"]),
        encoding="utf-8",
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "prepare-application",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_docs",
        "--run-id",
        "prepare_docs",
        "--scenario",
        "A2",
        "--items-file",
        str(items_path),
    ]

    assert main(arguments) == 0
    assert json.loads(capsys.readouterr().out) == {
        "campaign_id": "campaign_docs",
        "campaign_kind": "google_docs_section_review",
        "item_count": 2,
        "run_id": "prepare_docs",
        "scenario_id": "A2",
    }


def test_plan_run_and_ask_route_to_one_runtime_with_distinct_output_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "agent.toml"
    captured: list[tuple[Path, str, bool]] = []

    def fake_run(path: Path, task: str, *, json_output: bool = True) -> int:
        captured.append((path, task, json_output))
        return 0

    monkeypatch.setattr(agent_cli, "_run_planned_observation", fake_run)

    assert main(["plan", "run", "--config", str(config_path), "--task", "Inspect"]) == 0
    assert main(["ask", "--config", str(config_path), "--task", "Summarize"]) == 0
    assert (
        main(
            [
                "ask",
                "--config",
                str(config_path),
                "--task",
                "Inspect",
                "--json",
            ]
        )
        == 0
    )
    assert captured == [
        (config_path, "Inspect", True),
        (config_path, "Summarize", False),
        (config_path, "Inspect", True),
    ]


def test_config_init_creates_an_immediately_valid_desktop_ask_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from computer_use_agent.config import load_agent_config

    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp_executable = tmp_path / "Scripts" / "guarded-desktop-mcp.exe"
    mcp_executable.parent.mkdir()
    mcp_executable.write_bytes(b"")
    output = tmp_path / "agent.toml"
    arguments = [
        "config",
        "init",
        "--provider",
        "openai",
        "--model",
        "reviewed-model",
        "--mcp-executable",
        str(mcp_executable),
        "--output",
        str(output),
    ]

    assert main(arguments) == 0

    result = json.loads(capsys.readouterr().out)
    config = load_agent_config(output)
    assert result["config_valid"] is True
    assert config.provider.name == "openai"
    assert config.provider.model == "reviewed-model"
    assert config.policy.mode == "read_only"
    assert config.continuation.enabled is True
    assert config.mcp.executable == mcp_executable.resolve()
    assert config.mcp.cwd == config.state_dir
    assert config.state_dir.is_dir()

    assert main(arguments) == 2
    assert capsys.readouterr().err.strip() == "error: CONFIG_OUTPUT_EXISTS"


def test_plan_run_requires_wal_before_loading_provider_or_desktop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")

    assert main(["plan", "run", "--config", str(config_path), "--task", "Inspect"]) == 2

    assert capsys.readouterr().err.strip() == ("error: PLANNED_OBSERVATION_WAL_REQUIRED")
    assert not state_dir.exists()


def test_release_preflight_cli_returns_the_report_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {"passed": False, "gates": {"ruff": {"passed": False}}}
    captured: list[tuple[Path, Path, Path]] = []

    def fake_preflight(root: Path, artifacts: Path, report: Path) -> dict[str, object]:
        captured.append((root, artifacts, report))
        return expected

    monkeypatch.setattr("computer_use_agent.release.run_release_preflight", fake_preflight)
    root = tmp_path / "root"
    artifacts = tmp_path / "artifacts"
    report = tmp_path / "report.json"

    assert (
        main(
            [
                "release",
                "preflight",
                "--root",
                str(root),
                "--artifacts",
                str(artifacts),
                "--report",
                str(report),
            ]
        )
        == 1
    )

    assert captured == [(root, artifacts, report)]
    assert json.loads(capsys.readouterr().out) == expected


def test_config_validation_has_no_filesystem_or_external_side_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    path = tmp_path / "agent.toml"
    path.write_text(text, encoding="utf-8")

    assert main(["config", "validate", "--config", str(path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["valid"] is True
    assert output["policy_mode"] == "read_only"
    assert not state_dir.exists()


def test_dry_run_outputs_only_safe_metadata_and_releases_the_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    path = tmp_path / "agent.toml"
    path.write_text(text, encoding="utf-8")
    task = "task-secret-value"

    assert main(["run", "--config", str(path), "--task", task, "--dry-run"]) == 0

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert task not in raw
    assert output["dry_run"] is True
    assert output["task_length"] == len(task)
    lock_path = state_dir.parent / "active-run.lock"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == {"released": True}


def test_run_memory_scope_is_explicit_and_dry_run_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "agent.toml"
    captured: list[tuple[Path, str, str | None]] = []

    def fake_run(path: Path, task: str, scope: str | None = None) -> int:
        captured.append((path, task, scope))
        return 0

    monkeypatch.setattr(agent_cli, "_run_live", fake_run)

    assert (
        main(
            [
                "run",
                "--config",
                str(config_path),
                "--task",
                "Inspect",
                "--memory-scope",
                "app:notepad",
            ]
        )
        == 0
    )
    assert captured == [(config_path, "Inspect", "app:notepad")]

    assert (
        main(
            [
                "run",
                "--config",
                str(config_path),
                "--task",
                "Inspect",
                "--dry-run",
                "--memory-scope",
                "global",
            ]
        )
        == 2
    )
    assert "DRY_RUN_MEMORY_CONTEXT_UNAVAILABLE" in capsys.readouterr().err


def test_synthetic_campaign_resume_cli_has_no_task_or_selector_and_prints_safe_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)

    def fake_resume(
        runner: object,
        *,
        campaign_id: str,
        replacement_run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, replacement_run_id, now))
        return SimpleNamespace(
            resume=SimpleNamespace(
                campaign_id=campaign_id,
                finished_run_id="run_1",
                next_item_ordinal=2,
                replacement_run_id=replacement_run_id,
                state=SimpleNamespace(value="NO_ELIGIBLE_ITEMS"),
            )
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.campaign_observation_runtime."
        "resume_finished_synthetic_campaign_after_restart",
        fake_resume,
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)

    parsed = agent_cli.build_parser().parse_args(
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
    )
    assert not hasattr(parsed, "task")
    assert not hasattr(parsed, "item_key")

    assert (
        main(
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
        )
        == 0
    )

    assert len(captured) == 1
    runner, campaign_id, replacement_run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is None
    assert campaign_id == "campaign_1"
    assert replacement_run_id == "run_2"
    assert captured_now == now
    assert json.loads(capsys.readouterr().out) == {
        "campaign_id": "campaign_1",
        "finished_run_id": "run_1",
        "next_item_ordinal": 2,
        "replacement_run_id": "run_2",
        "resume_state": "NO_ELIGIBLE_ITEMS",
    }


def test_synthetic_campaign_prepare_cli_has_no_selector_and_prints_safe_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)

    def fake_prepare(
        runner: object,
        *,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, run_id, now))
        return SimpleNamespace(
            manifest=SimpleNamespace(
                campaign_id=campaign_id,
                kind="synthetic_read_only",
            ),
            session=SimpleNamespace(batch_id="synthetic_batch_1", run_id=run_id),
            claimed=SimpleNamespace(
                item_key="synthetic:list_windows",
                ordinal=1,
                status=SimpleNamespace(value="CLAIMED"),
            ),
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.campaign_observation_runtime.prepare_synthetic_campaign",
        fake_prepare,
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "prepare-synthetic",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "run_1",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in (
        "task",
        "item_key",
        "campaign_kind",
        "batch_id",
        "lease_seconds",
    ):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0

    assert len(captured) == 1
    runner, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is None
    assert campaign_id == "campaign_1"
    assert run_id == "run_1"
    assert captured_now == now
    assert json.loads(capsys.readouterr().out) == {
        "batch_id": "synthetic_batch_1",
        "campaign_id": "campaign_1",
        "campaign_kind": "synthetic_read_only",
        "item_key": "synthetic:list_windows",
        "item_ordinal": 1,
        "item_status": "CLAIMED",
        "run_id": "run_1",
    }


def test_claimed_synthetic_campaign_cli_uses_desktop_with_provider_forbidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from computer_use_agent.fakes import FakeDesktopMCP

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)
    desktop = FakeDesktopMCP()

    async def fake_execute(
        runner: object,
        *,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, run_id, now))
        return SimpleNamespace(
            state=SimpleNamespace(run_id=run_id),
            committed=SimpleNamespace(
                item_key="synthetic:list_windows",
                status=SimpleNamespace(value="COMMITTED"),
            ),
            content_digest="a" * 64,
            handoff={"next_item_ordinal": 2},
            stop_code="ITEM_LIMIT",
            usage=SimpleNamespace(
                elapsed_seconds=0,
                input_tokens=0,
                provider_turns=0,
                tool_calls=1,
            ),
            window_count=2,
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.desktop_mcp.StdioDesktopMCP",
        lambda _config: desktop,
    )
    monkeypatch.setattr(
        "computer_use_agent.campaign_observation_runtime."
        "execute_persisted_claimed_synthetic_item_through_handoff",
        fake_execute,
    )
    presence = RecordingProgress()
    progress = RecordingProgress()
    monkeypatch.setattr(agent_cli, "_presence_lifecycle", lambda _config: presence)
    monkeypatch.setattr(agent_cli, "_progress_lifecycle", lambda _config: progress)
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "run-claimed-synthetic",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "run_1",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    assert not hasattr(parsed, "task")
    assert not hasattr(parsed, "item_key")

    assert main(arguments) == 0

    assert len(captured) == 1
    runner, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is not None
    assert runner.ports.desktop is desktop
    assert isinstance(runner.ports.provider, agent_cli._ForbiddenCampaignProvider)
    assert runner.ports.presence is presence
    assert campaign_id == "campaign_1"
    assert run_id == "run_1"
    assert captured_now == now
    assert progress.events == ["wake", "release"]
    assert json.loads(capsys.readouterr().out) == {
        "campaign_id": "campaign_1",
        "content_digest": "a" * 64,
        "item_key": "synthetic:list_windows",
        "item_status": "COMMITTED",
        "next_item_ordinal": 2,
        "run_id": "run_1",
        "stop_code": "ITEM_LIMIT",
        "usage": {
            "elapsed_seconds": 0,
            "input_tokens": 0,
            "provider_turns": 0,
            "tool_calls": 1,
        },
        "window_count": 2,
    }


def test_boss_discovery_prepare_cli_has_no_selector_or_external_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)

    def fake_prepare(
        runner: object,
        *,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, run_id, now))
        return SimpleNamespace(
            campaign_id=campaign_id,
            campaign_kind="boss_saved_job_read_only",
            run_id=run_id,
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.boss_campaign_observation_runtime.prepare_boss_discovery_campaign",
        fake_prepare,
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "prepare-boss-discovery",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "prepare_1",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in ("task", "item_key", "url", "page", "scope", "campaign_kind"):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0
    runner, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is None
    assert (campaign_id, run_id, captured_now) == ("campaign_1", "prepare_1", now)
    assert json.loads(capsys.readouterr().out) == {
        "campaign_id": "campaign_1",
        "campaign_kind": "boss_saved_job_read_only",
        "discovered_count": 0,
        "run_id": "prepare_1",
    }


@pytest.mark.parametrize(
    "command",
    [
        "start-boss-semantic-batch",
        "run-claimed-boss-semantic",
        "resume-boss-semantic-batch",
    ],
)
def test_boss_semantic_cli_has_no_free_form_or_item_selector(
    command: str,
    tmp_path: Path,
) -> None:
    parsed = agent_cli.build_parser().parse_args(
        [
            "campaign",
            command,
            "--config",
            str(tmp_path / "agent.toml"),
            "--campaign-id",
            "campaign_1",
            "--run-id",
            "semantic_run_1",
        ]
    )

    for forbidden in (
        "task",
        "item_key",
        "url",
        "page",
        "scope",
        "campaign_kind",
        "batch_id",
        "classification",
        "classification_policy",
    ):
        assert not hasattr(parsed, forbidden)


def test_discovery_prepare_cli_accepts_only_a_registered_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    captured: list[tuple[object, str, str, str, datetime]] = []
    now = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)

    def fake_prepare(
        runner: object,
        *,
        campaign_kind: str,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_kind, campaign_id, run_id, now))
        return SimpleNamespace(
            campaign_id=campaign_id,
            campaign_kind=campaign_kind,
            adapter_id="incident_queue_rows",
            run_id=run_id,
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.application_discovery_runtime."
        "prepare_application_discovery_campaign",
        fake_prepare,
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "prepare-discovery",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "prepare_1",
        "--kind",
        "enterprise_incident",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in ("task", "item_key", "url", "page", "scope", "items_file"):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0
    runner, campaign_kind, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is None
    assert (campaign_kind, campaign_id, run_id, captured_now) == (
        "enterprise_incident",
        "campaign_1",
        "prepare_1",
        now,
    )
    assert json.loads(capsys.readouterr().out) == {
        "adapter_id": "incident_queue_rows",
        "campaign_id": "campaign_1",
        "campaign_kind": "enterprise_incident",
        "discovered_count": 0,
        "run_id": "prepare_1",
    }

    with pytest.raises(SystemExit) as raised:
        agent_cli.build_parser().parse_args(
            [
                "campaign",
                "prepare-discovery",
                "--config",
                str(config_path),
                "--campaign-id",
                "campaign_1",
                "--run-id",
                "prepare_2",
                "--kind",
                "google_docs_section_review",
            ]
        )
    assert raised.value.code == 2


def test_discovery_page_cli_uses_one_desktop_with_provider_forbidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from computer_use_agent.fakes import FakeDesktopMCP

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 26, 6, 0, tzinfo=timezone.utc)
    desktop = FakeDesktopMCP()

    async def fake_execute(
        runner: object,
        *,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, run_id, now))
        return SimpleNamespace(
            state=SimpleNamespace(
                run_id=run_id,
                budgets=SimpleNamespace(tool_calls_used=1),
            ),
            discovery=SimpleNamespace(
                adapter_id="incident_queue_rows",
                campaign_kind="enterprise_incident",
                discovered_count=2,
                duplicate_count=1,
                new_item_keys=("incident:ticket:INC-004822",),
                pass_sequence=2,
                added_nothing=False,
            ),
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.desktop_mcp.StdioDesktopMCP",
        lambda _config: desktop,
    )
    monkeypatch.setattr(
        "computer_use_agent.application_discovery_runtime."
        "execute_application_discovery_pass",
        fake_execute,
    )
    presence = RecordingProgress()
    progress = RecordingProgress()
    monkeypatch.setattr(agent_cli, "_presence_lifecycle", lambda _config: presence)
    monkeypatch.setattr(agent_cli, "_progress_lifecycle", lambda _config: progress)
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "observe-discovery-page",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "run_1",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in ("task", "item_key", "url", "page", "scope", "kind"):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0
    runner, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is not None
    assert runner.ports.desktop is desktop
    assert isinstance(runner.ports.provider, agent_cli._ForbiddenCampaignProvider)
    assert runner.ports.presence is presence
    assert (campaign_id, run_id, captured_now) == ("campaign_1", "run_1", now)
    assert progress.events == ["wake", "release"]
    assert json.loads(capsys.readouterr().out) == {
        "adapter_id": "incident_queue_rows",
        "campaign_id": "campaign_1",
        "campaign_kind": "enterprise_incident",
        "discovered_count": 2,
        "duplicate_count": 1,
        "new_item_count": 1,
        "pass_added_nothing": False,
        "pass_sequence": 2,
        "run_id": "run_1",
        "tool_calls": 1,
    }


def test_boss_page_cli_uses_one_desktop_with_provider_forbidden(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from computer_use_agent.fakes import FakeDesktopMCP

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 19, 4, 0, tzinfo=timezone.utc)
    desktop = FakeDesktopMCP()

    async def fake_execute(
        runner: object,
        *,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, run_id, now))
        return SimpleNamespace(
            state=SimpleNamespace(
                run_id=run_id,
                budgets=SimpleNamespace(tool_calls_used=1),
            ),
            discovery=SimpleNamespace(
                discovered_count=2,
                duplicate_count=1,
                new_item_keys=("boss:job:publicjob002",),
                pass_sequence=2,
                added_nothing=False,
            ),
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.desktop_mcp.StdioDesktopMCP",
        lambda _config: desktop,
    )
    monkeypatch.setattr(
        "computer_use_agent.boss_campaign_observation_runtime.execute_boss_discovery_page",
        fake_execute,
    )
    presence = RecordingProgress()
    progress = RecordingProgress()
    monkeypatch.setattr(agent_cli, "_presence_lifecycle", lambda _config: presence)
    monkeypatch.setattr(agent_cli, "_progress_lifecycle", lambda _config: progress)
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "observe-boss-page",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "run_1",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in ("task", "item_key", "url", "page", "scope"):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0
    runner, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is not None
    assert runner.ports.desktop is desktop
    assert isinstance(runner.ports.provider, agent_cli._ForbiddenCampaignProvider)
    assert runner.ports.presence is presence
    assert (campaign_id, run_id, captured_now) == ("campaign_1", "run_1", now)
    assert progress.events == ["wake", "release"]
    assert json.loads(capsys.readouterr().out) == {
        "campaign_id": "campaign_1",
        "discovered_count": 2,
        "duplicate_count": 1,
        "new_item_count": 1,
        "pass_sequence": 2,
        "pass_added_nothing": False,
        "run_id": "run_1",
        "tool_calls": 1,
    }


def test_boss_batch_start_cli_has_no_item_selector_or_external_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)

    def fake_start(
        runner: object,
        *,
        campaign_id: str,
        run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, run_id, now))
        return SimpleNamespace(
            batch_id="boss_batch_0123456789abcdef",
            campaign_id=campaign_id,
            claimed_item_ordinal=1,
            discovered_count=25,
            discovery_pass_count=2,
            lease_expires_at="2026-07-23T14:05:00+00:00",
            planned_item_count=20,
            run_id=run_id,
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.boss_campaign_batch_runtime.start_boss_read_only_batch",
        fake_start,
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "start-boss-batch",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "boss_run_1",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in (
        "task",
        "item_key",
        "url",
        "page",
        "scope",
        "campaign_kind",
        "batch_id",
    ):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0
    runner, campaign_id, run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is None
    assert (campaign_id, run_id, captured_now) == ("campaign_1", "boss_run_1", now)
    assert json.loads(capsys.readouterr().out) == {
        "batch_id": "boss_batch_0123456789abcdef",
        "campaign_id": "campaign_1",
        "claimed_item_ordinal": 1,
        "discovered_count": 25,
        "discovery_pass_count": 2,
        "lease_expires_at": "2026-07-23T14:05:00+00:00",
        "planned_item_count": 20,
        "run_id": "boss_run_1",
    }


def test_boss_batch_resume_cli_has_no_item_selector_or_external_ports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from datetime import datetime, timezone
    from types import SimpleNamespace

    captured: list[tuple[object, str, str, datetime]] = []
    now = datetime(2026, 7, 23, 14, 5, tzinfo=timezone.utc)

    def fake_resume(
        runner: object,
        *,
        campaign_id: str,
        replacement_run_id: str,
        now: datetime,
    ) -> object:
        captured.append((runner, campaign_id, replacement_run_id, now))
        return SimpleNamespace(
            batch_id="boss_resume_0123456789abcdef",
            campaign_id=campaign_id,
            claimed_item_ordinal=2,
            lease_expires_at="2026-07-23T14:10:00+00:00",
            planned_item_count=19,
            prior_run_id="boss_run_1",
            replacement_run_id=replacement_run_id,
        )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(
        "computer_use_agent.boss_campaign_restart_runtime."
        "resume_finished_boss_batch_after_restart",
        fake_resume,
    )
    monkeypatch.setattr(agent_cli, "_campaign_now", lambda: now)
    arguments = [
        "campaign",
        "resume-boss-batch",
        "--config",
        str(config_path),
        "--campaign-id",
        "campaign_1",
        "--run-id",
        "boss_run_2",
    ]
    parsed = agent_cli.build_parser().parse_args(arguments)
    for forbidden in (
        "task",
        "item_key",
        "url",
        "page",
        "scope",
        "campaign_kind",
        "batch_id",
        "prior_run_id",
    ):
        assert not hasattr(parsed, forbidden)

    assert main(arguments) == 0
    runner, campaign_id, replacement_run_id, captured_now = captured[0]
    assert isinstance(runner, agent_cli.AgentRunner)
    assert runner.ports is None
    assert (campaign_id, replacement_run_id, captured_now) == (
        "campaign_1",
        "boss_run_2",
        now,
    )
    assert json.loads(capsys.readouterr().out) == {
        "batch_id": "boss_resume_0123456789abcdef",
        "campaign_id": "campaign_1",
        "claimed_item_ordinal": 2,
        "lease_expires_at": "2026-07-23T14:10:00+00:00",
        "planned_item_count": 19,
        "prior_run_id": "boss_run_1",
        "run_id": "boss_run_2",
    }


def test_non_dry_run_with_missing_config_fails_before_creating_a_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist.toml"

    assert main(["run", "--config", str(missing), "--task", "secret"]) == 2

    captured = capsys.readouterr()
    assert "does-not-exist" in captured.err
    assert not missing.exists()


def test_agent_foundation_imports_no_server_provider_or_mcp_runtime() -> None:
    script = (
        "import sys; import computer_use_agent.cli; "
        "forbidden=('computer_use_mcp','openai','anthropic','mcp'); "
        "loaded=[name for name in sys.modules if name.split('.')[0] in forbidden]; "
        "raise SystemExit(1 if loaded else 0)"
    )

    result = subprocess.run([sys.executable, "-c", script], check=False)

    assert result.returncode == 0


def test_eval_cli_runs_offline_cases_and_writes_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cases = Path(__file__).parents[2] / "evals" / "cases"
    report_path = tmp_path / "reports" / "report.json"

    assert main(["eval", "--cases", str(cases), "--report", str(report_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["passed"] is True
    assert output["safety_escapes"] == 0
    assert json.loads(report_path.read_text(encoding="utf-8")) == output


def test_trace_cli_reads_only_redacted_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from computer_use_agent.trace import RunRecorder
    from computer_use_agent.types import RunBudget, RunState

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    state = RunState(
        run_id="run_cli_trace",
        task="CLI_TASK_SECRET",
        policy_version="trace-v1",
        observation_epoch=0,
        budgets=RunBudget(1, 1, 0),
    )
    RunRecorder(state_dir.resolve(), state.run_id).start(state)

    assert main(["trace", state.run_id, "--config", str(config_path)]) == 0

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output["state"]["phase"] == "CREATED"
    assert output["state"]["recovery_action"] == "inspect_trace_then_start_new_run"
    assert "CLI_TASK_SECRET" not in raw


def test_fullcycle_cli_writes_manifest_and_redacted_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from computer_use_agent.fullcycle_export import canonical_json_bytes
    from computer_use_agent.trace import RunRecorder
    from computer_use_agent.types import RunBudget, RunState

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    manifest_path = tmp_path.resolve() / "runtime-manifest.json"
    export_path = tmp_path.resolve() / "run-export.json"
    state = RunState(
        run_id="run_cli_fullcycle",
        task="FULLCYCLE_CLI_SECRET",
        policy_version="trace-v1",
        observation_epoch=0,
        budgets=RunBudget(1, 1, 0),
    )
    RunRecorder(state_dir.resolve(), state.run_id).start(state)

    assert main(["fullcycle", "manifest", "--output", str(manifest_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "fullcycle_manifest_version": 1,
        "written": True,
    }
    assert (
        main(
            [
                "fullcycle",
                "export-run",
                "--config",
                str(config_path),
                "--run-id",
                state.run_id,
                "--output",
                str(export_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out) == {
        "fullcycle_run_export_version": 1,
        "run_id": state.run_id,
        "written": True,
    }
    exported = json.loads(export_path.read_bytes())
    assert export_path.read_bytes() == canonical_json_bytes(exported)
    assert exported["run_id"] == state.run_id
    assert "FULLCYCLE_CLI_SECRET" not in export_path.read_text(encoding="utf-8")


def test_fullcycle_cli_rejects_existing_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path.resolve() / "existing.json"
    output.write_text("keep", encoding="utf-8")

    assert main(["fullcycle", "manifest", "--output", str(output)]) == 2

    assert "FULLCYCLE_OUTPUT_ALREADY_EXISTS" in capsys.readouterr().err
    assert output.read_text(encoding="utf-8") == "keep"


def test_recovery_cli_classifies_without_mutating_or_disclosing_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from computer_use_agent.trace import RunRecorder
    from computer_use_agent.types import LedgerEvent, LedgerEventKind, RunBudget, RunState

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    task = "RECOVERY_TASK_SECRET"
    state = RunState(
        run_id="run_cli_recovery",
        task=task,
        policy_version="phase2",
        observation_epoch=0,
        budgets=RunBudget(1, 1, 0),
        event_log=(
            LedgerEvent(
                "run_cli_recovery:event:1",
                LedgerEventKind.USER_TASK,
                {"task_length": len(task)},
            ),
        ),
    )
    recorder = RunRecorder(state_dir.resolve(), state.run_id)
    recorder.start(state)
    before = recorder.checkpoint_path.read_bytes()

    assert main(["recovery", state.run_id, "--config", str(config_path)]) == 0

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert output == {
        "action": "resume_initial",
        "phase": "CREATED",
        "reason": "INITIAL_CHECKPOINT",
        "resume_allowed": True,
        "run_id": state.run_id,
        "task_length": len(task),
    }
    assert task not in raw
    assert recorder.checkpoint_path.read_bytes() == before


def test_recover_cli_requires_explicit_read_only_execution_confirmation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "agent.toml"

    assert (
        main(
            [
                "recover",
                "run_1",
                "--config",
                str(config_path),
                "--task",
                "Inspect",
            ]
        )
        == 2
    )

    assert "RECOVERY_EXECUTION_CONFIRMATION_REQUIRED" in capsys.readouterr().err
    assert not config_path.exists()


@pytest.mark.parametrize("maximum", [0, 5])
def test_recover_cli_rejects_unreviewed_step_bounds_before_loading_config(
    maximum: int, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "agent.toml"

    assert (
        main(
            [
                "recover",
                "run_1",
                "--config",
                str(config_path),
                "--task",
                "Inspect",
                "--execute-read-only",
                "--max-steps",
                str(maximum),
            ]
        )
        == 2
    )

    assert "RECOVERY_MAX_STEPS_INVALID" in capsys.readouterr().err
    assert not config_path.exists()


def test_recover_cli_forwards_explicit_stateless_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[tuple[Path, str, str, int, bool]] = []

    def recover(
        path: Path,
        run_id: str,
        task: str,
        *,
        max_steps: int,
        stateless_replay: bool,
    ) -> int:
        captured.append((path, run_id, task, max_steps, stateless_replay))
        return 0

    monkeypatch.setattr(agent_cli, "_recover_live", recover)
    config_path = tmp_path / "agent.toml"

    assert (
        main(
            [
                "recover",
                "run_1",
                "--config",
                str(config_path),
                "--task",
                "Inspect",
                "--execute-read-only",
                "--stateless-replay",
            ]
        )
        == 0
    )
    assert captured == [(config_path, "run_1", "Inspect", 1, True)]


def test_recover_cli_executes_one_persisted_observation_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from collections import deque

    import computer_use_agent.desktop_mcp as desktop_module
    from computer_use_agent.config import load_agent_config
    from computer_use_agent.continuation import RuntimeContinuationRecorder
    from computer_use_agent.fakes import FakeDesktopMCP
    from computer_use_agent.tool_registry import REVIEWED_TOOLS, reviewed_registry_digest
    from computer_use_agent.trace import RunPhase, RunRecorder
    from computer_use_agent.types import (
        CallIdentity,
        DispatchCertainty,
        ModelTurn,
        RunBudget,
        RunState,
        ToolCall,
        ToolResult,
        ToolResultStatus,
    )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _ = _config_text(tmp_path)
    text += "\n[continuation]\nenabled = true\nttl_seconds = 900\n"
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    config = load_agent_config(config_path)
    task = "RECOVER_TASK_SECRET"
    state = RunState(
        "run_cli_continue",
        task,
        config.policy_version,
        0,
        RunBudget(
            config.policy.max_model_turns,
            config.policy.max_tool_calls,
            config.policy.max_side_effects,
            max_input_tokens=config.policy.max_input_tokens,
            model_turns_used=1,
        ),
    )
    call = ToolCall(CallIdentity(state.run_id, "turn_1", "call_1"), "list_windows", {})
    continuation = RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=state,
        provider_name=config.provider.name,
        provider_model=config.provider.model,
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        ttl_seconds=900,
        mcp_generation=1,
    )
    continuation.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    continuation.dispatch_provider(state, checkpoint_sequence=2)
    continuation.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    desktop = FakeDesktopMCP(results=deque([result]))
    monkeypatch.setattr(desktop_module, "StdioDesktopMCP", lambda _config: desktop)

    assert (
        main(
            [
                "recover",
                state.run_id,
                "--config",
                str(config_path),
                "--task",
                task,
                "--execute-read-only",
            ]
        )
        == 0
    )

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert task not in raw
    assert output == {
        "action": "dispatch_observation",
        "checkpoint_sequence": 5,
        "next_step": "provider_continue",
        "reason": "PROVIDER_COMPLETED_OBSERVATION_PENDING",
        "run_id": state.run_id,
        "tool_code": None,
        "tool_status": "success",
    }
    assert len(desktop.tool_calls) == 1
    assert desktop.close_calls == 1


def test_recover_cli_reobserves_completed_side_effect_once_then_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from collections import deque
    from dataclasses import replace

    import computer_use_agent.desktop_mcp as desktop_module
    from computer_use_agent.config import load_agent_config
    from computer_use_agent.continuation import RuntimeContinuationRecorder
    from computer_use_agent.fakes import FakeDesktopMCP
    from computer_use_agent.tool_registry import REVIEWED_TOOLS, reviewed_registry_digest
    from computer_use_agent.trace import RunPhase, RunRecorder
    from computer_use_agent.types import (
        CallIdentity,
        DispatchCertainty,
        ModelTurn,
        RecoveryStatus,
        RunBudget,
        RunState,
        ToolCall,
        ToolEffect,
        ToolResult,
        ToolResultStatus,
    )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _ = _config_text(tmp_path)
    text += "\n[continuation]\nenabled = true\nttl_seconds = 900\n"
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    config = load_agent_config(config_path)
    task = "RECOVER_ACTION_TASK_SECRET"
    state = RunState(
        "run_cli_action_recovery",
        task,
        config.policy_version,
        0,
        RunBudget(
            config.policy.max_model_turns,
            config.policy.max_tool_calls,
            config.policy.max_side_effects,
            max_input_tokens=config.policy.max_input_tokens,
            model_turns_used=1,
        ),
    )
    action = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "click",
        {"ref": "ref_1"},
    )
    continuation = RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=state,
        provider_name=config.provider.name,
        provider_model=config.provider.model,
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        ttl_seconds=900,
        mcp_generation=1,
    )
    continuation.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    continuation.dispatch_provider(state, checkpoint_sequence=2)
    continuation.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (action,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    action_state = replace(
        state,
        budgets=replace(state.budgets, tool_calls_used=1, side_effects_used=1),
        recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
    )
    continuation.prepare_tool(
        action_state,
        action,
        effect=ToolEffect.SIDE_EFFECT,
        checkpoint_sequence=4,
    )
    continuation.dispatch_tool(action_state, checkpoint_sequence=5)
    continuation.complete_tool(
        action_state,
        ToolResult(
            action.identity,
            action.name,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
        ),
        checkpoint_sequence=6,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(action_state)
    safe.record(action_state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(action_state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    for _ in range(3):
        safe.record(action_state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    mandatory_identity = CallIdentity(state.run_id, "recovery_7", "mandatory_ui_snapshot")
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    mandatory_identity,
                    "ui_snapshot",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="verified desktop state",
                )
            ]
        )
    )
    monkeypatch.setattr(desktop_module, "StdioDesktopMCP", lambda _config: desktop)

    class Progress:
        def __init__(self) -> None:
            self.events: list[RunPhase | str] = []

        def on_phase(self, phase: RunPhase) -> None:
            self.events.append(phase)

        def estop(self) -> None:
            self.events.append("estop")

        def release(self) -> None:
            self.events.append("release")

    presence = Progress()
    progress = Progress()
    monkeypatch.setattr(agent_cli, "_presence_lifecycle", lambda _config: presence)
    monkeypatch.setattr(agent_cli, "_progress_lifecycle", lambda _config: progress)

    assert (
        main(
            [
                "recover",
                state.run_id,
                "--config",
                str(config_path),
                "--task",
                task,
                "--execute-read-only",
            ]
        )
        == 0
    )

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert task not in raw
    assert output == {
        "action": "mandatory_reobserve",
        "checkpoint_sequence": 8,
        "next_step": "stop",
        "reason": "SIDE_EFFECT_COMPLETED",
        "run_id": state.run_id,
        "tool_code": None,
        "tool_status": "success",
    }
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]
    assert desktop.close_calls == 1
    expected_events = [
        RunPhase.PLANNING,
        RunPhase.VERIFYING,
        RunPhase.VERIFYING,
        "release",
    ]
    assert presence.events == expected_events
    assert progress.events == expected_events


@pytest.mark.parametrize("provider_requests_action", [False, True])
def test_recover_cli_runs_bounded_read_only_chain_without_dispatching_new_action(
    provider_requests_action: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from collections import deque

    import computer_use_agent.desktop_mcp as desktop_module
    from computer_use_agent.config import load_agent_config
    from computer_use_agent.continuation import (
        RuntimeContinuationRecorder,
        continuation_path,
        read_continuation,
    )
    from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
    from computer_use_agent.providers.openai import OpenAIResponsesProvider
    from computer_use_agent.tool_registry import REVIEWED_TOOLS, reviewed_registry_digest
    from computer_use_agent.trace import RunPhase, RunRecorder, read_run_checkpoint
    from computer_use_agent.types import (
        CallIdentity,
        DispatchCertainty,
        ModelTurn,
        RunBudget,
        RunState,
        ToolCall,
        ToolEffect,
        ToolResult,
        ToolResultStatus,
    )

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, _ = _config_text(tmp_path)
    text += "\n[continuation]\nenabled = true\nttl_seconds = 900\n"
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    config = load_agent_config(config_path)
    task = "MULTISTEP_RECOVERY_TASK_SECRET"
    state = RunState(
        "run_cli_multistep",
        task,
        config.policy_version,
        0,
        RunBudget(
            config.policy.max_model_turns,
            config.policy.max_tool_calls,
            config.policy.max_side_effects,
            max_input_tokens=config.policy.max_input_tokens,
            model_turns_used=1,
        ),
    )
    observation = ToolCall(CallIdentity(state.run_id, "turn_1", "call_1"), "list_windows", {})
    continuation = RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=state,
        provider_name=config.provider.name,
        provider_model=config.provider.model,
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        ttl_seconds=900,
        mcp_generation=1,
    )
    continuation.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    continuation.dispatch_provider(state, checkpoint_sequence=2)
    continuation.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (observation,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    observation.identity,
                    observation.name,
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="Notepad",
                )
            ]
        )
    )
    next_calls = (
        (
            ToolCall(
                CallIdentity(state.run_id, "turn_2", "action_1"),
                "click",
                {"ref": "ref_1"},
            ),
        )
        if provider_requests_action
        else ()
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    state.run_id,
                    "turn_2",
                    "response_2",
                    "" if provider_requests_action else "done",
                    next_calls,
                )
            ]
        )
    )
    monkeypatch.setattr(desktop_module, "StdioDesktopMCP", lambda _config: desktop)
    monkeypatch.setattr(
        OpenAIResponsesProvider,
        "from_environment",
        staticmethod(lambda _model, **_kwargs: provider),
    )

    exit_code = main(
        [
            "recover",
            state.run_id,
            "--config",
            str(config_path),
            "--task",
            task,
            "--execute-read-only",
            "--max-steps",
            "4",
        ]
    )

    captured = capsys.readouterr()
    if provider_requests_action:
        assert exit_code == 2
        assert captured.out == ""
        assert captured.err.strip() == "error: RECOVERY_PROVIDER_TOOL_NOT_ADVERTISED"
        assert [call.name for call in desktop.tool_calls] == ["list_windows"]
        assert len(provider.calls) == 1
        assert all(
            tool.effect is ToolEffect.OBSERVATION
            for tool in provider.calls[0]["tools"]
        )
        assert desktop.close_calls == 1
        checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
        assert checkpoint["phase"] == RunPhase.PLANNING.value
        assert checkpoint["checkpoint_sequence"] == 6
        envelope = read_continuation(config.state_dir, state.run_id)
        assert envelope.payload["checkpoint_sequence"] == 6
        assert envelope.payload["boundary"] == {
            "operation_kind": "provider",
            "stage": "dispatch_intent",
            "operation_id": f"{state.run_id}:turn_2:provider",
            "effect": None,
            "dispatch": "unknown",
            "next_step": "stop",
        }
        return

    assert exit_code == 0
    raw = captured.out
    output = json.loads(raw)
    assert task not in raw
    assert output["steps_executed"] == 2
    assert [step["action"] for step in output["steps"]] == [
        "dispatch_observation",
        "continue_provider",
    ]
    assert output["checkpoint_sequence"] == 8
    assert output["next_step"] == "stop"
    assert output["tool_call_count"] == 0
    assert [call.name for call in desktop.tool_calls] == ["list_windows"]
    assert len(provider.calls) == 1
    assert desktop.close_calls == 1
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    assert checkpoint["phase"] == RunPhase.SUCCESS.value
    assert continuation_path(config.state_dir, state.run_id).exists() is False


def test_report_cli_is_read_only_for_empty_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")

    assert main(["report", "--config", str(config_path)]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["run_count"] == 0
    assert output["metrics_run_count"] == 0
    assert not state_dir.exists()


def test_remember_cli_requires_confirmation_and_supports_list_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    text, state_dir = _config_text(tmp_path)
    config_path = tmp_path / "agent.toml"
    config_path.write_text(text, encoding="utf-8")
    common = [
        "--config",
        str(config_path),
        "--kind",
        "preference",
        "--content",
        "Prefer concise summaries.",
        "--scope",
        "global",
        "--expires-at",
        "2099-01-01T00:00:00Z",
    ]

    assert main(["remember", "add", *common]) == 2
    assert "MEMORY_REQUIRES_EXPLICIT_CONFIRMATION" in capsys.readouterr().err
    assert not (state_dir / "memory.sqlite3").exists()

    assert main(["remember", "add", *common, "--confirmed"]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["kind"] == "preference"

    assert main(["remember", "list", "--config", str(config_path)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert [item["id"] for item in listed["memories"]] == [added["id"]]

    assert main(["remember", "delete", added["id"], "--config", str(config_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"deleted": True, "id": added["id"]}


@pytest.mark.parametrize(
    ("provider_name", "provider_module"),
    [
        ("openai", "computer_use_agent.providers.openai"),
        ("anthropic", "computer_use_agent.providers.anthropic"),
    ],
)
def test_live_cli_loads_only_the_selected_optional_provider(
    tmp_path: Path,
    provider_name: str,
    provider_module: str,
) -> None:
    config_path = tmp_path / "agent.toml"
    script = f"""\
import sys
from pathlib import Path
from computer_use_agent.config import AgentConfig, MCPLaunchConfig, PolicyConfig, ProviderConfig
from computer_use_agent.cli import _run_live_async
config = AgentConfig(
    state_dir=Path({str(tmp_path / "computer-use-agent" / "state")!r}),
    policy_version="test",
    provider=ProviderConfig(name={provider_name!r}, model="test-model"),
    mcp=MCPLaunchConfig(
        executable=Path({str(tmp_path / "mcp.exe")!r}),
        args=(), cwd=Path({str(tmp_path)!r}), environment={{"CUMCP_ALLOWLIST": "notepad.exe"}},
    ),
    policy=PolicyConfig(),
)
import computer_use_agent.cli as cli
cli.load_agent_config = lambda path: config
try:
    import asyncio
    asyncio.run(_run_live_async(Path({str(config_path)!r}), "inspect"))
except Exception:
    # This test asserts which provider module got imported, nothing else.
    # How the run then fails depends on whether the optional provider package
    # is installed and whether credentials exist, and neither is the subject.
    pass
selected={provider_module!r}
other="computer_use_agent.providers.anthropic" if selected.endswith("openai") else "computer_use_agent.providers.openai"
raise SystemExit(1 if other in sys.modules else 0)
"""
    environment = dict(os.environ)
    environment["LOCALAPPDATA"] = str(tmp_path)
    # Drop provider credentials so the outcome cannot depend on whether the
    # developer running the suite happens to have them exported.
    for credential in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "ANTHROPIC_API_KEY"):
        environment.pop(credential, None)

    result = subprocess.run([sys.executable, "-c", script], check=False, env=environment)

    assert result.returncode == 0


def test_live_cli_passes_configured_request_budget_to_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from computer_use_agent.config import (
        AgentConfig,
        MCPLaunchConfig,
        PolicyConfig,
        ProviderConfig,
    )
    from computer_use_agent.fakes import FakeDesktopMCP
    from computer_use_agent.providers.openai import OpenAIResponsesProvider
    from computer_use_agent.trace import RunPhase
    from computer_use_agent.types import ModelTurn

    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    config = AgentConfig(
        state_dir=local / "computer-use-agent" / "budget-test",
        policy_version="test",
        provider=ProviderConfig("openai", "test-model", max_request_bytes=4096),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {"CUMCP_ALLOWLIST": "notepad.exe"}),
        policy=PolicyConfig(),
    )
    captured: dict[str, object] = {}

    class Progress:
        def __init__(self) -> None:
            self.events: list[RunPhase | str] = []

        def on_phase(self, phase: RunPhase) -> None:
            self.events.append(phase)

        def estop(self) -> None:
            self.events.append("estop")

        def release(self) -> None:
            self.events.append("release")

    progress = Progress()

    class FinalProvider:
        name = "openai"

        async def create_turn(self, **kwargs: object) -> ModelTurn:
            return ModelTurn(
                str(kwargs["run_id"]),
                str(kwargs["turn_id"]),
                "response_1",
                "done",
            )

    def from_environment(model: str, **kwargs: object) -> FinalProvider:
        captured.update({"model": model, **kwargs})
        return FinalProvider()

    monkeypatch.setattr(agent_cli, "load_agent_config", lambda _path: config)
    monkeypatch.setattr(OpenAIResponsesProvider, "from_environment", from_environment)
    monkeypatch.setattr(
        "computer_use_agent.desktop_mcp.StdioDesktopMCP", lambda _launch: FakeDesktopMCP()
    )
    monkeypatch.setattr(agent_cli, "_progress_lifecycle", lambda _config: progress)

    assert asyncio.run(agent_cli._run_live_async(tmp_path / "agent.toml", "Inspect")) == 0

    assert captured["model"] == "test-model"
    assert captured["max_request_bytes"] == 4096
    assert captured["context_window_tokens"] == 128_000
    assert captured["output_token_reserve"] == 1_024
    assert json.loads(capsys.readouterr().out)["text"] == "done"
    assert progress.events[0] is RunPhase.CREATED
    assert progress.events[-1] == "release"


def test_cli_builds_opt_in_decision_card_approval_with_configured_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from computer_use_agent.approvals import DecisionCardApprovalPort
    from computer_use_agent.config import (
        APPROVED_ACTIONS_MODE,
        AgentConfig,
        MCPLaunchConfig,
        OperatorConfig,
        PolicyConfig,
        ProviderConfig,
    )
    from computer_use_agent import decision_card_window_win32

    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    config = AgentConfig(
        state_dir=local / "computer-use-agent" / "card-cli-test",
        policy_version="approved-v1",
        provider=ProviderConfig("openai", "test-model"),
        mcp=MCPLaunchConfig(
            tmp_path / "mcp.exe", (), tmp_path, {"CUMCP_ALLOWLIST": "notepad.exe"}
        ),
        policy=PolicyConfig(mode=APPROVED_ACTIONS_MODE),
        operator=OperatorConfig(
            decision_cards_enabled=True,
            decision_timeout_seconds=45,
            decision_card_corner="top_left",
        ),
    )
    native = object()
    monkeypatch.setattr(
        decision_card_window_win32,
        "Win32DecisionCardWindowApi",
        lambda *, corner: (native, corner),
    )

    port = agent_cli._approval_port(config)

    assert isinstance(port, DecisionCardApprovalPort)
    assert port._timeout_seconds == 45
    assert port._surface.api == (native, "top_left")


def test_cli_builds_progress_lifecycle_only_for_explicit_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from computer_use_agent.config import (
        AgentConfig,
        MCPLaunchConfig,
        OperatorConfig,
        PolicyConfig,
        ProviderConfig,
    )
    from computer_use_agent.fakes import FakeProgressWindowApi
    from computer_use_agent.progress_lifecycle import RunProgressCoordinator
    from computer_use_agent import progress_window_win32

    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    base = {
        "state_dir": local / "computer-use-agent" / "progress-cli-test",
        "policy_version": "test",
        "provider": ProviderConfig("openai", "test-model"),
        "mcp": MCPLaunchConfig(
            tmp_path / "mcp.exe",
            (),
            tmp_path,
            {"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        "policy": PolicyConfig(),
    }
    constructed = 0

    def native_api() -> FakeProgressWindowApi:
        nonlocal constructed
        constructed += 1
        api = FakeProgressWindowApi()
        api.pump = lambda: None  # type: ignore[attr-defined]
        return api

    monkeypatch.setattr(
        progress_window_win32,
        "Win32ProgressWindowApi",
        native_api,
    )

    assert agent_cli._progress_lifecycle(AgentConfig(**base)) is None
    assert constructed == 0

    lifecycle = agent_cli._progress_lifecycle(
        AgentConfig(
            **base,
            operator=OperatorConfig(progress_enabled=True),
        )
    )

    assert isinstance(lifecycle, RunProgressCoordinator)
    assert lifecycle.poller.state_dir == base["state_dir"]
    assert constructed == 1
    lifecycle.release()


def test_progress_native_construction_failure_is_fail_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from computer_use_agent.config import (
        AgentConfig,
        MCPLaunchConfig,
        OperatorConfig,
        PolicyConfig,
        ProviderConfig,
    )
    from computer_use_agent import progress_window_win32

    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    config = AgentConfig(
        state_dir=local / "computer-use-agent" / "progress-cli-failure",
        policy_version="test",
        provider=ProviderConfig("openai", "test-model"),
        mcp=MCPLaunchConfig(
            tmp_path / "mcp.exe",
            (),
            tmp_path,
            {"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(),
        operator=OperatorConfig(progress_enabled=True),
    )

    def fail_native() -> None:
        raise OSError("native unavailable")

    monkeypatch.setattr(
        progress_window_win32,
        "Win32ProgressWindowApi",
        fail_native,
    )

    assert agent_cli._progress_lifecycle(config) is None
