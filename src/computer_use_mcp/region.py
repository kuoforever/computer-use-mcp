"""Shared primary-display region validation for bounded observation sources.

OCR and image capture accept the same explicit rectangle and must reject the
same inputs, so the rule lives here once. Each caller keeps its own error type
and code prefix, because the two tools report through different contracts.
"""
from __future__ import annotations

from collections.abc import Sequence

from .contract import Rect, Window


class RegionError(ValueError):
    """An invalid observation region, carrying the caller's stable code."""


def validate_region(
    x: int,
    y: int,
    w: int,
    h: int,
    *,
    max_pixels: int,
    code_prefix: str,
) -> Rect:
    values = {"x": x, "y": y, "w": w, "h": h}
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values.values()):
        raise RegionError(f"{code_prefix}_INVALID_REGION: x, y, w, and h must be integers")
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise RegionError(
            f"{code_prefix}_INVALID_REGION: region must be positive and within the primary display"
        )
    if w * h > max_pixels:
        raise RegionError(f"{code_prefix}_REGION_TOO_LARGE: maximum is {max_pixels} pixels")
    return Rect(x, y, w, h)


def redaction_boxes(
    windows: Sequence[Window],
    region: Rect,
    titles: Sequence[str],
) -> list[tuple[int, int, int, int]]:
    """Return crop-local blackout boxes for title-matched windows in ``region``."""

    boxes: list[tuple[int, int, int, int]] = []
    for window in windows:
        if not window.title or not any(
            title.lower() in window.title.lower() for title in titles
        ):
            continue
        x = max(region.x, window.bounds.x)
        y = max(region.y, window.bounds.y)
        right = min(region.right, window.bounds.right)
        bottom = min(region.bottom, window.bounds.bottom)
        if x < right and y < bottom:
            boxes.append((x - region.x, y - region.y, right - x, bottom - y))
    return boxes
