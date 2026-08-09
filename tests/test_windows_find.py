from __future__ import annotations

import pytest

from computer_use_mcp.contract import Node, PruneOpts, Rect, Result, STALE_ELEMENT
from computer_use_mcp.core import Session
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


def _node(
    index: int,
    *,
    name: str,
    role: str = "Button",
    native_id: str | None = None,
) -> Node:
    return Node(
        native_id=native_id or f"node-{index}",
        role=role,
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


def test_explicit_scope_relocation_finds_an_unnamed_target_after_snapshot_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _Control(_node(200, name="", native_id="needle-old"))
    root = _Control(children=[old])
    driver = WindowsDriver.__new__(WindowsDriver)
    monkeypatch.setattr(driver, "_root_for_scope", lambda _opts: root)
    monkeypatch.setattr(driver, "_rect_of", lambda _ctrl: Rect(0, 0, 1000, 1000))
    monkeypatch.setattr(driver, "_children", lambda control: control.children)
    monkeypatch.setattr(
        driver,
        "_maybe_node",
        lambda control, wanted, _clip, _opts: (
            control.node
            if control.node is not None and control.node.role in wanted
            else None
        ),
    )
    monkeypatch.setattr(driver, "snapshot_warmup_delay", lambda _scope: 0.0)
    find_requests: list[tuple[str, tuple[str, ...]]] = []
    real_find = driver.find

    def recording_find(opts: PruneOpts, query: str):
        find_requests.append((query, opts.resolved_types()))
        return real_find(opts, query)

    monkeypatch.setattr(driver, "find", recording_find)
    invoked: list[str] = []

    def invoke(native_id: str) -> Result:
        invoked.append(native_id)
        if native_id == "needle-old":
            return Result.fail(STALE_ELEMENT)
        return Result.success()

    monkeypatch.setattr(driver, "invoke", invoke)
    session = Session(driver)
    found = session.find("Button", scope="123")
    ref = next(
        line.split(" | ", 1)[0]
        for line in found.splitlines()
        if line.startswith("ref_")
    )
    root.children = [
        _Control(_node(index, name=f"Button decoy {index}", role="Edit"))
        for index in range(200)
    ] + [_Control(_node(200, name="", native_id="needle-new"))]

    result = session.click(ref=ref, backend="uia")

    assert result.ok is True
    assert invoked == ["needle-old", "needle-new"]
    assert find_requests == [
        ("Button", PruneOpts().resolved_types()),
        ("Button", ("Button",)),
    ]
