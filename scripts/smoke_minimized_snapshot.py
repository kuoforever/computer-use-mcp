"""Minimized-window smoke for get_tree().

Verifies that a minimized window does not silently collapse to an empty
snapshot because the root BoundingRectangle is 0-area. This script launches or
uses Notepad, minimizes it, reads UIA by hwnd without activating it, then
restores the window.

Run:  python scripts/smoke_minimized_snapshot.py
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from computer_use_mcp.dpi import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from computer_use_mcp.contract import PruneOpts  # noqa: E402
from computer_use_mcp.drivers.windows import WindowsDriver  # noqa: E402

import psutil  # noqa: E402
import uiautomation as auto  # noqa: E402

SW_MINIMIZE = 6
SW_RESTORE = 9


def notepad_hwnd(launch: bool = True) -> int | None:
    def scan() -> int | None:
        for w in auto.GetRootControl().GetChildren():
            try:
                if (
                    psutil.Process(w.ProcessId).name().lower().removesuffix(".exe") == "notepad"
                    and w.NativeWindowHandle
                ):
                    return int(w.NativeWindowHandle)
            except Exception:
                continue
        return None

    h = scan()
    if h is None and launch:
        subprocess.Popen(["notepad.exe"])
        time.sleep(2)
        h = scan()
    return h


def main() -> int:
    drv = WindowsDriver()
    user32 = ctypes.windll.user32
    hwnd = notepad_hwnd()
    if hwnd is None:
        print("no notepad window found")
        return 1

    print(f"notepad hwnd={hwnd} dpi={drv.dpi_mode}")

    user32.ShowWindow(hwnd, SW_RESTORE)
    time.sleep(0.4)
    before = drv.get_tree(PruneOpts(scope=str(hwnd)))
    print(f"[before minimize] nodes={len(before.nodes)} truncated={before.truncated}")
    if not before.nodes:
        print("no baseline nodes before minimizing")
        return 2

    try:
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        for _ in range(20):
            if user32.IsIconic(hwnd):
                break
            time.sleep(0.1)

        root = drv._root_for_scope(PruneOpts(scope=str(hwnd)))  # smoke-level introspection
        root_rect = drv._rect_of(root)
        after = drv.get_tree(PruneOpts(scope=str(hwnd)))
        offscreen = sum(1 for n in after.nodes if "offscreen" in n.states)

        print(f"[minimized] iconic={bool(user32.IsIconic(hwnd))} root_rect={root_rect.as_tuple()}")
        print(f"[minimized] nodes={len(after.nodes)} offscreen={offscreen} truncated={after.truncated}")
        for node in after.nodes[:8]:
            print(f"    {node.role:<10} {node.name[:40]!r} {node.bbox.as_tuple()} {node.states}")

        ok = bool(user32.IsIconic(hwnd)) and len(after.nodes) > 0
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 5
    finally:
        user32.ShowWindow(hwnd, SW_RESTORE)


if __name__ == "__main__":
    raise SystemExit(main())
