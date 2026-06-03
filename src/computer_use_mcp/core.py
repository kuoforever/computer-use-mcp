"""Core layer — the model-facing session over a platform Driver.

This is the platform-agnostic half of the system. It owns the ref<->native_id
table and its lifecycle (Driver Contract section D): the model only ever sees
stable ``ref_N`` handles; the driver only ever sees ``native_id``. Refs stay
stable across snapshots where the native_id is unchanged, and an action on a
stale ref is relocated by (role, name) before giving up.

The MCP server (next milestone) is a thin wrapper that exposes these methods as
tools: ``ui_snapshot`` / ``screenshot`` / ``find`` / ``click`` / ``type`` / ``key``.
"""
from __future__ import annotations

from .contract import (
    DRIVER_ERROR,
    STALE_ELEMENT,
    Driver,
    Image,
    Node,
    PruneOpts,
    Result,
    TreeResult,
)


class Session:
    def __init__(self, driver: Driver) -> None:
        self.driver = driver
        self._by_ref: dict[str, Node] = {}         # ref -> Node from the last snapshot
        self._native_by_ref: dict[str, str] = {}   # ref -> native_id
        self._ref_by_native: dict[str, str] = {}   # native_id -> ref (for stability)
        self._scope: str = "foreground"
        self._counter = 0

    # --- perception ----------------------------------------------------------

    def ui_snapshot(self, scope: str = "foreground", max_nodes: int = 200) -> str:
        tree = self.driver.get_tree(PruneOpts(scope=scope, max_nodes=max_nodes))
        return self._ingest(tree, scope)

    def find(self, query: str, scope: str = "foreground", max_nodes: int = 200) -> str:
        tree = self.driver.find(PruneOpts(scope=scope, max_nodes=max_nodes), query)
        return self._ingest(tree, scope, header=f"find {query!r}")

    def screenshot(self) -> Image:
        return self.driver.capture_screen()

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

    def activate(self, window_id: str) -> Result:
        return self.driver.activate_window(window_id)

    def _press(self, native_id: str, node: Node, button: str) -> Result:
        if "invoke" in node.patterns:
            return self.driver.invoke(native_id)
        if "selectionitem" in node.patterns:
            return self.driver.select(native_id)
        # no actionable pattern -> fall back to a coordinate click at the center
        return self.driver.click(node.bbox.cx, node.bbox.cy, button=button)

    # --- ref table + lifecycle ----------------------------------------------

    def _ingest(self, tree: TreeResult, scope: str, header: str | None = None) -> str:
        # The ref table ACCUMULATES across snapshots/finds, so a ref stays
        # resolvable even after a narrowing find() that doesn't list it again;
        # staleness is caught at action time and relocated. The returned text
        # reflects only the current view.
        self._scope = scope
        lines: list[str] = []
        for node in tree.nodes:
            ref = self._ref_for(node.native_id)
            self._by_ref[ref] = node
            self._native_by_ref[ref] = node.native_id
            lines.append(self._format(ref, node))
        out: list[str] = []
        if header:
            out.append(f"# {header}")
        out.extend(lines)
        if tree.truncated:
            out.append(f"# … {tree.truncated} more truncated — narrow with find()")
        if not lines:
            out.append("# (no interactive elements in scope)")
        return "\n".join(out)

    def _ref_for(self, native_id: str) -> str:
        if native_id and native_id in self._ref_by_native:
            return self._ref_by_native[native_id]
        self._counter += 1
        ref = f"ref_{self._counter}"
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
        if node is None or not native_id:
            return Result.fail(STALE_ELEMENT, f"{ref} not in current snapshot; call ui_snapshot first")
        res = action(native_id, node)
        if res.ok or res.code != STALE_ELEMENT:
            return res
        # relocate by (role, name) and retry once (Driver Contract section D)
        relocated = self._relocate(node)
        if not relocated:
            return Result.fail(STALE_ELEMENT, f"{ref} is stale and could not be relocated; re-snapshot")
        self._native_by_ref[ref] = relocated
        return action(relocated, node)

    def _relocate(self, node: Node) -> str | None:
        tree = self.driver.get_tree(PruneOpts(scope=self._scope))
        cands = [n for n in tree.nodes if n.role == node.role and n.name == node.name and n.native_id]
        if not cands:
            return None
        best = min(cands, key=lambda n: abs(n.bbox.cx - node.bbox.cx) + abs(n.bbox.cy - node.bbox.cy))
        return best.native_id
