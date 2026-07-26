"""Live smoke for fixed synthetic-campaign progress lifecycle wiring."""

from __future__ import annotations

import asyncio
import ctypes
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from ctypes import wintypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for stream in (sys.stdout, sys.stderr):
    try:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_agent import cli as agent_cli  # noqa: E402
from computer_use_agent.campaign_observation_runtime import (  # noqa: E402
    prepare_synthetic_campaign,
)
from computer_use_agent.config import (  # noqa: E402
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
)
from computer_use_agent.progress_lifecycle import RunProgressCoordinator  # noqa: E402
from computer_use_agent.progress_poller import ProgressPoller  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.runner import AgentRunner  # noqa: E402

CAMPAIGN_ID = "campaign_progress_live"
RUN_ID = "campaign_progress_run"


class RecordingWin32ProgressApi(Win32ProgressWindowApi):
    """Retain only fixed rendered lines and native lifecycle counts."""

    def __init__(self) -> None:
        super().__init__()
        self.created_handles: list[int] = []
        self.destroyed_handles: list[int] = []
        self.rendered: list[tuple[str, ...]] = []

    def create(self, *, ex_style: int, style: int, title: str) -> int:
        hwnd = super().create(ex_style=ex_style, style=style, title=title)
        self.created_handles.append(hwnd)
        return hwnd

    def set_lines(self, hwnd: int, lines: Sequence[str]) -> None:
        safe_lines = tuple(lines)
        self.rendered.append(safe_lines)
        super().set_lines(hwnd, safe_lines)

    def destroy(self, hwnd: int) -> None:
        self.destroyed_handles.append(hwnd)
        super().destroy(hwnd)


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _config(state_dir: Path) -> AgentConfig:
    return AgentConfig(
        state_dir=state_dir,
        policy_version="campaign-progress-live-v1",
        provider=ProviderConfig("openai", "forbidden"),
        mcp=MCPLaunchConfig(
            executable=ROOT / ".venv" / "Scripts" / "computer-use-mcp.exe",
            args=(),
            cwd=ROOT,
            environment={
                "CUMCP_MODE": "safe_local",
                "CUMCP_ALLOWLIST": "notepad.exe",
            },
        ),
        policy=PolicyConfig(
            max_model_turns=1,
            max_tool_calls=1,
            max_side_effects=0,
        ),
    )


async def _run() -> tuple[int, dict[str, object], RecordingWin32ProgressApi, int, int, int, int]:
    local_root = default_state_dir()
    local_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="campaign-progress-smoke-",
        dir=local_root,
    ) as raw_dir:
        config = _config(Path(raw_dir).resolve())
        now = datetime.now(UTC).replace(microsecond=0)
        prepare_synthetic_campaign(
            AgentRunner(config),
            campaign_id=CAMPAIGN_ID,
            run_id=RUN_ID,
            now=now,
        )

        api = RecordingWin32ProgressApi()
        window = PassiveProgressWindow(api)
        lifecycle = RunProgressCoordinator(
            ProgressPoller(config.state_dir, window, interval_seconds=0.05),
            pump=api.pump,
        )
        original_load = agent_cli.load_agent_config
        original_progress = agent_cli._progress_lifecycle
        original_now = agent_cli._campaign_now
        agent_cli.load_agent_config = lambda _path: config
        agent_cli._progress_lifecycle = lambda _config: lifecycle
        agent_cli._campaign_now = lambda: now
        foreground_before = api.foreground()
        input_before = _last_input_tick()
        captured = io.StringIO()
        try:
            with redirect_stdout(captured):
                code = await agent_cli._run_claimed_synthetic_campaign_async(
                    config.state_dir / "unused.toml",
                    CAMPAIGN_ID,
                    RUN_ID,
                )
        finally:
            agent_cli.load_agent_config = original_load
            agent_cli._progress_lifecycle = original_progress
            agent_cli._campaign_now = original_now
        foreground_after = api.foreground()
        input_after = _last_input_tick()
        payload = json.loads(captured.getvalue())
        return (
            code,
            payload,
            api,
            foreground_before,
            foreground_after,
            input_before,
            input_after,
        )


def main() -> int:
    (
        code,
        payload,
        api,
        foreground_before,
        foreground_after,
        input_before,
        input_after,
    ) = asyncio.run(_run())
    drawn = "\n".join(line for frame in api.rendered for line in frame)
    problems: list[str] = []
    if code != 0:
        problems.append(f"campaign command returned {code}")
    if payload.get("campaign_id") != CAMPAIGN_ID:
        problems.append("campaign result identity drifted")
    if payload.get("stop_code") != "ITEM_LIMIT":
        problems.append("campaign did not stop at the fixed item limit")
    usage = payload.get("usage")
    if not isinstance(usage, dict) or usage.get("tool_calls") != 1:
        problems.append("campaign did not retain exactly one tool call")
    if len(api.created_handles) != 1 or api.created_handles != api.destroyed_handles:
        problems.append("native progress window lifecycle was not exactly one create/destroy")
    if (
        "Active campaigns  1" not in drawn
        or f"{CAMPAIGN_ID}  Running" not in drawn
    ):
        problems.append("validated active campaign state never reached the native window")
    if foreground_after != foreground_before:
        problems.append(
            f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
        )
    forbidden_output_keys = {"text", "title", "windows", "screenshot", "task"}
    if forbidden_output_keys.intersection(payload):
        problems.append("campaign output exposed an unreviewed content field")
    if input_after != input_before:
        print("RESULT: INCONCLUSIVE (local input occurred during the probe)")
        return 2
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; one "
        "validated Active campaign reached one native progress window; the "
        "fixed synthetic command made one list_windows call; cleanup destroyed "
        "the window; no task, title, window, or screenshot field was retained)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
