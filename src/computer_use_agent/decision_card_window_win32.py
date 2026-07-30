"""Resizable ctypes Win32 backend for the focus-taking local Decision Card."""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Literal

from computer_use_mcp.dpi import enable_dpi_awareness

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
_TDM_CLICK_BUTTON = 0x0400 + 102
_BN_CLICKED = 0
_VK_ESCAPE = 0x1B

_WS_OVERLAPPEDWINDOW = 0x00CF0000
_WS_CLIPCHILDREN = 0x02000000
_WS_CHILD = 0x40000000
_WS_VISIBLE = 0x10000000
_WS_TABSTOP = 0x00010000
_WS_VSCROLL = 0x00200000
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_CLIENTEDGE = 0x00000200

_ES_MULTILINE = 0x0004
_ES_AUTOVSCROLL = 0x0040
_ES_READONLY = 0x0800
_BS_PUSHBUTTON = 0x00000000
_BS_DEFPUSHBUTTON = 0x00000001
_BS_MULTILINE = 0x00002000

_SW_HIDE = 0
_SW_SHOWNORMAL = 1
_SW_RESTORE = 9
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040
_COLOR_WINDOW = 5
_DEFAULT_GUI_FONT = 17
_MONITOR_DEFAULTTOPRIMARY = 1
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20

_FIRST_BUTTON_ID = 1001
_CONTENT_ID = 2001
_EVIDENCE_TOGGLE_ID = 2002
_EVIDENCE_ID = 2003
_TIMEOUT_ID = 2004
_TIMER_ID = 1
_TIMER_INTERVAL_MS = 250

_COMPACT_CLIENT_WIDTH = 560
_COMPACT_CLIENT_HEIGHT = 270
_EXPANDED_CLIENT_WIDTH = 720
_EXPANDED_CLIENT_HEIGHT = 620
_CORNER_MARGIN = 20
_BASE_DPI = 96

# COLORREF values use BGR byte order.
_HUD_BACKGROUND = 0x0022201F
_HUD_SURFACE = 0x00302D2B
_HUD_TEXT = 0x00F2F2F2
_HUD_MUTED_TEXT = 0x00AAA7A3

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


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
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
) -> tuple[int, int]:
    """Return intentional logical geometry for one DPI-aware card state."""

    if not 96 <= dpi <= 768:
        dpi = _BASE_DPI
    width = _EXPANDED_CLIENT_WIDTH if expanded else _COMPACT_CLIENT_WIDTH
    height = _EXPANDED_CLIENT_HEIGHT if expanded else _COMPACT_CLIENT_HEIGHT
    return (
        max(1, round(width * dpi / _BASE_DPI)),
        max(1, round(height * dpi / _BASE_DPI)),
    )


def _layout_rects(
    width: int,
    height: int,
    button_count: int,
    *,
    expanded: bool,
    dpi: int = _BASE_DPI,
) -> dict[str, tuple[int, int, int, int]]:
    """Compute a fixed 2x2 compact grid and bounded expanded detail panes."""

    if not 96 <= dpi <= 768:
        dpi = _BASE_DPI

    def scale(value: int) -> int:
        return max(1, round(value * dpi / _BASE_DPI))

    margin = scale(16)
    gap = scale(8)
    header_height = scale(78)
    timeout_width = min(scale(150), max(scale(112), width // 4))
    toggle_height = scale(30)
    button_height = scale(42)
    columns = 2
    rows = (button_count + columns - 1) // columns
    buttons_height = rows * button_height + max(0, rows - 1) * gap
    buttons_top = height - margin - buttons_height
    button_width = max(
        100,
        (width - 2 * margin - gap) // columns,
    )
    rects: dict[str, tuple[int, int, int, int]] = {
        "instruction": (
            margin,
            margin,
            max(120, width - 2 * margin - timeout_width - gap),
            header_height,
        ),
        "timeout": (
            width - margin - timeout_width,
            margin,
            timeout_width,
            24,
        ),
        "toggle": (
            margin,
            margin + header_height + gap,
            min(150, width - 2 * margin),
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
        details_top = margin + header_height + gap + toggle_height + gap
        details_bottom = buttons_top - gap
        available = max(128, details_bottom - details_top)
        content_height = max(72, int(available * 0.55))
        evidence_height = max(48, available - content_height - gap)
        rects["content"] = (
            margin,
            details_top,
            width - 2 * margin,
            content_height,
        )
        rects["evidence"] = (
            margin,
            details_top + content_height + gap,
            width - 2 * margin,
            evidence_height,
        )
    return rects


class Win32DecisionCardWindowApi:
    """Show a timed, resizable Decision Card in a normal Windows tool window."""

    def __init__(self, *, corner: DecisionCardCorner = "bottom_right") -> None:
        if corner not in _VALID_CORNERS:
            raise ValueError("decision card corner is invalid")
        enable_dpi_awareness()
        self.corner = corner
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._gdi32 = ctypes.windll.gdi32
        self._dwmapi = ctypes.windll.dwmapi
        self._uxtheme = ctypes.windll.uxtheme
        self._configure_apis()

    def _configure_apis(self) -> None:
        user32 = self._user32
        kernel32 = self._kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetDpiForSystem.restype = wintypes.UINT
        user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
        user32.GetDlgCtrlID.restype = ctypes.c_int
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
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
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_MONITORINFO),
        ]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.AdjustWindowRectEx.argtypes = [
            ctypes.POINTER(wintypes.RECT),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        user32.AdjustWindowRectEx.restype = wintypes.BOOL
        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadCursorW.restype = wintypes.HANDLE
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

    def _window_rect(
        self,
        foreground: wintypes.HWND,
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
        monitor = self._user32.MonitorFromWindow(
            foreground, _MONITOR_DEFAULTTOPRIMARY
        )
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not monitor or not self._user32.GetMonitorInfoW(
            monitor, ctypes.byref(info)
        ):
            raise OSError("DECISION_CARD_MONITOR_INFO_FAILED")
        work_width = info.rcWork.right - info.rcWork.left
        work_height = info.rcWork.bottom - info.rcWork.top
        width = min(width, max(1, work_width - 2 * _CORNER_MARGIN))
        height = min(height, max(1, work_height - 2 * _CORNER_MARGIN))
        left, top = _corner_origin(
            (
                info.rcWork.left,
                info.rcWork.top,
                info.rcWork.right,
                info.rcWork.bottom,
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
            self._user32.ShowWindow(hwnd, _SW_RESTORE)
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
        instance = self._kernel32.GetModuleHandleW(None)
        class_name = f"GuardedDesktopDecisionCard_{id(self):x}"
        selected: list[str | None] = [None]
        controls: dict[str, wintypes.HWND] = {}
        expanded = [False]
        compact_window_rect: list[tuple[int, int, int, int] | None] = [None]
        deadline = time.monotonic() + timeout_seconds
        dpi = int(self._user32.GetDpiForSystem() or _BASE_DPI)
        background_brush = self._gdi32.CreateSolidBrush(_HUD_BACKGROUND)
        surface_brush = self._gdi32.CreateSolidBrush(_HUD_SURFACE)
        id_to_option = {
            _FIRST_BUTTON_ID + index: button.option_id
            for index, button in enumerate(buttons)
        }

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
            for name, rectangle in _layout_rects(
                width,
                height,
                len(buttons),
                expanded=expanded[0],
                dpi=dpi,
            ).items():
                move(name, *rectangle)

        def resize_for_state(hwnd: wintypes.HWND) -> None:
            if not expanded[0] and compact_window_rect[0] is not None:
                left, top, width, height = compact_window_rect[0]
            else:
                left, top, width, height = self._window_rect(
                    hwnd,
                    _WS_OVERLAPPEDWINDOW | _WS_CLIPCHILDREN,
                    _WS_EX_APPWINDOW,
                    _scaled_client_size(expanded[0], dpi),
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
                        (
                            "Hide details"
                            if expanded[0]
                            else "Show details"
                        ),
                    )
                    for name in ("content", "evidence"):
                        self._user32.ShowWindow(
                            controls[name],
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
                self._user32.SetWindowTextW(
                    controls["timeout"],
                    f"Closes in {remaining}s",
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
                text_color = (
                    _HUD_MUTED_TEXT if control_id == _TIMEOUT_ID else _HUD_TEXT
                )
                self._gdi32.SetTextColor(wintypes.HDC(wparam), text_color)
                self._gdi32.SetBkColor(
                    wintypes.HDC(wparam),
                    _HUD_SURFACE if message == _WM_CTLCOLOREDIT else _HUD_BACKGROUND,
                )
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
        try:
            style = _WS_OVERLAPPEDWINDOW | _WS_CLIPCHILDREN
            ex_style = _WS_EX_APPWINDOW
            x, y, width, height = self._window_rect(
                foreground_before,
                style,
                ex_style,
                _scaled_client_size(False, dpi),
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
            dark_mode = wintypes.BOOL(True)
            self._dwmapi.DwmSetWindowAttribute(
                hwnd,
                _DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(dark_mode),
                ctypes.sizeof(dark_mode),
            )

            font = self._gdi32.CreateFontW(
                -max(13, round(10 * dpi / 72)),
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
                self._user32.SendMessageW(handle, _WM_SETFONT, font, 1)
                self._uxtheme.SetWindowTheme(
                    handle,
                    "DarkMode_Explorer",
                    None,
                )
                return handle

            create_control(
                "instruction",
                "STATIC",
                instruction,
                0,
                0,
            )
            create_control(
                "timeout",
                "STATIC",
                f"Closes in {timeout_seconds}s",
                0,
                _TIMEOUT_ID,
            )
            create_control(
                "content",
                "EDIT",
                content,
                _ES_MULTILINE
                | _ES_AUTOVSCROLL
                | _ES_READONLY
                | _WS_VSCROLL
                | _WS_TABSTOP,
                _CONTENT_ID,
                ex=_WS_EX_CLIENTEDGE,
                visible=False,
            )
            create_control(
                "toggle",
                "BUTTON",
                "Show details",
                _BS_PUSHBUTTON | _WS_TABSTOP,
                _EVIDENCE_TOGGLE_ID,
            )
            create_control(
                "evidence",
                "EDIT",
                expanded_information,
                _ES_MULTILINE
                | _ES_AUTOVSCROLL
                | _ES_READONLY
                | _WS_VSCROLL
                | _WS_TABSTOP,
                _EVIDENCE_ID,
                ex=_WS_EX_CLIENTEDGE,
                visible=False,
            )
            for index, button in enumerate(buttons):
                create_control(
                    f"button_{index}",
                    "BUTTON",
                    button.label,
                    (
                        _BS_DEFPUSHBUTTON
                        if button.option_id == "option_deny"
                        else _BS_PUSHBUTTON
                    )
                    | _BS_MULTILINE
                    | _WS_TABSTOP,
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
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if hwnd and self._user32.IsWindow(hwnd):
                self._user32.DestroyWindow(hwnd)
            self._user32.UnregisterClassW(class_name, instance)
            if surface_brush:
                self._gdi32.DeleteObject(surface_brush)
            if background_brush:
                self._gdi32.DeleteObject(background_brush)
            if owns_font and font:
                self._gdi32.DeleteObject(font)
            if foreground_before and self._user32.IsWindow(foreground_before):
                foreground_after = self._user32.GetForegroundWindow()
                self._bring_to_foreground(
                    foreground_before,
                    foreground_after,
                )
        return selected[0]


__all__ = ["DecisionCardCorner", "Win32DecisionCardWindowApi"]
