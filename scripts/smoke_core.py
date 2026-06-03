"""Core-layer smoke — ref table + ui_snapshot text serialization + ref actions.

Exercises Session: snapshot -> stable ref_N lines, type BY REF (ValuePattern),
read back to verify, find(), and click by ref. Run: python scripts/smoke_core.py
"""
from __future__ import annotations

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

from computer_use_mcp.core import Session  # noqa: E402
from computer_use_mcp.drivers.windows import WindowsDriver  # noqa: E402

import psutil  # noqa: E402
import uiautomation as auto  # noqa: E402

CONTENT = "core ref table 你好 — typed by ref"


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
    sess = Session(WindowsDriver())
    hwnd = notepad_hwnd()
    if hwnd is None:
        print("no notepad window found")
        return 1
    sess.activate(str(hwnd))
    time.sleep(0.2)

    snap = sess.ui_snapshot(scope=str(hwnd))
    print("=== ui_snapshot (first 16 lines) ===")
    print("\n".join(snap.splitlines()[:16]))

    doc_ref = next((r for r, n in sess._by_ref.items() if n.role == "Document"), None)
    print(f"\neditor ref = {doc_ref}")
    if not doc_ref:
        print("no Document ref found")
        return 2

    r = sess.type(CONTENT, ref=doc_ref)
    print(f"type(ref={doc_ref!r}) -> ok={r.ok} code={r.code}")

    sess.ui_snapshot(scope=str(hwnd))  # re-snapshot; stable ref should persist
    doc = next((n for n in sess._by_ref.values() if n.role == "Document"), None)
    got = doc.value if doc else None
    typed_ok = got is not None and CONTENT in got
    print(f"readback: {got!r}  -> {'PASS' if typed_ok else 'FAIL'}")
    print(f"ref stable across snapshot: {doc_ref in sess._by_ref}")

    print("\n=== find('文件') ===")
    print(sess.find("文件", scope=str(hwnd)))

    rc = sess.click(ref=doc_ref)  # Document has no invoke -> coordinate fallback
    print(f"\nclick(ref={doc_ref!r}) -> ok={rc.ok} code={rc.code}")

    ok = typed_ok and rc.ok and (doc_ref in sess._by_ref)
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
