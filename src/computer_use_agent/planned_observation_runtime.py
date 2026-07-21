"""Bounded composition of one Planner and the observation-only Executor."""
from __future__ import annotations

from dataclasses import dataclass

from .executor_final import FinalResponsePort
from .executor_runtime import (
    RuntimeFinalResponseOutcome,
    open_runtime_executor_session,
)
from .planner import (
    PlannerPort,
    build_planner_request,
    request_task_plan,
)
from .planning import PlanStepAction
from .runner import AgentRunner
from .types import ToolEffect


OBSERVATION_PLAN_TOOLS = (
    "ui_snapshot",
    "find",
    "list_windows",
    "screenshot",
    "capture_region",
    "ocr",
)
MAX_PLANNED_OBSERVATIONS = 4


class PlannedObservationRuntimeError(RuntimeError):
    """Fixed failure from the bounded plan composition boundary."""


@dataclass(frozen=True, repr=False)
class PlannedObservationOutcome:
    """Terminal result plus bounded non-sensitive plan metadata."""

    plan_id: str
    observation_steps: int
    final: RuntimeFinalResponseOutcome

    def __repr__(self) -> str:
        return (
            "PlannedObservationOutcome("
            f"run_id={self.final.state.run_id!r}, plan_id={self.plan_id!r}, "
            f"observation_steps={self.observation_steps}, "
            f"text_length={len(self.final.text)})"
        )


async def run_planned_observation(
    runner: AgentRunner,
    planner: PlannerPort,
    final_port: FinalResponsePort,
    *,
    task: str,
    run_id: str,
    plan_id: str,
) -> PlannedObservationOutcome:
    """Run one host-scoped read-only plan without adding execution authority."""

    if (
        not isinstance(runner, AgentRunner)
        or not isinstance(planner, PlannerPort)
        or not isinstance(final_port, FinalResponsePort)
        or not isinstance(task, str)
        or not task
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(plan_id, str)
        or not plan_id
    ):
        raise PlannedObservationRuntimeError("PLANNED_OBSERVATION_INPUT_INVALID")
    if not runner.config.continuation.enabled:
        raise PlannedObservationRuntimeError("PLANNED_OBSERVATION_WAL_REQUIRED")
    if runner.config.policy.max_model_turns < 1:
        raise PlannedObservationRuntimeError(
            "PLANNED_OBSERVATION_MODEL_BUDGET_INVALID"
        )
    request = build_planner_request(
        run_id=run_id,
        plan_id=plan_id,
        task=task,
        allowed_tools=OBSERVATION_PLAN_TOOLS,
    )
    plan = await request_task_plan(planner, request)
    observations = tuple(
        step for step in plan.steps if step.action is PlanStepAction.TOOL
    )
    if (
        not 1 <= len(observations) <= MAX_PLANNED_OBSERVATIONS
        or len(plan.steps) != len(observations) + 1
        or any(step.effect is not ToolEffect.OBSERVATION for step in observations)
    ):
        raise PlannedObservationRuntimeError("PLANNED_OBSERVATION_PLAN_UNSAFE")
    if len(observations) > runner.config.policy.max_tool_calls:
        raise PlannedObservationRuntimeError(
            "PLANNED_OBSERVATION_TOOL_BUDGET_INVALID"
        )

    session = await open_runtime_executor_session(runner, task=task, plan=plan)
    try:
        for _ in observations:
            await session.execute_next_observation()
        final = await session.execute_final_response(final_port)
    except BaseException:
        if not session.closed:
            await session.preserve_and_close()
        raise
    return PlannedObservationOutcome(
        plan_id=plan.plan_id,
        observation_steps=len(observations),
        final=final,
    )


__all__ = [
    "MAX_PLANNED_OBSERVATIONS",
    "OBSERVATION_PLAN_TOOLS",
    "PlannedObservationOutcome",
    "PlannedObservationRuntimeError",
    "run_planned_observation",
]
