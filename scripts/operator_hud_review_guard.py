"""Single-instance guard for isolated operator-HUD visual review scripts."""

from __future__ import annotations

import ctypes
from contextlib import contextmanager
from ctypes import wintypes
from collections.abc import Iterator

_ERROR_ALREADY_EXISTS = 183
_REVIEW_NAMES = frozenset({"decision-card", "progress-hud"})


class ReviewAlreadyRunningError(RuntimeError):
    """The same isolated visual review surface already owns its local slot."""


@contextmanager
def exclusive_review(name: str) -> Iterator[None]:
    if name not in _REVIEW_NAMES:
        raise ValueError("OPERATOR_HUD_REVIEW_NAME_INVALID")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.LPCWSTR,
    ]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel32.ReleaseMutex.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    mutex = kernel32.CreateMutexW(
        None,
        True,
        f"Local\\GuardedDesktopAgent.OperatorHudReview.{name}",
    )
    if not mutex:
        raise OSError("OPERATOR_HUD_REVIEW_MUTEX_FAILED")
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(mutex)
        raise ReviewAlreadyRunningError(
            f"OPERATOR_HUD_REVIEW_ALREADY_RUNNING:{name}"
        )
    try:
        yield
    finally:
        kernel32.ReleaseMutex(mutex)
        kernel32.CloseHandle(mutex)
