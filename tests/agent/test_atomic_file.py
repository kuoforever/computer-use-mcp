"""Tests for the concurrent publish/read contract in ``atomic_file``.

The regression these protect is asymmetric: a blocked *publish* fails the
agent's run with ``CHECKPOINT_WRITE_FAILED``, while a blocked *read* only makes
one record momentarily unavailable to a viewer. So the publish path must never
be blocked by a reader, and the read path must never return a torn record.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from computer_use_agent.atomic_file import (
    READ_ATTEMPTS,
    publish_atomically,
    read_shared_bytes,
)


def _publish(target: Path, payload: bytes) -> None:
    descriptor, raw = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=str(target.parent))
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
    publish_atomically(Path(raw), target)


def test_publish_creates_then_replaces(tmp_path: Path) -> None:
    target = tmp_path / "state.json"

    _publish(target, b"first")  # no existing target: plain rename path
    assert target.read_bytes() == b"first"

    _publish(target, b"second")  # existing target: replace path
    assert target.read_bytes() == b"second"


def test_publish_leaves_no_temporary_behind(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    _publish(target, b"first")
    _publish(target, b"second")

    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_read_shared_bytes_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"payload")

    assert read_shared_bytes(target) == b"payload"


def test_read_missing_file_raises_oserror(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        read_shared_bytes(tmp_path / "absent.json")


def test_read_rejects_nonpositive_attempts(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_bytes(b"payload")

    if sys.platform != "win32":  # pragma: no cover - the guard is Windows-only
        pytest.skip("attempt bound only applies to the Windows read path")
    with pytest.raises(ValueError):
        read_shared_bytes(target, attempts=0)


def test_reader_never_blocks_a_publish(tmp_path: Path) -> None:
    """The core regression: a concurrent reader must not fail any publish.

    Before this contract, a reader holding an ordinary handle broke ~62% of
    ``os.replace`` publishes on Windows, and each one is a hard run failure.
    """

    target = tmp_path / "state.json"
    target.write_bytes(b'{"v":0}')
    stop = threading.Event()
    read_failures = 0
    read_successes = 0

    def reader() -> None:
        nonlocal read_failures, read_successes
        while not stop.is_set():
            try:
                read_shared_bytes(target)
                read_successes += 1
            except OSError:
                read_failures += 1

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    publish_failures = 0
    try:
        for index in range(400):
            try:
                _publish(target, json.dumps({"v": index}).encode())
            except OSError:
                publish_failures += 1
    finally:
        stop.set()
        thread.join(timeout=5)

    # The property that matters: a reader can never fail a publish, because a
    # failed publish fails the agent's run.
    assert publish_failures == 0
    # A read may miss transiently by design, and the exact rate depends on
    # machine load, so this only asserts that misses stay the exception rather
    # than the rule. Correctness of what a successful read returns is covered by
    # test_concurrent_read_never_returns_a_torn_record.
    assert read_successes > read_failures


def test_concurrent_read_never_returns_a_torn_record(tmp_path: Path) -> None:
    """Every observation is one whole published payload, never a mixture."""

    target = tmp_path / "state.json"
    small = json.dumps({"phase": "PLANNING", "pad": "a" * 2000}).encode()
    large = json.dumps({"phase": "SUCCESS", "pad": "b" * 8000}).encode()
    target.write_bytes(small)
    stop = threading.Event()

    def writer() -> None:
        index = 0
        while not stop.is_set():
            try:
                _publish(target, small if index % 2 == 0 else large)
            except OSError:
                pass
            index += 1

    thread = threading.Thread(target=writer, daemon=True)
    thread.start()
    observed: set[str] = set()
    try:
        for _ in range(600):
            try:
                data = read_shared_bytes(target)
            except OSError:
                continue
            # A torn read would not parse, or would not equal a published blob.
            record = json.loads(data)
            assert data in (small, large)
            observed.add(record["phase"])
    finally:
        stop.set()
        thread.join(timeout=5)

    assert observed, "expected at least one successful observation"


def test_read_attempts_default_is_bounded_and_documented() -> None:
    # The retry exists to absorb the brief window a publish opens; it must stay
    # small enough that a genuinely missing file fails fast.
    assert 1 < READ_ATTEMPTS <= 8
