from __future__ import annotations

import sys

import pytest

from computer_use_agent.decision_card_window_win32 import (
    Win32DecisionCardWindowApi,
    _corner_origin as decision_corner_origin,
    _scaled_client_size as decision_client_size,
)
from computer_use_agent.presence_window import PresenceGeometry
from computer_use_agent.presence_window_win32 import (
    Win32PresenceWindowApi,
    _presence_tab_layout,
)
from computer_use_agent.operator_personalization import OperatorTheme
from computer_use_agent.progress_window_win32 import Win32ProgressWindowApi
from computer_use_agent.progress_window_win32 import _scaled as scale_progress
from computer_use_agent.progress_window_win32 import (
    _top_right_origin as progress_top_right_origin,
)
from computer_use_agent.progress_window_win32 import (
    _window_size as progress_window_size,
)
from computer_use_agent.progress_window_win32 import _workflow_layout


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 operator surfaces")
def test_native_operator_surfaces_can_share_one_process_abi() -> None:
    # Decision Card configures the process-global user32 handle first, matching
    # the integration order that exposed nominally incompatible ctypes pointers.
    Win32DecisionCardWindowApi()
    presence = Win32PresenceWindowApi()
    progress = Win32ProgressWindowApi()

    # The card also configures message-pump signatures. Both passive surfaces
    # must still accept their layout-compatible wintypes.MSG structures.
    presence.pump()
    progress.pump()


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 operator surfaces")
def test_native_operator_surfaces_accept_one_shared_light_theme() -> None:
    decision = Win32DecisionCardWindowApi(theme=OperatorTheme.LIGHT)
    presence = Win32PresenceWindowApi(theme=OperatorTheme.LIGHT)
    progress = Win32ProgressWindowApi(theme=OperatorTheme.LIGHT)

    assert decision.theme is OperatorTheme.LIGHT
    assert presence.theme is OperatorTheme.LIGHT
    assert progress.theme is OperatorTheme.LIGHT


def test_progress_summary_geometry_scales_with_dpi() -> None:
    assert scale_progress(460, 96) == 460
    assert scale_progress(460, 120) == 575
    assert scale_progress(460, 144) == 690
    assert progress_window_size(False, 144) == (690, 375)
    assert progress_window_size(True, 144) == (780, 840)


def test_progress_geometry_reflows_at_400_percent_text_scale() -> None:
    compact = progress_window_size(False, 96, text_scale_factor=4.0)
    expanded = progress_window_size(True, 96, text_scale_factor=4.0)

    assert 920 <= compact[0] <= 1_040
    assert compact[1] >= 500
    assert expanded[0] >= compact[0]
    assert expanded[1] > compact[1]


def test_progress_expanded_content_is_one_bounded_viewport_at_400_percent() -> None:
    rows = _workflow_layout(192, 384, checklist_steps=6)

    # Six semantic summary rows are followed by one scrollable document
    # viewport; checklist length no longer makes the passive window unbounded.
    assert len(rows) == 7
    for current, following in zip(rows, rows[1:], strict=False):
        assert current[0] + current[1] < following[0]
    compact_height = progress_window_size(False, 96, text_scale_factor=4.0)[1]
    expanded_height = progress_window_size(True, 96, text_scale_factor=4.0)[1]
    assert rows[-1][1] == 360
    assert compact_height < expanded_height <= 1_400


def test_progress_document_style_ranges_follow_rich_edit_newlines() -> None:
    lines = ("status", "workflow", "counts", "step", "action", "app", "checklist")

    text, spans = Win32ProgressWindowApi._workflow_document_text(lines)

    assert text == "status\nworkflow\ncounts\n\nstep\naction\napp\n\nchecklist"
    assert tuple(text[start:end] for start, end, _index in spans) == lines
    assert tuple(index for _start, _end, index in spans) == tuple(range(len(lines)))


@pytest.mark.parametrize(
    ("text_width", "text_height"),
    [(641, 53), (845, 53), (444, 53), (581, 53)],
)
def test_presence_status_tab_contains_measured_large_text(
    text_width: int,
    text_height: int,
) -> None:
    geometry = PresenceGeometry(0, 0, 1920, 1080, 20, 32, 192)

    left, top, right, bottom, text_x, text_y = _presence_tab_layout(
        geometry,
        192,
        text_width=text_width,
        text_height=text_height,
    )

    assert text_x >= left
    assert text_y >= top
    assert text_x + text_width + geometry.label_inset_px <= right
    assert text_y + text_height + geometry.label_inset_px <= bottom
    assert right <= geometry.width - geometry.border_px
    assert bottom <= geometry.height - geometry.border_px


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_compact_huds_use_separate_right_side_rails_without_covering_demo_app(
    dpi: int,
) -> None:
    work_area = (0, 0, 2560, 1400)
    demo_application = (80, 80, 1360, 980)
    progress_size = progress_window_size(False, dpi)
    decision_size = decision_client_size(False, dpi)
    scaled_margin = scale_progress(20, dpi)
    progress_origin = progress_top_right_origin(
        work_area,
        progress_size,
        margin=scaled_margin,
    )
    decision_origin = decision_corner_origin(
        work_area,
        decision_size,
        "bottom_right",
        margin=scaled_margin,
    )
    progress_rect = (
        *progress_origin,
        progress_origin[0] + progress_size[0],
        progress_origin[1] + progress_size[1],
    )
    decision_rect = (
        *decision_origin,
        decision_origin[0] + decision_size[0],
        decision_origin[1] + decision_size[1],
    )

    assert progress_rect[2] <= work_area[2]
    assert progress_rect[3] <= work_area[3]
    assert decision_rect[2] <= work_area[2]
    assert decision_rect[3] <= work_area[3]
    assert progress_rect[0] >= demo_application[2]
    assert decision_rect[0] >= demo_application[2]
    assert progress_rect[3] < decision_rect[1]


def test_progress_top_right_origin_handles_offset_and_small_work_areas() -> None:
    assert progress_top_right_origin(
        (-1920, 0, 0, 1080),
        (460, 250),
    ) == (-480, 20)
    assert progress_top_right_origin(
        (0, 40, 300, 200),
        (460, 250),
    ) == (0, 40)
    with pytest.raises(ValueError, match="PROGRESS_WORK_AREA_INVALID"):
        progress_top_right_origin((0, 0, 0, 100), (40, 40))
