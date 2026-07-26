"""Driver Contract v1, ported to Python.

The single boundary between the universal core and a platform-native driver.
Keep this module platform-free: stdlib only, no mss/uiautomation/ctypes. See
docs/DRIVER_CONTRACT.md — the prose there is the source of truth; this file is
its typed Python projection.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Literal

CONTRACT_VERSION = "1.0.0"

# --- error codes ------------------------------------------------------------

STALE_ELEMENT = "STALE_ELEMENT"      # native_id no longer resolves
NOT_INVOKABLE = "NOT_INVOKABLE"      # element does not support the action
OUT_OF_BOUNDS = "OUT_OF_BOUNDS"      # coordinate outside the shared grid
PERMISSION_DENIED = "PERMISSION_DENIED"  # gate / allowlist rejected
DRIVER_ERROR = "DRIVER_ERROR"        # anything else from the platform layer


class DriverError(Exception):
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code
        self.message = message


# --- shared pixel-space geometry --------------------------------------------


@dataclass(frozen=True)
class Rect:
    """A rectangle in the shared pixel grid of the most recent capture."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> int:
        return self.x + self.w // 2

    @property
    def cy(self) -> int:
        return self.y + self.h // 2

    def intersects(self, other: "Rect") -> bool:
        return not (
            other.x >= self.right
            or other.right <= self.x
            or other.y >= self.bottom
            or other.bottom <= self.y
        )

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass
class Display:
    id: str
    bounds: Rect
    scale: float
    primary: bool


@dataclass
class Image:
    png: bytes
    width: int          # pixel grid that every bbox shares
    height: int
    scale: float        # primary-display DPI scale (1.0 / 1.5 / 2.0 ...)
    displays: list[Display] = field(default_factory=list)


@dataclass
class ProcRef:
    pid: int
    name: str


@dataclass
class Window:
    id: str
    title: str
    bounds: Rect
    owner: ProcRef                 # process that owns the foreground window
    owner_chain: list[ProcRef]     # self -> ... -> root ancestor (gate uses this)
    is_foreground: bool


@dataclass
class Node:
    native_id: str                 # driver-resolvable handle (Win RuntimeId, ...)
    role: str                      # normalized control type (Button/Edit/...)
    name: str                      # <= PruneOpts.name_max_len
    value: str | None              # None when redacted (password) or N/A
    bbox: Rect
    states: list[str]              # enabled/disabled, focused, selected, ...
    patterns: list[str]            # supported actions: invoke, value, ...


# Default interactive control-type whitelist (normalized, no "Control" suffix).
# "Document" is the editable text surface (e.g. the Notepad editor) — it carries
# a writable ValuePattern, so an agent acts on it; it is a single node, not a
# subtree, so it does not bloat the snapshot.
DEFAULT_CONTROL_TYPES: tuple[str, ...] = (
    "Button", "Edit", "Document", "CheckBox", "RadioButton", "ComboBox",
    "List", "ListItem", "MenuItem", "Hyperlink",
    "Tab", "TabItem", "Tree", "TreeItem", "Slider",
)


@dataclass
class PruneOpts:
    scope: str = "foreground"                       # "foreground" | window_id | "all"
    control_types: tuple[str, ...] | Literal["default"] = "default"
    include_offscreen: bool = False
    max_nodes: int = 200
    name_max_len: int = 100
    redact_password: bool = True

    def resolved_types(self) -> tuple[str, ...]:
        if self.control_types == "default":
            return DEFAULT_CONTROL_TYPES
        return tuple(self.control_types)


@dataclass
class TreeResult:
    nodes: list[Node]
    truncated: int   # how many qualifying nodes were dropped by max_nodes


@dataclass
class DocumentTextBlock:
    text: str                      # semantic text of one document region
    bbox: Rect | None              # bounding box when the channel exposes one
    order: int                     # stable local reading order within the scope


@dataclass
class DocumentTextResult:
    blocks: list[DocumentTextBlock]
    truncated_blocks: int          # qualifying blocks dropped by a driver-side cap
    source: str                    # semantic channel, e.g. "uia_text_pattern"
    complete: bool                 # driver's honest completeness signal for the scope


@dataclass
class Result:
    ok: bool
    code: str | None = None
    message: str = ""

    @classmethod
    def success(cls) -> "Result":
        return cls(ok=True)

    @classmethod
    def fail(cls, code: str, message: str = "") -> "Result":
        return cls(ok=False, code=code, message=message)


# --- the contract ------------------------------------------------------------


class Driver(abc.ABC):
    """Every platform implements exactly these primitives. The core (MCP tools,
    snapshot serialization, ref table, security layer, agent loop) is written
    once against this interface and never imports a platform module."""

    @abc.abstractmethod
    def capabilities(self) -> dict: ...

    @abc.abstractmethod
    def capture_screen(self, region: Rect | None = None) -> Image: ...

    @abc.abstractmethod
    def list_windows(self) -> list[Window]: ...

    @abc.abstractmethod
    def foreground_owner_chain(self) -> list[ProcRef]: ...

    @abc.abstractmethod
    def get_tree(self, opts: PruneOpts) -> TreeResult: ...

    @abc.abstractmethod
    def find(self, opts: PruneOpts, query: str) -> TreeResult: ...

    def get_document_text(self, opts: PruneOpts) -> DocumentTextResult:
        """Read bounded semantic document text for ``opts.scope``.

        The default rejects the request: a backend without a real document-text
        channel must fail closed rather than let the tool fall back to dumping
        the accessibility tree or hidden application state as document text.
        """
        raise DriverError(DRIVER_ERROR, "document text is not supported by this backend")

    # --- actions (implemented from v0.1 onward) ---

    @abc.abstractmethod
    def invoke(self, native_id: str) -> Result: ...

    @abc.abstractmethod
    def set_value(self, native_id: str, text: str) -> Result: ...

    @abc.abstractmethod
    def select(self, native_id: str) -> Result: ...

    @abc.abstractmethod
    def click(self, x: int, y: int, button: str = "left", modifiers: list[str] | None = None) -> Result: ...

    @abc.abstractmethod
    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Result: ...

    @abc.abstractmethod
    def drag(self, x: int, y: int, to_x: int, to_y: int, duration_ms: int = 250) -> Result: ...

    @abc.abstractmethod
    def key(self, combo: str) -> Result: ...

    @abc.abstractmethod
    def type(self, text: str) -> Result: ...

    @abc.abstractmethod
    def activate_window(self, window_id: str) -> Result: ...
