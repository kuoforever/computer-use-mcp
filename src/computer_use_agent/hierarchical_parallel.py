"""H8A bounded parallel evaluation of typed H5 condition leaves.

The only concurrency here is pure, local evaluation over one immutable world
snapshot and context. The module has no provider, Runner, MCP, desktop,
approval, script, retry, replay, or dispatch port. A complete known batch is
committed as one tree-store CAS; unavailable evidence leaves the tree unchanged.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Mapping

from .hierarchical_control import (
    TREE_CONTRACT_VERSION_V2,
    TaskTree,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
    reduce_tree_statuses,
)
from .hierarchical_parallel_contract import (
    MAX_PARALLEL_WORKERS,
    ParallelBatchDisposition,
    ParallelConditionBatch,
    ParallelConditionResult,
)
from .planning import PlanStepStatus
from .tree_store import PersistedTaskTree, TaskTreeStore, TreeStoreError
from .world_state import (
    ConditionOutcome,
    FactCondition,
    WorldStateContext,
    WorldStateSnapshot,
    evaluate_fact_condition,
)


class ParallelConditionError(RuntimeError):
    """Fixed, content-free H8A evaluation failure."""


@dataclass(frozen=True)
class ParallelConditionCommit:
    """One complete batch and its optional single-CAS persisted snapshot."""

    batch: ParallelConditionBatch
    persisted: PersistedTaskTree | None

    def __post_init__(self) -> None:
        if not isinstance(self.batch, ParallelConditionBatch):
            raise ParallelConditionError("PARALLEL_CONDITION_RESULT_INVALID")
        if self.batch.disposition is ParallelBatchDisposition.BLOCKED:
            if self.persisted is not None:
                raise ParallelConditionError("PARALLEL_CONDITION_RESULT_INVALID")
        elif not isinstance(self.persisted, PersistedTaskTree):
            raise ParallelConditionError("PARALLEL_CONDITION_RESULT_INVALID")


def world_state_context_digest(context: WorldStateContext) -> str:
    """Return a content-free digest for the exact H5 consumption context."""

    if not isinstance(context, WorldStateContext):
        raise ParallelConditionError("PARALLEL_CONDITION_CONTEXT_INVALID")
    payload = {
        "run_id": context.run_id,
        "observation_epoch": context.observation_epoch,
        "mcp_generation": context.mcp_generation,
        "now_ms": context.now_ms,
        "window_digest": None if context.window is None else context.window.digest,
    }
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _parallel_node(tree: TaskTree, parallel_node_id: str) -> tuple[TreeNode, ...]:
    if not isinstance(tree, TaskTree) or tree.contract_version != TREE_CONTRACT_VERSION_V2:
        raise ParallelConditionError("PARALLEL_CONDITION_TREE_INVALID")
    node = next((item for item in tree.nodes if item.node_id == parallel_node_id), None)
    if node is None or node.kind is not TreeNodeKind.PARALLEL:
        raise ParallelConditionError("PARALLEL_CONDITION_NODE_INVALID")
    by_id = {item.node_id: item for item in tree.nodes}
    children = tuple(by_id[child_id] for child_id in node.child_ids)
    if node.status is not PlanStepStatus.PENDING or any(
        child.status is not PlanStepStatus.PENDING for child in children
    ):
        raise ParallelConditionError("PARALLEL_CONDITION_STATE_INVALID")
    return children


def evaluate_parallel_conditions(
    tree: TaskTree,
    *,
    source_sequence: int,
    parallel_node_id: str,
    conditions: Mapping[str, FactCondition],
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
) -> ParallelConditionBatch:
    """Evaluate every direct condition leaf before constructing one result."""

    if (
        isinstance(source_sequence, bool)
        or not isinstance(source_sequence, int)
        or source_sequence < 0
        or not isinstance(conditions, Mapping)
        or not isinstance(snapshot, WorldStateSnapshot)
        or not isinstance(context, WorldStateContext)
    ):
        raise ParallelConditionError("PARALLEL_CONDITION_INPUT_INVALID")
    if tree.run_id != snapshot.run_id or tree.run_id != context.run_id:
        raise ParallelConditionError("PARALLEL_CONDITION_RUN_MISMATCH")
    children = _parallel_node(tree, parallel_node_id)
    condition_ids = tuple(child.condition_id for child in children)
    if any(condition_id is None for condition_id in condition_ids) or set(
        conditions
    ) != set(condition_ids):
        raise ParallelConditionError("PARALLEL_CONDITION_BINDING_INVALID")
    if not all(
        isinstance(condition, FactCondition)
        and condition.condition_id == condition_id
        for condition_id, condition in conditions.items()
    ):
        raise ParallelConditionError("PARALLEL_CONDITION_BINDING_INVALID")

    ordered = tuple(sorted(children, key=lambda child: child.node_id))

    def evaluate(child: TreeNode) -> ParallelConditionResult:
        condition_id = child.condition_id
        if condition_id is None:
            raise ParallelConditionError("PARALLEL_CONDITION_BINDING_INVALID")
        evaluation = evaluate_fact_condition(snapshot, conditions[condition_id], context)
        return ParallelConditionResult(
            node_id=child.node_id,
            condition_id=evaluation.condition_id,
            outcome=evaluation.outcome,
            availability=evaluation.availability,
            condition_digest=evaluation.condition_digest,
            fact_digest=evaluation.fact_digest,
            evidence_digest=evaluation.evidence_digest,
        )

    with ThreadPoolExecutor(
        max_workers=min(MAX_PARALLEL_WORKERS, len(ordered)),
        thread_name_prefix="h8a-condition",
    ) as executor:
        futures = tuple(executor.submit(evaluate, child) for child in ordered)
        results = tuple(future.result() for future in futures)

    outcomes = tuple(result.outcome for result in results)
    disposition = (
        ParallelBatchDisposition.FAILED
        if ConditionOutcome.FALSE in outcomes
        else ParallelBatchDisposition.BLOCKED
        if ConditionOutcome.UNAVAILABLE in outcomes
        else ParallelBatchDisposition.COMPLETED
    )
    return ParallelConditionBatch(
        parallel_node_id=parallel_node_id,
        source_sequence=source_sequence,
        source_tree_digest=tree.digest,
        snapshot_digest=snapshot.digest,
        context_digest=world_state_context_digest(context),
        results=results,
        disposition=disposition,
    )


def apply_parallel_condition_batch(
    tree: TaskTree, batch: ParallelConditionBatch
) -> TaskTree:
    """Project one complete known batch into leaf state and immutable evidence."""

    if not isinstance(tree, TaskTree) or not isinstance(batch, ParallelConditionBatch):
        raise ParallelConditionError("PARALLEL_CONDITION_INPUT_INVALID")
    if (
        batch.disposition is ParallelBatchDisposition.BLOCKED
        or batch.source_tree_digest != tree.digest
        or any(
            existing.parallel_node_id == batch.parallel_node_id
            for existing in tree.parallel_batches
        )
    ):
        raise ParallelConditionError("PARALLEL_CONDITION_BATCH_INVALID")
    children = _parallel_node(tree, batch.parallel_node_id)
    results = {item.node_id: item for item in batch.results}
    if set(results) != {child.node_id for child in children} or any(
        results[child.node_id].condition_id != child.condition_id for child in children
    ):
        raise ParallelConditionError("PARALLEL_CONDITION_BINDING_INVALID")
    statuses = {
        result.node_id: (
            PlanStepStatus.COMPLETED
            if result.outcome is ConditionOutcome.TRUE
            else PlanStepStatus.FAILED
            if result.outcome is ConditionOutcome.FALSE
            else PlanStepStatus.PENDING
        )
        for result in batch.results
    }
    projected = reduce_tree_statuses(tree, statuses)
    try:
        return replace(
            projected,
            parallel_batches=tuple(
                sorted(
                    (*tree.parallel_batches, batch),
                    key=lambda item: item.parallel_node_id,
                )
            ),
        )
    except TreeValidationError as exc:
        raise ParallelConditionError("PARALLEL_CONDITION_BATCH_INVALID") from exc


def evaluate_and_commit_parallel_conditions(
    store: TaskTreeStore,
    run_id: str,
    *,
    expected_sequence: int,
    expected_tree_digest: str,
    parallel_node_id: str,
    conditions: Mapping[str, FactCondition],
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
) -> ParallelConditionCommit:
    """Compute one full batch, then perform zero or one existing-store CAS."""

    if not isinstance(store, TaskTreeStore):
        raise ParallelConditionError("PARALLEL_CONDITION_STORE_INVALID")
    current = store.read(run_id)
    if (
        current.sequence != expected_sequence
        or current.tree.digest != expected_tree_digest
    ):
        raise TreeStoreError("TREE_STORE_STALE_WRITE")
    batch = evaluate_parallel_conditions(
        current.tree,
        source_sequence=current.sequence,
        parallel_node_id=parallel_node_id,
        conditions=conditions,
        snapshot=snapshot,
        context=context,
    )
    if batch.disposition is ParallelBatchDisposition.BLOCKED:
        return ParallelConditionCommit(batch=batch, persisted=None)
    updated = apply_parallel_condition_batch(current.tree, batch)
    persisted = store.compare_and_swap(
        run_id,
        updated,
        expected_sequence=current.sequence,
        expected_tree_digest=current.tree.digest,
    )
    return ParallelConditionCommit(batch=batch, persisted=persisted)


__all__ = [
    "ParallelConditionCommit",
    "ParallelConditionError",
    "apply_parallel_condition_batch",
    "evaluate_and_commit_parallel_conditions",
    "evaluate_parallel_conditions",
    "world_state_context_digest",
]
