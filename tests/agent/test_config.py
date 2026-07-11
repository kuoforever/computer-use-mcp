from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    READ_ONLY_MODE,
    ConfigError,
    MCPLaunchConfig,
    PolicyConfig,
    default_state_dir,
    load_agent_config,
)


def _config_text(
    tmp_path: Path,
    *,
    environment: str = 'CUMCP_ALLOWLIST = "notepad.exe"',
    state_dir: Path | None = None,
) -> str:
    local_app_data = tmp_path / "LocalAppData"
    configured_state_dir = state_dir or local_app_data / "computer-use-agent" / "test-run"
    executable = (tmp_path / "computer-use-mcp.exe").as_posix()
    cwd = tmp_path.as_posix()
    return f'''\
[agent]
state_dir = "{configured_state_dir.as_posix()}"
policy_version = "phase0"

[provider]
name = "openai"
model = "test-model"

[mcp]
executable = "{executable}"
args = []
cwd = "{cwd}"
environment = {{ {environment} }}
'''


def test_config_defaults_to_read_only_and_uses_host_generated_safe_child_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")

    config = load_agent_config(path)

    assert config.policy.mode == READ_ONLY_MODE
    assert config.policy.require_approval_for_actions is True
    assert config.mcp.child_environment()["CUMCP_MODE"] == "safe_local"
    assert config.mcp.child_environment()["CUMCP_DANGEROUS_CONFIRM"] == "1"
    assert config.mcp.child_environment()["CUMCP_ALLOWLIST"] == "notepad.exe"
    assert config.trace_dir != config.memory_database


@pytest.mark.parametrize(
    "environment",
    [
        'OPENAI_API_KEY = "not-allowed"',
        'OPENAI_KEY = "not-allowed"',
        'AWS_ACCESS_KEY_ID = "not-allowed"',
        'SERVICE_TOKEN = "not-allowed"',
        'PYTHONPATH = "not-allowed"',
        'CUMCP_AUDIT = "NUL"',
        'CUMCP_ESTOP = ""',
    ],
)
def test_config_rejects_unreviewed_child_environment_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path, environment=environment), encoding="utf-8")

    with pytest.raises(ConfigError, match="not reviewed"):
        load_agent_config(path)


@pytest.mark.parametrize(
    "environment",
    [
        'CUMCP_MODE = "full_control_local"',
        'CUMCP_DANGEROUS_CONFIRM = "0"',
        'CUMCP_HUMAN_IDLE_SECONDS = "0"',
    ],
)
def test_config_rejects_child_environment_values_that_weaken_server_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, environment: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path, environment=environment), encoding="utf-8")

    with pytest.raises(ConfigError):
        load_agent_config(path)


def test_config_rejects_state_outside_the_user_local_application_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(_config_text(tmp_path, state_dir=tmp_path / "outside"), encoding="utf-8")

    with pytest.raises(ConfigError, match="user-local"):
        load_agent_config(path)


def test_approved_actions_cannot_disable_host_approval() -> None:
    with pytest.raises(ConfigError, match="still requires"):
        PolicyConfig(mode=APPROVED_ACTIONS_MODE, require_approval_for_actions=False)


def test_launch_config_rejects_relative_executable_and_unreviewed_environment() -> None:
    with pytest.raises(ConfigError, match="absolute"):
        MCPLaunchConfig(
            executable=Path("computer-use-mcp.exe"),
            args=(),
            cwd=Path.cwd(),
            environment={},
        )
    with pytest.raises(ConfigError, match="not reviewed"):
        MCPLaunchConfig(
            executable=Path.cwd() / "computer-use-mcp.exe",
            args=(),
            cwd=Path.cwd(),
            environment={"OPENAI_API_KEY": "not-allowed"},
        )


def test_default_state_directory_is_user_local() -> None:
    path = default_state_dir({"LOCALAPPDATA": "C:/Users/example/AppData/Local"})

    assert path.name == "computer-use-agent"
    assert "AppData" in str(path)
