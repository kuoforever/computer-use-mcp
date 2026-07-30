from __future__ import annotations

import pytest

from computer_use_agent.decision_card_window_win32 import (
    Win32DecisionCardWindowApi,
    _corner_origin,
    _layout_rects,
    _scaled_client_size,
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


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_compact_layout_is_two_by_two_without_detail_panes(dpi: int) -> None:
    width, height = _scaled_client_size(False, dpi)
    rects = _layout_rects(width, height, 4, expanded=False, dpi=dpi)

    assert "content" not in rects
    assert "evidence" not in rects
    assert rects["accent"] == (0, 0, round(5 * dpi / 96), height)
    assert rects["button_0"][1] == rects["button_1"][1]
    assert rects["button_2"][1] == rects["button_3"][1]
    assert rects["button_0"][0] == rects["button_2"][0]
    assert rects["button_1"][0] == rects["button_3"][0]
    assert rects["toggle"][1] + rects["toggle"][3] < rects["button_0"][1]
    for x, y, control_width, control_height in rects.values():
        assert x >= 0 and y >= 0
        assert x + control_width <= width
        assert y + control_height <= height


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_expanded_layout_reveals_separate_bounded_detail_panes(dpi: int) -> None:
    width, height = _scaled_client_size(True, dpi)
    rects = _layout_rects(width, height, 4, expanded=True, dpi=dpi)

    content = rects["content"]
    evidence = rects["evidence"]
    first_button = rects["button_0"]
    assert content[1] + content[3] < evidence[1]
    assert evidence[1] + evidence[3] < first_button[1]
