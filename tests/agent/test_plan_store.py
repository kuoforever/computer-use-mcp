from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from computer_use_agent.plan_store import (
    MAX_PERSISTED_PLAN_BYTES,
    PLAN_STORE_VERSION,
    PlanStoreError,
    TaskPlanStore,
    task_plan_path,
)
from computer_use_agent.planning import (
    PlanStepStatus,
    TaskPlan,
    compile_task_plan,
)
from computer_use_agent.run_lock import RunLock


TASK = "Inspect the active window without changing it"


def _plan(*, run_id: str = "run_1", plan_id: str = "plan_1") -> TaskPlan:
    return compile_task_plan(
        json.dumps(
            {
                "version": 1,
                "steps": [
                    {"action": "tool", "tool": "ui_snapshot", "arguments": {}},
                    {"action": "final_response"},
                ],
            }
        ),
        plan_id=plan_id,
        run_id=run_id,
        task=TASK,
        allowed_tools=("ui_snapshot",),
    )


def _locked_store(tmp_path: Path) -> tuple[TaskPlanStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    return TaskPlanStore(tmp_path / "state", lock), lock


def test_private_plan_round_trip_is_bounded_digest_bound_and_task_free(
    tmp_path: Path,
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_plan())
        loaded = store.read("run_1")
        path = task_plan_path((tmp_path / "state").resolve(), "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))

        assert created == loaded
        assert created.sequence == 0
        assert created.plan.digest == payload["plan_digest"]
        assert payload["store_version"] == PLAN_STORE_VERSION
        assert len(created.envelope_digest) == 64
        assert TASK not in path.read_text(encoding="utf-8")
        assert len(path.read_bytes()) <= MAX_PERSISTED_PLAN_BYTES
        if os.name != "nt":
            assert path.stat().st_mode & 0o777 == 0o600
    finally:
        lock.release()


def test_transition_is_sequence_and_digest_compare_and_swap(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_plan())
        running = store.transition(
            "run_1",
            "step_1",
            PlanStepStatus.IN_PROGRESS,
            expected_sequence=created.sequence,
            expected_plan_digest=created.plan.digest,
        )

        assert running.sequence == 1
        assert running.plan.steps[0].status is PlanStepStatus.IN_PROGRESS
        assert running.plan.digest != created.plan.digest

        before = task_plan_path((tmp_path / "state").resolve(), "run_1").read_bytes()
        with pytest.raises(PlanStoreError, match="PLAN_STORE_STALE_WRITE"):
            store.transition(
                "run_1",
                "step_1",
                PlanStepStatus.COMPLETED,
                expected_sequence=created.sequence,
                expected_plan_digest=created.plan.digest,
            )
        assert task_plan_path((tmp_path / "state").resolve(), "run_1").read_bytes() == before
    finally:
        lock.release()


def test_store_requires_the_application_run_lock_for_every_operation(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "application")
    store = TaskPlanStore((tmp_path / "state").resolve(), lock)

    with pytest.raises(PlanStoreError, match="PLAN_STORE_LOCK_REQUIRED"):
        store.create(_plan())
    lock.acquire()
    created = store.create(_plan())
    lock.release()
    with pytest.raises(PlanStoreError, match="PLAN_STORE_LOCK_REQUIRED"):
        store.read(created.plan.run_id)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload.update({"store_version": 1.0}),
        lambda payload: payload.update({"plan_digest": "0" * 64}),
        lambda payload: payload["plan"].update({"registry_digest": "0" * 64}),
        lambda payload: payload["plan"].update({"run_id": "run_other"}),
        lambda payload: payload.update({"sequence": True}),
    ],
)
def test_reader_rejects_unknown_tampered_drifted_or_mismatched_state(
    tmp_path: Path, mutation: object
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_plan())
        path = task_plan_path((tmp_path / "state").resolve(), "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutation(payload)  # type: ignore[operator]
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(PlanStoreError):
            store.read("run_1")
    finally:
        lock.release()


def test_create_never_replaces_an_existing_plan(tmp_path: Path) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        store.create(_plan())
        path = task_plan_path((tmp_path / "state").resolve(), "run_1")
        before = path.read_bytes()

        with pytest.raises(PlanStoreError, match="PLAN_STORE_ALREADY_EXISTS"):
            store.create(_plan(plan_id="plan_other"))
        assert path.read_bytes() == before
    finally:
        lock.release()


def test_failed_atomic_replace_preserves_the_previous_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_plan())
        path = task_plan_path((tmp_path / "state").resolve(), "run_1")
        before = path.read_bytes()

        def fail_replace(_source: object, _target: object) -> None:
            raise OSError("synthetic replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(PlanStoreError, match="PLAN_STORE_WRITE_FAILED"):
            store.transition(
                "run_1",
                "step_1",
                PlanStepStatus.IN_PROGRESS,
                expected_sequence=created.sequence,
                expected_plan_digest=created.plan.digest,
            )

        assert path.read_bytes() == before
        assert not tuple(path.parent.glob(".task-plan-*.tmp"))
    finally:
        lock.release()


def test_paths_and_illegal_transitions_fail_closed(tmp_path: Path) -> None:
    with pytest.raises((ValueError, PlanStoreError)):
        task_plan_path((tmp_path / "state").resolve(), "../escape")
    with pytest.raises((ValueError, PlanStoreError)):
        task_plan_path((tmp_path / "state").resolve(), "run:invalid")

    store, lock = _locked_store(tmp_path)
    try:
        created = store.create(_plan())
        with pytest.raises(PlanStoreError, match="PLAN_STORE_TRANSITION_INVALID"):
            store.transition(
                "run_1",
                "step_2",
                PlanStepStatus.IN_PROGRESS,
                expected_sequence=created.sequence,
                expected_plan_digest=created.plan.digest,
            )
    finally:
        lock.release()
