from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters

from computer_use_agent.bounded_stdio import bounded_stdio_client
from computer_use_agent.config import MCPLaunchConfig
from computer_use_agent.desktop_mcp import MCPBridgeError, StdioDesktopMCP


def _child() -> Path:
    return Path(__file__).parent / "fixtures" / "stdio_mcp_server.py"


def test_malformed_child_stdout_is_redacted_before_sdk_parsing(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "typed-secret-XYZ"
    caplog.set_level(logging.DEBUG)
    bridge = StdioDesktopMCP(
        MCPLaunchConfig(
            executable=Path(sys.executable).resolve(),
            args=(str(_child()), "malformed-stdout"),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        timeout_seconds=5.0,
    )

    with pytest.raises(MCPBridgeError) as raised:
        asyncio.run(bridge.discover_tools())

    captured = capsys.readouterr()
    assert raised.value.code == "MCP_TRANSPORT_ERROR"
    assert secret not in str(raised.value)
    assert secret not in caplog.text
    assert secret not in captured.out
    assert secret not in captured.err


def test_unterminated_stdout_frame_is_bounded_without_raw_error_content(
    tmp_path: Path,
) -> None:
    secret = "oversized-secret-XYZ"
    parameters = StdioServerParameters(
        command=str(Path(sys.executable).resolve()),
        args=[str(_child()), "oversized-stdout"],
        cwd=tmp_path,
        env={"CUMCP_MODE": "safe_local"},
    )

    async def scenario() -> None:
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with bounded_stdio_client(
                parameters,
                errlog=errlog,
                max_frame_bytes=1024,
            ) as streams:
                async with ClientSession(
                    *streams,
                    read_timeout_seconds=timedelta(seconds=2),
                ) as session:
                    await session.initialize()

    with pytest.raises(Exception) as raised:
        asyncio.run(scenario())

    assert secret not in str(raised.value)
    assert secret not in repr(raised.value)


def test_child_requests_and_notifications_are_rejected_before_sdk_logging(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "typed-secret-notification-XYZ"
    caplog.set_level(logging.DEBUG)
    bridge = StdioDesktopMCP(
        MCPLaunchConfig(
            executable=Path(sys.executable).resolve(),
            args=(str(_child()), "notification-secret"),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        timeout_seconds=5.0,
    )

    with pytest.raises(MCPBridgeError) as raised:
        asyncio.run(bridge.discover_tools())

    captured = capsys.readouterr()
    assert raised.value.code == "MCP_TRANSPORT_ERROR"
    assert secret not in str(raised.value)
    assert secret not in caplog.text
    assert secret not in captured.out
    assert secret not in captured.err
