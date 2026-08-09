from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from computer_use_agent.hierarchical_control import (
    MAX_TREE_CHILDREN,
    TREE_CONTRACT_VERSION,
    TaskTree,
    TreeBudget,
    TreeLimits,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
    project_linear_plan,
    reduce_child_statuses,
    reduce_tree_statuses,
)
from computer_use_agent.planning import (
    PlanStepStatus,
    TaskPlan,
    compile_task_plan,
    transition_plan_step,
)


POLICY_DIGEST = "a" * 64


def _linear_plan() -> TaskPlan:
    return compile_task_plan(
        '{"version":1,"steps":['
        '{"action":"tool","tool":"ui_snapshot","arguments":{}},'
        '{"action":"final_response"}'
        "]}",
        plan_id="plan_1",
        run_id="run_1",
        task="Inspect the active window",
        allowed_tools=("ui_snapshot",),
    )


def _tree() -> TaskTree:
    return project_linear_plan(
        _linear_plan(), tree_id="tree_1", policy_digest=POLICY_DIGEST
    )


def test_linear_plan_projects_to_an_inert_digest_bound_sequence() -> None:
    plan = _linear_plan()
    tree = project_linear_plan(
        plan,
        tree_id="tree_1",
        policy_digest=POLICY_DIGEST,
    )

    assert tree.contract_version == TREE_CONTRACT_VERSION
    assert tree.status is PlanStepStatus.PENDING
    assert tree.root_id == "root"
    assert [node.node_id for node in tree.nodes] == [
        "node_step_1",
        "node_step_2",
        "root",
    ]
    assert next(node for node in tree.nodes if node.node_id == "root").child_ids == (
        "node_step_1",
        "node_step_2",
    )
    assert tree.aggregate_budget == TreeBudget(tool_calls=1)
    assert tree.task_digest == plan.task_digest
    assert tree.registry_digest == plan.registry_digest
    assert len(tree.digest) == 64
    assert tree.digest == "ea5961dfbc75e9e2a64e4ef84f16c5386aa55cc48ec129d9550002d616459898"
    assert "parallel_batches" not in tree.to_payload()
    assert "Inspect the active window" not in repr(tree)
    assert not hasattr(tree, "dispatch")
    assert not hasattr(tree, "authorized")


def test_digest_is_canonical_but_child_order_remains_semantic() -> None:
    tree = _tree()
    reordered_storage = replace(tree, nodes=tuple(reversed(tree.nodes)))
    assert reordered_storage.nodes == tree.nodes
    assert reordered_storage.digest == tree.digest

    root = next(node for node in tree.nodes if node.node_id == "root")
    reordered_root = replace(root, child_ids=tuple(reversed(root.child_ids)))
    reordered_children = replace(
        tree,
        nodes=tuple(reordered_root if node.node_id == "root" else node for node in tree.nodes),
    )
    assert reordered_children.digest != tree.digest


def test_tree_digest_binds_limits_budgets_policy_and_status() -> None:
    tree = _tree()
    variants = (
        replace(tree, policy_digest="b" * 64),
        replace(tree, limits=replace(tree.limits, max_visits=tree.limits.max_visits + 1)),
        replace(
            tree,
            aggregate_budget=replace(tree.aggregate_budget, tokens=1),
        ),
        reduce_tree_statuses(
            tree, {"node_step_1": PlanStepStatus.IN_PROGRESS}
        ),
    )

    assert len({tree.digest, *(variant.digest for variant in variants)}) == 5


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ((PlanStepStatus.PENDING,), PlanStepStatus.PENDING),
        ((PlanStepStatus.IN_PROGRESS,), PlanStepStatus.IN_PROGRESS),
        ((PlanStepStatus.COMPLETED,), PlanStepStatus.COMPLETED),
        (
            (PlanStepStatus.COMPLETED, PlanStepStatus.PENDING),
            PlanStepStatus.IN_PROGRESS,
        ),
        (
            (PlanStepStatus.CANCELLED, PlanStepStatus.BLOCKED, PlanStepStatus.FAILED),
            PlanStepStatus.FAILED,
        ),
        (
            (PlanStepStatus.CANCELLED, PlanStepStatus.BLOCKED),
            PlanStepStatus.BLOCKED,
        ),
        ((PlanStepStatus.CANCELLED,), PlanStepStatus.CANCELLED),
    ],
)
def test_parent_status_reduction_precedence_is_total(
    statuses: tuple[PlanStepStatus, ...], expected: PlanStepStatus
) -> None:
    assert reduce_child_statuses(statuses) is expected


def test_reducer_covers_every_status_combination_without_mutating_tree() -> None:
    original = _tree()
    for left, right in itertools.product(PlanStepStatus, repeat=2):
        reduced = reduce_tree_statuses(
            original,
            {"node_step_1": left, "node_step_2": right},
        )
        assert reduced.status is reduce_child_statuses((left, right))
        assert original.status is PlanStepStatus.PENDING


def test_completed_linear_plan_remains_readable_without_status_rewrite() -> None:
    plan = _linear_plan()
    first_running = transition_plan_step(plan, "step_1", PlanStepStatus.IN_PROGRESS)
    first_done = transition_plan_step(
        first_running, "step_1", PlanStepStatus.COMPLETED
    )
    final_running = transition_plan_step(
        first_done, "step_2", PlanStepStatus.IN_PROGRESS
    )
    completed = transition_plan_step(
        final_running, "step_2", PlanStepStatus.COMPLETED
    )

    tree = project_linear_plan(
        completed, tree_id="tree_completed", policy_digest=POLICY_DIGEST
    )
    assert tree.status is PlanStepStatus.COMPLETED
    assert {
        node.step_id: node.status for node in tree.nodes if node.step_id is not None
    } == {step.step_id: step.status for step in completed.steps}


def test_schema_supports_each_closed_node_kind_without_executable_content() -> None:
    nodes = (
        TreeNode(
            node_id="root",
            kind=TreeNodeKind.GOAL,
            child_ids=("sequence",),
        ),
        TreeNode(
            node_id="sequence",
            parent_id="root",
            kind=TreeNodeKind.SEQUENCE,
            child_ids=(
                "condition",
                "choice",
                "verify",
                "subtree",
                "final",
            ),
        ),
        TreeNode(
            node_id="condition",
            parent_id="sequence",
            kind=TreeNodeKind.CONDITION,
            condition_id="window_present",
        ),
        TreeNode(
            node_id="choice",
            parent_id="sequence",
            kind=TreeNodeKind.CHOICE,
            child_ids=("tool",),
        ),
        TreeNode(
            node_id="tool",
            parent_id="choice",
            kind=TreeNodeKind.TOOL_STEP,
            step_id="step_1",
        ),
        TreeNode(
            node_id="verify",
            parent_id="sequence",
            kind=TreeNodeKind.VERIFY,
            verification_id="window_stable",
        ),
        TreeNode(
            node_id="subtree",
            parent_id="sequence",
            kind=TreeNodeKind.SUBTREE,
            template_id="observation_ladder",
            template_version=1,
            template_digest="c" * 64,
        ),
        TreeNode(
            node_id="final",
            parent_id="sequence",
            kind=TreeNodeKind.FINAL_RESPONSE,
            step_id="step_final",
        ),
    )
    tree = TaskTree(
        tree_id="tree_kinds",
        run_id="run_1",
        task_digest="d" * 64,
        registry_digest="e" * 64,
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=nodes,
    )

    assert {node.kind for node in tree.nodes} == set(TreeNodeKind) - {
        TreeNodeKind.PARALLEL,
        TreeNodeKind.JOIN,
    }
    assert all("arguments" not in node.to_payload() for node in tree.nodes)


@pytest.mark.parametrize(
    "node",
    [
        TreeNode(
            node_id="bad_parent",
            parent_id="missing",
            kind=TreeNodeKind.FINAL_RESPONSE,
            step_id="step_final",
        ),
        TreeNode(
            node_id="duplicate_parent",
            parent_id="root",
            kind=TreeNodeKind.FINAL_RESPONSE,
            step_id="step_final",
        ),
    ],
)
def test_invalid_parent_or_reachability_fails_closed(node: TreeNode) -> None:
    root = TreeNode(
        node_id="root",
        kind=TreeNodeKind.SEQUENCE,
        child_ids=("final",),
    )
    final = TreeNode(
        node_id="final",
        parent_id="root",
        kind=TreeNodeKind.FINAL_RESPONSE,
        step_id="step_final",
    )
    with pytest.raises(TreeValidationError):
        TaskTree(
            tree_id="tree_invalid",
            run_id="run_1",
            task_digest="d" * 64,
            registry_digest="e" * 64,
            policy_digest=POLICY_DIGEST,
            root_id="root",
            nodes=(root, final, node),
        )


def test_cycle_depth_count_child_and_budget_limits_fail_closed() -> None:
    tree = _tree()
    root = next(node for node in tree.nodes if node.node_id == "root")
    first = next(node for node in tree.nodes if node.node_id == "node_step_1")

    with pytest.raises(TreeValidationError, match="budget"):
        replace(first, budget=TreeBudget(tool_calls=2))
        # Tree validation, not the immutable node, owns aggregate comparison.
        replace(
            tree,
            nodes=tuple(
                replace(first, budget=TreeBudget(tool_calls=2))
                if node.node_id == first.node_id
                else node
                for node in tree.nodes
            ),
        )

    with pytest.raises(TreeValidationError, match="child count"):
        replace(
            tree,
            limits=replace(tree.limits, max_children=1),
        )

    with pytest.raises(TreeValidationError, match="node count"):
        replace(tree, limits=replace(tree.limits, max_nodes=2))

    cycle_root = replace(root, parent_id="node_step_1")
    cycle_first = TreeNode(
        node_id="node_step_1",
        parent_id="root",
        kind=TreeNodeKind.SEQUENCE,
        child_ids=("root",),
    )
    with pytest.raises(TreeValidationError):
        replace(tree, nodes=(cycle_root, cycle_first, tree.nodes[1]))

    deep_nodes = [
        TreeNode(node_id="root", kind=TreeNodeKind.SEQUENCE, child_ids=("n1",))
    ]
    for index in range(1, 4):
        child = "final" if index == 3 else f"n{index + 1}"
        deep_nodes.append(
            TreeNode(
                node_id=f"n{index}",
                parent_id="root" if index == 1 else f"n{index - 1}",
                kind=TreeNodeKind.SEQUENCE,
                child_ids=(child,),
            )
        )
    deep_nodes.append(
        TreeNode(
            node_id="final",
            parent_id="n3",
            kind=TreeNodeKind.FINAL_RESPONSE,
            step_id="step_final",
        )
    )
    with pytest.raises(TreeValidationError, match="depth"):
        TaskTree(
            tree_id="tree_deep",
            run_id="run_1",
            task_digest="d" * 64,
            registry_digest="e" * 64,
            policy_digest=POLICY_DIGEST,
            root_id="root",
            nodes=tuple(deep_nodes),
            limits=TreeLimits(max_depth=3),
        )


def test_malformed_bindings_limits_versions_and_unknown_status_fail_closed() -> None:
    with pytest.raises(TreeValidationError):
        TreeNode(node_id="condition", kind=TreeNodeKind.CONDITION)
    with pytest.raises(TreeValidationError):
        TreeNode(
            node_id="subtree",
            kind=TreeNodeKind.SUBTREE,
            template_id="template",
            template_version=True,  # type: ignore[arg-type]
            template_digest="a" * 64,
        )
    with pytest.raises(TreeValidationError):
        TreeLimits(max_visits=0)
    with pytest.raises(TreeValidationError):
        TreeBudget(retries=True)  # type: ignore[arg-type]
    with pytest.raises(TreeValidationError):
        reduce_child_statuses(())
    with pytest.raises(TreeValidationError):
        reduce_child_statuses(("unknown",))  # type: ignore[arg-type]
    with pytest.raises(TreeValidationError):
        replace(_tree(), contract_version=2)
    with pytest.raises(TreeValidationError):
        reduce_tree_statuses(
            _tree(), {"root": PlanStepStatus.COMPLETED}
        )


def test_global_child_limit_is_enforced_by_the_pure_reducer() -> None:
    with pytest.raises(TreeValidationError):
        reduce_child_statuses(
            tuple(PlanStepStatus.PENDING for _ in range(MAX_TREE_CHILDREN + 1))
        )
