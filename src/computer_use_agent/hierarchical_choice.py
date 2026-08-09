"""H8C safe ordered choice and exact read-only fallback evaluation.

All concurrency is local H5 computation. This module has no provider, Runner,
MCP, desktop, approval, retry, replay, script, or dispatch port.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Mapping

from .hierarchical_choice_contract import (
    MAX_CHOICE_WORKERS,
    ChoiceDisposition,
    ChoiceEvent,
    ChoiceFallbackCause,
    ChoiceFallbackEvidence,
    ChoiceGateResult,
)
from .hierarchical_control import (
    TREE_CONTRACT_VERSION_V4,
    TaskTree,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
    reduce_tree_statuses,
)
from .hierarchical_parallel import world_state_context_digest
from .planning import PlanStepStatus
from .tree_store import PersistedTaskTree, TaskTreeStore, TreeStoreError
from .world_state import (
    ConditionEvaluation,
    ConditionOutcome,
    FactCondition,
    ObservationEvidence,
    WorldStateContext,
    WorldStateSnapshot,
    evaluate_fact_condition,
)


class ChoiceEvaluationError(RuntimeError):
    """Fixed H8C failure without task, fact, or observation content."""


@dataclass(frozen=True)
class ChoiceCommit:
    event: ChoiceEvent
    persisted: PersistedTaskTree | None

    def __post_init__(self) -> None:
        if not isinstance(self.event, ChoiceEvent):
            raise ChoiceEvaluationError("CHOICE_RESULT_INVALID")
        if self.event.disposition is ChoiceDisposition.BLOCKED:
            if self.persisted is not None:
                raise ChoiceEvaluationError("CHOICE_RESULT_INVALID")
        elif not isinstance(self.persisted, PersistedTaskTree):
            raise ChoiceEvaluationError("CHOICE_RESULT_INVALID")


def _choice(tree: TaskTree, choice_node_id: str) -> tuple[TreeNode, tuple[TreeNode, ...]]:
    if not isinstance(tree, TaskTree) or tree.contract_version != TREE_CONTRACT_VERSION_V4:
        raise ChoiceEvaluationError("CHOICE_TREE_INVALID")
    by_id = {node.node_id: node for node in tree.nodes}
    choice = by_id.get(choice_node_id)
    if choice is None or choice.kind is not TreeNodeKind.CHOICE:
        raise ChoiceEvaluationError("CHOICE_NODE_INVALID")
    return choice, tuple(by_id[branch_id] for branch_id in choice.child_ids)


def _selected_branch(tree: TaskTree, choice_node_id: str) -> TreeNode:
    _, branches = _choice(tree, choice_node_id)
    if not tree.choice_events:
        raise ChoiceEvaluationError("CHOICE_NOT_SELECTED")
    branch_id = tree.choice_events[-1].selected_branch_id
    branch = next((item for item in branches if item.node_id == branch_id), None)
    if branch is None:
        raise ChoiceEvaluationError("CHOICE_TERMINAL")
    return branch


def _descendants(tree: TaskTree, root: TreeNode) -> tuple[TreeNode, ...]:
    by_id = {node.node_id: node for node in tree.nodes}
    found: list[TreeNode] = []
    stack = list(root.child_ids)
    while stack:
        node = by_id[stack.pop()]
        found.append(node)
        stack.extend(node.child_ids)
    return tuple(found)


def _fresh_false(
    snapshot: WorldStateSnapshot,
    condition: FactCondition,
    context: WorldStateContext,
) -> ConditionEvaluation:
    evaluation = evaluate_fact_condition(snapshot, condition, context)
    if evaluation.outcome is not ConditionOutcome.FALSE:
        raise ChoiceEvaluationError("CHOICE_FALLBACK_REQUIRES_FRESH_FALSE")
    if evaluation.fact_digest is None or evaluation.evidence_digest is None:
        raise ChoiceEvaluationError("CHOICE_FALLBACK_REQUIRES_FRESH_FALSE")
    return evaluation


def build_pre_boundary_false_fallback(
    tree: TaskTree,
    *,
    choice_node_id: str,
    condition: FactCondition,
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
) -> ChoiceFallbackEvidence:
    """Build fallback evidence only while the selected branch has done no work."""

    branch = _selected_branch(tree, choice_node_id)
    by_id = {node.node_id: node for node in tree.nodes}
    gate = by_id[branch.child_ids[0]]
    body = tuple(node for node in _descendants(tree, branch) if node.node_id != gate.node_id)
    if (
        gate.condition_id != condition.condition_id
        or gate.status is not PlanStepStatus.COMPLETED
        or any(node.status is not PlanStepStatus.PENDING for node in body)
    ):
        raise ChoiceEvaluationError("CHOICE_FALLBACK_NOT_PRE_BOUNDARY")
    evaluation = _fresh_false(snapshot, condition, context)
    return ChoiceFallbackEvidence(
        cause=ChoiceFallbackCause.PRE_BOUNDARY_FALSE,
        source_branch_id=branch.node_id,
        failure_node_id=gate.node_id,
        condition_id=evaluation.condition_id,
        condition_digest=evaluation.condition_digest,
        fact_digest=evaluation.fact_digest or "",
        evidence_digest=evaluation.evidence_digest or "",
    )


def build_verified_read_only_miss_fallback(
    tree: TaskTree,
    *,
    choice_node_id: str,
    observation_node_id: str,
    verification_node_id: str,
    observation_evidence: ObservationEvidence,
    condition: FactCondition,
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
) -> ChoiceFallbackEvidence:
    """Build fallback evidence for one successful observation and fresh miss."""

    branch = _selected_branch(tree, choice_node_id)
    descendants = _descendants(tree, branch)
    by_id = {node.node_id: node for node in descendants}
    observation = by_id.get(observation_node_id)
    verification = by_id.get(verification_node_id)
    if (
        not isinstance(observation_evidence, ObservationEvidence)
        or observation_evidence.identity.run_id != tree.run_id
        or observation is None
        or observation.kind not in {TreeNodeKind.TOOL_STEP, TreeNodeKind.SUBTREE}
        or observation.status is not PlanStepStatus.COMPLETED
        or verification is None
        or verification.kind is not TreeNodeKind.VERIFY
        or verification.verification_id != condition.condition_id
        or verification.status
        not in {PlanStepStatus.PENDING, PlanStepStatus.IN_PROGRESS}
        or any(node.budget.side_effects for node in descendants)
    ):
        raise ChoiceEvaluationError("CHOICE_FALLBACK_NOT_READ_ONLY")
    evaluation = _fresh_false(snapshot, condition, context)
    if evaluation.evidence_digest != observation_evidence.evidence_digest:
        raise ChoiceEvaluationError("CHOICE_FALLBACK_OBSERVATION_MISMATCH")
    return ChoiceFallbackEvidence(
        cause=ChoiceFallbackCause.VERIFIED_READ_ONLY_MISS,
        source_branch_id=branch.node_id,
        failure_node_id=verification.node_id,
        condition_id=evaluation.condition_id,
        condition_digest=evaluation.condition_digest,
        fact_digest=evaluation.fact_digest or "",
        evidence_digest=evaluation.evidence_digest or "",
        observation_node_id=observation.node_id,
        observation_evidence_digest=observation_evidence.evidence_digest,
    )


def evaluate_choice_event(
    tree: TaskTree,
    *,
    source_sequence: int,
    choice_node_id: str,
    conditions: Mapping[str, FactCondition],
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
    fallback: ChoiceFallbackEvidence | None = None,
) -> ChoiceEvent:
    """Evaluate all candidate gates concurrently, then select in Host order."""

    if (
        isinstance(source_sequence, bool)
        or not isinstance(source_sequence, int)
        or source_sequence < 0
        or not isinstance(conditions, Mapping)
        or not isinstance(snapshot, WorldStateSnapshot)
        or not isinstance(context, WorldStateContext)
        or tree.run_id != snapshot.run_id
        or tree.run_id != context.run_id
    ):
        raise ChoiceEvaluationError("CHOICE_INPUT_INVALID")
    choice, branches = _choice(tree, choice_node_id)
    by_id = {node.node_id: node for node in tree.nodes}
    if not tree.choice_events:
        if fallback is not None:
            raise ChoiceEvaluationError("CHOICE_FALLBACK_INVALID")
        candidates = branches
    else:
        selected = _selected_branch(tree, choice_node_id)
        if fallback is None or fallback.source_branch_id != selected.node_id:
            raise ChoiceEvaluationError("CHOICE_FALLBACK_INVALID")
        selected_index = choice.child_ids.index(selected.node_id)
        candidates = branches[selected_index + 1 :]

    gates = tuple(by_id[branch.child_ids[0]] for branch in candidates)
    expected_condition_ids = {gate.condition_id for gate in gates}
    if (
        None in expected_condition_ids
        or set(conditions) != expected_condition_ids
        or not all(
            isinstance(condition, FactCondition)
            and condition.condition_id == condition_id
            for condition_id, condition in conditions.items()
        )
    ):
        raise ChoiceEvaluationError("CHOICE_BINDING_INVALID")

    def evaluate(pair: tuple[TreeNode, TreeNode]) -> ChoiceGateResult:
        branch, gate = pair
        condition_id = gate.condition_id
        if condition_id is None:
            raise ChoiceEvaluationError("CHOICE_BINDING_INVALID")
        evaluation = evaluate_fact_condition(snapshot, conditions[condition_id], context)
        return ChoiceGateResult(
            branch_id=branch.node_id,
            condition_node_id=gate.node_id,
            condition_id=evaluation.condition_id,
            outcome=evaluation.outcome,
            availability=evaluation.availability,
            condition_digest=evaluation.condition_digest,
            fact_digest=evaluation.fact_digest,
            evidence_digest=evaluation.evidence_digest,
        )

    pairs = tuple(zip(candidates, gates))
    if pairs:
        with ThreadPoolExecutor(
            max_workers=min(MAX_CHOICE_WORKERS, len(pairs)),
            thread_name_prefix="h8c-choice",
        ) as executor:
            futures = tuple(executor.submit(evaluate, pair) for pair in pairs)
            results = tuple(future.result() for future in futures)
    else:
        results = ()

    selected_branch_id: str | None = None
    disposition = ChoiceDisposition.FAILED
    for result in results:
        if result.outcome is ConditionOutcome.UNAVAILABLE:
            disposition = ChoiceDisposition.BLOCKED
            break
        if result.outcome is ConditionOutcome.TRUE:
            selected_branch_id = result.branch_id
            disposition = ChoiceDisposition.SELECTED
            break
    return ChoiceEvent(
        choice_node_id=choice.node_id,
        source_sequence=source_sequence,
        source_tree_digest=tree.digest,
        snapshot_digest=snapshot.digest,
        context_digest=world_state_context_digest(context),
        disposition=disposition,
        selected_branch_id=selected_branch_id,
        fallback=fallback,
        results=results,
    )


def apply_choice_event(tree: TaskTree, event: ChoiceEvent) -> TaskTree:
    """Atomically project one known choice/fallback event into tree state."""

    if (
        not isinstance(tree, TaskTree)
        or not isinstance(event, ChoiceEvent)
        or event.disposition is ChoiceDisposition.BLOCKED
        or event.source_tree_digest != tree.digest
    ):
        raise ChoiceEvaluationError("CHOICE_EVENT_INVALID")
    statuses: dict[str, PlanStepStatus] = {}
    if event.fallback is not None:
        statuses[event.fallback.failure_node_id] = PlanStepStatus.FAILED
    for result in event.results:
        if result.outcome is ConditionOutcome.FALSE:
            statuses[result.condition_node_id] = PlanStepStatus.FAILED
            continue
        if result.outcome is ConditionOutcome.TRUE:
            statuses[result.condition_node_id] = PlanStepStatus.COMPLETED
            break
    try:
        return reduce_tree_statuses(
            tree,
            statuses,
            choice_events=(*tree.choice_events, event),
        )
    except TreeValidationError as exc:
        raise ChoiceEvaluationError("CHOICE_EVENT_INVALID") from exc


def evaluate_and_commit_choice(
    store: TaskTreeStore,
    run_id: str,
    *,
    expected_sequence: int,
    expected_tree_digest: str,
    choice_node_id: str,
    conditions: Mapping[str, FactCondition],
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
    fallback: ChoiceFallbackEvidence | None = None,
) -> ChoiceCommit:
    """Compute one complete event, then perform zero or one existing-store CAS."""

    if not isinstance(store, TaskTreeStore):
        raise ChoiceEvaluationError("CHOICE_STORE_INVALID")
    current = store.read(run_id)
    if (
        current.sequence != expected_sequence
        or current.tree.digest != expected_tree_digest
    ):
        raise TreeStoreError("TREE_STORE_STALE_WRITE")
    event = evaluate_choice_event(
        current.tree,
        source_sequence=current.sequence,
        choice_node_id=choice_node_id,
        conditions=conditions,
        snapshot=snapshot,
        context=context,
        fallback=fallback,
    )
    if event.disposition is ChoiceDisposition.BLOCKED:
        return ChoiceCommit(event=event, persisted=None)
    updated = apply_choice_event(current.tree, event)
    persisted = store.compare_and_swap(
        run_id,
        updated,
        expected_sequence=current.sequence,
        expected_tree_digest=current.tree.digest,
    )
    return ChoiceCommit(event=event, persisted=persisted)


__all__ = [
    "ChoiceCommit",
    "ChoiceEvaluationError",
    "apply_choice_event",
    "build_pre_boundary_false_fallback",
    "build_verified_read_only_miss_fallback",
    "evaluate_and_commit_choice",
    "evaluate_choice_event",
]
