"""Win32 global-hotkey loop for the bounded ShortcutBroker."""

from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from enum import Enum
from collections.abc import Callable
from typing import Protocol
from ctypes import wintypes

from .shortcut_broker import ShortcutAction
from .win32_dll import private_windll


MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
OPEN_CONTROLS_HOTKEY_ID = 0x4744
REQUEST_PAUSE_HOTKEY_ID = 0x5044
_WM_TIMER = 0x0113
_WM_HOTKEY = 0x0312
_TIMER_ID = 0x5342
_DEFAULT_TIMER_INTERVAL_MS = 100
_SW_RESTORE = 9


class ShortcutRegistrationError(RuntimeError):
    """Fixed registration or message-loop failure without key-state content."""


class ShortcutLoopEvent(str, Enum):
    OPEN_CONTROLS = "open_controls"
    REQUEST_PAUSE = "request_pause"
    TICK = "tick"
    STOP = "stop"


class ShortcutLoopApi(Protocol):
    def register_hotkey(
        self, identifier: int, modifiers: int, virtual_key: int
    ) -> bool: ...

    def unregister_hotkey(self, identifier: int) -> None: ...

    def start_timer(self, interval_ms: int) -> None: ...

    def stop_timer(self) -> None: ...

    def next_event(self) -> ShortcutLoopEvent: ...


class ShortcutBrokerPort(Protocol):
    def handle(self, action: ShortcutAction) -> None: ...

    def poll(self) -> None: ...


@dataclass(frozen=True)
class _HotkeySpec:
    identifier: int
    action: ShortcutAction
    virtual_key: int
    conflict_code: str


_HOTKEY_SPECS = (
    _HotkeySpec(
        OPEN_CONTROLS_HOTKEY_ID,
        ShortcutAction.OPEN_CONTROLS,
        ord("G"),
        "SHORTCUT_CONFLICT_OPEN_CONTROLS",
    ),
    _HotkeySpec(
        REQUEST_PAUSE_HOTKEY_ID,
        ShortcutAction.REQUEST_PAUSE,
        ord("P"),
        "SHORTCUT_CONFLICT_REQUEST_PAUSE",
    ),
)


class GlobalShortcutLoop:
    """Atomically own G/P registration and route content-free events."""

    def __init__(
        self,
        api: ShortcutLoopApi,
        *,
        timer_interval_ms: int = _DEFAULT_TIMER_INTERVAL_MS,
    ) -> None:
        if (
            not callable(getattr(api, "register_hotkey", None))
            or not callable(getattr(api, "unregister_hotkey", None))
            or not callable(getattr(api, "start_timer", None))
            or not callable(getattr(api, "stop_timer", None))
            or not callable(getattr(api, "next_event", None))
            or isinstance(timer_interval_ms, bool)
            or not isinstance(timer_interval_ms, int)
            or not 25 <= timer_interval_ms <= 5_000
        ):
            raise ShortcutRegistrationError("SHORTCUT_LOOP_CONFIG_INVALID")
        self._api = api
        self._timer_interval_ms = timer_interval_ms

    def run(
        self,
        broker: ShortcutBrokerPort,
        *,
        on_registered: Callable[[], object] | None = None,
    ) -> int:
        if not callable(getattr(broker, "handle", None)) or not callable(
            getattr(broker, "poll", None)
        ) or (on_registered is not None and not callable(on_registered)):
            raise ShortcutRegistrationError("SHORTCUT_BROKER_INVALID")
        registered: list[int] = []
        timer_started = False
        handled = 0
        modifiers = MOD_ALT | MOD_CONTROL | MOD_NOREPEAT
        try:
            for spec in _HOTKEY_SPECS:
                if not self._api.register_hotkey(
                    spec.identifier,
                    modifiers,
                    spec.virtual_key,
                ):
                    raise ShortcutRegistrationError(spec.conflict_code)
                registered.append(spec.identifier)
            self._api.start_timer(self._timer_interval_ms)
            timer_started = True
            if on_registered is not None:
                on_registered()
            while True:
                event = self._api.next_event()
                if not isinstance(event, ShortcutLoopEvent):
                    raise ShortcutRegistrationError("SHORTCUT_MESSAGE_INVALID")
                if event is ShortcutLoopEvent.STOP:
                    break
                if event is ShortcutLoopEvent.OPEN_CONTROLS:
                    broker.handle(ShortcutAction.OPEN_CONTROLS)
                elif event is ShortcutLoopEvent.REQUEST_PAUSE:
                    broker.handle(ShortcutAction.REQUEST_PAUSE)
                else:
                    broker.poll()
                handled += 1
            return handled
        finally:
            if timer_started:
                self._api.stop_timer()
            for identifier in reversed(registered):
                self._api.unregister_hotkey(identifier)


class Win32GlobalShortcutApi:
    """Thread-message adapter with no window or desktop action capability."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise ShortcutRegistrationError("SHORTCUT_WINDOWS_REQUIRED")
        user32 = private_windll("user32")
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL
        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL
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
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = ctypes.c_int
        user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.TranslateMessage.restype = wintypes.BOOL
        user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
        user32.DispatchMessageW.restype = wintypes.LPARAM
        self._user32 = user32
        self._timer_id: int | None = None

    def register_hotkey(self, identifier: int, modifiers: int, virtual_key: int) -> bool:
        return bool(self._user32.RegisterHotKey(None, identifier, modifiers, virtual_key))

    def unregister_hotkey(self, identifier: int) -> None:
        self._user32.UnregisterHotKey(None, identifier)

    def start_timer(self, interval_ms: int) -> None:
        if self._timer_id is not None:
            raise ShortcutRegistrationError("SHORTCUT_TIMER_ALREADY_STARTED")
        timer_id = int(self._user32.SetTimer(None, _TIMER_ID, interval_ms, None))
        if not timer_id:
            raise ShortcutRegistrationError("SHORTCUT_TIMER_START_FAILED")
        self._timer_id = timer_id

    def stop_timer(self) -> None:
        timer_id = self._timer_id
        self._timer_id = None
        if timer_id is not None:
            self._user32.KillTimer(None, timer_id)

    def next_event(self) -> ShortcutLoopEvent:
        while True:
            message = wintypes.MSG()
            result = int(self._user32.GetMessageW(ctypes.byref(message), None, 0, 0))
            if result == -1:
                raise ShortcutRegistrationError("SHORTCUT_MESSAGE_LOOP_FAILED")
            if result == 0:
                return ShortcutLoopEvent.STOP
            if message.message == _WM_HOTKEY:
                identifier = int(message.wParam)
                if identifier == OPEN_CONTROLS_HOTKEY_ID:
                    return ShortcutLoopEvent.OPEN_CONTROLS
                if identifier == REQUEST_PAUSE_HOTKEY_ID:
                    return ShortcutLoopEvent.REQUEST_PAUSE
            elif message.message == _WM_TIMER and int(message.wParam) == self._timer_id:
                return ShortcutLoopEvent.TICK
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))


class Win32ConsoleForeground:
    """Bring only this explicitly started console host to the foreground."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise ShortcutRegistrationError("SHORTCUT_WINDOWS_REQUIRED")
        kernel32 = private_windll("kernel32")
        user32 = private_windll("user32")
        kernel32.GetConsoleWindow.argtypes = []
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        self._kernel32 = kernel32
        self._user32 = user32

    def show(self) -> bool:
        hwnd = self._kernel32.GetConsoleWindow()
        if not hwnd:
            return False
        self._user32.ShowWindow(hwnd, _SW_RESTORE)
        return bool(self._user32.SetForegroundWindow(hwnd))


__all__ = [
    "MOD_ALT",
    "MOD_CONTROL",
    "MOD_NOREPEAT",
    "OPEN_CONTROLS_HOTKEY_ID",
    "REQUEST_PAUSE_HOTKEY_ID",
    "GlobalShortcutLoop",
    "ShortcutLoopApi",
    "ShortcutLoopEvent",
    "ShortcutRegistrationError",
    "Win32ConsoleForeground",
    "Win32GlobalShortcutApi",
]
