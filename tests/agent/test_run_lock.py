from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from computer_use_agent.run_lock import (
    RunLock,
    RunLockedError,
    RunLockOwnershipError,
)


def test_second_lock_for_the_same_application_root_fails_closed(tmp_path: Path) -> None:
    first = RunLock(tmp_path / "state")
    second = RunLock(tmp_path / "state")
    owner = first.acquire()

    with pytest.raises(RunLockedError):
        second.acquire()

    assert first.owner == owner
    assert set(owner.as_json()) == {"pid", "acquired_at", "token"}
    first.release()
    assert json.loads(first.path.read_text(encoding="utf-8")) == {"released": True}


def test_clean_release_allows_a_new_owner(tmp_path: Path) -> None:
    first = RunLock(tmp_path / "state")
    first.acquire()
    first.release()

    replacement = RunLock(tmp_path / "state")
    replacement.acquire()
    replacement.release()


def test_context_manager_releases_after_an_exception(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "state")

    with pytest.raises(RuntimeError, match="boom"):
        with lock:
            assert lock.path.exists()
            raise RuntimeError("boom")

    assert json.loads(lock.path.read_text(encoding="utf-8")) == {"released": True}


def test_existing_unknown_lock_is_never_reclaimed_automatically(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "state")
    lock.lock_dir.mkdir(parents=True)
    lock.path.write_text("unknown owner", encoding="utf-8")

    with pytest.raises(RunLockedError):
        lock.acquire()

    assert lock.path.read_text(encoding="utf-8") == "unknown owner"


def test_explicit_recovery_reclaims_only_a_well_formed_unlocked_owner(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "state")
    lock.lock_dir.mkdir(parents=True)
    stale = {"pid": 123, "acquired_at": "2026-01-01T00:00:00+00:00", "token": "abc"}
    lock.path.write_text(json.dumps(stale), encoding="utf-8")

    with pytest.raises(RunLockedError):
        lock.acquire()

    lock.acquire(recover_stale=True)
    lock.release()
    assert json.loads(lock.path.read_text(encoding="utf-8")) == {"released": True}

    lock.path.write_text('{"pid":123}', encoding="utf-8")
    with pytest.raises(RunLockedError):
        lock.acquire(recover_stale=True)


@pytest.mark.parametrize("content", ["", "\0"])
def test_preexisting_empty_or_nul_lock_is_not_treated_as_a_new_file(
    tmp_path: Path, content: str
) -> None:
    lock = RunLock(tmp_path / "state")
    lock.lock_dir.mkdir(parents=True)
    lock.path.write_text(content, encoding="utf-8")

    with pytest.raises(RunLockedError, match="unknown or stale"):
        lock.acquire()

    assert lock.path.exists()


def test_release_never_removes_a_replaced_lock(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "state")
    lock.acquire()
    assert lock._descriptor is not None
    lock._write_payload(lock._descriptor, {"token": "different-owner"})

    with pytest.raises(RunLockOwnershipError, match="ownership changed"):
        lock.release()

    assert json.loads(lock.path.read_text(encoding="utf-8")) == {"token": "different-owner"}


def test_release_closes_and_clears_state_even_if_explicit_unlock_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = RunLock(tmp_path / "state")
    lock.acquire()

    def fail_unlock(_descriptor: int) -> None:
        raise OSError("unlock failed")

    with monkeypatch.context() as context:
        context.setattr(RunLock, "_release_os_lock", staticmethod(fail_unlock))
        with pytest.raises(OSError, match="unlock failed"):
            lock.release()

    assert lock.acquired is False
    replacement = RunLock(tmp_path / "state")
    replacement.acquire()
    replacement.release()


def test_lock_excludes_a_second_process(tmp_path: Path) -> None:
    lock_dir = tmp_path / "state"
    script = (
        "import sys; from pathlib import Path; "
        "from computer_use_agent.run_lock import RunLock; "
        "lock=RunLock(Path(sys.argv[1])); lock.acquire(); "
        "print('locked', flush=True); sys.stdin.readline(); lock.release()"
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(RunLockedError):
            RunLock(lock_dir).acquire()
    finally:
        if process.poll() is None:
            assert process.stdin is not None
            process.stdin.write("\n")
            process.stdin.flush()
            process.stdin.close()
            process.wait(timeout=10)
    assert process.returncode == 0
