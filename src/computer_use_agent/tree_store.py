"""Private H2 persistence for inert hierarchical task-tree snapshots.

The store has no provider, policy, approval, Runner, MCP, campaign, or desktop
port. Callers must hold the existing application ``RunLock``. Replacement is
sequence/tree-digest compare-and-swap over one immutable tree structure; H3,
not this module, owns next-leaf and legal transition rules.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .hierarchical_control import (
    TREE_CONTRACT_VERSION,
    TREE_CONTRACT_VERSION_V2,
    TaskTree,
    TreeBudget,
    TreeLimits,
    TreeNode,
    TreeNodeKind,
    TreeValidationError,
)
from .hierarchical_parallel_contract import (
    ParallelBatchDisposition,
    ParallelConditionBatch,
    ParallelConditionContractError,
    ParallelConditionResult,
)
from .planning import PlanStepStatus
from .run_lock import RunLock
from .tool_registry import reviewed_registry_digest


TREE_STORE_VERSION = 1
MAX_PERSISTED_TREE_BYTES = 512 * 1024
TREE_STORE_WRITE_CHECKPOINTS = (
    "before_parent_create",
    "before_temp_create",
    "before_temp_chmod",
    "before_write",
    "before_flush",
    "before_fsync",
    "before_create_recheck",
    "before_replace",
)
_PATH_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ENVELOPE_FIELDS = frozenset(
    {"store_version", "sequence", "tree", "tree_digest", "envelope_digest"}
)
_TREE_FIELDS_V1 = frozenset(
    {
        "contract_version",
        "tree_id",
        "run_id",
        "task_digest",
        "registry_digest",
        "policy_digest",
        "root_id",
        "limits",
        "aggregate_budget",
        "nodes",
    }
)
_TREE_FIELDS_V2 = _TREE_FIELDS_V1 | {"parallel_batches"}
_LIMIT_FIELDS = frozenset(
    {
        "max_depth",
        "max_nodes",
        "max_children",
        "max_visits",
        "max_wall_clock_seconds",
    }
)
_BUDGET_FIELDS = frozenset({"tool_calls", "tokens", "side_effects", "retries"})
_NODE_FIELDS = frozenset(
    {
        "node_id",
        "parent_id",
        "kind",
        "status",
        "child_ids",
        "step_id",
        "condition_id",
        "verification_id",
        "template_id",
        "template_version",
        "template_digest",
        "budget",
    }
)
_PARALLEL_BATCH_FIELDS = frozenset(
    {
        "version",
        "parallel_node_id",
        "source_sequence",
        "source_tree_digest",
        "snapshot_digest",
        "context_digest",
        "disposition",
        "results",
    }
)
_PARALLEL_RESULT_FIELDS = frozenset(
    {
        "node_id",
        "condition_id",
        "outcome",
        "availability",
        "condition_digest",
        "fact_digest",
        "evidence_digest",
    }
)


class TreeStoreError(RuntimeError):
    """Fixed persistence failure that never embeds tree or task content."""


@dataclass(frozen=True)
class PersistedTaskTree:
    """One strictly validated private tree-store snapshot."""

    tree: TaskTree
    sequence: int
    envelope_digest: str


def _canonical(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise TreeStoreError("TREE_STORE_INVALID")
    return value


def _require_sequence(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TreeStoreError("TREE_STORE_INVALID")
    return value


def _require_path_identifier(value: object) -> str:
    if not isinstance(value, str) or _PATH_IDENTIFIER.fullmatch(value) is None:
        raise TreeStoreError("TREE_STORE_INVALID")
    return value


def _require_str(value: object) -> str:
    if not isinstance(value, str):
        raise TreeStoreError("TREE_STORE_INVALID")
    return value


def _require_optional_str(value: object) -> str | None:
    if value is None:
        return None
    return _require_str(value)


def _require_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TreeStoreError("TREE_STORE_INVALID")
    return value


def _is_unsafe_path(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse)


def task_tree_path(state_dir: Path, run_id: str) -> Path:
    """Return the private H2 tree path after strict path-shape validation."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    safe_run_id = _require_path_identifier(run_id)
    return state_dir / "runs" / safe_run_id / "task-tree.json"


def _decode_budget(value: object) -> TreeBudget:
    if not isinstance(value, Mapping) or set(value) != _BUDGET_FIELDS:
        raise TreeStoreError("TREE_STORE_INVALID")
    try:
        return TreeBudget(
            tool_calls=_require_int(value.get("tool_calls")),
            tokens=_require_int(value.get("tokens")),
            side_effects=_require_int(value.get("side_effects")),
            retries=_require_int(value.get("retries")),
        )
    except TreeValidationError as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc


def _decode_limits(value: object) -> TreeLimits:
    if not isinstance(value, Mapping) or set(value) != _LIMIT_FIELDS:
        raise TreeStoreError("TREE_STORE_INVALID")
    try:
        return TreeLimits(
            max_depth=_require_int(value.get("max_depth")),
            max_nodes=_require_int(value.get("max_nodes")),
            max_children=_require_int(value.get("max_children")),
            max_visits=_require_int(value.get("max_visits")),
            max_wall_clock_seconds=_require_int(value.get("max_wall_clock_seconds")),
        )
    except TreeValidationError as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc


def _decode_node(value: object) -> TreeNode:
    if not isinstance(value, Mapping) or set(value) != _NODE_FIELDS:
        raise TreeStoreError("TREE_STORE_INVALID")
    child_ids = value.get("child_ids")
    if not isinstance(child_ids, list) or not all(
        isinstance(child_id, str) for child_id in child_ids
    ):
        raise TreeStoreError("TREE_STORE_INVALID")
    try:
        return TreeNode(
            node_id=_require_str(value.get("node_id")),
            parent_id=_require_optional_str(value.get("parent_id")),
            kind=TreeNodeKind(_require_str(value.get("kind"))),
            status=PlanStepStatus(_require_str(value.get("status"))),
            child_ids=tuple(child_ids),
            step_id=_require_optional_str(value.get("step_id")),
            condition_id=_require_optional_str(value.get("condition_id")),
            verification_id=_require_optional_str(value.get("verification_id")),
            template_id=_require_optional_str(value.get("template_id")),
            template_version=(
                None
                if value.get("template_version") is None
                else _require_int(value.get("template_version"))
            ),
            template_digest=_require_optional_str(value.get("template_digest")),
            budget=_decode_budget(value.get("budget")),
        )
    except (TreeValidationError, ValueError) as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc


def _decode_parallel_result(value: object) -> ParallelConditionResult:
    if not isinstance(value, Mapping) or set(value) != _PARALLEL_RESULT_FIELDS:
        raise TreeStoreError("TREE_STORE_INVALID")
    from .world_state import ConditionOutcome, FactAvailability

    try:
        return ParallelConditionResult(
            node_id=_require_str(value.get("node_id")),
            condition_id=_require_str(value.get("condition_id")),
            outcome=ConditionOutcome(_require_str(value.get("outcome"))),
            availability=FactAvailability(_require_str(value.get("availability"))),
            condition_digest=_require_digest(value.get("condition_digest")),
            fact_digest=(
                None
                if value.get("fact_digest") is None
                else _require_digest(value.get("fact_digest"))
            ),
            evidence_digest=(
                None
                if value.get("evidence_digest") is None
                else _require_digest(value.get("evidence_digest"))
            ),
        )
    except (ParallelConditionContractError, ValueError) as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc


def _decode_parallel_batch(value: object) -> ParallelConditionBatch:
    if not isinstance(value, Mapping) or set(value) != _PARALLEL_BATCH_FIELDS:
        raise TreeStoreError("TREE_STORE_INVALID")
    raw_results = value.get("results")
    if not isinstance(raw_results, list):
        raise TreeStoreError("TREE_STORE_INVALID")
    try:
        return ParallelConditionBatch(
            version=_require_int(value.get("version")),
            parallel_node_id=_require_str(value.get("parallel_node_id")),
            source_sequence=_require_sequence(value.get("source_sequence")),
            source_tree_digest=_require_digest(value.get("source_tree_digest")),
            snapshot_digest=_require_digest(value.get("snapshot_digest")),
            context_digest=_require_digest(value.get("context_digest")),
            disposition=ParallelBatchDisposition(
                _require_str(value.get("disposition"))
            ),
            results=tuple(_decode_parallel_result(item) for item in raw_results),
        )
    except (ParallelConditionContractError, ValueError) as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc


def _decode_tree(value: object, *, expected_run_id: str) -> TaskTree:
    if not isinstance(value, Mapping):
        raise TreeStoreError("TREE_STORE_INVALID")
    contract_version = _require_int(value.get("contract_version"))
    expected_fields = (
        _TREE_FIELDS_V1
        if contract_version == TREE_CONTRACT_VERSION
        else _TREE_FIELDS_V2
        if contract_version == TREE_CONTRACT_VERSION_V2
        else frozenset()
    )
    if not expected_fields or set(value) != expected_fields:
        raise TreeStoreError("TREE_STORE_INVALID")
    if value.get("run_id") != expected_run_id:
        raise TreeStoreError("TREE_STORE_IDENTITY_MISMATCH")
    raw_nodes = value.get("nodes")
    if not isinstance(raw_nodes, list):
        raise TreeStoreError("TREE_STORE_INVALID")
    try:
        tree = TaskTree(
            contract_version=contract_version,
            tree_id=_require_str(value.get("tree_id")),
            run_id=expected_run_id,
            task_digest=_require_digest(value.get("task_digest")),
            registry_digest=_require_digest(value.get("registry_digest")),
            policy_digest=_require_digest(value.get("policy_digest")),
            root_id=_require_str(value.get("root_id")),
            limits=_decode_limits(value.get("limits")),
            aggregate_budget=_decode_budget(value.get("aggregate_budget")),
            nodes=tuple(_decode_node(node) for node in raw_nodes),
            parallel_batches=(
                ()
                if contract_version == TREE_CONTRACT_VERSION
                else tuple(
                    _decode_parallel_batch(batch)
                    for batch in value.get("parallel_batches", [])
                )
                if isinstance(value.get("parallel_batches"), list)
                else (_raise_invalid_parallel_batches())
            ),
        )
    except TreeValidationError as exc:
        raise TreeStoreError("TREE_STORE_INVALID") from exc
    if tree.registry_digest != reviewed_registry_digest():
        raise TreeStoreError("TREE_STORE_REGISTRY_MISMATCH")
    return tree


def _envelope(tree: TaskTree, sequence: int) -> dict[str, object]:
    unsigned: dict[str, object] = {
        "store_version": TREE_STORE_VERSION,
        "sequence": sequence,
        "tree": tree.to_payload(),
        "tree_digest": tree.digest,
    }
    return {**unsigned, "envelope_digest": _digest(unsigned)}


def _decode_envelope(value: object, *, expected_run_id: str) -> PersistedTaskTree:
    if not isinstance(value, Mapping) or set(value) != _ENVELOPE_FIELDS:
        raise TreeStoreError("TREE_STORE_INVALID")
    store_version = value.get("store_version")
    if (
        not isinstance(store_version, int)
        or isinstance(store_version, bool)
        or store_version != TREE_STORE_VERSION
    ):
        raise TreeStoreError("TREE_STORE_VERSION_UNSUPPORTED")
    sequence = _require_sequence(value.get("sequence"))
    tree = _decode_tree(value.get("tree"), expected_run_id=expected_run_id)
    if _require_digest(value.get("tree_digest")) != tree.digest:
        raise TreeStoreError("TREE_STORE_DIGEST_MISMATCH")
    envelope_digest = _require_digest(value.get("envelope_digest"))
    unsigned = {key: item for key, item in value.items() if key != "envelope_digest"}
    if envelope_digest != _digest(unsigned):
        raise TreeStoreError("TREE_STORE_DIGEST_MISMATCH")
    return PersistedTaskTree(
        tree=tree,
        sequence=sequence,
        envelope_digest=envelope_digest,
    )


def _structure_payload(tree: TaskTree) -> dict[str, object]:
    payload = tree.to_payload()
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise TreeStoreError("TREE_STORE_INVALID")
    structural_nodes: list[dict[str, object]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise TreeStoreError("TREE_STORE_INVALID")
        structural_nodes.append({key: item for key, item in node.items() if key != "status"})
    return {
        key: item
        for key, item in payload.items()
        if key not in {"nodes", "parallel_batches"}
    } | {"nodes": structural_nodes}


def _raise_invalid_parallel_batches() -> tuple[ParallelConditionBatch, ...]:
    raise TreeStoreError("TREE_STORE_INVALID")


def _validate_parallel_batch_transition(current: TaskTree, updated: TaskTree) -> None:
    if updated.parallel_batches == current.parallel_batches:
        return
    if updated.contract_version != TREE_CONTRACT_VERSION_V2:
        raise TreeStoreError("TREE_STORE_STRUCTURE_MISMATCH")
    current_by_node = {batch.parallel_node_id: batch for batch in current.parallel_batches}
    updated_by_node = {batch.parallel_node_id: batch for batch in updated.parallel_batches}
    added = set(updated_by_node) - set(current_by_node)
    if (
        len(added) != 1
        or set(current_by_node) - set(updated_by_node)
        or any(updated_by_node[node_id] != batch for node_id, batch in current_by_node.items())
    ):
        raise TreeStoreError("TREE_STORE_STRUCTURE_MISMATCH")
    batch = updated_by_node[next(iter(added))]
    if batch.disposition is ParallelBatchDisposition.BLOCKED:
        raise TreeStoreError("TREE_STORE_STRUCTURE_MISMATCH")


class TaskTreeStore:
    """Run-lock-bound H2 storage with exact snapshot compare-and-swap."""

    def __init__(self, state_dir: Path, lock: RunLock) -> None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        if not isinstance(lock, RunLock):
            raise ValueError("lock must be a RunLock")
        self.state_dir = state_dir
        self.lock = lock

    def _require_lock(self) -> None:
        if not self.lock.acquired:
            raise TreeStoreError("TREE_STORE_LOCK_REQUIRED")

    def _path(self, run_id: str) -> Path:
        path = task_tree_path(self.state_dir, run_id)
        if (
            _is_unsafe_path(self.state_dir)
            or _is_unsafe_path(self.state_dir / "runs")
            or _is_unsafe_path(path.parent)
            or _is_unsafe_path(path)
        ):
            raise TreeStoreError("TREE_STORE_UNSAFE_PATH")
        return path

    def _read(self, run_id: str) -> PersistedTaskTree:
        path = self._path(run_id)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise TreeStoreError("TREE_STORE_READ_FAILED") from exc
        if not data or len(data) > MAX_PERSISTED_TREE_BYTES:
            raise TreeStoreError("TREE_STORE_READ_FAILED")
        try:
            value = json.loads(data)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise TreeStoreError("TREE_STORE_READ_FAILED") from exc
        return _decode_envelope(value, expected_run_id=run_id)

    def _write_checkpoint(self, stage: str) -> None:
        """Private deterministic fault-injection seam; production is a no-op."""

        if stage not in TREE_STORE_WRITE_CHECKPOINTS:
            raise TreeStoreError("TREE_STORE_INVALID_CHECKPOINT")

    def _write(self, snapshot: PersistedTaskTree, *, create: bool) -> PersistedTaskTree:
        payload = _envelope(snapshot.tree, snapshot.sequence)
        validated = _decode_envelope(payload, expected_run_id=snapshot.tree.run_id)
        encoded = _canonical(payload) + b"\n"
        if len(encoded) > MAX_PERSISTED_TREE_BYTES:
            raise TreeStoreError("TREE_STORE_TOO_LARGE")
        path = self._path(snapshot.tree.run_id)
        if create and path.exists():
            raise TreeStoreError("TREE_STORE_ALREADY_EXISTS")

        temporary: Path | None = None
        descriptor: int | None = None
        try:
            self._write_checkpoint("before_parent_create")
            path.parent.mkdir(parents=True, exist_ok=True)
            if _is_unsafe_path(path.parent) or _is_unsafe_path(path):
                raise TreeStoreError("TREE_STORE_UNSAFE_PATH")
            self._write_checkpoint("before_temp_create")
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".task-tree-", suffix=".tmp", dir=path.parent
            )
            temporary = Path(raw_path)
            self._write_checkpoint("before_temp_chmod")
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            self._write_checkpoint("before_write")
            with os.fdopen(descriptor, "wb") as file:
                descriptor = None
                file.write(encoded)
                self._write_checkpoint("before_flush")
                file.flush()
                self._write_checkpoint("before_fsync")
                os.fsync(file.fileno())
            self._write_checkpoint("before_create_recheck")
            if create and path.exists():
                raise TreeStoreError("TREE_STORE_ALREADY_EXISTS")
            self._write_checkpoint("before_replace")
            os.replace(temporary, path)
            temporary = None
            # No fallible operation follows commit. Permissions were fixed on
            # the temporary file and move with the atomic replacement.
        except TreeStoreError:
            raise
        except OSError as exc:
            raise TreeStoreError("TREE_STORE_WRITE_FAILED") from exc
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return validated

    def create(self, tree: TaskTree) -> PersistedTaskTree:
        """Persist one new all-pending inert tree without replacing state."""

        self._require_lock()
        if not isinstance(tree, TaskTree) or tree.status is not PlanStepStatus.PENDING:
            raise TreeStoreError("TREE_STORE_INITIAL_STATE_INVALID")
        if tree.registry_digest != reviewed_registry_digest():
            raise TreeStoreError("TREE_STORE_REGISTRY_MISMATCH")
        return self._write(
            PersistedTaskTree(tree=tree, sequence=0, envelope_digest="0" * 64),
            create=True,
        )

    def read(self, run_id: str) -> PersistedTaskTree:
        """Read one tree while the owning application run lock is held."""

        self._require_lock()
        return self._read(run_id)

    def compare_and_swap(
        self,
        run_id: str,
        updated_tree: TaskTree,
        *,
        expected_sequence: int,
        expected_tree_digest: str,
    ) -> PersistedTaskTree:
        """Persist one canonical status projection after exact CAS validation."""

        self._require_lock()
        _require_sequence(expected_sequence)
        _require_digest(expected_tree_digest)
        if not isinstance(updated_tree, TaskTree):
            raise TreeStoreError("TREE_STORE_INVALID")
        current = self._read(run_id)
        if (
            current.sequence != expected_sequence
            or current.tree.digest != expected_tree_digest
        ):
            raise TreeStoreError("TREE_STORE_STALE_WRITE")
        if updated_tree.run_id != run_id:
            raise TreeStoreError("TREE_STORE_IDENTITY_MISMATCH")
        if _structure_payload(updated_tree) != _structure_payload(current.tree):
            raise TreeStoreError("TREE_STORE_STRUCTURE_MISMATCH")
        _validate_parallel_batch_transition(current.tree, updated_tree)
        if updated_tree.parallel_batches != current.tree.parallel_batches:
            new_batches = tuple(
                batch
                for batch in updated_tree.parallel_batches
                if batch not in current.tree.parallel_batches
            )
            if (
                len(new_batches) != 1
                or new_batches[0].source_sequence != current.sequence
                or new_batches[0].source_tree_digest != current.tree.digest
            ):
                raise TreeStoreError("TREE_STORE_STALE_WRITE")
        if updated_tree.digest == current.tree.digest:
            raise TreeStoreError("TREE_STORE_NO_CHANGE")
        return self._write(
            PersistedTaskTree(
                tree=updated_tree,
                sequence=current.sequence + 1,
                envelope_digest="0" * 64,
            ),
            create=False,
        )


__all__ = [
    "MAX_PERSISTED_TREE_BYTES",
    "TREE_STORE_VERSION",
    "TREE_STORE_WRITE_CHECKPOINTS",
    "PersistedTaskTree",
    "TaskTreeStore",
    "TreeStoreError",
    "task_tree_path",
]
