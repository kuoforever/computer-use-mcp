from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path

from computer_use_mcp.contract import ProcRef, Result
from computer_use_mcp.human_activity import HumanActivity, HumanInputCapture
from computer_use_mcp.native_authority import NativeActionBoundary
from computer_use_mcp.safety import EStop
from computer_use_mcp.server import build_server


class FakeDriver:
    def __init__(self, idle_seconds: float) -> None:
        self.idle_seconds = idle_seconds
        self.input_tick = 1
        self.key_calls = 0
        self.activate_calls = 0
        self.native_boundary: NativeActionBoundary | None = None

    def bind_native_action_boundary(self, boundary: NativeActionBoundary) -> None:
        boundary.bind(self)
        self.native_boundary = boundary

    def _mutate(self, operation, *, native_input: bool = False):
        assert self.native_boundary is not None
        return self.native_boundary.mutate(operation, native_input=native_input)

    def last_input_idle_seconds(self) -> float:
        return self.idle_seconds

    def last_input_tick(self) -> int:
        return self.input_tick

    def foreground_owner_chain(self) -> list[ProcRef]:
        return [ProcRef(pid=1, name="notepad.exe")]

    def key(self, _combo: str) -> Result:
        self._mutate(self._record_key, native_input=True)
        return Result.success()

    def _record_key(self) -> None:
        self.key_calls += 1

    def activate_window(self, _window_id: str) -> Result:
        self._mutate(self._record_activation)
        return Result.success()

    def _record_activation(self) -> None:
        self.activate_calls += 1


class SamplingDriver(FakeDriver):
    def __init__(self, idle_samples: tuple[float, ...]) -> None:
        super().__init__(idle_seconds=0.0)
        self.idle_samples = deque(idle_samples)

    def last_input_idle_seconds(self) -> float:
        return self.idle_samples.popleft()


def tool_text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(item, "text", "") for item in content)


class HumanActivityTests(unittest.TestCase):
    def test_recent_and_idle_input_are_distinguished(self) -> None:
        self.assertIsNotNone(HumanActivity(FakeDriver(0.2), idle_seconds=1.0).blocking_reason())
        self.assertIsNone(HumanActivity(FakeDriver(1.0), idle_seconds=1.0).blocking_reason())

    def test_agent_injected_input_does_not_block_the_next_action(self) -> None:
        driver = FakeDriver(0.1)
        activity = HumanActivity(driver, idle_seconds=1.0)
        activity.note_agent_action()
        self.assertIsNone(activity.blocking_reason())

        driver.input_tick += 1
        self.assertIsNotNone(activity.blocking_reason())

    def test_final_authority_accepts_only_the_unchanged_ready_input_tick(self) -> None:
        driver = FakeDriver(10.0)
        activity = HumanActivity(driver, idle_seconds=1.0)
        readiness = activity.capture()

        self.assertIsNone(activity.final_blocking_reason(readiness))

        driver.input_tick += 1
        self.assertEqual(
            activity.final_blocking_reason(readiness),
            "human input changed after action readiness",
        )

    def test_final_authority_detects_input_during_its_own_observation(self) -> None:
        class ChangingDuringAgeDriver(FakeDriver):
            def last_input_idle_seconds(self) -> float:
                self.input_tick += 1
                return 10.0

        driver = ChangingDuringAgeDriver(10.0)
        activity = HumanActivity(driver, idle_seconds=1.0)
        readiness = activity.capture()

        self.assertEqual(
            activity.final_blocking_reason(readiness),
            "human input changed during final authority check",
        )

    def test_confirmation_capture_is_exact_and_never_retained(self) -> None:
        driver = FakeDriver(10.0)
        activity = HumanActivity(driver, idle_seconds=1.0)
        readiness = activity.capture()
        driver.idle_seconds = 0.1
        driver.input_tick = 2
        confirmation = activity.capture()

        self.assertEqual(confirmation, HumanInputCapture(2))
        self.assertIsNone(
            activity.final_blocking_reason(
                readiness,
                allowed_confirmation=confirmation,
            )
        )
        self.assertEqual(
            activity.final_blocking_reason(readiness),
            "human input changed after action readiness",
        )

        driver.input_tick = 3
        self.assertEqual(
            activity.final_blocking_reason(
                readiness,
                allowed_confirmation=confirmation,
            ),
            "human input changed after action readiness",
        )

    def test_final_authority_fails_closed_without_input_tick_evidence(self) -> None:
        class UnavailableTickDriver(FakeDriver):
            def last_input_tick(self) -> int:
                raise OSError("unavailable")

        activity = HumanActivity(UnavailableTickDriver(10.0), idle_seconds=1.0)

        self.assertIsNone(activity.capture())
        self.assertEqual(
            activity.final_blocking_reason(None),
            "human input idle state unavailable",
        )

    def test_call_scoped_readiness_requires_one_consecutive_idle_streak(self) -> None:
        driver = SamplingDriver((0.1, 1.1, 0.2, 1.1, 1.2, 1.3))
        sleeps: list[float] = []
        activity = HumanActivity(
            driver,
            idle_seconds=1.0,
            stable_samples=3,
            poll_interval_seconds=0.25,
            max_wait_seconds=2.0,
        )

        reason = activity.wait_until_stable(sleep=sleeps.append)

        self.assertIsNone(reason)
        self.assertEqual(sleeps, [0.25] * 5)
        self.assertEqual(len(driver.idle_samples), 0)

    def test_call_scoped_readiness_fails_closed_without_idle_observation(self) -> None:
        class UnavailableDriver(FakeDriver):
            def last_input_idle_seconds(self) -> float:
                raise OSError("unavailable")

        activity = HumanActivity(
            UnavailableDriver(0.0),
            stable_samples=3,
        )

        self.assertEqual(
            activity.wait_until_stable(sleep=lambda _seconds: None),
            "human input idle state unavailable",
        )

    def test_server_stabilizes_inside_one_call_then_dispatches_once(self) -> None:
        driver = SamplingDriver((0.1, 1.1, 0.2, 1.1, 1.2, 1.3, 1.4, 1.5))
        activity = HumanActivity(
            driver,
            idle_seconds=1.0,
            stable_samples=3,
            poll_interval_seconds=0.001,
            max_wait_seconds=0.01,
        )
        with tempfile.TemporaryDirectory() as directory:
            server = build_server(
                allowlist=["notepad.exe"],
                driver=driver,
                human_activity=activity,
                estop=EStop(),
                start_estop=False,
                audit_path=str(Path(directory) / "audit.jsonl"),
            )
            key = tool_text(
                asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"}))
            )

        self.assertEqual(key, "ok")
        self.assertEqual(driver.key_calls, 1)

    def test_readiness_timeout_rejects_without_dispatch_or_replay(self) -> None:
        driver = FakeDriver(idle_seconds=0.1)
        activity = HumanActivity(
            driver,
            idle_seconds=1.0,
            stable_samples=3,
            poll_interval_seconds=0.001,
            max_wait_seconds=0.002,
        )
        with tempfile.TemporaryDirectory() as directory:
            server = build_server(
                allowlist=["notepad.exe"],
                driver=driver,
                human_activity=activity,
                estop=EStop(),
                start_estop=False,
                audit_path=str(Path(directory) / "audit.jsonl"),
            )
            key = tool_text(
                asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"}))
            )

        self.assertTrue(key.startswith("HUMAN_ACTIVE:"))
        self.assertEqual(driver.key_calls, 0)

    def test_server_fails_closed_when_final_input_tick_is_unavailable(self) -> None:
        class UnavailableTickDriver(FakeDriver):
            def last_input_tick(self) -> int:
                raise OSError("unavailable")

        driver = UnavailableTickDriver(idle_seconds=10.0)
        with tempfile.TemporaryDirectory() as directory:
            server = build_server(
                allowlist=["notepad.exe"],
                driver=driver,
                estop=EStop(),
                start_estop=False,
                audit_path=str(Path(directory) / "audit.jsonl"),
            )
            key = tool_text(
                asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"}))
            )

        self.assertTrue(key.startswith("HUMAN_ACTIVE:"))
        self.assertEqual(driver.key_calls, 0)

    def test_server_blocks_actions_and_activation_while_human_is_active(self) -> None:
        driver = FakeDriver(idle_seconds=0.1)
        with tempfile.TemporaryDirectory() as directory:
            server = build_server(
                allowlist=["notepad.exe"],
                driver=driver,
                estop=EStop(),
                start_estop=False,
                audit_path=str(Path(directory) / "audit.jsonl"),
            )
            key = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
            activate = tool_text(asyncio.run(server.call_tool("activate_window", {"window_id": "1"})))

        self.assertTrue(key.startswith("HUMAN_ACTIVE:"))
        self.assertTrue(activate.startswith("HUMAN_ACTIVE:"))
        self.assertEqual(driver.key_calls, 0)
        self.assertEqual(driver.activate_calls, 0)

    def test_full_control_mode_bypasses_gate_and_human_yield_but_audits(self) -> None:
        driver = FakeDriver(idle_seconds=0.1)
        with tempfile.TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            server = build_server(
                allowlist=["calc.exe"],
                driver=driver,
                estop=EStop(),
                start_estop=False,
                audit_path=str(audit_path),
                control_mode="full_control_local",
            )
            key = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
            audit = json.loads(audit_path.read_text(encoding="utf-8"))

        self.assertEqual(key, "ok")
        self.assertEqual(driver.key_calls, 1)
        self.assertEqual(audit["args"]["control_mode"], "full_control_local")

    def test_full_control_mode_still_honors_estop(self) -> None:
        driver = FakeDriver(idle_seconds=10.0)
        estop = EStop()
        estop.engage()
        with tempfile.TemporaryDirectory() as directory:
            server = build_server(
                driver=driver,
                estop=estop,
                start_estop=False,
                audit_path=str(Path(directory) / "audit.jsonl"),
                control_mode="full_control_local",
            )
            key = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))

        self.assertTrue(key.startswith("ABORTED:"))
        self.assertEqual(driver.key_calls, 0)
