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
from collections.abc import Sequence
from ctypes import wintypes

from computer_use_mcp.dpi import enable_dpi_awareness

_SW_SHOWNOACTIVATE = 4

_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOSIZE = 0x0001
_SWP_NOACTIVATE = 0x0010

_WM_PAINT = 0x000F
_WM_DESTROY = 0x0002
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014

_TRANSPARENT = 1
_DEFAULT_WIN_W = 420
_DEFAULT_WIN_H = 320
_LINE_H = 18
_PAD = 10

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
        hwnd = user32.CreateWindowExW(
            ex_style, self._class_name, title, style,
            24, 24, _DEFAULT_WIN_W, _DEFAULT_WIN_H,
            None, None, self._hinstance(), None,
        )
        if not hwnd:
            raise OSError(f"CreateWindowExW failed (win32 error {self._last_error()})")
        self._lines[int(hwnd)] = ()
        return int(hwnd)

    def set_lines(self, hwnd: int, lines: Sequence[str]) -> None:
        self._lines[int(hwnd)] = tuple(lines)
        # Force a repaint without erasing to background first, so refreshes do
        # not flicker and never touch activation.
        self._user32.InvalidateRect(wintypes.HWND(hwnd), None, True)

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
            white = gdi32.GetStockObject(0)  # WHITE_BRUSH
            user32.FillRect(hdc, ctypes.byref(rect), white)
            gdi32.SetBkMode(hdc, _TRANSPARENT)
            y = _PAD
            for line in self._lines.get(hwnd, ()):
                text = str(line)
                gdi32.TextOutW(hdc, _PAD, y, text, len(text))
                y += _LINE_H
        finally:
            user32.EndPaint(wintypes.HWND(hwnd), ctypes.byref(ps))

    def _register_class(self) -> None:
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self._hinstance()
        wc.lpszClassName = self._class_name
        if not self._user32.RegisterClassExW(ctypes.byref(wc)):
            raise OSError(f"RegisterClassExW failed (win32 error {self._last_error()})")

    def _hinstance(self):
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        return self._kernel32.GetModuleHandleW(None)

    def _last_error(self) -> int:
        return int(self._kernel32.GetLastError())


__all__ = ["Win32ProgressWindowApi"]
