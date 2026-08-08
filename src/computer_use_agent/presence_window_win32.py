"""ctypes Win32 backend for the click-through desktop presence halo."""
from __future__ import annotations

import ctypes
from ctypes import wintypes

from computer_use_mcp.dpi import enable_dpi_awareness

from .operator_display import OperatorMonitor
from .operator_display_win32 import (
    configure_operator_monitor_apis,
    foreground_operator_monitor,
)
from .win32_dll import private_windll
from .operator_accessibility import (
    OperatorAccessibilitySettings,
    effective_text_dpi,
    layout_dpi,
    win32_palette,
)
from .operator_localization import OperatorLocale
from .operator_personalization import OperatorTheme
from .presence import PresenceView
from .presence_window import (
    PresenceGeometry,
    presence_accessible_name,
)

_SW_SHOWNOACTIVATE = 4
_HWND_TOPMOST = -1
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_WM_PAINT = 0x000F
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014
_WM_NCHITTEST = 0x0084
_WM_MOUSEACTIVATE = 0x0021
_WM_TIMER = 0x0113
_EVENT_OBJECT_NAMECHANGE = 0x800C
_OBJID_WINDOW = 0
_CHILDID_SELF = 0
_HTTRANSPARENT = -1
_MA_NOACTIVATE = 3
_TRANSPARENT = 1
_LWA_COLORKEY = 0x00000001
_WDA_EXCLUDEFROMCAPTURE = 0x00000011
#: The halo has no alpha blending. The whole window is filled with this key and
#: ``LWA_COLORKEY`` removes it outright, so the interior is fully transparent
#: while the border and phase tab stay fully opaque. That is what lets the halo
#: be unmistakable without covering anything the operator could act on.
#:
#: Consequence: any colour equal to this key renders as a hole. No phase colour
#: may collide with it, which `test_presence_window` asserts.
PRESENCE_TRANSPARENT_COLOR_KEY = 0x00FF00FF
_MAGENTA = PRESENCE_TRANSPARENT_COLOR_KEY
_ANIMATION_TIMER_ID = 1

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
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


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


def _presence_tab_layout(
    geometry: PresenceGeometry,
    geometry_dpi: int,
    *,
    text_width: int,
    text_height: int,
) -> tuple[int, int, int, int, int, int]:
    """Fit one measured status label inside the monitor-sized halo."""

    if text_width < 0 or text_height < 0:
        raise ValueError("PRESENCE_TEXT_EXTENT_INVALID")
    left = geometry.border_px
    top = geometry.border_px
    width = max(
        round(240 * geometry_dpi / 96),
        text_width + geometry.label_inset_px * 2,
    )
    height = max(
        round(42 * geometry_dpi / 96),
        text_height + geometry.label_inset_px * 2,
    )
    right = min(geometry.width - geometry.border_px, left + width)
    bottom = min(geometry.height - geometry.border_px, top + height)
    return (
        left,
        top,
        max(left + 1, right),
        max(top + 1, bottom),
        left + geometry.label_inset_px,
        top + geometry.label_inset_px,
    )


class Win32PresenceWindowApi:
    """Selected-display halo with no input, focus, or activation path."""

    _class_seq = 0

    def __init__(
        self,
        *,
        accessibility: OperatorAccessibilitySettings | None = None,
        locale: OperatorLocale = OperatorLocale.EN_US,
        theme: OperatorTheme = OperatorTheme.DARK,
    ) -> None:
        enable_dpi_awareness()
        self.accessibility = accessibility or OperatorAccessibilitySettings()
        if not isinstance(self.accessibility, OperatorAccessibilitySettings):
            raise ValueError("presence accessibility settings are invalid")
        if not isinstance(locale, OperatorLocale):
            raise ValueError("presence locale is invalid")
        if not isinstance(theme, OperatorTheme):
            raise ValueError("presence theme is invalid")
        self.locale = locale
        self.theme = theme
        self._user32 = private_windll("user32")
        self._shcore = private_windll("shcore")
        self._gdi32 = private_windll("gdi32")
        self._kernel32 = private_windll("kernel32")
        self._states: dict[int, tuple[PresenceView, PresenceGeometry]] = {}
        self._frames: dict[int, int] = {}
        self._accessible_names: dict[int, str] = {}
        configure_operator_monitor_apis(self._user32, self._shcore)
        self._configure_accessibility_apis()
        self._wndproc = _WNDPROC(self._on_message)
        Win32PresenceWindowApi._class_seq += 1
        self._class_name = f"CuaPresence_{id(self)}_{self._class_seq}"
        self._register_class()

    def display_monitor(self) -> OperatorMonitor:
        return foreground_operator_monitor(self._user32, shcore=self._shcore)

    def create(self, *, ex_style: int, style: int, title: str) -> int:
        self._user32.CreateWindowExW.restype = wintypes.HWND
        self._user32.CreateWindowExW.argtypes = [
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
            wintypes.LPVOID,
        ]
        hwnd = self._user32.CreateWindowExW(
            ex_style,
            self._class_name,
            title,
            style,
            0,
            0,
            1,
            1,
            None,
            None,
            self._hinstance(),
            None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed ({self._last_error()})")
        value = int(hwnd)
        self._user32.SetLayeredWindowAttributes(
            wintypes.HWND(value), _MAGENTA, 0, _LWA_COLORKEY
        )
        return value

    def configure(
        self, hwnd: int, view: PresenceView, geometry: PresenceGeometry
    ) -> None:
        self._states[int(hwnd)] = (view, geometry)
        self._frames[int(hwnd)] = 0
        accessible_name = presence_accessible_name(view, locale=self.locale)
        if self._accessible_names.get(int(hwnd)) != accessible_name:
            if self._user32.SetWindowTextW(wintypes.HWND(hwnd), accessible_name):
                self._accessible_names[int(hwnd)] = accessible_name
                self._user32.NotifyWinEvent(
                    _EVENT_OBJECT_NAMECHANGE,
                    wintypes.HWND(hwnd),
                    _OBJID_WINDOW,
                    _CHILDID_SELF,
                )
        self._user32.KillTimer(wintypes.HWND(hwnd), _ANIMATION_TIMER_ID)
        if view.animation_interval_ms is not None:
            timer = self._user32.SetTimer(
                wintypes.HWND(hwnd),
                _ANIMATION_TIMER_ID,
                view.animation_interval_ms,
                None,
            )
            if not timer:
                raise OSError(f"SetTimer failed ({self._last_error()})")
        ok = self._user32.SetWindowPos(
            wintypes.HWND(hwnd),
            wintypes.HWND(_HWND_TOPMOST),
            geometry.x,
            geometry.y,
            geometry.width,
            geometry.height,
            _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )
        if not ok:
            raise OSError(f"SetWindowPos failed ({self._last_error()})")
        self._user32.InvalidateRect(wintypes.HWND(hwnd), None, True)

    def exclude_from_capture(self, hwnd: int) -> bool:
        return bool(
            self._user32.SetWindowDisplayAffinity(
                wintypes.HWND(hwnd), _WDA_EXCLUDEFROMCAPTURE
            )
        )

    def show_noactivate(self, hwnd: int) -> None:
        self._user32.ShowWindow(wintypes.HWND(hwnd), _SW_SHOWNOACTIVATE)

    def foreground(self) -> int:
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        return int(self._user32.GetForegroundWindow() or 0)

    def state(self, hwnd: int) -> tuple[PresenceView, PresenceGeometry] | None:
        """Return the exact redaction-safe state painted by a smoke probe."""

        return self._states.get(int(hwnd))

    def animation_frame(self, hwnd: int) -> int:
        """Expose only the bounded animation counter for a live smoke check."""

        return self._frames.get(int(hwnd), 0)

    def destroy(self, hwnd: int) -> None:
        self._states.pop(int(hwnd), None)
        self._frames.pop(int(hwnd), None)
        self._accessible_names.pop(int(hwnd), None)
        self._user32.KillTimer(wintypes.HWND(hwnd), _ANIMATION_TIMER_ID)
        self._user32.DestroyWindow(wintypes.HWND(hwnd))

    def pump(self, iterations: int = 50) -> None:
        msg = wintypes.MSG()
        for _ in range(max(0, iterations)):
            if not self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                break
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def _on_message(self, hwnd, msg, wparam, lparam):  # noqa: ANN001
        if msg == _WM_NCHITTEST:
            return _HTTRANSPARENT
        if msg == _WM_MOUSEACTIVATE:
            return _MA_NOACTIVATE
        if msg == _WM_PAINT:
            self._paint(int(hwnd))
            return 0
        if msg == _WM_TIMER and int(wparam) == _ANIMATION_TIMER_ID:
            key = int(hwnd)
            self._frames[key] = (self._frames.get(key, 0) + 1) % 4
            self._user32.InvalidateRect(wintypes.HWND(hwnd), None, False)
            return 0
        if msg == _WM_ERASEBKGND:
            return 1
        if msg == _WM_CLOSE:
            self._user32.DestroyWindow(wintypes.HWND(hwnd))
            return 0
        return self._user32.DefWindowProcW(
            wintypes.HWND(hwnd),
            wintypes.UINT(msg),
            wintypes.WPARAM(wparam),
            wintypes.LPARAM(lparam),
        )

    def _paint(self, hwnd: int) -> None:
        state = self._states.get(hwnd)
        ps = _PAINTSTRUCT()
        hdc = self._user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        try:
            rect = ps.rcPaint
            background = self._gdi32.CreateSolidBrush(_MAGENTA)
            self._user32.FillRect(hdc, ctypes.byref(rect), background)
            self._gdi32.DeleteObject(background)
            if state is None:
                return
            view, geometry = state
            palette = win32_palette(
                self._user32,
                high_contrast=view.high_contrast,
                accent_rgb=view.color_rgb,
                theme=self.theme,
            )
            color = palette.accent
            if (
                not view.high_contrast
                and view.animation_interval_ms is not None
                and self._frames.get(hwnd, 0) >= 2
            ):
                # Uniformly dimming each byte is channel-order independent, so
                # this works on the resolved Win32 COLORREF in both themes.
                color = self._dim(color)
            border = self._gdi32.CreateSolidBrush(color)
            full = wintypes.RECT(0, 0, geometry.width, geometry.height)
            for inset in range(geometry.border_px):
                current = wintypes.RECT(
                    full.left + inset,
                    full.top + inset,
                    full.right - inset,
                    full.bottom - inset,
                )
                self._user32.FrameRect(hdc, ctypes.byref(current), border)
            self._gdi32.DeleteObject(border)
            # A solid status tab makes the active phase readable at a glance;
            # the rest of the window remains color-key transparent.
            text = f"{view.glyph}  AGENT · {view.label.upper()}"
            display_dpi = geometry.dpi
            geometry_dpi = layout_dpi(
                display_dpi,
                self.accessibility.text_scale_factor,
            )
            text_dpi = effective_text_dpi(
                display_dpi,
                self.accessibility.text_scale_factor,
            )
            font_height = max(12, round(10 * text_dpi / 72))
            font = self._gdi32.CreateFontW(
                -font_height,
                0,
                0,
                0,
                600,
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
                extent = _SIZE()
                measured = bool(
                    self._gdi32.GetTextExtentPoint32W(
                        hdc,
                        text,
                        len(text),
                        ctypes.byref(extent),
                    )
                )
                text_width = int(extent.cx) if measured else len(text) * font_height
                text_height = int(extent.cy) if measured else font_height
                left, top, right, bottom, text_x, text_y = _presence_tab_layout(
                    geometry,
                    geometry_dpi,
                    text_width=text_width,
                    text_height=text_height,
                )
                tab = wintypes.RECT(left, top, right, bottom)
                tab_brush = self._gdi32.CreateSolidBrush(color)
                self._user32.FillRect(hdc, ctypes.byref(tab), tab_brush)
                self._gdi32.DeleteObject(tab_brush)
                self._gdi32.SetBkMode(hdc, _TRANSPARENT)
                self._gdi32.SetTextColor(hdc, palette.accent_text)
                self._gdi32.TextOutW(
                    hdc,
                    text_x,
                    text_y,
                    text,
                    len(text),
                )
            finally:
                if font:
                    self._gdi32.SelectObject(hdc, previous)
                    self._gdi32.DeleteObject(font)
        finally:
            self._user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))

    def _configure_accessibility_apis(self) -> None:
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
        self._gdi32.CreateFontW.restype = wintypes.HGDIOBJ
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        self._gdi32.SelectObject.restype = wintypes.HGDIOBJ
        self._gdi32.GetTextExtentPoint32W.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(_SIZE),
        ]
        self._gdi32.GetTextExtentPoint32W.restype = wintypes.BOOL
        self._gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        self._gdi32.DeleteObject.restype = wintypes.BOOL

    @staticmethod
    def _colorref(rgb: int) -> int:
        red = (rgb >> 16) & 0xFF
        green = (rgb >> 8) & 0xFF
        blue = rgb & 0xFF
        return red | (green << 8) | (blue << 16)

    @staticmethod
    def _dim(rgb: int) -> int:
        red = ((rgb >> 16) & 0xFF) * 2 // 3
        green = ((rgb >> 8) & 0xFF) * 2 // 3
        blue = (rgb & 0xFF) * 2 // 3
        return (red << 16) | (green << 8) | blue

    def _register_class(self) -> None:
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self._hinstance()
        wc.lpszClassName = self._class_name
        self._user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        self._user32.RegisterClassExW.restype = wintypes.ATOM
        if not self._user32.RegisterClassExW(ctypes.byref(wc)):
            raise OSError(f"RegisterClassExW failed ({self._last_error()})")

    def _hinstance(self):
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        return self._kernel32.GetModuleHandleW(None)

    def _last_error(self) -> int:
        return int(self._kernel32.GetLastError())


__all__ = ["Win32PresenceWindowApi", "_presence_tab_layout"]
