from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import replace
from pathlib import Path

import pytest

import computer_use_agent.hierarchical_choice as choice_module
from computer_use_agent.hierarchical_choice import (
    ChoiceEvaluationError,
    apply_choice_event,
    build_pre_boundary_false_fallback,
    build_verified_read_only_miss_fallback,
    evaluate_and_commit_choice,
    evaluate_choice_event,
)
from computer_use_agent.hierarchical_choice_contract import (
    ChoiceBoundaryOutcome,
    ChoiceDisposition,
    ChoiceFallbackCause,
    choice_boundary_allows_fallback,
)
from computer_use_agent.hierarchical_compiler import (
    TreeCompileError,
    TreeTickDisposition,
    compile_next_leaf,
    transition_tree_leaf,
)
from computer_use_agent.hierarchical_control import (
    TREE_CONTRACT_VERSION_V4,
    TaskTree,
    TreeBudget,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
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


def _tree(*, side_effect_branch: str | None = None) -> TaskTree:
    branches = ("branch_a", "branch_b", "branch_c")
    nodes: list[TreeNode] = [
        TreeNode(
            node_id="root",
            kind=TreeNodeKind.SEQUENCE,
            child_ids=("choice", "final"),
        ),
        TreeNode(
            node_id="choice",
            parent_id="root",
            kind=TreeNodeKind.CHOICE,
            child_ids=branches,
        ),
    ]
    for suffix, branch_id in zip(("a", "b", "c"), branches):
        nodes.extend(
            (
                TreeNode(
                    node_id=branch_id,
                    parent_id="choice",
                    kind=TreeNodeKind.SEQUENCE,
                    child_ids=(f"gate_{suffix}", f"observe_{suffix}", f"verify_{suffix}"),
                ),
                TreeNode(
                    node_id=f"gate_{suffix}",
                    parent_id=branch_id,
                    kind=TreeNodeKind.CONDITION,
                    condition_id=f"gate_{suffix}",
                ),
                TreeNode(
                    node_id=f"observe_{suffix}",
                    parent_id=branch_id,
                    kind=TreeNodeKind.TOOL_STEP,
                    step_id=f"observe_{suffix}",
                    budget=TreeBudget(
                        tool_calls=1,
                        side_effects=1 if side_effect_branch == branch_id else 0,
                    ),
                ),
                TreeNode(
                    node_id=f"verify_{suffix}",
                    parent_id=branch_id,
                    kind=TreeNodeKind.VERIFY,
                    verification_id=f"miss_{suffix}",
                ),
            )
        )
    nodes.append(
        TreeNode(
            node_id="final",
            parent_id="root",
            kind=TreeNodeKind.FINAL_RESPONSE,
            step_id="final",
        )
    )
    return TaskTree(
        contract_version=TREE_CONTRACT_VERSION_V4,
        tree_id="tree_choice",
        run_id="run_1",
        task_digest="b" * 64,
        registry_digest=reviewed_registry_digest(),
        policy_digest=POLICY_DIGEST,
        root_id="root",
        nodes=tuple(nodes),
        aggregate_budget=TreeBudget(
            tool_calls=3,
            side_effects=1 if side_effect_branch is not None else 0,
        ),
    )


def _result(call_id: str) -> ToolResult:
    return ToolResult(
        CallIdentity("run_1", "turn_1", call_id),
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="content excluded",
    )


def _evidence(fact_id: str, *, epoch: int = 3) -> ObservationEvidence:
    return ObservationEvidence.from_tool_result(
        _result(f"call_{fact_id}"),
        observation_epoch=epoch,
        mcp_generation=7,
        captured_at_ms=1_000,
    )


def _snapshot(
    *,
    a: bool = True,
    b: bool = True,
    c: bool = True,
    miss_a: bool = False,
    epoch: int = 3,
) -> WorldStateSnapshot:
    values = {
        "gate_a": a,
        "gate_b": b,
        "gate_c": c,
        "miss_a": miss_a,
    }
    return WorldStateSnapshot(
        run_id="run_1",
        facts=tuple(
            WorldFact(
                fact_id=fact_id,
                fact_type=FactType.BOOLEAN,
                knowledge=FactKnowledge.OBSERVED,
                value=value,
                evidence=_evidence(fact_id, epoch=epoch),
                scope=FactScope.RUN,
                max_age_ms=1_000,
            )
            for fact_id, value in values.items()
        ),
    )


def _context(*, epoch: int = 3) -> WorldStateContext:
    return WorldStateContext(
        run_id="run_1",
        observation_epoch=epoch,
        mcp_generation=7,
        now_ms=1_500,
    )


def _gates(*names: str) -> dict[str, FactCondition]:
    return {
        name: FactCondition(name, name, FactType.BOOLEAN, True) for name in names
    }


def _initial(tree: TaskTree, snapshot: WorldStateSnapshot | None = None) -> TaskTree:
    event = evaluate_choice_event(
        tree,
        source_sequence=0,
        choice_node_id="choice",
        conditions=_gates("gate_a", "gate_b", "gate_c"),
        snapshot=_snapshot() if snapshot is None else snapshot,
        context=_context(),
    )
    return apply_choice_event(tree, event)


def _completed_observation(tree: TaskTree, suffix: str = "a") -> TaskTree:
    running = transition_tree_leaf(
        tree, f"observe_{suffix}", PlanStepStatus.IN_PROGRESS
    )
    return transition_tree_leaf(
        running, f"observe_{suffix}", PlanStepStatus.COMPLETED
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


@pytest.mark.parametrize(
    ("values", "disposition", "selected"),
    [
        ((True, False, False), ChoiceDisposition.SELECTED, "branch_a"),
        ((False, True, True), ChoiceDisposition.SELECTED, "branch_b"),
        ((False, False, True), ChoiceDisposition.SELECTED, "branch_c"),
        ((False, False, False), ChoiceDisposition.FAILED, None),
    ],
)
def test_host_order_selection_and_all_false_failure(
    values: tuple[bool, bool, bool],
    disposition: ChoiceDisposition,
    selected: str | None,
) -> None:
    tree = _tree()
    event = evaluate_choice_event(
        tree,
        source_sequence=0,
        choice_node_id="choice",
        conditions=_gates("gate_a", "gate_b", "gate_c"),
        snapshot=_snapshot(a=values[0], b=values[1], c=values[2]),
        context=_context(),
    )

    assert event.disposition is disposition
    assert event.selected_branch_id == selected
    projected = apply_choice_event(tree, event)
    assert projected.choice_events == (event,)
    if selected is None:
        assert projected.status is PlanStepStatus.FAILED
    else:
        tick = compile_next_leaf(projected, sequence=1)
        assert tick.boundary is not None
        assert tick.boundary.node_id == f"observe_{selected[-1]}"


def test_earlier_unavailable_blocks_later_true_and_writes_nothing(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        path = task_tree_path(store.state_dir, "run_1")
        before = path.read_bytes()
        commit = evaluate_and_commit_choice(
            store,
            "run_1",
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
            choice_node_id="choice",
            conditions=_gates("gate_a", "gate_b", "gate_c"),
            snapshot=_snapshot(a=False, b=True, c=True),
            context=_context(epoch=4),
        )

        assert commit.event.disposition is ChoiceDisposition.BLOCKED
        assert commit.persisted is None
        assert path.read_bytes() == before
    finally:
        lock.release()

def test_later_unavailable_cannot_displace_an_earlier_true() -> None:
    snapshot = _snapshot(a=True, b=True, c=True)
    event = evaluate_choice_event(
        _tree(),
        source_sequence=0,
        choice_node_id="choice",
        conditions=_gates("gate_a", "gate_b", "gate_c"),
        snapshot=snapshot,
        context=_context(),
    )
    tampered = replace(
        event,
        results=(
            event.results[0],
            replace(
                event.results[1],
                outcome=ConditionOutcome.UNAVAILABLE,
                availability=FactAvailability.EXPIRED,
                fact_digest=None,
                evidence_digest=None,
            ),
            event.results[2],
        ),
    )

    assert tampered.disposition is ChoiceDisposition.SELECTED
    assert tampered.selected_branch_id == "branch_a"


def test_gate_workers_overlap_but_result_order_remains_host_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = threading.Barrier(3)
    thread_ids: set[int] = set()
    original = choice_module.evaluate_fact_condition

    def overlapping(
        snapshot: WorldStateSnapshot,
        condition: FactCondition,
        context: WorldStateContext,
    ) -> ConditionEvaluation:
        thread_ids.add(threading.get_ident())
        barrier.wait(timeout=2)
        return original(snapshot, condition, context)

    monkeypatch.setattr(choice_module, "evaluate_fact_condition", overlapping)
    event = evaluate_choice_event(
        _tree(),
        source_sequence=0,
        choice_node_id="choice",
        conditions=_gates("gate_a", "gate_b", "gate_c"),
        snapshot=_snapshot(a=False, b=True, c=True),
        context=_context(),
    )

    assert len(thread_ids) == 3
    assert tuple(result.branch_id for result in event.results) == (
        "branch_a",
        "branch_b",
        "branch_c",
    )
    assert event.selected_branch_id == "branch_b"


def test_pre_boundary_fresh_false_can_select_the_next_host_order_branch() -> None:
    selected = _initial(_tree())
    fresh = _snapshot(a=False, b=True, c=True)
    fallback = build_pre_boundary_false_fallback(
        selected,
        choice_node_id="choice",
        condition=FactCondition("gate_a", "gate_a", FactType.BOOLEAN, True),
        snapshot=fresh,
        context=_context(),
    )
    event = evaluate_choice_event(
        selected,
        source_sequence=1,
        choice_node_id="choice",
        conditions=_gates("gate_b", "gate_c"),
        snapshot=fresh,
        context=_context(),
        fallback=fallback,
    )
    projected = apply_choice_event(selected, event)
    by_id = {node.node_id: node for node in projected.nodes}

    assert fallback.cause is ChoiceFallbackCause.PRE_BOUNDARY_FALSE
    assert event.selected_branch_id == "branch_b"
    assert by_id["gate_a"].status is PlanStepStatus.FAILED
    assert by_id["gate_b"].status is PlanStepStatus.COMPLETED
    assert compile_next_leaf(projected, sequence=2).boundary.node_id == "observe_b"  # type: ignore[union-attr]


def test_verified_read_only_miss_can_fallback_and_is_content_free() -> None:
    selected = _completed_observation(_initial(_tree()))
    snapshot = _snapshot(a=True, b=True, c=True, miss_a=False)
    fallback = build_verified_read_only_miss_fallback(
        selected,
        choice_node_id="choice",
        observation_node_id="observe_a",
        verification_node_id="verify_a",
        observation_evidence=_evidence("miss_a"),
        condition=FactCondition("miss_a", "miss_a", FactType.BOOLEAN, True),
        snapshot=snapshot,
        context=_context(),
    )
    event = evaluate_choice_event(
        selected,
        source_sequence=3,
        choice_node_id="choice",
        conditions=_gates("gate_b", "gate_c"),
        snapshot=snapshot,
        context=_context(),
        fallback=fallback,
    )
    projected = apply_choice_event(selected, event)

    assert fallback.cause is ChoiceFallbackCause.VERIFIED_READ_ONLY_MISS
    assert event.selected_branch_id == "branch_b"
    assert "content excluded" not in json.dumps(event.to_payload())
    assert compile_next_leaf(projected, sequence=4).boundary.node_id == "observe_b"  # type: ignore[union-attr]


def test_fallback_all_remaining_false_is_known_terminal_choice_failure() -> None:
    selected = _initial(_tree())
    fresh = _snapshot(a=False, b=False, c=False)
    fallback = build_pre_boundary_false_fallback(
        selected,
        choice_node_id="choice",
        condition=FactCondition("gate_a", "gate_a", FactType.BOOLEAN, True),
        snapshot=fresh,
        context=_context(),
    )
    event = evaluate_choice_event(
        selected,
        source_sequence=1,
        choice_node_id="choice",
        conditions=_gates("gate_b", "gate_c"),
        snapshot=fresh,
        context=_context(),
        fallback=fallback,
    )
    projected = apply_choice_event(selected, event)

    assert event.disposition is ChoiceDisposition.FAILED
    assert event.selected_branch_id is None
    assert projected.status is PlanStepStatus.FAILED


def test_context_drift_missing_verification_and_side_effects_fail_closed() -> None:
    selected = _initial(_tree())
    with pytest.raises(ChoiceEvaluationError, match="FRESH_FALSE"):
        build_pre_boundary_false_fallback(
            selected,
            choice_node_id="choice",
            condition=FactCondition("gate_a", "gate_a", FactType.BOOLEAN, True),
            snapshot=_snapshot(a=False),
            context=_context(epoch=4),
        )

    side_effect = _completed_observation(_initial(_tree(side_effect_branch="branch_a")))
    with pytest.raises(ChoiceEvaluationError, match="NOT_READ_ONLY"):
        build_verified_read_only_miss_fallback(
            side_effect,
            choice_node_id="choice",
            observation_node_id="observe_a",
            verification_node_id="verify_a",
            observation_evidence=_evidence("miss_a"),
            condition=FactCondition("miss_a", "miss_a", FactType.BOOLEAN, True),
            snapshot=_snapshot(miss_a=False),
            context=_context(),
        )


def test_denial_authority_policy_budget_cancel_unknown_and_side_effect_stop() -> None:
    eligible = {
        ChoiceBoundaryOutcome.PRE_BOUNDARY_FALSE,
        ChoiceBoundaryOutcome.VERIFIED_READ_ONLY_MISS,
    }
    assert {
        outcome
        for outcome in ChoiceBoundaryOutcome
        if choice_boundary_allows_fallback(outcome)
    } == eligible


def test_first_selection_is_persisted_and_never_reselected_on_context_drift(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        committed = evaluate_and_commit_choice(
            store,
            "run_1",
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
            choice_node_id="choice",
            conditions=_gates("gate_a", "gate_b", "gate_c"),
            snapshot=_snapshot(),
            context=_context(),
        )
        assert committed.persisted is not None
        assert committed.persisted.tree.choice_events == (committed.event,)
        with pytest.raises(ChoiceEvaluationError, match="FALLBACK_INVALID"):
            evaluate_choice_event(
                committed.persisted.tree,
                source_sequence=committed.persisted.sequence,
                choice_node_id="choice",
                conditions=_gates("gate_b", "gate_c"),
                snapshot=_snapshot(a=False),
                context=_context(epoch=4),
            )
    finally:
        lock.release()

    lock.acquire()
    try:
        restarted = TaskTreeStore(store.state_dir, lock).read("run_1")
        assert restarted == committed.persisted
    finally:
        lock.release()


def test_evaluator_exception_and_cas_conflict_leave_exact_store_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        path = task_tree_path(store.state_dir, "run_1")
        before = path.read_bytes()
        original = choice_module.evaluate_fact_condition

        def explode(*args: object, **kwargs: object) -> ConditionEvaluation:
            raise RuntimeError("injected choice evaluator failure")

        monkeypatch.setattr(choice_module, "evaluate_fact_condition", explode)
        with pytest.raises(RuntimeError, match="injected choice evaluator failure"):
            evaluate_and_commit_choice(
                store,
                "run_1",
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
                choice_node_id="choice",
                conditions=_gates("gate_a", "gate_b", "gate_c"),
                snapshot=_snapshot(),
                context=_context(),
            )
        assert path.read_bytes() == before

        monkeypatch.setattr(choice_module, "evaluate_fact_condition", original)

        def conflict(*args: object, **kwargs: object) -> object:
            raise TreeStoreError("TREE_STORE_STALE_WRITE")

        monkeypatch.setattr(store, "compare_and_swap", conflict)
        with pytest.raises(TreeStoreError, match="TREE_STORE_STALE_WRITE"):
            evaluate_and_commit_choice(
                store,
                "run_1",
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
                choice_node_id="choice",
                conditions=_gates("gate_a", "gate_b", "gate_c"),
                snapshot=_snapshot(),
                context=_context(),
            )
        assert path.read_bytes() == before
    finally:
        lock.release()

def test_v4_contract_shape_digest_and_cross_version_fields_are_strict(tmp_path: Path) -> None:
    tree = _tree()
    payload = tree.to_payload()

    assert payload["choice_events"] == []
    assert payload["dependencies"] == []
    assert tree.digest == "6c892300984b149db9e289c7ec01a14ff962883242e417b1eeb2d0dd83a3ad3b"
    with pytest.raises(TreeValidationError, match="v3 cannot carry H8C"):
        replace(_initial(tree), contract_version=3)

    store, lock = _locked_store(tmp_path)
    try:
        store.create(tree)
        path = task_tree_path(store.state_dir, "run_1")
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["tree"]["choice_events"] = [{"invalid": True}]
        _resign(saved)
        path.write_bytes(_canonical(saved) + b"\n")
        with pytest.raises(TreeStoreError, match="TREE_STORE_INVALID"):
            store.read("run_1")
    finally:
        lock.release()


def test_resigned_selection_tamper_fails_semantic_restart_decode(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        committed = evaluate_and_commit_choice(
            store,
            "run_1",
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
            choice_node_id="choice",
            conditions=_gates("gate_a", "gate_b", "gate_c"),
            snapshot=_snapshot(),
            context=_context(),
        )
        assert committed.persisted is not None
        path = task_tree_path(store.state_dir, "run_1")
        saved = json.loads(path.read_text(encoding="utf-8"))
        saved["tree"]["choice_events"][0]["selected_branch_id"] = "branch_c"
        _resign(saved)
        path.write_bytes(_canonical(saved) + b"\n")

        with pytest.raises(TreeStoreError, match="TREE_STORE_INVALID"):
            store.read("run_1")
    finally:
        lock.release()


def test_invalid_choice_shapes_and_direct_transition_fail_closed() -> None:
    tree = _tree()
    by_id = {node.node_id: node for node in tree.nodes}
    bad_branch = replace(by_id["branch_a"], child_ids=("observe_a", "gate_a", "verify_a"))
    with pytest.raises(TreeValidationError, match="start with conditions"):
        replace(tree, nodes=tuple(bad_branch if node.node_id == "branch_a" else node for node in tree.nodes))

    tick = compile_next_leaf(tree, sequence=0)
    assert tick.disposition is TreeTickDisposition.BLOCKED
    with pytest.raises(TreeCompileError, match="TREE_TRANSITION_OUT_OF_ORDER"):
        transition_tree_leaf(tree, "observe_a", PlanStepStatus.IN_PROGRESS)
