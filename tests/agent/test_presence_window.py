from __future__ import annotations

import pytest

from computer_use_agent.operator_display import OperatorMonitor
from computer_use_agent.operator_localization import OperatorLocale
from computer_use_agent.presence import (
    DesktopAuthority,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
    PresenceView,
)
from computer_use_agent.presence_window import (
    PRESENCE_EX_STYLE,
    PRESENCE_STYLE,
    WS_EX_LAYERED,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_EX_TRANSPARENT,
    WS_POPUP,
    PassivePresenceWindow,
    PresenceGeometry,
    PresenceWindowApi,
    PresenceWindowError,
    presence_accessible_name,
    presence_geometry,
)

_FORBIDDEN_CALLS = frozenset(
    {
        "activate",
        "focus",
        "set_focus",
        "set_foreground",
        "bring_to_top",
        "capture_input",
        "set_capture",
        "register_hotkey",
    }
)


class FakePresenceWindowApi:
    def __init__(self, *, capture_excluded: bool = True) -> None:
        self.monitor = OperatorMonitor(
            (0, 0, 1920, 1080),
            (0, 0, 1920, 1040),
            96,
        )
        self.capture_excluded = capture_excluded
        self.calls: list[tuple] = []
        self._foreground = 4242
        self._next = 100
        self.alive: set[int] = set()

    def display_monitor(self) -> OperatorMonitor:
        self.calls.append(("display_monitor", self.monitor))
        return self.monitor

    def create(self, *, ex_style: int, style: int, title: str) -> int:
        self._next += 1
        self.alive.add(self._next)
        self.calls.append(("create", ex_style, style, title, self._next))
        return self._next

    def configure(
        self, hwnd: int, view: PresenceView, geometry: PresenceGeometry
    ) -> None:
        self.calls.append(("configure", hwnd, view, geometry))

    def exclude_from_capture(self, hwnd: int) -> bool:
        self.calls.append(("exclude_from_capture", hwnd))
        return self.capture_excluded

    def show_noactivate(self, hwnd: int) -> None:
        self.calls.append(("show_noactivate", hwnd))

    def foreground(self) -> int:
        return self._foreground

    def destroy(self, hwnd: int) -> None:
        self.alive.discard(hwnd)
        self.calls.append(("destroy", hwnd))

    def __getattr__(self, name: str):  # pragma: no cover - reached only on misuse
        if name in _FORBIDDEN_CALLS:
            raise AssertionError(f"presence surface must never call {name!r}")
        raise AttributeError(name)

    def kinds(self) -> list[str]:
        return [str(call[0]) for call in self.calls]


def _snapshot(
    phase: PresencePhase = PresencePhase.OBSERVING,
    authority: DesktopAuthority = DesktopAuthority.HELD,
    **over,
) -> PresenceSnapshot:
    return PresenceSnapshot(phase, authority, **over)


def test_fake_satisfies_minimal_native_protocol() -> None:
    assert isinstance(FakePresenceWindowApi(), PresenceWindowApi)


def test_presence_accessible_name_is_fixed_and_content_free() -> None:
    view = PresenceView(
        phase="WAITING_APPROVAL",
        visual_role="needs_input",
        label="Needs input",
        glyph="APPROVAL",
        color_rgb=0xF2C94C,
        motion="PULSE",
        motion_enabled=False,
        animation_interval_ms=None,
        high_contrast=True,
    )

    assert presence_accessible_name(view) == "Computer Use. Approval. Needs input."

    chinese_view = PresenceView(
        phase=view.phase,
        visual_role=view.visual_role,
        label="需要确认",
        glyph="审批",
        color_rgb=view.color_rgb,
        motion=view.motion,
        motion_enabled=view.motion_enabled,
        animation_interval_ms=view.animation_interval_ms,
        high_contrast=view.high_contrast,
    )
    assert presence_accessible_name(
        chinese_view,
        locale=OperatorLocale.ZH_CN,
    ) == "电脑操作。审批。需要确认。"


def test_open_uses_clickthrough_nonactivating_layered_tool_styles() -> None:
    api = FakePresenceWindowApi()
    window = PassivePresenceWindow(api)
    before = api.foreground()

    result = window.sync(_snapshot(PresencePhase.EXECUTING))

    create = next(call for call in api.calls if call[0] == "create")
    assert create[1] == PRESENCE_EX_STYLE
    for flag in (
        WS_EX_TOPMOST,
        WS_EX_TRANSPARENT,
        WS_EX_TOOLWINDOW,
        WS_EX_LAYERED,
        WS_EX_NOACTIVATE,
    ):
        assert create[1] & flag
    assert create[2] == PRESENCE_STYLE == WS_POPUP
    assert result.visible and result.created and result.capture_excluded
    assert api.kinds() == [
        "display_monitor",
        "create",
        "exclude_from_capture",
        "configure",
        "show_noactivate",
    ]
    assert api.foreground() == before


def test_unchanged_snapshot_is_not_reconfigured() -> None:
    api = FakePresenceWindowApi()
    window = PassivePresenceWindow(api)
    window.sync(_snapshot())

    outcome = window.sync(_snapshot())

    assert not outcome.changed and not outcome.created
    assert api.kinds().count("configure") == 1
    assert api.kinds().count("show_noactivate") == 1


def test_phase_and_dpi_changes_update_without_recreating_or_taking_focus() -> None:
    api = FakePresenceWindowApi()
    window = PassivePresenceWindow(api)
    before = api.foreground()
    window.sync(_snapshot())
    hwnd = window.hwnd

    api.monitor = OperatorMonitor(
        (1920, -200, 4480, 1240),
        (1920, -160, 4480, 1200),
        144,
    )
    outcome = window.sync(_snapshot(PresencePhase.VERIFYING))

    assert outcome.changed and not outcome.created
    assert window.hwnd == hwnd
    assert api.kinds().count("create") == 1
    configured = [call for call in api.calls if call[0] == "configure"][-1]
    geometry = configured[3]
    assert geometry == PresenceGeometry(1920, -200, 2560, 1440, 15, 24, 144)
    assert api.foreground() == before


@pytest.mark.parametrize(
    "hidden",
    [
        _snapshot(authority=DesktopAuthority.RELEASED),
        _snapshot(estop_engaged=True),
        _snapshot(terminal_closed=True),
        _snapshot(preferences=PresencePreferences(enabled=False)),
    ],
)
def test_release_estop_terminal_and_disable_destroy_immediately(
    hidden: PresenceSnapshot,
) -> None:
    api = FakePresenceWindowApi()
    window = PassivePresenceWindow(api)
    window.sync(_snapshot(PresencePhase.EXECUTING))
    hwnd = window.hwnd

    result = window.sync(hidden)

    assert result.visible is False and result.changed is True
    assert window.hwnd is None
    assert ("destroy", hwnd) in api.calls
    # A repeated hidden update is idempotent and cannot resurrect the surface.
    assert window.sync(hidden).changed is False
    assert api.kinds().count("create") == 1


def test_capture_exclusion_failure_is_reported_without_becoming_a_secrecy_claim() -> None:
    api = FakePresenceWindowApi(capture_excluded=False)
    window = PassivePresenceWindow(api)

    result = window.sync(_snapshot())

    assert result.visible and not result.capture_excluded
    assert window.hwnd in api.alive


def test_no_phase_colour_collides_with_the_transparency_key() -> None:
    """A phase colour equal to the colour key would render as a hole.

    The halo has no alpha: `LWA_COLORKEY` removes one exact colour so the
    interior is transparent while the border stays opaque. A phase whose colour
    matched that key would be punched out of the border and would look exactly
    like the halo not being drawn -- the original `GDA-HUD-001` report.
    """

    from computer_use_agent.operator_visuals import (
        OperatorVisualRole,
        operator_visual,
    )
    from computer_use_agent.presence_window_win32 import (
        PRESENCE_TRANSPARENT_COLOR_KEY,
    )

    key = PRESENCE_TRANSPARENT_COLOR_KEY & 0xFFFFFF
    for role in OperatorVisualRole:
        assert operator_visual(role).color_rgb != key, f"{role.value} is the colour key"
    # The high-contrast projection substitutes white; it must not collide either.
    assert key != 0xFFFFFF


def test_a_scaled_display_yields_a_visibly_thicker_halo_than_the_unscaled_one() -> None:
    scaled = presence_geometry(
        OperatorMonitor((0, 0, 2560, 1440), (0, 0, 2560, 1400), 144)
    )
    unscaled = presence_geometry(
        OperatorMonitor((0, 0, 1920, 1080), (0, 0, 1920, 1040), 96)
    )

    assert scaled.border_px == 15
    assert unscaled.border_px == 10
    assert scaled.border_px > unscaled.border_px


@pytest.mark.parametrize(
    ("dpi", "border", "inset"),
    [(96, 10, 16), (144, 15, 24), (192, 20, 32), (768, 32, 48)],
)
def test_geometry_is_dpi_scaled_and_bounded(dpi: int, border: int, inset: int) -> None:
    geometry = presence_geometry(
        OperatorMonitor((-1920, 0, 0, 1080), (-1920, 0, 0, 1040), dpi)
    )

    assert geometry == PresenceGeometry(-1920, 0, 1920, 1080, border, inset, dpi)


def test_non_monitor_geometry_input_fails_closed() -> None:
    with pytest.raises(PresenceWindowError, match="PRESENCE_DISPLAY_BOUNDS_INVALID"):
        presence_geometry(object())  # type: ignore[arg-type]
