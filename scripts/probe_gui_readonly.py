"""Explicit development probe: one synthetic window, real Host/stdio MCP, no model."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4

from computer_use_agent.config import (
    AgentConfig, MCPLaunchConfig, PolicyConfig, ProviderConfig, default_state_dir,
)
from computer_use_agent.desktop_mcp import MCPBridgeError, StdioDesktopMCP
from computer_use_agent.fakes import FakeApprovalPort, FakeModelProvider
from computer_use_agent.gui_host_source import collect_host_gui_observation
from computer_use_agent.gui_observation import validate_gui_task
from computer_use_agent.runner import AgentRunner, RunnerPorts, RunFailure
from computer_use_agent.tool_registry import ToolRegistryMismatchError
from computer_use_agent.trace import read_run_record
from computer_use_mcp.gui_metadata import GuiMetadataError

TITLE = "GDA read-only observation fixture"
TARGET = "Observation target"


def task_for(scope):
    return validate_gui_task(dict(
        version=1, request_id="single-window-readonly-v1", target_scope=scope,
        target=dict(name=TARGET, role="button"),
    ))


def config_for():
    return AgentConfig(
        state_dir=default_state_dir() / "gui-readonly-probe",
        policy_version="gui-readonly-probe-v1",
        provider=ProviderConfig(name="openai", model="never-called"),
        mcp=MCPLaunchConfig(
            executable=Path(sys.executable).resolve(),
            args=(str(Path(__file__).resolve()), "--serve-readonly"),
            cwd=Path(__file__).resolve().parents[1], environment={},
        ),
        policy=PolicyConfig(max_model_turns=0, max_tool_calls=3, max_side_effects=0),
    )


def input_tick():
    """Test attribution only: changed input invalidates a measured attempt."""
    import ctypes
    from ctypes import wintypes

    class InputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = InputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
        raise RuntimeError("INPUT_OBSERVATION_UNAVAILABLE")
    return int(info.dwTime)


async def probe(scope, *, tick=input_tick, runner=None):
    task = task_for(scope)
    if runner is None:
        config = config_for()
        runner = AgentRunner(config, RunnerPorts(
            FakeModelProvider(), StdioDesktopMCP(config.mcp), FakeApprovalPort(),
        ))
    run_id = "gui-readonly-" + uuid4().hex
    before = tick()
    outcome, code, control_count = "FAIL", "OBSERVATION_REJECTED", 0
    try:
        result = await collect_host_gui_observation(runner, task, run_id=run_id, max_seconds=5)
        payload = result.bundle.to_dict()
        controls = payload["host_facts"]["control_states"]
        window_lines = payload["results"]["windows"]["text"].splitlines()
        snapshot = payload["results"]["snapshot"]["text"]
        if (
            len(controls) != 1
            or not any(line.startswith("* " + scope + " | ") and
                       line.endswith(' | "' + TITLE + '"') for line in window_lines)
            or f'button "{TARGET}"' not in snapshot
            or payload["execution_authorized"] is not False
        ):
            code = "FIXTURE_MISMATCH"
        else:
            outcome, code, control_count = "PASS", "OBSERVATION_COLLECTED", 1
        # Raw observations and image bytes stay in memory; only counts escape.
        del payload, result
    except (GuiMetadataError, MCPBridgeError, RunFailure, ToolRegistryMismatchError):
        pass  # Do not serialize exception text or arbitrary native/UI data.
    after = tick()
    if before != after:
        outcome, code, control_count = "INVALID", "INPUT_CHANGED", 0
    record = read_run_record(runner.config.state_dir, run_id)["state"]
    budgets = record["budgets"]
    return dict(
        version=1, evidence="real_host_stdio_mcp_native_window", run_id=run_id,
        outcome=outcome, code=code, input_unchanged=(before == after),
        phase=record["phase"], observation_epoch=record["observation_epoch"],
        tool_calls=budgets["tool_calls_used"], model_turns=budgets["model_turns_used"],
        side_effects=budgets["side_effects_used"], control_count=control_count,
        execution_authorized=False, raw_observations_exported=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--live-readonly", action="store_true")
    modes.add_argument("--serve-readonly", action="store_true")
    parser.add_argument("--scope")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("Windows interactive session required")
    if args.serve_readonly:
        if args.scope is not None:
            parser.error("server does not accept scope")
        from computer_use_mcp.server import build_server

        build_server(gui_observation_enabled=True).run()
        return 0
    if args.scope is None:
        parser.error("--scope is required for --live-readonly")
    try:
        task_for(args.scope)  # Reject bad input before any child or OS read.
        receipt = asyncio.run(probe(args.scope))
    except Exception:
        print(json.dumps(dict(version=1, outcome="ERROR", code="PROBE_UNAVAILABLE")))
        return 1
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
