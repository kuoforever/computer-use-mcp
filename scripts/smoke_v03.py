"""v0.3 smoke — verify the foundation polish:
  - snapshot de-dup (menu-bar items no longer doubled as MenuItem + Button)
  - list_windows enumerates all visible top-level windows (incl. owned dialogs)
  - activate_window brings a window to the foreground
  - click(x,y) lands in the shared pixel space (minimize the window, then restore)

Run:  python scripts/smoke_v03.py
"""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from collections import Counter
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


def notepad_hwnd(launch: bool = True) -> int | None:
    def scan() -> int | None:
        for w in auto.GetRootControl().GetChildren():
            try:
                if psutil.Process(w.ProcessId).name().lower().removesuffix(".exe") == "notepad" and w.NativeWindowHandle:
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
    print(f"notepad hwnd={hwnd}  dpi={drv.dpi_mode}")
    ok_all = True

    # 1. activate_window
    r = drv.activate_window(str(hwnd))
    time.sleep(0.2)
    is_fg = int(user32.GetForegroundWindow()) == hwnd
    print(f"[activate]     ok={r.ok}  foreground=={hwnd}? {is_fg}")
    ok_all &= r.ok

    # 2. snapshot de-dup
    tree = drv.get_tree(PruneOpts(scope=str(hwnd)))
    menu = Counter(n.name for n in tree.nodes if n.name in ("文件", "编辑", "查看"))
    dedup_ok = bool(menu) and all(c == 1 for c in menu.values()) and set(menu) >= {"文件", "编辑", "查看"}
    print(f"[dedup]        menu counts={dict(menu)} (each == 1)  nodes={len(tree.nodes)}  {'PASS' if dedup_ok else 'FAIL'}")
    ok_all &= dedup_ok

    # 3. list_windows (all top-level, incl. owned)
    wins = drv.list_windows()
    has_np = any(int(w.id) == hwnd for w in wins)
    print(f"[list_windows] {len(wins)} windows; notepad present={has_np}")
    for w in wins[:8]:
        print(f"    hwnd={w.id:<8} fg={str(w.is_foreground):<5} owner={w.owner.name:<16} {w.title[:38]!r}")
    ok_all &= has_np

    # 4. coordinate click -> minimize, then restore
    mini = next((n for n in tree.nodes if n.name == "最小化"), None)
    if mini is None:
        print("[click]        minimize button not in tree; skipping click check")
    else:
        drv.activate_window(str(hwnd))
        time.sleep(0.2)
        rc = drv.click(mini.bbox.cx, mini.bbox.cy)
        iconic = False
        for _ in range(10):
            time.sleep(0.1)
            if user32.IsIconic(hwnd):
                iconic = True
                break
        print(f"[click]        click '最小化'@({mini.bbox.cx},{mini.bbox.cy}) ok={rc.ok} -> IsIconic={iconic}")
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE — put it back
        ok_all &= rc.ok and iconic

    print("RESULT:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 5


if __name__ == "__main__":
    raise SystemExit(main())
