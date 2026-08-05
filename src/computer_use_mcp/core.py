"""Core layer — the model-facing session over a platform Driver.

This is the platform-agnostic half of the system. It owns the ref<->native_id
table and its lifecycle (Driver Contract section D): the model only ever sees
stable ``ref_N`` handles; the driver only ever sees ``native_id``. Refs stay
stable across snapshots where the native_id is unchanged, and an action on a
stale ref is relocated once by (role, name) inside its original observation
scope. Accepted relocation keeps the node/native reverse bindings consistent.

The MCP server is a thin wrapper that exposes these methods as reviewed tools.
"""
from __future__ import annotations

import time

from .contract import (
    DRIVER_ERROR,
    NOT_INVOKABLE,
    STALE_ELEMENT,
    Driver,
    DriverError,
    Image,
    Node,
    PruneOpts,
    Rect,
    Result,
    TreeResult,
)


class Session:
    def __init__(self, driver: Driver) -> None:
        self.driver = driver
        self._by_ref: dict[str, Node] = {}         # ref -> Node from the last snapshot
        self._native_by_ref: dict[str, str] = {}   # ref -> native_id
        self._ref_by_native: dict[str, str] = {}   # native_id -> ref (for stability)
        self._scope_by_ref: dict[str, str] = {}     # ref -> first observation scope
        self._counter = 0

    # --- perception ----------------------------------------------------------

    def ui_snapshot(self, scope: str = "foreground", max_nodes: int = 200) -> str:
        # Browser accessibility trees may be populated lazily by the first UIA
        # walk. Drivers that know this applies can request a best-effort warmup
        # without widening the frozen Driver contract.
        warmup_delay = getattr(self.driver, "snapshot_warmup_delay", lambda _scope: 0.0)(scope)
        if warmup_delay > 0:
            try:
                self.driver.get_tree(PruneOpts(scope=scope, max_nodes=max_nodes))
            except DriverError:
                pass
            time.sleep(warmup_delay)
        tree = self.driver.get_tree(PruneOpts(scope=scope, max_nodes=max_nodes))
        incomplete_reason = getattr(
            self.driver, "snapshot_incomplete_reason", lambda _scope, _tree: None
        )(scope, tree)
        return self._ingest(tree, scope, footer=incomplete_reason)

    def find(self, query: str, scope: str = "foreground", max_nodes: int = 200) -> str:
        tree = self.driver.find(PruneOpts(scope=scope, max_nodes=max_nodes), query)
        return self._ingest(tree, scope, header=f"find {query!r}")

    def screenshot(self, region: Rect | None = None) -> Image:
        return self.driver.capture_screen(region)

    # --- action --------------------------------------------------------------

    def click(self, ref: str | None = None, x: int | None = None, y: int | None = None,
              button: str = "left") -> Result:
        """click({ref}) drives the element via its UIA pattern (focus/occlusion
        independent); click({x,y}) is a coordinate click in the shared space."""
        if ref is not None:
            return self._act_on_ref(ref, lambda nid, node: self._press(nid, node, button))
        if x is not None and y is not None:
            return self.driver.click(int(x), int(y), button=button)
        return Result.fail(DRIVER_ERROR, "click needs a ref or (x, y)")

    def type(self, text: str, ref: str | None = None) -> Result:
        """type(text, ref) sets the value via ValuePattern (preferred); type(text)
        sends keystrokes to whatever holds focus."""
        if ref is not None:
            return self._act_on_ref(ref, lambda nid, _node: self.driver.set_value(nid, text))
        return self.driver.type(text)

    def key(self, combo: str) -> Result:
        return self.driver.key(combo)

    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Result:
        return self.driver.scroll(x, y, delta_x, delta_y)

    def drag(
        self, x: int, y: int, to_x: int, to_y: int, duration_ms: int = 250
    ) -> Result:
        return self.driver.drag(x, y, to_x, to_y, duration_ms)

    def activate(self, window_id: str) -> Result:
        return self.driver.activate_window(window_id)

    def describe_ref(self, ref: str) -> str | None:
        """Human/keyword-checkable description of a ref's target, e.g. for the
        dangerous-action gate. None if the ref is unknown."""
        node = self._by_ref.get(ref)
        return f'{node.role} "{node.name}"' if node else None

    def _press(self, native_id: str, node: Node, button: str) -> Result:
        if "invoke" in node.patterns:
            return self.driver.invoke(native_id)
        if "selectionitem" in node.patterns:
            return self.driver.select(native_id)
        return Result.fail(
            NOT_INVOKABLE,
            "ref exposes no supported accessibility action",
        )

    # --- ref table + lifecycle ----------------------------------------------

    def _ingest(
        self,
        tree: TreeResult,
        scope: str,
        header: str | None = None,
        footer: str | None = None,
    ) -> str:
        # The ref table ACCUMULATES across snapshots/finds, so a ref stays
        # resolvable even after a narrowing find() that doesn't list it again;
        # staleness is caught at action time and relocated. The returned text
        # reflects only the current view.
        lines: list[str] = []
        for node in tree.nodes:
            ref = self._ref_for(node.native_id, scope)
            self._by_ref[ref] = node
            self._native_by_ref[ref] = node.native_id
            lines.append(self._format(ref, node))
        out: list[str] = []
        if header:
            out.append(f"# {header}")
        out.extend(lines)
        if tree.truncated:
            out.append(f"# … {tree.truncated} more truncated — narrow with find()")
        if footer:
            out.append(f"# incomplete: {footer}")
        if not lines:
            out.append("# (no interactive elements in scope)")
        return "\n".join(out)

    def _ref_for(self, native_id: str, scope: str) -> str:
        if native_id and native_id in self._ref_by_native:
            return self._ref_by_native[native_id]
        self._counter += 1
        ref = f"ref_{self._counter}"
        self._scope_by_ref[ref] = scope
        if native_id:
            self._ref_by_native[native_id] = ref
        return ref

    @staticmethod
    def _format(ref: str, node: Node) -> str:
        b = node.bbox
        line = f'{ref} | {node.role.lower()} "{node.name}" | ({b.x},{b.y},{b.w},{b.h}) | {",".join(node.states)}'
        if node.value:
            line += f' | value="{node.value}"'
        return line

    def _act_on_ref(self, ref: str, action) -> Result:
        node = self._by_ref.get(ref)
        native_id = self._native_by_ref.get(ref)
        scope = self._scope_by_ref.get(ref)
        if node is None or not native_id or scope is None:
            return Result.fail(STALE_ELEMENT, f"{ref} not in current snapshot; call ui_snapshot first")
        res = action(native_id, node)
        if res.ok or res.code != STALE_ELEMENT:
            return res
        # Relocate once inside the scope that originally minted this ref.
        relocated = self._relocate(node, scope)
        if relocated is None:
            return Result.fail(STALE_ELEMENT, f"{ref} is stale and could not be relocated; re-snapshot")
        if not self._rebind(ref, relocated):
            return Result.fail(
                STALE_ELEMENT,
                f"{ref} is stale and relocation conflicts with another ref; re-snapshot",
            )
        return action(relocated.native_id, relocated)

    def _relocate(self, node: Node, scope: str) -> Node | None:
        tree = self.driver.get_tree(PruneOpts(scope=scope))
        cands = [n for n in tree.nodes if n.role == node.role and n.name == node.name and n.native_id]
        if not cands:
            return None
        best = min(cands, key=lambda n: abs(n.bbox.cx - node.bbox.cx) + abs(n.bbox.cy - node.bbox.cy))
        return best

    def _rebind(self, ref: str, node: Node) -> bool:
        native_id = node.native_id
        if not native_id:
            return False
        owner = self._ref_by_native.get(native_id)
        if owner is not None and owner != ref:
            return False
        old_native_id = self._native_by_ref.get(ref)
        if (
            old_native_id
            and old_native_id != native_id
            and self._ref_by_native.get(old_native_id) == ref
        ):
            del self._ref_by_native[old_native_id]
        self._by_ref[ref] = node
        self._native_by_ref[ref] = native_id
        self._ref_by_native[native_id] = ref
        return True
