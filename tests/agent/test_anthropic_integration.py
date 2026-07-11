"""Opt-in E3 test: live Claude Messages API plus a harmless stdio MCP child."""
from __future__ import annotations

import asyncio
import os
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
