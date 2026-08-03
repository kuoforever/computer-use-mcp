"""Click-through Win32 action feedback for a visible desktop Demo."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from queue import Empty, Queue
from threading import Event, Lock, Thread
from time import monotonic
from typing import cast

from .dpi import enable_dpi_awareness

_WS_POPUP = 0x80000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_EX_STYLE = (
    _WS_EX_TOPMOST
    | _WS_EX_TRANSPARENT
    | _WS_EX_TOOLWINDOW
    | _WS_EX_LAYERED
    | _WS_EX_NOACTIVATE
)
_SW_HIDE = 0
_SW_SHOWNOACTIVATE = 4
_HWND_TOPMOST = -1
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_WM_PAINT = 0x000F
_WM_ERASEBKGND = 0x0014
_WM_NCHITTEST = 0x0084
_WM_MOUSEACTIVATE = 0x0021
_HTTRANSPARENT = -1
_MA_NOACTIVATE = 3
_PM_REMOVE = 0x0001
_TRANSPARENT = 1
_LWA_COLORKEY = 0x00000001
_WDA_EXCLUDEFROMCAPTURE = 0x00000011
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1
_NULL_BRUSH = 5
_PS_SOLID = 0
_COLOR_KEY = 0x00FF00FF
_POINTER_ACTIONS = frozenset({"move", "click", "scroll", "drag", "target"})
_KEYBOARD_ACTIONS = frozenset({"typing", "key"})

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
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


class _PAINTSTRUCT(ctypes.Structure):
    _fields_ = [
        ("hdc", wintypes.HDC),
        ("fErase", wintypes.BOOL),
        ("rcPaint", wintypes.RECT),
        ("fRestore", wintypes.BOOL),
        ("fIncremental", wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


class Win32ActionFeedback:
    """One capture-excluded overlay with no focus or input path."""

    _class_seq = 0

    def __init__(self) -> None:
        self._commands: Queue[
            tuple[str, tuple[object, ...], Event, list[BaseException]]
        ] = Queue()
        self._ready = Event()
        self._state_lock = Lock()
        self._state: tuple[str, int, int, str] | None = None
        self._typing_started: float | None = None
        self._typing_duration = 0.0
        self._typing_progress = 0
        self._typing_frame = 0
        self._typing_anchor_source = "fallback"
        self._startup_error: BaseException | None = None
        self._closed = False
        self._thread = Thread(
            target=self._run,
            name="guarded-action-feedback",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(5.0):
            raise OSError("action feedback window did not start")
        if self._startup_error is not None:
            raise OSError("action feedback window failed to start") from self._startup_error

    def _initialize_native(self) -> None:
        enable_dpi_awareness()
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._user32.DefWindowProcW.restype = ctypes.c_ssize_t
        self._user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.c_void_p,
        ]
        self._user32.GetGUIThreadInfo.restype = wintypes.BOOL
        self._user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.c_void_p]
        self._user32.ClientToScreen.restype = wintypes.BOOL
        self._user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.c_void_p]
        self._configure_paint_prototypes()
        self._wndproc = _WNDPROC(self._on_message)
        type(self)._class_seq += 1
        self._class_name = f"CuaActionFeedback_{id(self)}_{self._class_seq}"
        self._register_class()
        self._hwnd = self._create_window()

    @property
    def hwnd(self) -> int:
        """Trusted overlay identity for a native smoke probe."""

        return self._hwnd

    @property
    def state(self) -> tuple[str, int, int, str] | None:
        """Return only the fixed content-free presentation state."""

        with self._state_lock:
            return self._state

    @property
    def typing_progress(self) -> int:
        """Bounded content-free progress percentage for a native probe."""

        with self._state_lock:
            return self._typing_progress

    @property
    def typing_anchor_source(self) -> str:
        """Report whether the badge follows a native caret or its fallback."""

        with self._state_lock:
            return self._typing_anchor_source

    def show_pointer(self, x: int, y: int, *, action: str) -> None:
        if action not in _POINTER_ACTIONS:
            raise ValueError("unsupported pointer feedback action")
        self._send("pointer", int(x), int(y), action)

    def show_keyboard(
        self,
        *,
        action: str,
        total_units: int = 0,
        estimated_seconds: float = 0.0,
    ) -> None:
        if action not in _KEYBOARD_ACTIONS:
            raise ValueError("unsupported keyboard feedback action")
        if (
            isinstance(total_units, bool)
            or not isinstance(total_units, int)
            or not 0 <= total_units <= 1_000_000
            or isinstance(estimated_seconds, bool)
            or not isinstance(estimated_seconds, (int, float))
            or not 0.0 <= float(estimated_seconds) <= 3_600.0
        ):
            raise ValueError("keyboard feedback progress must be bounded")
        self._send(
            "keyboard",
            action,
            total_units,
            float(estimated_seconds),
        )

    def clear(self) -> None:
        self._send("clear")

    def close(self) -> None:
        if self._closed:
            return
        self._send("close")
        self._closed = True
        self._thread.join(timeout=2.0)

    def pump(self, iterations: int = 50) -> None:
        self._send("pump", iterations)

    def _pump_native(self, iterations: int = 50) -> None:
        msg = wintypes.MSG()
        for _ in range(max(0, iterations)):
            if not self._user32.PeekMessageW(
                ctypes.byref(msg), None, 0, 0, _PM_REMOVE
            ):
                break
            self._user32.TranslateMessage(ctypes.byref(msg))
            self._user32.DispatchMessageW(ctypes.byref(msg))

    def _send(self, name: str, *args: object) -> None:
        if self._closed:
            return
        done = Event()
        errors: list[BaseException] = []
        self._commands.put((name, args, done, errors))
        if not done.wait(2.0):
            raise OSError("action feedback worker did not respond")
        if errors:
            raise OSError("action feedback worker failed") from errors[0]

    def _run(self) -> None:
        try:
            self._initialize_native()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        running = True
        while running:
            command: tuple[str, tuple[object, ...], Event, list[BaseException]] | None
            try:
                command = self._commands.get(timeout=0.025)
            except Empty:
                command = None
            if command is not None:
                name, args, done, errors = command
                try:
                    running = self._handle_command(name, args)
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    done.set()
            self._advance_typing()
            self._pump_native()

    def _handle_command(self, name: str, args: tuple[object, ...]) -> bool:
        if name == "pointer":
            x, y, action = args
            self._set_state(
                (
                    "pointer",
                    cast(int, x),
                    cast(int, y),
                    cast(str, action),
                )
            )
            self._stop_typing_animation()
            self._show()
        elif name == "keyboard":
            action, _total_units, estimated_seconds = args
            x, y, source = self._keyboard_anchor()
            self._set_state(("keyboard", x, y, str(action)))
            with self._state_lock:
                self._typing_anchor_source = source
            if action == "typing":
                self._typing_started = monotonic()
                self._typing_duration = max(
                    0.15,
                    cast(float, estimated_seconds),
                )
                with self._state_lock:
                    self._typing_progress = 0
                    self._typing_frame = 0
            else:
                self._stop_typing_animation()
            self._show()
        elif name == "clear":
            self._set_state(None)
            self._stop_typing_animation()
            self._user32.ShowWindow(wintypes.HWND(self._hwnd), _SW_HIDE)
        elif name == "pump":
            self._pump_native(cast(int, args[0]))
        elif name == "close":
            self._set_state(None)
            self._stop_typing_animation()
            self._user32.DestroyWindow(wintypes.HWND(self._hwnd))
            self._hwnd = 0
            return False
        else:
            raise ValueError("unknown action feedback command")
        return True

    def _set_state(self, state: tuple[str, int, int, str] | None) -> None:
        with self._state_lock:
            self._state = state

    def _stop_typing_animation(self) -> None:
        self._typing_started = None
        self._typing_duration = 0.0

    def _keyboard_anchor(self) -> tuple[int, int, str]:
        foreground = int(self._user32.GetForegroundWindow() or 0)
        thread_id = (
            int(self._user32.GetWindowThreadProcessId(foreground, None) or 0)
            if foreground
            else 0
        )
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if thread_id and self._user32.GetGUIThreadInfo(
            thread_id,
            ctypes.byref(info),
        ):
            caret_hwnd = int(info.hwndCaret or 0)
            if caret_hwnd:
                point = wintypes.POINT(info.rcCaret.left, info.rcCaret.bottom)
                if self._user32.ClientToScreen(
                    wintypes.HWND(caret_hwnd),
                    ctypes.byref(point),
                ):
                    if 0 <= point.x < self._width and 0 <= point.y < self._height:
                        return int(point.x), int(point.y), "caret"
        point = wintypes.POINT()
        if self._user32.GetCursorPos(ctypes.byref(point)):
            return int(point.x), int(point.y), "pointer_fallback"
        return 24, 24, "screen_fallback"

    def _advance_typing(self) -> None:
        started = self._typing_started
        if started is None:
            return
        elapsed = max(0.0, monotonic() - started)
        progress = min(100, round(100 * elapsed / self._typing_duration))
        frame = int(elapsed / 0.16) % 4
        with self._state_lock:
            changed = (
                progress != self._typing_progress or frame != self._typing_frame
            )
            self._typing_progress = progress
            self._typing_frame = frame
            state = self._state
        if state is not None and state[0] == "keyboard" and state[3] == "typing":
            x, y, source = self._keyboard_anchor()
            if (x, y) != (state[1], state[2]):
                self._set_state(("keyboard", x, y, "typing"))
                changed = True
            with self._state_lock:
                self._typing_anchor_source = source
        if changed:
            self._user32.InvalidateRect(wintypes.HWND(self._hwnd), None, False)

    def _show(self) -> None:
        self._user32.InvalidateRect(wintypes.HWND(self._hwnd), None, True)
        self._user32.ShowWindow(wintypes.HWND(self._hwnd), _SW_SHOWNOACTIVATE)
        self._user32.SetWindowPos(
            wintypes.HWND(self._hwnd),
            wintypes.HWND(_HWND_TOPMOST),
            0,
            0,
            self._width,
            self._height,
            _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )
        self._pump_native()

    def _create_window(self) -> int:
        self._width = int(self._user32.GetSystemMetrics(_SM_CXSCREEN))
        self._height = int(self._user32.GetSystemMetrics(_SM_CYSCREEN))
        self._dpi = self._system_dpi()
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
            _EX_STYLE,
            self._class_name,
            "Computer Use action feedback",
            _WS_POPUP,
            0,
            0,
            self._width,
            self._height,
            None,
            None,
            self._hinstance(),
            None,
        )
        if not hwnd:
            raise OSError("could not create action feedback window")
        value = int(hwnd)
        if not self._user32.SetLayeredWindowAttributes(
            wintypes.HWND(value), _COLOR_KEY, 0, _LWA_COLORKEY
        ):
            raise OSError("could not make action feedback transparent")
        if not self._user32.SetWindowDisplayAffinity(
            wintypes.HWND(value), _WDA_EXCLUDEFROMCAPTURE
        ):
            raise OSError("could not exclude action feedback from capture")
        return value

    def _on_message(self, hwnd, msg, wparam, lparam):  # noqa: ANN001
        if msg == _WM_NCHITTEST:
            return _HTTRANSPARENT
        if msg == _WM_MOUSEACTIVATE:
            return _MA_NOACTIVATE
        if msg == _WM_PAINT:
            self._paint(int(hwnd))
            return 0
        if msg == _WM_ERASEBKGND:
            return 1
        return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _paint(self, hwnd: int) -> None:
        ps = _PAINTSTRUCT()
        hdc = self._user32.BeginPaint(wintypes.HWND(hwnd), ctypes.byref(ps))
        try:
            key_brush = self._gdi32.CreateSolidBrush(_COLOR_KEY)
            full = wintypes.RECT(0, 0, self._width, self._height)
            self._user32.FillRect(hdc, ctypes.byref(full), key_brush)
            self._gdi32.DeleteObject(key_brush)
            with self._state_lock:
                state = self._state
            if state is None:
                return
            kind, x, y, action = state
            if kind == "pointer":
                self._paint_pointer(hdc, x, y, action)
            else:
                self._paint_keyboard(hdc, x, y, action)
        finally:
            self._user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))

    def _paint_pointer(self, hdc: int, x: int, y: int, action: str) -> None:
        radius = max(24, min(56, round(30 * self._dpi / 96)))
        outer = self._gdi32.CreatePen(_PS_SOLID, max(6, radius // 5), self._colorref(0x101820))
        accent_rgb = 0x00D7FF if action in {"move", "target"} else 0xFFD400
        accent = self._gdi32.CreatePen(_PS_SOLID, max(3, radius // 10), self._colorref(accent_rgb))
        null_brush = self._gdi32.GetStockObject(_NULL_BRUSH)
        old_brush = self._gdi32.SelectObject(hdc, null_brush)
        old_pen = self._gdi32.SelectObject(hdc, outer)
        self._gdi32.Ellipse(hdc, x - radius, y - radius, x + radius, y + radius)
        self._gdi32.SelectObject(hdc, accent)
        inset = max(6, radius // 4)
        self._gdi32.Ellipse(
            hdc,
            x - radius + inset,
            y - radius + inset,
            x + radius - inset,
            y + radius - inset,
        )
        self._gdi32.SelectObject(hdc, old_pen)
        self._gdi32.SelectObject(hdc, old_brush)
        self._gdi32.DeleteObject(outer)
        self._gdi32.DeleteObject(accent)
        self._paint_label(hdc, x + radius + 8, y - 16, f"AGENT {action.upper()}")

    def _paint_keyboard(self, hdc: int, x: int, y: int, action: str) -> None:
        if action != "typing":
            self._paint_label(hdc, x + 28, y + 24, "AGENT KEY")
            return
        with self._state_lock:
            progress = self._typing_progress
            frame = self._typing_frame
        self._paint_typing_badge(hdc, x + 28, y + 24, progress, frame)

    def _paint_typing_badge(
        self,
        hdc: int,
        x: int,
        y: int,
        progress: int,
        frame: int,
    ) -> None:
        width = max(188, round(218 * self._dpi / 96))
        height = max(54, round(62 * self._dpi / 96))
        left = max(8, min(x, self._width - width - 8))
        top = max(8, min(y, self._height - height - 8))
        rect = wintypes.RECT(left, top, left + width, top + height)
        background = self._gdi32.CreateSolidBrush(self._colorref(0x101820))
        self._user32.FillRect(hdc, ctypes.byref(rect), background)
        self._gdi32.DeleteObject(background)
        self._gdi32.SetBkMode(hdc, _TRANSPARENT)
        self._gdi32.SetTextColor(hdc, self._colorref(0xFFFFFF))
        dots = "." * (frame % 4)
        label = f"AGENT TYPING{dots}"
        self._gdi32.TextOutW(hdc, left + 34, top + 13, label, len(label))
        caret_height = max(16, round(20 * self._dpi / 96))
        caret = wintypes.RECT(
            left + 14,
            top + 10,
            left + 20,
            top + 10 + caret_height,
        )
        caret_rgb = 0x00D7FF if frame % 2 == 0 else 0xFFD400
        caret_brush = self._gdi32.CreateSolidBrush(self._colorref(caret_rgb))
        self._user32.FillRect(hdc, ctypes.byref(caret), caret_brush)
        self._gdi32.DeleteObject(caret_brush)
        track = wintypes.RECT(left + 14, top + height - 13, left + width - 14, top + height - 7)
        track_brush = self._gdi32.CreateSolidBrush(self._colorref(0x314252))
        self._user32.FillRect(hdc, ctypes.byref(track), track_brush)
        self._gdi32.DeleteObject(track_brush)
        fill_width = max(0, (track.right - track.left) * progress // 100)
        if fill_width:
            fill = wintypes.RECT(track.left, track.top, track.left + fill_width, track.bottom)
            fill_brush = self._gdi32.CreateSolidBrush(self._colorref(0x00D7FF))
            self._user32.FillRect(hdc, ctypes.byref(fill), fill_brush)
            self._gdi32.DeleteObject(fill_brush)

    def _paint_label(self, hdc: int, x: int, y: int, label: str) -> None:
        width = max(132, round(154 * self._dpi / 96))
        height = max(36, round(42 * self._dpi / 96))
        left = max(8, min(x, self._width - width - 8))
        top = max(8, min(y, self._height - height - 8))
        rect = wintypes.RECT(left, top, left + width, top + height)
        background = self._gdi32.CreateSolidBrush(self._colorref(0x101820))
        self._user32.FillRect(hdc, ctypes.byref(rect), background)
        self._gdi32.DeleteObject(background)
        self._gdi32.SetBkMode(hdc, _TRANSPARENT)
        self._gdi32.SetTextColor(hdc, self._colorref(0xFFFFFF))
        self._gdi32.TextOutW(hdc, left + 14, top + 12, label, len(label))

    def _register_class(self) -> None:
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self._hinstance()
        wc.lpszClassName = self._class_name
        self._user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        self._user32.RegisterClassExW.restype = wintypes.ATOM
        if not self._user32.RegisterClassExW(ctypes.byref(wc)):
            raise OSError("could not register action feedback window")

    def _configure_paint_prototypes(self) -> None:
        self._gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        self._gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
        self._gdi32.CreatePen.restype = wintypes.HANDLE
        self._gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.DWORD]
        self._gdi32.GetStockObject.restype = wintypes.HANDLE
        self._gdi32.GetStockObject.argtypes = [ctypes.c_int]
        self._gdi32.SelectObject.restype = wintypes.HANDLE
        self._gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        self._gdi32.DeleteObject.restype = wintypes.BOOL
        self._gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self._gdi32.Ellipse.restype = wintypes.BOOL
        self._gdi32.Ellipse.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        self._gdi32.SetBkMode.restype = ctypes.c_int
        self._gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
        self._gdi32.SetTextColor.restype = wintypes.DWORD
        self._gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.DWORD]
        self._gdi32.TextOutW.restype = wintypes.BOOL
        self._gdi32.TextOutW.argtypes = [
            wintypes.HDC,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        self._user32.BeginPaint.restype = wintypes.HDC
        self._user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        self._user32.EndPaint.restype = wintypes.BOOL
        self._user32.EndPaint.argtypes = [wintypes.HWND, ctypes.c_void_p]
        self._user32.FillRect.restype = ctypes.c_int
        self._user32.FillRect.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            wintypes.HBRUSH,
        ]

    def _system_dpi(self) -> int:
        get_dpi = getattr(self._user32, "GetDpiForSystem", None)
        if get_dpi is None:
            return 96
        return max(48, min(768, int(get_dpi() or 96)))

    def _hinstance(self):
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        return self._kernel32.GetModuleHandleW(None)

    @staticmethod
    def _colorref(rgb: int) -> int:
        red = (rgb >> 16) & 0xFF
        green = (rgb >> 8) & 0xFF
        blue = rgb & 0xFF
        return red | (green << 8) | (blue << 16)


__all__ = ["Win32ActionFeedback"]
