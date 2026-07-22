"""ctypes Win32 backend for the focus-taking local Decision Card."""
from __future__ import annotations

import ctypes
import tempfile
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Iterator

from computer_use_mcp.dpi import enable_dpi_awareness

from .decision_card_window import DecisionCardButton

_IDCANCEL = 2
_TDN_CREATED = 0
_TDN_TIMER = 4
_TDM_CLICK_BUTTON = 0x0400 + 102
_TDF_ALLOW_DIALOG_CANCELLATION = 0x0008
_TDF_USE_COMMAND_LINKS = 0x0010
_TDF_CALLBACK_TIMER = 0x0800
_FIRST_BUTTON_ID = 1001
_SW_RESTORE = 9
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040

_COMMON_CONTROLS_V6_MANIFEST = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity version="1.0.0.0" processorArchitecture="*"
      name="computer-use-agent.decision-card" type="win32"/>
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls"
          version="6.0.0.0" processorArchitecture="*"
          publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
</assembly>
"""


class _ACTCTXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("dwFlags", wintypes.DWORD),
        ("lpSource", wintypes.LPCWSTR),
        ("wProcessorArchitecture", wintypes.USHORT),
        ("wLangId", wintypes.LANGID),
        ("lpAssemblyDirectory", wintypes.LPCWSTR),
        ("lpResourceName", wintypes.LPCWSTR),
        ("lpApplicationName", wintypes.LPCWSTR),
        ("hModule", wintypes.HMODULE),
    ]


class _TASKDIALOG_BUTTON(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("nButtonID", ctypes.c_int),
        ("pszButtonText", wintypes.LPCWSTR),
    ]


_TASKDIALOG_CALLBACK = ctypes.WINFUNCTYPE(
    ctypes.c_long,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    ctypes.c_ssize_t,
)


class _TASKDIALOGCONFIG(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("hwndParent", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("dwFlags", wintypes.UINT),
        ("dwCommonButtons", wintypes.UINT),
        ("pszWindowTitle", wintypes.LPCWSTR),
        ("mainIcon", ctypes.c_void_p),
        ("pszMainInstruction", wintypes.LPCWSTR),
        ("pszContent", wintypes.LPCWSTR),
        ("cButtons", wintypes.UINT),
        ("pButtons", ctypes.POINTER(_TASKDIALOG_BUTTON)),
        ("nDefaultButton", ctypes.c_int),
        ("cRadioButtons", wintypes.UINT),
        ("pRadioButtons", ctypes.POINTER(_TASKDIALOG_BUTTON)),
        ("nDefaultRadioButton", ctypes.c_int),
        ("pszVerificationText", wintypes.LPCWSTR),
        ("pszExpandedInformation", wintypes.LPCWSTR),
        ("pszExpandedControlText", wintypes.LPCWSTR),
        ("pszCollapsedControlText", wintypes.LPCWSTR),
        ("footerIcon", ctypes.c_void_p),
        ("pszFooter", wintypes.LPCWSTR),
        ("pfCallback", _TASKDIALOG_CALLBACK),
        ("lpCallbackData", ctypes.c_ssize_t),
        ("cxWidth", wintypes.UINT),
    ]


class Win32DecisionCardWindowApi:
    """Show a timed two- or three-option Task Dialog with expandable evidence."""

    def __init__(self) -> None:
        enable_dpi_awareness()
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsWindowEnabled.argtypes = [wintypes.HWND]
        self._user32.IsWindowEnabled.restype = wintypes.BOOL
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL
        self._user32.AttachThreadInput.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.BOOL,
        ]
        self._user32.AttachThreadInput.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL
        self._user32.SetFocus.argtypes = [wintypes.HWND]
        self._user32.SetFocus.restype = wintypes.HWND
        self._user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        self._user32.SetWindowPos.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.SendMessageW.restype = wintypes.LPARAM
        self._kernel32.CreateActCtxW.argtypes = [ctypes.POINTER(_ACTCTXW)]
        self._kernel32.CreateActCtxW.restype = wintypes.HANDLE
        self._kernel32.ActivateActCtx.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._kernel32.ActivateActCtx.restype = wintypes.BOOL
        self._kernel32.DeactivateActCtx.argtypes = [wintypes.DWORD, ctypes.c_size_t]
        self._kernel32.DeactivateActCtx.restype = wintypes.BOOL
        self._kernel32.ReleaseActCtx.argtypes = [wintypes.HANDLE]
        self._kernel32.GetCurrentProcessId.restype = wintypes.DWORD
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    @contextmanager
    def _common_controls_v6(self) -> Iterator[None]:
        manifest_path: Path | None = None
        activation = None
        cookie = ctypes.c_size_t()
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".manifest", delete=False
            ) as manifest:
                manifest.write(_COMMON_CONTROLS_V6_MANIFEST)
                manifest_path = Path(manifest.name)
            context = _ACTCTXW()
            context.cbSize = ctypes.sizeof(context)
            context.lpSource = str(manifest_path)
            activation = self._kernel32.CreateActCtxW(ctypes.byref(context))
            if activation == wintypes.HANDLE(-1).value:
                raise OSError("DECISION_CARD_ACTIVATION_CONTEXT_FAILED")
            if not self._kernel32.ActivateActCtx(activation, ctypes.byref(cookie)):
                raise OSError("DECISION_CARD_ACTIVATION_FAILED")
            yield
        finally:
            if cookie.value:
                self._kernel32.DeactivateActCtx(0, cookie)
            if activation not in (None, wintypes.HANDLE(-1).value):
                self._kernel32.ReleaseActCtx(activation)
            if manifest_path is not None:
                manifest_path.unlink(missing_ok=True)

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
        if not 2 <= len(buttons) <= 3:
            raise OSError("DECISION_CARD_NATIVE_REQUIRES_TWO_OR_THREE_OPTIONS")
        foreground_before = self._user32.GetForegroundWindow()
        foreground_process = wintypes.DWORD()
        foreground_thread = 0
        if foreground_before:
            foreground_thread = int(self._user32.GetWindowThreadProcessId(
                foreground_before, ctypes.byref(foreground_process)
            ))
        owner = None
        if (
            foreground_before
            and foreground_process.value == self._kernel32.GetCurrentProcessId()
            and self._user32.IsWindow(foreground_before)
            and self._user32.IsWindowVisible(foreground_before)
            and self._user32.IsWindowEnabled(foreground_before)
        ):
            owner = foreground_before
        native_buttons = (_TASKDIALOG_BUTTON * len(buttons))(
            *(
                _TASKDIALOG_BUTTON(_FIRST_BUTTON_ID + index, button.label)
                for index, button in enumerate(buttons)
            )
        )
        id_to_option = {
            _FIRST_BUTTON_ID + index: button.option_id
            for index, button in enumerate(buttons)
        }
        deny_id = next(
            (
                button_id
                for button_id, button in zip(id_to_option, buttons, strict=True)
                if button.option_id == "option_deny"
            ),
            _FIRST_BUTTON_ID + len(buttons) - 1,
        )

        @_TASKDIALOG_CALLBACK
        def callback(hwnd, notification, wparam, _lparam, _data):  # noqa: ANN001
            if notification == _TDN_CREATED:
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
                        wintypes.HWND(-1),
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
            if notification == _TDN_TIMER and int(wparam) >= timeout_seconds * 1000:
                self._user32.SendMessageW(hwnd, _TDM_CLICK_BUTTON, _IDCANCEL, 0)
            return 0

        config = _TASKDIALOGCONFIG()
        config.cbSize = ctypes.sizeof(config)
        config.hwndParent = owner
        config.dwFlags = (
            _TDF_ALLOW_DIALOG_CANCELLATION
            | _TDF_USE_COMMAND_LINKS
            | _TDF_CALLBACK_TIMER
        )
        config.pszWindowTitle = title
        config.pszMainInstruction = instruction
        config.pszContent = content
        config.cButtons = len(buttons)
        config.pButtons = native_buttons
        config.nDefaultButton = deny_id
        config.pszExpandedInformation = expanded_information
        config.pszExpandedControlText = "Hide bounded evidence"
        config.pszCollapsedControlText = "Show bounded evidence"
        config.pfCallback = callback
        selected = ctypes.c_int()
        try:
            with self._common_controls_v6():
                task_dialog = ctypes.WinDLL("comctl32.dll").TaskDialogIndirect
                task_dialog.argtypes = [
                    ctypes.POINTER(_TASKDIALOGCONFIG),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(ctypes.c_int),
                    ctypes.POINTER(wintypes.BOOL),
                ]
                task_dialog.restype = ctypes.c_long
                result = int(
                    task_dialog(
                        ctypes.byref(config), ctypes.byref(selected), None, None
                    )
                )
                if result < 0:
                    raise OSError(
                        f"DECISION_CARD_NATIVE_DIALOG_FAILED_{result & 0xFFFFFFFF:08X}"
                    )
        finally:
            if foreground_before and self._user32.IsWindow(foreground_before):
                self._user32.SetForegroundWindow(foreground_before)
        return id_to_option.get(selected.value)


__all__ = ["Win32DecisionCardWindowApi"]
