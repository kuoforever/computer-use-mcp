"""MCP server — exposes the Session over MCP, gated by the foreground allowlist.

Tools:
  ui_snapshot / find / screenshot / list_windows   perception (ungated; passwords
                                                    are redacted in the snapshot)
  activate_window / click / type / key              action (state-changing tools
                                                    pass the foreground gate first)

Run:  computer-use-mcp                 (console script, stdio transport)
      python -m computer_use_mcp.server
Config: CUMCP_ALLOWLIST="notepad.exe,weixin.exe"  (comma-separated; default notepad)
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image as MCPImage

from .core import Session
from .dpi import enable_dpi_awareness
from .gate import Gate

DEFAULT_ALLOWLIST = ("notepad.exe",)


def load_allowlist() -> list[str]:
    env = os.environ.get("CUMCP_ALLOWLIST", "")
    if env.strip():
        return [a for a in env.split(",") if a.strip()]
    return list(DEFAULT_ALLOWLIST)


def _fmt(res) -> str:
    return "ok" if res.ok else f"ERROR {res.code}: {res.message}".rstrip()


def build_server(allowlist=None, driver=None) -> FastMCP:
    enable_dpi_awareness()
    if driver is None:
        from .drivers.windows import WindowsDriver

        driver = WindowsDriver()
    session = Session(driver)
    gate = Gate(allowlist if allowlist is not None else load_allowlist(), driver)

    mcp = FastMCP(
        "computer-use-mcp",
        instructions=(
            "Model-agnostic computer-use for Windows. Read the screen with "
            "ui_snapshot (flat list of element refs) or screenshot (for vision "
            "models), then act with click/type/key. State-changing actions are "
            "restricted to allowlisted apps — " + gate.describe()
        ),
    )

    # --- perception (ungated; passwords redacted in the snapshot) ---

    @mcp.tool(description="Flat list of interactive elements with refs, for scope "
                          "('foreground' | a window id | 'all').")
    def ui_snapshot(scope: str = "foreground") -> str:
        return session.ui_snapshot(scope=scope)

    @mcp.tool(description="Find elements whose name or role matches query; returns a ref subset.")
    def find(query: str, scope: str = "foreground") -> str:
        return session.find(query, scope=scope)

    @mcp.tool(description="PNG screenshot of the primary screen, for vision models.")
    def screenshot() -> MCPImage:
        return MCPImage(data=session.screenshot().png, format="png")

    @mcp.tool(description="List visible top-level windows: id, owner process, title, * if foreground.")
    def list_windows() -> str:
        lines = [
            f'{"*" if w.is_foreground else " "} {w.id} | {w.owner.name} | "{w.title}"'
            for w in session.driver.list_windows()
        ]
        return "\n".join(lines) or "(no windows)"

    # --- action (gated) ---

    @mcp.tool(description="Bring a window (id from list_windows) to the foreground.")
    def activate_window(window_id: str) -> str:
        return _fmt(session.activate(window_id))

    @mcp.tool(description="Click an element by ref (preferred — focus/occlusion independent) "
                          "or at coordinates x,y. Requires an allowlisted app in the foreground.")
    def click(ref: str | None = None, x: int | None = None, y: int | None = None) -> str:
        allowed, reason = gate.foreground_allowed()
        if not allowed:
            return f"DENIED by gate: {reason}"
        return _fmt(session.click(ref=ref, x=x, y=y))

    @mcp.tool(name="type",
              description="Type text into an element by ref (ValuePattern) or to the focused "
                          "control. Requires an allowlisted app in the foreground.")
    def type_text(text: str, ref: str | None = None) -> str:
        allowed, reason = gate.foreground_allowed()
        if not allowed:
            return f"DENIED by gate: {reason}"
        return _fmt(session.type(text, ref=ref))

    @mcp.tool(description="Send a key chord like 'Ctrl+S' to the foreground window. "
                          "Requires an allowlisted app in the foreground.")
    def key(combo: str) -> str:
        allowed, reason = gate.foreground_allowed()
        if not allowed:
            return f"DENIED by gate: {reason}"
        return _fmt(session.key(combo))

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
