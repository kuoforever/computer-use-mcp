"""Passive click-through controller for the desktop presence halo."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .operator_display import OperatorDisplayError, OperatorMonitor
from .operator_localization import OperatorLocale, operator_text
from .presence import PresenceSnapshot, PresenceView, project_presence

WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

PRESENCE_STYLE = WS_POPUP
PRESENCE_EX_STYLE = (
    WS_EX_TOPMOST
    | WS_EX_TRANSPARENT
    | WS_EX_TOOLWINDOW
    | WS_EX_LAYERED
    | WS_EX_NOACTIVATE
)


class PresenceWindowError(RuntimeError):
    """A fixed presence-surface failure with no desktop or Host content."""


@dataclass(frozen=True)
class PresenceGeometry:
    x: int
    y: int
    width: int
    height: int
    border_px: int
    label_inset_px: int
    dpi: int


def presence_geometry(monitor: OperatorMonitor) -> PresenceGeometry:
    """Scale one selected-monitor halo from a single validated snapshot."""

    if not isinstance(monitor, OperatorMonitor):
        raise PresenceWindowError("PRESENCE_DISPLAY_BOUNDS_INVALID")
    left, top, right, bottom = monitor.bounds
    border = max(8, min(32, round(10 * monitor.dpi / 96)))
    inset = max(12, min(48, round(16 * monitor.dpi / 96)))
    return PresenceGeometry(
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
        border_px=border,
        label_inset_px=inset,
        dpi=monitor.dpi,
    )


@runtime_checkable
class PresenceWindowApi(Protocol):
    """Native operations allowed to the halo; focus and input APIs are absent."""

    def display_monitor(self) -> OperatorMonitor: ...

    def create(self, *, ex_style: int, style: int, title: str) -> int: ...

    def configure(
        self, hwnd: int, view: PresenceView, geometry: PresenceGeometry
    ) -> None: ...

    def exclude_from_capture(self, hwnd: int) -> bool: ...

    def show_noactivate(self, hwnd: int) -> None: ...

    def foreground(self) -> int: ...

    def destroy(self, hwnd: int) -> None: ...


@dataclass(frozen=True)
class PresenceUpdate:
    visible: bool
    changed: bool
    created: bool
    capture_excluded: bool


def presence_accessible_name(
    view: PresenceView,
    *,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> str:
    """Return the fixed click-through halo alternative exposed to UIA clients."""

    if not isinstance(view, PresenceView):
        raise PresenceWindowError("PRESENCE_ACCESSIBLE_VIEW_INVALID")
    if not isinstance(locale, OperatorLocale):
        raise PresenceWindowError("PRESENCE_ACCESSIBLE_LOCALE_INVALID")
    product = operator_text(locale, "product_name")
    if locale is OperatorLocale.EN_US:
        return f"{product}. {view.glyph.capitalize()}. {view.label}."
    return f"{product}。{view.glyph}。{view.label}。"


@dataclass
class PassivePresenceWindow:
    """Synchronize one non-authoritative Host snapshot to a passive halo."""

    api: PresenceWindowApi
    title: str = "Computer Use active"
    _hwnd: int | None = field(default=None, init=False)
    _last: tuple[PresenceView, PresenceGeometry] | None = field(default=None, init=False)
    _capture_excluded: bool = field(default=False, init=False)

    @property
    def hwnd(self) -> int | None:
        """Trusted identity for observation masking; never an action target."""

        return self._hwnd

    def sync(self, snapshot: PresenceSnapshot) -> PresenceUpdate:
        """Apply one snapshot; teardown is immediate when projection is absent."""

        view = project_presence(snapshot)
        if view is None:
            changed = self._hwnd is not None
            self.close()
            return PresenceUpdate(False, changed, False, False)

        geometry = presence_geometry(self.api.display_monitor())
        state = (view, geometry)
        created = False
        if self._hwnd is None:
            hwnd = self.api.create(
                ex_style=PRESENCE_EX_STYLE,
                style=PRESENCE_STYLE,
                title=self.title,
            )
            self._hwnd = hwnd
            self._capture_excluded = self.api.exclude_from_capture(hwnd)
            created = True

        if self._hwnd is None:  # Defensive: create either returned or raised.
            raise PresenceWindowError("PRESENCE_WINDOW_CREATE_FAILED")
        changed = created or state != self._last
        if changed:
            self.api.configure(self._hwnd, view, geometry)
            self._last = state
        if created:
            self.api.show_noactivate(self._hwnd)
        return PresenceUpdate(True, changed, created, self._capture_excluded)

    def close(self) -> None:
        if self._hwnd is None:
            return
        self.api.destroy(self._hwnd)
        self._hwnd = None
        self._last = None
        self._capture_excluded = False


__all__ = [
    "PRESENCE_EX_STYLE",
    "PRESENCE_STYLE",
    "PassivePresenceWindow",
    "PresenceGeometry",
    "PresenceUpdate",
    "PresenceWindowApi",
    "PresenceWindowError",
    "OperatorDisplayError",
    "OperatorMonitor",
    "presence_geometry",
    "presence_accessible_name",
]
