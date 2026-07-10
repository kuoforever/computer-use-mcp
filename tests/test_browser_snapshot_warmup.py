from __future__ import annotations

import unittest
from unittest.mock import patch

from computer_use_mcp.contract import Node, Rect, TreeResult
from computer_use_mcp.core import Session


class FakeDriver:
    def __init__(self, warmup_delay: float) -> None:
        self.warmup_delay = warmup_delay
        self.calls = 0

    def snapshot_warmup_delay(self, scope: str) -> float:
        assert scope == "123"
        return self.warmup_delay

    def get_tree(self, _opts) -> TreeResult:
        self.calls += 1
        return TreeResult(nodes=[Node(
            native_id="node-1",
            role="Button",
            name="Ready",
            value=None,
            bbox=Rect(0, 0, 10, 10),
            states=[],
            patterns=["invoke"],
        )], truncated=0)


class IncompleteBrowserDriver(FakeDriver):
    def snapshot_incomplete_reason(self, scope: str, _tree: TreeResult) -> str | None:
        assert scope == "123"
        return "browser content controls are not exposed yet"


class BrowserSnapshotWarmupTests(unittest.TestCase):
    def test_browser_snapshot_warms_up_before_returning_result(self) -> None:
        driver = FakeDriver(warmup_delay=1.0)
        with patch("computer_use_mcp.core.time.sleep") as sleep:
            snapshot = Session(driver).ui_snapshot(scope="123")

        self.assertEqual(driver.calls, 2)
        sleep.assert_called_once_with(1.0)
        self.assertIn('button "Ready"', snapshot)

    def test_non_browser_snapshot_is_read_once(self) -> None:
        driver = FakeDriver(warmup_delay=0.0)
        with patch("computer_use_mcp.core.time.sleep") as sleep:
            Session(driver).ui_snapshot(scope="123")

        self.assertEqual(driver.calls, 1)
        sleep.assert_not_called()

    def test_incomplete_browser_snapshot_is_explicit(self) -> None:
        driver = IncompleteBrowserDriver(warmup_delay=0.0)

        snapshot = Session(driver).ui_snapshot(scope="123")

        self.assertIn("# incomplete: browser content controls are not exposed yet", snapshot)
