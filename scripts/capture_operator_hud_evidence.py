"""Retain an exact-window screenshot of an isolated operator HUD review.

The capture surface and output names are deliberately fixed. This helper cannot
be pointed at an arbitrary user window or arbitrary output path, and it does
not launch, focus, resize, click, type into, or close any window.
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_mcp.dpi import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from PIL import ImageGrab  # noqa: E402

EVIDENCE_ROOT = ROOT / "docs" / "evidence" / "operator-hud"

Surface = Literal[
    "decision-card-compact",
    "decision-card-expanded",
    "progress-compact",
    "progress-expanded",
]


@dataclass(frozen=True)
class CaptureTarget:
    title: str
    filename: str


TARGETS: dict[Surface, CaptureTarget] = {
    "decision-card-compact": CaptureTarget(
        "Decision required · action blocked",
        "decision-card-compact.png",
    ),
    "decision-card-expanded": CaptureTarget(
        "Decision required · action blocked",
        "decision-card-expanded.png",
    ),
    "progress-compact": CaptureTarget(
        "Progress HUD visual review",
        "progress-hud-compact.png",
    ),
    "progress-expanded": CaptureTarget(
        "Progress HUD visual review",
        "progress-hud-expanded.png",
    ),
}


def _matching_visible_windows(title: str) -> tuple[int, ...]:
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int
    matches: list[int] = []

    @callback_type
    def collect(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        if buffer.value == title:
            matches.append(int(hwnd))
        return True

    if not user32.EnumWindows(collect, 0):
        raise RuntimeError("OPERATOR_HUD_CAPTURE_ENUM_WINDOWS_FAILED")
    return tuple(matches)


def _window_rectangle(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        raise RuntimeError("OPERATOR_HUD_CAPTURE_GET_WINDOW_RECT_FAILED")
    bounds = (
        int(rectangle.left),
        int(rectangle.top),
        int(rectangle.right),
        int(rectangle.bottom),
    )
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    if not 200 <= width <= 2000 or not 150 <= height <= 1400:
        raise RuntimeError("OPERATOR_HUD_CAPTURE_UNEXPECTED_WINDOW_BOUNDS")
    return bounds


def _output_path(surface: Surface, *, capture_date: date) -> Path:
    return EVIDENCE_ROOT / capture_date.isoformat() / TARGETS[surface].filename


def _matches_surface_geometry(
    surface: Surface,
    bounds: tuple[int, int, int, int],
) -> bool:
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    compact_geometry = width / height > 1.45
    return compact_geometry == surface.endswith("-compact")


def capture(
    surface: Surface,
    *,
    overwrite: bool = False,
    wait_seconds: float = 0,
    settle_seconds: float = 1,
) -> Path:
    target = TARGETS[surface]
    output = _output_path(surface, capture_date=date.today())
    if output.exists() and not overwrite:
        raise FileExistsError(f"OPERATOR_HUD_CAPTURE_ALREADY_EXISTS:{output}")
    deadline = time.monotonic() + wait_seconds + settle_seconds
    observed_count = 0
    bounds: tuple[int, int, int, int] | None = None
    stable_signature: tuple[int, tuple[int, int, int, int]] | None = None
    stable_since: float | None = None
    while True:
        now = time.monotonic()
        matches = _matching_visible_windows(target.title)
        observed_count = len(matches)
        if len(matches) == 1:
            candidate_bounds = _window_rectangle(matches[0])
            if _matches_surface_geometry(surface, candidate_bounds):
                signature = (matches[0], candidate_bounds)
                if signature != stable_signature:
                    stable_signature = signature
                    stable_since = now
                if stable_since is not None and now - stable_since >= settle_seconds:
                    bounds = candidate_bounds
                    break
            else:
                stable_signature = None
                stable_since = None
        else:
            stable_signature = None
            stable_since = None
        if now >= deadline:
            raise RuntimeError(
                "OPERATOR_HUD_CAPTURE_EXPECTED_ONE_EXACT_WINDOW_AND_STATE:"
                f"{target.title!r}:observed={observed_count}:surface={surface}"
            )
        time.sleep(0.05)
    assert bounds is not None
    output.parent.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(bbox=bounds, all_screens=True)
    image.save(output, format="PNG")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Capture one exact isolated operator-HUD review window into the "
            "fixed dated repository evidence directory."
        )
    )
    parser.add_argument(
        "surface",
        choices=tuple(TARGETS),
        nargs="+",
        help=(
            "One or more fixed slots. Multiple slots are captured in order, "
            "waiting for each exact window state."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace only the fixed evidence slot for this surface.",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=0,
        help="Wait up to this many seconds for each exact state (0-600).",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1,
        help="Require unchanged exact geometry for this long before capture (0-10).",
    )
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 600:
        parser.error("--wait-seconds must be between 0 and 600")
    if not 0 <= args.settle_seconds <= 10:
        parser.error("--settle-seconds must be between 0 and 10")
    for surface in args.surface:
        output = capture(
            surface,
            overwrite=args.overwrite,
            wait_seconds=args.wait_seconds,
            settle_seconds=args.settle_seconds,
        )
        print(output.relative_to(ROOT), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
