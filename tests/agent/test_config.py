from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    ContinuationConfig,
    READ_ONLY_MODE,
    ConfigError,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
    load_agent_config,
)


def _config_text(
    tmp_path: Path,
    *,
    environment: str = 'CUMCP_ALLOWLIST = "notepad.exe"',
    state_dir: Path | None = None,
    provider_extra: str = "",
    context_window_tokens: int = 128_000,
    output_token_reserve: int = 1_024,
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
context_window_tokens = {context_window_tokens}
output_token_reserve = {output_token_reserve}
{provider_extra}

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


def test_provider_request_budget_defaults_and_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path, provider_extra="max_request_bytes = 4096"),
        encoding="utf-8",
    )

    assert load_agent_config(path).provider.max_request_bytes == 4096

    for value in (1, 49 * 1024 * 1024, True):
        with pytest.raises(ConfigError, match="max_request_bytes"):
            ProviderConfig("openai", "test-model", value)


def test_provider_token_window_defaults_and_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(
            tmp_path,
            context_window_tokens=200_000,
            output_token_reserve=4_096,
        ),
        encoding="utf-8",
    )

    provider = load_agent_config(path).provider
    assert provider.context_window_tokens == 200_000
    assert provider.output_token_reserve == 4_096

    with pytest.raises(ConfigError, match="context_window_tokens"):
        ProviderConfig("openai", "test-model", context_window_tokens=100)
    with pytest.raises(ConfigError, match="output_token_reserve"):
        ProviderConfig(
            "openai",
            "test-model",
            context_window_tokens=2_000,
            output_token_reserve=2_000,
        )

    missing = tmp_path / "missing-window.toml"
    missing.write_text(
        _config_text(tmp_path).replace("context_window_tokens = 128000\n", ""),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="context_window_tokens"):
        load_agent_config(missing)


def test_continuation_persistence_is_explicit_opt_in_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    path = tmp_path / "agent.toml"
    path.write_text(
        _config_text(tmp_path)
        + "\n[continuation]\nenabled = true\nttl_seconds = 600\n",
        encoding="utf-8",
    )

    config = load_agent_config(path)

    assert config.continuation == ContinuationConfig(enabled=True, ttl_seconds=600)
    with pytest.raises(ConfigError, match="ttl_seconds"):
        ContinuationConfig(enabled=True, ttl_seconds=59)


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


def test_context_event_budget_must_be_positive() -> None:
    with pytest.raises(ConfigError, match="max_context_events"):
        PolicyConfig(max_context_events=0)


def test_input_token_budget_must_be_nonnegative() -> None:
    with pytest.raises(ConfigError, match="max_input_tokens"):
        PolicyConfig(max_input_tokens=-1)


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
