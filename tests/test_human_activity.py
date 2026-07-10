from __future__ import annotations

import asyncio
import tempfile
import unittest
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
