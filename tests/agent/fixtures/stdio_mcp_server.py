"""Harmless stdio MCP child used by the Agent bridge integration test."""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.types import Image as MCPImage

if "malformed-stdout" in sys.argv[1:]:
    sys.stdout.write("{not-json typed-secret-XYZ\n")
    sys.stdout.flush()
    raise SystemExit(0)

if "oversized-stdout" in sys.argv[1:]:
    sys.stdout.write("oversized-secret-XYZ" + ("x" * 4096))
    sys.stdout.flush()
    raise SystemExit(0)

if "notification-secret" in sys.argv[1:]:
    sys.stdout.write(
        '{"jsonrpc":"2.0","method":"notifications/message","params":'
        '{"level":"info","data":"typed-secret-notification-XYZ"}}\n'
    )
    sys.stdout.flush()
    raise SystemExit(0)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
_SECRET_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "UNRELATED_SECRET",
)

print("STDERR_SECRET_SENTINEL", file=sys.stderr, flush=True)

mcp = FastMCP("scripted-agent-test-child")


@mcp.tool()
def ui_snapshot(scope: str = "foreground") -> str:
    return f"snapshot:{scope}"


@mcp.tool()
def find(query: str, scope: str = "foreground") -> str:
    return f"find:{query}:{scope}"


@mcp.tool()
def list_windows() -> str:
    secrets = "present" if any(name in os.environ for name in _SECRET_NAMES) else "absent"
    marker = "|".join(sys.argv[1:])
    allowlist = os.environ.get("CUMCP_ALLOWLIST", "")
    return (
        f"secrets={secrets};cwd={Path.cwd().name};argv={marker};"
        f"allowlist={allowlist}"
    )


@mcp.tool()
def screenshot() -> MCPImage:
    return MCPImage(data=_PNG, format="png")


@mcp.tool(structured_output=False)
def capture_region(x: int, y: int, w: int, h: int) -> list[str | MCPImage]:
    envelope = (
        f'{{"source":"image","scope":{{"display":"primary","region":[{x},{y},{w},{h}]}},'
        f'"crop_origin":[{x},{y}],"width":1,"height":1}}'
    )
    return [envelope, MCPImage(data=_PNG, format="png")]


@mcp.tool()
def ocr(x: int, y: int, w: int, h: int) -> str:
    return f'{{"source":"ocr","scope":{{"region":[{x},{y},{w},{h}]}},"runs":[]}}'


@mcp.tool()
def document_text(scope: str = "foreground") -> str:
    return f'{{"source":"document_text","scope":"{scope}","blocks":[]}}'


if os.environ.get("CUMCP_BROWSER_OBSERVATION", "off").strip().lower() == "cdp":

    @mcp.tool()
    def browser_snapshot(
        page_index: int = 0,
        detail: Literal["semantic", "text", "both"] = "semantic",
    ) -> str:
        return (
            f'{{"version":1,"source":"playwright_cdp_read_only",'
            f'"page_index":{page_index},"detail":"{detail}",'
            f'"action_backend":"os_input_only"}}'
        )


@mcp.tool()
def activate_window(window_id: str) -> str:
    return "ok"


@mcp.tool()
def click(ref: str | None = None, x: int | None = None, y: int | None = None) -> str:
    return "ok"


@mcp.tool()
def scroll(x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> str:
    return "ok"


@mcp.tool()
def drag(x: int, y: int, to_x: int, to_y: int, duration_ms: int = 250) -> str:
    return "ok"


@mcp.tool(name="type")
def type_text(text: str, ref: str | None = None) -> str:
    return "ok"


@mcp.tool()
def key(combo: str) -> str:
    return "ok"


if __name__ == "__main__":
    mcp.run()
