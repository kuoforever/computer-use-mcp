"""Strict local Pause/Takeover/Resume control for one live Agent run.

The control record is a small Host-owned coordination lane.  It contains no
task, provider, desktop, approval, screenshot, or tool-result content and it
never dispatches work.  The live Runner remains the only process that may
acknowledge a safe pause or regain desktop authority.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Mapping, Protocol, runtime_checkable
from uuid import uuid4

from .atomic_file import publish_atomically, read_shared_bytes
from .run_lock import RunLock, RunLockError, is_run_lock_held
from .trace import RunPhase, TraceError, read_run_checkpoint
from .types import JSONValue


COOPERATIVE_CONTROL_VERSION = 1
MAX_COOPERATIVE_CONTROL_BYTES = 16 * 1024
MAX_CONTROL_RUNS = 10_000
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset(
    {
        "cooperative_control_version",
        "run_id",
        "owner_token_digest",
        "runner_state_path",
        "sequence",
        "status",
        "request_kind",
        "request_id",
        "authority",
        "fresh_observation_required",
        "boundary",
        "checkpoint_sequence",
        "outcome",
        "created_at",
        "updated_at",
    }
)


class CooperativeControlError(RuntimeError):
    """Fixed cooperative-control failure without persisted content."""


class ControlStatus(str, Enum):
    ACTIVE = "active"
    PAUSE_REQUESTED = "pause_requested"
    PAUSED = "paused"
    RESUME_REQUESTED = "resume_requested"
    RESUMING = "resuming"
    CLOSED = "closed"


class ControlRequestKind(str, Enum):
    PAUSE = "pause"
    TAKEOVER = "takeover"


class DesktopControlAuthority(str, Enum):
    AGENT = "agent"
    RELEASED = "released"
    NONE = "none"


class ControlBoundary(str, Enum):
    BEFORE_PROVIDER = "before_provider"
    BEFORE_TOOL = "before_tool"
    AFTER_APPROVAL = "after_approval"


class ControlOutcome(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STOPPED = "stopped"
    UNKNOWN_OUTCOME = "unknown_outcome"


@dataclass(frozen=True)
class ControlRequest:
    request_id: str
    kind: ControlRequestKind

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or _SAFE_ID.fullmatch(self.request_id) is None:
            raise CooperativeControlError("COOPERATIVE_CONTROL_REQUEST_INVALID")
        if not isinstance(self.kind, ControlRequestKind):
            raise CooperativeControlError("COOPERATIVE_CONTROL_REQUEST_INVALID")


def _timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
    return parsed


@dataclass(frozen=True)
class CooperativeControlSnapshot:
    run_id: str
    owner_token_digest: str
    runner_state_path: str
    sequence: int
    status: ControlStatus
    request_kind: ControlRequestKind | None
    request_id: str | None
    authority: DesktopControlAuthority
    fresh_observation_required: bool
    boundary: ControlBoundary | None
    checkpoint_sequence: int | None
    outcome: ControlOutcome | None
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or _RUN_ID.fullmatch(self.run_id) is None:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if (
            not isinstance(self.owner_token_digest, str)
            or _DIGEST.fullmatch(self.owner_token_digest) is None
            or not isinstance(self.runner_state_path, str)
            or len(self.runner_state_path) > 1024
            or "\\" in self.runner_state_path
            or isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 1
            or not isinstance(self.status, ControlStatus)
            or not isinstance(self.authority, DesktopControlAuthority)
            or not isinstance(self.fresh_observation_required, bool)
        ):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        state_path = PurePosixPath(self.runner_state_path)
        if self.runner_state_path != "." and (
            state_path.is_absolute()
            or not state_path.parts
            or any(part in {"", ".", ".."} or ":" in part for part in state_path.parts)
        ):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        created = _timestamp(self.created_at)
        updated = _timestamp(self.updated_at)
        if updated < created:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if (self.request_kind is None) != (self.request_id is None):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if self.request_kind is not None and not isinstance(
            self.request_kind, ControlRequestKind
        ):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if self.request_id is not None and _SAFE_ID.fullmatch(self.request_id) is None:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if self.boundary is not None and not isinstance(self.boundary, ControlBoundary):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if self.checkpoint_sequence is not None and (
            isinstance(self.checkpoint_sequence, bool)
            or not isinstance(self.checkpoint_sequence, int)
            or self.checkpoint_sequence < 1
        ):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        if self.outcome is not None and not isinstance(self.outcome, ControlOutcome):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")

        request = self.request_kind is not None
        paused_evidence = self.boundary is not None and self.checkpoint_sequence is not None
        if self.status is ControlStatus.ACTIVE:
            valid = (
                not request
                and self.authority is DesktopControlAuthority.AGENT
                and not self.fresh_observation_required
                and not paused_evidence
                and self.outcome is None
            )
        elif self.status is ControlStatus.PAUSE_REQUESTED:
            valid = (
                request
                and self.authority is DesktopControlAuthority.AGENT
                and not self.fresh_observation_required
                and not paused_evidence
                and self.outcome is None
            )
        elif self.status in {ControlStatus.PAUSED, ControlStatus.RESUME_REQUESTED}:
            valid = (
                request
                and self.authority is DesktopControlAuthority.RELEASED
                and self.fresh_observation_required
                and paused_evidence
                and self.outcome is None
            )
        elif self.status is ControlStatus.RESUMING:
            valid = (
                request
                and self.authority is DesktopControlAuthority.AGENT
                and self.fresh_observation_required
                and paused_evidence
                and self.outcome is None
            )
        else:
            valid = self.authority is DesktopControlAuthority.NONE and self.outcome is not None
        if not valid:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")

    @property
    def request(self) -> ControlRequest | None:
        if self.request_id is None or self.request_kind is None:
            return None
        return ControlRequest(self.request_id, self.request_kind)

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "cooperative_control_version": COOPERATIVE_CONTROL_VERSION,
            "run_id": self.run_id,
            "owner_token_digest": self.owner_token_digest,
            "runner_state_path": self.runner_state_path,
            "sequence": self.sequence,
            "status": self.status.value,
            "request_kind": (
                None if self.request_kind is None else self.request_kind.value
            ),
            "request_id": self.request_id,
            "authority": self.authority.value,
            "fresh_observation_required": self.fresh_observation_required,
            "boundary": None if self.boundary is None else self.boundary.value,
            "checkpoint_sequence": self.checkpoint_sequence,
            "outcome": None if self.outcome is None else self.outcome.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@runtime_checkable
class CooperativeControlPort(Protocol):
    """Runner-facing coordination only; this port has no desktop authority."""

    def start(
        self, run_id: str, *, owner_token: str, runner_state_dir: Path
    ) -> None: ...

    def pending_request(self, run_id: str) -> ControlRequest | None: ...

    def request_from_runner(
        self, run_id: str, kind: ControlRequestKind
    ) -> ControlRequest: ...

    def acknowledge_paused(
        self,
        run_id: str,
        request: ControlRequest,
        *,
        boundary: ControlBoundary,
        checkpoint_sequence: int,
    ) -> None: ...

    async def wait_for_resume(self, run_id: str, request: ControlRequest) -> None: ...

    def acknowledge_resumed(self, run_id: str, request: ControlRequest) -> None: ...

    def acknowledge_fresh_observation(self, run_id: str) -> None: ...

    def close(self, run_id: str, outcome: ControlOutcome) -> None: ...


class LocalCooperativeControl:
    """Atomic local control store shared by the live Runner and CLI."""

    def __init__(
        self,
        state_dir: Path,
        application_state_dir: Path,
        *,
        poll_seconds: float = 0.1,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if (
            not isinstance(state_dir, Path)
            or not state_dir.is_absolute()
            or not isinstance(application_state_dir, Path)
            or not application_state_dir.is_absolute()
            or isinstance(poll_seconds, bool)
            or not isinstance(poll_seconds, (int, float))
            or not 0.01 <= float(poll_seconds) <= 5.0
            or not callable(clock)
        ):
            raise CooperativeControlError("COOPERATIVE_CONTROL_CONFIG_INVALID")
        self.state_dir = state_dir
        self.application_state_dir = application_state_dir
        self.poll_seconds = float(poll_seconds)
        self._clock = clock
        self._owned_digests: dict[str, str] = {}

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise CooperativeControlError("COOPERATIVE_CONTROL_CLOCK_INVALID")
        return value.isoformat()

    def _run_dir(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RUN_ID_INVALID")
        root = self.state_dir.resolve(strict=False)
        run_dir = self.state_dir / "runs" / run_id
        resolved_parent = run_dir.resolve(strict=False)
        try:
            resolved_parent.relative_to(root)
        except ValueError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_PATH_UNSAFE") from exc
        if run_dir.exists() and (run_dir.is_symlink() or resolved_parent != run_dir.absolute()):
            raise CooperativeControlError("COOPERATIVE_CONTROL_PATH_UNSAFE")
        return run_dir

    def _path(self, run_id: str) -> Path:
        return self._run_dir(run_id) / "control.json"

    @contextmanager
    def _locked(self, run_id: str) -> Iterator[None]:
        lock = RunLock(self._run_dir(run_id) / ".control-lock")
        try:
            lock.acquire(recover_stale=True)
        except RunLockError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_BUSY") from exc
        try:
            yield
        finally:
            try:
                lock.release()
            except RunLockError as exc:
                raise CooperativeControlError("COOPERATIVE_CONTROL_LOCK_FAILED") from exc

    @staticmethod
    def _decode(payload: Mapping[str, object]) -> CooperativeControlSnapshot:
        if set(payload) != _FIELDS or payload.get("cooperative_control_version") != 1:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        try:
            request_kind = payload["request_kind"]
            boundary = payload["boundary"]
            outcome = payload["outcome"]
            return CooperativeControlSnapshot(
                run_id=payload["run_id"],  # type: ignore[arg-type]
                owner_token_digest=payload["owner_token_digest"],  # type: ignore[arg-type]
                runner_state_path=payload["runner_state_path"],  # type: ignore[arg-type]
                sequence=payload["sequence"],  # type: ignore[arg-type]
                status=ControlStatus(payload["status"]),
                request_kind=(
                    None if request_kind is None else ControlRequestKind(request_kind)
                ),
                request_id=payload["request_id"],  # type: ignore[arg-type]
                authority=DesktopControlAuthority(payload["authority"]),
                fresh_observation_required=payload[  # type: ignore[arg-type]
                    "fresh_observation_required"
                ],
                boundary=None if boundary is None else ControlBoundary(boundary),
                checkpoint_sequence=payload["checkpoint_sequence"],  # type: ignore[arg-type]
                outcome=None if outcome is None else ControlOutcome(outcome),
                created_at=payload["created_at"],  # type: ignore[arg-type]
                updated_at=payload["updated_at"],  # type: ignore[arg-type]
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID") from exc

    def read(self, run_id: str) -> CooperativeControlSnapshot:
        path = self._path(run_id)
        if path.is_symlink():
            raise CooperativeControlError("COOPERATIVE_CONTROL_PATH_UNSAFE")
        try:
            raw = read_shared_bytes(path)
        except OSError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_NOT_FOUND") from exc
        if not raw or len(raw) > MAX_COOPERATIVE_CONTROL_BYTES:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID") from exc
        if not isinstance(payload, dict):
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        snapshot = self._decode(payload)
        if snapshot.run_id != run_id:
            raise CooperativeControlError("COOPERATIVE_CONTROL_IDENTITY_MISMATCH")
        return snapshot

    def _write(
        self, snapshot: CooperativeControlSnapshot, *, exclusive: bool = False
    ) -> None:
        path = self._path(snapshot.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if exclusive and path.exists():
            raise CooperativeControlError("COOPERATIVE_CONTROL_ALREADY_EXISTS")
        encoded = (
            json.dumps(snapshot.as_json(), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_COOPERATIVE_CONTROL_BYTES:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".control-", suffix=".tmp", dir=path.parent
            )
            temporary = Path(raw_path)
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            if exclusive and path.exists():
                raise CooperativeControlError("COOPERATIVE_CONTROL_ALREADY_EXISTS")
            publish_atomically(temporary, path)
            temporary = None
        except CooperativeControlError:
            raise
        except OSError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_WRITE_FAILED") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _updated(
        self, snapshot: CooperativeControlSnapshot, **changes: object
    ) -> CooperativeControlSnapshot:
        return replace(
            snapshot,
            sequence=snapshot.sequence + 1,
            updated_at=self._now(),
            **changes,  # type: ignore[arg-type]
        )

    @staticmethod
    def _owner_digest(owner_token: str) -> str:
        if not isinstance(owner_token, str) or not owner_token:
            raise CooperativeControlError("COOPERATIVE_CONTROL_OWNER_INVALID")
        return sha256(owner_token.encode("utf-8")).hexdigest()

    def _runner_state_path(self, runner_state_dir: Path) -> str:
        if not isinstance(runner_state_dir, Path) or not runner_state_dir.is_absolute():
            raise CooperativeControlError("COOPERATIVE_CONTROL_STATE_PATH_INVALID")
        root = self.state_dir.resolve(strict=False)
        resolved = runner_state_dir.resolve(strict=False)
        if resolved != runner_state_dir.absolute():
            raise CooperativeControlError("COOPERATIVE_CONTROL_STATE_PATH_UNSAFE")
        try:
            relative = resolved.relative_to(root)
        except ValueError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_STATE_PATH_UNSAFE") from exc
        return "." if relative == Path(".") else relative.as_posix()

    def _checkpoint_state_dir(self, snapshot: CooperativeControlSnapshot) -> Path:
        relative = Path(snapshot.runner_state_path)
        candidate = self.state_dir if snapshot.runner_state_path == "." else self.state_dir / relative
        root = self.state_dir.resolve(strict=False)
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_STATE_PATH_UNSAFE") from exc
        if resolved != candidate.absolute():
            raise CooperativeControlError("COOPERATIVE_CONTROL_STATE_PATH_UNSAFE")
        return candidate

    def start(
        self, run_id: str, *, owner_token: str, runner_state_dir: Path
    ) -> None:
        digest = self._owner_digest(owner_token)
        runner_state_path = self._runner_state_path(runner_state_dir)
        self._require_live_owner()
        try:
            read_run_checkpoint(runner_state_dir, run_id)
        except TraceError as exc:
            raise CooperativeControlError(
                "COOPERATIVE_CONTROL_CHECKPOINT_MISMATCH"
            ) from exc
        now = self._now()
        snapshot = CooperativeControlSnapshot(
            run_id=run_id,
            owner_token_digest=digest,
            runner_state_path=runner_state_path,
            sequence=1,
            status=ControlStatus.ACTIVE,
            request_kind=None,
            request_id=None,
            authority=DesktopControlAuthority.AGENT,
            fresh_observation_required=False,
            boundary=None,
            checkpoint_sequence=None,
            outcome=None,
            created_at=now,
            updated_at=now,
        )
        with self._locked(run_id):
            self._write(snapshot, exclusive=True)
        self._owned_digests[run_id] = digest

    def _owned(self, snapshot: CooperativeControlSnapshot) -> None:
        if self._owned_digests.get(snapshot.run_id) != snapshot.owner_token_digest:
            raise CooperativeControlError("COOPERATIVE_CONTROL_OWNER_MISMATCH")

    def pending_request(self, run_id: str) -> ControlRequest | None:
        snapshot = self.read(run_id)
        self._owned(snapshot)
        if snapshot.status is ControlStatus.PAUSE_REQUESTED:
            return snapshot.request
        if snapshot.status in {ControlStatus.ACTIVE, ControlStatus.RESUMING}:
            return None
        if snapshot.status is ControlStatus.CLOSED:
            raise CooperativeControlError("COOPERATIVE_CONTROL_CLOSED")
        return None

    def request_from_runner(
        self, run_id: str, kind: ControlRequestKind
    ) -> ControlRequest:
        if not isinstance(kind, ControlRequestKind):
            raise CooperativeControlError("COOPERATIVE_CONTROL_REQUEST_INVALID")
        with self._locked(run_id):
            snapshot = self.read(run_id)
            self._owned(snapshot)
            if snapshot.status is not ControlStatus.ACTIVE:
                raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")
            request = ControlRequest(uuid4().hex, kind)
            self._write(
                self._updated(
                    snapshot,
                    status=ControlStatus.PAUSE_REQUESTED,
                    request_kind=kind,
                    request_id=request.request_id,
                )
            )
            return request

    def acknowledge_paused(
        self,
        run_id: str,
        request: ControlRequest,
        *,
        boundary: ControlBoundary,
        checkpoint_sequence: int,
    ) -> None:
        if (
            not isinstance(request, ControlRequest)
            or not isinstance(boundary, ControlBoundary)
            or isinstance(checkpoint_sequence, bool)
            or not isinstance(checkpoint_sequence, int)
            or checkpoint_sequence < 1
        ):
            raise CooperativeControlError("COOPERATIVE_CONTROL_PAUSE_INVALID")
        with self._locked(run_id):
            snapshot = self.read(run_id)
            self._owned(snapshot)
            if snapshot.status is not ControlStatus.PAUSE_REQUESTED or snapshot.request != request:
                raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")
            self._write(
                self._updated(
                    snapshot,
                    status=ControlStatus.PAUSED,
                    authority=DesktopControlAuthority.RELEASED,
                    fresh_observation_required=True,
                    boundary=boundary,
                    checkpoint_sequence=checkpoint_sequence,
                )
            )

    async def wait_for_resume(self, run_id: str, request: ControlRequest) -> None:
        while True:
            snapshot = self.read(run_id)
            self._owned(snapshot)
            if snapshot.request != request:
                raise CooperativeControlError("COOPERATIVE_CONTROL_REQUEST_MISMATCH")
            if snapshot.status is ControlStatus.RESUME_REQUESTED:
                return
            if snapshot.status is not ControlStatus.PAUSED:
                raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")
            await asyncio.sleep(self.poll_seconds)

    def acknowledge_resumed(self, run_id: str, request: ControlRequest) -> None:
        with self._locked(run_id):
            snapshot = self.read(run_id)
            self._owned(snapshot)
            if snapshot.status is not ControlStatus.RESUME_REQUESTED or snapshot.request != request:
                raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")
            self._write(
                self._updated(
                    snapshot,
                    status=ControlStatus.RESUMING,
                    authority=DesktopControlAuthority.AGENT,
                )
            )

    def acknowledge_fresh_observation(self, run_id: str) -> None:
        with self._locked(run_id):
            snapshot = self.read(run_id)
            self._owned(snapshot)
            if snapshot.status in {
                ControlStatus.ACTIVE,
                ControlStatus.PAUSE_REQUESTED,
            }:
                return
            if snapshot.status is not ControlStatus.RESUMING:
                raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")
            self._write(
                self._updated(
                    snapshot,
                    status=ControlStatus.ACTIVE,
                    request_kind=None,
                    request_id=None,
                    fresh_observation_required=False,
                    boundary=None,
                    checkpoint_sequence=None,
                )
            )

    def close(self, run_id: str, outcome: ControlOutcome) -> None:
        if not isinstance(outcome, ControlOutcome):
            raise CooperativeControlError("COOPERATIVE_CONTROL_OUTCOME_INVALID")
        with self._locked(run_id):
            snapshot = self.read(run_id)
            self._owned(snapshot)
            if snapshot.status is ControlStatus.CLOSED:
                if snapshot.outcome is not outcome:
                    raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")
                return
            self._write(
                self._updated(
                    snapshot,
                    status=ControlStatus.CLOSED,
                    authority=DesktopControlAuthority.NONE,
                    outcome=outcome,
                )
            )

    def _require_live_owner(self) -> None:
        try:
            held = is_run_lock_held(self.application_state_dir)
        except RunLockError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_OWNER_UNAVAILABLE") from exc
        if not held:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RUN_NOT_ACTIVE")

    def _active_run_id(self) -> str:
        runs_dir = self.state_dir / "runs"
        if not runs_dir.is_dir():
            raise CooperativeControlError("COOPERATIVE_CONTROL_NOT_FOUND")
        matches: list[str] = []
        try:
            children = runs_dir.iterdir()
            for index, child in enumerate(children, start=1):
                if index > MAX_CONTROL_RUNS:
                    raise CooperativeControlError("COOPERATIVE_CONTROL_SCAN_LIMIT")
                if not child.is_dir() or _RUN_ID.fullmatch(child.name) is None:
                    continue
                if not (child / "control.json").is_file():
                    continue
                try:
                    snapshot = self.read(child.name)
                except CooperativeControlError:
                    continue
                if snapshot.status is not ControlStatus.CLOSED:
                    matches.append(snapshot.run_id)
        except OSError as exc:
            raise CooperativeControlError("COOPERATIVE_CONTROL_SCAN_FAILED") from exc
        if len(matches) != 1:
            raise CooperativeControlError(
                "COOPERATIVE_CONTROL_NOT_FOUND"
                if not matches
                else "COOPERATIVE_CONTROL_AMBIGUOUS"
            )
        return matches[0]

    def _resolve_live(self, run_id: str | None) -> CooperativeControlSnapshot:
        self._require_live_owner()
        active_run_id = self._active_run_id()
        if run_id is not None and run_id != active_run_id:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RUN_NOT_ACTIVE")
        resolved_id = active_run_id
        snapshot = self.read(resolved_id)
        if snapshot.status is ControlStatus.CLOSED:
            raise CooperativeControlError("COOPERATIVE_CONTROL_RUN_NOT_ACTIVE")
        return snapshot

    def inspect(self, run_id: str | None = None) -> CooperativeControlSnapshot:
        if run_id is not None:
            return self.read(run_id)
        return self._resolve_live(None)

    def request_pause(
        self, kind: ControlRequestKind, *, run_id: str | None = None
    ) -> CooperativeControlSnapshot:
        if not isinstance(kind, ControlRequestKind):
            raise CooperativeControlError("COOPERATIVE_CONTROL_REQUEST_INVALID")
        initial = self._resolve_live(run_id)
        with self._locked(initial.run_id):
            snapshot = self._resolve_live(initial.run_id)
            if snapshot.status is ControlStatus.ACTIVE:
                request = ControlRequest(uuid4().hex, kind)
                snapshot = self._updated(
                    snapshot,
                    status=ControlStatus.PAUSE_REQUESTED,
                    request_kind=kind,
                    request_id=request.request_id,
                )
                self._write(snapshot)
                return snapshot
            if (
                snapshot.status in {ControlStatus.PAUSE_REQUESTED, ControlStatus.PAUSED}
                and snapshot.request_kind is kind
            ):
                return snapshot
            raise CooperativeControlError("COOPERATIVE_CONTROL_TRANSITION_INVALID")

    def request_resume(self, *, run_id: str | None = None) -> CooperativeControlSnapshot:
        initial = self._resolve_live(run_id)
        with self._locked(initial.run_id):
            snapshot = self._resolve_live(initial.run_id)
            if snapshot.status is ControlStatus.RESUME_REQUESTED:
                return snapshot
            if snapshot.status is not ControlStatus.PAUSED:
                raise CooperativeControlError("COOPERATIVE_CONTROL_NOT_PAUSED")
            try:
                checkpoint = read_run_checkpoint(
                    self._checkpoint_state_dir(snapshot), snapshot.run_id
                )
            except TraceError as exc:
                raise CooperativeControlError(
                    "COOPERATIVE_CONTROL_CHECKPOINT_MISMATCH"
                ) from exc
            if (
                checkpoint.get("phase") != RunPhase.PAUSED.value
                or checkpoint.get("checkpoint_sequence") != snapshot.checkpoint_sequence
                or checkpoint.get("recovery_status") != "requires_reobservation"
            ):
                raise CooperativeControlError("COOPERATIVE_CONTROL_CHECKPOINT_MISMATCH")
            snapshot = self._updated(
                snapshot,
                status=ControlStatus.RESUME_REQUESTED,
            )
            self._write(snapshot)
            return snapshot


def render_cooperative_control(snapshot: CooperativeControlSnapshot) -> str:
    """Render fixed local control facts without model or desktop content."""

    if not isinstance(snapshot, CooperativeControlSnapshot):
        raise CooperativeControlError("COOPERATIVE_CONTROL_RECORD_INVALID")
    next_actions = {
        ControlStatus.ACTIVE: "The Agent owns the control lane; request pause or takeover if needed.",
        ControlStatus.PAUSE_REQUESTED: "Wait for PAUSED before touching the shared desktop.",
        ControlStatus.PAUSED: "Desktop authority is released; use task resume when finished.",
        ControlStatus.RESUME_REQUESTED: "Stop desktop input; the Agent is reacquiring authority.",
        ControlStatus.RESUMING: "Fresh observation is mandatory before any later side effect.",
        ControlStatus.CLOSED: "This control lifecycle is closed; inspect the run outcome.",
    }
    request = "none" if snapshot.request_kind is None else snapshot.request_kind.value
    outcome = "none" if snapshot.outcome is None else snapshot.outcome.value
    return "\n".join(
        [
            "Cooperative desktop control",
            f"Run: {snapshot.run_id}",
            f"State: {snapshot.status.value}",
            f"Request: {request}",
            f"Desktop authority: {snapshot.authority.value}",
            "Fresh observation required: "
            + ("yes" if snapshot.fresh_observation_required else "no"),
            f"Outcome: {outcome}",
            f"Next: {next_actions[snapshot.status]}",
        ]
    ) + "\n"


__all__ = [
    "COOPERATIVE_CONTROL_VERSION",
    "ControlBoundary",
    "ControlOutcome",
    "ControlRequest",
    "ControlRequestKind",
    "ControlStatus",
    "CooperativeControlError",
    "CooperativeControlPort",
    "CooperativeControlSnapshot",
    "DesktopControlAuthority",
    "LocalCooperativeControl",
    "render_cooperative_control",
]
