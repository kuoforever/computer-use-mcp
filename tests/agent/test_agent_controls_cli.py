from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.cli import main
from computer_use_agent.config import load_agent_config


def _mcp_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "Scripts" / "guarded-desktop-mcp.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    return executable


def test_config_setup_creates_default_human_first_profile_and_settings_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp_executable = _mcp_executable(tmp_path)

    assert main(["config", "setup", "--mcp-executable", str(mcp_executable)]) == 0
    setup_output = capsys.readouterr().out
    config_path = local_app_data / "computer-use-agent" / "agent.toml"
    assert "SETUP CREATED" in setup_output
    assert str(config_path) in setup_output
    assert "config doctor" in setup_output
    assert load_agent_config(config_path).provider.model == "gpt-5.6-terra"

    assert main(["config", "settings"]) == 0
    settings_output = capsys.readouterr().out
    assert "AGENT CONTROLS" in settings_output
    assert "Read-only desktop questions" in settings_output
    assert "Emergency stop: ctrl+alt+q" in settings_output

    assert main(["config", "settings", "--json"]) == 0
    settings_json = json.loads(capsys.readouterr().out)
    assert settings_json["configuration"]["config_path"] == str(config_path.resolve())
    assert settings_json["authority"]["shortcuts_registered"] is False

    assert main(["config", "setup", "--mcp-executable", str(mcp_executable)]) == 2
    assert capsys.readouterr().err.strip() == "error: CONFIG_OUTPUT_EXISTS"


def test_config_setup_json_accepts_bounded_profile_provider_and_path_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    mcp_executable = _mcp_executable(tmp_path)
    output = tmp_path / "custom.toml"

    assert (
        main(
            [
                "config",
                "setup",
                "--profile",
                "public-web-word",
                "--provider",
                "anthropic",
                "--model",
                "explicit-reviewed-model",
                "--output",
                str(output),
                "--mcp-executable",
                str(mcp_executable),
                "--pause-shortcut",
                "ctrl+alt+k",
                "--json",
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result["setup_version"] == 1
    assert result["created"] is True
    assert result["configuration"]["profile"] == "public-web-word"
    assert result["configuration"]["provider"] == "anthropic"
    assert result["configuration"]["model"] == "explicit-reviewed-model"
    assert result["authority"]["can_dispatch"] is False
    assert result["shortcuts"]["request_pause"] == "ctrl+alt+k"
    assert load_agent_config(output).operator.pause_shortcut == "ctrl+alt+k"
    assert load_agent_config(output).policy.mode == "approved_actions"


def test_config_setup_rejects_reserved_pause_shortcut_before_writing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    output = tmp_path / "reserved.toml"

    assert (
        main(
            [
                "config",
                "setup",
                "--output",
                str(output),
                "--mcp-executable",
                str(_mcp_executable(tmp_path)),
                "--pause-shortcut",
                "ctrl+alt+q",
            ]
        )
        == 2
    )
    assert "operator pause_shortcut" in capsys.readouterr().err
    assert not output.exists()
