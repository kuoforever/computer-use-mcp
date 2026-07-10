from __future__ import annotations

from computer_use_mcp.contract import Node, Rect, Result, TreeResult
from computer_use_mcp.core import Session


def node(native_id: str, name: str = "Save") -> Node:
    return Node(
        native_id=native_id,
        role="Button",
        name=name,
        value=None,
        bbox=Rect(10, 10, 20, 20),
        states=["enabled"],
        patterns=["invoke"],
    )


class RelocatingDriver:
    def __init__(self) -> None:
        self.trees = [TreeResult([node("old")], truncated=0), TreeResult([node("new")], truncated=0)]
        self.invoked: list[str] = []

    def get_tree(self, _opts) -> TreeResult:
        return self.trees.pop(0)

    def invoke(self, native_id: str) -> Result:
        self.invoked.append(native_id)
        return Result.fail("STALE_ELEMENT") if native_id == "old" else Result.success()


def test_stale_ref_is_relocated_once_by_role_and_name() -> None:
    driver = RelocatingDriver()
    session = Session(driver)
    snapshot = session.ui_snapshot(scope="42")
    ref = snapshot.split(" | ", 1)[0]

    result = session.click(ref=ref)

    assert result.ok is True
    assert driver.invoked == ["old", "new"]


def test_snapshot_surfaces_truncation() -> None:
    class TruncatedDriver:
        def get_tree(self, _opts) -> TreeResult:
            return TreeResult([node("one")], truncated=3)

    snapshot = Session(TruncatedDriver()).ui_snapshot()

    assert "# … 3 more truncated" in snapshot
