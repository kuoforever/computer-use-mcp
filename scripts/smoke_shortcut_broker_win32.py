"""Retain non-input Windows evidence for the bounded ShortcutBroker.

The harness uses real Win32 hotkey registration and a real thread message
queue, but it never synthesizes keyboard or mouse input.  Cross-process holder
workers prove conflict, rollback, release, and reacquisition behavior.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any

from computer_use_agent.shortcut_broker import ShortcutAction
from computer_use_agent.shortcut_broker_win32 import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    OPEN_CONTROLS_HOTKEY_ID,
    REQUEST_PAUSE_HOTKEY_ID,
    GlobalShortcutLoop,
    ShortcutRegistrationError,
    Win32GlobalShortcutApi,
)
from computer_use_agent.win32_dll import private_windll


_MODIFIERS = MOD_ALT | MOD_CONTROL | MOD_NOREPEAT
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_HOLDER_TIMEOUT_SECONDS = 15.0
_PROCESS_TIMEOUT_SECONDS = 10.0


class ShortcutEvidenceError(RuntimeError):
    """Fixed native-evidence failure without desktop content."""


class _RecordingBroker:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.polls = 0

    def handle(self, action: ShortcutAction) -> None:
        self.actions.append(action.value)

    def poll(self) -> None:
        self.polls += 1


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _hotkey_specs(mode: str) -> tuple[tuple[int, int], ...]:
    if mode == "hold-both":
        return (
            (OPEN_CONTROLS_HOTKEY_ID, ord("G")),
            (REQUEST_PAUSE_HOTKEY_ID, ord("P")),
        )
    if mode == "hold-p":
        return ((REQUEST_PAUSE_HOTKEY_ID, ord("P")),)
    raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_WORKER_INVALID")


def _holder_worker(mode: str, ready: Path, stop: Path) -> int:
    api = Win32GlobalShortcutApi()
    registered: list[int] = []
    try:
        for identifier, virtual_key in _hotkey_specs(mode):
            if not api.register_hotkey(identifier, _MODIFIERS, virtual_key):
                _write_json(
                    ready,
                    {"ready": False, "code": "SHORTCUT_EVIDENCE_HOLDER_CONFLICT"},
                )
                return 2
            registered.append(identifier)
        _write_json(ready, {"ready": True, "mode": mode})
        deadline = time.monotonic() + _HOLDER_TIMEOUT_SECONDS
        while not stop.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        return 0 if stop.exists() else 3
    finally:
        for identifier in reversed(registered):
            api.unregister_hotkey(identifier)


def _configure_thread_messaging() -> tuple[Any, Any]:
    kernel32 = private_windll("kernel32")
    user32 = private_windll("user32")
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.PostThreadMessageW.argtypes = [
        wintypes.DWORD,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.PeekMessageW.restype = wintypes.BOOL
    return kernel32, user32


def _message_loop_worker(result_path: Path) -> int:
    kernel32, user32 = _configure_thread_messaging()
    message = wintypes.MSG()
    user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
    thread_id = int(kernel32.GetCurrentThreadId())
    registered = threading.Event()
    post_results: list[bool] = []
    broker = _RecordingBroker()

    def post_messages() -> None:
        if not registered.wait(timeout=5.0):
            post_results.append(False)
            return
        for message_id, w_param in (
            (_WM_HOTKEY, OPEN_CONTROLS_HOTKEY_ID),
            (_WM_HOTKEY, REQUEST_PAUSE_HOTKEY_ID),
            (_WM_QUIT, 0),
        ):
            post_results.append(
                bool(user32.PostThreadMessageW(thread_id, message_id, w_param, 0))
            )

    poster = threading.Thread(target=post_messages, name="shortcut-evidence-poster")
    poster.start()
    try:
        handled = GlobalShortcutLoop(Win32GlobalShortcutApi()).run(
            broker,
            on_registered=registered.set,
        )
    except Exception as exc:
        _write_json(
            result_path,
            {"passed": False, "code": type(exc).__name__, "message": str(exc)},
        )
        return 2
    finally:
        poster.join(timeout=5.0)
    passed = (
        post_results == [True, True, True]
        and broker.actions
        == [ShortcutAction.OPEN_CONTROLS.value, ShortcutAction.REQUEST_PAUSE.value]
    )
    _write_json(
        result_path,
        {
            "passed": passed,
            "posted": post_results,
            "actions": broker.actions,
            "polls": broker.polls,
            "handled_events": handled,
        },
    )
    return 0 if passed else 2


def _wait_for_ready(process: subprocess.Popen[bytes], ready: Path) -> dict[str, Any]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if ready.exists():
            payload = json.loads(ready.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                break
            return payload
        if process.poll() is not None:
            break
        time.sleep(0.02)
    raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_HOLDER_START_FAILED")


def _start_holder(mode: str, directory: Path) -> tuple[subprocess.Popen[bytes], Path]:
    ready = directory / f"{mode}-ready.json"
    stop = directory / f"{mode}-stop"
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            mode,
            "--ready",
            str(ready),
            "--stop",
            str(stop),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    try:
        payload = _wait_for_ready(process, ready)
    except Exception:
        _stop_holder(process, stop)
        raise
    if payload.get("ready") is not True:
        _stop_holder(process, stop)
        raise ShortcutEvidenceError(str(payload.get("code", "SHORTCUT_CONFLICT")))
    return process, stop


def _stop_holder(process: subprocess.Popen[bytes], stop: Path) -> None:
    stop.touch(exist_ok=True)
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)


def _expect_loop_conflict(code: str) -> str:
    try:
        GlobalShortcutLoop(Win32GlobalShortcutApi()).run(_RecordingBroker())
    except ShortcutRegistrationError as exc:
        observed = str(exc)
        if observed != code:
            raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_CONFLICT_CODE_MISMATCH")
        return observed
    raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_CONFLICT_NOT_OBSERVED")


def _register_once(specs: tuple[tuple[int, int], ...]) -> bool:
    api = Win32GlobalShortcutApi()
    registered: list[int] = []
    try:
        for identifier, virtual_key in specs:
            if not api.register_hotkey(identifier, _MODIFIERS, virtual_key):
                return False
            registered.append(identifier)
        return True
    finally:
        for identifier in reversed(registered):
            api.unregister_hotkey(identifier)


def _foreground_window() -> int:
    user32 = private_windll("user32")
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    return int(user32.GetForegroundWindow() or 0)


def _loaded_layouts() -> list[dict[str, Any]]:
    user32 = private_windll("user32")
    kernel32 = private_windll("kernel32")
    user32.GetKeyboardLayoutList.argtypes = [
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    user32.GetKeyboardLayoutList.restype = ctypes.c_int
    user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
    user32.GetKeyboardLayout.restype = ctypes.c_void_p
    user32.VkKeyScanExW.argtypes = [wintypes.WCHAR, ctypes.c_void_p]
    user32.VkKeyScanExW.restype = ctypes.c_short
    kernel32.LCIDToLocaleName.argtypes = [
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    kernel32.LCIDToLocaleName.restype = ctypes.c_int

    count = int(user32.GetKeyboardLayoutList(0, None))
    if count <= 0:
        raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_LAYOUT_LIST_EMPTY")
    handles = (ctypes.c_void_p * count)()
    actual = int(user32.GetKeyboardLayoutList(count, handles))
    if actual != count:
        raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_LAYOUT_LIST_CHANGED")
    current = int(user32.GetKeyboardLayout(0) or 0)
    layouts: list[dict[str, Any]] = []
    seen: set[int] = set()
    for raw_handle in handles:
        handle = int(raw_handle or 0)
        if not handle or handle in seen:
            continue
        seen.add(handle)
        locale_buffer = ctypes.create_unicode_buffer(85)
        language_id = handle & 0xFFFF
        locale_ok = kernel32.LCIDToLocaleName(
            language_id,
            locale_buffer,
            len(locale_buffer),
            0,
        )
        collisions: dict[str, list[str]] = {"G": [], "P": []}
        for codepoint in range(0x20, 0x10000):
            if 0xD800 <= codepoint <= 0xDFFF:
                continue
            packed = int(user32.VkKeyScanExW(chr(codepoint), ctypes.c_void_p(handle)))
            if packed == -1:
                continue
            value = packed & 0xFFFF
            virtual_key = value & 0xFF
            shift_state = (value >> 8) & 0xFF
            if (shift_state & 0x06) == 0x06:
                if virtual_key == ord("G") and len(collisions["G"]) < 12:
                    collisions["G"].append(f"U+{codepoint:04X}")
                if virtual_key == ord("P") and len(collisions["P"]) < 12:
                    collisions["P"].append(f"U+{codepoint:04X}")
        layouts.append(
            {
                "handle": f"0x{handle:016X}",
                "locale": locale_buffer.value if locale_ok else "unknown",
                "current_thread": handle == current,
                "ctrl_alt_g_codepoints": collisions["G"],
                "ctrl_alt_p_codepoints": collisions["P"],
                "fixed_shortcut_altgr_collision": bool(
                    collisions["G"] or collisions["P"]
                ),
            }
        )
    return layouts


def _run_message_loop(directory: Path) -> dict[str, Any]:
    result_path = directory / "message-loop.json"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "message-loop",
                "--result",
                str(result_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_PROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ShortcutEvidenceError(
            "SHORTCUT_EVIDENCE_MESSAGE_LOOP_TIMEOUT"
        ) from exc
    if completed.returncode != 0 or not result_path.exists():
        raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_MESSAGE_LOOP_FAILED")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("passed") is not True:
        raise ShortcutEvidenceError("SHORTCUT_EVIDENCE_MESSAGE_LOOP_FAILED")
    return payload


def _run_evidence(candidate_sha: str) -> dict[str, Any]:
    foreground_before = _foreground_window()
    layouts = _loaded_layouts()
    with tempfile.TemporaryDirectory(prefix="gda-shortcut-evidence-") as temp:
        directory = Path(temp)
        holder: subprocess.Popen[bytes] | None = None
        stop: Path | None = None
        try:
            holder, stop = _start_holder("hold-both", directory)
            multi_instance = _expect_loop_conflict("SHORTCUT_CONFLICT_OPEN_CONTROLS")
        finally:
            if holder is not None and stop is not None:
                _stop_holder(holder, stop)

        holder = None
        stop = None
        try:
            holder, stop = _start_holder("hold-p", directory)
            atomic_conflict = _expect_loop_conflict(
                "SHORTCUT_CONFLICT_REQUEST_PAUSE"
            )
            rollback_released_g = _register_once(
                ((OPEN_CONTROLS_HOTKEY_ID, ord("G")),)
            )
        finally:
            if holder is not None and stop is not None:
                _stop_holder(holder, stop)

        pair_reacquired = _register_once(
            (
                (OPEN_CONTROLS_HOTKEY_ID, ord("G")),
                (REQUEST_PAUSE_HOTKEY_ID, ord("P")),
            )
        )
        message_loop = _run_message_loop(directory)

    foreground_after = _foreground_window()
    layout_collision = any(
        item["fixed_shortcut_altgr_collision"] is True for item in layouts
    )
    passed = (
        multi_instance == "SHORTCUT_CONFLICT_OPEN_CONTROLS"
        and atomic_conflict == "SHORTCUT_CONFLICT_REQUEST_PAUSE"
        and rollback_released_g
        and pair_reacquired
        and message_loop.get("passed") is True
        and foreground_before == foreground_after
        and not layout_collision
    )
    return {
        "evidence_version": 1,
        "candidate_sha": candidate_sha,
        "passed": passed,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "modifiers": "MOD_CONTROL|MOD_ALT|MOD_NOREPEAT",
        "shortcuts": {"open_controls": "Ctrl+Alt+G", "request_pause": "Ctrl+Alt+P"},
        "loaded_layouts": layouts,
        "tests": {
            "multi_instance_conflict": multi_instance,
            "atomic_second_key_conflict": atomic_conflict,
            "atomic_rollback_released_g": rollback_released_g,
            "pair_reacquired_after_release": pair_reacquired,
            "message_loop": message_loop,
            "foreground_before": foreground_before,
            "foreground_after": foreground_after,
            "foreground_unchanged": foreground_before == foreground_after,
        },
        "physical_input_sent": False,
        "provider_started": False,
        "mcp_started": False,
        "application_started": False,
        "desktop_dispatch": False,
        "claims": {
            "physical_hotkey_trigger": False,
            "unloaded_keyboard_layouts": False,
            "configurable_shortcuts": False,
            "global_approve": False,
            "global_resume": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-sha", default="unknown")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--worker", choices=("hold-both", "hold-p", "message-loop")
    )
    parser.add_argument("--ready", type=Path)
    parser.add_argument("--stop", type=Path)
    parser.add_argument("--result", type=Path)
    return parser


def main() -> int:
    if os.name != "nt":
        raise SystemExit("SHORTCUT_WINDOWS_REQUIRED")
    args = _parser().parse_args()
    if args.worker in {"hold-both", "hold-p"}:
        if args.ready is None or args.stop is None:
            raise SystemExit("SHORTCUT_EVIDENCE_WORKER_INVALID")
        return _holder_worker(args.worker, args.ready, args.stop)
    if args.worker == "message-loop":
        if args.result is None:
            raise SystemExit("SHORTCUT_EVIDENCE_WORKER_INVALID")
        return _message_loop_worker(args.result)
    payload = _run_evidence(args.candidate_sha)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if payload["passed"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
