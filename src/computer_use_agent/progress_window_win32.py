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

from .operator_display_win32 import (
    configure_operator_monitor_apis,
    operator_dpi_for_window,
    operator_monitor_for_window,
)
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
from .operator_localization import OperatorLocale, operator_text
from .operator_personalization import OperatorTheme
from .progress_window import workflow_accessible_name

_SW_SHOWNOACTIVATE = 4

_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010

_WM_PAINT = 0x000F
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014
_WM_COMMAND = 0x0111
_WM_SETFONT = 0x0030
_EVENT_OBJECT_NAMECHANGE = 0x800C
_OBJID_WINDOW = 0
_CHILDID_SELF = 0

_TRANSPARENT = 1
_WM_USER = 0x0400
_EM_EXSETSEL = _WM_USER + 55
_EM_SETBKGNDCOLOR = _WM_USER + 67
_EM_SETCHARFORMAT = _WM_USER + 68
_EM_SCROLLCARET = 0x00B7
_SCF_SELECTION = 0x0001
_SCF_ALL = 0x0004
_CFM_BOLD = 0x00000001
_CFM_COLOR = 0x40000000
_CFM_FACE = 0x20000000
_CFM_SIZE = 0x80000000
_CFE_BOLD = 0x00000001

_WS_CHILD = 0x40000000
_WS_VISIBLE = 0x10000000
_WS_VSCROLL = 0x00200000
_ES_MULTILINE = 0x0004
_ES_AUTOVSCROLL = 0x0040
_ES_READONLY = 0x0800
_BS_PUSHBUTTON = 0x00000000
_SW_HIDE = 0
_BN_CLICKED = 0
_WORKFLOW_TOGGLE_ID = 2101
_WORKFLOW_DOCUMENT_ID = 2102
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
    text_ratio = text_dpi / max(1, geometry_dpi)
    wrapped_rows = {1: 3, 2: 2, 4: 2} if text_ratio >= 2.0 else {1: 2, 2: 2, 4: 2}
    preferred_tops = (18, 47, 78, 114, 139, 174)
    minimum_gaps = (8, 8, 14, 6, 6)
    rows: list[tuple[int, int]] = []
    for index, (point_size, preferred_top) in enumerate(
        zip(points, preferred_tops, strict=True)
    ):
        height = _font_height(point_size, text_dpi) * (
            wrapped_rows.get(index, 1) if text_ratio > 1.0 else 1
        )
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

    if checklist_steps:
        # Expanded workflow content lives in one bounded RichEdit viewport.
        # It wraps and scrolls instead of making every checklist row enlarge the
        # passive window beyond the selected monitor work area.
        previous_top, previous_height = rows[-1]
        rows.append(
            (
                previous_top + previous_height + _scaled(16, geometry_dpi),
                max(
                    _scaled(180, geometry_dpi),
                    _font_height(10, text_dpi) * 3,
                ),
            )
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
    rows = _workflow_layout(geometry_dpi, text_dpi)
    summary_height = sum(height for _top, height in rows)
    summary_height += _scaled(8, geometry_dpi) * (len(rows) - 1)
    # The RichEdit document inserts two empty semantic separators. Their line
    # height follows text scale, not the geometry cap.
    summary_height += _font_height(10, text_dpi) * 2
    toggle_height = max(
        _scaled(36, geometry_dpi),
        _font_height(10, text_dpi) + _scaled(12, geometry_dpi),
    )
    content_height = (
        _scaled(_PAD, geometry_dpi) * 2
        + summary_height
        + _scaled(10, geometry_dpi)
        + toggle_height
    )
    if text_dpi > geometry_dpi:
        # RichEdit includes font-leading and word-wrap variance that nominal
        # font heights do not. Keep the complete six-line glance summary above
        # the disclosure at 200%/400%; the expanded checklist still scrolls.
        content_height += _font_height(10, text_dpi) * 3
    if expanded:
        content_height += _scaled(80, geometry_dpi)
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


class _CHARRANGE(ctypes.Structure):
    _fields_ = [
        ("cpMin", ctypes.c_long),
        ("cpMax", ctypes.c_long),
    ]


class _CHARFORMAT2W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwMask", wintypes.DWORD),
        ("dwEffects", wintypes.DWORD),
        ("yHeight", ctypes.c_long),
        ("yOffset", ctypes.c_long),
        ("crTextColor", wintypes.DWORD),
        ("bCharSet", ctypes.c_byte),
        ("bPitchAndFamily", ctypes.c_byte),
        ("szFaceName", wintypes.WCHAR * 32),
        ("wWeight", wintypes.WORD),
        ("sSpacing", ctypes.c_short),
        ("crBackColor", wintypes.DWORD),
        ("lcid", wintypes.DWORD),
        ("dwReserved", wintypes.DWORD),
        ("sStyle", ctypes.c_short),
        ("wKerning", wintypes.WORD),
        ("bUnderlineType", ctypes.c_byte),
        ("bAnimation", ctypes.c_byte),
        ("bRevAuthor", ctypes.c_byte),
        ("bReserved1", ctypes.c_byte),
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
    """A live, non-activating tool window with bounded native semantics.

    Plain status lines remain passive GDI output. Workflow mode separates one
    read-only, wrapping UIA Document from one real disclosure Button. The
    top-level window still never activates or steals focus; the Button exists so
    mouse and assistive-technology invocation receive standard control states
    instead of relying on an invisible coordinate hit target.
    """

    _class_seq = 0

    def __init__(
        self,
        *,
        accessibility: OperatorAccessibilitySettings | None = None,
        locale: OperatorLocale = OperatorLocale.EN_US,
        theme: OperatorTheme = OperatorTheme.DARK,
    ) -> None:
        if not isinstance(locale, OperatorLocale):
            raise ValueError("progress locale is invalid")
        if not isinstance(theme, OperatorTheme):
            raise ValueError("progress theme is invalid")
        enable_dpi_awareness()
        self.locale = locale
        self.theme = theme
        self.accessibility = accessibility or OperatorAccessibilitySettings()
        if not isinstance(self.accessibility, OperatorAccessibilitySettings):
            raise ValueError("progress accessibility settings are invalid")
        self._user32 = private_windll("user32")
        self._shcore = private_windll("shcore")
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
        self._workflow_toggles: dict[int, int] = {}
        self._workflow_documents: dict[int, int] = {}
        self._workflow_fonts: dict[int, wintypes.HGDIOBJ] = {}
        configure_operator_monitor_apis(self._user32, self._shcore)
        self._configure_gdi()
        self._configure_window_apis()
        self._msftedit_module = self._kernel32.GetModuleHandleW("Msftedit.dll")
        if not self._msftedit_module:
            self._msftedit_module = self._kernel32.LoadLibraryW("Msftedit.dll")
        if not self._msftedit_module:
            raise OSError("PROGRESS_RICH_EDIT_UNAVAILABLE")
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
        foreground = self.foreground()
        monitor = operator_monitor_for_window(
            self._user32,
            foreground,
            shcore=self._shcore,
        )
        dpi = monitor.dpi
        width, height = _window_size(
            False,
            dpi,
            text_scale_factor=self.accessibility.text_scale_factor,
        )
        x, y = _top_right_origin(
            monitor.work_area,
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
        if int(hwnd) in self._workflow_lines:
            self._resize_summary(hwnd, expanded=False)
        self._show_workflow_controls(hwnd, visible=False)
        self._workflow_lines.pop(int(hwnd), None)
        self._toggle_handlers.pop(int(hwnd), None)
        self._workflow_accents.pop(int(hwnd), None)
        title = self._base_titles[int(hwnd)]
        summary = operator_text(self.locale, "progress_summary")
        name = (
            f"{title}。{summary}。"
            if self.locale is OperatorLocale.ZH_CN
            else f"{title}. {summary}."
        )
        self._set_accessible_name(hwnd, name)
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
            or detail[6] != operator_text(self.locale, "workflow_checklist")
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
        self._ensure_workflow_controls(hwnd)
        self._set_accessible_name(
            hwnd,
            workflow_accessible_name(compact, self.locale),
        )
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
        font = self._workflow_fonts.pop(int(hwnd), None)
        self._workflow_toggles.pop(int(hwnd), None)
        self._workflow_documents.pop(int(hwnd), None)
        self._lines.pop(int(hwnd), None)
        self._workflow_lines.pop(int(hwnd), None)
        self._toggle_handlers.pop(int(hwnd), None)
        self._workflow_accents.pop(int(hwnd), None)
        self._base_titles.pop(int(hwnd), None)
        self._accessible_names.pop(int(hwnd), None)
        self._top_right_anchored.discard(int(hwnd))
        self._user32.DestroyWindow(wintypes.HWND(hwnd))
        if font:
            self._gdi32.DeleteObject(font)

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
        if msg == _WM_COMMAND and int(hwnd) in self._workflow_lines:
            command_id = int(wparam) & 0xFFFF
            notification = (int(wparam) >> 16) & 0xFFFF
            if notification == _BN_CLICKED and command_id == _WORKFLOW_TOGGLE_ID:
                expanded = self._workflow_is_expanded(int(hwnd))
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
                theme=self.theme,
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
            if int(hwnd) in self._workflow_lines:
                # Workflow text and disclosure are child controls. The parent
                # paints only chrome so information never collides with the
                # interactive state at large text scales.
                return
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

    @staticmethod
    def _workflow_document_text(lines: tuple[str, ...]) -> tuple[str, tuple[tuple[int, int, int], ...]]:
        """Return readable paragraphs plus source-line ranges for rich styling."""

        rendered: list[str] = []
        spans: list[tuple[int, int, int]] = []
        offset = 0
        for index, line in enumerate(lines):
            if index in {3, 6}:
                rendered.append("")
                offset += 1
            rendered.append(line)
            spans.append((offset, offset + len(line), index))
            offset += len(line) + 1
        return "\n".join(rendered), tuple(spans)

    def _style_workflow_document(
        self,
        hwnd: int,
        lines: tuple[str, ...],
        *,
        palette: Win32Palette,
        display_dpi: int,
        text_dpi: int,
    ) -> None:
        """Give the wrapping UIA document the same semantic text hierarchy."""

        document = wintypes.HWND(self._workflow_documents[int(hwnd)])
        text, spans = self._workflow_document_text(lines)
        self._user32.SetWindowTextW(document, text)
        self._user32.SendMessageW(document, _EM_SETBKGNDCOLOR, 0, palette.surface)

        def char_format(*, points: int, color: int, bold: bool) -> _CHARFORMAT2W:
            result = _CHARFORMAT2W()
            result.cbSize = ctypes.sizeof(result)
            result.dwMask = _CFM_BOLD | _CFM_COLOR | _CFM_FACE | _CFM_SIZE
            result.dwEffects = _CFE_BOLD if bold else 0
            result.yHeight = max(
                1,
                round(points * text_dpi * 20 / max(96, display_dpi)),
            )
            result.crTextColor = color
            result.szFaceName = "Segoe UI"
            return result

        def send_format(wparam: int, value: _CHARFORMAT2W) -> None:
            pointer = ctypes.cast(ctypes.byref(value), ctypes.c_void_p).value or 0
            self._user32.SendMessageW(document, _EM_SETCHARFORMAT, wparam, pointer)

        send_format(
            _SCF_ALL,
            char_format(points=10, color=palette.text, bold=False),
        )
        for start, end, index in spans:
            selection = _CHARRANGE(start, end)
            pointer = ctypes.cast(ctypes.byref(selection), ctypes.c_void_p).value or 0
            self._user32.SendMessageW(document, _EM_EXSETSEL, 0, pointer)
            if index in {0, 3, 6}:
                points, color, bold = (10 if index == 0 else 9), palette.accent, True
            elif index == 1:
                points, color, bold = 16, palette.text, True
            elif index == 4:
                points, color, bold = 14, palette.text, True
            elif index >= 7 and index % 2 == 1:
                points, color, bold = 11, palette.text, True
            elif index >= 7:
                points, color, bold = 9, palette.muted_text, False
            else:
                points, color, bold = 10, palette.muted_text, False
            send_format(
                _SCF_SELECTION,
                char_format(points=points, color=color, bold=bold),
            )
        selection = _CHARRANGE(0, 0)
        pointer = ctypes.cast(ctypes.byref(selection), ctypes.c_void_p).value or 0
        self._user32.SendMessageW(document, _EM_EXSETSEL, 0, pointer)
        self._user32.SendMessageW(document, _EM_SCROLLCARET, 0, 0)

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

    def _ensure_workflow_controls(self, hwnd: int) -> None:
        key = int(hwnd)
        if key in self._workflow_toggles:
            return
        display_dpi = self._window_dpi(key)
        text_dpi = effective_text_dpi(
            display_dpi,
            self.accessibility.text_scale_factor,
        )
        instance = self._hinstance()
        document = self._user32.CreateWindowExW(
            0,
            "RICHEDIT50W",
            "",
            _WS_CHILD
            | _WS_VISIBLE
            | _ES_MULTILINE
            | _ES_AUTOVSCROLL
            | _ES_READONLY
            | _WS_VSCROLL,
            0,
            0,
            1,
            1,
            wintypes.HWND(key),
            wintypes.HMENU(_WORKFLOW_DOCUMENT_ID),
            instance,
            None,
        )
        toggle = self._user32.CreateWindowExW(
            0,
            "BUTTON",
            operator_text(self.locale, "show_steps"),
            _WS_CHILD | _WS_VISIBLE | _BS_PUSHBUTTON,
            0,
            0,
            1,
            1,
            wintypes.HWND(key),
            wintypes.HMENU(_WORKFLOW_TOGGLE_ID),
            instance,
            None,
        )
        if not document or not toggle:
            if document:
                self._user32.DestroyWindow(document)
            if toggle:
                self._user32.DestroyWindow(toggle)
            raise OSError("PROGRESS_WORKFLOW_CONTROL_CREATE_FAILED")
        font = self._gdi32.CreateFontW(
            -max(12, round(10 * text_dpi / 72)),
            0,
            0,
            0,
            _FW_SEMIBOLD,
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
        self._workflow_documents[key] = int(document)
        self._workflow_toggles[key] = int(toggle)
        if font:
            self._workflow_fonts[key] = font
            self._user32.SendMessageW(toggle, _WM_SETFONT, font, 1)

    def _show_workflow_controls(self, hwnd: int, *, visible: bool) -> None:
        command = _SW_SHOWNOACTIVATE if visible else _SW_HIDE
        for controls in (self._workflow_documents, self._workflow_toggles):
            handle = controls.get(int(hwnd))
            if handle:
                self._user32.ShowWindow(wintypes.HWND(handle), command)

    def _layout_workflow_controls(self, hwnd: int) -> None:
        key = int(hwnd)
        document = self._workflow_documents.get(key)
        toggle = self._workflow_toggles.get(key)
        if not document or not toggle:
            return
        client = wintypes.RECT()
        if not self._user32.GetClientRect(wintypes.HWND(key), ctypes.byref(client)):
            return
        display_dpi = self._window_dpi(key)
        geometry_dpi = layout_dpi(
            display_dpi,
            self.accessibility.text_scale_factor,
        )
        text_dpi = effective_text_dpi(
            display_dpi,
            self.accessibility.text_scale_factor,
        )
        pad = _scaled(_PAD, geometry_dpi)
        gap = _scaled(10, geometry_dpi)
        toggle_height = max(
            _scaled(36, geometry_dpi),
            _font_height(10, text_dpi) + _scaled(12, geometry_dpi),
        )
        content_left = pad + _scaled(6, geometry_dpi)
        content_width = max(1, client.right - content_left - pad)
        toggle_top = max(pad, client.bottom - pad - toggle_height)
        document_height = max(1, toggle_top - gap - pad)
        self._user32.MoveWindow(
            wintypes.HWND(document),
            content_left,
            pad,
            content_width,
            document_height,
            True,
        )
        self._user32.MoveWindow(
            wintypes.HWND(toggle),
            content_left,
            toggle_top,
            content_width,
            toggle_height,
            True,
        )

    def _apply_lines(self, hwnd: int, lines: tuple[str, ...]) -> None:
        self._lines[int(hwnd)] = lines
        if int(hwnd) in self._workflow_lines:
            self._resize_summary(
                hwnd,
                expanded=self._workflow_is_expanded(int(hwnd)),
            )
            self._layout_workflow_controls(hwnd)
        # Repaint without activation. The window owns no executable control.
        self._user32.InvalidateRect(wintypes.HWND(hwnd), None, True)

    def _show_workflow(self, hwnd: int, *, expanded: bool) -> None:
        variants = self._workflow_lines.get(int(hwnd))
        if variants is None:
            raise ValueError("PROGRESS_WORKFLOW_LINES_UNAVAILABLE")
        lines = variants[1] if expanded else variants[0]
        self._apply_lines(hwnd, lines)
        self._show_workflow_controls(hwnd, visible=True)
        toggle = self._workflow_toggles[int(hwnd)]
        self._user32.SetWindowTextW(
            wintypes.HWND(toggle),
            operator_text(self.locale, "hide_steps" if expanded else "show_steps")
            + ("  ▲" if expanded else "  ▼"),
        )
        display_dpi = self._window_dpi(hwnd)
        palette = win32_palette(
            self._user32,
            high_contrast=self.accessibility.high_contrast,
            accent_rgb=self._workflow_accents.get(int(hwnd), _DEFAULT_ACCENT_RGB),
            theme=self.theme,
        )
        self._style_workflow_document(
            hwnd,
            lines,
            palette=palette,
            display_dpi=display_dpi,
            text_dpi=effective_text_dpi(
                display_dpi,
                self.accessibility.text_scale_factor,
            ),
        )

    def _workflow_is_expanded(self, hwnd: int) -> bool:
        lines = self._lines.get(int(hwnd), ())
        variants = self._workflow_lines.get(int(hwnd))
        return variants is not None and lines == variants[1]

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

    def _window_dpi(self, hwnd: int) -> int:
        return operator_dpi_for_window(self._user32, hwnd)

    def _resize_summary(self, hwnd: int, *, expanded: bool) -> None:
        monitor = operator_monitor_for_window(
            self._user32,
            hwnd,
            shcore=self._shcore,
        )
        dpi = monitor.dpi
        geometry_dpi = layout_dpi(dpi, self.accessibility.text_scale_factor)
        width, height = _window_size(
            expanded,
            dpi,
            text_scale_factor=self.accessibility.text_scale_factor,
        )
        work_left, work_top, work_right, work_bottom = monitor.work_area
        width = min(width, work_right - work_left)
        height = min(height, work_bottom - work_top)
        flags = _SWP_NOZORDER | _SWP_NOACTIVATE
        x = 0
        y = 0
        if int(hwnd) in self._top_right_anchored:
            x, y = _top_right_origin(
                monitor.work_area,
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
        return operator_monitor_for_window(
            self._user32,
            hwnd,
            shcore=self._shcore,
        ).work_area

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
        self._user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.SendMessageW.restype = ctypes.c_ssize_t
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.MoveWindow.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.BOOL,
        ]
        self._user32.MoveWindow.restype = wintypes.BOOL
        self._user32.GetClientRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        self._user32.GetClientRect.restype = wintypes.BOOL
        self._user32.DestroyWindow.argtypes = [wintypes.HWND]
        self._user32.DestroyWindow.restype = wintypes.BOOL
        self._kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.LoadLibraryW.restype = wintypes.HMODULE
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE

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
