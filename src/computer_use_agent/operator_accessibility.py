"""Fail-silent accessibility settings shared by native operator surfaces.

The module resolves presentation preferences only.  It owns no HWND, input,
approval, control, or desktop-dispatch capability.  Windows may provide a text
scale and animation preference through ``UISettings`` plus a High Contrast
preference through ``SystemParametersInfoW``; unavailable APIs fall back to the
static, motion-enabled 100% presentation without affecting Runner authority.
"""

from __future__ import annotations

import ctypes
import math
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

from .operator_visuals import OPERATOR_SURFACE
from .win32_dll import private_windll


_BASE_DPI = 96
_MAX_TEXT_DPI = 384
_MAX_LAYOUT_DPI = 192

_SPI_GETHIGHCONTRAST = 0x0042
_HCF_HIGHCONTRASTON = 0x00000001

_COLOR_WINDOW = 5
_COLOR_WINDOWTEXT = 8
_COLOR_HIGHLIGHT = 13
_COLOR_HIGHLIGHTTEXT = 14
_COLOR_BTNFACE = 15
_COLOR_BTNTEXT = 18


class _SystemColorApi(Protocol):
    def GetSysColor(self, index: int) -> int: ...


class _HIGHCONTRASTW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwFlags", wintypes.DWORD),
        ("lpszDefaultScheme", wintypes.LPWSTR),
    ]


@dataclass(frozen=True)
class OperatorAccessibilitySettings:
    """Resolved presentation preferences, never an authority or action token."""

    high_contrast: bool = False
    reduced_motion: bool = False
    text_scale_factor: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.high_contrast, bool) or not isinstance(
            self.reduced_motion, bool
        ):
            raise ValueError("OPERATOR_ACCESSIBILITY_BOOLEAN_INVALID")
        factor = self.text_scale_factor
        if (
            isinstance(factor, bool)
            or not isinstance(factor, (int, float))
            or not math.isfinite(float(factor))
            or not 1.0 <= float(factor) <= 4.0
        ):
            raise ValueError("OPERATOR_TEXT_SCALE_INVALID")


@dataclass(frozen=True)
class Win32Palette:
    """One complete ``COLORREF`` palette for GDI operator surfaces."""

    background: int
    surface: int
    text: int
    muted_text: int
    hairline: int
    accent: int
    accent_text: int


def _colorref(rgb: int) -> int:
    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return red | (green << 8) | (blue << 16)


def _system_accessibility() -> OperatorAccessibilitySettings:
    """Read public Windows accessibility APIs and fail by raising to the caller."""

    user32 = private_windll("user32")
    user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    user32.SystemParametersInfoW.restype = wintypes.BOOL
    high_contrast = _HIGHCONTRASTW()
    high_contrast.cbSize = ctypes.sizeof(high_contrast)
    if not user32.SystemParametersInfoW(
        _SPI_GETHIGHCONTRAST,
        high_contrast.cbSize,
        ctypes.byref(high_contrast),
        0,
    ):
        raise OSError("OPERATOR_HIGH_CONTRAST_UNAVAILABLE")

    from winrt.windows.ui.viewmanagement import UISettings

    ui_settings = UISettings()
    factor = float(ui_settings.text_scale_factor)
    # The documented system range is 1.0 through 2.25.  Keep a strict fallback
    # if an older or future binding returns an unexpected value.
    if not math.isfinite(factor) or not 1.0 <= factor <= 2.25:
        raise OSError("OPERATOR_TEXT_SCALE_UNAVAILABLE")
    return OperatorAccessibilitySettings(
        high_contrast=bool(high_contrast.dwFlags & _HCF_HIGHCONTRASTON),
        reduced_motion=not bool(ui_settings.animations_enabled),
        text_scale_factor=factor,
    )


def resolve_operator_accessibility(
    *,
    force_high_contrast: bool,
    force_reduced_motion: bool,
    system_loader: Callable[[], OperatorAccessibilitySettings] | None = None,
) -> OperatorAccessibilitySettings:
    """Compose explicit product preferences with fail-silent system settings."""

    if not isinstance(force_high_contrast, bool) or not isinstance(
        force_reduced_motion, bool
    ):
        raise ValueError("OPERATOR_ACCESSIBILITY_BOOLEAN_INVALID")
    loader = _system_accessibility if system_loader is None else system_loader
    try:
        system = loader()
        if not isinstance(system, OperatorAccessibilitySettings):
            raise TypeError("OPERATOR_ACCESSIBILITY_SYSTEM_INVALID")
    except Exception:
        system = OperatorAccessibilitySettings()
    return OperatorAccessibilitySettings(
        high_contrast=force_high_contrast or system.high_contrast,
        reduced_motion=force_reduced_motion or system.reduced_motion,
        text_scale_factor=system.text_scale_factor,
    )


def effective_text_dpi(dpi: int, text_scale_factor: float) -> int:
    """Combine display DPI and text scale, bounded to a 400% presentation."""

    settings = OperatorAccessibilitySettings(text_scale_factor=text_scale_factor)
    observed = dpi if isinstance(dpi, int) and not isinstance(dpi, bool) else _BASE_DPI
    if not _BASE_DPI <= observed <= 768:
        observed = _BASE_DPI
    return min(
        _MAX_TEXT_DPI,
        max(_BASE_DPI, round(observed * settings.text_scale_factor)),
    )


def layout_dpi(dpi: int, text_scale_factor: float) -> int:
    """Grow containers to 200%, then reflow larger text inside bounded windows."""

    return min(_MAX_LAYOUT_DPI, effective_text_dpi(dpi, text_scale_factor))


def win32_palette(
    user32: _SystemColorApi,
    *,
    high_contrast: bool,
    accent_rgb: int,
) -> Win32Palette:
    """Resolve shared product colors or the operator's selected system colors."""

    if not isinstance(high_contrast, bool):
        raise ValueError("OPERATOR_HIGH_CONTRAST_INVALID")
    if (
        isinstance(accent_rgb, bool)
        or not isinstance(accent_rgb, int)
        or not 0 <= accent_rgb <= 0xFFFFFF
    ):
        raise ValueError("OPERATOR_ACCENT_INVALID")
    if high_contrast:
        return Win32Palette(
            background=int(user32.GetSysColor(_COLOR_WINDOW)),
            surface=int(user32.GetSysColor(_COLOR_BTNFACE)),
            text=int(user32.GetSysColor(_COLOR_WINDOWTEXT)),
            muted_text=int(user32.GetSysColor(_COLOR_BTNTEXT)),
            hairline=int(user32.GetSysColor(_COLOR_HIGHLIGHT)),
            accent=int(user32.GetSysColor(_COLOR_HIGHLIGHT)),
            accent_text=int(user32.GetSysColor(_COLOR_HIGHLIGHTTEXT)),
        )
    return Win32Palette(
        background=_colorref(OPERATOR_SURFACE.background_rgb),
        surface=_colorref(OPERATOR_SURFACE.surface_rgb),
        text=_colorref(OPERATOR_SURFACE.text_rgb),
        muted_text=_colorref(OPERATOR_SURFACE.muted_text_rgb),
        hairline=_colorref(OPERATOR_SURFACE.hairline_rgb),
        accent=_colorref(accent_rgb),
        accent_text=_colorref(OPERATOR_SURFACE.background_rgb),
    )


__all__ = [
    "OperatorAccessibilitySettings",
    "Win32Palette",
    "effective_text_dpi",
    "layout_dpi",
    "resolve_operator_accessibility",
    "win32_palette",
]
