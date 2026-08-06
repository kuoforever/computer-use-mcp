from __future__ import annotations

import pytest

from computer_use_mcp.contract import Node, PruneOpts, Rect
from computer_use_mcp.drivers.windows import WindowsDriver


class _Control:
    def __init__(
        self,
        node: Node | None = None,
        *,
        children: list[_Control] | None = None,
    ) -> None:
        self.node = node
        self.children = children or []


def _node(index: int, *, name: str) -> Node:
    return Node(
        native_id=f"node-{index}",
        role="Button",
        name=name,
        value=None,
        bbox=Rect(index, 0, 1, 1),
        states=[],
        patterns=["invoke"],
    )


def test_windows_find_filters_before_applying_the_result_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controls = [
        _Control(_node(index, name="Needle" if index == 200 else f"Item {index}"))
        for index in range(201)
    ]
    root = _Control(children=controls)
    driver = WindowsDriver.__new__(WindowsDriver)
    monkeypatch.setattr(driver, "_root_for_scope", lambda _opts: root)
    monkeypatch.setattr(driver, "_rect_of", lambda _ctrl: Rect(0, 0, 1000, 1000))
    monkeypatch.setattr(driver, "_children", lambda control: control.children)
    monkeypatch.setattr(
        driver,
        "_maybe_node",
        lambda control, _wanted, _clip, _opts: control.node,
    )
    opts = PruneOpts(scope="foreground", max_nodes=200)

    snapshot = driver.get_tree(opts)
    found = driver.find(opts, "Needle")

    assert len(snapshot.nodes) == 200
    assert snapshot.truncated == 1
    assert [node.name for node in found.nodes] == ["Needle"]
    assert found.truncated == 0
    assert driver._node_cache == {"node-200": controls[200]}

    root.children.append(controls[200])
    all_buttons = driver.find(opts, "Button")

    assert len(all_buttons.nodes) == 200
    assert all_buttons.truncated == 1
