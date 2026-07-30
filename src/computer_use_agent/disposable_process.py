"""Exact-process cleanup for disposable desktop application fixtures.

The cleanup boundary is window-first. It never searches by executable name:
each target is an exact process handle returned by the caller's launch. Visible
unowned top-level windows for that PID receive ``WM_CLOSE``; all visible
top-level windows, including owned dialogs, are observed until gone. A process
may remain alive without an operator-visible window.
Forced termination is reserved for a bounded graceful-close failure or a
partial launch that never exposed a window.
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

_GW_OWNER = 4
_WM_CLOSE = 0x0010


class ProcessHandle(Protocol):
    pid: int

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def wait(self, timeout: float) -> int: ...


class ProcessWindows(Protocol):
    def visible_count(self, pid: int) -> int: ...

    def request_close(self, pid: int) -> int: ...


@dataclass(frozen=True)
class DisposableProcess:
    application: str
    process: ProcessHandle


@dataclass(frozen=True)
class DisposableCleanup:
    application: str
    pid: int
    disposition: str
    exit_code: int | None
    close_requests: int
    process_running: bool


class Win32ProcessWindows:
    """Observe and close only visible, unowned top-level windows for one PID."""

    def __init__(self) -> None:
        self._user32 = ctypes.windll.user32

    def _visible_windows(
        self,
        pid: int,
        *,
        unowned_only: bool,
    ) -> tuple[int, ...]:
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
        windows: list[int] = []

        @callback_type
        def collect(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            if unowned_only and user32.GetWindow(hwnd, _GW_OWNER):
                return True
            window_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            if int(window_pid.value) == pid:
                windows.append(int(hwnd))
            return True

        if not user32.EnumWindows(collect, 0):
            raise OSError(ctypes.get_last_error(), "EnumWindows failed")
        return tuple(windows)

    def visible_count(self, pid: int) -> int:
        return len(self._visible_windows(pid, unowned_only=False))

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
        for hwnd in self._visible_windows(pid, unowned_only=True):
            if user32.PostMessageW(hwnd, _WM_CLOSE, 0, 0):
                requested += 1
        return requested


def cleanup_disposable_processes(
    launched: Sequence[DisposableProcess],
    *,
    windows: ProcessWindows | None = None,
    wait_seconds: float = 5.0,
    poll_interval_seconds: float = 0.1,
    sleep: Callable[[float], None] = time.sleep,
    timeout_error: type[BaseException] = subprocess.TimeoutExpired,
) -> tuple[DisposableCleanup, ...]:
    """Close exact owned windows, then force only when they remain visible."""

    if (
        not math.isfinite(wait_seconds)
        or wait_seconds <= 0
        or not math.isfinite(poll_interval_seconds)
        or poll_interval_seconds <= 0
    ):
        raise ValueError("cleanup timing must be finite and positive")
    process_windows = windows or Win32ProcessWindows()
    max_observations = max(1, math.ceil(wait_seconds / poll_interval_seconds))
    results: list[DisposableCleanup] = []
    for fixture in reversed(launched):
        process = fixture.process
        disposition = "already_exited"
        exit_code: int | None = None
        close_requests = 0
        try:
            exit_code = process.poll()
            if exit_code is None:
                initial_windows = process_windows.visible_count(process.pid)
                if initial_windows:
                    close_requests = process_windows.request_close(process.pid)
                    remaining = initial_windows
                    for observation in range(max_observations):
                        remaining = process_windows.visible_count(process.pid)
                        if remaining == 0:
                            break
                        if observation + 1 < max_observations:
                            sleep(poll_interval_seconds)
                    if remaining == 0:
                        disposition = "windows_closed"
                        exit_code = process.poll()
                    else:
                        process.terminate()
                        disposition = "terminated_after_close_timeout"
                        try:
                            exit_code = process.wait(timeout=wait_seconds)
                        except timeout_error:
                            process.kill()
                            disposition = "killed_after_close_timeout"
                            exit_code = process.wait(timeout=wait_seconds)
                else:
                    process.terminate()
                    disposition = "terminated_without_window"
                    try:
                        exit_code = process.wait(timeout=wait_seconds)
                    except timeout_error:
                        process.kill()
                        disposition = "killed_without_window"
                        exit_code = process.wait(timeout=wait_seconds)
        except (OSError, timeout_error):
            disposition = "handoff_required"
            try:
                exit_code = process.poll()
            except OSError:
                exit_code = None
        try:
            process_running = process.poll() is None
        except OSError:
            disposition = "handoff_required"
            process_running = True
        results.append(
            DisposableCleanup(
                fixture.application,
                process.pid,
                disposition,
                exit_code,
                close_requests,
                process_running,
            )
        )
    return tuple(results)


__all__ = [
    "DisposableCleanup",
    "DisposableProcess",
    "ProcessHandle",
    "ProcessWindows",
    "Win32ProcessWindows",
    "cleanup_disposable_processes",
]
