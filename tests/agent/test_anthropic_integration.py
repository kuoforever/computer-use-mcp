"""Opt-in E3 test: live Claude Messages API plus a harmless stdio MCP child."""
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
from computer_use_agent.providers.anthropic import AnthropicMessagesProvider
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.types import LedgerEventKind


pytestmark = pytest.mark.anthropic_integration


def _require_opt_in() -> str:
    if os.environ.get("RUN_ANTHROPIC_INTEGRATION") != "1":
        pytest.skip("set RUN_ANTHROPIC_INTEGRATION=1 to enable the live Claude test")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is required for the live Claude test")
    model = os.environ.get("ANTHROPIC_INTEGRATION_MODEL")
    if not model:
        pytest.skip("ANTHROPIC_INTEGRATION_MODEL is required to pin cost and behavior")
    pytest.importorskip("anthropic", reason="install the agent-anthropic optional dependency")
    return model


def test_live_claude_read_tool_result_final_answer_cycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make one real provider cycle without touching the real desktop."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    fixture = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    child_cwd = tmp_path / "claude integration child"
    child_cwd.mkdir()
    config = AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "claude-integration",
        policy_version="claude-e3-v1",
        provider=ProviderConfig(name="anthropic", model=model),
        mcp=MCPLaunchConfig(
            executable=Path(sys.executable).resolve(),
            args=(str(fixture), "claude-e3"),
            cwd=child_cwd,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(max_model_turns=3, max_tool_calls=1, max_side_effects=0),
    )
    desktop = StdioDesktopMCP(config.mcp, timeout_seconds=15.0)
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=AnthropicMessagesProvider.from_environment(model),
            desktop=desktop,
            approvals=ReadOnlyApprovalPort(),
        ),
    )

    async def scenario() -> object:
        async with asyncio.timeout(90):
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


def test_live_claude_planned_observation_cli_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the bounded plan CLI against the harmless MCP child."""

    model = _require_opt_in()
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    fixture = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    child_cwd = tmp_path / "claude plan integration child"
    child_cwd.mkdir()
    state_dir = local_app_data / "computer-use-agent" / "claude-plan-integration"
    config_path = tmp_path / "claude-plan.toml"
    config_path.write_text(
        f'''\
[agent]
state_dir = {json.dumps(state_dir.as_posix())}
policy_version = "claude-plan-e3-v1"

[provider]
name = "anthropic"
model = {json.dumps(model)}
context_window_tokens = 128000
output_token_reserve = 1024

[mcp]
executable = {json.dumps(Path(sys.executable).resolve().as_posix())}
args = [{json.dumps(fixture.as_posix())}, "claude-plan-e3"]
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
            (
                "Plan exactly one list_windows observation, then report whether "
                "the observation says secrets are absent."
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["text"].strip()
    assert payload["observation_steps"] == 1
    assert set(payload["usage"]) == {
        "planner_calls",
        "final_model_turns",
        "tool_calls",
        "final_input_tokens",
    }
    assert payload["usage"]["planner_calls"] == 1
    assert payload["usage"]["final_model_turns"] == 1
    assert payload["usage"]["tool_calls"] == 1
    assert payload["usage"]["final_input_tokens"] >= 0
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
        ("tool_call", "list_windows"),
        ("tool_result", "list_windows"),
        ("observation", "list_windows"),
    ]
