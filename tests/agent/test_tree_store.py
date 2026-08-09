from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

import computer_use_agent.tree_store as tree_store_module
from computer_use_agent.hierarchical_control import (
    TaskTree,
    project_linear_plan,
    reduce_tree_statuses,
)
from computer_use_agent.planning import PlanStepStatus, compile_task_plan
from computer_use_agent.run_lock import RunLock
from computer_use_agent.tree_store import (
    MAX_PERSISTED_TREE_BYTES,
    TREE_STORE_VERSION,
    TREE_STORE_WRITE_CHECKPOINTS,
    TaskTreeStore,
    TreeStoreError,
    task_tree_path,
)


TASK = "Inspect the active window without changing it"
POLICY_DIGEST = "a" * 64


def _tree(*, run_id: str = "run_1", tree_id: str = "tree_1") -> TaskTree:
    plan = compile_task_plan(
        json.dumps(
            {
                "version": 1,
                "steps": [
                    {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
                    {"action": "final_response"},
                ],
            }
        ),
        plan_id="plan_1",
        run_id=run_id,
        task=TASK,
        allowed_tools=("ui_snapshot",),
    )
    return project_linear_plan(
        plan,
        tree_id=tree_id,
        policy_digest=POLICY_DIGEST,
    )


def _locked_store(tmp_path: Path) -> tuple[TaskTreeStore, RunLock]:
    lock = RunLock((tmp_path / "application").resolve())
    lock.acquire()
    return TaskTreeStore((tmp_path / "state").resolve(), lock), lock


def _path(tmp_path: Path) -> Path:
    return task_tree_path((tmp_path / "state").resolve(), "run_1")


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


def _running(tree: TaskTree) -> TaskTree:
    return reduce_tree_statuses(
        tree,
        {"node_step_1": PlanStepStatus.IN_PROGRESS},
    )


def test_private_tree_round_trip_is_bounded_digest_bound_and_task_free(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        loaded = store.read("run_1")
        path = _path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert created == loaded
        assert created.sequence == 0
        assert created.tree.digest == payload["tree_digest"]
        assert payload["store_version"] == TREE_STORE_VERSION
        assert len(created.envelope_digest) == 64
        assert TASK not in path.read_text(encoding="utf-8")
        assert len(path.read_bytes()) <= MAX_PERSISTED_TREE_BYTES
        assert not hasattr(store, "dispatch")
        assert not hasattr(store, "authorized")
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        lock.release()


def test_compare_and_swap_binds_sequence_and_tree_digest(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        running = store.compare_and_swap(
            "run_1",
            _running(created.tree),
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
        )

        assert running.sequence == 1
        assert running.tree.status is PlanStepStatus.IN_PROGRESS
        assert running.tree.digest != created.tree.digest

        before = _path(tmp_path).read_bytes()
        with pytest.raises(TreeStoreError, match="TREE_STORE_STALE_WRITE"):
            store.compare_and_swap(
                "run_1",
                reduce_tree_statuses(
                    running.tree,
                    {"node_step_1": PlanStepStatus.COMPLETED},
                ),
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )
        assert _path(tmp_path).read_bytes() == before
    finally:
        lock.release()


def test_store_requires_the_application_run_lock_for_every_operation(
    tmp_path: Path,
) -> None:
    lock = RunLock((tmp_path / "application").resolve())
    store = TaskTreeStore((tmp_path / "state").resolve(), lock)

    with pytest.raises(TreeStoreError, match="TREE_STORE_LOCK_REQUIRED"):
        store.create(_tree())
    lock.acquire()
    created = store.create(_tree())
    lock.release()
    with pytest.raises(TreeStoreError, match="TREE_STORE_LOCK_REQUIRED"):
        store.read(created.tree.run_id)
    with pytest.raises(TreeStoreError, match="TREE_STORE_LOCK_REQUIRED"):
        store.compare_and_swap(
            "run_1",
            _running(created.tree),
            expected_sequence=created.sequence,
            expected_tree_digest=created.tree.digest,
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.update({"store_version": 1.0}),
        lambda payload: payload.update({"tree_digest": "0" * 64}),
        lambda payload: payload.update({"envelope_digest": "0" * 64}),
        lambda payload: payload["tree"].update({"registry_digest": "0" * 64}),
        lambda payload: payload["tree"].update({"run_id": "run_other"}),
        lambda payload: payload.update({"sequence": True}),
        lambda payload: payload["tree"]["nodes"][0].update({"unknown": True}),
        lambda payload: payload["tree"]["nodes"][-1].update(
            {"status": PlanStepStatus.COMPLETED.value}
        ),
    ],
)
def test_reader_rejects_unknown_tampered_drifted_or_noncanonical_state(
    tmp_path: Path, mutation: Callable[[dict[str, object]], None]
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_tree())
        path = _path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutation(payload)
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(TreeStoreError):
            store.read("run_1")
    finally:
        lock.release()


def test_reader_rejects_registry_drift_even_with_valid_digests(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_tree())
        path = _path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tree"]["registry_digest"] = "0" * 64
        _resign(payload)
        path.write_bytes(_canonical(payload) + b"\n")

        with pytest.raises(TreeStoreError, match="TREE_STORE_REGISTRY_MISMATCH"):
            store.read("run_1")
    finally:
        lock.release()


def test_v1_reader_rejects_resigned_h8a_fields(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_tree())
        path = _path(tmp_path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tree"]["parallel_batches"] = []
        _resign(payload)
        path.write_bytes(_canonical(payload) + b"\n")

        with pytest.raises(TreeStoreError, match="TREE_STORE_INVALID"):
            store.read("run_1")
    finally:
        lock.release()


def test_current_registry_drift_rejects_create_and_restart_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        tree = _tree()
        store.create(tree)
        monkeypatch.setattr(
            tree_store_module,
            "reviewed_registry_digest",
            lambda: "0" * 64,
        )
        with pytest.raises(TreeStoreError, match="TREE_STORE_REGISTRY_MISMATCH"):
            store.read("run_1")
        with pytest.raises(TreeStoreError, match="TREE_STORE_REGISTRY_MISMATCH"):
            store.create(replace(tree, run_id="run_2", tree_id="tree_2"))
    finally:
        lock.release()


def test_create_never_replaces_an_existing_tree(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_tree())
        before = _path(tmp_path).read_bytes()

        with pytest.raises(TreeStoreError, match="TREE_STORE_ALREADY_EXISTS"):
            store.create(_tree(tree_id="tree_other"))
        assert _path(tmp_path).read_bytes() == before
    finally:
        lock.release()


@pytest.mark.parametrize(
    "variant",
    [
        lambda tree: replace(tree, tree_id="tree_other"),
        lambda tree: replace(tree, policy_digest="b" * 64),
        lambda tree: replace(
            tree,
            limits=replace(tree.limits, max_visits=tree.limits.max_visits + 1),
        ),
        lambda tree: replace(
            tree,
            aggregate_budget=replace(tree.aggregate_budget, tokens=1),
        ),
    ],
)
def test_compare_and_swap_rejects_every_non_status_structure_change(
    tmp_path: Path, variant: Callable[[TaskTree], TaskTree]
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        changed = variant(_running(created.tree))
        before = _path(tmp_path).read_bytes()

        with pytest.raises(TreeStoreError, match="TREE_STORE_STRUCTURE_MISMATCH"):
            store.compare_and_swap(
                "run_1",
                changed,
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )
        assert _path(tmp_path).read_bytes() == before
    finally:
        lock.release()


def test_compare_and_swap_rejects_identity_drift_and_no_change(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        before = _path(tmp_path).read_bytes()
        with pytest.raises(TreeStoreError, match="TREE_STORE_IDENTITY_MISMATCH"):
            store.compare_and_swap(
                "run_1",
                _running(_tree(run_id="run_other")),
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )
        with pytest.raises(TreeStoreError, match="TREE_STORE_NO_CHANGE"):
            store.compare_and_swap(
                "run_1",
                created.tree,
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )
        assert _path(tmp_path).read_bytes() == before
    finally:
        lock.release()


@pytest.mark.parametrize("checkpoint", TREE_STORE_WRITE_CHECKPOINTS)
def test_each_update_persistence_checkpoint_preserves_the_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        path = _path(tmp_path)
        before = path.read_bytes()

        def fail_at(stage: str) -> None:
            if stage == checkpoint:
                raise OSError(f"synthetic crash at {stage}")

        monkeypatch.setattr(store, "_write_checkpoint", fail_at)
        with pytest.raises(TreeStoreError, match="TREE_STORE_WRITE_FAILED"):
            store.compare_and_swap(
                "run_1",
                _running(created.tree),
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )

        assert path.read_bytes() == before
        assert not tuple(path.parent.glob(".task-tree-*.tmp"))
    finally:
        lock.release()


@pytest.mark.parametrize("checkpoint", TREE_STORE_WRITE_CHECKPOINTS)
def test_each_create_persistence_checkpoint_leaves_no_partial_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, checkpoint: str
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        path = _path(tmp_path)

        def fail_at(stage: str) -> None:
            if stage == checkpoint:
                raise OSError(f"synthetic crash at {stage}")

        monkeypatch.setattr(store, "_write_checkpoint", fail_at)
        with pytest.raises(TreeStoreError, match="TREE_STORE_WRITE_FAILED"):
            store.create(_tree())

        assert not path.exists()
        if path.parent.exists():
            assert not tuple(path.parent.glob(".task-tree-*.tmp"))
    finally:
        lock.release()


def test_failed_atomic_replace_preserves_the_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_tree())
        path = _path(tmp_path)
        before = path.read_bytes()

        def fail_replace(_source: object, _target: object) -> None:
            raise OSError("synthetic replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(TreeStoreError, match="TREE_STORE_WRITE_FAILED"):
            store.compare_and_swap(
                "run_1",
                _running(created.tree),
                expected_sequence=created.sequence,
                expected_tree_digest=created.tree.digest,
            )

        assert path.read_bytes() == before
        assert not tuple(path.parent.glob(".task-tree-*.tmp"))
    finally:
        lock.release()


def test_restart_reads_the_last_committed_snapshot(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    created = store.create(_tree())
    running = store.compare_and_swap(
        "run_1",
        _running(created.tree),
        expected_sequence=created.sequence,
        expected_tree_digest=created.tree.digest,
    )
    lock.release()

    restarted_lock = RunLock((tmp_path / "application").resolve())
    restarted_lock.acquire()
    try:
        restarted = TaskTreeStore((tmp_path / "state").resolve(), restarted_lock)
        assert restarted.read("run_1") == running
    finally:
        restarted_lock.release()


def test_paths_malformed_and_oversized_state_fail_closed(tmp_path: Path) -> None:
    with pytest.raises((ValueError, TreeStoreError)):
        task_tree_path((tmp_path / "state").resolve(), "../escape")
    with pytest.raises((ValueError, TreeStoreError)):
        task_tree_path((tmp_path / "state").resolve(), "run:invalid")

    store, lock = _locked_store(tmp_path)
    try:
        store.create(_tree())
        path = _path(tmp_path)
        path.write_bytes(b"{")
        with pytest.raises(TreeStoreError, match="TREE_STORE_READ_FAILED"):
            store.read("run_1")

        path.write_bytes(b"x" * (MAX_PERSISTED_TREE_BYTES + 1))
        with pytest.raises(TreeStoreError, match="TREE_STORE_READ_FAILED"):
            store.read("run_1")
    finally:
        lock.release()
