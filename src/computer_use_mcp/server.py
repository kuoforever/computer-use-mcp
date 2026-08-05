"""MCP server — exposes the Session over MCP behind the full safety layer.

Tools:
  ui_snapshot / find / list_windows      perception (ungated; passwords redacted)
  screenshot / capture_region / ocr      perception; sensitive windows blacked out
  activate_window / click / scroll / drag / type / key   action

In ``safe_local`` mode, actions pass e-stop -> human activity -> foreground
allowlist -> dangerous confirmation -> execute -> audit. ``full_control_local``
explicitly bypasses the allowlist and human-yield checks, but never e-stop or
audit. A global panic hotkey (default Ctrl+Alt+Q) latches the server off.

Run:    guarded-desktop-mcp               (console script, stdio)
Config (env):
  CUMCP_ALLOWLIST="notepad.exe,weixin.exe"   actions allowed only for these (front)
  CUMCP_REDACT_TITLES="1Password,Bitwarden"  window-title substrings to black out
  CUMCP_ESTOP="ctrl+alt+q"                   panic hotkey
  CUMCP_AUDIT="audit/actions.jsonl"          audit log path
  CUMCP_HUMAN_IDLE_SECONDS="2.5"             yield after recent local input
  CUMCP_HUMAN_STABLE_SAMPLES="1"             consecutive action-gate samples
  CUMCP_HUMAN_POLL_INTERVAL_SECONDS="0.25"   interval between stable samples
  CUMCP_HUMAN_MAX_WAIT_SECONDS="60"          bounded readiness wait
  CUMCP_INTERACTION_SPEED="normal"           fast | normal | deliberate
  CUMCP_ACTION_FEEDBACK="1"                  visible mouse/key activity, no content
  CUMCP_TYPE_WAIT_SECONDS="0.025"             optional typing-delay override
  CUMCP_MODE="safe_local"                    safe_local | full_control_local
  CUMCP_DANGEROUS_CONFIRM="1"                require confirmation for dangerous clicks
"""
from __future__ import annotations

import asyncio
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image as MCPImage

from . import MCP_SERVER_NAME, SAFETY_BASELINE_ATTESTATION_V1
from .audit import AuditLog
from .capture import CaptureError, serialize_capture
from .capture import validate_region as validate_capture_region
from .contract import DRIVER_ERROR, DriverError, PruneOpts, Result
from .document_text import DocumentTextError, serialize_document_text
from .core import Session
from .dpi import enable_dpi_awareness
from .gate import Gate
from .human_activity import (
    DEFAULT_IDLE_SECONDS,
    DEFAULT_MAX_WAIT_SECONDS,
    DEFAULT_POLL_INTERVAL_SECONDS,
    DEFAULT_STABLE_SAMPLES,
    HumanActivity,
    HumanInputCapture,
)
from .native_authority import (
    NativeActionBoundary,
    NativeAuthorityLost,
    NativeOutcomeUnknown,
)
from .ocr import (
    OCR_TIMEOUT_SECONDS,
    OcrError,
    OcrReader,
    WindowsOcrReader,
    serialize_recognition,
    validate_region,
)
from .region import redaction_boxes
from .safety import DANGEROUS_WORDS, EStop, is_dangerous, message_box_confirm, redact

DEFAULT_ALLOWLIST = ("notepad.exe",)
DEFAULT_REDACT_TITLES = ("1Password", "Bitwarden", "KeePass", "Authenticator")
SAFE_LOCAL = "safe_local"
FULL_CONTROL_LOCAL = "full_control_local"


def _env_list(name: str, default) -> list[str]:
    raw = os.environ.get(name, "")
    return [x for x in raw.split(",") if x.strip()] if raw.strip() else list(default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _env_positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _control_mode(value: str) -> str:
    mode = value.strip().lower()
    if mode not in {SAFE_LOCAL, FULL_CONTROL_LOCAL}:
        raise ValueError(f"CUMCP_MODE must be {SAFE_LOCAL!r} or {FULL_CONTROL_LOCAL!r}")
    return mode


def _fmt(res: Result) -> str:
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
    control_mode=None,
    dangerous_confirmation=None,
    ocr_reader: OcrReader | None = None,
) -> FastMCP:
    enable_dpi_awareness()
    native_boundary = NativeActionBoundary()
    native_boundary_ready = True
    if driver is None:
        from .drivers.windows import WindowsDriver

        action_feedback = None
        if _env_bool("CUMCP_ACTION_FEEDBACK", False):
            from .interaction_feedback_win32 import Win32ActionFeedback

            action_feedback = Win32ActionFeedback()
        raw_type_wait = os.environ.get("CUMCP_TYPE_WAIT_SECONDS")
        driver = WindowsDriver(
            type_wait_seconds=(
                None
                if raw_type_wait is None
                else _env_float("CUMCP_TYPE_WAIT_SECONDS", 0.0)
            ),
            interaction_speed=os.environ.get("CUMCP_INTERACTION_SPEED"),
            action_feedback=action_feedback,
            native_action_boundary=native_boundary,
        )
    else:
        bind_boundary = getattr(driver, "bind_native_action_boundary", None)
        if not callable(bind_boundary):
            native_boundary_ready = False
        else:
            try:
                bind_boundary(native_boundary)
            except Exception:
                native_boundary_ready = False
    session = Session(driver)
    gate = Gate(allowlist if allowlist is not None else _env_list("CUMCP_ALLOWLIST", DEFAULT_ALLOWLIST), driver)
    activity = human_activity or HumanActivity(
        driver,
        _env_float("CUMCP_HUMAN_IDLE_SECONDS", DEFAULT_IDLE_SECONDS),
        stable_samples=_env_positive_int(
            "CUMCP_HUMAN_STABLE_SAMPLES",
            DEFAULT_STABLE_SAMPLES,
        ),
        poll_interval_seconds=_env_float(
            "CUMCP_HUMAN_POLL_INTERVAL_SECONDS",
            DEFAULT_POLL_INTERVAL_SECONDS,
        ),
        max_wait_seconds=_env_float(
            "CUMCP_HUMAN_MAX_WAIT_SECONDS",
            DEFAULT_MAX_WAIT_SECONDS,
        ),
    )
    mode = _control_mode(control_mode or os.environ.get("CUMCP_MODE", SAFE_LOCAL))
    require_dangerous_confirmation = (
        _env_bool("CUMCP_DANGEROUS_CONFIRM", mode == SAFE_LOCAL)
        if dangerous_confirmation is None
        else bool(dangerous_confirmation)
    )
    audit = AuditLog(audit_path or os.environ.get("CUMCP_AUDIT", "audit/actions.jsonl"))
    confirm = confirmer or message_box_confirm
    reader = ocr_reader
    rtitles = redact_titles if redact_titles is not None else _env_list("CUMCP_REDACT_TITLES", DEFAULT_REDACT_TITLES)
    if estop is None:
        estop = EStop(os.environ.get("CUMCP_ESTOP", "ctrl+alt+q"))
        if start_estop:
            estop.start()

    mcp = FastMCP(
        MCP_SERVER_NAME,
        instructions=(
            "Model-agnostic computer-use for Windows. Read with ui_snapshot (refs) "
            "or screenshot, act with click/scroll/drag/type/key. "
            f"Operating mode={mode}. A panic hotkey can abort every action. "
            f"{SAFETY_BASELINE_ATTESTATION_V1}"
        ),
    )

    def _audit_args(args: dict) -> dict:
        return {**args, "control_mode": mode}

    def _estop_guard(
        tool: str,
        args: dict,
        *,
        audit_denial: bool = True,
    ) -> tuple[bool, str]:
        if estop.engaged:
            if audit_denial:
                audit.record(tool, _audit_args(args), "estop", "aborted")
            return False, "ABORTED: e-stop engaged (restart the server to clear)"
        return True, ""

    def _foreground_guard(
        tool: str,
        args: dict,
        *,
        final: bool,
        audit_denial: bool = True,
    ) -> tuple[bool, str]:
        allowed, reason = (
            gate.foreground_allowed_once() if final else gate.foreground_allowed()
        )
        if not allowed:
            if audit_denial:
                audit.record(tool, _audit_args(args), "gate_denied", reason)
            return False, f"DENIED by gate: {reason}"
        return True, ""

    def _human_activity_denied(
        tool: str,
        args: dict,
        reason: str,
        *,
        audit_denial: bool = True,
    ) -> tuple[bool, str]:
        if audit_denial:
            audit.record(
                tool,
                _audit_args(args),
                "human_active",
                reason,
            )
        return False, f"HUMAN_ACTIVE: {reason}"

    def _guard(
        tool: str,
        args: dict,
        *,
        require_foreground: bool = True,
    ) -> tuple[bool, str, HumanInputCapture | None]:
        allowed, reason = _estop_guard(tool, args)
        if not allowed:
            return allowed, reason, None
        if mode == FULL_CONTROL_LOCAL:
            return True, "", None
        activity_reason = activity.wait_until_stable()
        if activity_reason:
            allowed, reason = _human_activity_denied(tool, args, activity_reason)
            return allowed, reason, None
        readiness = activity.capture()
        if readiness is None:
            allowed, reason = _human_activity_denied(
                tool,
                args,
                "human input idle state unavailable",
            )
            return allowed, reason, None
        if not require_foreground:
            return True, "", readiness
        allowed, reason = _foreground_guard(tool, args, final=False)
        return allowed, reason, readiness

    def _final_authority_guard(
        tool: str,
        args: dict,
        *,
        require_foreground: bool = True,
        readiness: HumanInputCapture | None,
        allowed_confirmation: HumanInputCapture | None = None,
        audit_denial: bool = True,
    ) -> tuple[bool, str]:
        """Revalidate non-waiting authority immediately before driver dispatch."""

        allowed, reason = _estop_guard(tool, args, audit_denial=audit_denial)
        if not allowed:
            return allowed, reason
        if mode == FULL_CONTROL_LOCAL:
            return True, ""
        if require_foreground:
            allowed, reason = _foreground_guard(
                tool,
                args,
                final=True,
                audit_denial=audit_denial,
            )
            if not allowed:
                return allowed, reason
        activity_reason = activity.final_blocking_reason(
            readiness,
            allowed_confirmation=allowed_confirmation,
        )
        if activity_reason:
            return _human_activity_denied(
                tool,
                args,
                activity_reason,
                audit_denial=audit_denial,
            )
        return True, ""

    def _record_action(
        tool: str,
        args: dict,
        result: Result,
        *,
        native_input_on_success: bool = False,
    ) -> str:
        out = _fmt(result)
        if native_input_on_success and result.ok:
            activity.note_agent_action()
        audit.record(tool, _audit_args(args), "ok", out)
        return out

    def _run_native_action(
        tool: str,
        args: dict,
        operation,
        *,
        readiness: HumanInputCapture | None,
        require_foreground: bool = True,
        allowed_confirmation: HumanInputCapture | None = None,
        native_input_on_success: bool = False,
    ) -> str:
        """Run one Session action inside the sole call-scoped native boundary."""

        if not native_boundary_ready:
            audit.record(
                tool,
                _audit_args(args),
                "authority_lost",
                "native action boundary unavailable",
            )
            return "NATIVE_AUTHORITY_LOST: native action boundary unavailable"

        call_allowed_input = allowed_confirmation

        def _revalidate() -> tuple[bool, str]:
            nonlocal call_allowed_input
            allowed_input = call_allowed_input
            call_allowed_input = None
            return _final_authority_guard(
                tool,
                args,
                require_foreground=require_foreground,
                readiness=readiness,
                allowed_confirmation=allowed_input,
                audit_denial=False,
            )

        def _capture_native_input() -> tuple[bool, str]:
            nonlocal call_allowed_input
            if mode == FULL_CONTROL_LOCAL:
                return True, ""
            captured = activity.capture()
            if captured is None:
                return False, "HUMAN_ACTIVE: human input idle state unavailable"
            call_allowed_input = captured
            return True, ""

        try:
            with native_boundary.call_scope(_revalidate, _capture_native_input):
                result = operation()
                native_boundary.complete_action(succeeded=result.ok)
        except NativeOutcomeUnknown:
            audit.record(
                tool,
                _audit_args(args),
                "unknown_outcome",
                "native action outcome unknown after dispatch",
            )
            return (
                "ERROR NATIVE_OUTCOME_UNKNOWN: "
                "native action outcome unknown after dispatch"
            )
        except NativeAuthorityLost as exc:
            if exc.after_dispatch:
                audit.record(
                    tool,
                    _audit_args(args),
                    "unknown_outcome",
                    "native authority lost after dispatch",
                )
                return (
                    "ERROR NATIVE_AUTHORITY_LOST: "
                    "native action authority changed after dispatch"
                )
            if exc.rejection.startswith(("ABORTED:", "HUMAN_ACTIVE:", "DENIED by gate:")):
                decision = (
                    "estop"
                    if exc.rejection.startswith("ABORTED:")
                    else "human_active"
                    if exc.rejection.startswith("HUMAN_ACTIVE:")
                    else "gate_denied"
                )
                audit.record(tool, _audit_args(args), decision, exc.rejection)
                return exc.rejection
            audit.record(
                tool,
                _audit_args(args),
                "authority_lost",
                "native action boundary unavailable",
            )
            return "NATIVE_AUTHORITY_LOST: native action boundary unavailable"
        return _record_action(
            tool,
            args,
            result,
            native_input_on_success=native_input_on_success,
        )

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

    @mcp.tool(
        description=(
            "OCR one explicit primary-display region. Returns bounded text runs and "
            "screen-relative boxes; OCR runs are evidence, not clickable refs."
        )
    )
    async def ocr(x: int, y: int, w: int, h: int) -> str:
        nonlocal reader
        args = {"x": x, "y": y, "w": w, "h": h}
        try:
            region = validate_region(x, y, w, h)
            if reader is None:
                reader = WindowsOcrReader()

            async def _run() -> str:
                image = await asyncio.to_thread(session.screenshot, region)
                if (image.width, image.height) != (region.w, region.h):
                    raise OcrError("OCR_CAPTURE_MISMATCH: driver did not return requested region")
                png = image.png
                if rtitles:
                    windows = await asyncio.to_thread(session.driver.list_windows)
                    redactions = redaction_boxes(windows, region, rtitles)
                    if redactions:
                        png = redact(png, redactions)
                        audit.record("ocr", args, "redacted", f"{len(redactions)} window(s)")
                recognition = await reader.recognize(png)
                return serialize_recognition(recognition, region, png)

            return await asyncio.wait_for(_run(), timeout=OCR_TIMEOUT_SECONDS)
        except TimeoutError:
            return f"ERROR OCR_TIMEOUT: exceeded {OCR_TIMEOUT_SECONDS:g} seconds"
        except (DriverError, OcrError) as exc:
            return f"ERROR {exc}"

    @mcp.tool(
        structured_output=False,
        description=(
            "Capture one explicit primary-display region as PNG, for vision models that "
            "only need part of the screen. Returns a grounding envelope plus the image; "
            "windows matching the redaction list are blacked out inside the crop."
        ),
    )
    def capture_region(x: int, y: int, w: int, h: int) -> list[str | MCPImage]:
        args = {"x": x, "y": y, "w": w, "h": h}
        try:
            region = validate_capture_region(x, y, w, h)
            image = session.screenshot(region)
            png = image.png
            if rtitles:
                redactions = redaction_boxes(session.driver.list_windows(), region, rtitles)
                if redactions:
                    png = redact(png, redactions)
                    audit.record("capture_region", args, "redacted", f"{len(redactions)} window(s)")
            envelope = serialize_capture(image, region, png)
        except (DriverError, CaptureError) as exc:
            return [f"ERROR {exc}"]
        return [envelope, MCPImage(data=png, format="png")]

    @mcp.tool(
        description=(
            "Read bounded semantic document text for a scope ('foreground' | a window id "
            "| 'all'). Returns ordered text blocks from a real UIA text channel, not an "
            "accessibility-tree dump; password fields are skipped."
        )
    )
    def document_text(scope: str = "foreground") -> str:
        try:
            result = session.driver.get_document_text(PruneOpts(scope=scope))
            return serialize_document_text(result, scope)
        except (DriverError, DocumentTextError) as exc:
            return f"ERROR {exc}"

    # --- action -------------------------------------------------------------

    @mcp.tool(description="Bring a window (id from list_windows) to the foreground.")
    def activate_window(window_id: str) -> str:
        args = {"window_id": window_id}
        ok, msg, readiness = _guard(
            "activate_window", args, require_foreground=False
        )
        if not ok:
            return msg
        ok, msg = _final_authority_guard(
            "activate_window",
            args,
            require_foreground=False,
            readiness=readiness,
        )
        if not ok:
            return msg
        return _run_native_action(
            "activate_window",
            args,
            lambda: session.activate(window_id),
            readiness=readiness,
            require_foreground=False,
        )

    @mcp.tool(description="Click an element by ref (preferred — focus/occlusion independent) "
                          "or at coordinates x,y. Allowlisted app must be in front; dangerous "
                          "targets (send/delete/pay…) ask the human first.")
    def click(ref: str | None = None, x: int | None = None, y: int | None = None) -> str:
        args = {"ref": ref, "x": x, "y": y}
        ok, msg, readiness = _guard("click", args)
        if not ok:
            return msg
        desc = session.describe_ref(ref) if ref else None
        allowed_confirmation = None
        if require_dangerous_confirmation and desc and is_dangerous(desc, dangerous_words):
            if not confirm(f"{MCP_SERVER_NAME} 请求点击：\n\n{desc}\n\n允许执行吗？"):
                audit.record("click", _audit_args(args), "user_denied", desc)
                return f"DENIED by user (dangerous: {desc})"
            if mode == SAFE_LOCAL:
                allowed_confirmation = activity.capture()
        ok, msg = _final_authority_guard(
            "click",
            args,
            readiness=readiness,
            allowed_confirmation=allowed_confirmation,
        )
        if not ok:
            return msg
        return _run_native_action(
            "click",
            args,
            lambda: session.click(ref=ref, x=x, y=y),
            readiness=readiness,
            allowed_confirmation=allowed_confirmation,
            native_input_on_success=(ref is None and x is not None and y is not None),
        )

    @mcp.tool(
        description="Scroll at a screenshot-grounded coordinate. Positive delta_y scrolls up; "
        "positive delta_x scrolls right. The allowlisted app must be in front."
    )
    def scroll(x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> str:
        args = {"x": x, "y": y, "delta_x": delta_x, "delta_y": delta_y}
        ok, msg, readiness = _guard("scroll", args)
        if not ok:
            return msg
        if (
            delta_x == delta_y == 0
            or abs(delta_x) > 2400
            or abs(delta_y) > 2400
        ):
            return _record_action(
                "scroll",
                args,
                Result.fail(DRIVER_ERROR, "invalid scroll delta"),
            )
        ok, msg = _final_authority_guard("scroll", args, readiness=readiness)
        if not ok:
            return msg
        return _run_native_action(
            "scroll",
            args,
            lambda: session.scroll(x, y, delta_x, delta_y),
            readiness=readiness,
            native_input_on_success=True,
        )

    @mcp.tool(
        description="Drag from one screenshot-grounded coordinate to another with the left "
        "mouse button. The allowlisted app must be in front."
    )
    def drag(
        x: int,
        y: int,
        to_x: int,
        to_y: int,
        duration_ms: int = 250,
    ) -> str:
        args = {
            "x": x,
            "y": y,
            "to_x": to_x,
            "to_y": to_y,
            "duration_ms": duration_ms,
        }
        ok, msg, readiness = _guard("drag", args)
        if not ok:
            return msg
        if (x, y) == (to_x, to_y) or not 0 <= duration_ms <= 5000:
            return _record_action(
                "drag",
                args,
                Result.fail(DRIVER_ERROR, "invalid drag bounds"),
            )
        ok, msg = _final_authority_guard("drag", args, readiness=readiness)
        if not ok:
            return msg
        return _run_native_action(
            "drag",
            args,
            lambda: session.drag(x, y, to_x, to_y, duration_ms),
            readiness=readiness,
            native_input_on_success=True,
        )

    @mcp.tool(name="type",
              description="Type text into an element by ref (ValuePattern) or to the focused "
                          "control. Allowlisted app must be in the foreground.")
    def type_text(text: str, ref: str | None = None) -> str:
        args = {"text": text, "ref": ref}
        ok, msg, readiness = _guard("type", args)
        if not ok:
            return msg
        ok, msg = _final_authority_guard("type", args, readiness=readiness)
        if not ok:
            return msg
        return _run_native_action(
            "type",
            args,
            lambda: session.type(text, ref=ref),
            readiness=readiness,
            native_input_on_success=(ref is None and bool(text)),
        )

    @mcp.tool(description="Send a key chord like 'Ctrl+S' to the foreground window. "
                          "Allowlisted app must be in the foreground.")
    def key(combo: str) -> str:
        args = {"combo": combo}
        ok, msg, readiness = _guard("key", args)
        if not ok:
            return msg
        ok, msg = _final_authority_guard("key", args, readiness=readiness)
        if not ok:
            return msg
        return _run_native_action(
            "key",
            args,
            lambda: session.key(combo),
            readiness=readiness,
            native_input_on_success=bool(combo.strip()),
        )

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
