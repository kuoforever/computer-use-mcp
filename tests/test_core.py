from __future__ import annotations

from computer_use_mcp.contract import (
    NOT_INVOKABLE,
    STALE_ELEMENT,
    Node,
    PruneOpts,
    Rect,
    Result,
    TreeResult,
)
from computer_use_mcp.core import Session


def node(
    native_id: str,
    name: str = "Save",
    *,
    patterns: tuple[str, ...] = ("invoke",),
) -> Node:
    return Node(
        native_id=native_id,
        role="Button",
        name=name,
        value=None,
        bbox=Rect(10, 10, 20, 20),
        states=["enabled"],
        patterns=list(patterns),
    )


class RefDriver:
    def __init__(
        self,
        trees: list[tuple[str, TreeResult]],
        *,
        stale_native_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.trees = list(trees)
        self.stale_native_ids = stale_native_ids
        self.tree_scopes: list[str] = []
        self.invoked: list[str] = []
        self.selected: list[str] = []
        self.coordinate_clicks: list[tuple[int, int, str]] = []

    def get_tree(self, opts: PruneOpts) -> TreeResult:
        self.tree_scopes.append(opts.scope)
        expected_scope, tree = self.trees.pop(0)
        assert opts.scope == expected_scope
        return tree

    def invoke(self, native_id: str) -> Result:
        self.invoked.append(native_id)
        if native_id in self.stale_native_ids:
            return Result.fail(STALE_ELEMENT)
        return Result.success()

    def select(self, native_id: str) -> Result:
        self.selected.append(native_id)
        if native_id in self.stale_native_ids:
            return Result.fail(STALE_ELEMENT)
        return Result.success()

    def click(self, x: int, y: int, button: str = "left") -> Result:
        self.coordinate_clicks.append((x, y, button))
        return Result.success()


def snapshot_ref(snapshot: str) -> str:
    return snapshot.split(" | ", 1)[0]


def test_stale_foreground_ref_does_not_relocate_into_new_foreground_window() -> None:
    driver = RefDriver(
        [
            ("foreground", TreeResult([node("window-a-old")], truncated=0)),
            (
                "foreground",
                TreeResult(
                    [node("window-b-candidate", patterns=("selectionitem",))],
                    truncated=0,
                ),
            ),
        ],
        stale_native_ids=frozenset({"window-a-old"}),
    )
    session = Session(driver)
    ref = snapshot_ref(session.ui_snapshot())
    bindings_before = (
        dict(session._by_ref),
        dict(session._native_by_ref),
        dict(session._ref_by_native),
        dict(session._scope_by_ref),
    )

    result = session.click(ref=ref)

    assert result == Result.fail(
        STALE_ELEMENT,
        f"{ref} is stale in a dynamic scope; re-snapshot",
    )
    assert driver.tree_scopes == ["foreground"]
    assert driver.invoked == ["window-a-old"]
    assert driver.selected == []
    assert driver.coordinate_clicks == []
    assert (
        session._by_ref,
        session._native_by_ref,
        session._ref_by_native,
        session._scope_by_ref,
    ) == bindings_before


def test_stale_all_scope_ref_does_not_query_or_act_on_relocation_candidate() -> None:
    driver = RefDriver(
        [
            ("all", TreeResult([node("all-old")], truncated=0)),
            (
                "all",
                TreeResult(
                    [node("other-window-candidate", patterns=("selectionitem",))],
                    truncated=0,
                ),
            ),
        ],
        stale_native_ids=frozenset({"all-old"}),
    )
    session = Session(driver)
    ref = snapshot_ref(session.ui_snapshot(scope="all"))
    bindings_before = (
        dict(session._by_ref),
        dict(session._native_by_ref),
        dict(session._ref_by_native),
        dict(session._scope_by_ref),
    )

    result = session.click(ref=ref)

    assert result == Result.fail(
        STALE_ELEMENT,
        f"{ref} is stale in a dynamic scope; re-snapshot",
    )
    assert driver.tree_scopes == ["all"]
    assert driver.invoked == ["all-old"]
    assert driver.selected == []
    assert driver.coordinate_clicks == []
    assert (
        session._by_ref,
        session._native_by_ref,
        session._ref_by_native,
        session._scope_by_ref,
    ) == bindings_before


def test_later_observation_cannot_move_ref_relocation_scope() -> None:
    driver = RefDriver(
        [
            ("window-A", TreeResult([node("a-old")], truncated=0)),
            ("window-B", TreeResult([node("b-current")], truncated=0)),
            (
                "window-A",
                TreeResult(
                    [node("a-new", patterns=("selectionitem",))],
                    truncated=0,
                ),
            ),
        ],
        stale_native_ids=frozenset({"a-old"}),
    )
    session = Session(driver)
    ref_a = snapshot_ref(session.ui_snapshot(scope="window-A"))
    ref_b = snapshot_ref(session.ui_snapshot(scope="window-B"))

    result = session.click(ref=ref_a)

    assert ref_a != ref_b
    assert result.ok is True
    assert driver.tree_scopes == ["window-A", "window-B", "window-A"]
    assert driver.invoked == ["a-old"]
    assert driver.selected == ["a-new"]
    assert driver.coordinate_clicks == []


def test_foreign_scope_candidate_is_never_used_when_original_scope_has_none() -> None:
    driver = RefDriver(
        [
            ("window-A", TreeResult([node("a-old")], truncated=0)),
            ("window-B", TreeResult([node("b-new")], truncated=0)),
            ("window-A", TreeResult([], truncated=0)),
        ],
        stale_native_ids=frozenset({"a-old"}),
    )
    session = Session(driver)
    ref = snapshot_ref(session.ui_snapshot(scope="window-A"))
    session.ui_snapshot(scope="window-B")

    result = session.click(ref=ref)

    assert result == Result.fail(
        STALE_ELEMENT,
        f"{ref} is stale and could not be relocated; re-snapshot",
    )
    assert driver.tree_scopes == ["window-A", "window-B", "window-A"]
    assert driver.invoked == ["a-old"]
    assert driver.selected == []
    assert driver.coordinate_clicks == []


def test_successful_relocation_rebinds_node_and_native_maps_bijectively() -> None:
    relocated = node("new")
    driver = RefDriver(
        [
            ("101", TreeResult([node("old")], truncated=0)),
            ("101", TreeResult([relocated], truncated=0)),
            (
                "101",
                TreeResult([relocated, node("old")], truncated=0),
            ),
        ],
        stale_native_ids=frozenset({"old"}),
    )
    session = Session(driver)
    ref = snapshot_ref(session.ui_snapshot(scope="101"))

    result = session.click(ref=ref)
    refreshed_refs = [
        line.split(" | ", 1)[0]
        for line in session.ui_snapshot(scope="101").splitlines()
    ]

    assert result.ok is True
    assert refreshed_refs[0] == ref
    assert refreshed_refs[1] != ref
    assert driver.tree_scopes == ["101", "101", "101"]
    assert driver.invoked == ["old", "new"]
    assert session._by_ref[ref] == relocated
    assert session._native_by_ref == {ref: "new", refreshed_refs[1]: "old"}
    assert session._ref_by_native == {"new": ref, "old": refreshed_refs[1]}
    assert session._scope_by_ref == {
        ref: "101",
        refreshed_refs[1]: "101",
    }


def test_relocation_reverse_collision_fails_before_candidate_action() -> None:
    driver = RefDriver(
        [
            (
                "101",
                TreeResult([node("old"), node("owned", name="Other")], truncated=0),
            ),
            ("101", TreeResult([node("owned")], truncated=0)),
        ],
        stale_native_ids=frozenset({"old"}),
    )
    session = Session(driver)
    snapshot = session.ui_snapshot(scope="101")
    old_ref, owner_ref = [line.split(" | ", 1)[0] for line in snapshot.splitlines()]

    result = session.click(ref=old_ref)

    assert result == Result.fail(
        STALE_ELEMENT,
        f"{old_ref} is stale and relocation conflicts with another ref; re-snapshot",
    )
    assert driver.tree_scopes == ["101", "101"]
    assert driver.invoked == ["old"]
    assert driver.selected == []
    assert driver.coordinate_clicks == []
    assert session._native_by_ref == {old_ref: "old", owner_ref: "owned"}
    assert session._ref_by_native == {"old": old_ref, "owned": owner_ref}
    assert session._by_ref[old_ref].native_id == "old"


def test_same_native_cross_scope_reuses_ref_and_first_scope() -> None:
    driver = RefDriver(
        [
            ("scope-A", TreeResult([node("shared")], truncated=0)),
            ("scope-B", TreeResult([node("shared")], truncated=0)),
            ("scope-A", TreeResult([node("a-new")], truncated=0)),
        ],
        stale_native_ids=frozenset({"shared"}),
    )
    session = Session(driver)
    first_ref = snapshot_ref(session.ui_snapshot(scope="scope-A"))
    second_ref = snapshot_ref(session.ui_snapshot(scope="scope-B"))

    result = session.click(ref=first_ref)

    assert second_ref == first_ref
    assert result.ok is True
    assert driver.tree_scopes == ["scope-A", "scope-B", "scope-A"]
    assert driver.invoked == ["shared", "a-new"]
    assert session._scope_by_ref == {first_ref: "scope-A"}


def test_unknown_ref_fails_without_any_driver_call() -> None:
    driver = RefDriver([])

    result = Session(driver).click(ref="ref_999")

    assert result == Result.fail(
        STALE_ELEMENT,
        "ref_999 not in current snapshot; call ui_snapshot first",
    )
    assert driver.tree_scopes == []
    assert driver.invoked == []
    assert driver.selected == []
    assert driver.coordinate_clicks == []
    assert driver.trees == []


def test_ref_without_semantic_action_never_falls_back_to_coordinates() -> None:
    driver = RefDriver(
        [("scope-A", TreeResult([node("target", patterns=())], truncated=0))]
    )
    session = Session(driver)
    ref = snapshot_ref(session.ui_snapshot(scope="scope-A"))

    result = session.click(ref=ref)

    assert result == Result.fail(
        NOT_INVOKABLE,
        "ref exposes no supported accessibility action",
    )
    assert driver.tree_scopes == ["scope-A"]
    assert driver.invoked == []
    assert driver.selected == []
    assert driver.coordinate_clicks == []


def test_snapshot_surfaces_truncation() -> None:
    class TruncatedDriver:
        def get_tree(self, _opts) -> TreeResult:
            return TreeResult([node("one")], truncated=3)

    snapshot = Session(TruncatedDriver()).ui_snapshot()

    assert "# … 3 more truncated" in snapshot
