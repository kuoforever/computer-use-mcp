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
_WM_LBUTTONUP = 0x0202

_TRANSPARENT = 1
_DEFAULT_WIN_W = 460
_DEFAULT_WIN_H = 250
_EXPANDED_WIN_W = 520
_EXPANDED_WIN_H = 560
_LINE_H = 20
_PAD = 14
_HUD_BACKGROUND = 0x001E1713
_HUD_TEXT = 0x00F5F5F5
_HUD_MUTED = 0x00B8B8B8
_DEFAULT_ACCENT_RGB = 0x2F80ED
_FW_NORMAL = 400
_FW_SEMIBOLD = 600

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


def _scaled(value: int, dpi: int) -> int:
    return max(1, round(value * dpi / 96))


def _window_size(expanded: bool, dpi: int) -> tuple[int, int]:
    width = _EXPANDED_WIN_W if expanded else _DEFAULT_WIN_W
    height = _EXPANDED_WIN_H if expanded else _DEFAULT_WIN_H
    return _scaled(width, dpi), _scaled(height, dpi)


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


class Win32ProgressWindowApi:
    """A live, non-activating tool window rendered with GDI text.

    One instance owns one registered window class and the line buffers of the
    windows it creates. The window procedure only paints stored lines and quits
    cleanly on destroy; it has no input handling and no controls, so there is
    nothing that could accept focus even if the window were somehow activated.
    """

    _class_seq = 0

    def __init__(self) -> None:
        enable_dpi_awareness()
        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._kernel32 = ctypes.windll.kernel32
        self._lines: dict[int, tuple[str, ...]] = {}
        self._workflow_lines: dict[
            int,
            tuple[tuple[str, ...], tuple[str, ...]],
        ] = {}
        self._toggle_handlers: dict[int, Callable[[bool], None]] = {}
        self._workflow_accents: dict[int, int] = {}
        self._configure_gdi()
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
        width, height = _window_size(False, dpi)
        hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, title, style,
            _scaled(24, dpi),
            _scaled(24, dpi),
            width,
            height,
            None, None, self._hinstance(), None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed (win32 error {self._last_error()})")
        self._lines[int(hwnd)] = ()
        return int(hwnd)

    def set_lines(self, hwnd: int, lines: Sequence[str]) -> None:
        rendered = tuple(lines)
        self._workflow_lines.pop(int(hwnd), None)
        self._toggle_handlers.pop(int(hwnd), None)
        self._workflow_accents.pop(int(hwnd), None)
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
            background = gdi32.CreateSolidBrush(_HUD_BACKGROUND)
            user32.FillRect(hdc, ctypes.byref(rect), background)
            gdi32.DeleteObject(background)
            gdi32.SetBkMode(hdc, _TRANSPARENT)
            gdi32.SetTextColor(hdc, _HUD_TEXT)
            accent_color = self._rgb_to_colorref(
                self._workflow_accents.get(hwnd, _DEFAULT_ACCENT_RGB)
            )
            accent = gdi32.CreateSolidBrush(accent_color)
            dpi = self._window_dpi(hwnd)
            accent_rect = wintypes.RECT(
                0,
                0,
                _scaled(6, dpi),
                max(rect.bottom, _scaled(_DEFAULT_WIN_H, dpi)),
            )
            user32.FillRect(hdc, ctypes.byref(accent_rect), accent)
            gdi32.DeleteObject(accent)
            lines = self._lines.get(hwnd, ())
            if lines and lines[0].startswith("COMPUTER USE  ·  "):
                self._paint_workflow_summary(
                    hdc,
                    lines[:6],
                    dpi,
                    accent_color,
                )
                if len(lines) > 6 and lines[6] == "WORKFLOW CHECKLIST":
                    self._paint_workflow_checklist(
                        hdc,
                        lines[6:],
                        dpi,
                        accent_color,
                    )
                if int(hwnd) in self._workflow_lines:
                    self._paint_toggle(
                        hdc,
                        expanded=self._workflow_is_expanded(int(hwnd)),
                        dpi=dpi,
                    )
            else:
                y = _scaled(_PAD, dpi)
                for line in lines:
                    self._text(
                        hdc,
                        _scaled(_PAD, dpi),
                        y,
                        str(line),
                        points=10,
                        weight=_FW_NORMAL,
                        color=_HUD_TEXT,
                        dpi=dpi,
                    )
                    y += _scaled(_LINE_H, dpi)
        finally:
            user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))

    def _paint_workflow_summary(
        self,
        hdc: wintypes.HDC,
        lines: tuple[str, ...],
        dpi: int,
        accent_color: int,
    ) -> None:
        """Paint the fixed six-line compact summary with visual hierarchy."""

        x = _scaled(24, dpi)
        styles = (
            (18, 10, _FW_SEMIBOLD, accent_color),
            (47, 16, _FW_SEMIBOLD, _HUD_TEXT),
            (78, 10, _FW_NORMAL, _HUD_MUTED),
            (114, 9, _FW_SEMIBOLD, accent_color),
            (139, 14, _FW_SEMIBOLD, _HUD_TEXT),
            (174, 10, _FW_NORMAL, _HUD_MUTED),
        )
        for text, (y, points, weight, color) in zip(lines, styles, strict=True):
            self._text(
                hdc,
                x,
                _scaled(y, dpi),
                text,
                points=points,
                weight=weight,
                color=color,
                dpi=dpi,
            )

    def _paint_workflow_checklist(
        self,
        hdc: wintypes.HDC,
        lines: tuple[str, ...],
        dpi: int,
        accent_color: int,
    ) -> None:
        """Paint the bounded checklist beneath the unchanged compact summary."""

        self._text(
            hdc,
            _scaled(24, dpi),
            _scaled(218, dpi),
            lines[0],
            points=9,
            weight=_FW_SEMIBOLD,
            color=accent_color,
            dpi=dpi,
        )
        y = 247
        for index in range(1, len(lines), 2):
            self._text(
                hdc,
                _scaled(24, dpi),
                _scaled(y, dpi),
                lines[index],
                points=11,
                weight=_FW_SEMIBOLD,
                color=_HUD_TEXT,
                dpi=dpi,
            )
            self._text(
                hdc,
                _scaled(24, dpi),
                _scaled(y + 22, dpi),
                lines[index + 1],
                points=9,
                weight=_FW_NORMAL,
                color=_HUD_MUTED,
                dpi=dpi,
            )
            y += 47

    def _paint_toggle(
        self,
        hdc: wintypes.HDC,
        *,
        expanded: bool,
        dpi: int,
    ) -> None:
        width = _EXPANDED_WIN_W if expanded else _DEFAULT_WIN_W
        self._text(
            hdc,
            _scaled(width - 132, dpi),
            _scaled(18, dpi),
            "HIDE STEPS  ∧" if expanded else "SHOW STEPS  ∨",
            points=9,
            weight=_FW_SEMIBOLD,
            color=_HUD_MUTED,
            dpi=dpi,
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

    def _point_in_toggle(self, hwnd: int, lparam: int, *, expanded: bool) -> bool:
        dpi = self._window_dpi(hwnd)
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

    @staticmethod
    def _rgb_to_colorref(rgb: int) -> int:
        red = (rgb >> 16) & 0xFF
        green = (rgb >> 8) & 0xFF
        blue = rgb & 0xFF
        return red | (green << 8) | (blue << 16)

    def _system_dpi(self) -> int:
        get_dpi = getattr(self._user32, "GetDpiForSystem", None)
        if get_dpi is not None:
            observed = int(get_dpi())
            if observed > 0:
                return observed
        desktop = self._user32.GetDesktopWindow()
        return self._window_dpi(int(desktop))

    def _resize_summary(self, hwnd: int, *, expanded: bool) -> None:
        width, height = _window_size(expanded, self._window_dpi(hwnd))
        ok = self._user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            0,
            0,
            width,
            height,
            _SWP_NOMOVE | _SWP_NOZORDER | _SWP_NOACTIVATE,
        )
        if not ok:
            raise OSError(
                f"SetWindowPos failed (win32 error {self._last_error()})"
            )

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


__all__ = ["Win32ProgressWindowApi", "_scaled", "_window_size"]
