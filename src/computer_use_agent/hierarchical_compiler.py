"""Pure H3 next-leaf compilation with no execution or persistence port.

One compile call returns at most one digest-bound inert leaf boundary. An
already active leaf returns ``waiting`` and can never be re-emitted. Choice
selection remains blocked until H5 supplies typed, fresh world-state facts.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256

from .hierarchical_control import (
    TaskTree,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
    reduce_tree_statuses,
)
from .planning import PlanStepStatus
from .tool_registry import reviewed_registry_digest


TREE_COMPILER_VERSION = 1
MAX_TREE_SEQUENCE = 9_223_372_036_854_775_807
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_TERMINAL_STATUSES = frozenset(
    {
        PlanStepStatus.COMPLETED,
        PlanStepStatus.FAILED,
        PlanStepStatus.BLOCKED,
        PlanStepStatus.CANCELLED,
    }
)
_INTERNAL_ORDERED_KINDS = frozenset(
    {TreeNodeKind.GOAL, TreeNodeKind.SEQUENCE}
)


class TreeCompileError(ValueError):
    """Fixed content-free H3 compilation or transition failure."""


class TreeTickDisposition(str, Enum):
    BOUNDARY = "boundary"
    WAITING = "waiting"
    TERMINAL = "terminal"
    BLOCKED = "blocked"


class TreeTickReason(str, Enum):
    BOUNDARY_READY = "boundary_ready"
    ACTIVE_LEAF_WAIT = "active_leaf_wait"
    TREE_TERMINAL = "tree_terminal"
    CHOICE_FACTS_REQUIRED = "choice_facts_required"


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise TreeCompileError("TREE_COMPILE_INVALID")
    return value


def _require_optional_identifier(value: object) -> str | None:
    if value is None:
        return None
    return _require_identifier(value)


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise TreeCompileError("TREE_COMPILE_INVALID")
    return value


def _require_sequence(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= MAX_TREE_SEQUENCE
    ):
        raise TreeCompileError("TREE_COMPILE_INVALID")
    return value


def _canonical(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


@dataclass(frozen=True)
class CompiledLeafBoundary:
    """One non-executable leaf identity bound to an exact H2 snapshot."""

    source_sequence: int
    source_tree_digest: str
    tree_id: str
    run_id: str
    node_id: str
    node_kind: TreeNodeKind
    step_id: str | None = None
    condition_id: str | None = None
    verification_id: str | None = None
    template_id: str | None = None
    template_version: int | None = None
    template_digest: str | None = None
    compiler_version: int = TREE_COMPILER_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.compiler_version, int)
            or isinstance(self.compiler_version, bool)
            or self.compiler_version != TREE_COMPILER_VERSION
        ):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        _require_sequence(self.source_sequence)
        _require_digest(self.source_tree_digest)
        _require_identifier(self.tree_id)
        _require_identifier(self.run_id)
        _require_identifier(self.node_id)
        if not isinstance(self.node_kind, TreeNodeKind):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        _require_optional_identifier(self.step_id)
        _require_optional_identifier(self.condition_id)
        _require_optional_identifier(self.verification_id)
        _require_optional_identifier(self.template_id)
        if self.template_version is not None and (
            not isinstance(self.template_version, int)
            or isinstance(self.template_version, bool)
            or not 1 <= self.template_version <= 2_147_483_647
        ):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        if self.template_digest is not None:
            _require_digest(self.template_digest)

        bindings = {
            "step_id": self.step_id,
            "condition_id": self.condition_id,
            "verification_id": self.verification_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_digest": self.template_digest,
        }
        required = {
            TreeNodeKind.TOOL_STEP: frozenset({"step_id"}),
            TreeNodeKind.FINAL_RESPONSE: frozenset({"step_id"}),
            TreeNodeKind.CONDITION: frozenset({"condition_id"}),
            TreeNodeKind.VERIFY: frozenset({"verification_id"}),
            TreeNodeKind.SUBTREE: frozenset(
                {"template_id", "template_version", "template_digest"}
            ),
        }.get(self.node_kind)
        present = frozenset(key for key, value in bindings.items() if value is not None)
        if required is None or present != required:
            raise TreeCompileError("TREE_COMPILE_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "compiler_version": self.compiler_version,
            "source_sequence": self.source_sequence,
            "source_tree_digest": self.source_tree_digest,
            "tree_id": self.tree_id,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "node_kind": self.node_kind.value,
            "step_id": self.step_id,
            "condition_id": self.condition_id,
            "verification_id": self.verification_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "template_digest": self.template_digest,
        }

    @property
    def digest(self) -> str:
        return sha256(_canonical(self.to_payload())).hexdigest()


@dataclass(frozen=True)
class CompiledTreeTick:
    """One pure compiler result; only ``boundary`` may contain a leaf."""

    disposition: TreeTickDisposition
    reason: TreeTickReason
    source_sequence: int
    source_tree_digest: str
    tree_status: PlanStepStatus
    boundary: CompiledLeafBoundary | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, TreeTickDisposition):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        if not isinstance(self.reason, TreeTickReason):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        _require_sequence(self.source_sequence)
        _require_digest(self.source_tree_digest)
        if not isinstance(self.tree_status, PlanStepStatus):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        expected_reason = {
            TreeTickDisposition.BOUNDARY: TreeTickReason.BOUNDARY_READY,
            TreeTickDisposition.WAITING: TreeTickReason.ACTIVE_LEAF_WAIT,
            TreeTickDisposition.TERMINAL: TreeTickReason.TREE_TERMINAL,
            TreeTickDisposition.BLOCKED: TreeTickReason.CHOICE_FACTS_REQUIRED,
        }[self.disposition]
        if self.reason is not expected_reason:
            raise TreeCompileError("TREE_COMPILE_INVALID")
        allowed_statuses = {
            TreeTickDisposition.BOUNDARY: frozenset(
                {PlanStepStatus.PENDING, PlanStepStatus.IN_PROGRESS}
            ),
            TreeTickDisposition.WAITING: frozenset({PlanStepStatus.IN_PROGRESS}),
            TreeTickDisposition.TERMINAL: _TERMINAL_STATUSES,
            TreeTickDisposition.BLOCKED: frozenset(
                {PlanStepStatus.PENDING, PlanStepStatus.IN_PROGRESS}
            ),
        }[self.disposition]
        if self.tree_status not in allowed_statuses:
            raise TreeCompileError("TREE_COMPILE_INVALID")
        if (self.boundary is None) is (
            self.disposition is TreeTickDisposition.BOUNDARY
        ):
            raise TreeCompileError("TREE_COMPILE_INVALID")
        if self.boundary is not None and (
            self.boundary.source_sequence != self.source_sequence
            or self.boundary.source_tree_digest != self.source_tree_digest
        ):
            raise TreeCompileError("TREE_COMPILE_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "disposition": self.disposition.value,
            "reason": self.reason.value,
            "source_sequence": self.source_sequence,
            "source_tree_digest": self.source_tree_digest,
            "tree_status": self.tree_status.value,
            "boundary": None if self.boundary is None else self.boundary.to_payload(),
        }


def _validate_source(tree: TaskTree, sequence: int) -> None:
    if not isinstance(tree, TaskTree):
        raise TreeCompileError("TREE_COMPILE_INVALID")
    _require_sequence(sequence)
    if tree.registry_digest != reviewed_registry_digest():
        raise TreeCompileError("TREE_COMPILE_REGISTRY_MISMATCH")


def _boundary(tree: TaskTree, node: TreeNode, sequence: int) -> CompiledLeafBoundary:
    return CompiledLeafBoundary(
        source_sequence=sequence,
        source_tree_digest=tree.digest,
        tree_id=tree.tree_id,
        run_id=tree.run_id,
        node_id=node.node_id,
        node_kind=node.kind,
        step_id=node.step_id,
        condition_id=node.condition_id,
        verification_id=node.verification_id,
        template_id=node.template_id,
        template_version=node.template_version,
        template_digest=node.template_digest,
    )


def _next_ordered_leaf(
    node: TreeNode, by_id: dict[str, TreeNode]
) -> tuple[TreeNode | None, bool]:
    if node.status in _TERMINAL_STATUSES:
        return None, False
    if node.is_leaf:
        if node.status not in {
            PlanStepStatus.PENDING,
            PlanStepStatus.IN_PROGRESS,
        }:
            raise TreeCompileError("TREE_COMPILE_STATE_INVALID")
        return node, False
    if node.kind is TreeNodeKind.CHOICE:
        return None, True
    if node.kind not in _INTERNAL_ORDERED_KINDS:
        raise TreeCompileError("TREE_COMPILE_STATE_INVALID")
    for child_id in node.child_ids:
        child = by_id[child_id]
        if child.status is PlanStepStatus.COMPLETED:
            continue
        return _next_ordered_leaf(child, by_id)
    raise TreeCompileError("TREE_COMPILE_STATE_INVALID")


def compile_next_leaf(tree: TaskTree, *, sequence: int) -> CompiledTreeTick:
    """Compile at most one inert next-leaf boundary without changing state."""

    _validate_source(tree, sequence)
    active = tuple(
        node
        for node in tree.nodes
        if node.is_leaf and node.status is PlanStepStatus.IN_PROGRESS
    )
    if len(active) > 1:
        raise TreeCompileError("TREE_COMPILE_MULTIPLE_ACTIVE_LEAVES")
    if tree.status in _TERMINAL_STATUSES:
        if active:
            raise TreeCompileError("TREE_COMPILE_ACTIVE_IN_TERMINAL_TREE")
        return CompiledTreeTick(
            disposition=TreeTickDisposition.TERMINAL,
            reason=TreeTickReason.TREE_TERMINAL,
            source_sequence=sequence,
            source_tree_digest=tree.digest,
            tree_status=tree.status,
        )

    by_id = {node.node_id: node for node in tree.nodes}
    leaf, choice_blocked = _next_ordered_leaf(by_id[tree.root_id], by_id)
    if choice_blocked:
        if active:
            raise TreeCompileError("TREE_COMPILE_ACTIVE_CHOICE_UNRESOLVED")
        return CompiledTreeTick(
            disposition=TreeTickDisposition.BLOCKED,
            reason=TreeTickReason.CHOICE_FACTS_REQUIRED,
            source_sequence=sequence,
            source_tree_digest=tree.digest,
            tree_status=tree.status,
        )
    if leaf is None:
        raise TreeCompileError("TREE_COMPILE_STATE_INVALID")
    if active:
        if leaf.node_id != active[0].node_id:
            raise TreeCompileError("TREE_COMPILE_ACTIVE_OUT_OF_ORDER")
        return CompiledTreeTick(
            disposition=TreeTickDisposition.WAITING,
            reason=TreeTickReason.ACTIVE_LEAF_WAIT,
            source_sequence=sequence,
            source_tree_digest=tree.digest,
            tree_status=tree.status,
        )
    return CompiledTreeTick(
        disposition=TreeTickDisposition.BOUNDARY,
        reason=TreeTickReason.BOUNDARY_READY,
        source_sequence=sequence,
        source_tree_digest=tree.digest,
        tree_status=tree.status,
        boundary=_boundary(tree, leaf, sequence),
    )


def transition_tree_leaf(
    tree: TaskTree,
    node_id: str,
    target: PlanStepStatus,
) -> TaskTree:
    """Return one pure legal ordered leaf transition; never dispatch work."""

    _validate_source(tree, 0)
    _require_identifier(node_id)
    if not isinstance(target, PlanStepStatus):
        raise TreeCompileError("TREE_TRANSITION_INVALID")
    if tree.status in _TERMINAL_STATUSES:
        raise TreeCompileError("TREE_TRANSITION_TERMINAL")
    by_id = {node.node_id: node for node in tree.nodes}
    node = by_id.get(node_id)
    if node is None or not node.is_leaf:
        raise TreeCompileError("TREE_TRANSITION_INVALID")

    allowed = {
        PlanStepStatus.PENDING: frozenset(
            {
                PlanStepStatus.IN_PROGRESS,
                PlanStepStatus.BLOCKED,
                PlanStepStatus.CANCELLED,
            }
        ),
        PlanStepStatus.IN_PROGRESS: frozenset(
            {
                PlanStepStatus.COMPLETED,
                PlanStepStatus.FAILED,
                PlanStepStatus.BLOCKED,
                PlanStepStatus.CANCELLED,
            }
        ),
    }.get(node.status, frozenset())
    if target not in allowed:
        raise TreeCompileError("TREE_TRANSITION_INVALID")

    active = tuple(
        item.node_id
        for item in tree.nodes
        if item.is_leaf and item.status is PlanStepStatus.IN_PROGRESS
    )
    if node.status is PlanStepStatus.PENDING:
        if active:
            raise TreeCompileError("TREE_TRANSITION_ACTIVE_LEAF")
        tick = compile_next_leaf(tree, sequence=0)
        if (
            tick.disposition is not TreeTickDisposition.BOUNDARY
            or tick.boundary is None
            or tick.boundary.node_id != node_id
        ):
            raise TreeCompileError("TREE_TRANSITION_OUT_OF_ORDER")
    elif active != (node_id,):
        raise TreeCompileError("TREE_TRANSITION_ACTIVE_LEAF")

    try:
        return reduce_tree_statuses(tree, {node_id: target})
    except TreeValidationError as exc:
        raise TreeCompileError("TREE_TRANSITION_INVALID") from exc


__all__ = [
    "MAX_TREE_SEQUENCE",
    "TREE_COMPILER_VERSION",
    "CompiledLeafBoundary",
    "CompiledTreeTick",
    "TreeCompileError",
    "TreeTickDisposition",
    "TreeTickReason",
    "compile_next_leaf",
    "transition_tree_leaf",
]
