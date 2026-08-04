"""Live smoke for read-only recovery progress lifecycle wiring."""

from __future__ import annotations

import asyncio
import ctypes
import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from ctypes import wintypes
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
from computer_use_agent.continuation import (  # noqa: E402
    RuntimeContinuationRecorder,
    read_continuation,
)
from computer_use_agent.progress_lifecycle import RunProgressCoordinator  # noqa: E402
from computer_use_agent.progress_poller import ProgressPoller  # noqa: E402
from computer_use_agent.progress_window import PassiveProgressWindow  # noqa: E402
from computer_use_agent.progress_window_win32 import (  # noqa: E402
    Win32ProgressWindowApi,
)
from computer_use_agent.tool_registry import (  # noqa: E402
    REVIEWED_TOOLS,
    reviewed_registry_digest,
)
from computer_use_agent.trace import RunPhase, RunRecorder  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    CallIdentity,
    ModelTurn,
    RunBudget,
    RunState,
    ToolCall,
)

RUN_ID = "recovery_progress_live"
TASK_SECRET = "RECOVERY_PROGRESS_TASK_MUST_NOT_APPEAR"


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
        policy_version="recovery-progress-live-v1",
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
            max_model_turns=2,
            max_tool_calls=2,
            max_side_effects=0,
        ),
        continuation=ContinuationConfig(enabled=True, ttl_seconds=900),
    )


def _prepare_recovery(config: AgentConfig) -> None:
    state = RunState(
        RUN_ID,
        TASK_SECRET,
        config.policy_version,
        0,
        RunBudget(
            config.policy.max_model_turns,
            config.policy.max_tool_calls,
            config.policy.max_side_effects,
            max_input_tokens=config.policy.max_input_tokens,
            model_turns_used=1,
        ),
    )
    call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "list_windows",
        {},
    )
    continuation = RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=state,
        provider_name=config.provider.name,
        provider_model=config.provider.model,
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        ttl_seconds=config.continuation.ttl_seconds,
        mcp_generation=1,
    )
    continuation.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    continuation.dispatch_provider(state, checkpoint_sequence=2)
    continuation.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": TASK_SECRET,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    recorder = RunRecorder(config.state_dir, state.run_id)
    recorder.start(state)
    recorder.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    recorder.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)


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
]:
    local_root = default_state_dir()
    local_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="recovery-progress-smoke-",
        dir=local_root,
    ) as raw_dir:
        config = _config(Path(raw_dir).resolve())
        _prepare_recovery(config)

        api = RecordingWin32ProgressApi()
        window = PassiveProgressWindow(api)
        lifecycle = RunProgressCoordinator(
            ProgressPoller(config.state_dir, window, interval_seconds=0.01),
            pump=api.pump,
        )
        original_load = agent_cli.load_agent_config
        original_progress = agent_cli._progress_lifecycle
        agent_cli.load_agent_config = lambda _path: config
        agent_cli._progress_lifecycle = lambda _config: lifecycle
        foreground_before = api.foreground()
        input_before = _last_input_tick()
        captured = io.StringIO()
        try:
            with redirect_stdout(captured):
                code = await agent_cli._recover_live_async(
                    config.state_dir / "unused.toml",
                    RUN_ID,
                    TASK_SECRET,
                    max_steps=1,
                )
        finally:
            agent_cli.load_agent_config = original_load
            agent_cli._progress_lifecycle = original_progress
        foreground_after = api.foreground()
        input_after = _last_input_tick()
        payload = json.loads(captured.getvalue())
        envelope = read_continuation(config.state_dir, RUN_ID)
        ledger = envelope.payload["ledger"]
        assert isinstance(ledger, list)
        recovered_tool_results = sum(
            1
            for event in ledger
            if isinstance(event, dict)
            and event.get("kind") == "tool_result"
            and isinstance(event.get("data"), dict)
            and event["data"].get("tool_name") == "list_windows"
        )
        return (
            code,
            payload,
            api,
            foreground_before,
            foreground_after,
            input_before,
            input_after,
            recovered_tool_results,
            lifecycle.error_count,
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
        recovered_tool_results,
        lifecycle_errors,
    ) = asyncio.run(_run())
    drawn = "\n".join(line for frame in api.rendered for line in frame)
    problems: list[str] = []
    if code != 0:
        problems.append(f"recovery command returned {code}")
    if payload != {
        "action": "dispatch_observation",
        "checkpoint_sequence": 5,
        "next_step": "provider_continue",
        "reason": "PROVIDER_COMPLETED_OBSERVATION_PENDING",
        "run_id": RUN_ID,
        "tool_code": None,
        "tool_status": "success",
    }:
        problems.append("recovery output crossed the expected one-step boundary")
    if recovered_tool_results != 1:
        problems.append("recovery did not durably retain exactly one list_windows result")
    if len(api.created_handles) != 1 or api.created_handles != api.destroyed_handles:
        problems.append("native progress window lifecycle was not exactly one create/destroy")
    if "In progress  1" not in drawn or RUN_ID not in drawn:
        problems.append("validated recovering run state never reached the native window")
    if foreground_after != foreground_before:
        problems.append(
            f"foreground changed {foreground_before:#x} -> {foreground_after:#x}"
        )
    if lifecycle_errors:
        problems.append(f"progress lifecycle reported {lifecycle_errors} errors")
    forbidden_output_keys = {"text", "title", "windows", "screenshot", "task"}
    if forbidden_output_keys.intersection(payload) or TASK_SECRET in drawn:
        problems.append("recovery evidence exposed an unreviewed content field")
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
        "persisted read-only recovery boundary reached one native progress "
        "window; the project MCP made one list_windows observation; cleanup "
        "destroyed the window; no task, title, window, or screenshot field "
        "was retained)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
