from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import computer_use_agent.hierarchical_compiler as compiler_module
from computer_use_agent.hierarchical_compiler import (
    TREE_COMPILER_VERSION,
    CompiledLeafBoundary,
    TreeCompileError,
    TreeTickDisposition,
    TreeTickReason,
    compile_next_leaf,
    transition_tree_leaf,
)
from computer_use_agent.hierarchical_control import (
    TaskTree,
    TreeNode,
    TreeNodeKind,
    project_linear_plan,
    reduce_tree_statuses,
)
from computer_use_agent.planning import PlanStepStatus, compile_task_plan
from computer_use_agent.tool_registry import reviewed_registry_digest


POLICY_DIGEST = "a" * 64
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "h3_next_leaf_traces.json"


def _tree() -> TaskTree:
    plan = compile_task_plan(
        json.dumps(
            {
                "version": 1,
                "steps": [
                    {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
                    {"action": "final_response"},
                ],
            }
        ),
        plan_id="plan_1",
        run_id="run_1",
        task="Inspect the active window",
        allowed_tools=("ui_snapshot",),
    )
    return project_linear_plan(
        plan,
        tree_id="tree_1",
        policy_digest=POLICY_DIGEST,
    )


def _tree_with_first_leaf(node: TreeNode) -> TaskTree:
    if node.kind is TreeNodeKind.FINAL_RESPONSE:
        child_ids = (node.node_id,)
        nodes = (
            TreeNode(
                node_id="root",
                kind=TreeNodeKind.GOAL,
                child_ids=child_ids,
            ),
            replace(node, parent_id="root"),
        )
    else:
        child_ids = (node.node_id, "final")
        nodes = (
            TreeNode(
                node_id="root",
                kind=TreeNodeKind.GOAL,
                child_ids=child_ids,
            ),
            replace(node, parent_id="root"),
            TreeNode(
                node_id="final",
                parent_id="root",
                kind=TreeNodeKind.FINAL_RESPONSE,
                step_id="step_final",
            ),
        )
    return TaskTree(
        tree_id="tree_kinds",
        run_id="run_1",
        task_digest="b" * 64,
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=nodes,
    )


def test_initial_tick_compiles_one_inert_digest_bound_boundary() -> None:
    tree = _tree()
    tick = compile_next_leaf(tree, sequence=7)

    assert tick.disposition is TreeTickDisposition.BOUNDARY
    assert tick.reason is TreeTickReason.BOUNDARY_READY
    assert tick.boundary is not None
    assert tick.boundary.compiler_version == TREE_COMPILER_VERSION
    assert tick.boundary.source_sequence == 7
    assert tick.boundary.source_tree_digest == tree.digest
    assert tick.boundary.node_id == "node_step_1"
    assert tick.boundary.node_kind is TreeNodeKind.TOOL_STEP
    assert tick.boundary.step_id == "step_1"
    assert len(tick.boundary.digest) == 64
    assert "arguments" not in tick.boundary.to_payload()
    assert "task" not in tick.boundary.to_payload()
    assert "tool" not in tick.boundary.to_payload()
    assert not hasattr(tick.boundary, "dispatch")
    assert not hasattr(tick.boundary, "authorized")


def test_active_leaf_waits_without_reemitting_a_boundary() -> None:
    tree = _tree()
    running = transition_tree_leaf(
        tree,
        "node_step_1",
        PlanStepStatus.IN_PROGRESS,
    )

    assert tree.status is PlanStepStatus.PENDING
    tick = compile_next_leaf(running, sequence=8)
    assert tick.disposition is TreeTickDisposition.WAITING
    assert tick.reason is TreeTickReason.ACTIVE_LEAF_WAIT
    assert tick.boundary is None
    assert tick.tree_status is PlanStepStatus.IN_PROGRESS


def test_ordered_transitions_reach_each_leaf_and_terminalize_once() -> None:
    tree = _tree()
    first_running = transition_tree_leaf(
        tree, "node_step_1", PlanStepStatus.IN_PROGRESS
    )
    first_done = transition_tree_leaf(
        first_running, "node_step_1", PlanStepStatus.COMPLETED
    )
    final_tick = compile_next_leaf(first_done, sequence=2)

    assert final_tick.boundary is not None
    assert final_tick.boundary.node_id == "node_step_2"
    assert final_tick.boundary.node_kind is TreeNodeKind.FINAL_RESPONSE

    final_running = transition_tree_leaf(
        first_done, "node_step_2", PlanStepStatus.IN_PROGRESS
    )
    completed = transition_tree_leaf(
        final_running, "node_step_2", PlanStepStatus.COMPLETED
    )
    terminal = compile_next_leaf(completed, sequence=4)
    assert terminal.disposition is TreeTickDisposition.TERMINAL
    assert terminal.reason is TreeTickReason.TREE_TERMINAL
    assert terminal.tree_status is PlanStepStatus.COMPLETED
    assert terminal.boundary is None


@pytest.mark.parametrize(
    "node",
    [
        TreeNode(
            node_id="tool",
            kind=TreeNodeKind.TOOL_STEP,
            step_id="step_tool",
        ),
        TreeNode(
            node_id="condition",
            kind=TreeNodeKind.CONDITION,
            condition_id="window_present",
        ),
        TreeNode(
            node_id="verify",
            kind=TreeNodeKind.VERIFY,
            verification_id="window_stable",
        ),
        TreeNode(
            node_id="subtree",
            kind=TreeNodeKind.SUBTREE,
            template_id="observation_ladder",
            template_version=1,
            template_digest="c" * 64,
        ),
        TreeNode(
            node_id="final",
            kind=TreeNodeKind.FINAL_RESPONSE,
            step_id="step_final",
        ),
    ],
)
def test_every_leaf_kind_compiles_identity_only(node: TreeNode) -> None:
    tick = compile_next_leaf(_tree_with_first_leaf(node), sequence=3)

    assert tick.boundary is not None
    assert tick.boundary.node_id == node.node_id
    assert tick.boundary.node_kind is node.kind
    assert tick.boundary.step_id == node.step_id
    assert tick.boundary.condition_id == node.condition_id
    assert tick.boundary.verification_id == node.verification_id
    assert tick.boundary.template_id == node.template_id
    assert tick.boundary.template_version == node.template_version
    assert tick.boundary.template_digest == node.template_digest


def test_choice_fails_closed_until_typed_fresh_facts_exist() -> None:
    tree = TaskTree(
        tree_id="tree_choice",
        run_id="run_1",
        task_digest="b" * 64,
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=(
            TreeNode(
                node_id="root",
                kind=TreeNodeKind.SEQUENCE,
                child_ids=("choice", "final"),
            ),
            TreeNode(
                node_id="choice",
                parent_id="root",
                kind=TreeNodeKind.CHOICE,
                child_ids=("condition",),
            ),
            TreeNode(
                node_id="condition",
                parent_id="choice",
                kind=TreeNodeKind.CONDITION,
                condition_id="window_present",
            ),
            TreeNode(
                node_id="final",
                parent_id="root",
                kind=TreeNodeKind.FINAL_RESPONSE,
                step_id="step_final",
            ),
        ),
    )

    tick = compile_next_leaf(tree, sequence=0)
    assert tick.disposition is TreeTickDisposition.BLOCKED
    assert tick.reason is TreeTickReason.CHOICE_FACTS_REQUIRED
    assert tick.boundary is None
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_OUT_OF_ORDER"):
        transition_tree_leaf(
            tree,
            "condition",
            PlanStepStatus.IN_PROGRESS,
        )


def test_multiple_active_leaves_fail_closed() -> None:
    tree = reduce_tree_statuses(
        _tree(),
        {
            "node_step_1": PlanStepStatus.IN_PROGRESS,
            "node_step_2": PlanStepStatus.IN_PROGRESS,
        },
    )

    with pytest.raises(TreeCompileError, match="TREE_COMPILE_MULTIPLE_ACTIVE_LEAVES"):
        compile_next_leaf(tree, sequence=0)


def test_out_of_order_or_terminal_active_leaf_fails_closed() -> None:
    out_of_order = reduce_tree_statuses(
        _tree(), {"node_step_2": PlanStepStatus.IN_PROGRESS}
    )
    with pytest.raises(TreeCompileError, match="TREE_COMPILE_ACTIVE_OUT_OF_ORDER"):
        compile_next_leaf(out_of_order, sequence=0)

    terminal_with_active = reduce_tree_statuses(
        _tree(),
        {
            "node_step_1": PlanStepStatus.FAILED,
            "node_step_2": PlanStepStatus.IN_PROGRESS,
        },
    )
    with pytest.raises(
        TreeCompileError, match="TREE_COMPILE_ACTIVE_IN_TERMINAL_TREE"
    ):
        compile_next_leaf(terminal_with_active, sequence=0)


def test_transition_cannot_skip_reenter_or_complete_a_pending_leaf() -> None:
    tree = _tree()
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_OUT_OF_ORDER"):
        transition_tree_leaf(tree, "node_step_2", PlanStepStatus.IN_PROGRESS)
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_INVALID"):
        transition_tree_leaf(tree, "node_step_1", PlanStepStatus.COMPLETED)

    running = transition_tree_leaf(
        tree, "node_step_1", PlanStepStatus.IN_PROGRESS
    )
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_INVALID"):
        transition_tree_leaf(running, "node_step_1", PlanStepStatus.IN_PROGRESS)
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_ACTIVE_LEAF"):
        transition_tree_leaf(running, "node_step_2", PlanStepStatus.CANCELLED)


@pytest.mark.parametrize(
    "terminal",
    [
        PlanStepStatus.FAILED,
        PlanStepStatus.BLOCKED,
        PlanStepStatus.CANCELLED,
    ],
)
def test_known_terminal_leaf_results_stop_the_complete_tree(
    terminal: PlanStepStatus,
) -> None:
    running = transition_tree_leaf(
        _tree(), "node_step_1", PlanStepStatus.IN_PROGRESS
    )
    stopped = transition_tree_leaf(running, "node_step_1", terminal)

    tick = compile_next_leaf(stopped, sequence=2)
    assert tick.disposition is TreeTickDisposition.TERMINAL
    assert tick.tree_status is terminal
    assert tick.boundary is None
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_TERMINAL"):
        transition_tree_leaf(stopped, "node_step_2", PlanStepStatus.IN_PROGRESS)


@pytest.mark.parametrize(
    "terminal",
    [PlanStepStatus.BLOCKED, PlanStepStatus.CANCELLED],
)
def test_exact_next_pending_leaf_may_fail_closed_without_starting(
    terminal: PlanStepStatus,
) -> None:
    stopped = transition_tree_leaf(_tree(), "node_step_1", terminal)
    assert stopped.status is terminal


def test_boundary_digest_binds_sequence_and_source_tree_status() -> None:
    tree = _tree()
    first = compile_next_leaf(tree, sequence=1).boundary
    second = compile_next_leaf(tree, sequence=2).boundary
    assert first is not None and second is not None
    assert first.digest != second.digest

    first_done = reduce_tree_statuses(
        tree, {"node_step_1": PlanStepStatus.COMPLETED}
    )
    final = compile_next_leaf(first_done, sequence=2).boundary
    assert final is not None
    assert final.source_tree_digest != second.source_tree_digest
    assert final.digest != second.digest


def test_registry_drift_and_invalid_sequence_fail_before_compilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = _tree()
    with pytest.raises(TreeCompileError, match="TREE_COMPILE_INVALID"):
        compile_next_leaf(tree, sequence=True)  # type: ignore[arg-type]

    monkeypatch.setattr(
        compiler_module,
        "reviewed_registry_digest",
        lambda: "0" * 64,
    )
    with pytest.raises(TreeCompileError, match="TREE_COMPILE_REGISTRY_MISMATCH"):
        compile_next_leaf(tree, sequence=0)
    with pytest.raises(TreeCompileError, match="TREE_COMPILE_REGISTRY_MISMATCH"):
        transition_tree_leaf(tree, "node_step_1", PlanStepStatus.IN_PROGRESS)


def test_public_boundary_constructor_rejects_conflicting_bindings() -> None:
    with pytest.raises(TreeCompileError, match="TREE_COMPILE_INVALID"):
        CompiledLeafBoundary(
            source_sequence=0,
            source_tree_digest="a" * 64,
            tree_id="tree_1",
            run_id="run_1",
            node_id="condition",
            node_kind=TreeNodeKind.CONDITION,
            step_id="step_1",
            condition_id="window_present",
        )


def test_frozen_linear_trace_is_exact_and_deterministic() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["fixture_version"] == 1
    tree = _tree()

    for case in fixture["cases"]:
        statuses = {
            node_id: PlanStepStatus(status)
            for node_id, status in case["leaf_statuses"].items()
        }
        projected = reduce_tree_statuses(tree, statuses)
        tick = compile_next_leaf(projected, sequence=case["sequence"])
        actual = tick.to_payload()
        actual["boundary_digest"] = (
            None if tick.boundary is None else tick.boundary.digest
        )

        assert actual == case["expected"], case["name"]
