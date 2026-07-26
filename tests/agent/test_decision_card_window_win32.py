from __future__ import annotations

import pytest

from computer_use_agent.decision_card_window_win32 import (
    Win32DecisionCardWindowApi,
    _corner_origin,
)


@pytest.mark.parametrize(
    ("corner", "expected"),
    [
        ("top_left", (120, 70)),
        ("top_right", (920, 70)),
        ("bottom_left", (120, 280)),
        ("bottom_right", (920, 280)),
    ],
)
def test_corner_origin_places_compact_window_inside_work_area(
    corner: str,
    expected: tuple[int, int],
) -> None:
    assert (
        _corner_origin(  # type: ignore[arg-type]
            (100, 50, 1500, 900),
            (560, 600),
            corner,
        )
        == expected
    )


def test_native_window_defaults_to_bottom_right_and_rejects_unknown_corner() -> None:
    assert Win32DecisionCardWindowApi().corner == "bottom_right"
    with pytest.raises(ValueError, match="corner is invalid"):
        Win32DecisionCardWindowApi(corner="center")  # type: ignore[arg-type]
