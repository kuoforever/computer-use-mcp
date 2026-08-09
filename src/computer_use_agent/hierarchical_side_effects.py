"""Pure H7 review gate for one bounded side-effect leaf sequence.

The contract is deliberately non-executable.  It accepts only an already
compiled, registry-bound ``TaskPlan`` shaped as fresh observation, one action,
fresh verification observation, and final response.  Runner remains the sole
owner of policy, approval, grounding, budgets, WAL, dispatch, and verification
state.
"""
from __future__ import annotations

from .planning import PlanStepAction, PlanStepStatus, TaskPlan
from .types import ToolEffect


H7_TOOL_STEP_COUNT = 3
H7_PLAN_STEP_COUNT = H7_TOOL_STEP_COUNT + 1


class HierarchicalSideEffectError(ValueError):
    """Fixed content-free rejection of an unsafe H7 plan shape."""


def validate_bounded_side_effect_plan(
    plan: TaskPlan, *, require_pending: bool = True
) -> None:
    """Require the one reviewed H7 action-and-verification sequence.

    Successful validation grants no authority.  In particular, the recorded
    ``requires_approval`` bit is checked only for registry consistency; the
    current Host policy and ordinary Runner boundary still decide whether an
    exact approval request is required, allowed, or denied.
    """

    if not isinstance(plan, TaskPlan) or not isinstance(require_pending, bool):
        raise HierarchicalSideEffectError("H7_PLAN_INVALID")
    if len(plan.steps) != H7_PLAN_STEP_COUNT or (
        require_pending
        and any(step.status is not PlanStepStatus.PENDING for step in plan.steps)
    ):
        raise HierarchicalSideEffectError("H7_PLAN_SHAPE_UNSAFE")

    before, action, after, final = plan.steps
    if (
        before.action is not PlanStepAction.TOOL
        or before.effect is not ToolEffect.OBSERVATION
        or before.requires_approval
        or action.action is not PlanStepAction.TOOL
        or action.effect is not ToolEffect.SIDE_EFFECT
        or not action.requires_approval
        or after.action is not PlanStepAction.TOOL
        or after.effect is not ToolEffect.OBSERVATION
        or after.requires_approval
        or final.action is not PlanStepAction.FINAL_RESPONSE
    ):
        raise HierarchicalSideEffectError("H7_PLAN_SHAPE_UNSAFE")


__all__ = [
    "H7_PLAN_STEP_COUNT",
    "H7_TOOL_STEP_COUNT",
    "HierarchicalSideEffectError",
    "validate_bounded_side_effect_plan",
]
