from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path

from computer_use_mcp.contract import ProcRef, Result
from computer_use_mcp.human_activity import HumanActivity
from computer_use_mcp.safety import EStop
from computer_use_mcp.server import build_server


class FakeDriver:
    def __init__(self, idle_seconds: float) -> None:
        self.idle_seconds = idle_seconds
        self.input_tick = 1
        self.key_calls = 0
        self.activate_calls = 0

    def last_input_idle_seconds(self) -> float:
        return self.idle_seconds

    def last_input_tick(self) -> int:
        return self.input_tick

    def foreground_owner_chain(self) -> list[ProcRef]:
        return [ProcRef(pid=1, name="notepad.exe")]

    def key(self, _combo: str) -> Result:
        self.key_calls += 1
        return Result.success()

    def activate_window(self, _window_id: str) -> Result:
        self.activate_calls += 1
        return Result.success()


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
        driver = SamplingDriver((0.1, 1.1, 0.2, 1.1, 1.2, 1.3))
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
