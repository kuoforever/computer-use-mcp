from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_use_agent.agent_controls import (
    RECOMMENDED_MODELS,
    create_quick_setup,
    default_config_path,
    load_agent_controls,
    render_agent_controls,
    render_quick_setup,
)
from computer_use_agent.config import load_agent_config
from computer_use_agent.config_init import initialize_agent_config


def _mcp_executable(tmp_path: Path) -> Path:
    executable = tmp_path / "Scripts" / "guarded-desktop-mcp.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    return executable


def test_quick_setup_uses_reviewed_defaults_without_storing_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-enter-config-or-output")
    mcp_executable = _mcp_executable(tmp_path)

    result = create_quick_setup(
        mcp_executable=mcp_executable,
        module_finder=lambda _name: object(),
    )

    expected_path = local_app_data / "computer-use-agent" / "agent.toml"
    assert default_config_path() == expected_path
    assert result.initialized.output == expected_path
    assert result.initialized.profile == "desktop-ask"
    assert result.initialized.provider == "openai"
    assert result.initialized.model == RECOMMENDED_MODELS["openai"]
    assert "must-not-enter-config-or-output" not in expected_path.read_text("utf-8")

    config = load_agent_config(expected_path)
    assert config.policy.mode == "read_only"
    assert config.mcp.executable == mcp_executable.resolve()
    projection = result.controls.as_json()
    assert projection["agent_controls_version"] == 1
    assert projection["configuration"]["profile"] == "desktop-ask"
    assert projection["provider_setup"] == {
        "credential_environment": "OPENAI_API_KEY",
        "credential_present": True,
        "sdk_installed": True,
    }
    assert projection["safety"]["emergency_stop"] == "ctrl+alt+q"
    assert projection["authority"] == {
        "can_approve": False,
        "can_control_task": False,
        "can_dispatch": False,
        "can_retry_or_replay": False,
        "shortcuts_registered": False,
    }
    assert "must-not-enter-config-or-output" not in json.dumps(projection)
    assert projection["commands"]["doctor"].endswith(f'--config "{expected_path}"')

    with pytest.raises(ValueError, match="CONFIG_OUTPUT_EXISTS"):
        create_quick_setup(mcp_executable=mcp_executable)


def test_agent_controls_projects_supervised_settings_with_human_json_parity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp_executable = _mcp_executable(tmp_path)
    config_path = tmp_path / "workflow.toml"
    initialize_agent_config(
        profile="public-web-word",
        provider="anthropic",
        model="explicit-reviewed-model",
        output=config_path,
        mcp_executable=mcp_executable,
    )

    controls = load_agent_controls(
        config_path,
        environ={},
        module_finder=lambda _name: None,
    )
    projection = controls.as_json()
    assert projection["configuration"] == {
        "config_path": str(config_path.resolve()),
        "model": "explicit-reviewed-model",
        "policy_mode": "approved_actions",
        "profile": "public-web-word",
        "provider": "anthropic",
        "purpose": "Supervised browser-to-Word workflow",
        "state_dir": str(
            (local_app_data / "computer-use-agent" / "public-web-word").resolve()
        ),
    }
    assert projection["provider_setup"] == {
        "credential_environment": "ANTHROPIC_API_KEY",
        "credential_present": False,
        "sdk_installed": False,
    }
    assert projection["safety"]["allowed_applications"] == [
        "chrome.exe",
        "winword.exe",
    ]
    assert projection["safety"]["approval_policy"] == "high_risk_only"
    assert projection["interface"]["decision_timeout_seconds"] == 180

    human = render_agent_controls(controls)
    assert "AGENT CONTROLS" in human
    assert "PURPOSE" in human
    assert "CONNECTION" in human
    assert "SAFETY" in human
    assert "INTERFACE" in human
    assert "NEXT" in human
    assert "Supervised browser-to-Word workflow" in human
    assert "Credential: not configured (ANTHROPIC_API_KEY)" in human
    assert projection["commands"]["doctor"] in human
    assert "approve" not in projection["commands"]["doctor"].casefold()


def test_quick_setup_human_view_explains_result_and_exact_next_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    result = create_quick_setup(
        provider="anthropic",
        profile="public-web-word",
        mcp_executable=_mcp_executable(tmp_path),
        environ={"LOCALAPPDATA": str(local_app_data)},
        module_finder=lambda _name: None,
    )

    human = render_quick_setup(result)

    assert "SETUP CREATED" in human
    assert "No credential was written to the configuration." in human
    assert "Set ANTHROPIC_API_KEY in the current shell." in human
    assert result.controls.doctor_command in human
    assert str(result.initialized.output) in human


def test_agent_controls_does_not_mislabel_custom_read_only_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    config_path = tmp_path / "custom.toml"
    initialize_agent_config(
        profile="desktop-ask",
        provider="openai",
        model="explicit-reviewed-model",
        output=config_path,
        mcp_executable=_mcp_executable(tmp_path),
    )
    custom = config_path.read_text("utf-8").replace(
        'policy_version = "readonly-v1"',
        'policy_version = "custom-readonly-v9"',
        1,
    )
    config_path.write_text(custom, "utf-8")

    controls = load_agent_controls(
        config_path,
        environ={},
        module_finder=lambda _name: None,
    )

    assert controls.profile == "advanced"
    assert controls.purpose == "Advanced custom configuration"
