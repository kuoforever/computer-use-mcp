from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from computer_use_agent.config import MCPLaunchConfig
from computer_use_agent.desktop_mcp import StdioDesktopMCP
from computer_use_agent.types import CallIdentity, ToolCall, ToolCallStatus, ToolResultStatus


def test_real_stdio_child_uses_fixed_launch_and_excludes_provider_secrets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "AWS_SECRET_ACCESS_KEY",
        "UNRELATED_SECRET",
    ):
        monkeypatch.setenv(name, f"sentinel-{name}")

    child = Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"
    child_cwd = tmp_path / "child cwd 空格"
    child_cwd.mkdir()
    launch = MCPLaunchConfig(
        executable=Path(sys.executable).resolve(),
        args=(str(child), "marker with spaces", "参数"),
        cwd=child_cwd,
        environment={"CUMCP_ALLOWLIST": "notepad.exe"},
    )
    bridge = StdioDesktopMCP(launch, timeout_seconds=10.0)
    text_call = ToolCall(
        identity=CallIdentity(run_id="run_stdio", turn_id="turn_1", call_id="call_1"),
        name="list_windows",
        arguments={},
        status=ToolCallStatus.AUTHORIZED,
    )
    screenshot_call = ToolCall(
        identity=CallIdentity(run_id="run_stdio", turn_id="turn_1", call_id="call_2"),
        name="screenshot",
        arguments={},
        status=ToolCallStatus.AUTHORIZED,
    )
    typed_secret = "typed-stdio-secret"
    type_call = ToolCall(
        identity=CallIdentity(run_id="run_stdio", turn_id="turn_1", call_id="call_3"),
        name="type",
        arguments={"text": typed_secret},
        status=ToolCallStatus.AUTHORIZED,
    )

    async def scenario() -> tuple[object, object, object]:
        async with bridge:
            return (
                await bridge.call_tool(text_call),
                await bridge.call_tool(screenshot_call),
                await bridge.call_tool(type_call),
            )

    result, screenshot, type_result = asyncio.run(scenario())

    assert result.status is ToolResultStatus.SUCCESS
    assert "secrets=absent" in result.sanitized_text
    assert "cwd=child cwd 空格" in result.sanitized_text
    assert "argv=marker with spaces|参数" in result.sanitized_text
    assert "allowlist=notepad.exe" in result.sanitized_text
    assert "sentinel-" not in result.sanitized_text
    assert screenshot.status is ToolResultStatus.SUCCESS
    assert len(screenshot.images) == 1
    assert (screenshot.images[0].width, screenshot.images[0].height) == (1, 1)
    assert type_result.status is ToolResultStatus.SUCCESS
    assert type_result.sanitized_text == ""
    assert typed_secret not in repr(type_result)
    assert bridge.closed
    assert "STDERR_SECRET_SENTINEL" not in capsys.readouterr().err
