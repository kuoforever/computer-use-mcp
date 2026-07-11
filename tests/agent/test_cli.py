from __future__ import annotations

import json
import os
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


@pytest.mark.parametrize(
    "arguments",
    [["--help"], ["run", "--help"], ["eval", "--help"], ["config", "validate", "--help"]],
)
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
    script = f'''\
import sys
from pathlib import Path
from computer_use_agent.config import AgentConfig, MCPLaunchConfig, PolicyConfig, ProviderConfig
from computer_use_agent.cli import _run_live_async
config = AgentConfig(
    state_dir=Path({str(tmp_path / 'computer-use-agent' / 'state')!r}),
    policy_version="test",
    provider=ProviderConfig(name={provider_name!r}, model="test-model"),
    mcp=MCPLaunchConfig(
        executable=Path({str(tmp_path / 'mcp.exe')!r}),
        args=(), cwd=Path({str(tmp_path)!r}), environment={{"CUMCP_ALLOWLIST": "notepad.exe"}},
    ),
    policy=PolicyConfig(),
)
import computer_use_agent.cli as cli
cli.load_agent_config = lambda path: config
try:
    import asyncio
    asyncio.run(_run_live_async(Path({str(config_path)!r}), "inspect"))
except RuntimeError:
    pass
selected={provider_module!r}
other="computer_use_agent.providers.anthropic" if selected.endswith("openai") else "computer_use_agent.providers.openai"
raise SystemExit(1 if other in sys.modules else 0)
'''
    environment = dict(os.environ)
    environment["LOCALAPPDATA"] = str(tmp_path)

    result = subprocess.run([sys.executable, "-c", script], check=False, env=environment)

    assert result.returncode == 0
