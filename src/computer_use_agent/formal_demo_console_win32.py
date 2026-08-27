"""Native Windows controls for the Review-only Formal Demo Agent Console.

The backend contains ordinary input, read-only review, acknowledgement, reset,
and cancel controls.  The Start button is created disabled, omitted from the tab
order, and has no command handler.  This module receives no provider, permit,
Runner, MCP, Driver, persistence, or execution callback.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from computer_use_mcp.dpi import enable_dpi_awareness

from .formal_demo_console import (
    CONSOLE_MODE_LABEL,
    FormalDemoConsoleCallbacks,
    FormalDemoConsoleStage,
    FormalDemoConsoleView,
)
from .operator_accessibility import (
    OperatorAccessibilitySettings,
    effective_text_dpi,
    layout_dpi,
    resolve_operator_accessibility,
)
from .win32_dll import private_windll


_WM_DESTROY = 0x0002
_WM_SIZE = 0x0005
_WM_CLOSE = 0x0010
_WM_SETFONT = 0x0030
_WM_COMMAND = 0x0111
_WM_KEYDOWN = 0x0100
_WM_DPICHANGED = 0x02E0
_BN_CLICKED = 0
_VK_TAB = 0x09
_VK_SHIFT = 0x10
_VK_ESCAPE = 0x1B
_SIZE_MINIMIZED = 1
_EM_SETLIMITTEXT = 0x00C5

_WS_OVERLAPPED = 0x00000000
_WS_CAPTION = 0x00C00000
_WS_SYSMENU = 0x00080000
_WS_THICKFRAME = 0x00040000
_WS_MINIMIZEBOX = 0x00020000
_WS_MAXIMIZEBOX = 0x00010000
_WS_CLIPCHILDREN = 0x02000000
_WS_CHILD = 0x40000000
_WS_VISIBLE = 0x10000000
_WS_TABSTOP = 0x00010000
_WS_DISABLED = 0x08000000
_WS_VSCROLL = 0x00200000
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_CLIENTEDGE = 0x00000200
_WS_EX_CONTROLPARENT = 0x00010000

_CONSOLE_WINDOW_STYLE = (
    _WS_OVERLAPPED
    | _WS_CAPTION
    | _WS_SYSMENU
    | _WS_THICKFRAME
    | _WS_MINIMIZEBOX
    | _WS_MAXIMIZEBOX
    | _WS_CLIPCHILDREN
)
_CONSOLE_WINDOW_EX_STYLE = _WS_EX_APPWINDOW | _WS_EX_CONTROLPARENT

_ES_LEFT = 0x0000
_ES_MULTILINE = 0x0004
_ES_AUTOVSCROLL = 0x0040
_ES_AUTOHSCROLL = 0x0080
_ES_READONLY = 0x0800
_BS_PUSHBUTTON = 0x00000000
_SS_LEFT = 0x00000000
_SS_NOPREFIX = 0x00000080

_SW_SHOW = 5
_COLOR_WINDOW = 5
_SPI_GETWORKAREA = 0x0030
_MONITOR_DEFAULTTONEAREST = 2
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_IDC_ARROW = 32512
_FW_NORMAL = 400
_OUT_DEFAULT_PRECIS = 0
_CLIP_DEFAULT_PRECIS = 0
_CLEARTYPE_QUALITY = 5
_DEFAULT_PITCH = 0
_FF_DONTCARE = 0

_TASK_LABEL_ID = 1001
_TASK_EDIT_ID = 1002
_REVIEW_BUTTON_ID = 1003
_RESET_BUTTON_ID = 1004
_DETAIL_LABEL_ID = 1005
_DETAIL_EDIT_ID = 1006
_ACK_LABEL_ID = 1007
_ACK_EDIT_ID = 1008
_ACK_BUTTON_ID = 1009
_START_BUTTON_ID = 1010
_CANCEL_BUTTON_ID = 1011
_MODE_LABEL_ID = 1012

_BASE_DPI = 96
_BASE_CLIENT_WIDTH = 980
_BASE_CLIENT_HEIGHT = 780
_MIN_CLIENT_WIDTH = 680
_MIN_CLIENT_HEIGHT = 600
_MAX_NATIVE_TEXT_CHARS = 64 * 1024
_TASK_EDIT_CHAR_LIMIT = 32 * 1024
_ACK_EDIT_CHAR_LIMIT = 128


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


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class ConsoleLayout:
    mode: tuple[int, int, int, int]
    task_label: tuple[int, int, int, int]
    task_edit: tuple[int, int, int, int]
    review_button: tuple[int, int, int, int]
    reset_button: tuple[int, int, int, int]
    detail_label: tuple[int, int, int, int]
    detail_edit: tuple[int, int, int, int]
    ack_label: tuple[int, int, int, int]
    ack_edit: tuple[int, int, int, int]
    ack_button: tuple[int, int, int, int]
    start_button: tuple[int, int, int, int]
    cancel_button: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class _Controls:
    mode: int
    task_label: int
    task_edit: int
    review_button: int
    reset_button: int
    detail_label: int
    detail_edit: int
    ack_label: int
    ack_edit: int
    ack_button: int
    start_button: int
    cancel_button: int

    def all_handles(self) -> tuple[int, ...]:
        return (
            self.mode,
            self.task_label,
            self.task_edit,
            self.review_button,
            self.reset_button,
            self.detail_label,
            self.detail_edit,
            self.ack_label,
            self.ack_edit,
            self.ack_button,
            self.start_button,
            self.cancel_button,
        )


def _scaled(value: int, dpi: int) -> int:
    selected = dpi if isinstance(dpi, int) and not isinstance(dpi, bool) else _BASE_DPI
    if not _BASE_DPI <= selected <= 768:
        selected = _BASE_DPI
    return max(1, round(value * selected / _BASE_DPI))


def _client_size(dpi: int, text_scale_factor: float) -> tuple[int, int]:
    geometry_dpi = layout_dpi(dpi, text_scale_factor)
    return (
        max(_MIN_CLIENT_WIDTH, _scaled(_BASE_CLIENT_WIDTH, geometry_dpi)),
        max(_MIN_CLIENT_HEIGHT, _scaled(_BASE_CLIENT_HEIGHT, geometry_dpi)),
    )


def _bounded_window_rect(
    desired_width: int,
    desired_height: int,
    work_area: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Center a top-level window without placing any edge outside work area."""

    left, top, right, bottom = work_area
    available_width = right - left
    available_height = bottom - top
    if (
        desired_width < 1
        or desired_height < 1
        or available_width < 1
        or available_height < 1
    ):
        raise ValueError("FORMAL_DEMO_CONSOLE_WORK_AREA_INVALID")
    width = min(desired_width, available_width)
    height = min(desired_height, available_height)
    return (
        left + (available_width - width) // 2,
        top + (available_height - height) // 2,
        width,
        height,
    )


def _bounded_window_at(
    x: int,
    y: int,
    desired_width: int,
    desired_height: int,
    work_area: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """Keep a suggested origin when possible, including negative monitors."""

    left, top, right, bottom = work_area
    available_width = right - left
    available_height = bottom - top
    if (
        desired_width < 1
        or desired_height < 1
        or available_width < 1
        or available_height < 1
    ):
        raise ValueError("FORMAL_DEMO_CONSOLE_WORK_AREA_INVALID")
    width = min(desired_width, available_width)
    height = min(desired_height, available_height)
    bounded_x = min(max(x, left), right - width)
    bounded_y = min(max(y, top), bottom - height)
    return bounded_x, bounded_y, width, height


def _layout_rects(
    width: int,
    height: int,
    dpi: int,
    *,
    text_scale_factor: float,
) -> ConsoleLayout:
    """Return a bounded reflow whose review document absorbs remaining height."""

    if width < _MIN_CLIENT_WIDTH or height < _MIN_CLIENT_HEIGHT:
        raise ValueError("FORMAL_DEMO_CONSOLE_LAYOUT_TOO_SMALL")
    geometry_dpi = layout_dpi(dpi, text_scale_factor)
    text_dpi = effective_text_dpi(dpi, text_scale_factor)
    margin = _scaled(18, geometry_dpi)
    gap = _scaled(10, geometry_dpi)
    label_height = max(_scaled(22, geometry_dpi), _scaled(19, text_dpi))
    button_height = max(_scaled(38, geometry_dpi), _scaled(22, text_dpi))
    desired_task_height = max(_scaled(92, geometry_dpi), _scaled(54, text_dpi))
    minimum_document_height = max(
        _scaled(32, geometry_dpi),
        _scaled(19, text_dpi),
    )
    minimum_required_height = (
        2 * margin
        + 5 * gap
        + 3 * label_height
        + 3 * button_height
        + 2 * minimum_document_height
    )
    if height < minimum_required_height:
        # Preserve the user's text size while reclaiming only ornamental space
        # on short work areas such as 1366x728 at 400% text scaling.
        margin = min(margin, _scaled(4, _BASE_DPI))
        gap = min(gap, _scaled(4, _BASE_DPI))
    desired_button_width = max(
        _scaled(150, geometry_dpi),
        _scaled(120, text_dpi),
    )
    content_width = width - 2 * margin
    if content_width <= gap:
        raise ValueError("FORMAL_DEMO_CONSOLE_LAYOUT_TOO_SMALL")
    paired_button_width = min(
        desired_button_width,
        max(1, (content_width - gap) // 2),
    )

    desired_ack_label_width = max(
        _scaled(170, geometry_dpi),
        _scaled(130, text_dpi),
    )
    desired_ack_width = max(
        _scaled(190, geometry_dpi),
        _scaled(140, text_dpi),
    )
    ack_section_height = max(label_height, button_height)
    fixed_height = (
        2 * margin
        + 4 * gap
        + label_height * 3
        + button_height
        + ack_section_height
        + gap
        + button_height
    )
    document_height = height - fixed_height
    if document_height < 2 * minimum_document_height:
        raise ValueError("FORMAL_DEMO_CONSOLE_LAYOUT_TOO_SMALL")
    task_height = min(
        desired_task_height,
        max(minimum_document_height, document_height // 3),
    )
    detail_height = document_height - task_height
    y = margin

    mode = (margin, y, content_width, label_height)
    y += label_height + gap
    task_label = (margin, y, content_width, label_height)
    y += label_height
    task_edit = (margin, y, content_width, task_height)
    y += task_height + gap
    review_button = (margin, y, paired_button_width, button_height)
    reset_button = (
        margin + paired_button_width + gap,
        y,
        paired_button_width,
        button_height,
    )
    y += button_height + gap
    detail_label = (margin, y, content_width, label_height)
    y += label_height

    detail_edit = (margin, y, content_width, detail_height)
    y += detail_height + gap

    ack_row_height = max(label_height, button_height)
    ack_available = content_width - 2 * gap
    ack_label_width = min(desired_ack_label_width, max(1, ack_available // 3))
    ack_remaining = ack_available - ack_label_width
    ack_edit_width = min(desired_ack_width, max(1, ack_remaining // 2))
    ack_button_width = ack_remaining - ack_edit_width
    ack_label = (margin, y, ack_label_width, ack_row_height)
    ack_edit_x = margin + ack_label_width + gap
    ack_edit = (ack_edit_x, y, ack_edit_width, ack_row_height)
    ack_button = (
        ack_edit_x + ack_edit_width + gap,
        y,
        ack_button_width,
        ack_row_height,
    )
    y += ack_row_height + gap
    start_button = (margin, y, paired_button_width, button_height)
    cancel_button = (
        width - margin - paired_button_width,
        y,
        paired_button_width,
        button_height,
    )
    return ConsoleLayout(
        mode=mode,
        task_label=task_label,
        task_edit=task_edit,
        review_button=review_button,
        reset_button=reset_button,
        detail_label=detail_label,
        detail_edit=detail_edit,
        ack_label=ack_label,
        ack_edit=ack_edit,
        ack_button=ack_button,
        start_button=start_button,
        cancel_button=cancel_button,
    )


class Win32FormalDemoConsoleApi:
    """One focus-taking native review window with no execution callback."""

    _class_sequence = 0

    def __init__(
        self,
        *,
        accessibility: OperatorAccessibilitySettings | None = None,
    ) -> None:
        enable_dpi_awareness()
        self.accessibility = accessibility or resolve_operator_accessibility(
            force_high_contrast=False,
            force_reduced_motion=False,
        )
        if not isinstance(self.accessibility, OperatorAccessibilitySettings):
            raise ValueError("FORMAL_DEMO_CONSOLE_ACCESSIBILITY_INVALID")
        self._user32 = private_windll("user32")
        self._kernel32 = private_windll("kernel32")
        self._gdi32 = private_windll("gdi32")
        self._controls: dict[int, _Controls] = {}
        self._callbacks: dict[int, FormalDemoConsoleCallbacks] = {}
        self._fonts: dict[int, int] = {}
        self._closing: set[int] = set()
        self._running_windows: set[int] = set()
        self._faulted_windows: set[int] = set()
        self._restoring_layout: set[int] = set()
        self._dpi_overrides: dict[int, int] = {}
        self._disposed = False
        self._configure_apis()
        self._msftedit_module = self._kernel32.GetModuleHandleW("Msftedit.dll")
        self._owns_msftedit_module = False
        if not self._msftedit_module:
            self._msftedit_module = self._kernel32.LoadLibraryW("Msftedit.dll")
            self._owns_msftedit_module = bool(self._msftedit_module)
        if not self._msftedit_module:
            raise OSError("FORMAL_DEMO_CONSOLE_RICH_EDIT_UNAVAILABLE")
        self._wndproc = _WNDPROC(self._on_message)
        Win32FormalDemoConsoleApi._class_sequence += 1
        self._class_name = (
            f"GdaFormalDemoReview_{id(self)}_{self._class_sequence}"
        )
        self._class_registered = False
        try:
            self._register_class()
            self._class_registered = True
        except Exception:
            if self._owns_msftedit_module:
                self._kernel32.FreeLibrary(self._msftedit_module)
            raise

    def create(self, *, title: str, callbacks: FormalDemoConsoleCallbacks) -> int:
        if not isinstance(title, str) or not title or not isinstance(
            callbacks, FormalDemoConsoleCallbacks
        ):
            raise ValueError("FORMAL_DEMO_CONSOLE_CREATE_INVALID")
        style = _CONSOLE_WINDOW_STYLE
        ex_style = _CONSOLE_WINDOW_EX_STYLE
        dpi = self._system_dpi()
        desired_client_width, desired_client_height = _client_size(
            dpi,
            self.accessibility.text_scale_factor,
        )
        desired_width, desired_height = self._outer_size(
            desired_client_width,
            desired_client_height,
            style=style,
            ex_style=ex_style,
            dpi=dpi,
        )
        x, y, width, height = _bounded_window_rect(
            desired_width,
            desired_height,
            self._work_area(),
        )
        hwnd = self._user32.CreateWindowExW(
            ex_style,
            self._class_name,
            title,
            style,
            x,
            y,
            width,
            height,
            None,
            None,
            self._hinstance(),
            None,
        )
        if not hwnd:
            raise OSError("FORMAL_DEMO_CONSOLE_CREATE_FAILED")
        key = int(hwnd)
        self._callbacks[key] = callbacks
        try:
            self._controls[key] = self._create_controls(key)
            self._layout(key)
        except Exception:
            self._callbacks.pop(key, None)
            self._user32.DestroyWindow(wintypes.HWND(key))
            raise
        return key

    def apply(self, hwnd: int, view: FormalDemoConsoleView) -> None:
        if type(view) is not FormalDemoConsoleView:
            raise ValueError("FORMAL_DEMO_CONSOLE_VIEW_INVALID")
        controls = self._controls[int(hwnd)]
        self._set_text(controls.mode, CONSOLE_MODE_LABEL)
        self._set_text(controls.task_edit, view.task_text)
        self._set_text(controls.detail_edit, view.detail_text)
        if view.stage is not FormalDemoConsoleStage.DISCLOSURE_READY:
            self._set_text(controls.ack_edit, "")
        self._enable(controls.task_edit, view.task_editable)
        self._enable(controls.review_button, view.review_enabled)
        self._enable(controls.ack_edit, view.acknowledgement_enabled)
        self._enable(controls.ack_button, view.acknowledgement_enabled)
        self._enable(
            controls.reset_button,
            view.stage is not FormalDemoConsoleStage.CANCELLED,
        )
        self._enable(controls.start_button, False)
        if self._is_enabled(controls.start_button):
            raise OSError("FORMAL_DEMO_CONSOLE_START_ENABLE_FAILED")
        focus_target = {
            FormalDemoConsoleStage.DRAFT: controls.task_edit,
            FormalDemoConsoleStage.DISCLOSURE_READY: controls.ack_edit,
            FormalDemoConsoleStage.PERMIT_ISSUED: controls.reset_button,
            FormalDemoConsoleStage.CANCELLED: controls.cancel_button,
        }[view.stage]
        self._user32.SetFocus(wintypes.HWND(focus_target))

    def read_task(self, hwnd: int) -> str:
        return self._read_text(self._controls[int(hwnd)].task_edit)

    def read_acknowledgement(self, hwnd: int) -> str:
        return self._read_text(self._controls[int(hwnd)].ack_edit)

    def focus_task(self, hwnd: int) -> None:
        controls = self._controls[int(hwnd)]
        if self._is_enabled(controls.task_edit):
            self._user32.SetFocus(wintypes.HWND(controls.task_edit))

    def show(self, hwnd: int) -> None:
        self._user32.ShowWindow(wintypes.HWND(hwnd), _SW_SHOW)
        self._user32.UpdateWindow(wintypes.HWND(hwnd))

    def run(self, hwnd: int) -> int:
        if int(hwnd) not in self._controls:
            raise ValueError("FORMAL_DEMO_CONSOLE_WINDOW_INVALID")
        key = int(hwnd)
        self._running_windows.add(key)
        message = wintypes.MSG()
        try:
            while True:
                result = int(
                    self._user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                )
                if result == 0:
                    if key in self._faulted_windows:
                        self._faulted_windows.discard(key)
                        raise OSError("FORMAL_DEMO_CONSOLE_NATIVE_CALLBACK_FAILED")
                    return 0
                if result < 0:
                    raise OSError("FORMAL_DEMO_CONSOLE_MESSAGE_LOOP_FAILED")
                if self._route_message(key, message):
                    continue
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))
        finally:
            self._running_windows.discard(key)

    def destroy(self, hwnd: int) -> None:
        key = int(hwnd)
        if key in self._closing:
            return
        if not self._user32.IsWindow(wintypes.HWND(key)):
            self._cleanup(key)
            return
        self._closing.add(key)
        if not self._user32.DestroyWindow(wintypes.HWND(key)):
            self._closing.discard(key)
            raise OSError("FORMAL_DEMO_CONSOLE_DESTROY_FAILED")

    def dispose(self) -> None:
        """Release the one-shot native class and any owned RichEdit module."""

        if self._disposed:
            return
        for hwnd in tuple(self._controls):
            self.destroy(hwnd)
        if self._controls:
            raise OSError("FORMAL_DEMO_CONSOLE_DISPOSE_FAILED")
        if self._class_registered:
            if not self._user32.UnregisterClassW(
                self._class_name,
                self._hinstance(),
            ):
                raise OSError("FORMAL_DEMO_CONSOLE_DISPOSE_FAILED")
            self._class_registered = False
        if self._owns_msftedit_module:
            if not self._kernel32.FreeLibrary(self._msftedit_module):
                raise OSError("FORMAL_DEMO_CONSOLE_DISPOSE_FAILED")
            self._owns_msftedit_module = False
        self._disposed = True

    def start_control_enabled(self, hwnd: int) -> bool:
        """Expose the actual native state for bounded smoke verification."""

        return self._is_enabled(self._controls[int(hwnd)].start_button)

    def _on_message(
        self,
        hwnd: wintypes.HWND,
        message: int,
        wparam: int,
        lparam: int,
    ) -> int:
        try:
            return self._dispatch_message(hwnd, message, wparam, lparam)
        except BaseException:
            # Python exceptions cannot safely cross the Win32 callback ABI. Close
            # the local-only window and abandon the attempt instead.
            key = int(hwnd)
            self._faulted_windows.add(key)
            try:
                if key in self._controls:
                    self.destroy(key)
            except BaseException:
                pass
            return 0

    def _dispatch_message(
        self,
        hwnd: wintypes.HWND,
        message: int,
        wparam: int,
        lparam: int,
    ) -> int:
        key = int(hwnd)
        if message == _WM_COMMAND:
            control_id = int(wparam) & 0xFFFF
            notification = (int(wparam) >> 16) & 0xFFFF
            if notification == _BN_CLICKED:
                callbacks = self._callbacks.get(key)
                if callbacks is not None:
                    handlers = {
                        _REVIEW_BUTTON_ID: callbacks.on_review,
                        _RESET_BUTTON_ID: callbacks.on_reset,
                        _ACK_BUTTON_ID: callbacks.on_acknowledge,
                        _CANCEL_BUTTON_ID: callbacks.on_cancel,
                    }
                    handler = handlers.get(control_id)
                    if handler is not None:
                        handler()
                        return 0
                    if control_id == _START_BUTTON_ID:
                        return 0
        elif message == _WM_KEYDOWN and int(wparam) == _VK_ESCAPE:
            callbacks = self._callbacks.get(key)
            if callbacks is not None:
                callbacks.on_cancel()
                return 0
        elif (
            message == _WM_SIZE
            and int(wparam) != _SIZE_MINIMIZED
            and key in self._controls
        ):
            self._layout(key)
            return 0
        elif message == _WM_DPICHANGED and key in self._controls:
            dpi = int(wparam) & 0xFFFF
            if not _BASE_DPI <= dpi <= 768 or not lparam:
                raise OSError("FORMAL_DEMO_CONSOLE_DPI_CHANGE_INVALID")
            self._dpi_overrides[key] = dpi
            suggested = ctypes.cast(
                lparam,
                ctypes.POINTER(wintypes.RECT),
            ).contents
            work_area = self._monitor_work_area_for_rect(suggested)
            x, y, width, height = _bounded_window_at(
                int(suggested.left),
                int(suggested.top),
                int(suggested.right - suggested.left),
                int(suggested.bottom - suggested.top),
                work_area,
            )
            if not self._user32.SetWindowPos(
                hwnd,
                None,
                x,
                y,
                width,
                height,
                _SWP_NOZORDER | _SWP_NOACTIVATE,
            ):
                raise OSError("FORMAL_DEMO_CONSOLE_DPI_CHANGE_FAILED")
            self._replace_font(key, dpi)
            self._layout(key)
            return 0
        elif message == _WM_CLOSE:
            callbacks = self._callbacks.get(key)
            if callbacks is not None:
                callbacks.on_cancel()
            else:
                self.destroy(key)
            return 0
        elif message == _WM_DESTROY:
            running = key in self._running_windows
            self._cleanup(key)
            if running:
                self._user32.PostQuitMessage(0)
            return 0
        return int(self._user32.DefWindowProcW(hwnd, message, wparam, lparam))

    def _route_message(self, hwnd: int, message: wintypes.MSG) -> bool:
        """Route modeless keyboard navigation before ordinary dispatch."""

        message_hwnd = int(message.hWnd or 0)
        belongs_to_window = message_hwnd == hwnd or bool(
            self._user32.IsChild(
                wintypes.HWND(hwnd),
                wintypes.HWND(message_hwnd),
            )
        )
        if (
            belongs_to_window
            and int(message.message) == _WM_KEYDOWN
            and int(message.wParam) == _VK_ESCAPE
        ):
            callbacks = self._callbacks.get(hwnd)
            if callbacks is not None:
                callbacks.on_cancel()
            return True
        if (
            belongs_to_window
            and int(message.message) == _WM_KEYDOWN
            and int(message.wParam) == _VK_TAB
        ):
            reverse = int(self._user32.GetKeyState(_VK_SHIFT)) < 0
            target = self._user32.GetNextDlgTabItem(
                wintypes.HWND(hwnd),
                wintypes.HWND(message_hwnd),
                reverse,
            )
            if target:
                self._user32.SetFocus(target)
            return True
        return bool(
            self._user32.IsDialogMessageW(
                wintypes.HWND(hwnd),
                ctypes.byref(message),
            )
        )

    def _create_controls(self, hwnd: int) -> _Controls:
        create = self._create_control
        controls = _Controls(
            mode=create(hwnd, "STATIC", CONSOLE_MODE_LABEL, _SS_LEFT | _SS_NOPREFIX, _MODE_LABEL_ID),
            task_label=create(hwnd, "STATIC", "Task (local memory only)", _SS_LEFT | _SS_NOPREFIX, _TASK_LABEL_ID),
            task_edit=create(
                hwnd,
                "EDIT",
                "",
                _WS_TABSTOP | _ES_LEFT | _ES_MULTILINE | _ES_AUTOVSCROLL,
                _TASK_EDIT_ID,
                ex_style=_WS_EX_CLIENTEDGE,
            ),
            review_button=create(hwnd, "BUTTON", "Review disclosure", _WS_TABSTOP | _BS_PUSHBUTTON, _REVIEW_BUTTON_ID),
            reset_button=create(hwnd, "BUTTON", "Reset draft", _WS_TABSTOP | _BS_PUSHBUTTON, _RESET_BUTTON_ID),
            detail_label=create(hwnd, "STATIC", "Review details (read only)", _SS_LEFT | _SS_NOPREFIX, _DETAIL_LABEL_ID),
            detail_edit=create(
                hwnd,
                "RICHEDIT50W",
                "",
                _WS_VSCROLL | _ES_LEFT | _ES_MULTILINE | _ES_AUTOVSCROLL | _ES_READONLY,
                _DETAIL_EDIT_ID,
                ex_style=_WS_EX_CLIENTEDGE,
            ),
            ack_label=create(hwnd, "STATIC", "Exact COMPILE", _SS_LEFT | _SS_NOPREFIX, _ACK_LABEL_ID),
            ack_edit=create(
                hwnd,
                "EDIT",
                "",
                _WS_TABSTOP | _ES_LEFT | _ES_AUTOHSCROLL,
                _ACK_EDIT_ID,
                ex_style=_WS_EX_CLIENTEDGE,
            ),
            ack_button=create(hwnd, "BUTTON", "Issue permit", _WS_TABSTOP | _BS_PUSHBUTTON, _ACK_BUTTON_ID),
            start_button=create(
                hwnd,
                "BUTTON",
                "Start unavailable",
                _WS_DISABLED | _BS_PUSHBUTTON,
                _START_BUTTON_ID,
            ),
            cancel_button=create(hwnd, "BUTTON", "Close safely", _WS_TABSTOP | _BS_PUSHBUTTON, _CANCEL_BUTTON_ID),
        )
        self._user32.SendMessageW(
            wintypes.HWND(controls.task_edit),
            _EM_SETLIMITTEXT,
            _TASK_EDIT_CHAR_LIMIT,
            0,
        )
        self._user32.SendMessageW(
            wintypes.HWND(controls.ack_edit),
            _EM_SETLIMITTEXT,
            _ACK_EDIT_CHAR_LIMIT,
            0,
        )
        dpi = self._dpi(hwnd)
        font = self._create_font(dpi)
        self._fonts[hwnd] = font
        for control in controls.all_handles():
            self._user32.SendMessageW(
                wintypes.HWND(control),
                _WM_SETFONT,
                wintypes.WPARAM(font),
                1,
            )
        return controls

    def _create_control(
        self,
        parent: int,
        class_name: str,
        text: str,
        style: int,
        control_id: int,
        *,
        ex_style: int = 0,
    ) -> int:
        hwnd = self._user32.CreateWindowExW(
            ex_style,
            class_name,
            text,
            _WS_CHILD | _WS_VISIBLE | style,
            0,
            0,
            1,
            1,
            wintypes.HWND(parent),
            wintypes.HMENU(control_id),
            self._hinstance(),
            None,
        )
        if not hwnd:
            raise OSError("FORMAL_DEMO_CONSOLE_CONTROL_CREATE_FAILED")
        return int(hwnd)

    def _layout(self, hwnd: int) -> None:
        controls = self._controls[hwnd]
        client = wintypes.RECT()
        if not self._user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(client)):
            raise OSError("FORMAL_DEMO_CONSOLE_LAYOUT_FAILED")
        width = int(client.right - client.left)
        height = int(client.bottom - client.top)
        try:
            layout = _layout_rects(
                width,
                height,
                self._dpi(hwnd),
                text_scale_factor=self.accessibility.text_scale_factor,
            )
        except ValueError:
            # Snap an undersized resizable window back to one work-area-bounded
            # layout instead of leaving critical controls outside the viewport.
            if hwnd in self._restoring_layout:
                return
            self._restoring_layout.add(hwnd)
            try:
                restored = self._restore_layout_window(hwnd)
            finally:
                self._restoring_layout.discard(hwnd)
            if restored:
                self._layout(hwnd)
            return
        pairs = (
            (controls.mode, layout.mode),
            (controls.task_label, layout.task_label),
            (controls.task_edit, layout.task_edit),
            (controls.review_button, layout.review_button),
            (controls.reset_button, layout.reset_button),
            (controls.detail_label, layout.detail_label),
            (controls.detail_edit, layout.detail_edit),
            (controls.ack_label, layout.ack_label),
            (controls.ack_edit, layout.ack_edit),
            (controls.ack_button, layout.ack_button),
            (controls.start_button, layout.start_button),
            (controls.cancel_button, layout.cancel_button),
        )
        for control, (x, y, width, height) in pairs:
            if not self._user32.MoveWindow(
                wintypes.HWND(control), x, y, width, height, True
            ):
                raise OSError("FORMAL_DEMO_CONSOLE_LAYOUT_FAILED")

    def _read_text(self, control: int) -> str:
        length = int(self._user32.GetWindowTextLengthW(wintypes.HWND(control)))
        if length < 0 or length > _MAX_NATIVE_TEXT_CHARS:
            raise ValueError("FORMAL_DEMO_CONSOLE_NATIVE_TEXT_INVALID")
        buffer = ctypes.create_unicode_buffer(length + 1)
        copied = int(
            self._user32.GetWindowTextW(
                wintypes.HWND(control),
                buffer,
                length + 1,
            )
        )
        if copied != length:
            raise OSError("FORMAL_DEMO_CONSOLE_NATIVE_TEXT_CHANGED")
        return buffer.value

    def _set_text(self, control: int, value: str) -> None:
        if not isinstance(value, str) or len(value) > _MAX_NATIVE_TEXT_CHARS:
            raise ValueError("FORMAL_DEMO_CONSOLE_NATIVE_TEXT_INVALID")
        rendered = value.replace("\r\n", "\n").replace("\n", "\r\n")
        if not self._user32.SetWindowTextW(wintypes.HWND(control), rendered):
            raise OSError("FORMAL_DEMO_CONSOLE_NATIVE_TEXT_FAILED")

    def _enable(self, control: int, enabled: bool) -> None:
        self._user32.EnableWindow(wintypes.HWND(control), bool(enabled))

    def _is_enabled(self, control: int) -> bool:
        return bool(self._user32.IsWindowEnabled(wintypes.HWND(control)))

    def _dpi(self, hwnd: int) -> int:
        overridden = self._dpi_overrides.get(int(hwnd))
        if overridden is not None:
            return overridden
        try:
            observed = int(self._user32.GetDpiForWindow(wintypes.HWND(hwnd)))
        except (AttributeError, OSError):
            observed = _BASE_DPI
        return observed if _BASE_DPI <= observed <= 768 else _BASE_DPI

    def _system_dpi(self) -> int:
        try:
            observed = int(self._user32.GetDpiForSystem())
        except (AttributeError, OSError):
            observed = _BASE_DPI
        return observed if _BASE_DPI <= observed <= 768 else _BASE_DPI

    def _outer_size(
        self,
        client_width: int,
        client_height: int,
        *,
        style: int,
        ex_style: int,
        dpi: int,
    ) -> tuple[int, int]:
        rect = wintypes.RECT(0, 0, client_width, client_height)
        adjusted = False
        try:
            adjusted = bool(
                self._user32.AdjustWindowRectExForDpi(
                    ctypes.byref(rect),
                    style,
                    False,
                    ex_style,
                    dpi,
                )
            )
        except (AttributeError, OSError):
            adjusted = False
        if not adjusted:
            rect = wintypes.RECT(0, 0, client_width, client_height)
            adjusted = bool(
                self._user32.AdjustWindowRectEx(
                    ctypes.byref(rect),
                    style,
                    False,
                    ex_style,
                )
            )
        if not adjusted:
            raise OSError("FORMAL_DEMO_CONSOLE_WINDOW_RECT_FAILED")
        return int(rect.right - rect.left), int(rect.bottom - rect.top)

    def _work_area(self) -> tuple[int, int, int, int]:
        work = wintypes.RECT()
        if self._user32.SystemParametersInfoW(
            _SPI_GETWORKAREA,
            0,
            ctypes.byref(work),
            0,
        ):
            return (int(work.left), int(work.top), int(work.right), int(work.bottom))
        return (
            0,
            0,
            int(self._user32.GetSystemMetrics(0)),
            int(self._user32.GetSystemMetrics(1)),
        )

    def _monitor_work_area_for_rect(
        self,
        rect: wintypes.RECT,
    ) -> tuple[int, int, int, int]:
        monitor = self._user32.MonitorFromRect(
            ctypes.byref(rect),
            _MONITOR_DEFAULTTONEAREST,
        )
        return self._monitor_work_area(monitor)

    def _monitor_work_area_for_window(self, hwnd: int) -> tuple[int, int, int, int]:
        monitor = self._user32.MonitorFromWindow(
            wintypes.HWND(hwnd),
            _MONITOR_DEFAULTTONEAREST,
        )
        return self._monitor_work_area(monitor)

    def _monitor_work_area(self, monitor: int) -> tuple[int, int, int, int]:
        if not monitor:
            return self._work_area()
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(info)
        if not self._user32.GetMonitorInfoW(
            wintypes.HANDLE(monitor),
            ctypes.byref(info),
        ):
            return self._work_area()
        return (
            int(info.rcWork.left),
            int(info.rcWork.top),
            int(info.rcWork.right),
            int(info.rcWork.bottom),
        )

    def _restore_layout_window(self, hwnd: int) -> bool:
        dpi = self._dpi(hwnd)
        client_width, client_height = _client_size(
            dpi,
            self.accessibility.text_scale_factor,
        )
        outer_width, outer_height = self._outer_size(
            client_width,
            client_height,
            style=_CONSOLE_WINDOW_STYLE,
            ex_style=_CONSOLE_WINDOW_EX_STYLE,
            dpi=dpi,
        )
        current = wintypes.RECT()
        if not self._user32.GetWindowRect(
            wintypes.HWND(hwnd),
            ctypes.byref(current),
        ):
            raise OSError("FORMAL_DEMO_CONSOLE_LAYOUT_FAILED")
        x, y, width, height = _bounded_window_at(
            int(current.left),
            int(current.top),
            outer_width,
            outer_height,
            self._monitor_work_area_for_window(hwnd),
        )
        if (
            int(current.left) == x
            and int(current.top) == y
            and int(current.right - current.left) == width
            and int(current.bottom - current.top) == height
        ):
            return False
        if not self._user32.SetWindowPos(
            wintypes.HWND(hwnd),
            None,
            x,
            y,
            width,
            height,
            _SWP_NOZORDER | _SWP_NOACTIVATE,
        ):
            raise OSError("FORMAL_DEMO_CONSOLE_LAYOUT_FAILED")
        return True

    def _create_font(self, dpi: int) -> int:
        text_dpi = effective_text_dpi(
            dpi,
            self.accessibility.text_scale_factor,
        )
        height = -max(12, round(10 * text_dpi / 72))
        font = self._gdi32.CreateFontW(
            height,
            0,
            0,
            0,
            _FW_NORMAL,
            False,
            False,
            False,
            1,
            _OUT_DEFAULT_PRECIS,
            _CLIP_DEFAULT_PRECIS,
            _CLEARTYPE_QUALITY,
            _DEFAULT_PITCH | _FF_DONTCARE,
            "Segoe UI",
        )
        if not font:
            raise OSError("FORMAL_DEMO_CONSOLE_FONT_UNAVAILABLE")
        return int(font)

    def _replace_font(self, hwnd: int, dpi: int) -> None:
        controls = self._controls[hwnd]
        replacement = self._create_font(dpi)
        for control in controls.all_handles():
            self._user32.SendMessageW(
                wintypes.HWND(control),
                _WM_SETFONT,
                wintypes.WPARAM(replacement),
                1,
            )
        previous = self._fonts.get(hwnd)
        self._fonts[hwnd] = replacement
        if previous:
            self._gdi32.DeleteObject(wintypes.HGDIOBJ(previous))

    def _cleanup(self, hwnd: int) -> None:
        self._controls.pop(hwnd, None)
        self._callbacks.pop(hwnd, None)
        self._closing.discard(hwnd)
        self._dpi_overrides.pop(hwnd, None)
        font = self._fonts.pop(hwnd, None)
        if font:
            self._gdi32.DeleteObject(wintypes.HGDIOBJ(font))

    def _register_class(self) -> None:
        window_class = _WNDCLASSEXW()
        window_class.cbSize = ctypes.sizeof(window_class)
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = self._hinstance()
        window_class.hCursor = self._user32.LoadCursorW(
            None,
            wintypes.LPCWSTR(_IDC_ARROW),
        )
        window_class.hbrBackground = self._user32.GetSysColorBrush(_COLOR_WINDOW)
        window_class.lpszClassName = self._class_name
        if not self._user32.RegisterClassExW(ctypes.byref(window_class)):
            raise OSError("FORMAL_DEMO_CONSOLE_CLASS_REGISTRATION_FAILED")

    def _hinstance(self) -> wintypes.HINSTANCE:
        return wintypes.HINSTANCE(self._kernel32.GetModuleHandleW(None))

    def _configure_apis(self) -> None:
        user32 = self._user32
        kernel32 = self._kernel32
        gdi32 = self._gdi32
        user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        user32.GetSystemMetrics.restype = ctypes.c_int
        user32.GetDpiForSystem.restype = wintypes.UINT
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        user32.GetSysColorBrush.argtypes = [ctypes.c_int]
        user32.GetSysColorBrush.restype = wintypes.HBRUSH
        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        user32.LoadCursorW.restype = wintypes.HANDLE
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.UpdateWindow.argtypes = [wintypes.HWND]
        user32.UpdateWindow.restype = wintypes.BOOL
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        user32.GetFocus.restype = wintypes.HWND
        user32.GetKeyState.argtypes = [ctypes.c_int]
        user32.GetKeyState.restype = ctypes.c_short
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
        user32.GetWindowRect.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.RECT),
        ]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.MonitorFromRect.argtypes = [
            ctypes.POINTER(wintypes.RECT),
            wintypes.DWORD,
        ]
        user32.MonitorFromRect.restype = wintypes.HANDLE
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        user32.SetWindowTextW.restype = wintypes.BOOL
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int
        user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        user32.EnableWindow.restype = wintypes.BOOL
        user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        user32.IsWindowEnabled.restype = wintypes.BOOL
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
        user32.DefWindowProcW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.DefWindowProcW.restype = _LRESULT
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = _LRESULT
        user32.PostQuitMessage.argtypes = [ctypes.c_int]
        user32.GetMessageW.argtypes = [
            ctypes.c_void_p,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = [ctypes.c_void_p]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
        user32.DispatchMessageW.restype = _LRESULT
        user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
        user32.UnregisterClassW.restype = wintypes.BOOL
        user32.IsDialogMessageW.argtypes = [wintypes.HWND, ctypes.c_void_p]
        user32.IsDialogMessageW.restype = wintypes.BOOL
        user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        user32.IsChild.restype = wintypes.BOOL
        user32.GetNextDlgTabItem.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            wintypes.BOOL,
        ]
        user32.GetNextDlgTabItem.restype = wintypes.HWND
        user32.PostMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.AdjustWindowRectEx.argtypes = [
            ctypes.POINTER(wintypes.RECT),
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        user32.AdjustWindowRectEx.restype = wintypes.BOOL
        try:
            user32.AdjustWindowRectExForDpi.argtypes = [
                ctypes.POINTER(wintypes.RECT),
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
                wintypes.UINT,
            ]
            user32.AdjustWindowRectExForDpi.restype = wintypes.BOOL
        except AttributeError:
            pass
        user32.SystemParametersInfoW.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPVOID,
            wintypes.UINT,
        ]
        user32.SystemParametersInfoW.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        kernel32.LoadLibraryW.argtypes = [wintypes.LPCWSTR]
        kernel32.LoadLibraryW.restype = wintypes.HMODULE
        kernel32.FreeLibrary.argtypes = [wintypes.HMODULE]
        kernel32.FreeLibrary.restype = wintypes.BOOL
        gdi32.CreateFontW.argtypes = [
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
        gdi32.CreateFontW.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL


__all__ = [
    "ConsoleLayout",
    "Win32FormalDemoConsoleApi",
    "_bounded_window_rect",
    "_bounded_window_at",
    "_client_size",
    "_layout_rects",
]
