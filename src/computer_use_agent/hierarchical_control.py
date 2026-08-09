"""Pure H1 hierarchical task-tree contract.

The types in this module are immutable, versioned, and deliberately inert.
They do not persist state, select executable calls, dispatch through Runner or
MCP, or grant policy, approval, retry, or replay authority.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from hashlib import sha256
from typing import Mapping, Sequence

from .hierarchical_choice_contract import (
    MAX_CHOICE_BRANCHES,
    MIN_CHOICE_BRANCHES,
    ChoiceDisposition,
    ChoiceEvent,
    ChoiceFallbackCause,
)
from .hierarchical_graph_contract import (
    MAX_TREE_DEPENDENCIES,
    MAX_TREE_DEPENDENCY_FAN_IN,
    MAX_TREE_GRAPH_DEPTH,
    TreeDependency,
)
from .hierarchical_parallel_contract import (
    MAX_PARALLEL_CONDITIONS,
    MIN_PARALLEL_CONDITIONS,
    ParallelBatchDisposition,
    ParallelConditionBatch,
)
from .planning import PlanStepAction, PlanStepStatus, TaskPlan
from .types import ToolEffect
from .world_state import ConditionOutcome


TREE_CONTRACT_VERSION = 1
TREE_CONTRACT_VERSION_V2 = 2
TREE_CONTRACT_VERSION_V3 = 3
TREE_CONTRACT_VERSION_V4 = 4
SUPPORTED_TREE_CONTRACT_VERSIONS = frozenset(
    {
        TREE_CONTRACT_VERSION,
        TREE_CONTRACT_VERSION_V2,
        TREE_CONTRACT_VERSION_V3,
        TREE_CONTRACT_VERSION_V4,
    }
)
MAX_TREE_NODES = 128
MAX_TREE_DEPTH = 12
MAX_TREE_CHILDREN = 32
MAX_TREE_VISITS = 1_024
MAX_TREE_WALL_CLOCK_SECONDS = 86_400
MAX_TREE_TOOL_CALLS = 64
MAX_TREE_TOKENS = 1_000_000
MAX_TREE_SIDE_EFFECTS = 32
MAX_TREE_RETRIES = 16
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class TreeValidationError(ValueError):
    """Fixed, content-free failure for an invalid hierarchical contract."""


class TreeNodeKind(str, Enum):
    GOAL = "goal"
    SEQUENCE = "sequence"
    CHOICE = "choice"
    CONDITION = "condition"
    TOOL_STEP = "tool_step"
    VERIFY = "verify"
    SUBTREE = "subtree"
    FINAL_RESPONSE = "final_response"
    PARALLEL = "parallel"
    JOIN = "join"


_INTERNAL_KINDS = frozenset(
    {
        TreeNodeKind.GOAL,
        TreeNodeKind.SEQUENCE,
        TreeNodeKind.CHOICE,
        TreeNodeKind.PARALLEL,
    }
)


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise TreeValidationError(f"{field_name} is invalid")
    return value


def _require_optional_identifier(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_identifier(value, field_name)


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise TreeValidationError(f"{field_name} must be a SHA-256 digest")
    return value


def _require_int(
    value: object, field_name: str, *, minimum: int, maximum: int
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        raise TreeValidationError(f"{field_name} is outside the reviewed limit")
    return value


@dataclass(frozen=True)
class TreeBudget:
    """Host-owned upper bounds; values are data and grant no authority."""

    tool_calls: int = 0
    tokens: int = 0
    side_effects: int = 0
    retries: int = 0

    def __post_init__(self) -> None:
        _require_int(
            self.tool_calls,
            "tool_calls",
            minimum=0,
            maximum=MAX_TREE_TOOL_CALLS,
        )
        _require_int(self.tokens, "tokens", minimum=0, maximum=MAX_TREE_TOKENS)
        _require_int(
            self.side_effects,
            "side_effects",
            minimum=0,
            maximum=MAX_TREE_SIDE_EFFECTS,
        )
        _require_int(self.retries, "retries", minimum=0, maximum=MAX_TREE_RETRIES)

    def fits_within(self, aggregate: TreeBudget) -> bool:
        return (
            self.tool_calls <= aggregate.tool_calls
            and self.tokens <= aggregate.tokens
            and self.side_effects <= aggregate.side_effects
            and self.retries <= aggregate.retries
        )

    def to_payload(self) -> dict[str, int]:
        return {
            "tool_calls": self.tool_calls,
            "tokens": self.tokens,
            "side_effects": self.side_effects,
            "retries": self.retries,
        }


@dataclass(frozen=True)
class TreeLimits:
    """Structural limits bound into every tree digest."""

    max_depth: int = 8
    max_nodes: int = 64
    max_children: int = 16
    max_visits: int = 256
    max_wall_clock_seconds: int = 3_600

    def __post_init__(self) -> None:
        _require_int(self.max_depth, "max_depth", minimum=1, maximum=MAX_TREE_DEPTH)
        _require_int(self.max_nodes, "max_nodes", minimum=2, maximum=MAX_TREE_NODES)
        _require_int(
            self.max_children,
            "max_children",
            minimum=1,
            maximum=MAX_TREE_CHILDREN,
        )
        _require_int(self.max_visits, "max_visits", minimum=1, maximum=MAX_TREE_VISITS)
        _require_int(
            self.max_wall_clock_seconds,
            "max_wall_clock_seconds",
            minimum=1,
            maximum=MAX_TREE_WALL_CLOCK_SECONDS,
        )

    def to_payload(self) -> dict[str, int]:
        return {
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_children": self.max_children,
            "max_visits": self.max_visits,
            "max_wall_clock_seconds": self.max_wall_clock_seconds,
        }


@dataclass(frozen=True)
class TreeNode:
    """One host-normalized node with no executable payload."""

    node_id: str
    kind: TreeNodeKind
    status: PlanStepStatus = PlanStepStatus.PENDING
    parent_id: str | None = None
    child_ids: tuple[str, ...] = ()
    step_id: str | None = None
    condition_id: str | None = None
    verification_id: str | None = None
    template_id: str | None = None
    template_version: int | None = None
    template_digest: str | None = None
    budget: TreeBudget = field(default_factory=TreeBudget)

    def __post_init__(self) -> None:
        _require_identifier(self.node_id, "node_id")
        _require_optional_identifier(self.parent_id, "parent_id")
        if not isinstance(self.kind, TreeNodeKind):
            raise TreeValidationError("node kind is invalid")
        if not isinstance(self.status, PlanStepStatus):
            raise TreeValidationError("node status is invalid")
        if not isinstance(self.child_ids, tuple) or not all(
            isinstance(item, str) for item in self.child_ids
        ):
            raise TreeValidationError("child_ids must be an immutable identifier tuple")
        if len(self.child_ids) != len(set(self.child_ids)):
            raise TreeValidationError("child_ids contains duplicates")
        for child_id in self.child_ids:
            _require_identifier(child_id, "child_id")
        if not isinstance(self.budget, TreeBudget):
            raise TreeValidationError("node budget is invalid")

        binding_fields = (
            self.step_id,
            self.condition_id,
            self.verification_id,
            self.template_id,
            self.template_version,
            self.template_digest,
        )
        if self.kind in _INTERNAL_KINDS:
            if not self.child_ids:
                raise TreeValidationError("control nodes require children")
            if any(value is not None for value in binding_fields):
                raise TreeValidationError("control nodes cannot carry leaf bindings")
            return

        if self.child_ids:
            raise TreeValidationError("leaf nodes cannot have children")
        if self.kind in {TreeNodeKind.TOOL_STEP, TreeNodeKind.FINAL_RESPONSE}:
            _require_identifier(self.step_id, "step_id")
            if any(
                value is not None
                for value in (
                    self.condition_id,
                    self.verification_id,
                    self.template_id,
                    self.template_version,
                    self.template_digest,
                )
            ):
                raise TreeValidationError("step nodes contain conflicting bindings")
        elif self.kind is TreeNodeKind.CONDITION:
            _require_identifier(self.condition_id, "condition_id")
            if any(
                value is not None
                for value in (
                    self.step_id,
                    self.verification_id,
                    self.template_id,
                    self.template_version,
                    self.template_digest,
                )
            ):
                raise TreeValidationError("condition node contains conflicting bindings")
        elif self.kind is TreeNodeKind.VERIFY:
            _require_identifier(self.verification_id, "verification_id")
            if any(
                value is not None
                for value in (
                    self.step_id,
                    self.condition_id,
                    self.template_id,
                    self.template_version,
                    self.template_digest,
                )
            ):
                raise TreeValidationError("verify node contains conflicting bindings")
        elif self.kind is TreeNodeKind.SUBTREE:
            _require_identifier(self.template_id, "template_id")
            _require_digest(self.template_digest, "template_digest")
            _require_int(
                self.template_version,
                "template_version",
                minimum=1,
                maximum=2_147_483_647,
            )
            if any(
                value is not None
                for value in (self.step_id, self.condition_id, self.verification_id)
            ):
                raise TreeValidationError("subtree node contains conflicting bindings")
        elif self.kind is TreeNodeKind.JOIN:
            if any(value is not None for value in binding_fields):
                raise TreeValidationError("join node cannot carry leaf bindings")

    @property
    def is_leaf(self) -> bool:
        return self.kind not in _INTERNAL_KINDS

    def to_payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "kind": self.kind.value,
            "status": self.status.value,
            "child_ids": list(self.child_ids),
            "step_id": self.step_id,
            "condition_id": self.condition_id,
            "verification_id": self.verification_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_digest": self.template_digest,
            "budget": self.budget.to_payload(),
        }


def reduce_child_statuses(statuses: Sequence[PlanStepStatus]) -> PlanStepStatus:
    """Apply the accepted total parent-state precedence to child evidence."""

    if isinstance(statuses, (str, bytes)) or not isinstance(statuses, Sequence):
        raise TreeValidationError("child statuses must be an explicit sequence")
    values = tuple(statuses)
    if not 1 <= len(values) <= MAX_TREE_CHILDREN or not all(
        isinstance(value, PlanStepStatus) for value in values
    ):
        raise TreeValidationError("child statuses are outside the reviewed contract")
    if PlanStepStatus.FAILED in values:
        return PlanStepStatus.FAILED
    if PlanStepStatus.BLOCKED in values:
        return PlanStepStatus.BLOCKED
    if PlanStepStatus.CANCELLED in values:
        return PlanStepStatus.CANCELLED
    if all(value is PlanStepStatus.COMPLETED for value in values):
        return PlanStepStatus.COMPLETED
    if any(
        value in {PlanStepStatus.IN_PROGRESS, PlanStepStatus.COMPLETED}
        for value in values
    ):
        return PlanStepStatus.IN_PROGRESS
    return PlanStepStatus.PENDING


def _validate_acyclic_graph(
    node_ids: frozenset[str], edges: set[tuple[str, str]], *, label: str
) -> None:
    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    indegree = {node_id: 0 for node_id in node_ids}
    for source, target in edges:
        if target not in adjacency[source]:
            adjacency[source].add(target)
            indegree[target] += 1
    ready = sorted(node_id for node_id, degree in indegree.items() if degree == 0)
    depths = {node_id: 1 for node_id in ready}
    visited = 0
    while ready:
        node_id = ready.pop(0)
        visited += 1
        node_depth = depths[node_id]
        if node_depth > MAX_TREE_GRAPH_DEPTH:
            raise TreeValidationError(f"{label} depth exceeds bound limits")
        for target in sorted(adjacency[node_id]):
            depths[target] = max(depths.get(target, 1), node_depth + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)
                ready.sort()
    if visited != len(node_ids):
        raise TreeValidationError(f"{label} contains a cycle")


def _validate_dependency_graph(
    by_id: Mapping[str, TreeNode], dependencies: tuple[TreeDependency, ...]
) -> None:
    if not 1 <= len(dependencies) <= MAX_TREE_DEPENDENCIES:
        raise TreeValidationError("dependency count is outside bound limits")
    if dependencies != tuple(sorted(dependencies)):
        raise TreeValidationError("dependencies are not canonical")
    if len(set(dependencies)) != len(dependencies):
        raise TreeValidationError("dependencies contain duplicates")
    incoming: dict[str, list[str]] = {}
    dependency_edges: set[tuple[str, str]] = set()
    for dependency in dependencies:
        if (
            dependency.prerequisite_id not in by_id
            or dependency.dependent_id not in by_id
        ):
            raise TreeValidationError("dependency node binding is invalid")
        if not by_id[dependency.dependent_id].is_leaf:
            raise TreeValidationError("dependency dependent must be a leaf node")
        incoming.setdefault(dependency.dependent_id, []).append(
            dependency.prerequisite_id
        )
        dependency_edges.add(
            (dependency.prerequisite_id, dependency.dependent_id)
        )
    if any(
        len(prerequisites) > MAX_TREE_DEPENDENCY_FAN_IN
        for prerequisites in incoming.values()
    ):
        raise TreeValidationError("dependency fan-in exceeds bound limits")

    join_ids = {
        node.node_id for node in by_id.values() if node.kind is TreeNodeKind.JOIN
    }
    if not join_ids or any(join_id not in incoming for join_id in join_ids):
        raise TreeValidationError("join nodes require dependency prerequisites")

    structural_forward: set[tuple[str, str]] = set()
    structural_reverse: set[tuple[str, str]] = set()
    for node in by_id.values():
        for child_id in node.child_ids:
            structural_forward.add((node.node_id, child_id))
            structural_reverse.add((child_id, node.node_id))
        if node.kind in {TreeNodeKind.GOAL, TreeNodeKind.SEQUENCE}:
            structural_forward.update(zip(node.child_ids, node.child_ids[1:]))
    node_ids = frozenset(by_id)
    _validate_acyclic_graph(
        node_ids,
        structural_forward | dependency_edges,
        label="tree dependency graph",
    )
    _validate_acyclic_graph(
        node_ids,
        structural_reverse | dependency_edges,
        label="tree dependency reduction graph",
    )


@dataclass(frozen=True)
class TaskTree:
    """Canonical immutable H1 tree snapshot; state and limits are not authority."""

    tree_id: str
    run_id: str
    task_digest: str
    registry_digest: str
    policy_digest: str
    root_id: str
    nodes: tuple[TreeNode, ...]
    limits: TreeLimits = field(default_factory=TreeLimits)
    aggregate_budget: TreeBudget = field(default_factory=TreeBudget)
    contract_version: int = TREE_CONTRACT_VERSION
    parallel_batches: tuple[ParallelConditionBatch, ...] = ()
    dependencies: tuple[TreeDependency, ...] = ()
    choice_events: tuple[ChoiceEvent, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.tree_id, "tree_id")
        _require_identifier(self.run_id, "run_id")
        _require_identifier(self.root_id, "root_id")
        _require_digest(self.task_digest, "task_digest")
        _require_digest(self.registry_digest, "registry_digest")
        _require_digest(self.policy_digest, "policy_digest")
        if (
            not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version not in SUPPORTED_TREE_CONTRACT_VERSIONS
        ):
            raise TreeValidationError("tree contract version is unsupported")
        if not isinstance(self.limits, TreeLimits):
            raise TreeValidationError("tree limits are invalid")
        if not isinstance(self.aggregate_budget, TreeBudget):
            raise TreeValidationError("aggregate budget is invalid")
        if not isinstance(self.nodes, tuple) or not all(
            isinstance(node, TreeNode) for node in self.nodes
        ):
            raise TreeValidationError("nodes must be an immutable TreeNode tuple")
        if not isinstance(self.parallel_batches, tuple) or not all(
            isinstance(batch, ParallelConditionBatch) for batch in self.parallel_batches
        ):
            raise TreeValidationError("parallel_batches must be immutable H8A evidence")
        if not isinstance(self.dependencies, tuple) or not all(
            isinstance(dependency, TreeDependency) for dependency in self.dependencies
        ):
            raise TreeValidationError("dependencies must be immutable H8B edges")
        if not isinstance(self.choice_events, tuple) or not all(
            isinstance(event, ChoiceEvent) for event in self.choice_events
        ):
            raise TreeValidationError("choice_events must be immutable H8C evidence")
        if not 2 <= len(self.nodes) <= self.limits.max_nodes:
            raise TreeValidationError("tree node count is outside the bound limits")

        ordered = tuple(sorted(self.nodes, key=lambda node: node.node_id))
        object.__setattr__(self, "nodes", ordered)
        by_id = {node.node_id: node for node in ordered}
        if len(by_id) != len(ordered):
            raise TreeValidationError("tree node identifiers must be unique")
        parallel_nodes = tuple(
            node for node in ordered if node.kind is TreeNodeKind.PARALLEL
        )
        join_nodes = tuple(node for node in ordered if node.kind is TreeNodeKind.JOIN)
        choice_nodes = tuple(
            node for node in ordered if node.kind is TreeNodeKind.CHOICE
        )
        if self.contract_version == TREE_CONTRACT_VERSION:
            if (
                parallel_nodes
                or join_nodes
                or self.parallel_batches
                or self.dependencies
                or self.choice_events
            ):
                raise TreeValidationError("tree v1 cannot carry H8 fields")
        elif self.contract_version == TREE_CONTRACT_VERSION_V2:
            if not parallel_nodes:
                raise TreeValidationError("tree v2 requires a parallel node")
            if join_nodes or self.dependencies or self.choice_events:
                raise TreeValidationError("tree v2 cannot carry H8B fields")
        elif self.contract_version == TREE_CONTRACT_VERSION_V3:
            if self.choice_events:
                raise TreeValidationError("tree v3 cannot carry H8C fields")
            if not join_nodes or not self.dependencies:
                raise TreeValidationError("tree v3 requires dependencies and join")
        elif len(choice_nodes) != 1:
            raise TreeValidationError("tree v4 requires exactly one choice node")
        root = by_id.get(self.root_id)
        if root is None or root.parent_id is not None or root.kind not in _INTERNAL_KINDS:
            raise TreeValidationError("tree root is invalid")

        final_nodes = [
            node for node in ordered if node.kind is TreeNodeKind.FINAL_RESPONSE
        ]
        if len(final_nodes) != 1:
            raise TreeValidationError("tree requires exactly one final_response node")

        for node in ordered:
            if len(node.child_ids) > self.limits.max_children:
                raise TreeValidationError("node child count exceeds bound limits")
            if not node.budget.fits_within(self.aggregate_budget):
                raise TreeValidationError("node budget exceeds aggregate budget")
            if node.node_id == self.root_id:
                continue
            parent = by_id.get(node.parent_id or "")
            if parent is None or node.node_id not in parent.child_ids:
                raise TreeValidationError("node parent binding is invalid")

        for parallel in parallel_nodes:
            if (
                not MIN_PARALLEL_CONDITIONS
                <= len(parallel.child_ids)
                <= MAX_PARALLEL_CONDITIONS
                or parallel.child_ids != tuple(sorted(parallel.child_ids))
            ):
                raise TreeValidationError("parallel condition children are not canonical")
            if self.contract_version == TREE_CONTRACT_VERSION_V2:
                children = tuple(by_id.get(child_id) for child_id in parallel.child_ids)
                if any(
                    child is None or child.kind is not TreeNodeKind.CONDITION
                    for child in children
                ):
                    raise TreeValidationError(
                        "tree v2 parallel children must be conditions"
                    )
                condition_ids = tuple(
                    child.condition_id for child in children if child is not None
                )
                if len(set(condition_ids)) != len(condition_ids):
                    raise TreeValidationError(
                        "parallel condition identifiers must be unique"
                    )

        if self.contract_version == TREE_CONTRACT_VERSION_V4:
            choice = choice_nodes[0]
            if not MIN_CHOICE_BRANCHES <= len(choice.child_ids) <= MAX_CHOICE_BRANCHES:
                raise TreeValidationError("choice branch count is outside bound limits")
            branches = tuple(by_id.get(branch_id) for branch_id in choice.child_ids)
            if any(
                branch is None
                or branch.kind is not TreeNodeKind.SEQUENCE
                or len(branch.child_ids) < 2
                for branch in branches
            ):
                raise TreeValidationError("choice branches must be fixed sequences")
            gates = tuple(
                by_id.get(branch.child_ids[0])
                for branch in branches
                if branch is not None
            )
            if any(gate is None or gate.kind is not TreeNodeKind.CONDITION for gate in gates):
                raise TreeValidationError("choice branches must start with conditions")
            if len({gate.condition_id for gate in gates if gate is not None}) != len(gates):
                raise TreeValidationError("choice gate identifiers must be unique")
            for branch in branches:
                if branch is None:
                    continue
                stack = list(branch.child_ids[1:])
                while stack:
                    descendant = by_id.get(stack.pop())
                    if descendant is None:
                        continue
                    if descendant.kind is TreeNodeKind.CHOICE:
                        raise TreeValidationError("nested choice nodes are not supported")
                    stack.extend(descendant.child_ids)

        canonical_batches = tuple(
            sorted(self.parallel_batches, key=lambda batch: batch.parallel_node_id)
        )
        if canonical_batches != self.parallel_batches:
            raise TreeValidationError("parallel_batches are not canonical")
        if len({batch.parallel_node_id for batch in canonical_batches}) != len(
            canonical_batches
        ):
            raise TreeValidationError("a parallel node can have only one committed batch")
        for batch in canonical_batches:
            bound_parallel = by_id.get(batch.parallel_node_id)
            if (
                bound_parallel is None
                or bound_parallel.kind is not TreeNodeKind.PARALLEL
            ):
                raise TreeValidationError("parallel batch node binding is invalid")
            if batch.disposition is ParallelBatchDisposition.BLOCKED:
                raise TreeValidationError("blocked parallel batches are not persisted")
            results = {item.node_id: item for item in batch.results}
            if set(results) != set(bound_parallel.child_ids):
                raise TreeValidationError("parallel batch child binding is invalid")
            for child_id in bound_parallel.child_ids:
                child = by_id[child_id]
                result = results[child_id]
                if result.condition_id != child.condition_id:
                    raise TreeValidationError("parallel batch condition binding is invalid")
                expected_status = (
                    PlanStepStatus.COMPLETED
                    if result.outcome is ConditionOutcome.TRUE
                    else PlanStepStatus.FAILED
                    if result.outcome is ConditionOutcome.FALSE
                    else PlanStepStatus.PENDING
                )
                if child.status is not expected_status:
                    raise TreeValidationError("parallel batch leaf status is not canonical")

        referenced: list[str] = []
        for parent in ordered:
            for child_id in parent.child_ids:
                bound_child = by_id.get(child_id)
                if bound_child is None or bound_child.parent_id != parent.node_id:
                    raise TreeValidationError("child binding is invalid")
                referenced.append(child_id)
        if len(referenced) != len(set(referenced)):
            raise TreeValidationError("a tree node cannot have multiple parents")
        if set(referenced) != set(by_id) - {self.root_id}:
            raise TreeValidationError("every non-root node must be reachable once")

        if self.contract_version == TREE_CONTRACT_VERSION_V3 or (
            self.contract_version == TREE_CONTRACT_VERSION_V4
            and (self.dependencies or join_nodes)
        ):
            if not self.dependencies or not join_nodes:
                raise TreeValidationError("dependencies and joins must appear together")
            _validate_dependency_graph(by_id, self.dependencies)

        choice_events = self.choice_events
        if self.contract_version == TREE_CONTRACT_VERSION_V4:
            choice = choice_nodes[0]
            branch_ids = choice.child_ids
            gate_by_branch = {
                branch_id: by_id[by_id[branch_id].child_ids[0]]
                for branch_id in branch_ids
            }
            previous_selected: str | None = None
            previous_sequence = -1
            evidence_leaf_statuses: dict[str, PlanStepStatus] = {}
            for index, event in enumerate(choice_events):
                if (
                    event.choice_node_id != choice.node_id
                    or event.disposition is ChoiceDisposition.BLOCKED
                    or event.source_sequence <= previous_sequence
                ):
                    raise TreeValidationError("choice event chain is invalid")
                expected_branches = (
                    branch_ids
                    if index == 0
                    else branch_ids[branch_ids.index(previous_selected or "") + 1 :]
                )
                if tuple(result.branch_id for result in event.results) != expected_branches:
                    raise TreeValidationError("choice result branch binding is invalid")
                for choice_result in event.results:
                    gate = gate_by_branch[choice_result.branch_id]
                    if (
                        choice_result.condition_node_id != gate.node_id
                        or choice_result.condition_id != gate.condition_id
                    ):
                        raise TreeValidationError("choice gate binding is invalid")
                if index == 0:
                    if event.fallback is not None:
                        raise TreeValidationError("initial choice cannot carry fallback")
                else:
                    fallback = event.fallback
                    if (
                        fallback is None
                        or fallback.source_branch_id != previous_selected
                    ):
                        raise TreeValidationError("choice fallback chain is invalid")
                    source_branch = by_id[fallback.source_branch_id]
                    descendants: set[str] = set()
                    stack = list(source_branch.child_ids)
                    while stack:
                        descendant_id = stack.pop()
                        descendants.add(descendant_id)
                        stack.extend(by_id[descendant_id].child_ids)
                    failure = by_id.get(fallback.failure_node_id)
                    if failure is None or failure.node_id not in descendants:
                        raise TreeValidationError("choice fallback binding is invalid")
                    if fallback.cause is ChoiceFallbackCause.PRE_BOUNDARY_FALSE:
                        if failure.node_id != source_branch.child_ids[0]:
                            raise TreeValidationError("choice fallback binding is invalid")
                        expected_condition_id = failure.condition_id
                    else:
                        observation = by_id.get(fallback.observation_node_id or "")
                        if (
                            failure.kind is not TreeNodeKind.VERIFY
                            or observation is None
                            or observation.node_id not in descendants
                            or observation.kind
                            not in {TreeNodeKind.TOOL_STEP, TreeNodeKind.SUBTREE}
                            or observation.status is not PlanStepStatus.COMPLETED
                            or any(by_id[node_id].budget.side_effects for node_id in descendants)
                        ):
                            raise TreeValidationError("choice fallback is not read-only")
                        expected_condition_id = failure.verification_id
                    if (
                        expected_condition_id != fallback.condition_id
                        or failure.status is not PlanStepStatus.FAILED
                    ):
                        raise TreeValidationError("choice fallback evidence is invalid")
                    evidence_leaf_statuses[failure.node_id] = PlanStepStatus.FAILED
                for choice_result in event.results:
                    if choice_result.outcome is ConditionOutcome.FALSE:
                        evidence_leaf_statuses[
                            choice_result.condition_node_id
                        ] = PlanStepStatus.FAILED
                        continue
                    if choice_result.outcome is ConditionOutcome.TRUE:
                        evidence_leaf_statuses[
                            choice_result.condition_node_id
                        ] = PlanStepStatus.COMPLETED
                        break
                previous_sequence = event.source_sequence
                previous_selected = event.selected_branch_id
                if event.disposition is ChoiceDisposition.FAILED:
                    previous_selected = None
                    if index != len(choice_events) - 1:
                        raise TreeValidationError("failed choice event must be final")
            if any(
                by_id[node_id].status is not status
                for node_id, status in evidence_leaf_statuses.items()
            ):
                raise TreeValidationError("choice evidence status is not canonical")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str, depth: int) -> None:
            if depth > self.limits.max_depth:
                raise TreeValidationError("tree depth exceeds bound limits")
            if node_id in visiting:
                raise TreeValidationError("tree contains a cycle")
            if node_id in visited:
                return
            visiting.add(node_id)
            node = by_id[node_id]
            for child_id in node.child_ids:
                visit(child_id, depth + 1)
            if node.child_ids:
                if node.kind is TreeNodeKind.CHOICE and choice_events:
                    final_event = choice_events[-1]
                    expected = (
                        PlanStepStatus.FAILED
                        if final_event.disposition is ChoiceDisposition.FAILED
                        else by_id[final_event.selected_branch_id or ""].status
                    )
                else:
                    expected = reduce_child_statuses(
                        tuple(by_id[child_id].status for child_id in node.child_ids)
                    )
                if node.status is not expected:
                    raise TreeValidationError("control node status is not canonical")
            visiting.remove(node_id)
            visited.add(node_id)

        visit(self.root_id, 1)
        if len(visited) != len(ordered):
            raise TreeValidationError("tree contains unreachable nodes")
        if self.contract_version >= TREE_CONTRACT_VERSION_V3:
            incoming: dict[str, tuple[PlanStepStatus, ...]] = {}
            for dependency in self.dependencies:
                incoming[dependency.dependent_id] = (
                    *incoming.get(dependency.dependent_id, ()),
                    by_id[dependency.prerequisite_id].status,
                )
            for join in join_nodes:
                expected = reduce_child_statuses(incoming[join.node_id])
                if join.status is not expected:
                    raise TreeValidationError("join node status is not canonical")

    @property
    def status(self) -> PlanStepStatus:
        return next(node.status for node in self.nodes if node.node_id == self.root_id)

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "tree_id": self.tree_id,
            "run_id": self.run_id,
            "task_digest": self.task_digest,
            "registry_digest": self.registry_digest,
            "policy_digest": self.policy_digest,
            "root_id": self.root_id,
            "limits": self.limits.to_payload(),
            "aggregate_budget": self.aggregate_budget.to_payload(),
            "nodes": [node.to_payload() for node in self.nodes],
        }
        if self.contract_version >= TREE_CONTRACT_VERSION_V2:
            payload["parallel_batches"] = [
                batch.to_payload() for batch in self.parallel_batches
            ]
        if self.contract_version >= TREE_CONTRACT_VERSION_V3:
            payload["dependencies"] = [
                dependency.to_payload() for dependency in self.dependencies
            ]
        if self.contract_version >= TREE_CONTRACT_VERSION_V4:
            payload["choice_events"] = [
                event.to_payload() for event in self.choice_events
            ]
        return payload

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_payload(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


def reduce_tree_statuses(
    tree: TaskTree,
    leaf_statuses: Mapping[str, PlanStepStatus],
    *,
    choice_events: tuple[ChoiceEvent, ...] | None = None,
) -> TaskTree:
    """Return a canonical pure projection from caller-supplied leaf evidence.

    This function deliberately does not validate runtime transition authority.
    H2/H3 own durable CAS and next-leaf transition rules.
    """

    if not isinstance(tree, TaskTree):
        raise TreeValidationError("tree must be a TaskTree")
    if not isinstance(leaf_statuses, Mapping):
        raise TreeValidationError("leaf_statuses must be an explicit mapping")
    by_id = {node.node_id: node for node in tree.nodes}
    for node_id, status in leaf_statuses.items():
        _require_identifier(node_id, "leaf node_id")
        node = by_id.get(node_id)
        if node is None or not node.is_leaf or node.kind is TreeNodeKind.JOIN:
            raise TreeValidationError("leaf status references a non-leaf node")
        if not isinstance(status, PlanStepStatus):
            raise TreeValidationError("leaf status is invalid")

    bound_choice_events = tree.choice_events if choice_events is None else choice_events
    if not isinstance(bound_choice_events, tuple) or not all(
        isinstance(event, ChoiceEvent) for event in bound_choice_events
    ):
        raise TreeValidationError("choice_events are invalid")
    prerequisites: dict[str, tuple[str, ...]] = {}
    for dependency in tree.dependencies:
        prerequisites[dependency.dependent_id] = (
            *prerequisites.get(dependency.dependent_id, ()),
            dependency.prerequisite_id,
        )
    resolved: dict[str, PlanStepStatus] = {
        node.node_id: leaf_statuses.get(node.node_id, node.status)
        for node in tree.nodes
        if node.is_leaf and node.kind is not TreeNodeKind.JOIN
    }
    unresolved = {node.node_id for node in tree.nodes if node.node_id not in resolved}
    while unresolved:
        progressed = False
        for node_id in sorted(unresolved):
            node = by_id[node_id]
            source_ids: tuple[str, ...]
            if node.kind is TreeNodeKind.CHOICE and bound_choice_events:
                final_event = bound_choice_events[-1]
                if final_event.disposition is ChoiceDisposition.FAILED:
                    resolved[node_id] = PlanStepStatus.FAILED
                    unresolved.remove(node_id)
                    progressed = True
                    break
                source_ids = (final_event.selected_branch_id or "",)
            else:
                source_ids = (
                    prerequisites.get(node_id, ())
                    if node.kind is TreeNodeKind.JOIN
                    else node.child_ids
                )
            if not source_ids or any(source_id not in resolved for source_id in source_ids):
                continue
            resolved[node_id] = reduce_child_statuses(
                tuple(resolved[source_id] for source_id in source_ids)
            )
            unresolved.remove(node_id)
            progressed = True
            break
        if not progressed:
            raise TreeValidationError("tree status reduction contains a cycle")
    nodes = tuple(replace(node, status=resolved[node.node_id]) for node in tree.nodes)
    return replace(tree, nodes=nodes, choice_events=bound_choice_events)


def project_linear_plan(
    plan: TaskPlan,
    *,
    tree_id: str,
    policy_digest: str,
    limits: TreeLimits | None = None,
) -> TaskTree:
    """Project an existing linear plan as one inert ``sequence`` tree."""

    if not isinstance(plan, TaskPlan):
        raise TreeValidationError("plan must be a TaskPlan")
    _require_identifier(tree_id, "tree_id")
    _require_digest(policy_digest, "policy_digest")
    bound_limits = TreeLimits() if limits is None else limits
    if not isinstance(bound_limits, TreeLimits):
        raise TreeValidationError("tree limits are invalid")
    if len(plan.steps) + 1 > bound_limits.max_nodes:
        raise TreeValidationError("linear plan exceeds tree node limits")

    leaves: list[TreeNode] = []
    tool_calls = 0
    side_effects = 0
    for step in plan.steps:
        kind = (
            TreeNodeKind.FINAL_RESPONSE
            if step.action is PlanStepAction.FINAL_RESPONSE
            else TreeNodeKind.TOOL_STEP
        )
        node_tool_calls = 1 if kind is TreeNodeKind.TOOL_STEP else 0
        node_side_effects = (
            1
            if kind is TreeNodeKind.TOOL_STEP and step.effect is ToolEffect.SIDE_EFFECT
            else 0
        )
        tool_calls += node_tool_calls
        side_effects += node_side_effects
        leaves.append(
            TreeNode(
                node_id=f"node_{step.step_id}",
                parent_id="root",
                kind=kind,
                status=step.status,
                step_id=step.step_id,
                budget=TreeBudget(
                    tool_calls=node_tool_calls,
                    side_effects=node_side_effects,
                ),
            )
        )
    root_status = reduce_child_statuses(tuple(node.status for node in leaves))
    root = TreeNode(
        node_id="root",
        kind=TreeNodeKind.SEQUENCE,
        status=root_status,
        child_ids=tuple(node.node_id for node in leaves),
    )
    return TaskTree(
        tree_id=tree_id,
        run_id=plan.run_id,
        task_digest=plan.task_digest,
        registry_digest=plan.registry_digest,
        policy_digest=policy_digest,
        root_id=root.node_id,
        nodes=(root, *leaves),
        limits=bound_limits,
        aggregate_budget=TreeBudget(
            tool_calls=tool_calls,
            side_effects=side_effects,
        ),
    )


__all__ = [
    "MAX_TREE_CHILDREN",
    "MAX_TREE_DEPTH",
    "MAX_TREE_NODES",
    "MAX_TREE_RETRIES",
    "MAX_TREE_SIDE_EFFECTS",
    "MAX_TREE_TOKENS",
    "MAX_TREE_TOOL_CALLS",
    "MAX_TREE_VISITS",
    "MAX_TREE_WALL_CLOCK_SECONDS",
    "TREE_CONTRACT_VERSION",
    "TREE_CONTRACT_VERSION_V2",
    "TREE_CONTRACT_VERSION_V3",
    "TREE_CONTRACT_VERSION_V4",
    "SUPPORTED_TREE_CONTRACT_VERSIONS",
    "TaskTree",
    "TreeBudget",
    "TreeLimits",
    "TreeNode",
    "TreeNodeKind",
    "TreeValidationError",
    "project_linear_plan",
    "reduce_child_statuses",
    "reduce_tree_statuses",
]
