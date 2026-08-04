"""Exact-process cleanup for disposable desktop application fixtures.

The cleanup boundary is window-first. It never searches by executable name:
each target is an exact process handle returned by the caller's launch. Visible
unowned top-level windows for that PID receive ``WM_CLOSE``; all visible
top-level windows, including owned dialogs, are observed until stably gone. An
owned dialog is an unresolved operator choice, so it requires handoff rather
than force termination. A process may remain alive without an operator-visible
window. Forced termination is reserved for a bounded graceful-close failure
with no owned dialog, or a partial launch that never exposed a window.
"""
from __future__ import annotations

import ctypes
import math
import subprocess
import time
from collections.abc import Callable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

from .win32_dll import private_windll

_GW_OWNER = 4
_WM_CLOSE = 0x0010


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float) -> int: ...


class ProcessWindows(Protocol):
    def snapshot(self, pid: int) -> ProcessWindowSnapshot: ...

    def request_close(self, pid: int) -> int: ...


@dataclass(frozen=True)
class DisposableProcess:
    application: str
    process: ProcessHandle


@dataclass(frozen=True)
class ProcessWindowSnapshot:
    """Visible top-level window topology for one exact process."""

    visible_count: int
    unowned_count: int
    owned_count: int


@dataclass(frozen=True)
class DisposableCleanup:
    application: str
    pid: int
    disposition: str
    exit_code: int | None
    close_requests: int
    window_cleanup_verified: bool
    process_running: bool


class Win32ProcessWindows:
    """Observe and close only visible, unowned top-level windows for one PID."""

    def __init__(self) -> None:
        self._user32 = private_windll("user32")

    def _visible_windows(
        self,
        pid: int,
    ) -> tuple[tuple[int, bool], ...]:
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )
        user32 = self._user32
        user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        windows: list[tuple[int, bool]] = []

        @callback_type
        def collect(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            owner = bool(user32.GetWindow(hwnd, _GW_OWNER))
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if int(window_pid.value) == pid:
                windows.append((int(hwnd), owner))
            return True

        if not user32.EnumWindows(collect, 0):
            raise OSError(ctypes.get_last_error(), "EnumWindows failed")
        return tuple(windows)

    def snapshot(self, pid: int) -> ProcessWindowSnapshot:
        windows = self._visible_windows(pid)
        owned_count = sum(1 for _hwnd, owned in windows if owned)
        return ProcessWindowSnapshot(
            visible_count=len(windows),
            unowned_count=len(windows) - owned_count,
            owned_count=owned_count,
        )

    def request_close(self, pid: int) -> int:
        user32 = self._user32
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        requested = 0
        for hwnd, owned in self._visible_windows(pid):
            if owned:
                continue
            if user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0):
                requested += 1
        return requested


def cleanup_disposable_processes(
    launched: Sequence[DisposableProcess],
    *,
    windows: ProcessWindows | None = None,
    wait_seconds: float = 5.0,
    poll_interval_seconds: float = 0.1,
    stable_zero_observations: int = 3,
    sleep: Callable[[float], None] = time.sleep,
    timeout_error: type[Exception] = subprocess.TimeoutExpired,
) -> tuple[DisposableCleanup, ...]:
    """Close exact windows and fail closed around unresolved dialog choices."""

    if (
        not math.isfinite(wait_seconds)
        or wait_seconds <= 0
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
        or isinstance(stable_zero_observations, bool)
        or not isinstance(stable_zero_observations, int)
        or stable_zero_observations < 2
    ):
        raise ValueError("cleanup timing and stability must be finite and positive")
    process_windows = windows or Win32ProcessWindows()
    max_observations = max(1, math.floor(wait_seconds / poll_interval_seconds) + 1)
    results: list[DisposableCleanup] = []
    for fixture in reversed(launched):
        process = fixture.process
        disposition = "already_exited"
        exit_code: int | None = None
        close_requests = 0
        window_cleanup_verified = False
        try:
            exit_code = process.poll()
            if exit_code is not None:
                window_cleanup_verified = True
            else:
                initial = process_windows.snapshot(process.pid)
                if initial.visible_count:
                    close_requests = process_windows.request_close(process.pid)
                    remaining = initial
                    stable_zero_count = 0
                    for observation in range(max_observations):
                        remaining = process_windows.snapshot(process.pid)
                        if remaining.visible_count == 0:
                            stable_zero_count += 1
                            if stable_zero_count >= stable_zero_observations:
                                break
                        else:
                            stable_zero_count = 0
                        if observation + 1 < max_observations:
                            sleep(poll_interval_seconds)
                    if stable_zero_count >= stable_zero_observations:
                        disposition = "windows_closed"
                        window_cleanup_verified = True
                        exit_code = process.poll()
                    elif remaining.owned_count:
                        disposition = "handoff_required"
                    elif remaining.visible_count == 0:
                        # A single zero at the deadline is not enough evidence
                        # to terminate or to claim that cleanup completed.
                        disposition = "handoff_required"
                    else:
                        process.terminate()
                        disposition = "terminated_after_close_timeout"
                        try:
                            exit_code = process.wait(timeout=wait_seconds)
                        except timeout_error:
                            process.kill()
                            disposition = "killed_after_close_timeout"
                            exit_code = process.wait(timeout=wait_seconds)
                        window_cleanup_verified = True
                else:
                    process.terminate()
                    disposition = "terminated_without_window"
                    try:
                        exit_code = process.wait(timeout=wait_seconds)
                    except timeout_error:
                        process.kill()
                        disposition = "killed_without_window"
                        exit_code = process.wait(timeout=wait_seconds)
                    window_cleanup_verified = True
        except Exception:
            disposition = "handoff_required"
            window_cleanup_verified = False
            try:
                exit_code = process.poll()
            except Exception:
                exit_code = None
        try:
            process_running = process.poll() is None
        except Exception:
            disposition = "handoff_required"
            window_cleanup_verified = False
            process_running = True
        results.append(
            DisposableCleanup(
                fixture.application,
                process.pid,
                disposition,
                exit_code,
                close_requests,
                window_cleanup_verified,
                process_running,
            )
        )
    return tuple(results)


__all__ = [
    "DisposableCleanup",
    "DisposableProcess",
    "ProcessHandle",
    "ProcessWindowSnapshot",
    "ProcessWindows",
    "Win32ProcessWindows",
    "cleanup_disposable_processes",
]
