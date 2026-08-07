"""Pure monitor-selection contract for native operator surfaces.

The Host selects the monitor that owns the current foreground window.  This
module contains only the validated, presentation-only result; it carries no
desktop coordinates for Runner actions and exposes no capture or dispatch API.
"""
from __future__ import annotations

from dataclasses import dataclass


class OperatorDisplayError(RuntimeError):
    """A fixed monitor-selection failure with no desktop or Host content."""


DisplayRect = tuple[int, int, int, int]


def _valid_rect(value: object) -> bool:
    if not isinstance(value, tuple) or len(value) != 4:
        return False
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        return False
    left, top, right, bottom = value
    return right > left and bottom > top


@dataclass(frozen=True)
class OperatorMonitor:
    """One immutable monitor layout selected by the Host.

    ``bounds`` is the complete monitor rectangle used by the click-through
    Presence halo. ``work_area`` excludes taskbars and app bars and is used by
    the corner-anchored Progress and Decision Card surfaces. Negative origins
    are valid in the Windows virtual-screen coordinate space.
    """

    bounds: DisplayRect
    work_area: DisplayRect
    dpi: int

    def __post_init__(self) -> None:
        if (
            not _valid_rect(self.bounds)
            or not _valid_rect(self.work_area)
            or isinstance(self.dpi, bool)
            or not isinstance(self.dpi, int)
            or not 48 <= self.dpi <= 768
        ):
            raise OperatorDisplayError("OPERATOR_MONITOR_INVALID")
        left, top, right, bottom = self.bounds
        work_left, work_top, work_right, work_bottom = self.work_area
        if (
            work_left < left
            or work_top < top
            or work_right > right
            or work_bottom > bottom
        ):
            raise OperatorDisplayError("OPERATOR_MONITOR_INVALID")


__all__ = [
    "DisplayRect",
    "OperatorDisplayError",
    "OperatorMonitor",
]
