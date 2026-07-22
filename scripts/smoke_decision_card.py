"""Operator-approved native smoke for the focus-taking Decision Card path."""
from __future__ import annotations

import asyncio
import ctypes
import sys
import tempfile
import threading
import time
from collections import deque
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass

from computer_use_agent.approvals import DecisionCardApprovalPort  # noqa: E402
from computer_use_agent.config import (  # noqa: E402
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
)
from computer_use_agent.decision_card_window import DecisionCardWindow  # noqa: E402
from computer_use_agent.decision_card_window_win32 import (  # noqa: E402
    Win32DecisionCardWindowApi,
)
from computer_use_agent.fakes import (  # noqa: E402
    FakeDesktopMCP,
    FakeModelProvider,
)
from computer_use_agent.runner import (  # noqa: E402
    AgentRunner,
    RunFailure,
    RunnerPorts,
)
from computer_use_agent.types import (  # noqa: E402
    CallIdentity,
    DispatchCertainty,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)

_WM_COMMAND = 0x0111
_IDYES = 6


class Presence:
    def __init__(self) -> None:
        self.releases = 0

    def on_phase(self, _phase) -> None:  # noqa: ANN001
        pass

    def estop(self) -> None:
        pass

    def release(self) -> None:
        self.releases += 1


def _config(state_dir: Path) -> AgentConfig:
    return AgentConfig(
        state_dir=state_dir,
        policy_version="decision-card-live-v1",
        provider=ProviderConfig("openai", "fake-live"),
        mcp=MCPLaunchConfig(
            executable=ROOT / ".venv" / "Scripts" / "computer-use-mcp.exe",
            args=(),
            cwd=ROOT,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=6,
            max_tool_calls=6,
            max_side_effects=1,
        ),
    )


def _workflow(run_id: str, *, complete: bool) -> tuple[FakeModelProvider, FakeDesktopMCP]:
    observe = ToolCall(
        CallIdentity(run_id, "turn_1", "call_1"), "list_windows", {}
    )
    action = ToolCall(
        CallIdentity(run_id, "turn_2", "call_2"),
        "activate_window",
        {"window_id": "42"},
    )
    turns = [
        ModelTurn(run_id, "turn_1", "response_1", "", (observe,)),
        ModelTurn(run_id, "turn_2", "response_2", "", (action,)),
    ]
    results = [
        ToolResult(
            observe.identity,
            observe.name,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
            sanitized_text='* 42 | synthetic.exe | "Synthetic"',
        )
    ]
    if complete:
        verify = ToolCall(
            CallIdentity(run_id, "turn_3", "call_3"), "list_windows", {}
        )
        turns.extend(
            [
                ModelTurn(run_id, "turn_3", "response_3", "", (verify,)),
                ModelTurn(run_id, "turn_4", "response_4", "Complete"),
            ]
        )
        results.extend(
            [
                ToolResult(
                    action.identity,
                    action.name,
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                ),
                ToolResult(
                    verify.identity,
                    verify.name,
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text='* 42 | synthetic.exe | "Synthetic"',
                ),
            ]
        )
    return FakeModelProvider(turns=deque(turns)), FakeDesktopMCP(results=deque(results))


def _choose_first_button(observed: dict[str, int]) -> None:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        hwnd = int(user32.FindWindowW(None, "Decision required") or 0)
        if hwnd:
            observed["hwnd"] = hwnd
            if int(user32.GetForegroundWindow() or 0) == hwnd:
                observed["foreground"] = hwnd
                user32.SendMessageW(wintypes.HWND(hwnd), _WM_COMMAND, _IDYES, 0)
                return
        time.sleep(0.05)


async def _approved_run(state_dir: Path, observed: dict[str, int]):
    provider, desktop = _workflow("card_live_allow", complete=True)
    presence = Presence()
    card = DecisionCardApprovalPort(
        DecisionCardWindow(Win32DecisionCardWindowApi()), timeout_seconds=10
    )
    clicker = threading.Thread(target=_choose_first_button, args=(observed,))
    clicker.start()
    outcome = await AgentRunner(
        _config(state_dir), RunnerPorts(provider, desktop, card, presence=presence)
    ).run("Exercise one synthetic approved action", run_id="card_live_allow")
    clicker.join(timeout=5)
    return outcome, desktop, presence


async def _timeout_run(state_dir: Path):
    provider, desktop = _workflow("card_live_timeout", complete=False)
    card = DecisionCardApprovalPort(
        DecisionCardWindow(Win32DecisionCardWindowApi()), timeout_seconds=5
    )
    try:
        await AgentRunner(
            _config(state_dir),
            RunnerPorts(provider, desktop, card, presence=Presence()),
        ).run("Exercise Decision Card timeout", run_id="card_live_timeout")
    except RunFailure as exc:
        return exc.code, desktop
    return "UNEXPECTED_SUCCESS", desktop


def main() -> int:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    foreground_before = int(user32.GetForegroundWindow() or 0)
    problems: list[str] = []
    observed: dict[str, int] = {}
    root = default_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="decision-card-", dir=root) as raw:
        outcome, approved_desktop, presence = asyncio.run(
            _approved_run(Path(raw), observed)
        )
        timeout_code, timeout_desktop = asyncio.run(_timeout_run(Path(raw)))

    if outcome.text != "Complete":
        problems.append("approved synthetic workflow did not complete")
    if [call.name for call in approved_desktop.tool_calls] != [
        "list_windows",
        "activate_window",
        "list_windows",
    ]:
        problems.append("approved workflow did not use the ordinary dispatch sequence")
    if presence.releases != 1:
        problems.append("Agent authority was not yielded exactly once before the card")
    if observed.get("hwnd", 0) == 0 or observed.get("foreground") != observed.get("hwnd"):
        problems.append("native Decision Card did not become the foreground window")
    if timeout_code != "APPROVAL_DENIED":
        problems.append(f"timeout did not fail closed ({timeout_code})")
    if [call.name for call in timeout_desktop.tool_calls] != ["list_windows"]:
        problems.append("timeout reached the side-effect dispatch boundary")
    foreground_after = int(user32.GetForegroundWindow() or 0)
    if foreground_after != foreground_before:
        problems.append(
            f"foreground was not restored {foreground_before:#x} -> {foreground_after:#x}"
        )
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1
    print(
        f"RESULT: PASS (card foreground {observed['hwnd']:#x}; authority yielded; "
        "approved choice used ordinary dispatch and verification; five-second "
        "timeout denied with zero side-effect dispatch; prior foreground restored)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
