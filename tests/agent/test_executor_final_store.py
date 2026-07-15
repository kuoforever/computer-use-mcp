from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from computer_use_agent.executor_final import (
    FinalResponseObservation,
    FinalResponseRequest,
    FinalResponseResult,
)
from computer_use_agent.executor_final_store import (
    FINAL_RESPONSE_STORE_VERSION,
    FinalResponseStage,
    FinalResponseStore,
    FinalResponseStoreError,
    final_response_path,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.types import ModelUsage


SECRET = "sensitive final response"
CONTINUATION_DIGEST = "b" * 64


def _request() -> FinalResponseRequest:
    observations = (
        FinalResponseObservation("step_1", "ui_snapshot", "{}", "observed"),
    )
    material = {
        "version": 1,
        "run_id": "run_1",
        "plan_id": "plan_1",
        "plan_digest": "a" * 64,
        "snapshot_sequence": 2,
        "turn_id": "executor_final_1",
        "task": "Inspect the UI",
        "observations": [
            {
                "step_id": "step_1",
                "tool_name": "ui_snapshot",
                "arguments": {},
                "sanitized_text": "observed",
                "images": [],
            }
        ],
    }
    digest = sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return FinalResponseRequest(
        run_id="run_1",
        plan_id="plan_1",
        plan_digest="a" * 64,
        snapshot_sequence=2,
        turn_id="executor_final_1",
        task="Inspect the UI",
        observations=observations,
        request_digest=digest,
    )


def _result(**changes: object) -> FinalResponseResult:
    values: dict[str, object] = {
        "run_id": "run_1",
        "turn_id": "executor_final_1",
        "provider_response_id": "resp_1",
        "text": SECRET,
        "usage": ModelUsage(10, 5),
    }
    values.update(changes)
    return FinalResponseResult(**values)  # type: ignore[arg-type]


def _store(tmp_path: Path) -> tuple[FinalResponseStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    return FinalResponseStore((tmp_path / "state").resolve(), lock), lock


def _create(store: FinalResponseStore):
    return store.create(
        _request(),
        step_id="step_2",
        checkpoint_sequence=4,
        continuation_digest=CONTINUATION_DIGEST,
    )


def test_final_response_wal_round_trip_and_exact_transitions(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        prepared = _create(store)
        assert prepared.stage is FinalResponseStage.PREPARED
        assert prepared.sequence == 0
        assert prepared.result is None
        assert prepared.plan_digest == "a" * 64
        assert prepared.snapshot_sequence == 2
        assert prepared.checkpoint_sequence == 4
        assert prepared.continuation_digest == CONTINUATION_DIGEST

        intent = store.mark_dispatch_intent(
            "run_1",
            expected_sequence=prepared.sequence,
            expected_digest=prepared.envelope_digest,
        )
        assert intent.stage is FinalResponseStage.DISPATCH_INTENT
        assert intent.sequence == 1
        assert intent.result is None

        completed = store.complete(
            "run_1",
            _result(),
            provider_latency_ms=17,
            expected_sequence=intent.sequence,
            expected_digest=intent.envelope_digest,
        )
        loaded = store.read("run_1")
    finally:
        lock.release()

    assert loaded == completed
    assert completed.stage is FinalResponseStage.COMPLETED
    assert completed.sequence == 2
    assert completed.result is not None
    assert completed.result.text == SECRET
    assert completed.provider_latency_ms == 17
    assert SECRET not in repr(completed)
    assert SECRET not in repr(completed.result)
    path = final_response_path((tmp_path / "state").resolve(), "run_1")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["store_version"] == FINAL_RESPONSE_STORE_VERSION
    assert payload["response"]["text"] == SECRET
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


def test_store_requires_lock_and_never_replaces_existing_wal(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "application")
    store = FinalResponseStore((tmp_path / "state").resolve(), lock)
    with pytest.raises(FinalResponseStoreError, match="LOCK_REQUIRED"):
        _create(store)

    lock.acquire()
    try:
        _create(store)
        with pytest.raises(FinalResponseStoreError, match="ALREADY_EXISTS"):
            _create(store)
    finally:
        lock.release()


def test_stale_or_illegal_transition_leaves_disk_unchanged(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        prepared = _create(store)
        path = final_response_path(store.state_dir, "run_1")
        before = path.read_bytes()
        with pytest.raises(FinalResponseStoreError, match="STALE_WRITE"):
            store.mark_dispatch_intent(
                "run_1",
                expected_sequence=1,
                expected_digest=prepared.envelope_digest,
            )
        assert path.read_bytes() == before
        with pytest.raises(FinalResponseStoreError, match="TRANSITION_INVALID"):
            store.complete(
                "run_1",
                _result(),
                provider_latency_ms=1,
                expected_sequence=prepared.sequence,
                expected_digest=prepared.envelope_digest,
            )
        assert path.read_bytes() == before
    finally:
        lock.release()


def test_result_identity_mismatch_does_not_complete_intent(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        prepared = _create(store)
        intent = store.mark_dispatch_intent(
            "run_1",
            expected_sequence=0,
            expected_digest=prepared.envelope_digest,
        )
        path = final_response_path(store.state_dir, "run_1")
        before = path.read_bytes()
        with pytest.raises(FinalResponseStoreError, match="IDENTITY_MISMATCH"):
            store.complete(
                "run_1",
                _result(turn_id="different"),
                provider_latency_ms=1,
                expected_sequence=intent.sequence,
                expected_digest=intent.envelope_digest,
            )
        assert path.read_bytes() == before
    finally:
        lock.release()


@pytest.mark.parametrize("field", ["stage", "sequence", "response", "digest"])
def test_corrupt_or_forged_wal_fails_closed(tmp_path: Path, field: str) -> None:
    store, lock = _store(tmp_path)
    try:
        _create(store)
        path = final_response_path(store.state_dir, "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if field == "stage":
            payload["stage"] = "completed"
        elif field == "sequence":
            payload["sequence"] = 99
        elif field == "response":
            payload["response"] = {"text": SECRET}
        else:
            payload["envelope_digest"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(FinalResponseStoreError):
            store.read("run_1")
    finally:
        lock.release()


def test_create_rejects_zero_checkpoint_before_writing(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        with pytest.raises(FinalResponseStoreError, match="INVALID"):
            store.create(
                _request(),
                step_id="step_2",
                checkpoint_sequence=0,
                continuation_digest=CONTINUATION_DIGEST,
            )
        assert not final_response_path(store.state_dir, "run_1").exists()
    finally:
        lock.release()


def test_legacy_final_response_wal_fails_closed(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        _create(store)
        path = final_response_path(store.state_dir, "run_1")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["store_version"] = 1
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(FinalResponseStoreError, match="VERSION_UNSUPPORTED"):
            store.read("run_1")
    finally:
        lock.release()
