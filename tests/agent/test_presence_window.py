from __future__ import annotations

from collections.abc import Sequence

import pytest

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
    DisplayBounds,
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
        self.bounds = DisplayBounds(0, 0, 1920, 1080, 96)
        self.capture_excluded = capture_excluded
        self.calls: list[tuple] = []
        self._foreground = 4242
        self._next = 100
        self.alive: set[int] = set()

    def display_bounds(self) -> DisplayBounds:
        self.calls.append(("display_bounds", self.bounds))
        return self.bounds

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
        "display_bounds",
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

    api.bounds = DisplayBounds(0, 0, 2560, 1440, 144)
    outcome = window.sync(_snapshot(PresencePhase.VERIFYING))

    assert outcome.changed and not outcome.created
    assert window.hwnd == hwnd
    assert api.kinds().count("create") == 1
    configured = [call for call in api.calls if call[0] == "configure"][-1]
    geometry = configured[3]
    assert geometry == PresenceGeometry(0, 0, 2560, 1440, 15, 24)
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


class _FakeUser32:
    """Mimic the Win32 DPI APIs, including the one that lies.

    ``GetDpiForWindow(GetDesktopWindow())`` reports 96 on a scaled display,
    because the desktop window is not per-monitor DPI aware.
    """

    def __init__(self, *, system_dpi: int | None, window_dpi: int = 96) -> None:
        self._window_dpi = window_dpi
        if system_dpi is not None:
            self.GetDpiForSystem = lambda: system_dpi  # noqa: N815

    def GetDesktopWindow(self) -> int:  # noqa: N802
        return 65548

    def GetDpiForWindow(self, _hwnd: int) -> int:  # noqa: N802
        return self._window_dpi

    def GetSystemMetrics(self, index: int) -> int:  # noqa: N802
        return 2560 if index == 0 else 1600


def _bounds_with(user32: _FakeUser32) -> DisplayBounds:
    from computer_use_agent.presence_window_win32 import Win32PresenceWindowApi

    api = Win32PresenceWindowApi.__new__(Win32PresenceWindowApi)
    api._user32 = user32  # type: ignore[attr-defined]
    return api.display_bounds()


def test_display_bounds_prefers_the_dpi_source_that_is_not_always_96() -> None:
    """The halo must scale by the primary display's real DPI.

    Reading `GetDpiForWindow(GetDesktopWindow())` pinned the halo to 96 on a
    150% display, so the border rendered at 10px where the contract asks for
    15px. That is the concrete reason a full-screen halo was reported as not
    visible during a live run.
    """

    assert _bounds_with(_FakeUser32(system_dpi=144, window_dpi=96)).dpi == 144
    # Falling back is still better than 96, and a zero must not be trusted.
    assert _bounds_with(_FakeUser32(system_dpi=None, window_dpi=120)).dpi == 120
    assert _bounds_with(_FakeUser32(system_dpi=0, window_dpi=120)).dpi == 120
    assert _bounds_with(_FakeUser32(system_dpi=None, window_dpi=0)).dpi == 96


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
    scaled = presence_geometry(_bounds_with(_FakeUser32(system_dpi=144)))
    unscaled = presence_geometry(_bounds_with(_FakeUser32(system_dpi=96)))

    assert scaled.border_px == 15
    assert unscaled.border_px == 10
    assert scaled.border_px > unscaled.border_px


@pytest.mark.parametrize(
    ("dpi", "border", "inset"),
    [(96, 10, 16), (144, 15, 24), (192, 20, 32), (768, 32, 48)],
)
def test_geometry_is_dpi_scaled_and_bounded(dpi: int, border: int, inset: int) -> None:
    geometry = presence_geometry(DisplayBounds(-1920, 0, 0, 1080, dpi))

    assert geometry == PresenceGeometry(-1920, 0, 1920, 1080, border, inset)


@pytest.mark.parametrize(
    "bounds",
    [
        (0, 0, 0, 10, 96),
        (0, 0, 10, 0, 96),
        (0, 0, 10, 10, 0),
        (0, 0, 10, 10, True),
    ],
)
def test_invalid_display_bounds_fail_closed(bounds: Sequence[object]) -> None:
    with pytest.raises(PresenceWindowError, match="PRESENCE_DISPLAY_BOUNDS_INVALID"):
        DisplayBounds(*bounds)  # type: ignore[arg-type]
