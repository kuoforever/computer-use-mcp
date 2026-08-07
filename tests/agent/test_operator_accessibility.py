from __future__ import annotations

import pytest

from computer_use_agent.operator_accessibility import (
    OperatorAccessibilitySettings,
    effective_text_dpi,
    layout_dpi,
    resolve_operator_accessibility,
    win32_palette,
)


class _SystemColors:
    def __init__(self) -> None:
        self.values = {
            5: 0x00112233,  # COLOR_WINDOW
            8: 0x00445566,  # COLOR_WINDOWTEXT
            13: 0x00778899,  # COLOR_HIGHLIGHT
            14: 0x00AABBCC,  # COLOR_HIGHLIGHTTEXT
            15: 0x00DDEEFF,  # COLOR_BTNFACE
            18: 0x00010203,  # COLOR_BTNTEXT
        }

    def GetSysColor(self, index: int) -> int:
        return self.values[index]


def test_forced_preferences_compose_with_system_accessibility() -> None:
    settings = resolve_operator_accessibility(
        force_high_contrast=False,
        force_reduced_motion=True,
        system_loader=lambda: OperatorAccessibilitySettings(
            high_contrast=True,
            reduced_motion=False,
            text_scale_factor=2.25,
        ),
    )

    assert settings == OperatorAccessibilitySettings(
        high_contrast=True,
        reduced_motion=True,
        text_scale_factor=2.25,
    )


def test_unavailable_system_settings_fail_to_static_safe_defaults() -> None:
    def unavailable() -> OperatorAccessibilitySettings:
        raise OSError("system accessibility unavailable")

    assert resolve_operator_accessibility(
        force_high_contrast=False,
        force_reduced_motion=False,
        system_loader=unavailable,
    ) == OperatorAccessibilitySettings()


@pytest.mark.parametrize("factor", [0.99, 4.01, float("inf"), float("nan")])
def test_text_scale_is_strictly_bounded(factor: float) -> None:
    with pytest.raises(ValueError, match="OPERATOR_TEXT_SCALE_INVALID"):
        OperatorAccessibilitySettings(text_scale_factor=factor)


def test_effective_text_scale_supports_400_percent_without_unbounded_geometry() -> None:
    assert effective_text_dpi(96, 4.0) == 384
    assert effective_text_dpi(192, 2.25) == 384
    assert layout_dpi(96, 4.0) == 192
    assert layout_dpi(384, 1.0) == 192


def test_high_contrast_palette_uses_only_operator_selected_system_colors() -> None:
    colors = _SystemColors()

    palette = win32_palette(colors, high_contrast=True, accent_rgb=0xF2C94C)

    assert palette.background == colors.values[5]
    assert palette.surface == colors.values[15]
    assert palette.text == colors.values[8]
    assert palette.muted_text == colors.values[18]
    assert palette.hairline == colors.values[13]
    assert palette.accent == colors.values[13]
    assert palette.accent_text == colors.values[14]


def test_regular_palette_retains_shared_product_tokens() -> None:
    palette = win32_palette(_SystemColors(), high_contrast=False, accent_rgb=0xF2C94C)

    assert palette.background == 0x001E1713
    assert palette.surface == 0x00362A23
    assert palette.text == 0x00F5F5F5
    assert palette.muted_text == 0x00B8B8B8
    assert palette.hairline == 0x007D6D62
    assert palette.accent == 0x004CC9F2
    assert palette.accent_text == 0x001E1713
