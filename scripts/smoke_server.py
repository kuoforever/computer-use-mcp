"""MCP server smoke — exercise the tools in-process (no transport) and verify
the foreground gate allows/denies correctly.

  - list_tools() registers the 8 expected tools
  - ui_snapshot tool returns the ref text; type tool writes by ref (allowed)
  - screenshot tool returns image content
  - with notepad NOT on the allowlist, key/click are DENIED by the gate

Run:  python scripts/smoke_server.py
"""
from __future__ import annotations

import asyncio
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
from computer_use_mcp.server import build_server  # noqa: E402

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


def _text(result) -> str:
    """call_tool may return a list of content blocks or (content, structured)."""
    content = result[0] if isinstance(result, tuple) else result
    parts = []
    for c in content:
        t = getattr(c, "text", None)
        parts.append(t if t is not None else f"<{type(c).__name__}>")
    return "\n".join(parts)


def _kinds(result) -> list[str]:
    content = result[0] if isinstance(result, tuple) else result
    return [type(c).__name__ for c in content]


async def run() -> int:
    driver = WindowsDriver()
    hwnd = notepad_hwnd()
    if hwnd is None:
        print("no notepad window found")
        return 1
    ok_all = True

    # --- allowlisted server: notepad allowed ---
    srv = build_server(allowlist=["notepad.exe"], driver=driver)
    tools = sorted(t.name for t in await srv.list_tools())
    expected = {"ui_snapshot", "find", "screenshot", "list_windows", "activate_window", "click", "type", "key"}
    print(f"[tools] {tools}")
    ok_all &= set(tools) == expected

    driver.activate_window(str(hwnd))
    time.sleep(0.3)

    snap = _text(await srv.call_tool("ui_snapshot", {"scope": str(hwnd)}))
    doc_ref = next((ln.split(" | ")[0] for ln in snap.splitlines()
                    if ln.startswith("ref_") and "document" in ln), None)
    print(f"[ui_snapshot] {len(snap.splitlines())} lines; editor ref={doc_ref}")
    ok_all &= doc_ref is not None

    if doc_ref:
        r = _text(await srv.call_tool("type", {"text": "MCP server 你好 — gated", "ref": doc_ref}))
        print(f"[type allowed] -> {r}")
        ok_all &= r.strip() == "ok"

    kinds = _kinds(await srv.call_tool("screenshot", {}))
    print(f"[screenshot] content kinds={kinds}")
    ok_all &= any("Image" in k for k in kinds)

    # --- gate denial: notepad NOT allowlisted ---
    srv_deny = build_server(allowlist=["calc.exe"], driver=driver)
    driver.activate_window(str(hwnd))
    time.sleep(0.3)
    d_key = _text(await srv_deny.call_tool("key", {"combo": "Ctrl+S"}))
    d_click = _text(await srv_deny.call_tool("click", {"ref": doc_ref or "ref_1"}))
    print(f"[gate deny] key -> {d_key}")
    print(f"[gate deny] click -> {d_click}")
    ok_all &= d_key.startswith("DENIED") and d_click.startswith("DENIED")

    print("\nRESULT:", "PASS" if ok_all else "FAIL")
    return 0 if ok_all else 5


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
