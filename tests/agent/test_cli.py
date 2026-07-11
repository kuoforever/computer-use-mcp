from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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

[mcp]
executable = "{(tmp_path / 'computer-use-mcp.exe').as_posix()}"
args = []
cwd = "{tmp_path.as_posix()}"
environment = {{ CUMCP_ALLOWLIST = "notepad.exe" }}
'''
    return text, state_dir


@pytest.mark.parametrize("arguments", [["--help"], ["run", "--help"], ["config", "validate", "--help"]])
def test_cli_help_needs_no_config_provider_or_desktop(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        main(arguments)

    assert raised.value.code == 0


def test_cli_without_a_command_prints_help_and_returns_success(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "Safe local Agent Host foundation" in capsys.readouterr().out


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

    assert main(
        ["run", "--config", str(path), "--task", task, "--dry-run"]
    ) == 0

    raw = capsys.readouterr().out
    output = json.loads(raw)
    assert task not in raw
    assert output["dry_run"] is True
    assert output["task_length"] == len(task)
    lock_path = state_dir.parent / "active-run.lock"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == {"released": True}


def test_non_dry_run_fails_closed_before_reading_config_or_creating_a_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist.toml"

    assert main(["run", "--config", str(missing), "--task", "secret"]) == 2

    captured = capsys.readouterr()
    assert "unavailable" in captured.err
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
