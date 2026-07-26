"""Live smoke for bounded plan-run progress lifecycle wiring."""

from __future__ import annotations

import asyncio
import ctypes
import io
import json
import sys
import tempfile
import time
from collections import deque
from contextlib import redirect_stdout
from ctypes import wintypes
from dataclasses import dataclass, field
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
from computer_use_agent.config import (  # noqa: E402
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
    default_state_dir,
)
from computer_use_agent.executor_final import (  # noqa: E402
    FinalResponseRequest,
    FinalResponseResult,
)
from computer_use_agent.fakes import FakePlanner  # noqa: E402
from computer_use_agent.progress_lifecycle import RunProgressCoordinator  # noqa: E402
from computer_use_agent.progress_poller import ProgressPoller  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.providers import (  # noqa: E402
    openai_final as final_module,
)
from computer_use_agent.providers import (  # noqa: E402
    openai_planner as planner_module,
)
from computer_use_agent.trace import read_run_checkpoint  # noqa: E402
from computer_use_agent.types import ModelUsage  # noqa: E402

TASK_SECRET = "PLAN_PROGRESS_TASK_MUST_NOT_APPEAR"
FINAL_TEXT = "One bounded desktop observation completed."
PLAN_CANDIDATE = (
    '{"version":1,"steps":['
    '{"action":"tool","tool":"list_windows","arguments":{}},'
    '{"action":"final_response"}]}'
)


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


@dataclass
class FixedFinalPort:
    """Return one tool-free fixed response without opening a provider port."""

    name: str = "fixed-final"
    calls: list[FinalResponseRequest] = field(default_factory=list)

    async def create_final_response(
        self,
        request: FinalResponseRequest,
    ) -> FinalResponseResult:
        self.calls.append(request)
        return FinalResponseResult(
            run_id=request.run_id,
            turn_id=request.turn_id,
            provider_response_id="fixed_final_response",
            text=FINAL_TEXT,
            usage=ModelUsage(3, 4),
        )


def _last_input_tick() -> int:
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    return int(info.dwTime)


def _wait_for_idle(*, stable_seconds: float = 3.0, timeout_seconds: float = 30.0) -> bool:
    """Wait for a quiet input window before measuring non-interference."""

    started = time.monotonic()
    stable_since = started
    last_tick = _last_input_tick()
    while time.monotonic() - started < timeout_seconds:
        time.sleep(0.05)
        current_tick = _last_input_tick()
        now = time.monotonic()
        if current_tick != last_tick:
            last_tick = current_tick
            stable_since = now
        elif now - stable_since >= stable_seconds:
            return True
    return False


def _config(state_dir: Path) -> AgentConfig:
    return AgentConfig(
        state_dir=state_dir,
        policy_version="plan-progress-live-v1",
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
        continuation=ContinuationConfig(enabled=True, ttl_seconds=900),
    )


async def _run() -> tuple[
    int,
    dict[str, object],
    RecordingWin32ProgressApi,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    int,
]:
    local_root = default_state_dir()
    local_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="plan-progress-smoke-",
        dir=local_root,
    ) as raw_dir:
        config = _config(Path(raw_dir).resolve())
        planner = FakePlanner(candidates=deque([PLAN_CANDIDATE]))
        final = FixedFinalPort()
        api = RecordingWin32ProgressApi()
        window = PassiveProgressWindow(api)
        lifecycle = RunProgressCoordinator(
            ProgressPoller(config.state_dir, window, interval_seconds=0.01),
            pump=api.pump,
        )

        class PlannerFactory:
            @staticmethod
            def from_environment(_model: str, **_kwargs: object) -> FakePlanner:
                return planner

        class FinalFactory:
            @staticmethod
            def from_environment(_model: str, **_kwargs: object) -> FixedFinalPort:
                return final

        original_load = agent_cli.load_agent_config
        original_progress = agent_cli._progress_lifecycle
        original_planner = planner_module.OpenAIPlanner
        original_final = final_module.OpenAIFinalResponseAdapter
        agent_cli.load_agent_config = lambda _path: config
        agent_cli._progress_lifecycle = lambda _config: lifecycle
        planner_module.OpenAIPlanner = PlannerFactory  # type: ignore[assignment]
        final_module.OpenAIFinalResponseAdapter = FinalFactory  # type: ignore[assignment]
        foreground_before = api.foreground()
        input_before = _last_input_tick()
        captured = io.StringIO()
        try:
            with redirect_stdout(captured):
                code = await agent_cli._run_planned_observation_async(
                    config.state_dir / "unused.toml",
                    TASK_SECRET,
                )
        finally:
            agent_cli.load_agent_config = original_load
            agent_cli._progress_lifecycle = original_progress
            planner_module.OpenAIPlanner = original_planner
            final_module.OpenAIFinalResponseAdapter = original_final
        foreground_after = api.foreground()
        input_after = _last_input_tick()
        raw_output = captured.getvalue()
        payload = json.loads(raw_output)
        run_id = payload["run_id"]
        assert isinstance(run_id, str)
        checkpoint = read_run_checkpoint(config.state_dir, run_id)
        metrics = checkpoint["metrics"]
        assert isinstance(metrics, dict)
        return (
            code,
            payload,
            api,
            foreground_before,
            foreground_after,
            input_before,
            input_after,
            len(planner.calls),
            len(final.calls),
            int(metrics["tool_calls"]),
            lifecycle.error_count,
        )


def main() -> int:
    if not _wait_for_idle():
        print("RESULT: INCONCLUSIVE (no three-second local-input quiet window)")
        return 2
    (
        code,
        payload,
        api,
        foreground_before,
        foreground_after,
        input_before,
        input_after,
        planner_calls,
        final_calls,
        checkpoint_tool_calls,
        lifecycle_errors,
    ) = asyncio.run(_run())
    drawn = "\n".join(line for frame in api.rendered for line in frame)
    problems: list[str] = []
    usage = payload.get("usage")
    run_id = payload.get("run_id")
    plan_id = payload.get("plan_id")
    if code != 0:
        problems.append(f"plan command returned {code}")
    if not isinstance(run_id, str) or not run_id:
        problems.append("plan result omitted the generated run identity")
    if not isinstance(plan_id, str) or not plan_id.startswith("plan_"):
        problems.append("plan result omitted the generated plan identity")
    if payload.get("observation_steps") != 1 or payload.get("text") != FINAL_TEXT:
        problems.append("plan result crossed the fixed one-observation boundary")
    if (
        not isinstance(usage, dict)
        or usage.get("planner_calls") != 1
        or usage.get("final_model_turns") != 1
        or usage.get("tool_calls") != 1
    ):
        problems.append("plan result usage drifted from the fixed boundary")
    if planner_calls != 1 or final_calls != 1 or checkpoint_tool_calls != 1:
        problems.append("plan lifecycle did not retain exactly one call per boundary")
    if len(api.created_handles) != 1 or api.created_handles != api.destroyed_handles:
        problems.append("native progress window lifecycle was not exactly one create/destroy")
    if (
        "In progress  1" not in drawn
        or not isinstance(run_id, str)
        or run_id not in drawn
    ):
        problems.append("validated bounded-plan run never reached the native window")
    if foreground_after != foreground_before:
        problems.append(
            f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
        )
    if lifecycle_errors:
        problems.append(f"progress lifecycle reported {lifecycle_errors} errors")
    serialized = json.dumps(payload, sort_keys=True)
    if TASK_SECRET in serialized or TASK_SECRET in drawn:
        problems.append("plan evidence exposed private task content")
    if any(key in payload for key in ("title", "windows", "screenshot")):
        problems.append("plan evidence exposed an unreviewed desktop-content field")
    if input_after != input_before:
        print(
            "RESULT: INCONCLUSIVE (local input occurred during the probe; "
            f"last-input tick {input_before} -> {input_after})"
        )
        return 2
    if problems:
        for problem in problems:
            print(f"  - {problem}")
        print("RESULT: FAIL")
        return 1

    print(
        f"RESULT: PASS (foreground unchanged at {foreground_before:#x}; one "
        "fixed provider-free plan drove one project-MCP list_windows "
        "observation through one native progress window; the tool-free final "
        "boundary completed; cleanup destroyed the window; no private task or "
        "desktop content was retained)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
