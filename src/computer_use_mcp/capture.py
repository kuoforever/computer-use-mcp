"""Bounded cropped image observation for one explicit primary-display region.

This is the rung between OCR and a full screenshot in the observation ladder:
the caller pays for the pixels it names instead of the whole display. Image
bytes travel as native image content; the accompanying envelope carries only
the grounding facts a caller needs to place the crop back on the display.
"""
from __future__ import annotations

import hashlib
import json

from .contract import Image, Rect
from .region import RegionError
from .region import validate_region as validate_bounded_region

MAX_CAPTURE_PIXELS = 4_000_000
MAX_CAPTURE_PNG_BYTES = 4 * 1024 * 1024


class CaptureError(RuntimeError):
    """A stable capture failure safe to return through the tool boundary."""


def validate_region(x: int, y: int, w: int, h: int) -> Rect:
    try:
        return validate_bounded_region(
            x,
            y,
            w,
            h,
            max_pixels=MAX_CAPTURE_PIXELS,
            code_prefix="CAPTURE",
        )
    except RegionError as exc:
        raise CaptureError(str(exc)) from exc


def serialize_capture(image: Image, region: Rect, png: bytes) -> str:
    """Return the observation envelope for one already-redacted crop.

    The PNG is passed separately because redaction rewrites the bytes after the
    driver returns them, and the digest must describe what the caller receives.
    """

    if (image.width, image.height) != (region.w, region.h):
        raise CaptureError("CAPTURE_MISMATCH: driver did not return the requested region")
    if len(png) > MAX_CAPTURE_PNG_BYTES:
        raise CaptureError(
            f"CAPTURE_IMAGE_TOO_LARGE: maximum is {MAX_CAPTURE_PNG_BYTES} encoded bytes"
        )
    payload = {
        "source": "image",
        "scope": {"display": "primary", "region": list(region.as_tuple())},
        "coordinate_space": "primary_display_physical_pixels",
        "crop_origin": [region.x, region.y],
        "width": image.width,
        "height": image.height,
        "scale": image.scale,
        "encoded_bytes": len(png),
        "image_digest": hashlib.sha256(png).hexdigest(),
        "complete": True,
        "truncated": False,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
