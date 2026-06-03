"""v0.0 smoke test — prove the single-coordinate-space invariant.

Launches Notepad (or snapshots whatever is foreground), captures the primary
screen, walks the foreground UIA tree, prints the flat element list, and writes
an annotated PNG with every bbox drawn onto the screenshot. If the boxes land on
the right controls, mss pixels and UIA coordinates share one space — the hardest
and most failure-prone part of the whole project, verified at zero risk.

Run:
  python scripts/smoke_v0.py                 # launch + snapshot Notepad
  python scripts/smoke_v0.py --no-launch     # snapshot current foreground window
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The console here may be GBK (cp936); emit UTF-8 so non-ASCII UI names (and
# stray bidi marks like U+200E) don't crash the print loop.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# DPI awareness MUST be set before the driver (uiautomation) or mss are imported.
from computer_use_mcp.dpi import enable_dpi_awareness  # noqa: E402

enable_dpi_awareness()

from computer_use_mcp.contract import PruneOpts  # noqa: E402
from computer_use_mcp.drivers.windows import WindowsDriver  # noqa: E402
from PIL import Image as PILImage  # noqa: E402
from PIL import ImageDraw, ImageFont  # noqa: E402

_FONT_CANDIDATES = (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\arial.ttf")


def _load_font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _find_window_hwnd(target_exe: str, attempts: int = 10, interval: float = 0.5) -> int | None:
    """Return the handle of a top-level window owned by target_exe, matched by
    owning-process name (locale- and class-name-independent). Polls, because the
    modern WinUI Notepad can take a couple seconds to show its window. Also makes
    a best-effort SetActive so the window is visible in the screenshot — but the
    snapshot itself targets the handle, so focus is not required."""
    import psutil
    import uiautomation as auto

    target = target_exe.lower().removesuffix(".exe")
    for _ in range(attempts):
        for win in auto.GetRootControl().GetChildren():
            try:
                name = psutil.Process(win.ProcessId).name().lower().removesuffix(".exe")
            except Exception:
                continue
            if name == target and win.NativeWindowHandle:
                try:
                    win.SetActive()
                    time.sleep(0.2)
                except Exception:
                    pass
                return int(win.NativeWindowHandle)
        time.sleep(interval)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-launch", action="store_true", help="snapshot current foreground window")
    ap.add_argument("--target", default="notepad.exe")
    ap.add_argument("--wait", type=float, default=2.0, help="seconds to wait after launch")
    ap.add_argument("--out", default=str(ROOT / "out"))
    args = ap.parse_args()

    scope = "foreground"
    if not args.no_launch:
        print(f"launching {args.target} ...")
        subprocess.Popen([args.target])
        time.sleep(args.wait)
        hwnd = _find_window_hwnd(args.target)
        if hwnd:
            scope = str(hwnd)  # snapshot the window by handle, no focus needed
        print(f"target  : {args.target} hwnd={hwnd}  (snapshot scope={scope})")

    drv = WindowsDriver()
    caps = drv.capabilities()
    print(f"driver  : {caps['platform']}  contract={caps['contract_version']}  dpi={caps['dpi_mode']}")

    chain = drv.foreground_owner_chain()
    print("fg owner: " + " -> ".join(f"{p.name}({p.pid})" for p in chain))

    win = drv.list_windows()[0]
    b = win.bounds
    print(f"fg window: {win.title!r}  bounds=({b.x},{b.y},{b.w},{b.h})")

    img = drv.capture_screen()
    print(f"capture : {img.width}x{img.height}px  scale={img.scale}")

    tree = drv.get_tree(PruneOpts(scope=scope))
    print(f"elements: {len(tree.nodes)}  truncated={tree.truncated}")
    print("-" * 64)
    for i, n in enumerate(tree.nodes):
        bb = n.bbox
        disp = " ".join(n.name.split())  # collapse newlines/whitespace for one-line display
        val = f'  ="{" ".join(n.value.split())}"' if n.value else ""
        print(f'ref_{i:<3} {n.role:<9} "{disp}" ({bb.x},{bb.y},{bb.w},{bb.h}) [{",".join(n.states)}]{val}')
    print("-" * 64)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "smoke_raw.png"
    ann_path = out_dir / "smoke_annotated.png"
    raw_path.write_bytes(img.png)

    pil = PILImage.open(io.BytesIO(img.png)).convert("RGB")
    draw = ImageDraw.Draw(pil)
    font = _load_font(14)
    for i, n in enumerate(tree.nodes):
        bb = n.bbox
        draw.rectangle([bb.x, bb.y, bb.right, bb.bottom], outline=(255, 0, 0), width=2)
        draw.text((bb.x + 2, bb.y + 2), f"ref_{i}", fill=(255, 0, 0), font=font)
    pil.save(ann_path)

    print(f"raw      : {raw_path}")
    print(f"annotated: {ann_path}")
    if not tree.nodes:
        print("NOTE: 0 elements — is the target window foreground? try --no-launch with it focused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
