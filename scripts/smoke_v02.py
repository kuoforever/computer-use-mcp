"""v0.2 smoke — Ctrl+S, then drive the Save As dialog by ref.

Flow (the design's third rung — multi-window + ref invoke):
  1. launch a fresh Notepad, write content via ValuePattern
  2. focus it (AttachThreadInput) and send Ctrl+S via the driver's key()
  3. locate the Save As dialog (#32770, owned by Notepad — NOT a root sibling)
  4. set the filename field by ref (set_value) to a controlled path
  5. invoke the Save button by ref
  6. verify the file exists on disk with our content

Run:  python scripts/smoke_v02.py
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

CONTENT = "v0.2 — saved by Guarded Desktop Agent via ref invoke 你好"
TARGET = ROOT / "out" / "v02_saved.txt"


def notepad_hwnds() -> list[int]:
    out = []
    for w in auto.GetRootControl().GetChildren():
        try:
            if psutil.Process(w.ProcessId).name().lower().removesuffix(".exe") == "notepad" and w.NativeWindowHandle:
                out.append(int(w.NativeWindowHandle))
        except Exception:
            continue
    return out


def launch_fresh_notepad() -> int | None:
    before = set(notepad_hwnds())
    subprocess.Popen(["notepad.exe"])
    for _ in range(20):
        time.sleep(0.5)
        new = [h for h in notepad_hwnds() if h not in before]
        if new:
            return new[0]
    existing = notepad_hwnds()
    return existing[0] if existing else None


def force_foreground(hwnd: int) -> bool:
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    fg = user32.GetForegroundWindow()
    if int(fg or 0) == hwnd:
        return True
    fg_thread = user32.GetWindowThreadProcessId(fg, None)
    tgt_thread = user32.GetWindowThreadProcessId(hwnd, None)
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    attached = fg_thread != tgt_thread and user32.AttachThreadInput(fg_thread, tgt_thread, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    if attached:
        user32.AttachThreadInput(fg_thread, tgt_thread, False)
    time.sleep(0.3)
    return int(user32.GetForegroundWindow() or 0) == hwnd


def find_save_dialog(notepad_hwnd: int):
    """The Save As dialog is modal and owned by Notepad; it may surface as the
    foreground window OR only as a child of the Notepad window. Check both."""
    user32 = ctypes.windll.user32
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    for _ in range(12):
        time.sleep(0.4)
        fg = auto.ControlFromHandle(int(user32.GetForegroundWindow() or 0))
        if fg is not None and fg.ClassName == "#32770":
            return int(fg.NativeWindowHandle)
        npc = auto.ControlFromHandle(notepad_hwnd)
        for w in (npc.GetChildren() if npc else []):
            try:
                if w.ControlTypeName == "WindowControl" and w.ClassName == "#32770" and w.NativeWindowHandle:
                    return int(w.NativeWindowHandle)
            except Exception:
                continue
    return None


def main() -> int:
    drv = WindowsDriver()
    if TARGET.exists():
        TARGET.unlink()  # avoid the "replace existing file?" confirmation

    hwnd = launch_fresh_notepad()
    if hwnd is None:
        print("could not launch/find notepad")
        return 1
    print(f"notepad : hwnd={hwnd}  dpi={drv.dpi_mode}")

    # write content into the editor (focus-independent)
    tree = drv.get_tree(PruneOpts(scope=str(hwnd)))
    doc = next((n for n in tree.nodes if n.role == "Document"), None)
    if doc is None:
        print("no editor Document found")
        return 2
    drv.set_value(doc.native_id, CONTENT)
    print(f"wrote   : {CONTENT!r}")

    # focus + Ctrl+S via the driver
    print("fg forced:", force_foreground(hwnd))
    time.sleep(0.2)
    res = drv.key("Ctrl+S")
    print(f"key Ctrl+S -> ok={res.ok}")

    dialog_hwnd = find_save_dialog(hwnd)
    if dialog_hwnd is None:
        print("Save As dialog not found")
        return 3
    print(f"dialog  : #32770 hwnd={dialog_hwnd}")

    # snapshot the dialog by handle; bump max_nodes past the file list
    dtree = drv.get_tree(PruneOpts(scope=str(dialog_hwnd), max_nodes=600))
    fname = next((n for n in dtree.nodes if n.role == "Edit" and "文件名" in n.name), None)
    save = next((n for n in dtree.nodes if n.role == "Button" and n.name.startswith("保存")), None)
    if fname is None or save is None:
        print("could not find filename field / Save button. roles seen:",
              sorted({n.role for n in dtree.nodes}))
        drv.key("Esc")
        return 4
    print(f"filename: ref native_id={fname.native_id}")
    print(f"save btn: '{save.name}' native_id={save.native_id}")

    r1 = drv.set_value(fname.native_id, str(TARGET))
    print(f"set filename -> ok={r1.ok} code={r1.code}")
    time.sleep(0.2)
    r2 = drv.invoke(save.native_id)
    print(f"invoke Save  -> ok={r2.ok} code={r2.code}")

    # verify on disk
    ok = False
    for _ in range(10):
        time.sleep(0.3)
        if TARGET.exists():
            try:
                body = TARGET.read_text(encoding="utf-8-sig")
            except Exception:
                body = ""
            ok = CONTENT in body
            if ok:
                break
    print(f"file     : {TARGET}  exists={TARGET.exists()}")
    print("VERIFY  :", "PASS" if ok else "FAIL")
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
