from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from computer_use_agent.hierarchical_compiler import (
    TreeCompileError,
    TreeTickDisposition,
    compile_next_leaf,
    transition_tree_leaf,
)
from computer_use_agent.hierarchical_control import (
    TREE_CONTRACT_VERSION_V2,
    TREE_CONTRACT_VERSION_V3,
    TaskTree,
    TreeLimits,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
    reduce_child_statuses,
    reduce_tree_statuses,
)
from computer_use_agent.hierarchical_graph_contract import (
    MAX_TREE_DEPENDENCIES,
    MAX_TREE_DEPENDENCY_FAN_IN,
    MAX_TREE_GRAPH_DEPTH,
    TreeDependency,
    TreeDependencyError,
)
from computer_use_agent.planning import PlanStepStatus
from computer_use_agent.run_lock import RunLock
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.tree_store import TaskTreeStore, TreeStoreError, task_tree_path


POLICY_DIGEST = "a" * 64


def _graph_tree(
    *, dependencies: tuple[TreeDependency, ...] | None = None
) -> TaskTree:
    bound_dependencies = (
        (
            TreeDependency("a", "join"),
            TreeDependency("b", "join"),
        )
        if dependencies is None
        else dependencies
    )
    return TaskTree(
        contract_version=TREE_CONTRACT_VERSION_V3,
        tree_id="tree_graph",
        run_id="run_1",
        task_digest="b" * 64,
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=(
            TreeNode(
                node_id="root",
                kind=TreeNodeKind.SEQUENCE,
                child_ids=("parallel", "join", "final"),
            ),
            TreeNode(
                node_id="parallel",
                parent_id="root",
                kind=TreeNodeKind.PARALLEL,
                child_ids=("a", "b"),
            ),
            TreeNode(
                node_id="a",
                parent_id="parallel",
                kind=TreeNodeKind.TOOL_STEP,
                step_id="step_a",
            ),
            TreeNode(
                node_id="b",
                parent_id="parallel",
                kind=TreeNodeKind.TOOL_STEP,
                step_id="step_b",
            ),
            TreeNode(
                node_id="join",
                parent_id="root",
                kind=TreeNodeKind.JOIN,
            ),
            TreeNode(
                node_id="final",
                parent_id="root",
                kind=TreeNodeKind.FINAL_RESPONSE,
                step_id="step_final",
            ),
        ),
        dependencies=bound_dependencies,
    )


def _sequence_graph(
    child_ids: tuple[str, ...], dependencies: tuple[TreeDependency, ...]
) -> TaskTree:
    nodes: list[TreeNode] = [
        TreeNode(
            node_id="root",
            kind=TreeNodeKind.SEQUENCE,
            child_ids=child_ids,
        )
    ]
    for node_id in child_ids:
        if node_id == "join":
            kind = TreeNodeKind.JOIN
            step_id = None
        elif node_id == "final":
            kind = TreeNodeKind.FINAL_RESPONSE
            step_id = "step_final"
        else:
            kind = TreeNodeKind.TOOL_STEP
            step_id = f"step_{node_id}"
        nodes.append(
            TreeNode(
                node_id=node_id,
                parent_id="root",
                kind=kind,
                step_id=step_id,
            )
        )
    return TaskTree(
        contract_version=TREE_CONTRACT_VERSION_V3,
        tree_id="tree_sequence_graph",
        run_id="run_1",
        task_digest="b" * 64,
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=tuple(nodes),
        limits=TreeLimits(max_children=len(child_ids)),
        dependencies=dependencies,
    )


def _v2_parallel_tree() -> TaskTree:
    return TaskTree(
        contract_version=TREE_CONTRACT_VERSION_V2,
        tree_id="tree_v2",
        run_id="run_1",
        task_digest="b" * 64,
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=(
            TreeNode(
                node_id="root",
                kind=TreeNodeKind.SEQUENCE,
                child_ids=("parallel", "final"),
            ),
            TreeNode(
                node_id="parallel",
                parent_id="root",
                kind=TreeNodeKind.PARALLEL,
                child_ids=("condition_a", "condition_b"),
            ),
            TreeNode(
                node_id="condition_a",
                parent_id="parallel",
                kind=TreeNodeKind.CONDITION,
                condition_id="condition_a",
            ),
            TreeNode(
                node_id="condition_b",
                parent_id="parallel",
                kind=TreeNodeKind.CONDITION,
                condition_id="condition_b",
            ),
            TreeNode(
                node_id="final",
                parent_id="root",
                kind=TreeNodeKind.FINAL_RESPONSE,
                step_id="step_final",
            ),
        ),
    )


def _locked_store(tmp_path: Path) -> tuple[TaskTreeStore, RunLock]:
    lock = RunLock((tmp_path / "application").resolve())
    lock.acquire()
    return TaskTreeStore((tmp_path / "state").resolve(), lock), lock


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _resign(payload: dict[str, object]) -> None:
    tree = payload["tree"]
    payload["tree_digest"] = hashlib.sha256(_canonical(tree)).hexdigest()
    unsigned = {
        key: value for key, value in payload.items() if key != "envelope_digest"
    }
    payload["envelope_digest"] = hashlib.sha256(_canonical(unsigned)).hexdigest()


def test_v3_contract_is_content_free_canonical_and_strictly_versioned() -> None:
    tree = _graph_tree()
    payload = tree.to_payload()

    assert tree.contract_version == 3
    assert tree.digest == "afb85674dd5c1c7522f08acfb82614f35936ab899333993cbe5d0d4208bec72c"
    assert payload["dependencies"] == [
        {"prerequisite_id": "a", "dependent_id": "join"},
        {"prerequisite_id": "b", "dependent_id": "join"},
    ]
    assert payload["parallel_batches"] == []
    assert not hasattr(tree.dependencies[0], "call")
    assert "arguments" not in json.dumps(payload)
    with pytest.raises(TreeValidationError, match="v2 cannot carry H8B"):
        replace(tree, contract_version=2)


def test_dependency_shape_rejects_missing_self_duplicate_and_noncanonical_edges() -> None:
    with pytest.raises(TreeDependencyError, match="SELF_REFERENCE"):
        TreeDependency("a", "a")
    with pytest.raises(TreeValidationError, match="binding is invalid"):
        _graph_tree(
            dependencies=(
                TreeDependency("a", "join"),
                TreeDependency("missing", "join"),
            )
        )
    with pytest.raises(TreeValidationError, match="duplicates"):
        _graph_tree(
            dependencies=(
                TreeDependency("a", "join"),
                TreeDependency("a", "join"),
            )
        )
    with pytest.raises(TreeValidationError, match="not canonical"):
        _graph_tree(
            dependencies=(
                TreeDependency("b", "join"),
                TreeDependency("a", "join"),
            )
        )
    with pytest.raises(TreeValidationError, match="dependent must be a leaf"):
        _graph_tree(
            dependencies=tuple(
                sorted(
                    (
                        TreeDependency("a", "join"),
                        TreeDependency("b", "join"),
                        TreeDependency("a", "parallel"),
                    )
                )
            )
        )


def test_dependency_graph_rejects_direct_structural_and_order_cycles() -> None:
    with pytest.raises(TreeValidationError, match="contains a cycle"):
        _graph_tree(
            dependencies=(
                TreeDependency("a", "b"),
                TreeDependency("a", "join"),
                TreeDependency("b", "a"),
                TreeDependency("b", "join"),
            )
        )
    with pytest.raises(TreeValidationError, match="contains a cycle"):
        _graph_tree(
            dependencies=(
                TreeDependency("a", "join"),
                TreeDependency("b", "join"),
                TreeDependency("parallel", "a"),
            )
        )
    with pytest.raises(TreeValidationError, match="contains a cycle"):
        _sequence_graph(
            ("a", "b", "join", "final"),
            (
                TreeDependency("a", "join"),
                TreeDependency("b", "a"),
                TreeDependency("b", "join"),
            ),
        )


def test_dependency_fan_in_total_and_graph_depth_are_bounded() -> None:
    fan_in_ids = tuple(
        f"n_{index:02d}" for index in range(MAX_TREE_DEPENDENCY_FAN_IN + 1)
    )
    with pytest.raises(TreeValidationError, match="fan-in"):
        _sequence_graph(
            (*fan_in_ids, "join", "final"),
            tuple(TreeDependency(node_id, "join") for node_id in fan_in_ids),
        )

    node_ids = tuple(f"n_{index:02d}" for index in range(20))
    too_many: list[TreeDependency] = []
    for target_index in range(1, len(node_ids)):
        for source_index in range(max(0, target_index - 16), target_index):
            too_many.append(
                TreeDependency(node_ids[source_index], node_ids[target_index])
            )
            if len(too_many) == MAX_TREE_DEPENDENCIES + 1:
                break
        if len(too_many) == MAX_TREE_DEPENDENCIES + 1:
            break
    too_many.append(TreeDependency(node_ids[-1], "join"))
    with pytest.raises(TreeValidationError, match="dependency count"):
        _sequence_graph((*node_ids, "join", "final"), tuple(sorted(too_many)))

    depth_ids = tuple(f"d_{index:02d}" for index in range(MAX_TREE_GRAPH_DEPTH - 2))
    with pytest.raises(TreeValidationError, match="depth exceeds"):
        _sequence_graph(
            (*depth_ids, "join", "final"),
            (TreeDependency(depth_ids[-1], "join"),),
        )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        (PlanStepStatus.PENDING, PlanStepStatus.PENDING),
        (PlanStepStatus.COMPLETED, PlanStepStatus.PENDING),
        (PlanStepStatus.IN_PROGRESS, PlanStepStatus.COMPLETED),
        (PlanStepStatus.COMPLETED, PlanStepStatus.COMPLETED),
        (PlanStepStatus.CANCELLED, PlanStepStatus.COMPLETED),
        (PlanStepStatus.BLOCKED, PlanStepStatus.CANCELLED),
        (PlanStepStatus.FAILED, PlanStepStatus.BLOCKED),
    ],
)
def test_join_is_a_pure_local_all_of_reduction(
    left: PlanStepStatus, right: PlanStepStatus
) -> None:
    reduced = reduce_tree_statuses(_graph_tree(), {"a": left, "b": right})
    by_id = {node.node_id: node for node in reduced.nodes}

    assert by_id["join"].status is reduce_child_statuses((left, right))
    assert not hasattr(by_id["join"], "dispatch")
    with pytest.raises(TreeValidationError, match="non-leaf"):
        reduce_tree_statuses(_graph_tree(), {"join": PlanStepStatus.COMPLETED})


def test_v3_parallel_selects_one_stable_ready_leaf_and_never_emits_join() -> None:
    tree = _graph_tree(
        dependencies=(
            TreeDependency("a", "b"),
            TreeDependency("a", "join"),
            TreeDependency("b", "join"),
        )
    )
    first = compile_next_leaf(tree, sequence=0)
    assert first.boundary is not None
    assert first.boundary.node_id == "a"

    a_running = transition_tree_leaf(tree, "a", PlanStepStatus.IN_PROGRESS)
    waiting = compile_next_leaf(a_running, sequence=1)
    assert waiting.disposition is TreeTickDisposition.WAITING
    assert waiting.boundary is None

    a_done = transition_tree_leaf(a_running, "a", PlanStepStatus.COMPLETED)
    second = compile_next_leaf(a_done, sequence=2)
    assert second.boundary is not None
    assert second.boundary.node_id == "b"

    b_running = transition_tree_leaf(a_done, "b", PlanStepStatus.IN_PROGRESS)
    b_done = transition_tree_leaf(b_running, "b", PlanStepStatus.COMPLETED)
    by_id = {node.node_id: node for node in b_done.nodes}
    assert by_id["join"].status is PlanStepStatus.COMPLETED
    final = compile_next_leaf(b_done, sequence=3)
    assert final.boundary is not None
    assert final.boundary.node_id == "final"
    assert final.boundary.node_kind is TreeNodeKind.FINAL_RESPONSE


def test_any_active_external_leaf_blocks_a_second_parallel_boundary() -> None:
    forced = reduce_tree_statuses(
        _graph_tree(),
        {"b": PlanStepStatus.IN_PROGRESS},
    )
    tick = compile_next_leaf(forced, sequence=4)

    assert tick.disposition is TreeTickDisposition.WAITING
    assert tick.boundary is None
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_ACTIVE_LEAF"):
        transition_tree_leaf(forced, "a", PlanStepStatus.IN_PROGRESS)


def test_v3_store_round_trip_and_resigned_dependency_tamper_fail_closed(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_graph_tree())
        assert store.read("run_1") == created
        path = task_tree_path(store.state_dir, "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tree"]["dependencies"][0]["dependent_id"] = "missing"
        _resign(payload)
        path.write_bytes(_canonical(payload) + b"\n")

        with pytest.raises(TreeStoreError, match="TREE_STORE_INVALID"):
            store.read("run_1")
    finally:
        lock.release()


def test_v3_dependency_structure_is_immutable_under_tree_store_cas(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_graph_tree())
        mutated = replace(
            created.tree,
            dependencies=(
                TreeDependency("a", "b"),
                TreeDependency("a", "join"),
                TreeDependency("b", "join"),
            ),
        )

        with pytest.raises(TreeStoreError, match="TREE_STORE_STRUCTURE_MISMATCH"):
            store.compare_and_swap(
                "run_1",
                mutated,
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )
        assert store.read("run_1") == created
    finally:
        lock.release()


def test_v2_payload_rejects_resigned_v3_field(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_v2_parallel_tree())
        path = task_tree_path(store.state_dir, "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tree"]["dependencies"] = []
        _resign(payload)
        path.write_bytes(_canonical(payload) + b"\n")

        with pytest.raises(TreeStoreError, match="TREE_STORE_INVALID"):
            store.read("run_1")
    finally:
        lock.release()
