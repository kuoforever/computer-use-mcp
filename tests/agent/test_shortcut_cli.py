from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.cli import main
from computer_use_agent.config_init import initialize_agent_config


def test_shortcuts_run_routes_only_to_bounded_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    executable = tmp_path / "guarded-desktop-mcp.exe"
    executable.write_bytes(b"")
    config_path = tmp_path / "agent.toml"
    initialize_agent_config(
        profile="desktop-ask",
        provider="openai",
        model="reviewed-model",
        output=config_path,
        mcp_executable=executable,
    )
    calls: list[Path] = []

    def run_shortcut_service(path: Path) -> int:
        calls.append(path)
        return 0

    monkeypatch.setattr(
        "computer_use_agent.shortcut_service.run_shortcut_service",
        run_shortcut_service,
    )

    assert main(["shortcuts", "run", "--config", str(config_path)]) == 0
    assert calls == [config_path]


def test_shortcuts_run_uses_quick_setup_default_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    calls: list[Path] = []

    monkeypatch.setattr(
        "computer_use_agent.shortcut_service.run_shortcut_service",
        lambda path: calls.append(path) or 0,
    )

    assert main(["shortcuts", "run"]) == 0
    assert calls == [local_app_data / "computer-use-agent" / "agent.toml"]
