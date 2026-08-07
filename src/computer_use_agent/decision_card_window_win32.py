"""Fixed-geometry ctypes Win32 backend for the focus-taking Decision Card.

The surface is painted against the shared operator tokens rather than assembled
from system dialog controls, so it reads as one state of the same product as the
Presence and workflow Progress HUDs. Buttons stay real ``BUTTON`` controls, so
focus, tab order, and accessibility are unchanged; only their pixels are ours.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Literal

from computer_use_mcp.dpi import enable_dpi_awareness

from .operator_display import OperatorMonitor
from .operator_display_win32 import (
    configure_operator_monitor_apis,
    operator_monitor_for_window,
)
from .win32_dll import private_windll
from .operator_visuals import (
    OPERATOR_SURFACE,
    OPERATOR_TYPE_META,
    OPERATOR_TYPE_MICRO_LABEL,
    OPERATOR_TYPE_TITLE,
    OperatorTypeTier,
    OperatorVisualRole,
    operator_visual,
)
from .operator_accessibility import (
    OperatorAccessibilitySettings,
    Win32Palette,
    effective_text_dpi,
    layout_dpi,
    win32_palette,
)
from .operator_localization import OperatorLocale, operator_text

from .decision_card_window import DecisionCardButton

DecisionCardCorner = Literal[
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
]

_VALID_CORNERS = {
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
}

_WM_CLOSE = 0x0010
_WM_DESTROY = 0x0002
_WM_SIZE = 0x0005
_WM_KEYDOWN = 0x0100
_WM_COMMAND = 0x0111
_WM_TIMER = 0x0113
_WM_SETFONT = 0x0030
_WM_CTLCOLOREDIT = 0x0133
_WM_CTLCOLORSTATIC = 0x0138
_WM_CTLCOLORBTN = 0x0135
_WM_PAINT = 0x000F
_WM_ERASEBKGND = 0x0014
_WM_DRAWITEM = 0x002B
_TDM_CLICK_BUTTON = 0x0400 + 102
_BN_CLICKED = 0
_VK_ESCAPE = 0x1B
_VK_RETURN = 0x0D
_VK_TAB = 0x09
_VK_SHIFT = 0x10
_EVENT_OBJECT_NAMECHANGE = 0x800C
_OBJID_WINDOW = 0
_CHILDID_SELF = 0

_WS_CAPTION = 0x00C00000
_WS_SYSMENU = 0x00080000
_WS_CLIPCHILDREN = 0x02000000
_WS_CHILD = 0x40000000
_WS_VISIBLE = 0x10000000
_WS_TABSTOP = 0x00010000
_WS_VSCROLL = 0x00200000
_WS_EX_APPWINDOW = 0x00040000

#: One bounded decision has one exact compact and one exact expanded geometry,
#: so the frame offers no resize, maximize, or minimize. Dropping
#: ``WS_THICKFRAME`` and the min/max boxes is what keeps the reviewed layout the
#: layout an operator actually sees. The caption and system menu stay: closing
#: the card is a safe deny and must remain one obvious click.
_CARD_STYLE = _WS_CAPTION | _WS_SYSMENU | _WS_CLIPCHILDREN
_CARD_EX_STYLE = _WS_EX_APPWINDOW

_ES_MULTILINE = 0x0004
_ES_AUTOVSCROLL = 0x0040
_ES_READONLY = 0x0800
_BS_MULTILINE = 0x00002000
_BS_OWNERDRAW = 0x0000000B
_SS_LEFT = 0x00000000
_SS_NOPREFIX = 0x00000080

_ODS_SELECTED = 0x0001
_ODS_FOCUS = 0x0010

_DT_SINGLELINE = 0x0020
_DT_CENTER = 0x0001
_DT_VCENTER = 0x0004
_DT_LEFT = 0x0000
_DT_RIGHT = 0x0002
_DT_END_ELLIPSIS = 0x8000
_TRANSPARENT = 1

_SW_HIDE = 0
_SW_SHOWNORMAL = 1
_SW_RESTORE = 9
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040
_COLOR_WINDOW = 5
_DEFAULT_GUI_FONT = 17
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20

_FIRST_BUTTON_ID = 1001
_CONTENT_ID = 2001
_EVIDENCE_TOGGLE_ID = 2002
_HEADER_CONTROL_IDS = (2003, 2004, 2006, 2007)
_ACCENT_ID = 2005
_COUNTDOWN_ID = 2008
_DETAILS_LABEL_ID = 2009
_TIMER_ID = 1
_TIMER_INTERVAL_MS = 250

_COMPACT_CLIENT_WIDTH = 560
_COMPACT_CLIENT_HEIGHT = 270
_EXPANDED_CLIENT_WIDTH = 720
_EXPANDED_CLIENT_HEIGHT = 620
_CORNER_MARGIN = 20
_BASE_DPI = 96


def _colorref(rgb: int) -> int:
    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return red | (green << 8) | (blue << 16)


def _restore_if_minimized(user32, hwnd: wintypes.HWND) -> None:  # noqa: ANN001
    """Make a minimized window usable without changing any other placement."""

    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, _SW_RESTORE)


# COLORREF values use BGR byte order, so every shared RGB token is converted
# once here rather than being restated as a second hand-maintained palette.
_HUD_BACKGROUND = _colorref(OPERATOR_SURFACE.background_rgb)
_HUD_SURFACE = _colorref(OPERATOR_SURFACE.surface_rgb)
_HUD_TEXT = _colorref(OPERATOR_SURFACE.text_rgb)
_HUD_MUTED_TEXT = _colorref(OPERATOR_SURFACE.muted_text_rgb)
_HUD_HAIRLINE = _colorref(OPERATOR_SURFACE.hairline_rgb)

#: The header tiers, zipped against the exactly four instruction lines the
#: controller emits. Order is the shared HUD order: accent micro-label, the one
#: thing being decided, then the counts that qualify it.
_HEADER_TIERS: tuple[tuple[int, OperatorTypeTier, bool], ...] = (
    (0, OPERATOR_TYPE_MICRO_LABEL, True),
    (20, OPERATOR_TYPE_TITLE, False),
    (50, OPERATOR_TYPE_META, False),
    (72, OPERATOR_TYPE_META, False),
)

_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(
    _LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncUpdate", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class _DRAWITEMSTRUCT(ctypes.Structure):
    _fields_ = [
        ("CtlType", wintypes.UINT),
        ("CtlID", wintypes.UINT),
        ("itemID", wintypes.UINT),
        ("itemAction", wintypes.UINT),
        ("itemState", wintypes.UINT),
        ("hwndItem", wintypes.HWND),
        ("hDC", wintypes.HDC),
        ("rcItem", wintypes.RECT),
        ("itemData", ctypes.c_void_p),
    ]


def _loword(value: int) -> int:
    return value & 0xFFFF


def _hiword(value: int) -> int:
    return (value >> 16) & 0xFFFF


def _corner_origin(
    work_area: tuple[int, int, int, int],
    outer_size: tuple[int, int],
    corner: DecisionCardCorner,
    *,
    margin: int = _CORNER_MARGIN,
) -> tuple[int, int]:
    left, top, right, bottom = work_area
    width, height = outer_size
    x = left + margin
    y = top + margin
    if corner.endswith("right"):
        x = right - width - margin
    if corner.startswith("bottom"):
        y = bottom - height - margin
    return x, y


def _scaled_client_size(
    expanded: bool,
    dpi: int,
    *,
    text_scale_factor: float = 1.0,
) -> tuple[int, int]:
    """Return a 400%-safe client size with geometry capped for reflow."""

    geometry_dpi = layout_dpi(dpi, text_scale_factor)
    text_dpi = effective_text_dpi(dpi, text_scale_factor)
    width = _EXPANDED_CLIENT_WIDTH if expanded else _COMPACT_CLIENT_WIDTH
    height = _EXPANDED_CLIENT_HEIGHT if expanded else _COMPACT_CLIENT_HEIGHT
    client_width = max(1, round(width * geometry_dpi / _BASE_DPI))
    desired_height = max(1, round(height * geometry_dpi / _BASE_DPI))
    header_bottom = max(
        top + rect_height
        for (_left, top, _width, rect_height), _tier in _header_rects(
            client_width,
            dpi,
            text_scale_factor=text_scale_factor,
        ).values()
    )

    def scale(value: int) -> int:
        return max(1, round(value * geometry_dpi / _BASE_DPI))

    micro_height = max(
        scale(26),
        _tier_font_height(OPERATOR_TYPE_MICRO_LABEL, text_dpi) + scale(8),
    )
    button_height = max(
        scale(42),
        _tier_font_height(OPERATOR_TYPE_META, text_dpi) + scale(16),
    )
    gap = scale(8)
    buttons_height = 2 * button_height + gap
    required_height = header_bottom + gap + micro_height + gap + buttons_height + scale(20)
    if expanded:
        required_height += scale(128) + gap
    return (
        client_width,
        max(desired_height, required_height),
    )


def _toggle_label(
    expanded: bool,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> str:
    """Use one visible/UIA-safe label without symbol-encoding dependence."""

    return operator_text(locale, "hide_details" if expanded else "show_details")


#: Private handles for the measurement helper. It prototypes GDI calls too, and
#: it runs from tests, so it must not reach into the process-wide table either.
_MEASURE_GDI32 = private_windll("gdi32")
_MEASURE_USER32 = private_windll("user32")


def _tier_font_height(tier: OperatorTypeTier, dpi: int) -> int:
    """The exact ``CreateFontW`` height every tier resolves to at one DPI."""

    return -max(12, round(tier.points * dpi / 72))


def measure_tier_text_width(
    text: str,
    *,
    tier: OperatorTypeTier,
    dpi: int = _BASE_DPI,
) -> int:
    """Measure one tier's rendered width in pixels without showing a window.

    Uses a memory device context, so a fit check costs no desktop interaction
    and cannot disturb an operator. Windows-only, like the rest of this module.
    """

    gdi32 = _MEASURE_GDI32
    user32 = _MEASURE_USER32
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.GetTextExtentPoint32W.argtypes = [
        wintypes.HDC,
        wintypes.LPCWSTR,
        ctypes.c_int,
        ctypes.POINTER(wintypes.SIZE),
    ]
    gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
    # Handle-returning calls must be prototyped here, not inherited. On a
    # private library handle nothing else has declared them, and a default
    # c_int return truncates a 64-bit HDC or HGDIOBJ.
    gdi32.CreateFontW.restype = wintypes.HGDIOBJ
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    screen = user32.GetDC(None)
    hdc = gdi32.CreateCompatibleDC(screen)
    font = gdi32.CreateFontW(
        _tier_font_height(tier, dpi),
        0,
        0,
        0,
        tier.weight,
        0,
        0,
        0,
        1,
        0,
        0,
        5,
        0,
        "Segoe UI",
    )
    previous = gdi32.SelectObject(hdc, font) if font else None
    try:
        size = wintypes.SIZE()
        if not gdi32.GetTextExtentPoint32W(hdc, text, len(text), ctypes.byref(size)):
            raise OSError("DECISION_CARD_TEXT_EXTENT_FAILED")
        return int(size.cx)
    finally:
        if font:
            gdi32.SelectObject(hdc, previous)
            gdi32.DeleteObject(font)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(None, screen)


def _header_rects(
    client_width: int,
    dpi: int = _BASE_DPI,
    *,
    text_scale_factor: float = 1.0,
) -> dict[str, tuple[tuple[int, int, int, int], OperatorTypeTier]]:
    """Compute the painted header rectangles and the tier each one uses.

    Pure, so a text-fit check can measure real glyph extents against the exact
    rectangles the card paints into. Geometry alone was not enough: the boxes
    all fitted the client area while the title inside one of them was clipped.
    """

    geometry_dpi = layout_dpi(dpi, text_scale_factor)
    text_dpi = effective_text_dpi(dpi, text_scale_factor)

    def scale(value: int) -> int:
        return max(1, round(value * geometry_dpi / _BASE_DPI))

    margin = scale(20)
    countdown_width = scale(120)
    rects: dict[str, tuple[tuple[int, int, int, int], OperatorTypeTier]] = {}
    top = margin
    for index, (offset, tier, _is_accent) in enumerate(_HEADER_TIERS):
        # Only the micro-label shares its row with the countdown. Giving every
        # row that reserve clipped the one line that matters most: the action
        # being approved.
        right = client_width - margin
        if index == 0:
            right -= countdown_width
        height = max(
            scale(tier.points * 2),
            _tier_font_height(tier, text_dpi) + scale(4),
        )
        rects[f"line_{index}"] = (
            (margin, top, max(1, right - margin), height),
            tier,
        )
        top += height + scale(4)
    rects["countdown"] = (
        (
            max(0, client_width - margin - countdown_width),
            margin,
            countdown_width,
            rects["line_0"][0][3],
        ),
        OPERATOR_TYPE_MICRO_LABEL,
    )
    return rects


def _layout_rects(
    width: int,
    height: int,
    button_count: int,
    *,
    expanded: bool,
    dpi: int = _BASE_DPI,
    text_scale_factor: float = 1.0,
) -> dict[str, tuple[int, int, int, int]]:
    """Compute a fixed 2x2 compact grid and bounded expanded detail panes."""

    geometry_dpi = layout_dpi(dpi, text_scale_factor)
    text_dpi = effective_text_dpi(dpi, text_scale_factor)

    def scale(value: int) -> int:
        return max(1, round(value * geometry_dpi / _BASE_DPI))

    margin = scale(20)
    gap = scale(8)
    header_bottom = max(
        top + rect_height
        for (_left, top, _width, rect_height), _tier in _header_rects(
            width,
            dpi,
            text_scale_factor=text_scale_factor,
        ).values()
    )
    toggle_height = max(
        scale(26),
        _tier_font_height(OPERATOR_TYPE_MICRO_LABEL, text_dpi) + scale(8),
    )
    button_height = max(
        scale(42),
        _tier_font_height(OPERATOR_TYPE_META, text_dpi) + scale(16),
    )
    columns = 2
    rows = (button_count + columns - 1) // columns
    buttons_height = rows * button_height + max(0, rows - 1) * gap
    buttons_top = height - margin - buttons_height
    button_width = max(
        100,
        (width - 2 * margin - gap) // columns,
    )
    rects: dict[str, tuple[int, int, int, int]] = {
        "accent": (
            0,
            0,
            scale(4),
            height,
        ),
        "toggle": (
            margin,
            header_bottom + gap,
            min(scale(140), width - 2 * margin),
            toggle_height,
        ),
    }
    for index in range(button_count):
        row = index // columns
        column = index % columns
        rects[f"button_{index}"] = (
            margin + column * (button_width + gap),
            buttons_top + row * (button_height + gap),
            button_width,
            button_height,
        )
    if expanded:
        # One detail region, not two stacked scrollers. Nesting a second scroll
        # context inside a fixed card was the last structural difference from
        # the reference interfaces, and it was also what clipped text: a fixed
        # 55/45 split cut whichever section happened to be longer.
        details_top = rects["toggle"][1] + toggle_height + gap
        details_bottom = buttons_top - gap
        detail_region = (
            margin,
            details_top,
            width - 2 * margin,
            max(128, details_bottom - details_top),
        )
        details_label_height = max(
            scale(22),
            _tier_font_height(OPERATOR_TYPE_META, text_dpi) + scale(4),
        )
        rects["details_label"] = (
            detail_region[0],
            detail_region[1],
            detail_region[2],
            details_label_height,
        )
        rects["details"] = (
            detail_region[0],
            detail_region[1] + details_label_height,
            detail_region[2],
            max(1, detail_region[3] - details_label_height),
        )
    return rects


def _safe_default_control_id(id_to_option: dict[int, str]) -> int:
    """Require one exact deny option before native keyboard input is accepted."""

    safe_ids = [
        control_id
        for control_id, option_id in id_to_option.items()
        if option_id == "option_deny"
    ]
    if len(safe_ids) != 1:
        raise OSError("DECISION_CARD_SAFE_DEFAULT_REQUIRED")
    return safe_ids[0]


def _status_announcement_seconds(timeout_seconds: int) -> tuple[int, ...]:
    """Return bounded name-change milestones for one visible countdown."""

    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or not 5 <= timeout_seconds <= 3_600
    ):
        raise ValueError("DECISION_CARD_TIMEOUT_INVALID")
    return tuple(
        dict.fromkeys(
            value
            for value in (timeout_seconds, 60, 30, 10, 0)
            if value == timeout_seconds or value < timeout_seconds
        )
    )


class Win32DecisionCardWindowApi:
    """Show a timed, fixed-geometry Decision Card in one dark HUD window."""

    def __init__(
        self,
        *,
        corner: DecisionCardCorner = "bottom_right",
        accessibility: OperatorAccessibilitySettings | None = None,
        locale: OperatorLocale = OperatorLocale.EN_US,
    ) -> None:
        if corner not in _VALID_CORNERS:
            raise ValueError("decision card corner is invalid")
        if not isinstance(locale, OperatorLocale):
            raise ValueError("decision card locale is invalid")
        enable_dpi_awareness()
        self.corner = corner
        self.locale = locale
        self.accessibility = accessibility or OperatorAccessibilitySettings()
        if not isinstance(self.accessibility, OperatorAccessibilitySettings):
            raise ValueError("decision card accessibility settings are invalid")
        self._user32 = private_windll("user32")
        self._shcore = private_windll("shcore")
        self._kernel32 = private_windll("kernel32")
        self._gdi32 = private_windll("gdi32")
        self._dwmapi = private_windll("dwmapi")
        self._uxtheme = private_windll("uxtheme")
        configure_operator_monitor_apis(self._user32, self._shcore)
        self._configure_apis()

    def _configure_apis(self) -> None:
        user32 = self._user32
        kernel32 = self._kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetDpiForSystem.restype = wintypes.UINT
        user32.GetSysColor.argtypes = [ctypes.c_int]
        user32.GetSysColor.restype = wintypes.DWORD
        user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
        user32.GetDlgCtrlID.restype = ctypes.c_int
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsIconic.argtypes = [wintypes.HWND]
        user32.IsIconic.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.GetFocus.restype = wintypes.HWND
        user32.GetKeyState.argtypes = [ctypes.c_int]
        user32.GetKeyState.restype = ctypes.c_short
        user32.GetNextDlgTabItem.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            wintypes.BOOL,
        ]
        user32.GetNextDlgTabItem.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.UpdateWindow.restype = wintypes.BOOL
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = _LRESULT
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = _LRESULT
        # user32 is one process-global ctypes library object. Presence and
        # progress use layout-compatible WNDCLASSEXW definitions, so binding
        # this function to one module-private pointer type makes construction
        # order accidentally authoritative. Keep the ABI pointer opaque.
        user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.HWND,
            wintypes.HMENU,
            wintypes.HINSTANCE,
            ctypes.c_void_p,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.MoveWindow.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.BOOL,
        ]
        user32.MoveWindow.restype = wintypes.BOOL
        user32.GetClientRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.GetClientRect.restype = wintypes.BOOL
        user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        user32.SetWindowTextW.restype = wintypes.BOOL
        user32.SetTimer.argtypes = [
            wintypes.HWND,
            ctypes.c_size_t,
            wintypes.UINT,
            ctypes.c_void_p,
        ]
        user32.SetTimer.restype = ctypes.c_size_t
        user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        user32.KillTimer.restype = wintypes.BOOL
        user32.GetMessageW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL
        # The passive surfaces pump wintypes.MSG on other threads. Their layout
        # is the same, but ctypes pointer classes are nominally distinct.
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.IsDialogMessageW.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.IsDialogMessageW.restype = wintypes.BOOL
        user32.NotifyWinEvent.argtypes = [
            wintypes.DWORD,
            wintypes.HWND,
            wintypes.LONG,
            wintypes.LONG,
        ]
        user32.AdjustWindowRectEx.argtypes = [
            ctypes.POINTER(wintypes.RECT),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        user32.AdjustWindowRectEx.restype = wintypes.BOOL
        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadCursorW.restype = wintypes.HANDLE
        user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.BeginPaint.restype = wintypes.HDC
        user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.EndPaint.restype = wintypes.BOOL
        user32.FillRect.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            wintypes.HBRUSH,
        ]
        user32.FillRect.restype = ctypes.c_int
        user32.FrameRect.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            wintypes.HBRUSH,
        ]
        user32.FrameRect.restype = ctypes.c_int
        user32.DrawTextW.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.UINT,
        ]
        user32.DrawTextW.restype = ctypes.c_int
        user32.InvalidateRect.argtypes = [
            wintypes.HWND,
            ctypes.c_void_p,
            wintypes.BOOL,
        ]
        user32.InvalidateRect.restype = wintypes.BOOL
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self._gdi32.GetStockObject.argtypes = [ctypes.c_int]
        self._gdi32.GetStockObject.restype = wintypes.HGDIOBJ
        self._gdi32.CreateFontW.argtypes = [
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPCWSTR,
        ]
        self._gdi32.CreateFontW.restype = wintypes.HGDIOBJ
        self._gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
        self._gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.SetBkColor.argtypes = [wintypes.HDC, wintypes.DWORD]
        self._gdi32.SetBkColor.restype = wintypes.DWORD
        self._gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
        self._gdi32.SetTextColor.restype = wintypes.DWORD
        self._gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        self._gdi32.SetBkMode.restype = ctypes.c_int
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._uxtheme.SetWindowTheme.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
        ]
        self._uxtheme.SetWindowTheme.restype = ctypes.c_long
        self._dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        self._dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

    def _draw_text(
        self,
        hdc: wintypes.HDC,
        rectangle: wintypes.RECT,
        text: str,
        *,
        tier: OperatorTypeTier,
        color: int,
        dpi: int,
        format_flags: int,
    ) -> None:
        """Draw one shared-tier line, creating and releasing its own font.

        Mirrors the workflow Progress HUD's text helper so both surfaces
        resolve the same tier to the same pixels at the same DPI.
        """

        if not text:
            return
        font = self._gdi32.CreateFontW(
            -max(12, round(tier.points * dpi / 72)),
            0,
            0,
            0,
            tier.weight,
            0,
            0,
            0,
            1,
            0,
            0,
            5,
            0,
            "Segoe UI",
        )
        previous = self._gdi32.SelectObject(hdc, font) if font else None
        try:
            self._gdi32.SetBkMode(hdc, _TRANSPARENT)
            self._gdi32.SetTextColor(hdc, color)
            self._user32.DrawTextW(
                hdc,
                text,
                -1,
                ctypes.byref(rectangle),
                format_flags,
            )
        finally:
            if font:
                self._gdi32.SelectObject(hdc, previous)
                self._gdi32.DeleteObject(font)

    def _control_label(self, hwnd: wintypes.HWND) -> str:
        """Read one owner-drawn control's caption.

        The length must come from ``GetWindowTextLengthW``. ``GetWindowTextW``
        with a null buffer and ``nMaxCount=0`` copies nothing and returns 0, so
        sizing the buffer from it paints every control with an empty label.
        """

        length = int(self._user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        self._user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value

    def _paint_header(
        self,
        hdc: wintypes.HDC,
        client: wintypes.RECT,
        *,
        lines: tuple[str, ...],
        countdown: str,
        accent_color: int,
        dpi: int,
    ) -> None:
        """Paint the accent micro-label, action title, and muted qualifiers."""

        def scaled(value: int) -> int:
            return max(1, round(value * dpi / _BASE_DPI))

        rects = _header_rects(client.right, dpi)
        for index, ((_offset, tier, is_accent), text) in enumerate(
            zip(_HEADER_TIERS, lines, strict=True)
        ):
            (left, top, width, height), _tier = rects[f"line_{index}"]
            self._draw_text(
                hdc,
                wintypes.RECT(left, top, left + width, top + height),
                text,
                tier=tier,
                color=accent_color if is_accent else (
                    _HUD_TEXT if tier is OPERATOR_TYPE_TITLE else _HUD_MUTED_TEXT
                ),
                dpi=dpi,
                # A fixed card cannot grow, so an over-long reviewed label must
                # degrade to an ellipsis rather than be sliced mid-glyph.
                format_flags=(
                    _DT_SINGLELINE | _DT_LEFT | _DT_VCENTER | _DT_END_ELLIPSIS
                ),
            )
        (left, top, width, height), countdown_tier = rects["countdown"]
        self._draw_text(
            hdc,
            wintypes.RECT(left, top, left + width, top + height),
            countdown,
            tier=countdown_tier,
            color=_HUD_MUTED_TEXT,
            dpi=dpi,
            format_flags=_DT_SINGLELINE | _DT_RIGHT | _DT_VCENTER,
        )

    def _draw_item(
        self,
        item: _DRAWITEMSTRUCT,
        *,
        background_brush: wintypes.HBRUSH,
        surface_brush: wintypes.HBRUSH,
        hairline_brush: wintypes.HBRUSH,
        accent_brush: wintypes.HBRUSH,
        accent_color: int,
        palette: Win32Palette,
        is_toggle: bool,
        is_safe_default: bool,
        dpi: int,
    ) -> None:
        """Paint one flat HUD control instead of a raised system push button.

        The control stays a real ``BUTTON``, so tab order, the default-button
        rule, mnemonics, and accessibility are untouched; only the pixels are
        ours.
        """

        label = self._control_label(item.hwndItem)
        focused = bool(item.itemState & (_ODS_FOCUS | _ODS_SELECTED))
        if is_toggle:
            # Owner drawing owns the whole rectangle including its background.
            # Text alone leaves the previous label underneath, so the affordance
            # renders SHOW and HIDE on top of each other after one toggle.
            self._user32.FillRect(
                item.hDC, ctypes.byref(item.rcItem), background_brush
            )
            # A quiet text affordance, matching the Progress HUD's
            # SHOW/HIDE STEPS control rather than a framed dialog button.
            self._draw_text(
                item.hDC,
                item.rcItem,
                label,
                tier=OPERATOR_TYPE_MICRO_LABEL,
                color=accent_color if focused else palette.muted_text,
                dpi=dpi,
                format_flags=_DT_SINGLELINE | _DT_LEFT | _DT_VCENTER,
            )
            return
        self._user32.FillRect(item.hDC, ctypes.byref(item.rcItem), surface_brush)
        self._user32.FrameRect(
            item.hDC,
            ctypes.byref(item.rcItem),
            accent_brush if focused else hairline_brush,
        )
        if is_safe_default and not focused:
            # The quiet safe-default hint. It is deliberately a second hairline
            # rather than a filled primary: the consequential option on an
            # approval card must not be the visually loudest one.
            inner = wintypes.RECT(
                item.rcItem.left + 2,
                item.rcItem.top + 2,
                item.rcItem.right - 2,
                item.rcItem.bottom - 2,
            )
            self._user32.FrameRect(item.hDC, ctypes.byref(inner), hairline_brush)
        self._draw_text(
            item.hDC,
            item.rcItem,
            label,
            tier=OPERATOR_TYPE_META,
            color=palette.text,
            dpi=dpi,
            format_flags=_DT_SINGLELINE | _DT_CENTER | _DT_VCENTER,
        )

    def _window_rect(
        self,
        monitor: OperatorMonitor,
        style: int,
        ex_style: int,
        client_size: tuple[int, int],
    ) -> tuple[int, int, int, int]:
        rectangle = wintypes.RECT(0, 0, client_size[0], client_size[1])
        if not self._user32.AdjustWindowRectEx(
            ctypes.byref(rectangle), style, False, ex_style
        ):
            raise OSError("DECISION_CARD_WINDOW_RECT_FAILED")
        width = rectangle.right - rectangle.left
        height = rectangle.bottom - rectangle.top
        work_left, work_top, work_right, work_bottom = monitor.work_area
        work_width = work_right - work_left
        work_height = work_bottom - work_top
        width = min(width, max(1, work_width - 2 * _CORNER_MARGIN))
        height = min(height, max(1, work_height - 2 * _CORNER_MARGIN))
        left, top = _corner_origin(
            (
                work_left,
                work_top,
                work_right,
                work_bottom,
            ),
            (width, height),
            self.corner,
        )
        return left, top, width, height

    def _bring_to_foreground(
        self,
        hwnd: wintypes.HWND,
        foreground_before: wintypes.HWND,
    ) -> None:
        foreground_process = wintypes.DWORD()
        foreground_thread = 0
        if foreground_before:
            foreground_thread = int(
                self._user32.GetWindowThreadProcessId(
                    foreground_before, ctypes.byref(foreground_process)
                )
            )
        current_thread = int(self._kernel32.GetCurrentThreadId())
        attached = bool(
            foreground_thread
            and foreground_thread != current_thread
            and self._user32.AttachThreadInput(
                current_thread, foreground_thread, True
            )
        )
        try:
            _restore_if_minimized(self._user32, hwnd)
            self._user32.SetWindowPos(
                hwnd,
                wintypes.HWND(0),
                0,
                0,
                0,
                0,
                _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
            )
            self._user32.BringWindowToTop(hwnd)
            self._user32.SetForegroundWindow(hwnd)
            self._user32.SetFocus(hwnd)
        finally:
            if attached:
                self._user32.AttachThreadInput(
                    current_thread, foreground_thread, False
                )

    def choose(
        self,
        *,
        title: str,
        instruction: str,
        content: str,
        expanded_information: str,
        buttons: tuple[DecisionCardButton, ...],
        timeout_seconds: int,
    ) -> str | None:
        if not 2 <= len(buttons) <= 4:
            raise OSError("DECISION_CARD_NATIVE_REQUIRES_TWO_TO_FOUR_OPTIONS")
        foreground_before = self._user32.GetForegroundWindow()
        selected_monitor = operator_monitor_for_window(
            self._user32,
            int(foreground_before or 0),
            shcore=self._shcore,
        )
        instance = self._kernel32.GetModuleHandleW(None)
        class_name = f"GuardedDesktopDecisionCard_{id(self):x}"
        selected: list[str | None] = [None]
        controls: dict[str, wintypes.HWND] = {}
        expanded = [False]
        compact_window_rect: list[tuple[int, int, int, int] | None] = [None]
        deadline = time.monotonic() + timeout_seconds
        dpi = selected_monitor.dpi
        text_scale_factor = self.accessibility.text_scale_factor
        text_dpi = effective_text_dpi(dpi, text_scale_factor)
        attention = operator_visual(OperatorVisualRole.NEEDS_INPUT)
        palette = win32_palette(
            self._user32,
            high_contrast=self.accessibility.high_contrast,
            accent_rgb=attention.color_rgb,
        )
        background_brush = self._gdi32.CreateSolidBrush(palette.background)
        surface_brush = self._gdi32.CreateSolidBrush(palette.surface)
        hairline_brush = self._gdi32.CreateSolidBrush(palette.hairline)
        accent_color = palette.accent
        accent_brush = self._gdi32.CreateSolidBrush(accent_color)
        header_lines = tuple(instruction.split("\n"))
        if len(header_lines) != len(_HEADER_TIERS):
            raise ValueError("DECISION_CARD_HEADER_TIERS_INVALID")
        countdown = [
            operator_text(self.locale, "countdown", seconds=timeout_seconds)
        ]
        id_to_option = {
            _FIRST_BUTTON_ID + index: button.option_id
            for index, button in enumerate(buttons)
        }
        safe_default_id = _safe_default_control_id(id_to_option)
        safe_default_ids = {safe_default_id}
        safe_default_name = f"button_{safe_default_id - _FIRST_BUTTON_ID}"
        announcement_seconds = frozenset(
            _status_announcement_seconds(timeout_seconds)
        )
        announced_seconds: set[int] = set()

        def move(name: str, x: int, y: int, width: int, height: int) -> None:
            handle = controls.get(name)
            if handle:
                self._user32.MoveWindow(
                    handle,
                    x,
                    y,
                    max(1, width),
                    max(1, height),
                    True,
                )

        def layout(width: int, height: int) -> None:
            rects = _layout_rects(
                width,
                height,
                len(buttons),
                expanded=expanded[0],
                dpi=dpi,
                text_scale_factor=text_scale_factor,
            )
            for name, rectangle in rects.items():
                move(name, *rectangle)
            header_rects = _header_rects(
                width,
                dpi,
                text_scale_factor=text_scale_factor,
            )
            for index in range(len(_HEADER_TIERS)):
                move(f"header_{index}", *header_rects[f"line_{index}"][0])
            move("countdown", *header_rects["countdown"][0])

        def resize_for_state(hwnd: wintypes.HWND) -> None:
            if not expanded[0] and compact_window_rect[0] is not None:
                left, top, width, height = compact_window_rect[0]
            else:
                left, top, width, height = self._window_rect(
                    selected_monitor,
                    _CARD_STYLE,
                    _CARD_EX_STYLE,
                    _scaled_client_size(
                        expanded[0],
                        dpi,
                        text_scale_factor=text_scale_factor,
                    ),
                )
            self._user32.SetWindowPos(
                hwnd,
                wintypes.HWND(0),
                left,
                top,
                width,
                height,
                _SWP_SHOWWINDOW,
            )

        @_WNDPROC
        def window_proc(hwnd, message, wparam, lparam):  # noqa: ANN001
            if message == _WM_SIZE:
                layout(_loword(int(lparam)), _hiword(int(lparam)))
                return 0
            if message == _WM_ERASEBKGND:
                # WM_PAINT fills the whole client area, so erasing separately
                # would only flicker.
                return 1
            if message == _WM_PAINT:
                paint = _PAINTSTRUCT()
                hdc = self._user32.BeginPaint(hwnd, ctypes.byref(paint))
                try:
                    client = wintypes.RECT()
                    self._user32.GetClientRect(hwnd, ctypes.byref(client))
                    self._user32.FillRect(
                        hdc, ctypes.byref(client), background_brush
                    )
                    if expanded[0]:
                        # Bound the detail region with a hairline. Without an
                        # edge the elevated surface and the scrollbar inside it
                        # read as part of the card, which is what the sunken
                        # 3D bevel used to communicate.
                        left, top, width, height = _layout_rects(
                            client.right,
                            client.bottom,
                            len(buttons),
                            expanded=True,
                            dpi=dpi,
                            text_scale_factor=text_scale_factor,
                        )["details"]
                        self._user32.FrameRect(
                            hdc,
                            ctypes.byref(
                                wintypes.RECT(
                                    left - 1,
                                    top - 1,
                                    left + width + 1,
                                    top + height + 1,
                                )
                            ),
                            hairline_brush,
                        )
                finally:
                    self._user32.EndPaint(hwnd, ctypes.byref(paint))
                return 0
            if message == _WM_DRAWITEM:
                item = ctypes.cast(
                    lparam, ctypes.POINTER(_DRAWITEMSTRUCT)
                ).contents
                self._draw_item(
                    item,
                    background_brush=background_brush,
                    surface_brush=surface_brush,
                    hairline_brush=hairline_brush,
                    accent_brush=accent_brush,
                    accent_color=accent_color,
                    palette=palette,
                    is_toggle=int(item.CtlID) == _EVIDENCE_TOGGLE_ID,
                    is_safe_default=int(item.CtlID) in safe_default_ids,
                    dpi=dpi,
                )
                return 1
            if message == _WM_KEYDOWN and int(wparam) == _VK_ESCAPE:
                # Escape is always a safe rejection. It never selects a
                # positive option and therefore cannot dispatch an action.
                self._user32.DestroyWindow(hwnd)
                return 0
            if message == _WM_COMMAND:
                command_id = _loword(int(wparam))
                notification = _hiword(int(wparam))
                if notification == _BN_CLICKED and command_id in id_to_option:
                    selected[0] = id_to_option[command_id]
                    self._user32.DestroyWindow(hwnd)
                    return 0
                if (
                    notification == _BN_CLICKED
                    and command_id == _EVIDENCE_TOGGLE_ID
                ):
                    expanded[0] = not expanded[0]
                    self._user32.SetWindowTextW(
                        controls["toggle"],
                        _toggle_label(expanded[0], self.locale),
                    )
                    self._user32.ShowWindow(
                        controls["details"],
                        _SW_SHOWNORMAL if expanded[0] else _SW_HIDE,
                    )
                    self._user32.ShowWindow(
                        controls["details_label"],
                        _SW_SHOWNORMAL if expanded[0] else _SW_HIDE,
                    )
                    resize_for_state(hwnd)
                    rectangle = wintypes.RECT()
                    self._user32.GetClientRect(hwnd, ctypes.byref(rectangle))
                    layout(rectangle.right, rectangle.bottom)
                    return 0
            if message == _TDM_CLICK_BUTTON:
                command_id = int(wparam)
                if command_id in id_to_option:
                    selected[0] = id_to_option[command_id]
                self._user32.DestroyWindow(hwnd)
                return 0
            if message == _WM_TIMER and int(wparam) == _TIMER_ID:
                remaining = max(0, int(deadline - time.monotonic() + 0.999))
                next_countdown = operator_text(
                    self.locale,
                    "countdown",
                    seconds=remaining,
                )
                countdown_control = controls.get("countdown")
                if next_countdown != countdown[0]:
                    countdown[0] = next_countdown
                    if countdown_control:
                        self._user32.SetWindowTextW(
                            countdown_control,
                            countdown[0],
                        )
                if (
                    remaining in announcement_seconds
                    and remaining not in announced_seconds
                ):
                    announced_seconds.add(remaining)
                    if countdown_control:
                        self._user32.NotifyWinEvent(
                            _EVENT_OBJECT_NAMECHANGE,
                            countdown_control,
                            _OBJID_WINDOW,
                            _CHILDID_SELF,
                        )
                if remaining <= 0:
                    self._user32.DestroyWindow(hwnd)
                return 0
            if message == _WM_CLOSE:
                self._user32.DestroyWindow(hwnd)
                return 0
            if message in {
                _WM_CTLCOLORSTATIC,
                _WM_CTLCOLOREDIT,
                _WM_CTLCOLORBTN,
            }:
                control_id = self._user32.GetDlgCtrlID(wintypes.HWND(lparam))
                if control_id == _ACCENT_ID:
                    return int(
                        ctypes.cast(accent_brush, ctypes.c_void_p).value or 0
                    )
                if control_id == _HEADER_CONTROL_IDS[0]:
                    text_color = palette.accent
                elif control_id in {
                    _HEADER_CONTROL_IDS[2],
                    _HEADER_CONTROL_IDS[3],
                    _COUNTDOWN_ID,
                }:
                    text_color = palette.muted_text
                else:
                    text_color = palette.text
                self._gdi32.SetTextColor(wintypes.HDC(wparam), text_color)
                self._gdi32.SetBkColor(
                    wintypes.HDC(wparam),
                    palette.surface
                    if message == _WM_CTLCOLOREDIT
                    else palette.background,
                )
                if message == _WM_CTLCOLORSTATIC:
                    self._gdi32.SetBkMode(wintypes.HDC(wparam), _TRANSPARENT)
                brush = (
                    surface_brush
                    if message == _WM_CTLCOLOREDIT
                    else background_brush
                )
                return int(ctypes.cast(brush, ctypes.c_void_p).value or 0)
            if message == _WM_DESTROY:
                self._user32.KillTimer(hwnd, _TIMER_ID)
                self._user32.PostQuitMessage(0)
                return 0
            return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

        cursor = self._user32.LoadCursorW(None, wintypes.LPCWSTR(32512))
        window_class = _WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(window_class)
        window_class.lpfnWndProc = window_proc
        window_class.hInstance = instance
        window_class.hCursor = cursor
        window_class.hbrBackground = background_brush
        window_class.lpszClassName = class_name
        if not self._user32.RegisterClassExW(ctypes.byref(window_class)):
            raise OSError("DECISION_CARD_WINDOW_CLASS_FAILED")

        hwnd = None
        font = None
        owns_font = False
        owned_header_fonts: list[wintypes.HGDIOBJ] = []
        try:
            style = _CARD_STYLE
            ex_style = _CARD_EX_STYLE
            x, y, width, height = self._window_rect(
                selected_monitor,
                style,
                ex_style,
                _scaled_client_size(
                    False,
                    dpi,
                    text_scale_factor=text_scale_factor,
                ),
            )
            hwnd = self._user32.CreateWindowExW(
                ex_style,
                class_name,
                title,
                style,
                x,
                y,
                width,
                height,
                None,
                None,
                instance,
                None,
            )
            if not hwnd:
                raise OSError("DECISION_CARD_WINDOW_CREATE_FAILED")
            compact_window_rect[0] = (x, y, width, height)
            dark_mode = wintypes.BOOL(not self.accessibility.high_contrast)
            self._dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(dark_mode),
                ctypes.sizeof(dark_mode),
            )

            font = self._gdi32.CreateFontW(
                -max(13, round(10 * text_dpi / 72)),
                0,
                0,
                0,
                400,
                0,
                0,
                0,
                1,
                0,
                0,
                5,
                0,
                "Segoe UI",
            )
            if not font:
                font = self._gdi32.GetStockObject(_DEFAULT_GUI_FONT)
            owns_font = font != self._gdi32.GetStockObject(_DEFAULT_GUI_FONT)

            def create_control(
                name: str,
                class_text: str,
                text: str,
                control_style: int,
                control_id: int,
                *,
                ex: int = 0,
                visible: bool = True,
                control_font: wintypes.HGDIOBJ | None = None,
            ) -> wintypes.HWND:
                rendered_text = (
                    text.replace("\n", "\r\n")
                    if class_text == "EDIT"
                    else text
                )
                handle = self._user32.CreateWindowExW(
                    ex,
                    class_text,
                    rendered_text,
                    _WS_CHILD
                    | (_WS_VISIBLE if visible else 0)
                    | control_style,
                    0,
                    0,
                    1,
                    1,
                    hwnd,
                    wintypes.HMENU(control_id),
                    instance,
                    None,
                )
                if not handle:
                    raise OSError("DECISION_CARD_CONTROL_CREATE_FAILED")
                controls[name] = handle
                self._user32.SendMessageW(
                    handle,
                    _WM_SETFONT,
                    control_font or font,
                    1,
                )
                self._uxtheme.SetWindowTheme(
                    handle,
                    "" if self.accessibility.high_contrast else "DarkMode_Explorer",
                    None,
                )
                return handle

            def create_tier_font(tier: OperatorTypeTier) -> wintypes.HGDIOBJ:
                handle = self._gdi32.CreateFontW(
                    _tier_font_height(tier, text_dpi),
                    0,
                    0,
                    0,
                    tier.weight,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    5,
                    0,
                    "Segoe UI",
                )
                if handle:
                    owned_header_fonts.append(handle)
                    return handle
                return font

            create_control(
                "accent",
                "STATIC",
                "",
                0,
                _ACCENT_ID,
            )
            # Standard STATIC controls make every Host-owned header line a UIA
            # Text element. They remain non-focusable and carry no authority.
            for index, ((_offset, tier, _accent), line) in enumerate(
                zip(_HEADER_TIERS, header_lines, strict=True)
            ):
                create_control(
                    f"header_{index}",
                    "STATIC",
                    line,
                    _SS_LEFT | _SS_NOPREFIX,
                    _HEADER_CONTROL_IDS[index],
                    control_font=create_tier_font(tier),
                )
            create_control(
                "countdown",
                "STATIC",
                countdown[0],
                _SS_LEFT | _SS_NOPREFIX,
                _COUNTDOWN_ID,
                control_font=create_tier_font(OPERATOR_TYPE_MICRO_LABEL),
            )
            create_control(
                "toggle",
                "BUTTON",
                _toggle_label(False, self.locale),
                _BS_OWNERDRAW | _WS_TABSTOP,
                _EVIDENCE_TOGGLE_ID,
            )
            create_control(
                "details_label",
                "STATIC",
                operator_text(self.locale, "decision_details"),
                _SS_LEFT | _SS_NOPREFIX,
                _DETAILS_LABEL_ID,
                visible=False,
                control_font=create_tier_font(OPERATOR_TYPE_META),
            )
            create_control(
                "details",
                "EDIT",
                f"{content}\n\n{expanded_information}",
                _ES_MULTILINE
                | _ES_AUTOVSCROLL
                | _ES_READONLY
                | _WS_VSCROLL
                | _WS_TABSTOP,
                _CONTENT_ID,
                visible=False,
            )
            for index, button in enumerate(buttons):
                # ``BS_*`` type styles share one 4-bit field, so an owner-drawn
                # button cannot also carry ``BS_DEFPUSHBUTTON``. That style was
                # safe-default hint is painted explicitly below, and it stays
                # on deny: emphasis must never migrate to the approving option.
                create_control(
                    f"button_{index}",
                    "BUTTON",
                    button.label,
                    _BS_OWNERDRAW | _BS_MULTILINE | _WS_TABSTOP,
                    _FIRST_BUTTON_ID + index,
                )

            client = wintypes.RECT()
            self._user32.GetClientRect(hwnd, ctypes.byref(client))
            layout(client.right, client.bottom)
            if not self._user32.SetTimer(
                hwnd, _TIMER_ID, _TIMER_INTERVAL_MS, None
            ):
                raise OSError("DECISION_CARD_TIMER_FAILED")
            self._user32.ShowWindow(hwnd, _SW_SHOWNORMAL)
            self._user32.UpdateWindow(hwnd)
            self._bring_to_foreground(hwnd, foreground_before)
            self._user32.SetFocus(controls[safe_default_name])

            message = _MSG()
            while True:
                result = int(
                    self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                )
                if result == -1:
                    raise OSError("DECISION_CARD_MESSAGE_LOOP_FAILED")
                if result == 0:
                    break
                if (
                    message.message == _WM_KEYDOWN
                    and int(message.wParam) == _VK_ESCAPE
                ):
                    # Child edit/button controls receive keyboard messages
                    # directly, so enforce the same safe exit at the pump.
                    self._user32.DestroyWindow(hwnd)
                    continue
                if (
                    message.message == _WM_KEYDOWN
                    and int(message.wParam) == _VK_RETURN
                ):
                    focused = self._user32.GetFocus()
                    focused_id = (
                        int(self._user32.GetDlgCtrlID(focused)) if focused else 0
                    )
                    if focused_id in id_to_option or focused_id == _EVIDENCE_TOGGLE_ID:
                        # Owner-drawn buttons cannot also carry the ordinary
                        # default-push type. Enter therefore activates only the
                        # already-focused known BUTTON; it never invents a
                        # default approval from the top-level or details pane.
                        self._user32.SendMessageW(
                            hwnd,
                            _WM_COMMAND,
                            focused_id,
                            int(focused or 0),
                        )
                        continue
                if (
                    message.message == _WM_KEYDOWN
                    and int(message.wParam) == _VK_TAB
                    and self._user32.GetFocus() == controls.get("details")
                ):
                    previous = bool(
                        int(self._user32.GetKeyState(_VK_SHIFT)) & 0x8000
                    )
                    next_control = self._user32.GetNextDlgTabItem(
                        hwnd,
                        controls["details"],
                        previous,
                    )
                    if next_control:
                        self._user32.SetFocus(next_control)
                    continue
                if self._user32.IsDialogMessageW(hwnd, ctypes.byref(message)):
                    # IsDialogMessage already translates and dispatches Tab,
                    # Shift+Tab, arrows, Space, and Enter for native controls.
                    continue
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if hwnd and self._user32.IsWindow(hwnd):
                self._user32.DestroyWindow(hwnd)
            self._user32.UnregisterClassW(class_name, instance)
            if surface_brush:
                self._gdi32.DeleteObject(surface_brush)
            if accent_brush:
                self._gdi32.DeleteObject(accent_brush)
            if hairline_brush:
                self._gdi32.DeleteObject(hairline_brush)
            if background_brush:
                self._gdi32.DeleteObject(background_brush)
            if owns_font and font:
                self._gdi32.DeleteObject(font)
            for header_font in owned_header_fonts:
                self._gdi32.DeleteObject(header_font)
            if foreground_before and self._user32.IsWindow(foreground_before):
                foreground_after = self._user32.GetForegroundWindow()
                self._bring_to_foreground(
                    foreground_before,
                    foreground_after,
                )
        return selected[0]


__all__ = ["DecisionCardCorner", "Win32DecisionCardWindowApi"]
