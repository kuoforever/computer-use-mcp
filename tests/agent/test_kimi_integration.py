"""Opt-in E3 matrix: live Kimi CN API plus a harmless fake MCP child."""
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
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerPorts, RunOutcome
from computer_use_agent.types import LedgerEventKind


pytestmark = pytest.mark.kimi_integration
_KIMI_INTEGRATION_MODEL = "kimi-k2.6"


def _require_opt_in() -> str:
    if os.environ.get("RUN_KIMI_INTEGRATION") != "1":
        pytest.skip("set RUN_KIMI_INTEGRATION=1 to enable the live Kimi test")
    if not os.environ.get("MOONSHOT_CN_API_KEY"):
        pytest.skip("MOONSHOT_CN_API_KEY is required for the live Kimi CN test")
    configured_model = os.environ.get("KIMI_INTEGRATION_MODEL")
    if configured_model not in {None, _KIMI_INTEGRATION_MODEL}:
        pytest.fail("KIMI_INTEGRATION_MODEL must be exactly kimi-k2.6")
    pytest.importorskip("openai", reason="install the agent-openai optional dependency")
    return _KIMI_INTEGRATION_MODEL


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
        name="kimi",
        model=model,
        region="cn",
        context_window_tokens=256000,
        output_token_reserve=512,
        request_timeout_seconds=timeout_seconds,
    )


def test_kimi_cn_setup_and_doctor_use_the_formal_product_route(tmp_path: Path) -> None:
    """Generate and diagnose the user-facing Kimi CN configuration."""

    _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    config_path = tmp_path / "kimi-cn-setup.toml"
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
            "kimi",
            "--model",
            "kimi-k2.6",
            "--region",
            "cn",
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
    assert setup.returncode == 0, setup.stderr
    setup_payload = json.loads(setup.stdout)
    assert setup_payload["configuration"]["provider"] == "kimi"
    assert setup_payload["configuration"]["model"] == "kimi-k2.6"
    assert setup_payload["configuration"]["region"] == "cn"
    assert setup_payload["provider_setup"] == {
        "credential_environment": "MOONSHOT_CN_API_KEY",
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
    assert doctor.returncode == 0, doctor.stderr
    doctor_payload = json.loads(doctor.stdout)
    assert doctor_payload["provider"] == "kimi"
    assert doctor_payload["ready"] is True
    assert set(doctor_payload["checks"].values()) == {"pass"}
    assert doctor_payload["mcp"]["tool_count"] == 13

    rendered = config_path.read_text(encoding="utf-8")
    assert 'region = "cn"' in rendered
    assert "MOONSHOT_CN_API_KEY" not in rendered
    if os.environ["MOONSHOT_CN_API_KEY"] in rendered:
        pytest.fail("generated configuration persisted the provider credential")


def test_live_kimi_cn_tool_result_continuation_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use one real two-turn tool continuation without touching Windows."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp = _mcp_config(tmp_path, "kimi-cn-e3")
    config = AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "kimi-cn-integration",
        policy_version="kimi-cn-e3-v1",
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
        async with asyncio.timeout(120):
            return await runner.run(
                "Call list_windows exactly once, then report whether the tool says secrets are absent."
            )

    outcome = asyncio.run(scenario())

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


def _run_planned_observation(
    tmp_path: Path,
    *,
    model: str,
    tool_name: str,
    task: str,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    local_app_data = tmp_path / "LocalAppData"
    state_dir = local_app_data / "computer-use-agent" / f"kimi-plan-{tool_name}"
    fixture = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    child_cwd = tmp_path / f"kimi {tool_name} plan child"
    child_cwd.mkdir()
    config_path = tmp_path / f"kimi-{tool_name}-plan.toml"
    config_path.write_text(
        f'''\
[agent]
state_dir = {json.dumps(state_dir.as_posix())}
policy_version = "kimi-cn-plan-e3-v1"

[provider]
name = "kimi"
model = {json.dumps(model)}
region = "cn"
context_window_tokens = 256000
output_token_reserve = 512
request_timeout_seconds = 90

[mcp]
executable = {json.dumps(Path(sys.executable).resolve().as_posix())}
args = [{json.dumps(fixture.as_posix())}, "kimi-cn-plan-e3"]
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
        timeout=150,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    trace_path = state_dir / "traces" / f"{payload['run_id']}.jsonl"
    trace = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
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
    return payload, trace


def test_live_kimi_cn_structured_planner_and_final_cycle(tmp_path: Path) -> None:
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


def test_live_kimi_cn_image_planner_and_final_cycle(tmp_path: Path) -> None:
    """Pass one synthetic 1x1 PNG through the reviewed image boundary."""

    model = _require_opt_in()
    payload, _trace = _run_planned_observation(
        tmp_path,
        model=model,
        tool_name="screenshot",
        task="Plan exactly one screenshot observation, then state that an image was supplied.",
    )
    assert str(payload["text"]).strip()
    assert "image" in str(payload["text"]).lower()
    assert payload["observation_steps"] == 1


def test_live_kimi_cn_timeout_stops_before_mcp_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the one-second Host timeout is fixed and grants no MCP authority."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    mcp = _mcp_config(tmp_path, "kimi-cn-timeout-e3")
    config = AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "kimi-cn-timeout",
        policy_version="kimi-cn-timeout-e3-v1",
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
