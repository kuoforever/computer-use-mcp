"""Operator-approved live smoke for ordinary Host presence lifecycle wiring."""
from __future__ import annotations

import asyncio
import sys
import tempfile
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from computer_use_agent.config import (  # noqa: E402
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
)
from computer_use_agent.fakes import (  # noqa: E402
    FakeApprovalPort,
    FakeDesktopMCP,
    FakeModelProvider,
)
from computer_use_agent.presence import PresenceSnapshot  # noqa: E402
from computer_use_agent.presence_lifecycle import RunPresenceCoordinator  # noqa: E402
from computer_use_agent.presence_window import PassivePresenceWindow  # noqa: E402
from computer_use_agent.presence_window_win32 import (  # noqa: E402
    Win32PresenceWindowApi,
)
from computer_use_agent.runner import AgentRunner, RunnerPorts  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    CallIdentity,
    DispatchCertainty,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


class RecordingSurface:
    """Record only fixed paint state and native identity during the live run."""

    def __init__(self, window: PassivePresenceWindow, api: Win32PresenceWindowApi) -> None:
        self.window = window
        self.api = api
        self.labels: list[str] = []
        self.handles: list[int] = []

    def sync(self, snapshot: PresenceSnapshot) -> object:
        update = self.window.sync(snapshot)
        self.api.pump()
        hwnd = self.window.hwnd
        if hwnd is not None:
            state = self.api.state(hwnd)
            if state is None:
                raise RuntimeError("PRESENCE_PAINT_STATE_MISSING")
            self.handles.append(hwnd)
            self.labels.append(state[0].label)
        return update

    def close(self) -> None:
        self.window.close()
        self.api.pump()


def _config(state_dir: Path) -> AgentConfig:
    return AgentConfig(
        state_dir=state_dir,
        policy_version="presence-live-v1",
        provider=ProviderConfig("openai", "fake-live"),
        mcp=MCPLaunchConfig(
            executable=ROOT / ".venv" / "Scripts" / "computer-use-mcp.exe",
            args=(),
            cwd=ROOT,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(),
    )


async def _successful_run(state_dir: Path, surface: RecordingSurface) -> str:
    identity = CallIdentity("presence_live", "turn_1", "call_1")
    provider = FakeModelProvider(turns=deque([
        ModelTurn(
            "presence_live", "turn_1", "response_1", "",
            tool_calls=(ToolCall(identity, "list_windows", {}),),
        ),
        ModelTurn("presence_live", "turn_2", "response_2", "Complete"),
    ]))
    desktop = FakeDesktopMCP(results=deque([ToolResult(
        identity,
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Synthetic",
    )]))
    coordinator = RunPresenceCoordinator(surface)
    outcome = await AgentRunner(
        _config(state_dir),
        RunnerPorts(provider, desktop, FakeApprovalPort(), presence=coordinator),
    ).run("Observe one synthetic window", run_id="presence_live")
    return outcome.text


async def _estop_run(state_dir: Path, surface: RecordingSurface) -> str:
    identity = CallIdentity("presence_estop", "turn_1", "call_1")
    provider = FakeModelProvider(turns=deque([
        ModelTurn(
            "presence_estop", "turn_1", "response_1", "",
            tool_calls=(ToolCall(identity, "list_windows", {}),),
        ),
        ModelTurn("presence_estop", "turn_2", "response_2", "Stopped"),
    ]))
    desktop = FakeDesktopMCP(results=deque([ToolResult(
        identity,
        "list_windows",
        ToolResultStatus.REJECTED,
        DispatchCertainty.NOT_DISPATCHED,
        code="ABORTED",
    )]))
    coordinator = RunPresenceCoordinator(surface)
    outcome = await AgentRunner(
        _config(state_dir),
        RunnerPorts(provider, desktop, FakeApprovalPort(), presence=coordinator),
    ).run("Exercise synthetic E-stop", run_id="presence_estop")
    return outcome.text


def main() -> int:
    api = Win32PresenceWindowApi()
    foreground_before = api.foreground()
    problems: list[str] = []
    state_root = default_state_dir()
    state_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="presence-lifecycle-", dir=state_root) as raw:
        success_window = PassivePresenceWindow(api)
        success_surface = RecordingSurface(success_window, api)
        text = asyncio.run(_successful_run(Path(raw), success_surface))
        if text != "Complete":
            problems.append("ordinary AgentRunner did not complete")
        expected = {"Observing", "Planning", "Executing"}
        if not expected.issubset(success_surface.labels):
            problems.append(f"missing fixed lifecycle labels: {success_surface.labels!r}")
        if len(set(success_surface.handles)) != 1:
            problems.append("nonterminal phases did not reuse one native window")
        if success_window.hwnd is not None:
            problems.append("terminal success did not destroy the halo")

        estop_api = Win32PresenceWindowApi()
        estop_window = PassivePresenceWindow(estop_api)
        estop_surface = RecordingSurface(estop_window, estop_api)
        stopped = asyncio.run(_estop_run(Path(raw), estop_surface))
        if stopped != "Stopped" or estop_window.hwnd is not None:
            problems.append("MCP ABORTED did not latch the halo off")

    foreground_after = api.foreground()
    if foreground_after != foreground_before:
        problems.append(
            f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
        )
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1
    print(
        f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; "
        f"durable labels {success_surface.labels!r}; one HWND reused; "
        "terminal success and MCP ABORTED destroyed the halo)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
