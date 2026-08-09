"""Run-lock-bound H4 projection for the existing observation runtime.

This module has no provider, MCP, desktop, approval, or dispatch port.  It
binds the H1-H3 linear tree to the existing durable ``TaskPlan`` and permits
only status projection around the sole Runner boundary owned elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass

from .hierarchical_compiler import (
    TreeCompileError,
    TreeTickDisposition,
    compile_next_leaf,
    transition_tree_leaf,
)
from .hierarchical_control import (
    TreeNodeKind,
    TreeValidationError,
    project_linear_plan,
    reduce_tree_statuses,
)
from .plan_store import PersistedTaskPlan, PlanStoreError, TaskPlanStore
from .planning import PlanStepAction, PlanStepStatus, TaskPlan
from .policy import HostPolicy
from .tree_store import PersistedTaskTree, TaskTreeStore, TreeStoreError
from .types import ToolEffect


class HierarchicalRuntimeError(RuntimeError):
    """A fixed H4 projection failure without plan, tree, or task content."""


def runtime_policy_digest(policy: HostPolicy) -> str:
    """Return the canonical reviewed Runner-policy binding used by H4."""

    if not isinstance(policy, HostPolicy):
        raise HierarchicalRuntimeError("HIERARCHICAL_RUNTIME_INPUT_INVALID")
    return policy.digest


def _expected_kind(action: PlanStepAction) -> TreeNodeKind:
    return (
        TreeNodeKind.FINAL_RESPONSE
        if action is PlanStepAction.FINAL_RESPONSE
        else TreeNodeKind.TOOL_STEP
    )


@dataclass(frozen=True)
class LinearTaskTreeProjection:
    """Exact H4 status projection sharing the canonical plan's ``RunLock``."""

    plan_store: TaskPlanStore
    tree_store: TaskTreeStore
    run_id: str
    tree_id: str
    policy_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.plan_store, TaskPlanStore)
            or not isinstance(self.tree_store, TaskTreeStore)
            or self.plan_store.lock is not self.tree_store.lock
            or self.plan_store.state_dir != self.tree_store.state_dir
            or not self.plan_store.lock.acquired
            or not isinstance(self.run_id, str)
            or not self.run_id
            or not isinstance(self.tree_id, str)
            or not self.tree_id
            or not isinstance(self.policy_digest, str)
        ):
            raise HierarchicalRuntimeError("HIERARCHICAL_RUNTIME_INPUT_INVALID")

    @classmethod
    def create(
        cls,
        plan_store: TaskPlanStore,
        tree_store: TaskTreeStore,
        plan: TaskPlan,
        *,
        tree_id: str,
        policy_digest: str,
    ) -> "LinearTaskTreeProjection":
        """Create one pending observation-only tree beside its existing plan."""

        if (
            not isinstance(plan, TaskPlan)
            or any(
                step.action is PlanStepAction.TOOL
                and step.effect is not ToolEffect.OBSERVATION
                for step in plan.steps
            )
        ):
            raise HierarchicalRuntimeError("HIERARCHICAL_RUNTIME_PLAN_UNSAFE")
        projection = cls(
            plan_store=plan_store,
            tree_store=tree_store,
            run_id=plan.run_id,
            tree_id=tree_id,
            policy_digest=policy_digest,
        )
        try:
            tree = project_linear_plan(
                plan,
                tree_id=tree_id,
                policy_digest=policy_digest,
            )
            tree_store.create(tree)
            projection._validate_pair(plan_store.read(plan.run_id), tree_store.read(plan.run_id))
        except (PlanStoreError, TreeStoreError, TreeValidationError) as exc:
            raise HierarchicalRuntimeError(
                "HIERARCHICAL_RUNTIME_CREATE_FAILED"
            ) from exc
        return projection

    def _read_pair(self) -> tuple[PersistedTaskPlan, PersistedTaskTree]:
        try:
            plan = self.plan_store.read(self.run_id)
            tree = self.tree_store.read(self.run_id)
            self._validate_pair(plan, tree)
        except (PlanStoreError, TreeStoreError, TreeValidationError) as exc:
            raise HierarchicalRuntimeError(
                "HIERARCHICAL_RUNTIME_STATE_INVALID"
            ) from exc
        return plan, tree

    def _validate_pair(
        self, plan_snapshot: PersistedTaskPlan, tree_snapshot: PersistedTaskTree
    ) -> None:
        plan = plan_snapshot.plan
        tree = tree_snapshot.tree
        if (
            plan.run_id != self.run_id
            or tree.run_id != self.run_id
            or tree.tree_id != self.tree_id
            or tree.task_digest != plan.task_digest
            or tree.registry_digest != plan.registry_digest
            or tree.policy_digest != self.policy_digest
        ):
            raise HierarchicalRuntimeError("HIERARCHICAL_RUNTIME_IDENTITY_MISMATCH")
        by_id = {node.node_id: node for node in tree.nodes}
        root = by_id.get(tree.root_id)
        if (
            root is None
            or root.kind is not TreeNodeKind.SEQUENCE
            or len(root.child_ids) != len(plan.steps)
            or len(tree.nodes) != len(plan.steps) + 1
        ):
            raise HierarchicalRuntimeError("HIERARCHICAL_RUNTIME_STRUCTURE_MISMATCH")
        for step, node_id in zip(plan.steps, root.child_ids, strict=True):
            node = by_id.get(node_id)
            if (
                node is None
                or node.node_id != f"node_{step.step_id}"
                or node.parent_id != root.node_id
                or node.step_id != step.step_id
                or node.kind is not _expected_kind(step.action)
            ):
                raise HierarchicalRuntimeError(
                    "HIERARCHICAL_RUNTIME_STRUCTURE_MISMATCH"
                )

    def snapshot(self) -> PersistedTaskTree:
        """Return the validated current tree evidence while the lock is held."""

        return self._read_pair()[1]

    def start_step(
        self, step_id: str, *, node_kind: TreeNodeKind
    ) -> PersistedTaskTree:
        """Durably mark the one exact next leaf active before its boundary."""

        plan_snapshot, tree_snapshot = self._read_pair()
        plan_step = next(
            (
                step
                for step in plan_snapshot.plan.steps
                if step.status is not PlanStepStatus.COMPLETED
            ),
            None,
        )
        try:
            tick = compile_next_leaf(
                tree_snapshot.tree, sequence=tree_snapshot.sequence
            )
            if (
                plan_step is None
                or plan_step.step_id != step_id
                or plan_step.status is not PlanStepStatus.PENDING
                or _expected_kind(plan_step.action) is not node_kind
                or tick.disposition is not TreeTickDisposition.BOUNDARY
                or tick.boundary is None
                or tick.boundary.step_id != step_id
                or tick.boundary.node_kind is not node_kind
            ):
                raise HierarchicalRuntimeError(
                    "HIERARCHICAL_RUNTIME_BOUNDARY_MISMATCH"
                )
            updated = transition_tree_leaf(
                tree_snapshot.tree,
                tick.boundary.node_id,
                PlanStepStatus.IN_PROGRESS,
            )
            return self.tree_store.compare_and_swap(
                self.run_id,
                updated,
                expected_sequence=tree_snapshot.sequence,
                expected_tree_digest=tree_snapshot.tree.digest,
            )
        except (TreeCompileError, TreeStoreError) as exc:
            raise HierarchicalRuntimeError(
                "HIERARCHICAL_RUNTIME_START_FAILED"
            ) from exc

    def finish_step(
        self,
        step_id: str,
        target: PlanStepStatus,
        *,
        node_kind: TreeNodeKind,
    ) -> PersistedTaskTree:
        """Commit a known leaf result only after the plan owns that result."""

        if target not in {PlanStepStatus.COMPLETED, PlanStepStatus.FAILED}:
            raise HierarchicalRuntimeError("HIERARCHICAL_RUNTIME_TARGET_INVALID")
        plan_snapshot, tree_snapshot = self._read_pair()
        plan_step = next(
            (step for step in plan_snapshot.plan.steps if step.step_id == step_id),
            None,
        )
        active = tuple(
            node
            for node in tree_snapshot.tree.nodes
            if node.is_leaf and node.status is PlanStepStatus.IN_PROGRESS
        )
        try:
            tick = compile_next_leaf(
                tree_snapshot.tree, sequence=tree_snapshot.sequence
            )
            if (
                plan_step is None
                or plan_step.status is not target
                or _expected_kind(plan_step.action) is not node_kind
                or tick.disposition is not TreeTickDisposition.WAITING
                or len(active) != 1
                or active[0].step_id != step_id
                or active[0].kind is not node_kind
            ):
                raise HierarchicalRuntimeError(
                    "HIERARCHICAL_RUNTIME_RESULT_MISMATCH"
                )
            updated = transition_tree_leaf(
                tree_snapshot.tree, active[0].node_id, target
            )
            return self.tree_store.compare_and_swap(
                self.run_id,
                updated,
                expected_sequence=tree_snapshot.sequence,
                expected_tree_digest=tree_snapshot.tree.digest,
            )
        except (TreeCompileError, TreeStoreError) as exc:
            raise HierarchicalRuntimeError(
                "HIERARCHICAL_RUNTIME_FINISH_FAILED"
            ) from exc

    def cancel_pending_step(self, step_id: str) -> PersistedTaskTree:
        """Mirror a known pending-plan cancellation without executing a leaf."""

        plan_snapshot, tree_snapshot = self._read_pair()
        plan_step = next(
            (step for step in plan_snapshot.plan.steps if step.step_id == step_id),
            None,
        )
        try:
            tick = compile_next_leaf(
                tree_snapshot.tree, sequence=tree_snapshot.sequence
            )
            if (
                plan_step is None
                or plan_step.status is not PlanStepStatus.CANCELLED
                or tick.disposition is not TreeTickDisposition.BOUNDARY
                or tick.boundary is None
                or tick.boundary.step_id != step_id
            ):
                raise HierarchicalRuntimeError(
                    "HIERARCHICAL_RUNTIME_RESULT_MISMATCH"
                )
            updated = transition_tree_leaf(
                tree_snapshot.tree,
                tick.boundary.node_id,
                PlanStepStatus.CANCELLED,
            )
            return self.tree_store.compare_and_swap(
                self.run_id,
                updated,
                expected_sequence=tree_snapshot.sequence,
                expected_tree_digest=tree_snapshot.tree.digest,
            )
        except (TreeCompileError, TreeStoreError) as exc:
            raise HierarchicalRuntimeError(
                "HIERARCHICAL_RUNTIME_FINISH_FAILED"
            ) from exc

    def reconcile_from_plan(self) -> PersistedTaskTree:
        """Repair only the tree projection from exact durable plan evidence.

        This method has no external port and never retries a boundary.  In
        particular an ``in_progress`` plan step remains ``in_progress``.
        """

        plan_snapshot, tree_snapshot = self._read_pair()
        statuses = {
            f"node_{step.step_id}": step.status for step in plan_snapshot.plan.steps
        }
        try:
            updated = reduce_tree_statuses(tree_snapshot.tree, statuses)
            if updated.digest == tree_snapshot.tree.digest:
                return tree_snapshot
            return self.tree_store.compare_and_swap(
                self.run_id,
                updated,
                expected_sequence=tree_snapshot.sequence,
                expected_tree_digest=tree_snapshot.tree.digest,
            )
        except (TreeValidationError, TreeStoreError) as exc:
            raise HierarchicalRuntimeError(
                "HIERARCHICAL_RUNTIME_RECONCILE_FAILED"
            ) from exc


__all__ = [
    "HierarchicalRuntimeError",
    "LinearTaskTreeProjection",
    "runtime_policy_digest",
]
