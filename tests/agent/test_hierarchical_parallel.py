from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

import computer_use_agent.hierarchical_parallel as parallel_module
from computer_use_agent.hierarchical_control import (
    TREE_CONTRACT_VERSION_V2,
    TREE_CONTRACT_VERSION_V3,
    TaskTree,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
)
from computer_use_agent.hierarchical_graph_contract import TreeDependency
from computer_use_agent.hierarchical_parallel import (
    ParallelConditionError,
    apply_parallel_condition_batch,
    evaluate_and_commit_parallel_conditions,
    evaluate_parallel_conditions,
    world_state_context_digest,
)
from computer_use_agent.hierarchical_parallel_contract import (
    ParallelBatchDisposition,
)
from computer_use_agent.planning import PlanStepStatus
from computer_use_agent.run_lock import RunLock
from computer_use_agent.tool_registry import reviewed_registry_digest
from computer_use_agent.tree_store import TaskTreeStore, TreeStoreError, task_tree_path
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ToolResult,
    ToolResultStatus,
)
from computer_use_agent.world_state import (
    ConditionEvaluation,
    ConditionOutcome,
    FactAvailability,
    FactCondition,
    FactKnowledge,
    FactScope,
    FactType,
    ObservationEvidence,
    WorldFact,
    WorldStateContext,
    WorldStateSnapshot,
)


POLICY_DIGEST = "a" * 64
TASK_DIGEST = "b" * 64


def _tree(*, child_ids: tuple[str, ...] = ("condition_a", "condition_b")) -> TaskTree:
    conditions = tuple(
        TreeNode(
            node_id=node_id,
            parent_id="parallel",
            kind=TreeNodeKind.CONDITION,
            condition_id=node_id,
        )
        for node_id in child_ids
    )
    return TaskTree(
        contract_version=TREE_CONTRACT_VERSION_V2,
        tree_id="tree_1",
        run_id="run_1",
        task_digest=TASK_DIGEST,
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
                child_ids=child_ids,
            ),
            *conditions,
            TreeNode(
                node_id="final",
                parent_id="root",
                kind=TreeNodeKind.FINAL_RESPONSE,
                step_id="step_final",
            ),
        ),
    )


def _v3_tree() -> TaskTree:
    base = _tree()
    nodes = tuple(
        replace(node, child_ids=("parallel", "join", "final"))
        if node.node_id == "root"
        else node
        for node in base.nodes
    )
    return TaskTree(
        contract_version=TREE_CONTRACT_VERSION_V3,
        tree_id=base.tree_id,
        run_id=base.run_id,
        task_digest=base.task_digest,
        registry_digest=base.registry_digest,
        policy_digest=base.policy_digest,
        root_id=base.root_id,
        nodes=(
            *nodes,
            TreeNode(
                node_id="join",
                parent_id="root",
                kind=TreeNodeKind.JOIN,
            ),
        ),
        dependencies=(
            TreeDependency("condition_a", "join"),
            TreeDependency("condition_b", "join"),
        ),
    )


def _evidence(fact_id: str) -> ObservationEvidence:
    result = ToolResult(
        CallIdentity("run_1", "turn_1", f"call_{fact_id}"),
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="content excluded",
    )
    return ObservationEvidence.from_tool_result(
        result,
        observation_epoch=3,
        mcp_generation=7,
        captured_at_ms=1_000,
    )


def _snapshot(*, a: bool = True, b: bool = True) -> WorldStateSnapshot:
    return WorldStateSnapshot(
        run_id="run_1",
        facts=(
            WorldFact(
                fact_id="fact_a",
                fact_type=FactType.BOOLEAN,
                knowledge=FactKnowledge.OBSERVED,
                value=a,
                evidence=_evidence("a"),
                scope=FactScope.RUN,
                max_age_ms=1_000,
            ),
            WorldFact(
                fact_id="fact_b",
                fact_type=FactType.BOOLEAN,
                knowledge=FactKnowledge.OBSERVED,
                value=b,
                evidence=_evidence("b"),
                scope=FactScope.RUN,
                max_age_ms=1_000,
            ),
        ),
    )


def _context(*, epoch: int = 3) -> WorldStateContext:
    return WorldStateContext(
        run_id="run_1",
        observation_epoch=epoch,
        mcp_generation=7,
        now_ms=1_500,
    )


def _conditions() -> dict[str, FactCondition]:
    return {
        "condition_a": FactCondition(
            "condition_a", "fact_a", FactType.BOOLEAN, True
        ),
        "condition_b": FactCondition(
            "condition_b", "fact_b", FactType.BOOLEAN, True
        ),
    }


def _locked_store(tmp_path: Path) -> tuple[TaskTreeStore, RunLock]:
    lock = RunLock((tmp_path / "application").resolve())
    lock.acquire()
    return TaskTreeStore((tmp_path / "state").resolve(), lock), lock


def test_v2_parallel_shape_is_closed_bounded_and_canonical() -> None:
    tree = _tree()

    assert tree.contract_version == 2
    assert tree.digest == "4fd8b73783d18df11f896be41052a5fa45da85fcf4d000adb522ae00ff27fd2e"
    assert tree.to_payload()["parallel_batches"] == []
    assert "dependencies" not in tree.to_payload()
    assert next(node for node in tree.nodes if node.node_id == "parallel").child_ids == (
        "condition_a",
        "condition_b",
    )
    with pytest.raises(TreeValidationError, match="v1 cannot carry H8"):
        replace(tree, contract_version=1)
    with pytest.raises(TreeValidationError, match="not canonical"):
        _tree(child_ids=("condition_b", "condition_a"))
    with pytest.raises(TreeValidationError, match="not canonical"):
        _tree(child_ids=("condition_a",))


def test_v3_direct_condition_parallel_reuses_the_same_bounded_h8a_batch() -> None:
    tree = _v3_tree()
    batch = evaluate_parallel_conditions(
        tree,
        source_sequence=0,
        parallel_node_id="parallel",
        conditions=_conditions(),
        snapshot=_snapshot(),
        context=_context(),
    )
    projected = apply_parallel_condition_batch(tree, batch)
    by_id = {node.node_id: node for node in projected.nodes}

    assert batch.disposition is ParallelBatchDisposition.COMPLETED
    assert by_id["parallel"].status is PlanStepStatus.COMPLETED
    assert by_id["join"].status is PlanStepStatus.COMPLETED


def test_parallel_workers_overlap_and_results_are_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(2)
    thread_ids: set[int] = set()
    original = parallel_module.evaluate_fact_condition

    def overlapping(
        snapshot: WorldStateSnapshot,
        condition: FactCondition,
        context: WorldStateContext,
    ) -> ConditionEvaluation:
        thread_ids.add(threading.get_ident())
        barrier.wait(timeout=2)
        return original(snapshot, condition, context)

    monkeypatch.setattr(parallel_module, "evaluate_fact_condition", overlapping)
    tree = _tree()
    first = evaluate_parallel_conditions(
        tree,
        source_sequence=0,
        parallel_node_id="parallel",
        conditions=_conditions(),
        snapshot=_snapshot(),
        context=_context(),
    )
    second = evaluate_parallel_conditions(
        tree,
        source_sequence=0,
        parallel_node_id="parallel",
        conditions=dict(reversed(tuple(_conditions().items()))),
        snapshot=_snapshot(),
        context=_context(),
    )

    assert len(thread_ids) >= 2
    assert first == second
    assert first.disposition is ParallelBatchDisposition.COMPLETED
    assert tuple(item.node_id for item in first.results) == (
        "condition_a",
        "condition_b",
    )
    assert first.snapshot_digest == _snapshot().digest
    assert first.context_digest == world_state_context_digest(_context())
    assert len(first.digest) == 64
    assert "content excluded" not in json.dumps(first.to_payload())


def test_parallel_worker_pool_is_fixed_at_four(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_ids = tuple(f"condition_{letter}" for letter in "abcde")
    barrier = threading.Barrier(4)
    thread_ids: set[int] = set()

    def bounded(
        snapshot: WorldStateSnapshot,
        condition: FactCondition,
        context: WorldStateContext,
    ) -> ConditionEvaluation:
        thread_ids.add(threading.get_ident())
        if condition.condition_id != "condition_e":
            barrier.wait(timeout=2)
        return ConditionEvaluation(
            condition_id=condition.condition_id,
            outcome=ConditionOutcome.TRUE,
            availability=FactAvailability.FRESH,
            condition_digest=condition.digest,
            fact_digest="c" * 64,
            evidence_digest="d" * 64,
        )

    monkeypatch.setattr(parallel_module, "evaluate_fact_condition", bounded)
    conditions = {
        node_id: FactCondition(node_id, "fact_a", FactType.BOOLEAN, True)
        for node_id in child_ids
    }
    batch = evaluate_parallel_conditions(
        _tree(child_ids=child_ids),
        source_sequence=0,
        parallel_node_id="parallel",
        conditions=conditions,
        snapshot=_snapshot(),
        context=_context(),
    )

    assert len(thread_ids) == 4
    assert batch.disposition is ParallelBatchDisposition.COMPLETED


def test_false_is_known_failure_while_unavailable_never_writes_state(
    tmp_path: Path,
) -> None:
    tree = _tree()
    failed = evaluate_parallel_conditions(
        tree,
        source_sequence=0,
        parallel_node_id="parallel",
        conditions=_conditions(),
        snapshot=_snapshot(b=False),
        context=_context(),
    )
    projected = apply_parallel_condition_batch(tree, failed)
    statuses = {node.node_id: node.status for node in projected.nodes}

    assert failed.disposition is ParallelBatchDisposition.FAILED
    assert statuses["condition_a"] is PlanStepStatus.COMPLETED
    assert statuses["condition_b"] is PlanStepStatus.FAILED
    assert statuses["parallel"] is PlanStepStatus.FAILED
    assert projected.status is PlanStepStatus.FAILED
    assert projected.parallel_batches == (failed,)

    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(tree)
        path = task_tree_path(store.state_dir, "run_1")
        before = path.read_bytes()
        blocked = evaluate_and_commit_parallel_conditions(
            store,
            "run_1",
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
            parallel_node_id="parallel",
            conditions=_conditions(),
            snapshot=_snapshot(),
            context=_context(epoch=4),
        )
        assert blocked.batch.disposition is ParallelBatchDisposition.BLOCKED
        assert blocked.persisted is None
        assert path.read_bytes() == before
        assert store.read("run_1") == created
    finally:
        lock.release()


def test_known_batch_commits_status_and_evidence_once_and_survives_restart(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        committed = evaluate_and_commit_parallel_conditions(
            store,
            "run_1",
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
            parallel_node_id="parallel",
            conditions=_conditions(),
            snapshot=_snapshot(),
            context=_context(),
        )

        assert committed.persisted is not None
        assert committed.persisted.sequence == 1
        assert committed.persisted.tree.parallel_batches == (committed.batch,)
        assert store.read("run_1") == committed.persisted
        assert all(
            node.status is PlanStepStatus.COMPLETED
            for node in committed.persisted.tree.nodes
            if node.node_id in {"parallel", "condition_a", "condition_b"}
        )
        assert committed.persisted.tree.status is PlanStepStatus.IN_PROGRESS
    finally:
        lock.release()

    lock.acquire()
    try:
        restarted = TaskTreeStore(store.state_dir, lock).read("run_1")
        assert restarted == committed.persisted
    finally:
        lock.release()


def test_exception_and_cas_conflict_leave_the_exact_prior_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        path = task_tree_path(store.state_dir, "run_1")
        before = path.read_bytes()

        original = parallel_module.evaluate_fact_condition

        def explode(
            snapshot: WorldStateSnapshot,
            condition: FactCondition,
            context: WorldStateContext,
        ) -> ConditionEvaluation:
            raise RuntimeError("injected evaluator failure")

        monkeypatch.setattr(parallel_module, "evaluate_fact_condition", explode)
        with pytest.raises(RuntimeError, match="injected evaluator failure"):
            evaluate_and_commit_parallel_conditions(
                store,
                "run_1",
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
                parallel_node_id="parallel",
                conditions=_conditions(),
                snapshot=_snapshot(),
                context=_context(),
            )
        assert path.read_bytes() == before

        monkeypatch.setattr(parallel_module, "evaluate_fact_condition", original)

        def conflict(*args: object, **kwargs: object) -> object:
            raise TreeStoreError("TREE_STORE_STALE_WRITE")

        monkeypatch.setattr(store, "compare_and_swap", conflict)
        with pytest.raises(TreeStoreError, match="TREE_STORE_STALE_WRITE"):
            evaluate_and_commit_parallel_conditions(
                store,
                "run_1",
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
                parallel_node_id="parallel",
                conditions=_conditions(),
                snapshot=_snapshot(),
                context=_context(),
            )
        assert path.read_bytes() == before
    finally:
        lock.release()


def test_store_rejects_rehashed_cross_version_and_batch_tampering(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        committed = evaluate_and_commit_parallel_conditions(
            store,
            "run_1",
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
            parallel_node_id="parallel",
            conditions=_conditions(),
            snapshot=_snapshot(),
            context=_context(),
        )
        assert committed.persisted is not None
        path = task_tree_path(store.state_dir, "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tree"]["parallel_batches"][0]["results"][0]["outcome"] = "false"
        payload["tree_digest"] = hashlib.sha256(
            json.dumps(
                payload["tree"],
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        unsigned = {
            key: value for key, value in payload.items() if key != "envelope_digest"
        }
        payload["envelope_digest"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(TreeStoreError):
            store.read("run_1")
    finally:
        lock.release()


def test_invalid_bindings_fail_before_worker_start() -> None:
    with pytest.raises(ParallelConditionError, match="BINDING_INVALID"):
        evaluate_parallel_conditions(
            _tree(),
            source_sequence=0,
            parallel_node_id="parallel",
            conditions={"condition_a": _conditions()["condition_a"]},
            snapshot=_snapshot(),
            context=_context(),
        )
