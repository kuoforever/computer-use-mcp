"""Safety-layer smoke — confirmation, e-stop, redaction, audit (DESIGN §E).

  - dangerous click (name on the danger list) asks the confirmer; deny -> blocked
  - e-stop engaged -> actions ABORTED
  - redact() blacks out a window region; screenshot tool logs a redaction
  - the audit log records every decision (ok / user_denied / redacted / estop)

Run:  python scripts/smoke_safety.py
"""
from __future__ import annotations

import asyncio
import io
import json
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

from computer_use_mcp.drivers.windows import WindowsDriver  # noqa: E402
from computer_use_mcp.safety import EStop, redact  # noqa: E402
from computer_use_mcp.server import build_server  # noqa: E402

import psutil  # noqa: E402
import uiautomation as auto  # noqa: E402
from PIL import Image as PILImage  # noqa: E402


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


def _text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(c, "text", f"<{type(c).__name__}>") for c in content)


def _ref_for(snap: str, needle: str) -> str | None:
    for ln in snap.splitlines():
        if ln.startswith("ref_") and needle in ln:
            return ln.split(" | ")[0]
    return None


async def run() -> int:
    driver = WindowsDriver()
    hwnd = notepad_hwnd()
    if hwnd is None:
        print("no notepad window found")
        return 1
    driver.activate_window(str(hwnd))
    time.sleep(0.3)
    ok_all = True

    confirm_calls: list[str] = []

    def deny_confirm(prompt: str) -> bool:
        confirm_calls.append(prompt)
        return False  # human says no

    estop = EStop()  # constructed but NOT started (no real hotkey thread in the test)
    audit_path = ROOT / "out" / "audit_test.jsonl"
    if audit_path.exists():
        audit_path.unlink()

    srv = build_server(
        allowlist=["notepad.exe"], driver=driver, confirmer=deny_confirm,
        audit_path=str(audit_path), estop=estop, start_estop=False,
        dangerous_words=["标题"], redact_titles=["Notepad", "记事本"],
    )

    snap = _text(await srv.call_tool("ui_snapshot", {"scope": str(hwnd)}))
    doc_ref = _ref_for(snap, "document")
    title_ref = _ref_for(snap, '"标题"')

    # a. normal type is allowed
    r_type = _text(await srv.call_tool("type", {"text": "safety layer 你好", "ref": doc_ref}))
    print(f"[type allowed]      -> {r_type}")
    ok_all &= r_type.strip() == "ok"

    # b. dangerous click -> confirmer consulted, denied
    r_click = _text(await srv.call_tool("click", {"ref": title_ref}))
    print(f"[dangerous click]   -> {r_click}  (confirm called {len(confirm_calls)}x)")
    ok_all &= r_click.startswith("DENIED by user") and len(confirm_calls) == 1

    # c. screenshot tool redaction (audit) + redact() unit check
    await srv.call_tool("screenshot", {})
    img = driver.capture_screen()
    npw = next((w for w in driver.list_windows() if int(w.id) == hwnd), None)
    if npw is not None:
        red = redact(img.png, [npw.bounds.as_tuple()])
        pil = PILImage.open(io.BytesIO(red)).convert("RGB")
        x, y, w, h = npw.bounds.as_tuple()
        ix0, iy0, ix1, iy1 = max(x, 0), max(y, 0), min(x + w, pil.width), min(y + h, pil.height)
        if ix1 > ix0 and iy1 > iy0:
            px = pil.getpixel(((ix0 + ix1) // 2, (iy0 + iy1) // 2))
            print(f"[redact] notepad center after redact = {px}")
            ok_all &= px == (0, 0, 0)

    # d. e-stop latches everything off
    estop.engage()
    r_est = _text(await srv.call_tool("type", {"text": "should not type", "ref": doc_ref}))
    print(f"[e-stop]            -> {r_est}")
    ok_all &= r_est.startswith("ABORTED")

    # e. audit trail
    decisions = [json.loads(ln)["decision"] for ln in audit_path.read_text(encoding="utf-8").splitlines()]
    print(f"[audit] decisions   -> {decisions}")
    for need in ("ok", "user_denied", "redacted", "estop"):
        ok_all &= need in decisions

    print("\nRESULT:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 5


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
