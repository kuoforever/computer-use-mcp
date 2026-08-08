from __future__ import annotations

import pathlib

import pytest

from computer_use_agent.decision_card_window_win32 import (
    _BS_MULTILINE,
    _BS_OWNERDRAW,
    _CARD_EX_STYLE,
    _CARD_STYLE,
    _DETAILS_STYLE,
    _ES_READONLY,
    _HEADER_TIERS,
    _HEADER_CONTROL_IDS,
    _HUD_BACKGROUND,
    _HUD_MUTED_TEXT,
    _HUD_TEXT,
    _ODS_DISABLED,
    _ODS_FOCUS,
    _ODS_SELECTED,
    Win32DecisionCardWindowApi,
    _blend_colorref,
    _corner_origin,
    _detail_style_spans,
    _header_rects,
    _immersive_dark_mode,
    _interaction_fill_role,
    _layout_rects,
    _restore_if_minimized,
    _rich_detail_text,
    _scaled_client_size,
    _safe_default_control_id,
    _status_announcement_seconds,
    _tier_font_height,
    _toggle_label,
    _WS_TABSTOP,
    _WS_VSCROLL,
    measure_tier_text_extent,
    measure_tier_text_width,
)
from computer_use_agent.demo_cross_app import DEMO_WORKFLOW
from computer_use_agent.operator_accessibility import effective_text_dpi, layout_dpi
from computer_use_agent.operator_visuals import (
    OPERATOR_TYPE_ACTION,
    OPERATOR_TYPE_META,
    OPERATOR_TYPE_MICRO_LABEL,
)
from computer_use_agent.operator_localization import (
    OperatorLocale,
    localize_fixed_text,
    operator_text,
)
from computer_use_agent.operator_personalization import OperatorTheme
from computer_use_agent.progress_window_win32 import (
    _HUD_BACKGROUND as _PROGRESS_BACKGROUND,
    _HUD_MUTED as _PROGRESS_MUTED,
    _HUD_TEXT as _PROGRESS_TEXT,
)

_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_EX_CLIENTEDGE = 0x00000200


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


def test_light_and_high_contrast_disable_immersive_dark_caption() -> None:
    assert _immersive_dark_mode(OperatorTheme.DARK, high_contrast=False)
    assert not _immersive_dark_mode(OperatorTheme.LIGHT, high_contrast=False)
    assert not _immersive_dark_mode(OperatorTheme.DARK, high_contrast=True)


def test_native_copy_uses_one_locale_for_visible_and_uia_text() -> None:
    api = Win32DecisionCardWindowApi(locale=OperatorLocale.ZH_CN)

    assert api.locale is OperatorLocale.ZH_CN
    assert _toggle_label(False, api.locale) == "显示详情"
    assert _toggle_label(True, api.locale) == "收起详情"


def test_foreground_restore_preserves_non_minimized_window_placement() -> None:
    class User32:
        def __init__(self, *, minimized: bool) -> None:
            self.minimized = minimized
            self.show_calls: list[tuple[object, int]] = []

        def IsIconic(self, _hwnd: object) -> bool:
            return self.minimized

        def ShowWindow(self, hwnd: object, command: int) -> None:
            self.show_calls.append((hwnd, command))

    maximized = User32(minimized=False)
    _restore_if_minimized(maximized, "user-chrome")
    assert maximized.show_calls == []

    minimized = User32(minimized=True)
    _restore_if_minimized(minimized, "user-chrome")
    assert minimized.show_calls == [("user-chrome", 9)]


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_compact_layout_is_two_by_two_without_detail_panes(dpi: int) -> None:
    width, height = _scaled_client_size(False, dpi)
    rects = _layout_rects(width, height, 4, expanded=False, dpi=dpi)

    assert "content" not in rects
    assert "evidence" not in rects
    # The header is painted, so it contributes no child-control rectangle.
    assert "instruction" not in rects
    assert "timeout" not in rects
    assert rects["accent"] == (0, 0, round(4 * dpi / 96), height)
    assert rects["button_0"][1] == rects["button_1"][1]
    assert rects["button_2"][1] == rects["button_3"][1]
    assert rects["button_0"][0] == rects["button_2"][0]
    assert rects["button_1"][0] == rects["button_3"][0]
    geometry_dpi = layout_dpi(dpi, 1.0)
    minimum_section_gap = max(1, round(12 * geometry_dpi / 96))
    assert (
        rects["actions_panel"][1]
        - (rects["toggle"][1] + rects["toggle"][3])
        >= minimum_section_gap
    )
    for x, y, control_width, control_height in rects.values():
        assert x >= 0 and y >= 0
        assert x + control_width <= width
        assert y + control_height <= height


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_expanded_layout_reveals_separate_bounded_detail_panes(dpi: int) -> None:
    width, height = _scaled_client_size(True, dpi)
    rects = _layout_rects(width, height, 4, expanded=True, dpi=dpi)

    details = rects["details"]
    details_label = rects["details_label"]
    information_panel = rects["information_panel"]
    actions_panel = rects["actions_panel"]
    toggle = rects["toggle"]
    first_button = rects["button_0"]
    # One scroll context, not two stacked ones, and it clears the affordance
    # above it and the choices below it.
    assert "content" not in rects
    assert "evidence" not in rects
    assert toggle[1] + toggle[3] <= details[1]
    assert toggle[1] + toggle[3] <= details_label[1]
    assert details_label[1] + details_label[3] < details[1]
    assert details[1] + details[3] < first_button[1]
    assert details[0] + details[2] <= width
    assert information_panel[1] <= details_label[1]
    assert details[1] + details[3] <= (information_panel[1] + information_panel[3])
    assert information_panel[1] + information_panel[3] < actions_panel[1]


@pytest.mark.parametrize("text_scale_factor", [1.0, 2.0, 4.0])
@pytest.mark.parametrize("expanded", [False, True])
def test_layout_reflows_through_400_percent_without_control_overlap(
    text_scale_factor: float,
    expanded: bool,
) -> None:
    width, height = _scaled_client_size(
        expanded,
        96,
        text_scale_factor=text_scale_factor,
    )
    rects = _layout_rects(
        width,
        height,
        4,
        expanded=expanded,
        dpi=96,
        text_scale_factor=text_scale_factor,
    )
    header = _header_rects(width, 96, text_scale_factor=text_scale_factor)

    header_bottom = max(
        top + rect_height for (left, top, rect_width, rect_height), _tier in header.values()
    )
    toggle = rects["toggle"]
    first_button = rects["button_0"]
    actions_panel = rects["actions_panel"]
    assert header_bottom <= toggle[1]
    geometry_dpi = layout_dpi(96, text_scale_factor)
    minimum_section_gap = max(1, round(12 * geometry_dpi / 96))
    assert actions_panel[1] - (toggle[1] + toggle[3]) >= minimum_section_gap
    assert actions_panel[1] <= first_button[1]
    assert first_button[1] + first_button[3] <= (actions_panel[1] + actions_panel[3])
    if expanded:
        details = rects["details"]
        details_label = rects["details_label"]
        information_panel = rects["information_panel"]
        assert toggle[1] + toggle[3] <= details[1]
        assert details_label[1] + details_label[3] < details[1]
        assert details[1] + details[3] <= (information_panel[1] + information_panel[3])
        assert information_panel[1] + information_panel[3] < actions_panel[1]
    for x, y, control_width, control_height in rects.values():
        assert x >= 0 and y >= 0
        assert x + control_width <= width
        assert y + control_height <= height


@pytest.mark.parametrize("dpi", [96, 120, 144])
@pytest.mark.parametrize("text_scale_factor", [1.0, 2.0, 4.0])
def test_text_controls_reserve_positive_scaled_font_height(
    dpi: int,
    text_scale_factor: float,
) -> None:
    """Layout uses positive glyph height, not CreateFontW's signed request."""

    text_dpi = effective_text_dpi(dpi, text_scale_factor)
    geometry_dpi = layout_dpi(dpi, text_scale_factor)

    def scale(value: int) -> int:
        return max(1, round(value * geometry_dpi / 96))

    width, height = _scaled_client_size(
        True,
        dpi,
        text_scale_factor=text_scale_factor,
    )
    header = _header_rects(
        width,
        dpi,
        text_scale_factor=text_scale_factor,
    )
    rects = _layout_rects(
        width,
        height,
        4,
        expanded=True,
        dpi=dpi,
        text_scale_factor=text_scale_factor,
    )

    for rect, tier in header.values():
        assert rect[3] >= -_tier_font_height(tier, text_dpi) + scale(4)
    assert rects["toggle"][3] >= (
        -_tier_font_height(OPERATOR_TYPE_MICRO_LABEL, text_dpi) + scale(8)
    )
    assert rects["button_0"][3] >= (-_tier_font_height(OPERATOR_TYPE_META, text_dpi) + scale(16))
    assert rects["details_label"][3] >= (
        -_tier_font_height(OPERATOR_TYPE_ACTION, text_dpi) + scale(4)
    )


def test_interaction_fill_states_have_explicit_priority() -> None:
    assert _interaction_fill_role(0, is_hovered=False) == "normal"
    assert _interaction_fill_role(_ODS_FOCUS, is_hovered=False) == "focused"
    assert _interaction_fill_role(_ODS_FOCUS, is_hovered=True) == "focused"
    assert _interaction_fill_role(0, is_hovered=True) == "hovered"
    assert _interaction_fill_role(_ODS_SELECTED, is_hovered=True) == "pressed"
    assert (
        _interaction_fill_role(
            _ODS_DISABLED | _ODS_SELECTED,
            is_hovered=True,
        )
        == "disabled"
    )


def test_interaction_hover_blend_preserves_colorref_endpoints() -> None:
    assert _blend_colorref(0x112233, 0xAABBCC, 0) == 0x112233
    assert _blend_colorref(0x112233, 0xAABBCC, 255) == 0xAABBCC


@pytest.mark.parametrize(
    ("content", "evidence", "expected"),
    [
        (
            "Decision scope\nBody.\n\nYour choices\n1. Approve\n   Outcome: Blocked.",
            "Safety checks\n- Bound.\n\nTechnical verification\n- Screen state: 1234",
            {
                ("Decision scope", "section"),
                ("Your choices", "section"),
                ("1. Approve", "option"),
                ("Outcome:", "field"),
                ("Safety checks", "section"),
                ("Technical verification", "section"),
                ("Screen state:", "field"),
            },
        ),
        (
            "决策范围\n正文。\n\n你的选择\n1. 批准\n   结果：保持阻止。",
            "安全检查\n- 已绑定。\n\n技术验证\n- 屏幕状态：1234",
            {
                ("决策范围", "section"),
                ("你的选择", "section"),
                ("1. 批准", "option"),
                ("结果：", "field"),
                ("安全检查", "section"),
                ("技术验证", "section"),
                ("屏幕状态：", "field"),
            },
        ),
    ],
)
def test_detail_hierarchy_uses_locale_neutral_structure(
    content: str,
    evidence: str,
    expected: set[tuple[str, str]],
) -> None:
    text = _rich_detail_text(content, evidence)
    observed = {(text[span.start : span.end], span.role) for span in _detail_style_spans(text)}

    assert expected <= observed
    assert ("Body.", "section") not in observed
    assert ("正文。", "section") not in observed


def test_header_is_exposed_by_distinct_native_text_controls() -> None:
    assert tuple(_HEADER_CONTROL_IDS) == (2003, 2004, 2006, 2007)
    assert len(set(_HEADER_CONTROL_IDS)) == len(_HEADER_TIERS)


def test_deny_is_the_only_safe_default_and_is_required() -> None:
    assert (
        _safe_default_control_id(
            {
                1001: "option_approve_exact_effect",
                1002: "option_reobserve",
                1003: "option_defer",
                1004: "option_deny",
            }
        )
        == 1004
    )
    with pytest.raises(OSError, match="DECISION_CARD_SAFE_DEFAULT_REQUIRED"):
        _safe_default_control_id({1001: "option_approve_exact_effect"})


def test_timeout_announcements_are_bounded_not_one_event_per_second() -> None:
    assert _status_announcement_seconds(300) == (300, 60, 30, 10, 0)
    assert _status_announcement_seconds(30) == (30, 10, 0)
    assert _status_announcement_seconds(5) == (5, 0)


def test_card_frame_offers_no_resize_maximize_or_minimize() -> None:
    """One bounded decision has one reviewed geometry the operator cannot break."""

    for forbidden in (_WS_THICKFRAME, _WS_MINIMIZEBOX, _WS_MAXIMIZEBOX):
        assert _CARD_STYLE & forbidden == 0
    # The caption and system menu stay: closing the card must remain one
    # obvious click, and closing is already a safe deny.
    assert _CARD_STYLE & 0x00C00000 == 0x00C00000
    assert _CARD_STYLE & 0x00080000
    # The sunken 3D bevel is a legacy dialog cue and must not return.
    assert _CARD_EX_STYLE & _WS_EX_CLIENTEDGE == 0


def test_choice_controls_are_owner_drawn_without_a_default_push_type() -> None:
    """``BS_*`` type styles share one field, so owner draw excludes the rest."""

    style = _BS_OWNERDRAW | _BS_MULTILINE
    assert style & 0x0F == _BS_OWNERDRAW
    assert _toggle_label(False) == "Show details"
    assert _toggle_label(True) == "Hide details"


def test_read_only_details_stay_out_of_the_interactive_tab_order() -> None:
    assert _DETAILS_STYLE & _ES_READONLY
    assert _DETAILS_STYLE & _WS_VSCROLL
    assert not _DETAILS_STYLE & _WS_TABSTOP


def test_header_tiers_match_the_four_line_controller_contract() -> None:
    assert len(_HEADER_TIERS) == 4
    offsets = [offset for offset, _tier, _accent in _HEADER_TIERS]
    assert offsets == sorted(offsets)
    assert [accent for _offset, _tier, accent in _HEADER_TIERS] == [
        True,
        False,
        False,
        False,
    ]
    points = [tier.points for _offset, tier, _accent in _HEADER_TIERS]
    assert points[1] > points[0], "the decided action outranks its micro-label"


#: The longest strings the bounded Demo can actually put on the card. Chapter
#: labels come from the reviewed workflow itself so the check tracks real data.
_LONGEST_ACTION = "Add the source note to the research brief"
_LONGEST_CHAPTER = max(
    (step.label for step in DEMO_WORKFLOW.steps),
    key=len,
)
_LONGEST_HEADER_LINES = (
    "NEEDS INPUT  ·  APPROVAL LOCKED",
    _LONGEST_ACTION,
    "APPROVAL 7/7  ·  Microsoft Word",
    f"WORKFLOW 6/6  ·  {_LONGEST_CHAPTER}",
)
_BUTTON_LABELS = (
    "Approve once",
    "Check screen again",
    "Pause and inspect",
    "Stop task",
)


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_header_text_fits_its_painted_rectangle_at_every_dpi(dpi: int) -> None:
    """Measure real glyph extents, not just boxes.

    Geometry checks passed while the title was visibly clipped, because they
    only proved the rectangles fitted the client area. This measures the text
    that goes inside them.

    The measurement is machine-specific by design. If Segoe UI is unavailable
    and a wider fallback is substituted, a failure here is a true report that
    this card would clip on that machine, not a flaky test.
    """

    width, _height = _scaled_client_size(False, dpi)
    rects = _header_rects(width, dpi)

    for index, text in enumerate(_LONGEST_HEADER_LINES):
        (_left, _top, rect_width, _rect_height), tier = rects[f"line_{index}"]
        measured_width, measured_height = measure_tier_text_extent(
            text,
            tier=tier,
            dpi=dpi,
        )
        assert measured_width <= rect_width, (
            f"line {index} needs {measured_width}px in {rect_width}px at {dpi} DPI"
        )
        assert measured_height + round(4 * dpi / 96) <= _rect_height

    (_left, _top, countdown_width, _h), countdown_tier = rects["countdown"]
    measured_width, measured_height = measure_tier_text_extent(
        "Closes in 3600s",
        tier=countdown_tier,
        dpi=dpi,
    )
    assert measured_width <= countdown_width
    assert measured_height + round(4 * dpi / 96) <= _h


@pytest.mark.parametrize("text_scale_factor", [1.0, 2.0, 4.0])
@pytest.mark.parametrize("locale", [OperatorLocale.EN_US, OperatorLocale.ZH_CN])
def test_localized_header_and_countdown_reflow_fit_scaled_glyphs(
    locale: OperatorLocale,
    text_scale_factor: float,
) -> None:
    dpi = 144
    width, _height = _scaled_client_size(
        False,
        dpi,
        text_scale_factor=text_scale_factor,
    )
    rects = _header_rects(
        width,
        dpi,
        text_scale_factor=text_scale_factor,
    )
    text_dpi = effective_text_dpi(dpi, text_scale_factor)
    lines = (
        f"{localize_fixed_text(locale, 'Needs input').upper()}  ·  "
        f"{operator_text(locale, 'approval_locked')}",
        operator_text(locale, "choose_bounded_option"),
        f"{operator_text(locale, 'approval')} 7/7  ·  Microsoft Word",
        f"{operator_text(locale, 'workflow')} 6/6  ·  "
        f"{localize_fixed_text(locale, _LONGEST_CHAPTER)}",
    )

    for index, text in enumerate(lines):
        (_left, _top, rect_width, rect_height), tier = rects[f"line_{index}"]
        measured_width, measured_height = measure_tier_text_extent(
            text,
            tier=tier,
            dpi=text_dpi,
        )
        geometry_dpi = layout_dpi(dpi, text_scale_factor)
        rows = 1
        if index == 1 and text_dpi >= 2 * geometry_dpi:
            rows = 2
        elif index in {2, 3} and text_dpi > geometry_dpi:
            rows = 2
        assert measured_width <= rect_width * rows, (
            f"{locale.value} line {index} needs {measured_width}px in "
            f"{rect_width}px x {rows} rows at {text_scale_factor:.0f}x"
        )
        safety_padding = max(1, round(4 * layout_dpi(dpi, text_scale_factor) / 96))
        assert measured_height * rows + safety_padding <= rect_height

    countdown = operator_text(locale, "countdown", seconds=3600)
    (_left, countdown_top, countdown_width, countdown_height), tier = rects["countdown"]
    measured_width, measured_height = measure_tier_text_extent(
        countdown,
        tier=tier,
        dpi=text_dpi,
    )
    assert measured_width <= countdown_width
    assert measured_height + max(
        1,
        round(4 * layout_dpi(dpi, text_scale_factor) / 96),
    ) <= countdown_height
    line_0 = rects["line_0"][0]
    line_1 = rects["line_1"][0]
    if text_scale_factor == 4.0:
        assert line_0[1] + line_0[3] <= countdown_top
        assert countdown_top + rects["countdown"][0][3] <= line_1[1]
    else:
        assert countdown_top == line_0[1]


@pytest.mark.parametrize("dpi", [96, 120, 144])
def test_choice_labels_fit_their_buttons_at_every_dpi(dpi: int) -> None:
    width, height = _scaled_client_size(False, dpi)
    button_width = _layout_rects(width, height, 4, expanded=False, dpi=dpi)["button_0"][2]
    for label in _BUTTON_LABELS:
        measured = measure_tier_text_width(
            label,
            tier=OPERATOR_TYPE_META,
            dpi=dpi,
        )
        assert measured <= button_width


@pytest.mark.parametrize("text_scale_factor", [1.0, 2.0, 4.0])
def test_choice_labels_fit_their_buttons_at_scaled_text(
    text_scale_factor: float,
) -> None:
    dpi = 144
    text_dpi = effective_text_dpi(dpi, text_scale_factor)
    width, height = _scaled_client_size(
        False,
        dpi,
        text_scale_factor=text_scale_factor,
    )
    button_width = _layout_rects(
        width,
        height,
        4,
        expanded=False,
        dpi=dpi,
        text_scale_factor=text_scale_factor,
    )["button_0"][2]

    for label in _BUTTON_LABELS:
        measured = measure_tier_text_width(
            label,
            tier=OPERATOR_TYPE_META,
            dpi=text_dpi,
        )
        assert measured <= button_width


def test_the_text_fit_check_would_have_caught_the_clipped_title() -> None:
    """Guard the guard: the regression it exists for must actually trip it.

    The title was clipped because the countdown reserve was subtracted from
    every header row instead of only the micro-label's. Reproducing that
    reserve must exceed the measured title width.
    """

    dpi = 144
    width, _height = _scaled_client_size(False, dpi)
    (_left, _top, title_width, _h), tier = _header_rects(width, dpi)["line_1"]
    countdown_width = _header_rects(width, dpi)["countdown"][0][2]

    measured = measure_tier_text_width(_LONGEST_ACTION, tier=tier, dpi=dpi)
    assert measured <= title_width
    assert measured > title_width - countdown_width, (
        "the old shared-reserve layout must still be provably too narrow"
    )


#: Win32 entry points that can take an operator's input away from them. A
#: focus-taking approval gate is the one surface in this product with a motive
#: to reach for them, and `GDA-HUD-004` states the rule plainly: "Locked" must
#: never mean trapping the operator. Alt+Tab, the Windows key, and Ctrl+Alt+Del
#: stay available because the card never installs a hook, claims a hotkey,
#: blocks input, or confines the cursor.
_TRAPPING_WIN32_CALLS = (
    "SetWindowsHookEx",
    "RegisterHotKey",
    "BlockInput",
    "ClipCursor",
    "SetCapture",
    "SetWindowDisplayAffinity",
    "SystemParametersInfo",
    "LockWorkStation",
    "SetForegroundWindowLockTimeout",
)


def test_the_decision_card_never_reaches_for_an_input_trapping_api() -> None:
    """Read the source: the trapping calls must be absent, not merely unused.

    An approval gate that pauses dispatch is exactly where someone would be
    tempted to enforce the pause with a keyboard hook. This asserts the module
    cannot, because the calls do not appear in it at all.
    """

    source = (
        pathlib.Path(__file__).resolve().parents[2]
        / "src"
        / "computer_use_agent"
        / "decision_card_window_win32.py"
    ).read_text(encoding="utf-8")

    for name in _TRAPPING_WIN32_CALLS:
        assert name not in source, f"the Decision Card must not call {name}"

    assert "IsDialogMessageW" in source
    assert "SetFocus(controls[safe_default_name])" in source
    assert "focused_id in id_to_option" in source
    assert "GetNextDlgTabItem" in source
    assert "TrackMouseEvent" in source


def test_every_non_choice_exit_denies_rather_than_selecting() -> None:
    """Esc, close, timeout, and an unknown id must all resolve to no selection.

    A positive approval must come from an explicit bounded choice, so any exit
    that is not one of the card's own option ids has to be indistinguishable
    from a denial at this boundary.
    """

    card_options = {
        "option_approve_exact_effect",
        "option_reobserve",
        "option_defer",
        "option_deny",
    }
    for exit_value in (None, "", "option_unknown", "OPTION_APPROVE_EXACT_EFFECT"):
        assert exit_value not in card_options, (
            f"{exit_value!r} must not be mistaken for a bounded choice"
        )


def test_owner_drawn_labels_are_sized_from_get_window_text_length() -> None:
    """A caption read the Win32 way, so owner-drawn controls are never blank.

    ``GetWindowTextW(hwnd, NULL, 0)`` copies nothing and returns 0. Sizing the
    buffer from it produced buttons with correct geometry and no text at all.
    """

    class Win32Semantics:
        def GetWindowTextLengthW(self, _hwnd: object) -> int:
            return len("Approve once")

        def GetWindowTextW(
            self,
            _hwnd: object,
            buffer: object,
            max_count: int,
        ) -> int:
            if buffer is None or max_count <= 0:
                return 0
            buffer.value = "Approve once"[: max_count - 1]
            return len(buffer.value)

    api = Win32DecisionCardWindowApi.__new__(Win32DecisionCardWindowApi)
    api._user32 = Win32Semantics()  # type: ignore[attr-defined]

    assert api._control_label(object()) == "Approve once"  # type: ignore[arg-type]

    class NeverLabelled(Win32Semantics):
        def GetWindowTextLengthW(self, _hwnd: object) -> int:
            return 0

    api._user32 = NeverLabelled()  # type: ignore[attr-defined]
    assert api._control_label(object()) == ""  # type: ignore[arg-type]


def test_both_hud_surfaces_share_one_chrome_palette() -> None:
    assert _HUD_BACKGROUND == _PROGRESS_BACKGROUND
    assert _HUD_TEXT == _PROGRESS_TEXT
    assert _HUD_MUTED_TEXT == _PROGRESS_MUTED
