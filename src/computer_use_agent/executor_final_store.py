"""Private WAL for one tool-free Executor final-response request.

This store is deliberately separate from normal provider continuation state so
crash recovery cannot mistake a plan final response for a resumable tool loop.
It performs no provider I/O and grants no execution or terminal authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Mapping

from .executor_final import FinalResponseRequest, FinalResponseResult
from .final_response_wire import MAX_FINAL_RESPONSE_TEXT_BYTES
from .run_lock import RunLock
from .types import ModelUsage


FINAL_RESPONSE_STORE_VERSION = 1
MAX_FINAL_RESPONSE_STORE_BYTES = 512 * 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class FinalResponseStoreError(RuntimeError):
    """Fixed persistence failure without sensitive response content."""


class FinalResponseStage(str, Enum):
    PREPARED = "prepared"
    DISPATCH_INTENT = "dispatch_intent"
    COMPLETED = "completed"


@dataclass(frozen=True, repr=False)
class PersistedFinalResponse:
    """Strict request binding and optional sensitive completed result."""

    run_id: str
    plan_id: str
    step_id: str
    turn_id: str
    request_digest: str
    stage: FinalResponseStage
    sequence: int
    envelope_digest: str
    result: FinalResponseResult | None = None

    def __repr__(self) -> str:
        return (
            "PersistedFinalResponse("
            f"run_id={self.run_id!r}, plan_id={self.plan_id!r}, "
            f"step_id={self.step_id!r}, turn_id={self.turn_id!r}, "
            f"stage={self.stage.value!r}, sequence={self.sequence}, "
            f"has_result={self.result is not None})"
        )


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identifier(value: object) -> str:
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    return value


def _sha(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    return value


def _response_id(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    return value


def _uint(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    return value


def _is_unsafe(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse)


def final_response_path(state_dir: Path, run_id: str) -> Path:
    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be absolute")
    return state_dir / "runs" / _identifier(run_id) / "final-response.json"


def _payload(snapshot: PersistedFinalResponse) -> dict[str, object]:
    response = None
    if snapshot.result is not None:
        response = {
            "provider_response_id": snapshot.result.provider_response_id,
            "text": snapshot.result.text,
            "input_tokens": snapshot.result.usage.input_tokens,
            "output_tokens": snapshot.result.usage.output_tokens,
        }
    unsigned = {
        "store_version": FINAL_RESPONSE_STORE_VERSION,
        "run_id": snapshot.run_id,
        "plan_id": snapshot.plan_id,
        "step_id": snapshot.step_id,
        "turn_id": snapshot.turn_id,
        "request_digest": snapshot.request_digest,
        "stage": snapshot.stage.value,
        "sequence": snapshot.sequence,
        "response": response,
    }
    return {**unsigned, "envelope_digest": _digest(unsigned)}


def _decode(value: object, *, expected_run_id: str) -> PersistedFinalResponse:
    fields = {
        "store_version",
        "run_id",
        "plan_id",
        "step_id",
        "turn_id",
        "request_digest",
        "stage",
        "sequence",
        "response",
        "envelope_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    if value["store_version"] != FINAL_RESPONSE_STORE_VERSION:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_VERSION_UNSUPPORTED")
    run_id = _identifier(value["run_id"])
    if run_id != expected_run_id:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_IDENTITY_MISMATCH")
    plan_id = _identifier(value["plan_id"])
    step_id = _identifier(value["step_id"])
    turn_id = _identifier(value["turn_id"])
    request_digest = _sha(value["request_digest"])
    try:
        stage = FinalResponseStage(value["stage"])
    except ValueError as exc:
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID") from exc
    sequence = _uint(value["sequence"])
    response = value["response"]
    result = None
    if stage is FinalResponseStage.COMPLETED:
        response_fields = {
            "provider_response_id",
            "text",
            "input_tokens",
            "output_tokens",
        }
        if not isinstance(response, Mapping) or set(response) != response_fields:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
        text = response["text"]
        try:
            text_size = len(text.encode("utf-8")) if isinstance(text, str) else -1
        except UnicodeError as exc:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID") from exc
        if not isinstance(text, str) or not text.strip() or text_size > MAX_FINAL_RESPONSE_TEXT_BYTES:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
        try:
            usage = ModelUsage(response["input_tokens"], response["output_tokens"])
            result = FinalResponseResult(
                run_id=run_id,
                turn_id=turn_id,
                provider_response_id=_response_id(response["provider_response_id"]),
                text=text,
                usage=usage,
            )
        except ValueError as exc:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID") from exc
        if sequence != 2:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    elif response is not None or sequence != (
        0 if stage is FinalResponseStage.PREPARED else 1
    ):
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
    supplied = _sha(value["envelope_digest"])
    unsigned = {key: item for key, item in value.items() if key != "envelope_digest"}
    if supplied != _digest(unsigned):
        raise FinalResponseStoreError("FINAL_RESPONSE_STORE_DIGEST_MISMATCH")
    return PersistedFinalResponse(
        run_id=run_id,
        plan_id=plan_id,
        step_id=step_id,
        turn_id=turn_id,
        request_digest=request_digest,
        stage=stage,
        sequence=sequence,
        envelope_digest=supplied,
        result=result,
    )


class FinalResponseStore:
    """Run-lock-bound atomic WAL with strict prepared/intent/completed CAS."""

    def __init__(self, state_dir: Path, lock: RunLock) -> None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("state_dir must be absolute")
        if not isinstance(lock, RunLock):
            raise ValueError("lock must be RunLock")
        self.state_dir = state_dir
        self.lock = lock

    def _require_lock(self) -> None:
        if not self.lock.acquired:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_LOCK_REQUIRED")

    def _path(self, run_id: str) -> Path:
        path = final_response_path(self.state_dir, run_id)
        if any(
            _is_unsafe(item)
            for item in (self.state_dir, self.state_dir / "runs", path.parent, path)
        ):
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_UNSAFE_PATH")
        return path

    def _write(self, snapshot: PersistedFinalResponse, *, create: bool) -> PersistedFinalResponse:
        payload = _payload(snapshot)
        validated = _decode(payload, expected_run_id=snapshot.run_id)
        encoded = _canonical(payload) + b"\n"
        if len(encoded) > MAX_FINAL_RESPONSE_STORE_BYTES:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_TOO_LARGE")
        path = self._path(snapshot.run_id)
        if create and path.exists():
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_ALREADY_EXISTS")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".final-response-", suffix=".tmp", dir=path.parent
            )
            temporary = Path(raw_path)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            if create and path.exists():
                raise FinalResponseStoreError("FINAL_RESPONSE_STORE_ALREADY_EXISTS")
            os.replace(temporary, path)
            temporary = None
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except FinalResponseStoreError:
            raise
        except OSError as exc:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_WRITE_FAILED") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return validated

    def read(self, run_id: str) -> PersistedFinalResponse:
        self._require_lock()
        path = self._path(run_id)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_READ_FAILED") from exc
        if not data or len(data) > MAX_FINAL_RESPONSE_STORE_BYTES:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_READ_FAILED")
        try:
            value = json.loads(data)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_READ_FAILED") from exc
        return _decode(value, expected_run_id=run_id)

    def create(self, request: FinalResponseRequest, *, step_id: str) -> PersistedFinalResponse:
        self._require_lock()
        if not isinstance(request, FinalResponseRequest):
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
        return self._write(
            PersistedFinalResponse(
                run_id=request.run_id,
                plan_id=request.plan_id,
                step_id=_identifier(step_id),
                turn_id=request.turn_id,
                request_digest=request.request_digest,
                stage=FinalResponseStage.PREPARED,
                sequence=0,
                envelope_digest="0" * 64,
            ),
            create=True,
        )

    def mark_dispatch_intent(
        self, run_id: str, *, expected_sequence: int, expected_digest: str
    ) -> PersistedFinalResponse:
        return self._transition(
            run_id,
            FinalResponseStage.DISPATCH_INTENT,
            expected_sequence=expected_sequence,
            expected_digest=expected_digest,
        )

    def complete(
        self,
        run_id: str,
        result: FinalResponseResult,
        *,
        expected_sequence: int,
        expected_digest: str,
    ) -> PersistedFinalResponse:
        if not isinstance(result, FinalResponseResult):
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_INVALID")
        current = self._current(run_id, expected_sequence, expected_digest)
        if current.stage is not FinalResponseStage.DISPATCH_INTENT:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_TRANSITION_INVALID")
        if result.run_id != current.run_id or result.turn_id != current.turn_id:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_IDENTITY_MISMATCH")
        return self._write(
            PersistedFinalResponse(
                **{
                    **current.__dict__,
                    "stage": FinalResponseStage.COMPLETED,
                    "sequence": current.sequence + 1,
                    "envelope_digest": "0" * 64,
                    "result": result,
                }
            ),
            create=False,
        )

    def _current(
        self, run_id: str, expected_sequence: int, expected_digest: str
    ) -> PersistedFinalResponse:
        self._require_lock()
        _uint(expected_sequence)
        _sha(expected_digest)
        current = self.read(run_id)
        if current.sequence != expected_sequence or current.envelope_digest != expected_digest:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_STALE_WRITE")
        return current

    def _transition(
        self,
        run_id: str,
        target: FinalResponseStage,
        *,
        expected_sequence: int,
        expected_digest: str,
    ) -> PersistedFinalResponse:
        current = self._current(run_id, expected_sequence, expected_digest)
        if current.stage is not FinalResponseStage.PREPARED or target is not FinalResponseStage.DISPATCH_INTENT:
            raise FinalResponseStoreError("FINAL_RESPONSE_STORE_TRANSITION_INVALID")
        return self._write(
            PersistedFinalResponse(
                **{
                    **current.__dict__,
                    "stage": target,
                    "sequence": current.sequence + 1,
                    "envelope_digest": "0" * 64,
                }
            ),
            create=False,
        )


__all__ = [
    "FINAL_RESPONSE_STORE_VERSION",
    "MAX_FINAL_RESPONSE_STORE_BYTES",
    "FinalResponseStage",
    "FinalResponseStore",
    "FinalResponseStoreError",
    "PersistedFinalResponse",
    "final_response_path",
]
