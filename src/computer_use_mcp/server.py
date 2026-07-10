"""MCP server — exposes the Session over MCP behind the full safety layer.

Tools:
  ui_snapshot / find / list_windows      perception (ungated; passwords redacted)
  screenshot                             perception; sensitive windows blacked out
  activate_window / click / type / key   action

Every action passes, in order: e-stop check -> foreground allowlist gate ->
(for dangerous-named clicks) human confirmation -> execute -> audit. A global
panic hotkey (default Ctrl+Alt+Q) latches the server off.

Run:    computer-use-mcp                  (console script, stdio)
Config (env):
  CUMCP_ALLOWLIST="notepad.exe,weixin.exe"   actions allowed only for these (front)
  CUMCP_REDACT_TITLES="1Password,Bitwarden"  window-title substrings to black out
  CUMCP_ESTOP="ctrl+alt+q"                   panic hotkey
  CUMCP_AUDIT="audit/actions.jsonl"          audit log path
  CUMCP_HUMAN_IDLE_SECONDS="2.5"             yield after recent local input
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image as MCPImage

from .audit import AuditLog
from .core import Session
from .dpi import enable_dpi_awareness
from .gate import Gate
from .human_activity import DEFAULT_IDLE_SECONDS, HumanActivity
from .safety import DANGEROUS_WORDS, EStop, is_dangerous, message_box_confirm, redact

DEFAULT_ALLOWLIST = ("notepad.exe",)
DEFAULT_REDACT_TITLES = ("1Password", "Bitwarden", "KeePass", "Authenticator")


def _env_list(name: str, default) -> list[str]:
    raw = os.environ.get(name, "")
    return [x for x in raw.split(",") if x.strip()] if raw.strip() else list(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _fmt(res) -> str:
    return "ok" if res.ok else f"ERROR {res.code}: {res.message}".rstrip()


def build_server(
    allowlist=None,
    driver=None,
    *,
    confirmer=None,
    audit_path=None,
    estop=None,
    start_estop=True,
    dangerous_words=DANGEROUS_WORDS,
    redact_titles=None,
    human_activity=None,
) -> FastMCP:
    enable_dpi_awareness()
    if driver is None:
        from .drivers.windows import WindowsDriver

        driver = WindowsDriver()
    session = Session(driver)
    gate = Gate(allowlist if allowlist is not None else _env_list("CUMCP_ALLOWLIST", DEFAULT_ALLOWLIST), driver)
    activity = human_activity or HumanActivity(
        driver, _env_float("CUMCP_HUMAN_IDLE_SECONDS", DEFAULT_IDLE_SECONDS)
    )
    audit = AuditLog(audit_path or os.environ.get("CUMCP_AUDIT", "audit/actions.jsonl"))
    confirm = confirmer or message_box_confirm
    rtitles = redact_titles if redact_titles is not None else _env_list("CUMCP_REDACT_TITLES", DEFAULT_REDACT_TITLES)
    if estop is None:
        estop = EStop(os.environ.get("CUMCP_ESTOP", "ctrl+alt+q"))
        if start_estop:
            estop.start()

    mcp = FastMCP(
        "computer-use-mcp",
        instructions=(
            "Model-agnostic computer-use for Windows. Read with ui_snapshot (refs) "
            "or screenshot, act with click/type/key. Actions are restricted to "
            f"allowlisted apps ({gate.describe()}); dangerous clicks (send/delete/"
            "pay…) ask the human; a panic hotkey can abort everything."
        ),
    )

    def _guard(tool: str, args: dict, *, require_foreground: bool = True) -> tuple[bool, str]:
        if estop.engaged:
            audit.record(tool, args, "estop", "aborted")
            return False, "ABORTED: e-stop engaged (restart the server to clear)"
        activity_reason = activity.blocking_reason()
        if activity_reason:
            audit.record(tool, args, "human_active", activity_reason)
            return False, f"HUMAN_ACTIVE: {activity_reason}"
        if not require_foreground:
            return True, ""
        allowed, reason = gate.foreground_allowed()
        if not allowed:
            audit.record(tool, args, "gate_denied", reason)
            return False, f"DENIED by gate: {reason}"
        return True, ""

    def _record_action(tool: str, args: dict, out: str) -> str:
        activity.note_agent_action()
        audit.record(tool, args, "ok", out)
        return out

    # --- perception ---------------------------------------------------------

    @mcp.tool(description="Flat list of interactive elements with refs, for scope "
                          "('foreground' | a window id | 'all').")
    def ui_snapshot(scope: str = "foreground") -> str:
        return session.ui_snapshot(scope=scope)

    @mcp.tool(description="Find elements whose name or role matches query; returns a ref subset.")
    def find(query: str, scope: str = "foreground") -> str:
        return session.find(query, scope=scope)

    @mcp.tool(description="List visible top-level windows: id, owner process, title, * if foreground.")
    def list_windows() -> str:
        lines = [
            f'{"*" if w.is_foreground else " "} {w.id} | {w.owner.name} | "{w.title}"'
            for w in session.driver.list_windows()
        ]
        return "\n".join(lines) or "(no windows)"

    @mcp.tool(description="PNG screenshot of the primary screen, for vision models. "
                          "Windows whose title matches the redaction list are blacked out.")
    def screenshot() -> MCPImage:
        png = session.screenshot().png
        if rtitles:
            regions = [
                w.bounds.as_tuple()
                for w in session.driver.list_windows()
                if w.title and any(t.lower() in w.title.lower() for t in rtitles)
            ]
            if regions:
                png = redact(png, regions)
                audit.record("screenshot", {}, "redacted", f"{len(regions)} window(s)")
        return MCPImage(data=png, format="png")

    # --- action -------------------------------------------------------------

    @mcp.tool(description="Bring a window (id from list_windows) to the foreground.")
    def activate_window(window_id: str) -> str:
        args = {"window_id": window_id}
        ok, msg = _guard("activate_window", args, require_foreground=False)
        if not ok:
            return msg
        return _record_action("activate_window", args, _fmt(session.activate(window_id)))

    @mcp.tool(description="Click an element by ref (preferred — focus/occlusion independent) "
                          "or at coordinates x,y. Allowlisted app must be in front; dangerous "
                          "targets (send/delete/pay…) ask the human first.")
    def click(ref: str | None = None, x: int | None = None, y: int | None = None) -> str:
        args = {"ref": ref, "x": x, "y": y}
        ok, msg = _guard("click", args)
        if not ok:
            return msg
        desc = session.describe_ref(ref) if ref else None
        if desc and is_dangerous(desc, dangerous_words):
            if not confirm(f"computer-use-mcp 请求点击：\n\n{desc}\n\n允许执行吗？"):
                audit.record("click", args, "user_denied", desc)
                return f"DENIED by user (dangerous: {desc})"
        return _record_action("click", args, _fmt(session.click(ref=ref, x=x, y=y)))

    @mcp.tool(name="type",
              description="Type text into an element by ref (ValuePattern) or to the focused "
                          "control. Allowlisted app must be in the foreground.")
    def type_text(text: str, ref: str | None = None) -> str:
        args = {"text": text, "ref": ref}
        ok, msg = _guard("type", args)
        if not ok:
            return msg
        return _record_action("type", args, _fmt(session.type(text, ref=ref)))

    @mcp.tool(description="Send a key chord like 'Ctrl+S' to the foreground window. "
                          "Allowlisted app must be in the foreground.")
    def key(combo: str) -> str:
        args = {"combo": combo}
        ok, msg = _guard("key", args)
        if not ok:
            return msg
        return _record_action("key", args, _fmt(session.key(combo)))

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
