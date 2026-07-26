"""Isolated on-device smoke for the bounded ``capture_region`` observation.

The probe draws the project's real passive Win32 progress window using only
fixed synthetic records, reads that window's physical-pixel bounds, and asks
the project stdio MCP child to capture exactly that rectangle. It validates the
returned envelope and PNG in memory, then discards the pixels without writing
them to disk or printing them.

The result is inconclusive if local input occurs or the foreground window
changes during the probe. Run only with operator approval on an interactive
Windows desktop:

    python scripts/smoke_capture_region.py
"""
from __future__ import annotations

import asyncio
import ctypes
import hashlib
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_agent.config import MCPLaunchConfig  # noqa: E402
from computer_use_agent.desktop_mcp import StdioDesktopMCP  # noqa: E402
from computer_use_agent.progress_view import (  # noqa: E402
    CallBudget,
    ProgressProjection,
    RunProgressView,
)
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    CallIdentity,
    ToolCall,
    ToolCallStatus,
    ToolResultStatus,
)


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
        raise OSError("GetWindowRect failed")
    width = int(rect.right - rect.left)
    height = int(rect.bottom - rect.top)
    if rect.left < 0 or rect.top < 0 or width <= 0 or height <= 0:
        raise RuntimeError("capture fixture is outside the reviewed primary-display domain")
    return int(rect.left), int(rect.top), width, height


def _synthetic() -> ProgressProjection:
    view = RunProgressView(
        run_id="run_capture_fixture",
        phase="OBSERVING",
        display_state="In progress at last checkpoint; liveness unknown",
        is_terminal=False,
        liveness_known=False,
        needs_reobserve=False,
        model_calls=CallBudget(1, 3),
        tool_calls=CallBudget(1, 4),
        input_tokens=0,
        output_tokens=0,
        token_coverage_known=False,
        image_results=0,
        tool_failures=0,
        elapsed_known=False,
        duration_ms=None,
        failure_code=None,
    )
    return ProgressProjection(
        views=(view,),
        unavailable_run_ids=(),
        unavailable_unnamed=0,
    )


def _capture_call(region: tuple[int, int, int, int]) -> ToolCall:
    x, y, width, height = region
    return ToolCall(
        identity=CallIdentity(
            run_id="run_capture_region_smoke",
            turn_id="turn_1",
            call_id="call_1",
        ),
        name="capture_region",
        arguments={"x": x, "y": y, "w": width, "h": height},
        status=ToolCallStatus.AUTHORIZED,
    )


async def _capture(region: tuple[int, int, int, int]):  # noqa: ANN202
    launch = MCPLaunchConfig(
        executable=(ROOT / ".venv" / "Scripts" / "guarded-desktop-mcp.exe").resolve(),
        args=(),
        cwd=ROOT,
        environment={"CUMCP_ALLOWLIST": "python.exe"},
    )
    bridge = StdioDesktopMCP(launch, timeout_seconds=30.0)
    async with bridge:
        tools = await bridge.discover_tools()
        started = time.perf_counter()
        result = await bridge.call_tool(_capture_call(region))
        elapsed_ms = (time.perf_counter() - started) * 1000
    return tools, result, elapsed_ms


def main() -> int:
    api = Win32ProgressWindowApi()
    window = PassiveProgressWindow(api, title="Computer Use Capture Fixture")
    foreground_before = api.foreground()
    tick_before = _last_input_tick()

    try:
        hwnd = window.open(_synthetic())
        window.move(80, 80)
        api.pump()
        region = _window_rect(hwnd)
        tools, result, elapsed_ms = asyncio.run(_capture(region))
        api.pump()
        foreground_after = api.foreground()
        tick_after = _last_input_tick()
    finally:
        window.close()
        api.pump()

    if tick_after != tick_before:
        print("RESULT: INCONCLUSIVE (local input occurred during the probe)")
        return 2
    if foreground_after != foreground_before:
        print(
            "RESULT: FAIL (foreground changed "
            f"{foreground_before:#x} -> {foreground_after:#x})"
        )
        return 1

    problems: list[str] = []
    expected_tools = {
        "activate_window",
        "capture_region",
        "click",
        "document_text",
        "find",
        "key",
        "list_windows",
        "ocr",
        "screenshot",
        "type",
        "ui_snapshot",
    }
    if {tool.name for tool in tools} != expected_tools:
        problems.append("the stdio tool handshake drifted")
    if result.status is not ToolResultStatus.SUCCESS:
        problems.append(f"capture returned {result.status.value}")
    if len(result.images) != 1:
        problems.append("capture did not return exactly one PNG")

    envelope: dict[str, object] = {}
    try:
        parsed = json.loads(result.sanitized_text)
        if isinstance(parsed, dict):
            envelope = parsed
        else:
            problems.append("capture envelope was not an object")
    except json.JSONDecodeError:
        problems.append("capture envelope was not JSON")

    x, y, width, height = region
    image = result.images[0] if result.images else None
    if envelope.get("source") != "image":
        problems.append("capture envelope source drifted")
    if envelope.get("scope") != {"display": "primary", "region": [x, y, width, height]}:
        problems.append("capture envelope region did not match the requested window")
    if envelope.get("coordinate_space") != "primary_display_physical_pixels":
        problems.append("capture coordinate space drifted")
    if envelope.get("complete") is not True or envelope.get("truncated") is not False:
        problems.append("capture completeness flags drifted")
    if image is not None:
        if (image.width, image.height) != (width, height):
            problems.append("PNG dimensions did not match the requested window")
        digest = hashlib.sha256(image.data).hexdigest()
        if envelope.get("image_digest") != digest:
            problems.append("capture envelope digest did not match the returned PNG")
        if envelope.get("encoded_bytes") != len(image.data):
            problems.append("capture envelope byte count did not match the returned PNG")

    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    png_bytes = len(image.data) if image is not None else 0
    print(
        "RESULT: PASS ("
        f"region={x},{y},{width},{height}; "
        f"png_bytes={png_bytes}; digest={envelope['image_digest']}; "
        f"latency_ms={elapsed_ms:.1f}; foreground={foreground_before:#x}; "
        "11-tool handshake matched; PNG discarded)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
