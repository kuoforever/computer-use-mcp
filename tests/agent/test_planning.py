from __future__ import annotations

import json

import pytest

from computer_use_agent.planning import (
    MAX_PLAN_CANDIDATE_BYTES,
    PlanStep,
    PlanStepAction,
    PlanStepStatus,
    PlanValidationError,
    TaskPlan,
    TaskPlanStatus,
    compile_task_plan,
    transition_plan_step,
)
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.types import ToolEffect, to_json_value


def _candidate(*steps: dict[str, object], version: object = 1) -> str:
    return json.dumps({"version": version, "steps": list(steps)})


def _compile(candidate: str, *, allowed_tools: tuple[str, ...] = ("ui_snapshot",)) -> TaskPlan:
    return compile_task_plan(
        candidate,
        plan_id="plan_1",
        run_id="run_1",
        task="Inspect the active window",
        allowed_tools=allowed_tools,
    )


def test_compiler_creates_a_digest_bound_non_executable_ordered_plan() -> None:
    plan = _compile(
        _candidate(
            {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
            {"action": "final_response"},
        )
    )

    assert plan.status is TaskPlanStatus.PENDING
    assert plan.registry_digest == reviewed_registry_digest()
    assert len(plan.task_digest) == 64
    assert "Inspect the active window" not in repr(plan)
    assert [step.step_id for step in plan.steps] == ["step_1", "step_2"]
    assert plan.steps[0].effect is ToolEffect.OBSERVATION
    assert plan.steps[0].requires_approval is False
    assert plan.steps[1].action is PlanStepAction.FINAL_RESPONSE
    assert len(plan.digest) == 64


def test_final_response_step_default_arguments_are_independent_and_immutable() -> None:
    first = PlanStep(step_id="step_1", action=PlanStepAction.FINAL_RESPONSE)
    second = PlanStep(step_id="step_2", action=PlanStepAction.FINAL_RESPONSE)

    assert first.arguments == second.arguments == {}
    assert first.arguments is not second.arguments
    with pytest.raises(TypeError):
        first.arguments["unexpected"] = True  # type: ignore[index]


def test_action_plan_records_reviewed_approval_metadata_but_no_authorization() -> None:
    plan = _compile(
        _candidate(
            {"action": "tool", "tool": "click", "arguments": {"ref": "ref_1"}},
            {"action": "final_response"},
        ),
        allowed_tools=("click",),
    )

    step = plan.steps[0]
    assert step.status is PlanStepStatus.PENDING
    assert step.effect is ToolEffect.SIDE_EFFECT
    assert step.requires_approval is True
    assert to_json_value(step.arguments) == {"ref": "ref_1"}
    assert not hasattr(step, "authorized")
    assert not hasattr(step, "dispatch")


def test_compiler_rejects_sensitive_plan_arguments_without_echoing_them() -> None:
    secret = "TOP-SECRET-TEXT"
    candidate = _candidate(
        {"action": "tool", "tool": "type", "arguments": {"text": secret}},
        {"action": "final_response"},
    )

    with pytest.raises(PlanValidationError) as captured:
        _compile(candidate, allowed_tools=("type",))

    assert secret not in str(captured.value)
    assert "sensitive" in str(captured.value)


@pytest.mark.parametrize(
    "candidate",
    [
        "not-json",
        "[]",
        json.dumps({"version": 1, "steps": [], "extra": True}),
        _candidate({"action": "final_response"}, version=True),
        _candidate({"action": "unknown"}),
        _candidate({"action": "final_response", "tool": "ui_snapshot"}),
        _candidate(
            {"action": "final_response"},
            {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
        ),
        _candidate(
            {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
        ),
    ],
)
def test_candidate_shape_and_final_step_rules_fail_closed(candidate: str) -> None:
    with pytest.raises(PlanValidationError):
        _compile(candidate)


@pytest.mark.parametrize(
    ("step", "allowed_tools"),
    [
        ({"action": "tool", "tool": "shell", "arguments": {}}, ("ui_snapshot",)),
        ({"action": "tool", "tool": "click", "arguments": {"ref": "ref_1"}}, ("ui_snapshot",)),
        ({"action": "tool", "tool": "find", "arguments": {}}, ("find",)),
        (
            {
                "action": "tool",
                "tool": "click",
                "arguments": {"ref": "ref_1", "x": 1, "y": 2},
            },
            ("click",),
        ),
    ],
)
def test_unreviewed_unscoped_or_invalid_tool_steps_fail_closed(
    step: dict[str, object], allowed_tools: tuple[str, ...]
) -> None:
    with pytest.raises(PlanValidationError):
        _compile(
            _candidate(step, {"action": "final_response"}),
            allowed_tools=allowed_tools,
        )


def test_allowed_tool_scope_must_be_explicit_reviewed_and_unique() -> None:
    candidate = _candidate({"action": "final_response"})

    for allowed in ("ui_snapshot", ("shell",), ("ui_snapshot", "ui_snapshot")):
        with pytest.raises(PlanValidationError):
            compile_task_plan(
                candidate,
                plan_id="plan_1",
                run_id="run_1",
                task="Inspect",
                allowed_tools=allowed,  # type: ignore[arg-type]
            )


def test_candidate_byte_and_step_limits_are_enforced_before_execution() -> None:
    oversized = " " * (MAX_PLAN_CANDIDATE_BYTES + 1)
    too_many = _candidate(
        *(
            [
                {"action": "tool", "tool": "ui_snapshot", "arguments": {}}
                for _ in range(16)
            ]
            + [{"action": "final_response"}]
        )
    )

    with pytest.raises(PlanValidationError, match="byte limit"):
        _compile(oversized)
    with pytest.raises(PlanValidationError, match="step count"):
        _compile(too_many)


def test_plan_arguments_are_deeply_immutable_and_digest_is_stable() -> None:
    plan = _compile(
        _candidate(
            {"action": "tool", "tool": "find", "arguments": {"query": "Save"}},
            {"action": "final_response"},
        ),
        allowed_tools=("find",),
    )

    assert plan.digest == plan.digest
    with pytest.raises(TypeError):
        plan.steps[0].arguments["query"] = "Delete"  # type: ignore[index]


def test_step_transitions_are_ordered_pure_and_digest_bound() -> None:
    original = _compile(
        _candidate(
            {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
            {"action": "final_response"},
        )
    )
    running = transition_plan_step(original, "step_1", PlanStepStatus.IN_PROGRESS)
    observed = transition_plan_step(running, "step_1", PlanStepStatus.COMPLETED)
    finalizing = transition_plan_step(observed, "step_2", PlanStepStatus.IN_PROGRESS)
    completed = transition_plan_step(finalizing, "step_2", PlanStepStatus.COMPLETED)

    assert original.status is TaskPlanStatus.PENDING
    assert original.steps[0].status is PlanStepStatus.PENDING
    assert running.status is TaskPlanStatus.IN_PROGRESS
    assert completed.status is TaskPlanStatus.COMPLETED
    assert len({original.digest, running.digest, observed.digest, finalizing.digest, completed.digest}) == 5


def test_illegal_skip_completion_and_terminal_reentry_are_rejected() -> None:
    plan = _compile(
        _candidate(
            {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
            {"action": "final_response"},
        )
    )

    with pytest.raises(PlanValidationError, match="next ordered"):
        transition_plan_step(plan, "step_2", PlanStepStatus.IN_PROGRESS)
    with pytest.raises(PlanValidationError, match="illegal"):
        transition_plan_step(plan, "step_1", PlanStepStatus.COMPLETED)

    running = transition_plan_step(plan, "step_1", PlanStepStatus.IN_PROGRESS)
    failed = transition_plan_step(running, "step_1", PlanStepStatus.FAILED)
    assert failed.status is TaskPlanStatus.FAILED
    with pytest.raises(PlanValidationError, match="terminal"):
        transition_plan_step(failed, "step_2", PlanStepStatus.IN_PROGRESS)


def test_direct_contract_construction_rejects_registry_metadata_spoofing() -> None:
    with pytest.raises(PlanValidationError, match="metadata"):
        PlanStep(
            step_id="step_1",
            action=PlanStepAction.TOOL,
            tool_name="click",
            arguments={"ref": "ref_1"},
            effect=ToolEffect.OBSERVATION,
            requires_approval=False,
        )

    with pytest.raises(PlanValidationError, match="arguments"):
        PlanStep(
            step_id="step_1",
            action=PlanStepAction.TOOL,
            tool_name="click",
            arguments={"ref": "ref_1", "x": 1, "y": 2},
            effect=ToolEffect.SIDE_EFFECT,
            requires_approval=True,
        )

    with pytest.raises(PlanValidationError, match="sensitive"):
        PlanStep(
            step_id="step_1",
            action=PlanStepAction.TOOL,
            tool_name="type",
            arguments={"text": "never-store-this"},
            effect=ToolEffect.SIDE_EFFECT,
            requires_approval=True,
        )

    with pytest.raises(PlanValidationError, match="ordered prefix"):
        TaskPlan(
            plan_id="plan_1",
            run_id="run_1",
            task_digest="0" * 64,
            registry_digest=reviewed_registry_digest(),
            steps=(
                PlanStep(
                    step_id="step_1",
                    action=PlanStepAction.TOOL,
                    tool_name="ui_snapshot",
                    arguments={},
                    effect=ToolEffect.OBSERVATION,
                    status=PlanStepStatus.PENDING,
                ),
                PlanStep(
                    step_id="step_2",
                    action=PlanStepAction.FINAL_RESPONSE,
                    status=PlanStepStatus.COMPLETED,
                ),
            ),
        )
