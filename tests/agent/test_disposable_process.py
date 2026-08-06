from __future__ import annotations

import subprocess

import pytest

from computer_use_agent.disposable_process import (
    DisposableProcess,
    ProcessWindowSnapshot,
    cleanup_disposable_processes,
)


class Process:
    def __init__(
        self,
        pid: int,
        *,
        wait_times_out: bool = False,
        poll_failures: int = 0,
    ) -> None:
        self.pid = pid
        self.exit_code: int | None = None
        self.wait_times_out = wait_times_out
        self.poll_failures = poll_failures
        self.terminated = 0
        self.killed = 0

    def poll(self) -> int | None:
        if self.poll_failures:
            self.poll_failures -= 1
            raise OSError("synthetic poll failure")
        return self.exit_code

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1
        self.exit_code = -9

    def wait(self, timeout: float) -> int:
        del timeout
        if self.wait_times_out and not self.killed:
            raise subprocess.TimeoutExpired("synthetic", 0)
        if self.exit_code is None:
            self.exit_code = 0
        return self.exit_code


class Windows:
    def __init__(
        self,
        states: dict[int, list[int | ProcessWindowSnapshot]],
        *,
        fail_pid: int | None = None,
    ) -> None:
        self.states = {pid: list(values) for pid, values in states.items()}
        self.fail_pid = fail_pid
        self.closed: list[int] = []

    def snapshot(self, pid: int) -> ProcessWindowSnapshot:
        if pid == self.fail_pid:
            raise OSError("synthetic observation failure")
        values = self.states[pid]
        if len(values) > 1:
            value = values.pop(0)
        else:
            value = values[0]
        if isinstance(value, int):
            return ProcessWindowSnapshot(value, value, 0)
        return value

    def request_close(self, pid: int) -> int:
        self.closed.append(pid)
        return 1


def test_stably_absent_windows_are_the_completion_boundary_not_process_exit() -> None:
    process = Process(101)

    cleanup = cleanup_disposable_processes(
        (DisposableProcess("Word", process),),
        windows=Windows({101: [1, 0, 0, 0]}),
        sleep=lambda _seconds: None,
    )

    assert cleanup[0].disposition == "windows_closed"
    assert cleanup[0].window_cleanup_verified is True
    assert cleanup[0].process_running is True
    assert cleanup[0].close_requests == 1
    assert process.terminated == 0
    assert process.killed == 0


def test_remaining_window_uses_bounded_terminate_then_kill_fallback() -> None:
    process = Process(101, wait_times_out=True)

    cleanup = cleanup_disposable_processes(
        (DisposableProcess("Word", process),),
        windows=Windows({101: [1, 1]}),
        wait_seconds=0.1,
        poll_interval_seconds=0.1,
        sleep=lambda _seconds: None,
    )

    assert cleanup[0].disposition == "killed_after_close_timeout"
    assert cleanup[0].window_cleanup_verified is True
    assert cleanup[0].process_running is False
    assert process.terminated == 1
    assert process.killed == 1


def test_unavailable_window_observation_fails_to_explicit_handoff() -> None:
    process = Process(101)

    cleanup = cleanup_disposable_processes(
        (DisposableProcess("Word", process),),
        windows=Windows({101: [1]}, fail_pid=101),
    )

    assert cleanup[0].disposition == "handoff_required"
    assert cleanup[0].window_cleanup_verified is False
    assert cleanup[0].process_running is True
    assert process.terminated == 0
    assert process.killed == 0


def test_zero_window_stability_resets_when_a_window_reappears() -> None:
    process = Process(101)

    cleanup = cleanup_disposable_processes(
        (DisposableProcess("Word", process),),
        windows=Windows({101: [1, 0, 1, 0, 0, 0]}),
        wait_seconds=1.0,
        poll_interval_seconds=0.1,
        sleep=lambda _seconds: None,
    )

    assert cleanup[0].disposition == "windows_closed"
    assert cleanup[0].window_cleanup_verified is True
    assert process.terminated == 0


def test_owned_dialog_requires_handoff_instead_of_force_termination() -> None:
    process = Process(101)
    dialog = ProcessWindowSnapshot(2, 1, 1)

    cleanup = cleanup_disposable_processes(
        (DisposableProcess("Word", process),),
        windows=Windows({101: [1, dialog]}),
        wait_seconds=0.1,
        poll_interval_seconds=0.1,
        sleep=lambda _seconds: None,
    )

    assert cleanup[0].disposition == "handoff_required"
    assert cleanup[0].window_cleanup_verified is False
    assert cleanup[0].process_running is True
    assert process.terminated == 0
    assert process.killed == 0


def test_partial_launch_without_a_window_terminates_the_exact_process() -> None:
    process = Process(101)

    cleanup = cleanup_disposable_processes(
        (DisposableProcess("Word", process),),
        windows=Windows({101: [0]}),
    )

    assert cleanup[0].disposition == "terminated_without_window"
    assert cleanup[0].process_running is False
    assert process.terminated == 1


def test_one_broken_process_does_not_skip_later_cleanup_targets() -> None:
    healthy = Process(101)
    broken = Process(202, poll_failures=1)

    cleanup = cleanup_disposable_processes(
        (
            DisposableProcess("Healthy", healthy),
            DisposableProcess("Broken", broken),
        ),
        windows=Windows({101: [0], 202: [0]}),
    )

    assert [item.application for item in cleanup] == ["Broken", "Healthy"]
    assert cleanup[0].disposition == "handoff_required"
    assert cleanup[1].disposition == "terminated_without_window"
    assert healthy.terminated == 1


@pytest.mark.parametrize(
    ("wait_seconds", "poll_seconds"),
    [(0, 0.1), (1, 0), (float("inf"), 0.1)],
)
def test_cleanup_rejects_unbounded_or_nonpositive_timing(
    wait_seconds: float,
    poll_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        cleanup_disposable_processes(
            (),
            wait_seconds=wait_seconds,
            poll_interval_seconds=poll_seconds,
        )
