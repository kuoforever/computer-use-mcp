"""v0.1 smoke — write a line into Notepad via UIA ValuePattern.SetValue.

Focus-independent: sets the Document control's value by native_id even when
Notepad is not the foreground window. Verifies two ways:
  1. authoritative — read ValuePattern.Value back and compare
  2. visual        — annotate a screenshot with the editor bbox

Run:  python scripts/smoke_v01.py
"""
from __future__ import annotations

import io
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
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw  # noqa: E402

TEXT = "你好，世界 — hello from Guarded Desktop Agent v0.1"


def find_notepad_hwnd(launch: bool = True) -> int | None:
    import psutil
    import uiautomation as auto

    def scan() -> int | None:
        for win in auto.GetRootControl().GetChildren():
            try:
                name = psutil.Process(win.ProcessId).name().lower().removesuffix(".exe")
            except Exception:
                continue
            if name == "notepad" and win.NativeWindowHandle:
                try:
                    win.SetActive()  # best-effort, so the screenshot shows it
                    time.sleep(0.2)
                except Exception:
                    pass
                return int(win.NativeWindowHandle)
        return None

    hwnd = scan()
    if hwnd is None and launch:
        subprocess.Popen(["notepad.exe"])
        time.sleep(2)
        hwnd = scan()
    return hwnd


def main() -> int:
    hwnd = find_notepad_hwnd()
    if hwnd is None:
        print("no notepad window found")
        return 1

    drv = WindowsDriver()
    print(f"target  : notepad hwnd={hwnd}  dpi={drv.dpi_mode}")

    tree = drv.get_tree(PruneOpts(scope=str(hwnd)))
    docs = [n for n in tree.nodes if n.role == "Document"]
    if not docs:
        print("no Document editing surface found; roles seen:", sorted({n.role for n in tree.nodes}))
        return 2
    doc = docs[0]
    print(f"editor  : {doc.role} '{doc.name}' native_id={doc.native_id} patterns={doc.patterns}")

    res = drv.set_value(doc.native_id, TEXT)
    print(f"set_value -> ok={res.ok} code={res.code} {res.message}".rstrip())
    if not res.ok:
        return 3

    time.sleep(0.2)
    tree2 = drv.get_tree(PruneOpts(scope=str(hwnd)))
    doc2 = next((n for n in tree2.nodes if n.role == "Document"), None)
    got = doc2.value if doc2 else None
    print(f"readback: {got!r}")
    passed = got is not None and TEXT in got
    print("VERIFY  :", "PASS" if passed else "FAIL")

    img = drv.capture_screen()
    out_dir = ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    ann = out_dir / "smoke_v01.png"
    pil = PILImage.open(io.BytesIO(img.png)).convert("RGB")
    draw = ImageDraw.Draw(pil)
    b = doc.bbox
    draw.rectangle([b.x, b.y, b.right, b.bottom], outline=(0, 200, 0), width=3)
    pil.save(ann)
    print(f"annotated: {ann}")
    return 0 if passed else 3


if __name__ == "__main__":
    raise SystemExit(main())
