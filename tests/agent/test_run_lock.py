from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

import computer_use_agent.run_lock as run_lock_module
from computer_use_agent.run_lock import (
    RunLock,
    RunLockedError,
    RunLockOwnershipError,
    is_run_lock_held,
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


@pytest.mark.parametrize(
    ("os_name", "platform", "module_name"),
    [
        pytest.param("nt", "win32", "msvcrt", id="windows"),
        pytest.param("posix", "linux", "fcntl", id="unix"),
    ],
)
def test_supported_platform_lock_family_uses_exact_calls_at_offset_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: str,
    platform: str,
    module_name: str,
) -> None:
    path = tmp_path / "platform.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.write(descriptor, b"\0")
    module = types.ModuleType(module_name)
    calls: list[tuple[str, int, int | None, int]] = []

    if module_name == "msvcrt":
        module.LK_NBLCK = 7
        module.LK_UNLCK = 11

        def locking(candidate: int, mode: int, count: int) -> None:
            calls.append(
                ("locking", mode, count, os.lseek(candidate, 0, os.SEEK_CUR))
            )

        module.locking = locking
        expected = [("locking", 7, 1, 0), ("locking", 11, 1, 0)]
    else:
        module.LOCK_EX = 13
        module.LOCK_NB = 17
        module.LOCK_UN = 19

        def flock(candidate: int, mode: int) -> None:
            calls.append(("flock", mode, None, os.lseek(candidate, 0, os.SEEK_CUR)))

        module.flock = flock
        expected = [("flock", 29, None, 0), ("flock", 19, None, 0)]

    try:
        monkeypatch.setattr(run_lock_module.os, "name", os_name)
        monkeypatch.setattr(run_lock_module.sys, "platform", platform)
        monkeypatch.setitem(sys.modules, module_name, module)
        RunLock._acquire_os_lock(descriptor)
        RunLock._release_os_lock(descriptor)
    finally:
        os.close(descriptor)

    assert calls == expected


@pytest.mark.parametrize(
    ("os_name", "platform", "module_name"),
    [
        pytest.param("nt", "linux", "msvcrt", id="nt-with-non-win32-platform"),
        pytest.param("posix", "win32", "fcntl", id="posix-with-win32-platform"),
    ],
)
@pytest.mark.parametrize("method_name", ["_acquire_os_lock", "_release_os_lock"])
def test_inconsistent_platform_identity_fails_before_wrong_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    os_name: str,
    platform: str,
    module_name: str,
    method_name: str,
) -> None:
    path = tmp_path / "platform.lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.write(descriptor, b"\0")
    module = types.ModuleType(module_name)
    calls: list[tuple[object, ...]] = []

    def wrong_api(*arguments: object) -> None:
        calls.append(arguments)

    if module_name == "msvcrt":
        module.LK_NBLCK = 7
        module.LK_UNLCK = 11
        module.locking = wrong_api
    else:
        module.LOCK_EX = 13
        module.LOCK_NB = 17
        module.LOCK_UN = 19
        module.flock = wrong_api

    try:
        monkeypatch.setattr(run_lock_module.os, "name", os_name)
        monkeypatch.setattr(run_lock_module.sys, "platform", platform)
        monkeypatch.setitem(sys.modules, module_name, module)
        method = getattr(RunLock, method_name)
        with pytest.raises(
            OSError, match="^inconsistent operating-system lock platform$"
        ):
            method(descriptor)
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
    finally:
        os.close(descriptor)

    assert calls == []


def test_acquire_os_lock_failure_precedes_payload_read_and_closes_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = RunLock(tmp_path / "state")
    events: list[str] = []
    real_close = os.close

    def fail_lock(_descriptor: int) -> None:
        events.append("lock")
        raise OSError("lock failed")

    def unexpected_read(_self: RunLock, _descriptor: int) -> object:
        events.append("read")
        raise AssertionError("payload read must follow successful OS locking")

    def record_close(descriptor: int) -> None:
        events.append("close")
        real_close(descriptor)

    monkeypatch.setattr(RunLock, "_acquire_os_lock", staticmethod(fail_lock))
    monkeypatch.setattr(RunLock, "_read_payload", unexpected_read)
    monkeypatch.setattr(run_lock_module.os, "close", record_close)

    with pytest.raises(RunLockedError, match="another Agent run owns") as captured:
        lock.acquire()

    assert isinstance(captured.value.__cause__, OSError)
    assert str(captured.value.__cause__) == "lock failed"
    assert events == ["lock", "close"]
    assert lock.acquired is False
    assert lock.path.read_bytes() == b"\0"


def test_payload_failure_releases_and_closes_in_exact_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = RunLock(tmp_path / "state")
    events: list[str] = []
    real_close = os.close

    def record_lock(_descriptor: int) -> None:
        events.append("lock")

    def fail_read(_self: RunLock, _descriptor: int) -> object:
        events.append("read")
        raise json.JSONDecodeError("malformed", "{", 1)

    def record_unlock(_descriptor: int) -> None:
        events.append("unlock")

    def record_close(descriptor: int) -> None:
        events.append("close")
        real_close(descriptor)

    monkeypatch.setattr(RunLock, "_acquire_os_lock", staticmethod(record_lock))
    monkeypatch.setattr(RunLock, "_read_payload", fail_read)
    monkeypatch.setattr(RunLock, "_release_os_lock", staticmethod(record_unlock))
    monkeypatch.setattr(run_lock_module.os, "close", record_close)

    with pytest.raises(RunLockedError, match="unknown or malformed") as captured:
        lock.acquire()

    assert isinstance(captured.value.__cause__, json.JSONDecodeError)
    assert events == ["lock", "read", "unlock", "close"]
    assert lock.acquired is False
    assert lock.path.read_bytes() == b"\0"


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
        assert is_run_lock_held(lock_dir) is True
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
    assert is_run_lock_held(lock_dir) is False
    assert (lock_dir / RunLock.filename).read_bytes() == b'{"released":true}'
