"""OS-backed, fail-closed local run lock for the Agent Host."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class RunLockError(RuntimeError):
    """Base error for local run-lock failures."""


class RunLockedError(RunLockError):
    """Raised when another or unknown owner already holds the run lock."""


class RunLockOwnershipError(RunLockError):
    """Raised when release cannot prove ownership of the locked file."""


@dataclass(frozen=True)
class RunLockOwner:
    pid: int
    acquired_at: str
    token: str

    def as_json(self) -> dict[str, str | int]:
        return {
            "pid": self.pid,
            "acquired_at": self.acquired_at,
            "token": self.token,
        }


class RunLock:
    """One OS-locked lease file scoped to the user-local Agent root.

    The file remains present after a clean release with an explicit released
    marker. An owner record left by a crash is never reclaimed automatically.
    Keeping the descriptor locked for the entire lease avoids a read-token then
    unlink-by-path race and prevents cooperative processes from replacing the
    active lease.
    """

    filename = "active-run.lock"
    _released_payload = {"released": True}
    _max_payload_bytes = 4096

    def __init__(self, lock_dir: str | Path) -> None:
        self.lock_dir = Path(lock_dir)
        if not self.lock_dir.is_absolute():
            raise ValueError("lock_dir must be absolute")
        self.path = self.lock_dir / self.filename
        self._owner: RunLockOwner | None = None
        self._descriptor: int | None = None

    @property
    def acquired(self) -> bool:
        return self._owner is not None and self._descriptor is not None

    @property
    def owner(self) -> RunLockOwner | None:
        return self._owner

    def acquire(self, *, recover_stale: bool = False) -> RunLockOwner:
        if self.acquired:
            raise RunLockError("this RunLock instance is already acquired")
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        binary = getattr(os, "O_BINARY", 0)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_RDWR | binary,
                0o600,
            )
            created = True
        except FileExistsError:
            descriptor = os.open(self.path, os.O_RDWR | binary)
            created = False
        try:
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            self._acquire_os_lock(descriptor)
        except OSError as exc:
            os.close(descriptor)
            raise RunLockedError(f"another Agent run owns the lock at {self.path}") from exc

        try:
            try:
                existing = self._read_payload(descriptor)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RunLockedError(
                    f"an unknown or malformed Agent run lock exists at {self.path}"
                ) from exc
            stale_owner = (
                isinstance(existing, dict)
                and isinstance(existing.get("pid"), int)
                and isinstance(existing.get("acquired_at"), str)
                and isinstance(existing.get("token"), str)
            )
            if (created and existing is not None) or (
                not created
                and existing != self._released_payload
                and not (recover_stale and stale_owner)
            ):
                raise RunLockedError(
                    f"an unknown or stale Agent run lock exists at {self.path}"
                )
            owner = RunLockOwner(
                pid=os.getpid(),
                acquired_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                token=uuid4().hex,
            )
            self._write_payload(descriptor, owner.as_json())
        except BaseException:
            try:
                self._release_os_lock(descriptor)
            finally:
                os.close(descriptor)
            raise

        self._descriptor = descriptor
        self._owner = owner
        return owner

    def release(self) -> None:
        owner = self._owner
        descriptor = self._descriptor
        if owner is None or descriptor is None:
            return
        try:
            current = self._read_payload(descriptor)
            if not isinstance(current, dict) or current.get("token") != owner.token:
                raise RunLockOwnershipError(
                    "run lock ownership changed; refusing to mark it released"
                )
            self._write_payload(descriptor, self._released_payload)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunLockOwnershipError("cannot verify ownership of the run lock") from exc
        finally:
            try:
                self._release_os_lock(descriptor)
            finally:
                try:
                    os.close(descriptor)
                finally:
                    self._owner = None
                    self._descriptor = None

    def _read_payload(self, descriptor: int) -> object | None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        raw = os.read(descriptor, self._max_payload_bytes + 1)
        if raw in (b"", b"\0"):
            return None
        if len(raw) > self._max_payload_bytes:
            raise RunLockedError("run lock payload exceeds the reviewed size limit")
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _write_payload(descriptor: int, payload: object) -> None:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.ftruncate(descriptor, 0)
        os.write(descriptor, encoded)
        os.fsync(descriptor)

    @staticmethod
    def _acquire_os_lock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _release_os_lock(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

    def __enter__(self) -> "RunLock":
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


def is_run_lock_held(lock_dir: str | Path) -> bool:
    """Probe the operating-system lease without reading or changing its payload."""

    lock = RunLock(lock_dir)
    binary = getattr(os, "O_BINARY", 0)
    try:
        descriptor = os.open(lock.path, os.O_RDWR | binary)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RunLockError(f"cannot inspect Agent run lock at {lock.path}") from exc
    acquired_probe = False
    try:
        try:
            lock._acquire_os_lock(descriptor)
        except OSError:
            return True
        else:
            acquired_probe = True
            return False
    finally:
        if acquired_probe:
            lock._release_os_lock(descriptor)
        os.close(descriptor)


__all__ = [
    "RunLock",
    "RunLockError",
    "RunLockOwner",
    "RunLockOwnershipError",
    "RunLockedError",
    "is_run_lock_held",
]
