"""Bounded current native smoke for the focus-taking Decision Card path."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import sys
import tempfile
import threading
import time
from collections import deque
from ctypes import wintypes
from pathlib import Path

import uiautomation as auto

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

_TDM_CLICK_BUTTON = 0x0400 + 102
_FIRST_BUTTON_ID = 1001
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_EX_TOPMOST = 0x00000008


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
            executable=ROOT / ".venv" / "Scripts" / "guarded-desktop-mcp.exe",
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


def _choose_first_button(observed: dict[str, int], controls: list[str]) -> None:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long

    def collect(control, depth: int = 0) -> None:  # noqa: ANN001
        if control.Name:
            controls.append(control.Name)
        if depth < 4:
            for child in control.GetChildren():
                collect(child, depth + 1)

    with auto.UIAutomationInitializerInThread():
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            hwnd = int(user32.FindWindowW(None, "Decision required") or 0)
            if hwnd:
                observed["hwnd"] = hwnd
                if int(user32.GetForegroundWindow() or 0) == hwnd:
                    observed["foreground"] = hwnd
                    observed["style"] = int(
                        user32.GetWindowLongW(hwnd, _GWL_STYLE)
                    )
                    observed["ex_style"] = int(
                        user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
                    )
                    collect(auto.ControlFromHandle(hwnd))
                    user32.SendMessageW(
                        wintypes.HWND(hwnd), _TDM_CLICK_BUTTON, _FIRST_BUTTON_ID, 0
                    )
                    return
            time.sleep(0.05)


async def _approved_run(state_dir: Path, observed: dict[str, int]):
    provider, desktop = _workflow("card_live_allow", complete=True)
    presence = Presence()
    card = DecisionCardApprovalPort(
        DecisionCardWindow(Win32DecisionCardWindowApi()), timeout_seconds=10
    )
    controls: list[str] = []
    clicker = threading.Thread(
        target=_choose_first_button, args=(observed, controls)
    )
    clicker.start()
    outcome = await AgentRunner(
        _config(state_dir), RunnerPorts(provider, desktop, card, presence=presence)
    ).run("Exercise one synthetic approved action", run_id="card_live_allow")
    clicker.join(timeout=5)
    return outcome, desktop, presence, controls


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


async def _human_run(state_dir: Path, timeout_seconds: int) -> dict[str, object]:
    provider, desktop = _workflow("card_human_allow", complete=True)
    presence = Presence()
    card = DecisionCardApprovalPort(
        DecisionCardWindow(Win32DecisionCardWindowApi()),
        timeout_seconds=timeout_seconds,
    )
    outcome = await AgentRunner(
        _config(state_dir),
        RunnerPorts(provider, desktop, card, presence=presence),
    ).run(
        "Human reviews one synthetic exact-effect activation",
        run_id="card_human_allow",
    )
    calls = [call.name for call in desktop.tool_calls]
    if outcome.text != "Complete":
        raise RuntimeError("HUMAN_CARD_WORKFLOW_INCOMPLETE")
    if calls != ["list_windows", "activate_window", "list_windows"]:
        raise RuntimeError("HUMAN_CARD_DISPATCH_SEQUENCE_INVALID")
    if presence.releases != 1:
        raise RuntimeError("HUMAN_CARD_AUTHORITY_NOT_YIELDED")
    return {
        "authority_releases": presence.releases,
        "external_ports": "fake_only",
        "result": "PASS",
        "side_effect_dispatches": 1,
        "tool_sequence": calls,
    }


def _automated_main() -> int:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = wintypes.HWND
    foreground_before = int(user32.GetForegroundWindow() or 0)
    problems: list[str] = []
    observed: dict[str, int] = {}
    root = default_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="decision-card-", dir=root) as raw:
        outcome, approved_desktop, presence, controls = asyncio.run(
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
    forbidden_style = _WS_THICKFRAME | _WS_MINIMIZEBOX | _WS_MAXIMIZEBOX
    if observed.get("style", 0) & forbidden_style:
        problems.append("native Decision Card exposed a forbidden resize/frame style")
    if observed.get("ex_style", 0) & _WS_EX_TOPMOST:
        problems.append("native Decision Card remained topmost")
    expected_controls = {
        "Approve once",
        "Check screen again",
        "Pause and inspect",
        "Stop task",
        "Show details",
    }
    if not expected_controls.issubset(controls):
        missing = sorted(expected_controls.difference(controls))
        problems.append(
            "native Decision Card omitted bounded controls: "
            + ", ".join(missing)
            + f"; observed={controls!r}"
        )
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
        "bounded fixed-frame non-topmost window verified; four current plain-language "
        "options and details affordance rendered; approved choice "
        "used ordinary dispatch and verification; five-second timeout denied with "
        "zero side-effect dispatch; prior foreground restored)"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exercise the bounded native Decision Card with fake external ports."
    )
    parser.add_argument(
        "--human",
        action="store_true",
        help="Wait for a human to approve the exact synthetic effect.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=120,
        help="Human Decision Card timeout (15-300 seconds; default: 120).",
    )
    args = parser.parse_args()
    if not args.human:
        return _automated_main()
    if not 15 <= args.timeout_seconds <= 300:
        parser.error("--timeout-seconds must be between 15 and 300")
    root = default_state_dir()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="decision-card-human-", dir=root) as raw:
        result = asyncio.run(_human_run(Path(raw), args.timeout_seconds))
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
