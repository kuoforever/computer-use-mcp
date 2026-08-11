"""Opt-in E3 matrix: live DeepSeek API plus a harmless fake MCP child."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from computer_use_agent.approvals import ReadOnlyApprovalPort
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.desktop_mcp import StdioDesktopMCP
from computer_use_agent.fakes import FakeDesktopMCP
from computer_use_agent.provider_factory import create_model_provider
from computer_use_agent.providers.openai_chat import OpenAIChatCompletionsProvider
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerPorts, RunOutcome
from computer_use_agent.types import LedgerEventKind


pytestmark = pytest.mark.deepseek_integration
_DEEPSEEK_INTEGRATION_MODEL = "deepseek-v4-pro"


def _fail_if_credential_present(material: str | bytes) -> None:
    """Fail with fixed prose rather than reflecting sensitive material."""

    credential = os.environ.get("DEEPSEEK_API_KEY")
    if not credential:
        pytest.fail("DeepSeek credential is unavailable for leak inspection")
    contains_credential = (
        credential.encode("utf-8") in material
        if isinstance(material, bytes)
        else credential in material
    )
    if contains_credential:
        pytest.fail("DeepSeek credential leaked into captured test material")


def _scan_state_files(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            _fail_if_credential_present(path.read_bytes())


def _require_opt_in() -> str:
    if os.environ.get("RUN_DEEPSEEK_INTEGRATION") != "1":
        pytest.skip("set RUN_DEEPSEEK_INTEGRATION=1 to enable the live DeepSeek test")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("DEEPSEEK_API_KEY is required for the live DeepSeek test")
    configured_model = os.environ.get("DEEPSEEK_INTEGRATION_MODEL")
    if configured_model not in {None, _DEEPSEEK_INTEGRATION_MODEL}:
        pytest.fail("DEEPSEEK_INTEGRATION_MODEL must be exactly deepseek-v4-pro")
    pytest.importorskip("openai", reason="install the agent-openai optional dependency")
    return _DEEPSEEK_INTEGRATION_MODEL


def _mcp_config(tmp_path: Path, marker: str) -> MCPLaunchConfig:
    fixture = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    child_cwd = tmp_path / f"{marker} child"
    child_cwd.mkdir()
    return MCPLaunchConfig(
        executable=Path(sys.executable).resolve(),
        args=(str(fixture), marker),
        cwd=child_cwd,
        environment={"CUMCP_ALLOWLIST": "notepad.exe"},
    )


def _provider(model: str, *, timeout_seconds: int = 90) -> ProviderConfig:
    return ProviderConfig(
        name="deepseek",
        model=model,
        region="global",
        context_window_tokens=1_000_000,
        output_token_reserve=4096,
        request_timeout_seconds=timeout_seconds,
    )


def test_deepseek_global_setup_and_doctor_use_the_formal_product_route(
    tmp_path: Path,
) -> None:
    """Generate and diagnose the user-facing DeepSeek configuration."""

    _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    config_path = tmp_path / "deepseek-global-setup.toml"
    mcp_executable = Path(sys.executable).with_name("guarded-desktop-mcp.exe")
    assert mcp_executable.is_file()
    environment = os.environ.copy()
    environment["LOCALAPPDATA"] = str(local_app_data)
    source_dir = Path(__file__).parents[2] / "src"
    environment["PYTHONPATH"] = str(source_dir)

    setup = subprocess.run(
        [
            sys.executable,
            "-m",
            "computer_use_agent",
            "config",
            "setup",
            "--provider",
            "deepseek",
            "--model",
            _DEEPSEEK_INTEGRATION_MODEL,
            "--region",
            "global",
            "--output",
            str(config_path),
            "--mcp-executable",
            str(mcp_executable),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    _fail_if_credential_present(setup.stdout)
    _fail_if_credential_present(setup.stderr)
    assert setup.returncode == 0, setup.stderr
    setup_payload = json.loads(setup.stdout)
    assert setup_payload["configuration"]["provider"] == "deepseek"
    assert setup_payload["configuration"]["model"] == _DEEPSEEK_INTEGRATION_MODEL
    assert setup_payload["configuration"]["region"] == "global"
    assert setup_payload["provider_setup"] == {
        "credential_environment": "DEEPSEEK_API_KEY",
        "credential_present": True,
        "credential_required": True,
        "sdk_installed": True,
    }

    doctor = subprocess.run(
        [
            sys.executable,
            "-m",
            "computer_use_agent",
            "config",
            "doctor",
            "--config",
            str(config_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=environment,
    )
    _fail_if_credential_present(doctor.stdout)
    _fail_if_credential_present(doctor.stderr)
    assert doctor.returncode == 0, doctor.stderr
    doctor_payload = json.loads(doctor.stdout)
    assert doctor_payload["provider"] == "deepseek"
    assert doctor_payload["ready"] is True
    assert set(doctor_payload["checks"].values()) == {"pass"}
    assert doctor_payload["mcp"]["tool_count"] == 13

    rendered = config_path.read_text(encoding="utf-8")
    _fail_if_credential_present(rendered)
    assert 'region = "global"' in rendered
    assert "DEEPSEEK_API_KEY" not in rendered
    _scan_state_files(local_app_data)


def test_live_deepseek_global_tool_result_continuation_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use one real two-turn tool continuation without touching Windows."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp = _mcp_config(tmp_path, "deepseek-global-e3")
    config = AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "deepseek-global-integration",
        policy_version="deepseek-global-e3-v1",
        provider=_provider(model),
        mcp=mcp,
        policy=PolicyConfig(max_model_turns=3, max_tool_calls=1, max_side_effects=0),
    )
    desktop = StdioDesktopMCP(mcp, timeout_seconds=15.0)
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=create_model_provider(config.provider, allow_actions=False),
            desktop=desktop,
            approvals=ReadOnlyApprovalPort(),
        ),
    )

    async def scenario() -> RunOutcome:
        async with asyncio.timeout(180):
            return await runner.run(
                "Call list_windows exactly once, then report whether the tool says secrets are absent."
            )

    outcome = asyncio.run(scenario())

    _fail_if_credential_present(outcome.text)
    assert outcome.text.strip()
    assert outcome.state.budgets.model_turns_used == 2
    assert outcome.state.budgets.tool_calls_used == 1
    result_events = [
        event
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
    ]
    assert len(result_events) == 1
    assert result_events[0].tool_result is not None
    assert result_events[0].tool_result.tool_name == "list_windows"
    assert "secrets=absent" in result_events[0].tool_result.sanitized_text
    assert desktop.closed
    _scan_state_files(config.state_dir)


def _run_planned_observation(
    tmp_path: Path,
    *,
    model: str,
    tool_name: str,
    task: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    local_app_data = tmp_path / "LocalAppData"
    state_dir = local_app_data / "computer-use-agent" / f"deepseek-plan-{tool_name}"
    fixture = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    child_cwd = tmp_path / f"deepseek {tool_name} plan child"
    child_cwd.mkdir()
    config_path = tmp_path / f"deepseek-{tool_name}-plan.toml"
    config_path.write_text(
        f'''\
[agent]
state_dir = {json.dumps(state_dir.as_posix())}
policy_version = "deepseek-global-plan-e3-v1"

[provider]
name = "deepseek"
model = {json.dumps(model)}
region = "global"
context_window_tokens = 1000000
output_token_reserve = 4096
request_timeout_seconds = 90

[mcp]
executable = {json.dumps(Path(sys.executable).resolve().as_posix())}
args = [{json.dumps(fixture.as_posix())}, "deepseek-global-plan-e3"]
cwd = {json.dumps(child_cwd.as_posix())}
environment = {{ CUMCP_ALLOWLIST = "notepad.exe" }}

[policy]
mode = "read_only"
max_model_turns = 1
max_tool_calls = 1
max_side_effects = 0

[continuation]
enabled = true
ttl_seconds = 900
''',
        encoding="utf-8",
    )
    environment = os.environ.copy()
    source_dir = Path(__file__).parents[2] / "src"
    environment["PYTHONPATH"] = str(source_dir)
    environment["LOCALAPPDATA"] = str(local_app_data)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "computer_use_agent",
            "plan",
            "run",
            "--config",
            str(config_path),
            "--task",
            task,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=210,
        env=environment,
    )
    _fail_if_credential_present(completed.stdout)
    _fail_if_credential_present(completed.stderr)
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    trace_path = state_dir / "traces" / f"{payload['run_id']}.jsonl"
    trace = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    _fail_if_credential_present(
        json.dumps(trace, ensure_ascii=False, separators=(",", ":"))
    )
    tool_events = [
        event
        for event in trace
        if event["kind"] in {"tool_call", "tool_result", "observation"}
    ]
    assert [(event["kind"], event["tool"]) for event in tool_events] == [
        ("tool_call", tool_name),
        ("tool_result", tool_name),
        ("observation", tool_name),
    ]
    _scan_state_files(state_dir)
    return payload, trace


def test_live_deepseek_global_structured_planner_and_final_cycle(
    tmp_path: Path,
) -> None:
    """Exercise JSON-object planning and tool-free final response."""

    model = _require_opt_in()
    payload, _trace = _run_planned_observation(
        tmp_path,
        model=model,
        tool_name="list_windows",
        task=(
            "Plan exactly one list_windows observation, then report whether "
            "the observation says secrets are absent."
        ),
    )
    assert str(payload["text"]).strip()
    assert "absent" in str(payload["text"]).lower()
    assert payload["observation_steps"] == 1
    usage = payload["usage"]
    assert isinstance(usage, dict)
    assert usage["planner_calls"] == 1
    assert usage["final_model_turns"] == 1
    assert usage["tool_calls"] == 1


class _RecordingCompletions:
    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        create = getattr(self._delegate, "create")
        return await create(**kwargs)


def test_live_deepseek_global_withdraws_image_tools_from_the_model_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the text-only route receives no image-returning tool authority."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp = _mcp_config(tmp_path, "deepseek-global-text-only-e3")
    config = AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "deepseek-global-text-only",
        policy_version="deepseek-global-text-only-e3-v1",
        provider=_provider(model),
        mcp=mcp,
        policy=PolicyConfig(max_model_turns=1, max_tool_calls=1, max_side_effects=0),
    )
    provider = create_model_provider(config.provider, allow_actions=False)
    assert isinstance(provider, OpenAIChatCompletionsProvider)
    recording = _RecordingCompletions(provider.completions)
    provider.completions = recording
    desktop = FakeDesktopMCP()
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=provider,
            desktop=desktop,
            approvals=ReadOnlyApprovalPort(),
        ),
    )

    outcome = asyncio.run(runner.run("Return a concise final answer without calling a tool."))

    _fail_if_credential_present(outcome.text)
    assert outcome.text.strip()
    assert len(recording.calls) == 1
    definitions = recording.calls[0]["tools"]
    assert isinstance(definitions, list)
    advertised_names = {
        definition["function"]["name"] for definition in definitions
    }
    assert "screenshot" not in advertised_names
    assert "capture_region" not in advertised_names
    assert desktop.tool_calls == []
    _scan_state_files(config.state_dir)


def test_live_deepseek_global_timeout_stops_before_mcp_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the one-second Host timeout is fixed and grants no MCP authority."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp = _mcp_config(tmp_path, "deepseek-global-timeout-e3")
    config = AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "deepseek-global-timeout",
        policy_version="deepseek-global-timeout-e3-v1",
        provider=_provider(model, timeout_seconds=1),
        mcp=mcp,
        policy=PolicyConfig(max_model_turns=1, max_tool_calls=1, max_side_effects=0),
    )
    desktop = FakeDesktopMCP()
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=create_model_provider(config.provider, allow_actions=False),
            desktop=desktop,
            approvals=ReadOnlyApprovalPort(),
        ),
    )

    with pytest.raises(RunFailure, match="^PROVIDER_TIMEOUT$"):
        asyncio.run(runner.run("Return a concise final answer without calling a tool."))
    assert desktop.tool_calls == []
    _scan_state_files(config.state_dir)
