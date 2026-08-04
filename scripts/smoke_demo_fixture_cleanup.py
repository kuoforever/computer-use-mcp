"""Live smoke for exact-process Chrome/Word Demo cleanup.

This starts only disposable fixtures through ``demo_cross_app.py``, observes
their exact process-owned top-level windows, runs the shared cleanup, and
verifies that pre-existing Chrome/Word windows remain. It performs no Runner,
provider, MCP, approval, input, document edit, or network-side mutation.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = ROOT / "scripts" / "demo_cross_app.py"
TARGET_EXECUTABLES = frozenset({"chrome.exe", "winword.exe"})


def _load_demo_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "demo_cross_app_cleanup_smoke",
        DEMO_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("DEMO_CLEANUP_SMOKE_IMPORT_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _visible_top_level_windows() -> dict[int, int]:
    """Return every visible top-level HWND -> PID without window text."""

    user32 = ctypes.windll.user32
    user32.EnumWindows.argtypes = [
        ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM),
        wintypes.LPARAM,
    ]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    windows: dict[int, int] = {}
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HWND,
        wintypes.LPARAM,
    )

    @callback_type
    def collect(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            windows[int(hwnd)] = int(pid.value)
        return True

    if not user32.EnumWindows(collect, 0):
        raise RuntimeError("DEMO_CLEANUP_SMOKE_ENUM_WINDOWS_FAILED")
    return windows


def _target_pids_by_name() -> set[int]:
    import psutil

    pids: set[int] = set()
    for process in psutil.process_iter(("pid", "name")):
        try:
            name = str(process.info.get("name") or "").lower()
            pid = int(process.info["pid"])
        except (psutil.Error, TypeError, ValueError):
            continue
        if name in TARGET_EXECUTABLES:
            pids.add(pid)
    return pids


def _live_target_windows() -> dict[int, int]:
    target_pids = _target_pids_by_name()
    return {
        hwnd: pid
        for hwnd, pid in _visible_top_level_windows().items()
        if pid in target_pids
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify exact-process cleanup for disposable Demo fixtures.",
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=0,
        help="Bounded observation hold before cleanup (0-300 seconds).",
    )
    args = parser.parse_args()
    if not 0 <= args.hold_seconds <= 300:
        parser.error("--hold-seconds must be between 0 and 300")
    demo = _load_demo_script()
    document, profile, stamp = demo._fixtures()
    run_id = f"cross-app-cleanup-smoke-{stamp}"
    before = _live_target_windows()
    ownership: list[object] = []
    cleanup: tuple[object, ...] = ()
    observed_owned: dict[int, int] = {}
    problems: list[str] = []
    try:
        demo._launch_fixtures(
            demo.SOURCE_URL,
            document,
            profile,
            ownership=ownership,
        )
        owned_pids = {int(item.process.pid) for item in ownership}
        observed_owned = {
            hwnd: pid
            for hwnd, pid in _visible_top_level_windows().items()
            if pid in owned_pids
        }
        observed_pids = set(observed_owned.values())
        if observed_pids != owned_pids:
            problems.append("not every exact launched PID exposed a top-level window")
        if len(observed_owned) != len(ownership):
            problems.append("a disposable PID exposed an unexpected extra top-level window")
        if args.hold_seconds:
            time.sleep(args.hold_seconds)
    finally:
        cleanup = demo._cleanup_fixture_processes(ownership)

    # The shared cleanup contract already requires three consecutive zero
    # observations. This additional smoke-only grace catches applications that
    # surface a replacement window after returning from their close handler.
    time.sleep(0.5)
    after = _live_target_windows()
    owned_pids = {int(item.process.pid) for item in ownership}
    remaining_owned_windows = {
        hwnd: pid
        for hwnd, pid in _visible_top_level_windows().items()
        if pid in owned_pids
    }
    if remaining_owned_windows:
        problems.append("an exact launched process retained a top-level window")
    if set(before).difference(after):
        problems.append("a pre-existing Chrome/Word top-level window disappeared")
    if any(item.disposition == "handoff_required" for item in cleanup):
        problems.append("exact-process cleanup required operator handoff")
    if any(not item.window_cleanup_verified for item in cleanup):
        problems.append("exact-process window cleanup was not verified")

    outcome = "smoke_passed" if not problems else "smoke_failed"
    demo._write_final_state(
        document.parent,
        run_id=run_id,
        document_name=document.name,
        profile_name=profile.name,
        outcome=outcome,
        failure_class=None if not problems else "CleanupSmokeFailure",
        cleanup=cleanup,
    )
    result = {
        "cleanup": [
            {
                "application": item.application,
                "close_requests": item.close_requests,
                "disposition": item.disposition,
                "pid": item.pid,
                "process_running": item.process_running,
                "window_cleanup_verified": item.window_cleanup_verified,
            }
            for item in cleanup
        ],
        "owned_window_count": len(observed_owned),
        "preexisting_window_count": len(before),
        "preexisting_windows_preserved": not set(before).difference(after),
        "problems": problems,
        "result": "PASS" if not problems else "FAIL",
        "run_id": run_id,
    }
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
