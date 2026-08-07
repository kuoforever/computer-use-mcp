"""Real Win32 backend for the passive progress window — ctypes only.

This is the concrete :class:`~computer_use_agent.progress_window.ProgressWindowApi`
used on a live desktop. It is deliberately kept out of the controller module so
the pure controller and its tests never import ctypes or touch a real window;
only the operator-approved smoke and an actual desktop session load this.

The adapter's whole job is to honour the non-activating contract in native
calls: create with ``WS_EX_NOACTIVATE``, show with ``SW_SHOWNOACTIVATE``, and
reposition with ``SWP_NOACTIVATE``. It never calls ``SetForegroundWindow``,
``SetFocus``, ``SetActiveWindow``, or ``BringWindowToTop`` — the same absence the
controller's interface already guarantees, now upheld at the syscall layer.
"""
from __future__ import annotations

import ctypes
from collections.abc import Callable, Sequence
from ctypes import wintypes

from computer_use_mcp.dpi import enable_dpi_awareness

from .win32_dll import private_windll
from .operator_visuals import (
    OPERATOR_SURFACE,
    OPERATOR_WEIGHT_NORMAL,
    OPERATOR_WEIGHT_SEMIBOLD,
)
from .operator_accessibility import (
    OperatorAccessibilitySettings,
    Win32Palette,
    effective_text_dpi,
    layout_dpi,
    win32_palette,
)
from .progress_window import workflow_accessible_name

_SW_SHOWNOACTIVATE = 4

_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010

_MONITOR_DEFAULTTOPRIMARY = 1

_WM_PAINT = 0x000F
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014
_WM_LBUTTONUP = 0x0202
_EVENT_OBJECT_NAMECHANGE = 0x800C
_OBJID_WINDOW = 0
_CHILDID_SELF = 0

_TRANSPARENT = 1
_DEFAULT_WIN_W = 460
_DEFAULT_WIN_H = 250
_EXPANDED_WIN_W = 520
_EXPANDED_WIN_H = 560
_CORNER_MARGIN = 20
_LINE_H = 20
_PAD = 14


def _colorref(rgb: int) -> int:
    """Convert one shared RGB token to a Win32 BGR ``COLORREF``."""

    red = (rgb >> 16) & 0xFF
    green = (rgb >> 8) & 0xFF
    blue = rgb & 0xFF
    return red | (green << 8) | (blue << 16)


# These were literals until the Decision Card needed the same chrome and drifted
# onto a second dark grey. The values are unchanged; the source of truth moved.
_HUD_BACKGROUND = _colorref(OPERATOR_SURFACE.background_rgb)
_HUD_TEXT = _colorref(OPERATOR_SURFACE.text_rgb)
_HUD_MUTED = _colorref(OPERATOR_SURFACE.muted_text_rgb)
_DEFAULT_ACCENT_RGB = 0x2F80ED
_FW_NORMAL = OPERATOR_WEIGHT_NORMAL
_FW_SEMIBOLD = OPERATOR_WEIGHT_SEMIBOLD

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


def _scaled(value: int, dpi: int) -> int:
    return max(1, round(value * dpi / 96))


def _font_height(points: int, dpi: int) -> int:
    """Return the conservative pixel height used by the GDI font request."""

    return max(1, round(points * dpi / 72))


def _workflow_layout(
    geometry_dpi: int,
    text_dpi: int,
    *,
    checklist_steps: int = 0,
) -> tuple[tuple[int, int], ...]:
    """Place workflow rows without overlap at combined display/text scaling.

    The original 96-DPI visual rhythm remains the preferred layout.  When text
    becomes taller than those fixed slots, later rows move down instead of
    painting through earlier content.  Each tuple is ``(top, height)``.
    """

    if checklist_steps < 0:
        raise ValueError("checklist_steps must be non-negative")
    points = (10, 16, 10, 9, 14, 10)
    preferred_tops = (18, 47, 78, 114, 139, 174)
    minimum_gaps = (8, 8, 14, 6, 6)
    rows: list[tuple[int, int]] = []
    for index, (point_size, preferred_top) in enumerate(
        zip(points, preferred_tops, strict=True)
    ):
        height = _font_height(point_size, text_dpi)
        top = _scaled(preferred_top, geometry_dpi)
        if rows:
            previous_top, previous_height = rows[-1]
            top = max(
                top,
                previous_top
                + previous_height
                + _scaled(minimum_gaps[index - 1], geometry_dpi),
            )
        rows.append((top, height))

    if not checklist_steps:
        return tuple(rows)

    previous_top, previous_height = rows[-1]
    header_top = max(
        _scaled(218, geometry_dpi),
        previous_top + previous_height + _scaled(24, geometry_dpi),
    )
    header_height = _font_height(9, text_dpi)
    rows.append((header_top, header_height))
    title_top = max(
        _scaled(247, geometry_dpi),
        header_top + header_height + _scaled(20, geometry_dpi),
    )
    for step_index in range(checklist_steps):
        title_height = _font_height(11, text_dpi)
        rows.append((title_top, title_height))
        meta_top = max(
            title_top + _scaled(22, geometry_dpi),
            title_top + title_height + _scaled(4, geometry_dpi),
        )
        meta_height = _font_height(9, text_dpi)
        rows.append((meta_top, meta_height))
        if step_index + 1 < checklist_steps:
            title_top = max(
                title_top + _scaled(47, geometry_dpi),
                meta_top + meta_height + _scaled(10, geometry_dpi),
            )
    return tuple(rows)


def _window_size(
    expanded: bool,
    dpi: int,
    *,
    text_scale_factor: float = 1.0,
) -> tuple[int, int]:
    width = _EXPANDED_WIN_W if expanded else _DEFAULT_WIN_W
    height = _EXPANDED_WIN_H if expanded else _DEFAULT_WIN_H
    geometry_dpi = layout_dpi(dpi, text_scale_factor)
    text_dpi = effective_text_dpi(dpi, text_scale_factor)
    rows = _workflow_layout(
        geometry_dpi,
        text_dpi,
        checklist_steps=6 if expanded else 0,
    )
    content_height = rows[-1][0] + rows[-1][1] + _scaled(28, geometry_dpi)
    return (
        _scaled(width, geometry_dpi),
        max(_scaled(height, geometry_dpi), content_height),
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


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncremental", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _top_right_origin(
    work_area: tuple[int, int, int, int],
    outer_size: tuple[int, int],
    *,
    margin: int = _CORNER_MARGIN,
) -> tuple[int, int]:
    """Place one HUD inside a monitor work area, anchored to its top-right."""

    left, top, right, bottom = work_area
    width, height = outer_size
    if (
        right <= left
        or bottom <= top
        or width <= 0
        or height <= 0
        or margin < 0
    ):
        raise ValueError("PROGRESS_WORK_AREA_INVALID")
    x = right - width - margin
    y = top + margin
    if x < left:
        x = left
    if y + height > bottom:
        y = top
    return x, y


class Win32ProgressWindowApi:
    """A live, non-activating tool window rendered with GDI text.

    One instance owns one registered window class and the line buffers of the
    windows it creates. The window procedure only paints stored lines and quits
    cleanly on destroy; it has no input handling and no controls, so there is
    nothing that could accept focus even if the window were somehow activated.
    """

    _class_seq = 0

    def __init__(
        self,
        *,
        accessibility: OperatorAccessibilitySettings | None = None,
    ) -> None:
        enable_dpi_awareness()
        self.accessibility = accessibility or OperatorAccessibilitySettings()
        if not isinstance(self.accessibility, OperatorAccessibilitySettings):
            raise ValueError("progress accessibility settings are invalid")
        self._user32 = private_windll("user32")
        self._gdi32 = private_windll("gdi32")
        self._kernel32 = private_windll("kernel32")
        self._lines: dict[int, tuple[str, ...]] = {}
        self._workflow_lines: dict[
            int,
            tuple[tuple[str, ...], tuple[str, ...]],
        ] = {}
        self._toggle_handlers: dict[int, Callable[[bool], None]] = {}
        self._workflow_accents: dict[int, int] = {}
        self._base_titles: dict[int, str] = {}
        self._accessible_names: dict[int, str] = {}
        self._top_right_anchored: set[int] = set()
        self._configure_gdi()
        self._configure_window_apis()
        # Keep a strong reference to the WNDPROC; if it is collected, the window
        # procedure pointer dangles and the next message crashes the process.
        self._wndproc = _WNDPROC(self._on_message)
        Win32ProgressWindowApi._class_seq += 1
        self._class_name = f"CuaPassiveProgress_{id(self)}_{self._class_seq}"
        self._register_class()

    # --- ProgressWindowApi -------------------------------------------------

    def create(self, *, ex_style: int, style: int, title: str) -> int:
        user32 = self._user32
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        dpi = self._system_dpi()
        width, height = _window_size(
            False,
            dpi,
            text_scale_factor=self.accessibility.text_scale_factor,
        )
        x, y = _top_right_origin(
            self._work_area(self.foreground()),
            (width, height),
            margin=_scaled(_CORNER_MARGIN, dpi),
        )
        hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, title, style,
            x,
            y,
            width,
            height,
            None, None, self._hinstance(), None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed (win32 error {self._last_error()})")
        self._lines[int(hwnd)] = ()
        self._base_titles[int(hwnd)] = title
        self._accessible_names[int(hwnd)] = title
        self._top_right_anchored.add(int(hwnd))
        return int(hwnd)

    def set_lines(self, hwnd: int, lines: Sequence[str]) -> None:
        rendered = tuple(lines)
        self._workflow_lines.pop(int(hwnd), None)
        self._toggle_handlers.pop(int(hwnd), None)
        self._workflow_accents.pop(int(hwnd), None)
        self._set_accessible_name(hwnd, f"{self._base_titles[int(hwnd)]}. Progress summary.")
        self._apply_lines(hwnd, rendered)

    def set_workflow_lines(
        self,
        hwnd: int,
        *,
        compact_lines: Sequence[str],
        expanded_lines: Sequence[str],
        expanded: bool,
        accent_rgb: int,
        on_toggle: Callable[[bool], None],
    ) -> None:
        compact = tuple(compact_lines)
        detail = tuple(expanded_lines)
        if (
            len(compact) != 6
            or len(detail) <= 6
            or detail[:6] != compact
            or detail[6] != "WORKFLOW CHECKLIST"
            or not isinstance(expanded, bool)
            or isinstance(accent_rgb, bool)
            or not isinstance(accent_rgb, int)
            or not 0 <= accent_rgb <= 0xFFFFFF
            or not callable(on_toggle)
        ):
            raise ValueError("PROGRESS_WORKFLOW_LINES_INVALID")
        self._workflow_lines[int(hwnd)] = (compact, detail)
        self._toggle_handlers[int(hwnd)] = on_toggle
        self._workflow_accents[int(hwnd)] = accent_rgb
        self._set_accessible_name(hwnd, workflow_accessible_name(compact))
        self._show_workflow(hwnd, expanded=expanded)

    def lines(self, hwnd: int) -> tuple[str, ...]:
        """Return the lines currently held for ``hwnd``, for a smoke assertion.

        Read-only: this is what the window paints, so a probe can check that a
        real state change actually reached the drawn surface.
        """

        return self._lines.get(int(hwnd), ())

    def show_noactivate(self, hwnd: int) -> None:
        self._user32.ShowWindow(wintypes.HWND(hwnd), _SW_SHOWNOACTIVATE)

    def reposition_noactivate(self, hwnd: int, *, x: int, y: int, topmost: bool) -> None:
        self._top_right_anchored.discard(int(hwnd))
        insert_after = _HWND_TOPMOST if topmost else _HWND_NOTOPMOST
        ok = self._user32.SetWindowPos(
            wintypes.HWND(hwnd), wintypes.HWND(insert_after),
            int(x), int(y), 0, 0, _SWP_NOSIZE | _SWP_NOACTIVATE,
        )
        if not ok:
            raise OSError(f"SetWindowPos failed (win32 error {self._last_error()})")

    def foreground(self) -> int:
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        return int(self._user32.GetForegroundWindow() or 0)

    def destroy(self, hwnd: int) -> None:
        self._lines.pop(int(hwnd), None)
        self._workflow_lines.pop(int(hwnd), None)
        self._toggle_handlers.pop(int(hwnd), None)
        self._workflow_accents.pop(int(hwnd), None)
        self._base_titles.pop(int(hwnd), None)
        self._accessible_names.pop(int(hwnd), None)
        self._top_right_anchored.discard(int(hwnd))
        self._user32.DestroyWindow(wintypes.HWND(hwnd))

    # --- message pump (used by the smoke, not the controller) --------------

    def pump(self, iterations: int = 50) -> None:
        """Drain pending messages so the window paints and processes moves."""

        msg = wintypes.MSG()
        user32 = self._user32
        for _ in range(max(0, iterations)):
            if not user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):  # PM_REMOVE
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    # --- internals ---------------------------------------------------------

    def _on_message(self, hwnd, msg, wparam, lparam):  # noqa: ANN001 - ctypes callback
        if msg == _WM_PAINT:
            self._paint(int(hwnd))
            return 0
        if msg == _WM_ERASEBKGND:
            return 1  # painted fully in WM_PAINT; skip default erase flicker
        if msg == _WM_LBUTTONUP and int(hwnd) in self._workflow_lines:
            expanded = self._workflow_is_expanded(int(hwnd))
            if self._point_in_toggle(int(hwnd), int(lparam), expanded=expanded):
                next_expanded = not expanded
                self._show_workflow(int(hwnd), expanded=next_expanded)
                try:
                    self._toggle_handlers[int(hwnd)](next_expanded)
                except Exception:
                    pass
            return 0
        if msg == _WM_CLOSE:
            self._user32.DestroyWindow(wintypes.HWND(hwnd))
            return 0
        if msg == _WM_DESTROY:
            return 0
        return self._user32.DefWindowProcW(
            wintypes.HWND(hwnd), wintypes.UINT(msg), wintypes.WPARAM(wparam), wintypes.LPARAM(lparam)
        )

    def _paint(self, hwnd: int) -> None:
        ps = _PAINTSTRUCT()
        user32, gdi32 = self._user32, self._gdi32
        hdc = user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        try:
            rect = ps.rcPaint
            display_dpi = self._window_dpi(hwnd)
            geometry_dpi = layout_dpi(
                display_dpi,
                self.accessibility.text_scale_factor,
            )
            text_dpi = effective_text_dpi(
                display_dpi,
                self.accessibility.text_scale_factor,
            )
            palette = win32_palette(
                user32,
                high_contrast=self.accessibility.high_contrast,
                accent_rgb=self._workflow_accents.get(hwnd, _DEFAULT_ACCENT_RGB),
            )
            background = gdi32.CreateSolidBrush(palette.background)
            user32.FillRect(hdc, ctypes.byref(rect), background)
            gdi32.DeleteObject(background)
            gdi32.SetBkMode(hdc, _TRANSPARENT)
            gdi32.SetTextColor(hdc, palette.text)
            accent_color = palette.accent
            accent = gdi32.CreateSolidBrush(accent_color)
            accent_rect = wintypes.RECT(
                0,
                0,
                _scaled(6, geometry_dpi),
                max(rect.bottom, _scaled(_DEFAULT_WIN_H, geometry_dpi)),
            )
            user32.FillRect(hdc, ctypes.byref(accent_rect), accent)
            gdi32.DeleteObject(accent)
            lines = self._lines.get(hwnd, ())
            if lines and lines[0].startswith("COMPUTER USE  ·  "):
                self._paint_workflow_summary(
                    hdc,
                    lines[:6],
                    geometry_dpi,
                    text_dpi,
                    accent_color,
                    palette,
                )
                if len(lines) > 6 and lines[6] == "WORKFLOW CHECKLIST":
                    self._paint_workflow_checklist(
                        hdc,
                        lines[6:],
                        geometry_dpi,
                        text_dpi,
                        accent_color,
                        palette,
                    )
                if int(hwnd) in self._workflow_lines:
                    self._paint_toggle(
                        hdc,
                        expanded=self._workflow_is_expanded(int(hwnd)),
                        geometry_dpi=geometry_dpi,
                        text_dpi=text_dpi,
                        palette=palette,
                    )
            else:
                y = _scaled(_PAD, geometry_dpi)
                for line in lines:
                    self._text(
                        hdc,
                        _scaled(_PAD, geometry_dpi),
                        y,
                        str(line),
                        points=10,
                        weight=_FW_NORMAL,
                        color=palette.text,
                        dpi=text_dpi,
                    )
                    y += max(
                        _scaled(_LINE_H, geometry_dpi),
                        round(10 * text_dpi / 72) + _scaled(4, geometry_dpi),
                    )
        finally:
            user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))

    def _paint_workflow_summary(
        self,
        hdc: wintypes.HDC,
        lines: tuple[str, ...],
        geometry_dpi: int,
        text_dpi: int,
        accent_color: int,
        palette: Win32Palette,
    ) -> None:
        """Paint the fixed six-line compact summary with visual hierarchy."""

        x = _scaled(24, geometry_dpi)
        styles = (
            (10, _FW_SEMIBOLD, accent_color),
            (16, _FW_SEMIBOLD, palette.text),
            (10, _FW_NORMAL, palette.muted_text),
            (9, _FW_SEMIBOLD, accent_color),
            (14, _FW_SEMIBOLD, palette.text),
            (10, _FW_NORMAL, palette.muted_text),
        )
        rows = _workflow_layout(geometry_dpi, text_dpi)
        for text, (y, _height), (points, weight, color) in zip(
            lines, rows, styles, strict=True
        ):
            self._text(
                hdc,
                x,
                y,
                text,
                points=points,
                weight=weight,
                color=color,
                dpi=text_dpi,
            )

    def _paint_workflow_checklist(
        self,
        hdc: wintypes.HDC,
        lines: tuple[str, ...],
        geometry_dpi: int,
        text_dpi: int,
        accent_color: int,
        palette: Win32Palette,
    ) -> None:
        """Paint the bounded checklist beneath the unchanged compact summary."""

        checklist_steps = (len(lines) - 1) // 2
        rows = _workflow_layout(
            geometry_dpi,
            text_dpi,
            checklist_steps=checklist_steps,
        )
        header_top, _header_height = rows[6]
        self._text(
            hdc,
            _scaled(24, geometry_dpi),
            header_top,
            lines[0],
            points=9,
            weight=_FW_SEMIBOLD,
            color=accent_color,
            dpi=text_dpi,
        )
        for step_index, index in enumerate(range(1, len(lines), 2)):
            title_top, _title_height = rows[7 + step_index * 2]
            meta_top, _meta_height = rows[8 + step_index * 2]
            self._text(
                hdc,
                _scaled(24, geometry_dpi),
                title_top,
                lines[index],
                points=11,
                weight=_FW_SEMIBOLD,
                color=palette.text,
                dpi=text_dpi,
            )
            self._text(
                hdc,
                _scaled(24, geometry_dpi),
                meta_top,
                lines[index + 1],
                points=9,
                weight=_FW_NORMAL,
                color=palette.muted_text,
                dpi=text_dpi,
            )

    def _paint_toggle(
        self,
        hdc: wintypes.HDC,
        *,
        expanded: bool,
        geometry_dpi: int,
        text_dpi: int,
        palette: Win32Palette,
    ) -> None:
        width = _EXPANDED_WIN_W if expanded else _DEFAULT_WIN_W
        self._text(
            hdc,
            _scaled(width - 132, geometry_dpi),
            _scaled(18, geometry_dpi),
            "HIDE STEPS  ∧" if expanded else "SHOW STEPS  ∨",
            points=9,
            weight=_FW_SEMIBOLD,
            color=palette.muted_text,
            dpi=text_dpi,
        )

    def _text(
        self,
        hdc: wintypes.HDC,
        x: int,
        y: int,
        text: str,
        *,
        points: int,
        weight: int,
        color: int,
        dpi: int,
    ) -> None:
        font = self._gdi32.CreateFontW(
            -max(12, round(points * dpi / 72)),
            0,
            0,
            0,
            weight,
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
            self._gdi32.SetTextColor(hdc, color)
            self._gdi32.TextOutW(hdc, x, y, text, len(text))
            return
        previous = self._gdi32.SelectObject(hdc, font)
        try:
            self._gdi32.SetTextColor(hdc, color)
            self._gdi32.TextOutW(hdc, x, y, text, len(text))
        finally:
            self._gdi32.SelectObject(hdc, previous)
            self._gdi32.DeleteObject(font)

    def _apply_lines(self, hwnd: int, lines: tuple[str, ...]) -> None:
        self._lines[int(hwnd)] = lines
        if lines and lines[0].startswith("COMPUTER USE  ·  "):
            self._resize_summary(
                hwnd,
                expanded=len(lines) > 6 and lines[6] == "WORKFLOW CHECKLIST",
            )
        # Repaint without activation. The window owns no executable control.
        self._user32.InvalidateRect(wintypes.HWND(hwnd), None, True)

    def _show_workflow(self, hwnd: int, *, expanded: bool) -> None:
        variants = self._workflow_lines.get(int(hwnd))
        if variants is None:
            raise ValueError("PROGRESS_WORKFLOW_LINES_UNAVAILABLE")
        self._apply_lines(hwnd, variants[1] if expanded else variants[0])

    def _workflow_is_expanded(self, hwnd: int) -> bool:
        lines = self._lines.get(int(hwnd), ())
        return len(lines) > 6 and lines[6] == "WORKFLOW CHECKLIST"

    def _set_accessible_name(self, hwnd: int, name: str) -> None:
        """Publish one bounded status change without activating the window."""

        key = int(hwnd)
        if self._accessible_names.get(key) == name:
            return
        if not self._user32.SetWindowTextW(wintypes.HWND(hwnd), name):
            return
        self._accessible_names[key] = name
        self._user32.NotifyWinEvent(
            _EVENT_OBJECT_NAMECHANGE,
            wintypes.HWND(hwnd),
            _OBJID_WINDOW,
            _CHILDID_SELF,
        )

    def _point_in_toggle(self, hwnd: int, lparam: int, *, expanded: bool) -> bool:
        dpi = layout_dpi(
            self._window_dpi(hwnd),
            self.accessibility.text_scale_factor,
        )
        width = _EXPANDED_WIN_W if expanded else _DEFAULT_WIN_W
        x = ctypes.c_short(lparam & 0xFFFF).value
        y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
        return (
            _scaled(width - 150, dpi) <= x <= _scaled(width - 8, dpi)
            and _scaled(6, dpi) <= y <= _scaled(42, dpi)
        )

    def _window_dpi(self, hwnd: int) -> int:
        get_dpi = getattr(self._user32, "GetDpiForWindow", None)
        if get_dpi is None:
            return 96
        observed = int(get_dpi(wintypes.HWND(hwnd)))
        return observed if observed > 0 else 96

    def _system_dpi(self) -> int:
        get_dpi = getattr(self._user32, "GetDpiForSystem", None)
        if get_dpi is not None:
            observed = int(get_dpi())
            if observed > 0:
                return observed
        desktop = self._user32.GetDesktopWindow()
        return self._window_dpi(int(desktop))

    def _resize_summary(self, hwnd: int, *, expanded: bool) -> None:
        dpi = self._window_dpi(hwnd)
        geometry_dpi = layout_dpi(dpi, self.accessibility.text_scale_factor)
        width, height = _window_size(
            expanded,
            dpi,
            text_scale_factor=self.accessibility.text_scale_factor,
        )
        flags = _SWP_NOZORDER | _SWP_NOACTIVATE
        x = 0
        y = 0
        if int(hwnd) in self._top_right_anchored:
            x, y = _top_right_origin(
                self._work_area(hwnd),
                (width, height),
                margin=_scaled(_CORNER_MARGIN, geometry_dpi),
            )
        else:
            flags |= _SWP_NOMOVE
        ok = self._user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            x,
            y,
            width,
            height,
            flags,
        )
        if not ok:
            raise OSError(
                f"SetWindowPos failed (win32 error {self._last_error()})"
            )

    def _work_area(self, hwnd: int) -> tuple[int, int, int, int]:
        monitor = self._user32.MonitorFromWindow(
            wintypes.HWND(hwnd),
            _MONITOR_DEFAULTTOPRIMARY,
        )
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not monitor or not self._user32.GetMonitorInfoW(
            monitor,
            ctypes.byref(info),
        ):
            raise OSError(
                f"GetMonitorInfoW failed (win32 error {self._last_error()})"
            )
        return (
            info.rcWork.left,
            info.rcWork.top,
            info.rcWork.right,
            info.rcWork.bottom,
        )

    def _configure_window_apis(self) -> None:
        self._user32.GetSysColor.argtypes = [ctypes.c_int]
        self._user32.GetSysColor.restype = wintypes.DWORD
        self._user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self._user32.SetWindowTextW.restype = wintypes.BOOL
        self._user32.NotifyWinEvent.argtypes = [
            wintypes.DWORD,
            wintypes.HWND,
            wintypes.LONG,
            wintypes.LONG,
        ]
        self._user32.MonitorFromWindow.argtypes = [
            wintypes.HWND,
            wintypes.DWORD,
        ]
        self._user32.MonitorFromWindow.restype = wintypes.HANDLE
        self._user32.GetMonitorInfoW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_MONITORINFO),
        ]
        self._user32.GetMonitorInfoW.restype = wintypes.BOOL

    def _configure_gdi(self) -> None:
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
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL

    def _register_class(self) -> None:
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self._hinstance()
        wc.lpszClassName = self._class_name
        self._user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        self._user32.RegisterClassExW.restype = wintypes.ATOM
        if not self._user32.RegisterClassExW(ctypes.byref(wc)):
            raise OSError(f"RegisterClassExW failed (win32 error {self._last_error()})")

    def _hinstance(self):
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        return self._kernel32.GetModuleHandleW(None)

    def _last_error(self) -> int:
        return int(self._kernel32.GetLastError())


__all__ = [
    "Win32ProgressWindowApi",
    "_scaled",
    "_top_right_origin",
    "_window_size",
]
