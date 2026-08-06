from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import ModuleType

import pytest

import computer_use_agent.provider_setup as provider_setup
from computer_use_agent.cli import main
from computer_use_agent.config_init import initialize_desktop_ask_config
from computer_use_agent.doctor import diagnose_config
from computer_use_agent.tool_registry import reviewed_mcp_descriptors
from computer_use_agent.types import MCPToolDescriptor


class _RecordingDesktop:
    def __init__(self) -> None:
        self.discover_calls = 0
        self.close_calls = 0

    async def discover_tools(self) -> tuple[MCPToolDescriptor, ...]:
        self.discover_calls += 1
        return reviewed_mcp_descriptors()

    async def close(self) -> None:
        self.close_calls += 1


def _initialized_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    provider: str,
) -> tuple[Path, Path]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    executable = tmp_path / "Scripts" / "guarded-desktop-mcp.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"")
    output = tmp_path / f"{provider}.toml"
    initialize_desktop_ask_config(
        provider=provider,
        model="doctor-model",
        output=output,
        mcp_executable=executable,
    )
    return output, executable


@pytest.mark.parametrize(
    ("provider", "credential"),
    [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
    ],
)
def test_doctor_reports_exact_installed_readiness_without_calling_a_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    credential: str,
) -> None:
    config_path, _executable = _initialized_config(
        tmp_path,
        monkeypatch,
        provider=provider,
    )
    desktop = _RecordingDesktop()
    constructed = 0

    def factory(_launch: object) -> _RecordingDesktop:
        nonlocal constructed
        constructed += 1
        return desktop

    report = asyncio.run(
        diagnose_config(
            config_path,
            environ={credential: "doctor-placeholder"},
            module_finder=lambda _name: object(),
            desktop_factory=factory,
        )
    )

    expected_names = tuple(
        sorted(descriptor.name for descriptor in reviewed_mcp_descriptors())
    )
    assert report.as_json() == {
        "doctor_version": 1,
        "ready": True,
        "provider": provider,
        "checks": {
            "config": "pass",
            "provider_sdk": "pass",
            "provider_credential": "pass",
            "mcp_executable": "pass",
            "mcp_cwd": "pass",
            "mcp_discovery": "pass",
        },
        "mcp": {
            "tool_count": 13,
            "tool_names": list(expected_names),
        },
        "failure": None,
    }
    assert constructed == 1
    assert desktop.discover_calls == 1
    assert desktop.close_calls == 1


@pytest.mark.parametrize(
    ("failure_kind", "expected_check", "expected_code"),
    [
        ("sdk", "provider_sdk", "OPENAI_SDK_NOT_INSTALLED"),
        ("credential", "provider_credential", "OPENAI_API_KEY_MISSING"),
        ("executable", "mcp_executable", "MCP_EXECUTABLE_NOT_FOUND"),
    ],
)
def test_doctor_stops_at_one_actionable_setup_failure_before_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
    expected_check: str,
    expected_code: str,
) -> None:
    config_path, executable = _initialized_config(
        tmp_path,
        monkeypatch,
        provider="openai",
    )
    if failure_kind == "executable":
        executable.unlink()
    constructed = 0

    def factory(_launch: object) -> _RecordingDesktop:
        nonlocal constructed
        constructed += 1
        return _RecordingDesktop()

    report = asyncio.run(
        diagnose_config(
            config_path,
            environ=(
                {}
                if failure_kind == "credential"
                else {"OPENAI_API_KEY": "doctor-placeholder"}
            ),
            module_finder=(
                (lambda _name: None)
                if failure_kind == "sdk"
                else (lambda _name: object())
            ),
            desktop_factory=factory,
        )
    )
    payload = report.as_json()

    assert report.ready is False
    assert payload["failure"]["code"] == expected_code  # type: ignore[index]
    assert payload["checks"][expected_check] == "fail"  # type: ignore[index]
    assert constructed == 0


@pytest.mark.parametrize(
    ("provider", "credential", "module_name", "client_name", "extra"),
    [
        ("openai", "OPENAI_API_KEY", "openai", "AsyncOpenAI", "agent-openai"),
        (
            "anthropic",
            "ANTHROPIC_API_KEY",
            "anthropic",
            "AsyncAnthropic",
            "agent-anthropic",
        ),
    ],
)
@pytest.mark.parametrize("failure_kind", ["sdk", "credential", "client"])
def test_public_ask_reports_one_actionable_provider_setup_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str,
    credential: str,
    module_name: str,
    client_name: str,
    extra: str,
    failure_kind: str,
) -> None:
    config_path, _executable = _initialized_config(
        tmp_path,
        monkeypatch,
        provider=provider,
    )
    monkeypatch.setattr(
        provider_setup,
        "find_spec",
        (lambda _name: None)
        if failure_kind == "sdk"
        else (lambda _name: object()),
    )
    if failure_kind == "credential":
        monkeypatch.delenv(credential, raising=False)
    else:
        monkeypatch.setenv(credential, "doctor-placeholder")
    if failure_kind == "client":
        module = ModuleType(module_name)

        def fail_client() -> object:
            raise RuntimeError("unreviewed constructor detail")

        setattr(module, client_name, fail_client)
        monkeypatch.setitem(sys.modules, module_name, module)

    assert (
        main(["ask", "--config", str(config_path), "--task", "Inspect"])
        == 2
    )

    stderr = capsys.readouterr().err.strip()
    expected = {
        "sdk": (
            f'{provider.upper()}_SDK_NOT_INSTALLED: Install with: python -m pip install '
            f'"guarded-desktop-agent[{extra}]"'
        ),
        "credential": (
            f"{credential}_MISSING: Set {credential} in the current shell."
        ),
        "client": (
            f"{provider.upper()}_CLIENT_INIT_FAILED: check {credential} "
            "and the provider environment."
        ),
    }[failure_kind]
    assert stderr == f"error: {expected}"
    assert "Traceback" not in stderr
