"""Strict optional GUI metadata, separate from the unchanged Driver v1 contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


class GuiMetadataError(RuntimeError):
    """Fixed diagnostic code; never includes window or UI text."""


@dataclass(frozen=True)
class VerifiedControl:
    native_id: str
    role: str
    name: str
    bounds: tuple[int, int, int, int]
    enabled: bool
    visible: bool
    focused: bool

    def __post_init__(self) -> None:
        if (
            type(self.native_id) is not str
            or not 0 < len(self.native_id) <= 256
            or type(self.role) is not str
            or self.role not in {"button", "edit", "document"}
        ):
            raise GuiMetadataError("GUI_CONTROL_INVALID")
        if (
            type(self.name) is not str
            or not self.name.strip()
            or len(self.name) >= 100
            or any(ord(c) < 32 or c in '"|' for c in self.name)
        ):
            raise GuiMetadataError("GUI_NAME_INVALID")
        if (
            type(self.bounds) is not tuple
            or len(self.bounds) != 4
            or any(type(v) is not int for v in self.bounds)
            or not (
                0 <= self.bounds[0] < self.bounds[2] <= 16384
                and 0 <= self.bounds[1] < self.bounds[3] <= 16384
            )
        ):
            raise GuiMetadataError("GUI_BOUNDS_INVALID")
        if any(type(v) is not bool for v in (self.enabled, self.visible, self.focused)):
            raise GuiMetadataError("GUI_STATE_INVALID")


@dataclass(frozen=True)
class VerifiedGuiState:
    scope: str
    foreground_scope: str
    window_bounds: tuple[int, int, int, int]
    frame_bounds: tuple[int, int, int, int]
    controls: tuple[VerifiedControl, ...]

    def __post_init__(self) -> None:
        if (
            type(self.scope) is not str
            or not 0 < len(self.scope) <= 20
            or not self.scope.isascii()
            or not self.scope.isdecimal()
            or int(self.scope) <= 0
            or self.scope != self.foreground_scope
        ):
            raise GuiMetadataError("GUI_WINDOW_NOT_FOREGROUND")
        for box in (self.window_bounds, self.frame_bounds):
            if (
                type(box) is not tuple
                or len(box) != 4
                or any(type(v) is not int for v in box)
                or not (0 <= box[0] < box[2] <= 16384 and 0 <= box[1] < box[3] <= 16384)
            ):
                raise GuiMetadataError("GUI_BOUNDS_INVALID")
        if (
            self.frame_bounds[:2] != (0, 0)
            or self.window_bounds[2] > self.frame_bounds[2]
            or self.window_bounds[3] > self.frame_bounds[3]
        ):
            raise GuiMetadataError("GUI_FRAME_UNSUPPORTED")
        if (
            type(self.controls) is not tuple
            or len(self.controls) > 64
            or any(not isinstance(c, VerifiedControl) for c in self.controls)
        ):
            raise GuiMetadataError("GUI_CONTROL_INVALID")
        if len({c.native_id for c in self.controls}) != len(self.controls):
            raise GuiMetadataError("GUI_NATIVE_ID_DUPLICATE")
        for control in self.controls:
            b = control.bounds
            w = self.window_bounds
            if not (w[0] <= b[0] < b[2] <= w[2] and w[1] <= b[1] < b[3] <= w[3]):
                raise GuiMetadataError("GUI_BOUNDS_INVALID")


class UiaRect(Protocol):
    left: int
    top: int
    right: int
    bottom: int


class UiaControl(Protocol):
    ControlTypeName: str
    Name: str
    BoundingRectangle: UiaRect
    IsEnabled: bool
    IsOffscreen: bool
    HasKeyboardFocus: bool

    def GetChildren(self) -> Sequence[UiaControl]: ...
    def GetRuntimeId(self) -> Sequence[int]: ...


def strict_tree(root: UiaControl, window: tuple[int, int, int, int]) -> tuple[VerifiedControl, ...]:
    """No property fallback, deduplication, truncation, partial result or retry."""
    try:
        stack = [(child, 1) for child in reversed(root.GetChildren())]
        result = []
        seen: set[str] = set()
        visited = 0
        while stack:
            control, depth = stack.pop()
            visited += 1
            if visited > 512:
                raise GuiMetadataError("GUI_TREE_LIMIT")
            children = control.GetChildren()
            if children and depth >= 12:
                raise GuiMetadataError("GUI_TREE_LIMIT")
            stack.extend((child, depth + 1) for child in reversed(children))
            raw_role = control.ControlTypeName
            if type(raw_role) is not str or not raw_role.endswith("Control"):
                raise GuiMetadataError("GUI_ROLE_INVALID")
            role = raw_role[:-7].lower()
            if role in {"pane", "group", "window", "text", "custom"}:
                continue  # Structural/non-actionable nodes are still traversed.
            if role not in {"button", "edit", "document"}:
                raise GuiMetadataError("GUI_ROLE_UNSUPPORTED")
            name = control.Name
            enabled, offscreen, focused = (
                control.IsEnabled,
                control.IsOffscreen,
                control.HasKeyboardFocus,
            )
            if any(type(v) is not bool for v in (enabled, offscreen, focused)):
                raise GuiMetadataError("GUI_STATE_INVALID")
            if (
                type(name) is not str
                or not name.strip()
                or len(name) >= 100
                or any(c in name for c in '\r\n"|')
            ):
                raise GuiMetadataError("GUI_NAME_INVALID")
            box = control.BoundingRectangle
            bounds = (box.left, box.top, box.right, box.bottom)
            if any(type(v) is not int for v in bounds) or not (
                window[0] <= bounds[0] < bounds[2] <= window[2]
                and window[1] <= bounds[1] < bounds[3] <= window[3]
            ):
                raise GuiMetadataError("GUI_BOUNDS_INVALID")
            runtime_id = control.GetRuntimeId()
            if (
                not runtime_id
                or len(runtime_id) > 32
                or any(type(v) is not int or not -(2**31) <= v < 2**31 for v in runtime_id)
            ):
                raise GuiMetadataError("GUI_NATIVE_ID_INVALID")
            native_id = "-".join(str(v) for v in runtime_id)
            if native_id in seen:
                raise GuiMetadataError("GUI_NATIVE_ID_DUPLICATE")
            seen.add(native_id)
            result.append(
                VerifiedControl(native_id, role, name, bounds, enabled, not offscreen, focused)
            )
            if len(result) > 64:
                raise GuiMetadataError("GUI_TREE_LIMIT")
        return tuple(result)
    except GuiMetadataError:
        raise
    except Exception:
        raise GuiMetadataError("GUI_PROPERTY_READ_FAILED") from None
