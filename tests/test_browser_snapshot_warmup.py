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


class LazyFindDriver(FakeDriver):
    def __init__(self, warmup_delay: float) -> None:
        super().__init__(warmup_delay)
        self.get_tree_calls = 0
        self.find_queries: list[str] = []

    def _walk(self) -> TreeResult:
        self.calls += 1
        if self.calls == 1:
            return TreeResult(nodes=[], truncated=0)
        return TreeResult(nodes=[Node(
            native_id="node-1",
            role="Button",
            name="Ready",
            value=None,
            bbox=Rect(0, 0, 10, 10),
            states=[],
            patterns=["invoke"],
        )], truncated=0)

    def get_tree(self, _opts) -> TreeResult:
        self.get_tree_calls += 1
        return self._walk()

    def find(self, _opts, query: str) -> TreeResult:
        self.find_queries.append(query)
        return self._walk()


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

    def test_browser_find_warms_up_before_running_query(self) -> None:
        driver = LazyFindDriver(warmup_delay=1.0)
        with patch("computer_use_mcp.core.time.sleep") as sleep:
            found = Session(driver).find("Ready", scope="123")

        self.assertEqual(driver.calls, 2)
        self.assertEqual(driver.get_tree_calls, 1)
        self.assertEqual(driver.find_queries, ["Ready"])
        sleep.assert_called_once_with(1.0)
        self.assertIn('button "Ready"', found)

    def test_incomplete_browser_snapshot_is_explicit(self) -> None:
        driver = IncompleteBrowserDriver(warmup_delay=0.0)

        snapshot = Session(driver).ui_snapshot(scope="123")

        self.assertIn("# incomplete: browser content controls are not exposed yet", snapshot)
