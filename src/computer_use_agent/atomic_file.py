"""Publish and read a file atomically while the other side is concurrently busy.

Run checkpoints are published while other processes — the operator progress
poller above all — may be reading them. On Windows the obvious implementation is
quietly broken, and the breakage is asymmetric and severe, so both halves of the
contract live here together.

**The hazard.** ``os.replace`` is ``MoveFileExW(MOVEFILE_REPLACE_EXISTING)``,
which cannot replace a target that has *any* open handle. Share flags do not
help: ``FILE_SHARE_DELETE`` lets a reader's handle coexist with ``DeleteFile``,
but a pending-delete file still occupies its directory entry, so the rename onto
that name still fails with ``ERROR_ACCESS_DENIED``. Measured with one reader
polling one checkpoint in a tight loop:

~~~text
os.replace + ordinary read          61.9% of publishes FAILED
os.replace + share-delete read      73.8% of publishes FAILED   (no better)
~~~

Because ``trace._atomic_json`` does not retry, every one of those failures is a
hard ``CHECKPOINT_WRITE_FAILED`` that fails the agent's run. A live reader would
therefore inject a new failure mode into the write path.

**The fix.** ``ReplaceFileW`` is the documented API for replacing a file that
readers may hold open, and it succeeds — but *only* if those readers opened with
``FILE_SHARE_DELETE``. Neither half works alone:

~~~text
ReplaceFileW + ordinary read        FAILS (ERROR_SHARING_VIOLATION)
ReplaceFileW + share-delete read    publish failures 0.00%
~~~

``ReplaceFileW`` briefly frees the target name, so a racing reader can see a
transient "not found" or sharing violation. That trade is strongly favourable
and deliberate: a failed *publish* fails a run, while a failed *read* only makes
one record momentarily unavailable to a viewer that will look again. A small
bounded retry in the reader removes even that:

~~~text
reader attempts=1   publish 0.00% failed   reads 24.30% failed
reader attempts=4   publish 0.00% failed   reads  0.05% failed
~~~

Readers never observe a torn record either way: a share-delete handle keeps
referring to the original file object after the directory entry is swapped, so a
read that races a publish returns the complete previous record.

POSIX ``rename`` has none of these restrictions, so other platforms use the
ordinary paths.
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

_IS_WINDOWS = sys.platform == "win32"

_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

#: Share mode that lets a concurrent ``ReplaceFileW`` of this path proceed.
SHARE_ALL = _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE

_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3
_ERROR_SHARING_VIOLATION = 32
#: Errors a publish can transiently expose to a racing reader. Anything else is
#: a real failure and is raised on the first attempt.
_TRANSIENT = frozenset({_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND, _ERROR_SHARING_VIOLATION})

#: Attempts and backoff sized from the measurement above: 4 attempts takes the
#: adversarial tight-loop read failure rate to ~0.05% and costs nothing when the
#: first attempt succeeds, which is the overwhelmingly common case.
READ_ATTEMPTS = 4
_READ_BACKOFF_SECONDS = 0.001

if _IS_WINDOWS:  # pragma: no cover - exercised on Windows only
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.restype = ctypes.c_void_p
    _kernel32.CreateFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
    ]
    _kernel32.ReplaceFileW.restype = ctypes.c_int
    _kernel32.ReplaceFileW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p,
    ]
    _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


def _read_once_windows(path: Path) -> bytes:
    handle = _kernel32.CreateFileW(
        str(path), _GENERIC_READ, SHARE_ALL, None,
        _OPEN_EXISTING, _FILE_ATTRIBUTE_NORMAL, None,
    )
    if handle is None or handle == _INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())

    import msvcrt

    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except OSError:
        _kernel32.CloseHandle(ctypes.c_void_p(handle))
        raise
    # open_osfhandle transfers ownership: closing the file object closes the
    # underlying handle exactly once.
    with os.fdopen(descriptor, "rb") as file:
        return file.read()


def read_shared_bytes(path: Path, *, attempts: int = READ_ATTEMPTS) -> bytes:
    """Read ``path`` whole without ever blocking a concurrent publish.

    Retries only the transient states a concurrent :func:`publish_atomically`
    can expose; any other error is raised immediately. Raises ``OSError`` just
    like ``Path.read_bytes`` so existing callers keep their error handling.
    """

    if not _IS_WINDOWS:
        return path.read_bytes()
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    for attempt in range(attempts):
        try:
            return _read_once_windows(path)
        except OSError as exc:
            if exc.winerror not in _TRANSIENT or attempt + 1 == attempts:
                raise
            time.sleep(_READ_BACKOFF_SECONDS)
    raise AssertionError("unreachable")  # pragma: no cover


def publish_atomically(temporary: Path, target: Path) -> None:
    """Atomically move ``temporary`` onto ``target``, tolerating open readers.

    Uses ``ReplaceFileW`` when it applies, and falls back to ``os.replace`` when
    it does not — a first publish (no target to replace), a non-Windows
    platform, or a filesystem/volume layout ``ReplaceFileW`` refuses. The
    fallback is never worse than the previous behaviour, and any error it raises
    is the caller's to handle.
    """

    if not _IS_WINDOWS or not target.exists():
        os.replace(temporary, target)
        return

    if _kernel32.ReplaceFileW(str(target), str(temporary), None, 0, None, None):
        return
    # ReplaceFileW declined (cross-volume, unsupported filesystem, ...). Fall
    # back so behaviour is never worse than the plain rename it replaces.
    os.replace(temporary, target)


__all__ = ["READ_ATTEMPTS", "SHARE_ALL", "publish_atomically", "read_shared_bytes"]
