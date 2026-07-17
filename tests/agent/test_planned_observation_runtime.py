from __future__ import annotations

import asyncio
import inspect
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from computer_use_agent import planned_observation_runtime as runtime_module
from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.executor_final import (
    FinalResponseRequest,
    FinalResponseResult,
)
from computer_use_agent.fakes import (
    FakeApprovalPort,
    FakeDesktopMCP,
    FakeModelProvider,
    FakePlanner,
)
from computer_use_agent.planned_observation_runtime import (
    OBSERVATION_PLAN_TOOLS,
    PlannedObservationRuntimeError,
    run_planned_observation,
)
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.types import (
    DispatchCertainty,
    ModelUsage,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


TASK = "Inspect the visible desktop"


def test_composition_has_no_direct_provider_or_desktop_dispatch_site() -> None:
    source = inspect.getsource(runtime_module)

    assert ".call_tool(" not in source
    assert "create_turn(" not in source
    assert "create_candidate(" not in source
    assert "create_final_response(" not in source
    assert "_execute_requested_call_boundary(" not in source


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_model_turns: int = 4,
    max_tool_calls: int = 4,
    continuation_enabled: bool = True,
) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "planned-observation",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            max_model_turns=max_model_turns,
            max_tool_calls=max_tool_calls,
        ),
        continuation=ContinuationConfig(enabled=continuation_enabled),
    )


@dataclass
class EchoDesktop(FakeDesktopMCP):
    async def call_tool(self, call: ToolCall) -> ToolResult:
        self.tool_calls.append(call)
        return ToolResult(
            identity=call.identity,
            tool_name=call.name,
            status=ToolResultStatus.SUCCESS,
            dispatch=DispatchCertainty.DISPATCHED,
            sanitized_text=f"observed:{call.name}",
        )


@dataclass
class FakeFinalPort:
    name: str = "fake-final"
    calls: list[FinalResponseRequest] = field(default_factory=list)

    async def create_final_response(
        self, request: FinalResponseRequest
    ) -> FinalResponseResult:
        self.calls.append(request)
        return FinalResponseResult(
            run_id=request.run_id,
            turn_id=request.turn_id,
            provider_response_id="response_final_1",
            text="The desktop was inspected.",
            usage=ModelUsage(13, 5),
        )


def test_bounded_plan_runs_observations_through_runner_then_finalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    planner = FakePlanner(
        candidates=deque(
            [
                '{"version":1,"steps":['
                '{"action":"tool","tool":"list_windows","arguments":{}},'
                '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
                '{"action":"final_response"}]}'
            ]
        )
    )
    ordinary_provider = FakeModelProvider()
    desktop = EchoDesktop()
    approvals = FakeApprovalPort()
    final = FakeFinalPort()
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=ordinary_provider,
            desktop=desktop,
            approvals=approvals,
        ),
    )

    outcome = asyncio.run(
        run_planned_observation(
            runner,
            planner,
            final,
            task=TASK,
            run_id="run_1",
            plan_id="plan_1",
        )
    )

    assert outcome.plan_id == "plan_1"
    assert outcome.observation_steps == 2
    assert outcome.final.text == "The desktop was inspected."
    assert outcome.final.state.budgets.model_turns_used == 1
    assert outcome.final.state.budgets.tool_calls_used == 2
    assert tuple(tool.name for tool in planner.calls[0].tools) == OBSERVATION_PLAN_TOOLS
    assert [call.name for call in desktop.tool_calls] == [
        "list_windows",
        "ui_snapshot",
    ]
    assert len(final.calls) == 1
    assert ordinary_provider.calls == []
    assert approvals.requests == []
    assert desktop.close_calls == 1


def test_five_observation_candidate_stops_before_desktop_or_final(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    planner = FakePlanner(
        candidates=deque(
            [
                '{"version":1,"steps":['
                + ",".join(
                    '{"action":"tool","tool":"list_windows","arguments":{}}'
                    for _ in range(5)
                )
                + ',{"action":"final_response"}]}'
            ]
        )
    )
    desktop = EchoDesktop()
    final = FakeFinalPort()
    runner = AgentRunner(
        config,
        RunnerPorts(
            provider=FakeModelProvider(),
            desktop=desktop,
            approvals=FakeApprovalPort(),
        ),
    )

    with pytest.raises(
        PlannedObservationRuntimeError,
        match="^PLANNED_OBSERVATION_PLAN_UNSAFE$",
    ):
        asyncio.run(
            run_planned_observation(
                runner,
                planner,
                final,
                task=TASK,
                run_id="run_1",
                plan_id="plan_1",
            )
        )

    assert len(planner.calls) == 1
    assert desktop.discovery_calls == 0
    assert desktop.tool_calls == []
    assert final.calls == []
    assert not config.state_dir.exists()


def test_missing_wal_or_final_model_budget_stops_before_planner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for config, code in (
        (
            _config(tmp_path / "wal", monkeypatch, continuation_enabled=False),
            "PLANNED_OBSERVATION_WAL_REQUIRED",
        ),
        (
            _config(tmp_path / "budget", monkeypatch, max_model_turns=0),
            "PLANNED_OBSERVATION_MODEL_BUDGET_INVALID",
        ),
    ):
        planner = FakePlanner(candidates=deque())
        runner = AgentRunner(
            config,
            RunnerPorts(
                provider=FakeModelProvider(),
                desktop=EchoDesktop(),
                approvals=FakeApprovalPort(),
            ),
        )
        with pytest.raises(PlannedObservationRuntimeError, match=f"^{code}$"):
            asyncio.run(
                run_planned_observation(
                    runner,
                    planner,
                    FakeFinalPort(),
                    task=TASK,
                    run_id="run_1",
                    plan_id="plan_1",
                )
            )
        assert planner.calls == []
