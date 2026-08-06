"""Windows driver (A-path, in-process Python).

Implements the Driver Contract on Windows using:
  - mss            screen capture
  - uiautomation   UIA accessibility tree + patterns
  - psutil         process-tree (owner_chain — for the foreground gate)
  - ctypes/user32  foreground window handle + pid

DPI awareness is NOT set here: it must already be set before ``uiautomation``
is imported. Call ``computer_use_mcp.dpi.enable_dpi_awareness()`` at process
start (the constructor calls it too, as a backstop).
"""
from __future__ import annotations

import ctypes
import math
import time
from ctypes import wintypes

import mss
import mss.tools
import psutil
import uiautomation as auto

from ..interaction_feedback import (
    ActionFeedback,
    InteractionPacing,
    resolve_interaction_pacing,
)
from ..native_authority import NativeActionBoundary, NativeAuthorityLost
from ..contract import (
    CONTRACT_VERSION,
    DRIVER_ERROR,
    NOT_INVOKABLE,
    OUT_OF_BOUNDS,
    STALE_ELEMENT,
    Display,
    DocumentTextBlock,
    DocumentTextResult,
    Driver,
    DriverError,
    Image,
    Node,
    ProcRef,
    PruneOpts,
    Rect,
    Result,
    TreeResult,
    Window,
)
from ..dpi import enable_dpi_awareness

# Traversal backstops so a pathological tree can't hang the snapshot.
_MAX_VISIT = 8000
_MAX_DEPTH = 40

# Document-text traversal caps. A TextPattern DocumentRange already covers its
# subtree, so the walk stops descending once it reads one, which keeps the block
# count and visit count far below the interactive-tree limits.
_MAX_DOC_VISIT = 4000
_MAX_DOC_BLOCKS = 200
_DOC_RANGE_CHARS = 20_000
# One Python character can occupy two Windows UTF-16 code units. Probe one
# Python character beyond the output cap without requesting an unbounded range.
_DOC_RANGE_PROBE_UNITS = 2 * (_DOC_RANGE_CHARS + 1)

# Patterns probed per node (the ones the action model actually uses in v0.1+).
_PATTERN_PROBES = (
    ("invoke", "GetInvokePattern"),
    ("value", "GetValuePattern"),
    ("selectionitem", "GetSelectionItemPattern"),
)

# key() combo parsing -> virtual-key codes
_MOD_KEYS = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}
_NAMED_KEYS = {
    "enter": 0x0D, "return": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "space": 0x20, "backspace": 0x08, "delete": 0x2E, "del": 0x2E,
    "home": 0x24, "end": 0x23, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "pageup": 0x21, "pagedown": 0x22,
}
_KEYEVENTF_KEYUP = 0x0002
_SW_RESTORE = 9
_BROWSER_PROCESS_NAMES = frozenset({"chrome.exe", "chromium.exe", "msedge.exe"})
_BROWSER_SNAPSHOT_WARMUP_SECONDS = 1.0


def _activate_window_with_api(
    hwnd: int,
    user32: object,
    kernel32: object,
    boundary: NativeActionBoundary,
) -> Result:
    """Activate ``hwnd`` while balancing every attached input queue.

    Keeping the native API objects injectable makes the ordering and cleanup
    contract testable without interacting with the real desktop.
    """
    attached: list[tuple[int, int]] = []
    operation_error: str | None = None
    cleanup_errors: list[str] = []
    authority_lost: NativeAuthorityLost | None = None

    try:
        if hwnd <= 0 or not user32.IsWindow(hwnd):
            return Result.fail(STALE_ELEMENT, "window no longer exists")

        foreground_hwnd = int(user32.GetForegroundWindow() or 0)
        was_minimized = bool(user32.IsIconic(hwnd))
        if was_minimized:
            boundary.mutate(lambda: user32.ShowWindow(hwnd, _SW_RESTORE))
            if user32.IsIconic(hwnd):
                return Result.fail(DRIVER_ERROR, "could not restore minimized window")
        if foreground_hwnd == hwnd and not was_minimized:
            return Result.success()

        caller_thread = int(kernel32.GetCurrentThreadId() or 0)
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, None) or 0)
        foreground_thread = (
            int(user32.GetWindowThreadProcessId(foreground_hwnd, None) or 0)
            if foreground_hwnd
            else 0
        )
        if not caller_thread or not target_thread:
            return Result.fail(DRIVER_ERROR, "could not resolve activation input threads")
        if foreground_hwnd and not foreground_thread:
            return Result.fail(DRIVER_ERROR, "could not resolve foreground input thread")

        # Attaching the caller to both queues puts caller, foreground, and
        # target in one input group. Skip identical or duplicate pairings.
        pairs: list[tuple[int, int]] = []
        for other_thread in (foreground_thread, target_thread):
            pair = (caller_thread, other_thread)
            if other_thread and caller_thread != other_thread and pair not in pairs:
                pairs.append(pair)

        try:
            for caller, other in pairs:
                def attach(caller=caller, other=other):
                    # Record the possibly acquired queue before entering the
                    # native API so effect-then-error still detaches it.
                    attached.append((caller, other))
                    attached_now = user32.AttachThreadInput(caller, other, True)
                    if not attached_now:
                        # A normal FALSE return is a known non-acquisition;
                        # retain only an exception-uncertain attempt.
                        attached.pop()
                    return attached_now

                if not boundary.mutate(attach):
                    error = int(kernel32.GetLastError())
                    raise OSError(
                        "AttachThreadInput failed for threads "
                        f"{caller} and {other} (win32 error {error})"
                    )

            if not boundary.mutate(lambda: user32.BringWindowToTop(hwnd)):
                raise OSError("BringWindowToTop failed")
            if not boundary.mutate(lambda: user32.SetForegroundWindow(hwnd)):
                raise OSError("SetForegroundWindow failed")
        except NativeAuthorityLost as exc:
            authority_lost = exc
        except Exception as exc:
            operation_error = str(exc)
        finally:
            for caller, other in reversed(attached):
                try:
                    def detach(caller=caller, other=other):
                        return user32.AttachThreadInput(caller, other, False)

                    detached = (
                        detach()
                        if authority_lost is not None
                        else boundary.mutate(detach)
                    )
                    if not detached:
                        cleanup_errors.append(f"threads {caller} and {other}")
                except NativeAuthorityLost as exc:
                    authority_lost = exc
                    try:
                        if not user32.AttachThreadInput(caller, other, False):
                            cleanup_errors.append(f"threads {caller} and {other}")
                    except Exception as cleanup_exc:
                        cleanup_errors.append(
                            f"threads {caller} and {other}: {cleanup_exc}"
                        )
                except Exception as exc:
                    cleanup_errors.append(f"threads {caller} and {other}: {exc}")

        if authority_lost is not None:
            raise authority_lost
        if operation_error is not None:
            return Result.fail(DRIVER_ERROR, operation_error)
        if cleanup_errors:
            return Result.fail(
                DRIVER_ERROR,
                "could not detach input threads: " + "; ".join(cleanup_errors),
            )
        # Some Windows applications can become iconic again while their input
        # queues are being detached. Re-assert the restore only for a target
        # that was minimized on entry, then enforce the final postcondition.
        if was_minimized and user32.IsIconic(hwnd):
            boundary.mutate(lambda: user32.ShowWindow(hwnd, _SW_RESTORE))
            if user32.IsIconic(hwnd):
                return Result.fail(DRIVER_ERROR, "could not restore minimized window")
        if int(user32.GetForegroundWindow() or 0) != hwnd:
            return Result.fail(DRIVER_ERROR, "could not bring window to foreground")
        return Result.success()
    except NativeAuthorityLost:
        raise
    except Exception as exc:
        return Result.fail(DRIVER_ERROR, str(exc))


class WindowsDriver(Driver):
    def __init__(
        self,
        *,
        type_wait_seconds: float | None = None,
        interaction_speed: str | None = None,
        action_feedback: ActionFeedback | None = None,
        native_action_boundary: NativeActionBoundary | None = None,
        sleep: object = time.sleep,
    ) -> None:
        pacing = resolve_interaction_pacing(interaction_speed)
        resolved_type_wait = (
            pacing.type_wait_seconds
            if type_wait_seconds is None and pacing is not None
            else 0.0 if type_wait_seconds is None else type_wait_seconds
        )
        if (
            isinstance(resolved_type_wait, bool)
            or not isinstance(resolved_type_wait, (int, float))
            or not math.isfinite(resolved_type_wait)
            or not 0.0 <= float(resolved_type_wait) <= 0.1
        ):
            raise ValueError("type_wait_seconds must be between 0 and 0.1")
        if action_feedback is not None and not isinstance(action_feedback, ActionFeedback):
            raise ValueError("action_feedback must implement ActionFeedback")
        if not callable(sleep):
            raise ValueError("sleep must be callable")
        # Backstop: real entrypoints set this earlier, before uiautomation import.
        self.dpi_mode = enable_dpi_awareness()
        self._type_wait_seconds = float(resolved_type_wait)
        self._typing_interval = (
            None
            if type_wait_seconds is None and pacing is None
            else self._type_wait_seconds
        )
        self._pacing = pacing
        self._action_feedback = action_feedback
        self._sleep = sleep
        self._native_action_boundary: NativeActionBoundary | None = None
        if native_action_boundary is not None:
            self.bind_native_action_boundary(native_action_boundary)
        # native_id -> live UIA control, repopulated each get_tree(); actions
        # resolve refs through it. The core owns ref<->native_id; this is the
        # driver-side native_id<->handle half of that mapping.
        self._node_cache: dict[str, object] = {}

    def _pause(self, seconds: float) -> None:
        if seconds > 0:
            self._sleep(seconds)  # type: ignore[operator]

    def bind_native_action_boundary(self, boundary: NativeActionBoundary) -> None:
        """Bind the MCP-owned controller once without changing Driver v1."""

        if not isinstance(boundary, NativeActionBoundary):
            raise ValueError("native action boundary is invalid")
        if getattr(self, "_native_action_boundary", None) is not None:
            raise ValueError("native action boundary is already bound")
        boundary.bind(self)
        self._native_action_boundary = boundary

    def _require_native_action_boundary(self) -> NativeActionBoundary:
        boundary = getattr(self, "_native_action_boundary", None)
        if not isinstance(boundary, NativeActionBoundary):
            raise NativeAuthorityLost(dispatch_attempts=0)
        return boundary

    def _mutate(self, operation, *, native_input: bool = False):
        boundary = self._require_native_action_boundary()
        return boundary.mutate(operation, native_input=native_input)

    def _show_pointer_feedback(self, x: int, y: int, action: str) -> None:
        feedback = getattr(self, "_action_feedback", None)
        if feedback is None:
            return
        try:
            feedback.show_pointer(x, y, action=action)
        except Exception:
            self._action_feedback = None

    def _show_keyboard_feedback(
        self,
        action: str,
        *,
        total_units: int = 0,
        estimated_seconds: float = 0.0,
    ) -> None:
        feedback = getattr(self, "_action_feedback", None)
        if feedback is None:
            return
        try:
            feedback.show_keyboard(
                action=action,
                total_units=total_units,
                estimated_seconds=estimated_seconds,
            )
        except Exception:
            self._action_feedback = None

    def _finish_feedback(self, *, skip_delay: bool = False) -> None:
        pacing: InteractionPacing | None = getattr(self, "_pacing", None)
        if pacing is not None and not skip_delay:
            self._pause(pacing.post_action_seconds)
        feedback = getattr(self, "_action_feedback", None)
        if feedback is None:
            return
        try:
            feedback.clear()
        except Exception:
            self._action_feedback = None

    def _prepare_semantic_target(self, ctrl: object) -> None:
        rect = self._rect_of(ctrl)
        if rect.w > 0 and rect.h > 0:
            self._show_pointer_feedback(
                rect.x + rect.w // 2,
                rect.y + rect.h // 2,
                "target",
            )
        pacing: InteractionPacing | None = getattr(self, "_pacing", None)
        if pacing is not None:
            self._pause(pacing.pre_action_seconds)

    def _move_pointer(self, user32: object, x: int, y: int, action: str) -> None:
        pacing: InteractionPacing | None = getattr(self, "_pacing", None)
        if pacing is None:
            moved = self._mutate(
                lambda: user32.SetCursorPos(int(x), int(y)),
                native_input=True,
            )
            if not moved:
                raise OSError("SetCursorPos failed")
            self._show_pointer_feedback(x, y, action)
            return
        point = wintypes.POINT()
        if not user32.GetCursorPos(ctypes.byref(point)):
            point = wintypes.POINT(int(x), int(y))
        steps = max(1, min(30, pacing.pointer_move_ms // 16 or 1))
        for step in range(1, steps + 1):
            next_x = int(point.x + (x - point.x) * step / steps)
            next_y = int(point.y + (y - point.y) * step / steps)
            moved = self._mutate(
                lambda next_x=next_x, next_y=next_y: user32.SetCursorPos(
                    next_x, next_y
                ),
                native_input=True,
            )
            if not moved:
                raise OSError("SetCursorPos failed")
            self._show_pointer_feedback(next_x, next_y, "move" if step < steps else action)
            self._pause(pacing.pointer_move_ms / steps / 1000)
        self._pause(pacing.pre_action_seconds)

    # --- capabilities --------------------------------------------------------

    def capabilities(self) -> dict:
        return {
            "contract_version": CONTRACT_VERSION,
            "platform": "windows",
            "features": [
                "capture_screen",
                "list_windows",
                "foreground_owner_chain",
                "get_tree",
                "find",
                "get_document_text",
                "invoke",
                "set_value",
                "select",
                "type",
                "key",
                "click",
                "activate_window",
            ],
            "dpi_mode": self.dpi_mode,
        }

    # --- screen --------------------------------------------------------------

    def capture_screen(self, region: Rect | None = None) -> Image:
        with mss.mss() as sct:
            primary = self._primary_monitor(sct)
            if region is not None and (
                region.x < primary["left"]
                or region.y < primary["top"]
                or region.w <= 0
                or region.h <= 0
                or region.right > primary["left"] + primary["width"]
                or region.bottom > primary["top"] + primary["height"]
            ):
                raise DriverError(OUT_OF_BOUNDS, "capture region is outside the primary display")
            area = (
                {"left": region.x, "top": region.y, "width": region.w, "height": region.h}
                if region is not None
                else primary
            )
            raw = sct.grab(area)
            png = mss.tools.to_png(raw.rgb, raw.size)
            scale = self._primary_scale()
            displays = [
                Display(
                    id=str(i),
                    bounds=Rect(m["left"], m["top"], m["width"], m["height"]),
                    scale=scale,  # per-monitor scale is a v0.1+ refinement
                    primary=(m["left"] == 0 and m["top"] == 0),
                )
                for i, m in enumerate(sct.monitors[1:], start=1)
            ]
        return Image(png=png, width=raw.width, height=raw.height, scale=scale, displays=displays)

    @staticmethod
    def _primary_monitor(sct: "mss.base.MSSBase") -> dict:
        # The primary monitor's virtual top-left is (0,0) on Windows, which is
        # why its pixels coincide with UIA bbox coordinates (invariant #2).
        for m in sct.monitors[1:]:
            if m["left"] == 0 and m["top"] == 0:
                return m
        return sct.monitors[1]

    @staticmethod
    def _primary_scale() -> float:
        try:
            user32 = ctypes.windll.user32
            dpi = user32.GetDpiForWindow(user32.GetDesktopWindow())
            return round(dpi / 96.0, 4) if dpi else 1.0
        except Exception:
            return 1.0

    # --- windows / process ---------------------------------------------------

    @staticmethod
    def _foreground_hwnd() -> int:
        return int(ctypes.windll.user32.GetForegroundWindow() or 0)

    @staticmethod
    def _pid_of_hwnd(hwnd: int) -> int:
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def foreground_owner_chain(self) -> list[ProcRef]:
        return self._chain_for_pid(self._pid_of_hwnd(self._foreground_hwnd()))

    @staticmethod
    def last_input_tick() -> int:
        """Return the 32-bit timestamp from GetLastInputInfo."""
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
        user32 = ctypes.windll.user32
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            raise OSError(ctypes.get_last_error(), "GetLastInputInfo failed")
        return int(info.dwTime)

    def last_input_idle_seconds(self) -> float:
        """Return seconds since the last keyboard or mouse input Win32 reports.

        GetLastInputInfo is a single Win32 query, not a hook or a listener.
        Its tick count is 32-bit, so subtraction is intentionally modulo 2^32.
        """
        now = int(ctypes.windll.kernel32.GetTickCount64()) & 0xFFFFFFFF
        return ((now - self.last_input_tick()) & 0xFFFFFFFF) / 1000.0

    def snapshot_warmup_delay(self, scope: str) -> float:
        """Return a delay after a disposable browser UIA walk, if needed.

        Chromium-family browsers frequently materialize renderer accessibility
        only after their first UIA traversal. This method deliberately resolves
        the requested handle and never activates a window.
        """
        if scope == "all":
            return 0.0
        try:
            hwnd = self._foreground_hwnd() if scope == "foreground" else int(scope)
            name = psutil.Process(self._pid_of_hwnd(hwnd)).name().casefold()
        except (TypeError, ValueError, psutil.Error):
            return 0.0
        return _BROWSER_SNAPSHOT_WARMUP_SECONDS if name in _BROWSER_PROCESS_NAMES else 0.0

    def snapshot_incomplete_reason(self, scope: str, tree: TreeResult) -> str | None:
        """Identify the Chromium frame-only tree without taking foreground.

        A browser renderer can defer page accessibility indefinitely while it is
        backgrounded. Do not activate it just to build the tree; make that
        limitation visible to the caller instead of presenting a silent partial
        snapshot as complete.
        """
        if self.snapshot_warmup_delay(scope) <= 0:
            return None
        documents = sum(node.role == "Document" for node in tree.nodes)
        hyperlinks = sum(node.role == "Hyperlink" for node in tree.nodes)
        if documents <= 2 and hyperlinks == 0:
            return "browser content controls are not exposed yet; retry after the page is active"
        return None

    @staticmethod
    def _chain_for_pid(pid: int) -> list[ProcRef]:
        chain: list[ProcRef] = []
        try:
            proc: psutil.Process | None = psutil.Process(pid)
            while proc is not None:
                chain.append(ProcRef(pid=proc.pid, name=proc.name()))
                proc = proc.parent()
        except psutil.Error:
            pass
        return chain

    def list_windows(self) -> list[Window]:
        """All visible top-level windows in Z-order (front first), including
        owned windows such as dialogs — which UIA nests under their owner but
        Win32 EnumWindows lists flat (the v0.2 Save As #32770 finding)."""
        user32 = ctypes.windll.user32
        fg = self._foreground_hwnd()
        out: list[Window] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _collect(hwnd, _lparam):
            h = int(hwnd or 0)
            if not h or not user32.IsWindowVisible(h):
                return True
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, cls, 256)
            length = user32.GetWindowTextLengthW(h)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(h, buf, length + 1)
            title = buf.value
            if not title and cls.value != "#32770":
                return True  # skip untitled non-dialog windows (hosts/tooltips)
            rect = wintypes.RECT()
            user32.GetWindowRect(h, ctypes.byref(rect))
            bounds = Rect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
            if bounds.w <= 0 or bounds.h <= 0:
                return True
            chain = self._chain_for_pid(self._pid_of_hwnd(h))
            out.append(Window(
                id=str(h), title=title, bounds=bounds,
                owner=chain[0] if chain else ProcRef(0, ""),
                owner_chain=chain, is_foreground=(h == fg),
            ))
            return True

        user32.EnumWindows(_collect, 0)
        return out

    def _root_for_scope(self, opts: PruneOpts):
        """Resolve PruneOpts.scope to the UIA control to walk: the foreground
        window, a specific window handle, or the whole desktop. Targeting by
        handle is how the action model reaches a window without stealing focus."""
        if opts.scope == "all":
            return auto.GetRootControl()
        hwnd = self._foreground_hwnd() if opts.scope == "foreground" else int(opts.scope)
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl is None:
            raise DriverError(DRIVER_ERROR, f"no UIA control for scope={opts.scope!r}")
        return ctrl

    # --- tree ----------------------------------------------------------------

    def get_tree(self, opts: PruneOpts) -> TreeResult:
        return self._get_tree(opts)

    def _get_tree(self, opts: PruneOpts, *, query: str | None = None) -> TreeResult:
        self._node_cache = {}
        root = self._root_for_scope(opts)
        root_rect = self._rect_of(root)
        # Minimized and lazily materialized windows can report a 0-area root
        # BoundingRectangle while descendants are still addressable through UIA.
        # Only use the root rect as a clipping boundary when it is meaningful.
        clip_rect = root_rect if root_rect.w > 0 and root_rect.h > 0 else None
        wanted = set(opts.resolved_types())

        nodes: list[Node] = []
        seen: dict[tuple, int] = {}
        truncated_keys: set[tuple] = set()
        truncated = 0
        visited = 0
        stack: list[tuple[object, int]] = [(root, 0)]
        while stack:
            ctrl, depth = stack.pop()
            visited += 1
            if visited > _MAX_VISIT:
                break
            if depth < _MAX_DEPTH:
                for child in reversed(self._children(ctrl)):
                    stack.append((child, depth + 1))
            if ctrl is root:
                continue  # the window frame itself is not an element
            node = self._maybe_node(ctrl, wanted, clip_rect, opts)
            if node is None:
                continue
            if query is not None and query not in node.name.lower() and query not in node.role.lower():
                continue
            # de-dup: one visual control can surface under two control types
            # (e.g. a menu-bar item as both MenuItem and Button at the same
            # bbox) -> keep the first, merge the duplicate's patterns into it.
            dedup_key = (node.bbox.as_tuple(), node.name) if node.name else None
            if dedup_key is not None and dedup_key in seen:
                kept = nodes[seen[dedup_key]]
                for pat in node.patterns:
                    if pat not in kept.patterns:
                        kept.patterns.append(pat)
                continue
            if dedup_key is not None and dedup_key in truncated_keys:
                continue
            if len(nodes) >= opts.max_nodes:
                truncated += 1
                if dedup_key is not None:
                    truncated_keys.add(dedup_key)
                continue
            if dedup_key is not None:
                seen[dedup_key] = len(nodes)
            nodes.append(node)
            if node.native_id:
                self._node_cache[node.native_id] = ctrl
        return TreeResult(nodes=nodes, truncated=truncated)

    def find(self, opts: PruneOpts, query: str) -> TreeResult:
        return self._get_tree(opts, query=query.lower())

    def get_document_text(self, opts: PruneOpts) -> DocumentTextResult:
        """Read semantic text through UIA TextPattern, not the interactive tree.

        A control's TextPattern ``DocumentRange`` already covers its whole
        subtree, so the walk reads one range and stops descending into it. That
        keeps browser and editor page text as a small number of ordered blocks
        rather than a per-node dump, and password subtrees are skipped entirely.
        """
        root = self._root_for_scope(opts)
        blocks: list[DocumentTextBlock] = []
        truncated = 0
        complete = True
        visited = 0
        text_read_failed = object()
        stack: list[object] = [root]
        while stack:
            ctrl = stack.pop()
            visited += 1
            if visited > _MAX_DOC_VISIT:
                complete = False
                break
            if opts.redact_password and self._safe(lambda: bool(ctrl.IsPassword), False):
                continue  # never surface a password subtree as document text
            pattern = self._safe(
                lambda: ctrl.GetPattern(auto.PatternId.TextPattern), None
            )
            if pattern is not None:
                text = self._safe(
                    lambda: pattern.DocumentRange.GetText(_DOC_RANGE_PROBE_UNITS),
                    text_read_failed,
                )
                if not isinstance(text, str):
                    complete = False
                    continue
                if len(text) > _DOC_RANGE_CHARS:
                    complete = False
                text = text[:_DOC_RANGE_CHARS]
                if text.strip():
                    if len(blocks) >= _MAX_DOC_BLOCKS:
                        truncated += 1
                    else:
                        blocks.append(
                            DocumentTextBlock(
                                text=text,
                                bbox=self._rect_of(ctrl),
                                order=len(blocks),
                            )
                        )
                # The range already captured this subtree; do not descend.
                continue
            for child in reversed(self._children(ctrl)):
                stack.append(child)
        return DocumentTextResult(
            blocks=blocks,
            truncated_blocks=truncated,
            source="uia_text_pattern",
            complete=complete,
        )

    # --- node construction ---------------------------------------------------

    def _maybe_node(self, ctrl, wanted: set[str], clip_rect: Rect | None, opts: PruneOpts) -> Node | None:
        role = self._role(ctrl)
        if role not in wanted:
            return None
        # If the root has no usable bbox, UIA often marks every descendant as
        # offscreen. Keep returning ref-addressable nodes instead of collapsing
        # perception to an indistinguishable empty snapshot.
        if (
            clip_rect is not None
            and self._safe(lambda: bool(ctrl.IsOffscreen), False)
            and not opts.include_offscreen
        ):
            return None
        bbox = self._rect_of(ctrl)
        if bbox.w <= 0 or bbox.h <= 0:
            return None
        if clip_rect is not None and not clip_rect.intersects(bbox):
            return None

        name = self._safe(lambda: ctrl.Name or "", "")
        if len(name) > opts.name_max_len:
            name = name[: opts.name_max_len]

        return Node(
            native_id=self._native_id(ctrl),
            role=role,
            name=name,
            value=self._read_value(ctrl, opts),
            bbox=bbox,
            states=self._states(ctrl),
            patterns=self._patterns(ctrl),
        )

    @staticmethod
    def _role(ctrl) -> str:
        name = WindowsDriver._safe(lambda: ctrl.ControlTypeName, "")
        return name[:-7] if name.endswith("Control") else name

    @staticmethod
    def _children(ctrl) -> list:
        return WindowsDriver._safe(lambda: ctrl.GetChildren(), [])

    @staticmethod
    def _rect_of(ctrl) -> Rect:
        def build() -> Rect:
            r = ctrl.BoundingRectangle
            return Rect(int(r.left), int(r.top), int(r.right - r.left), int(r.bottom - r.top))

        return WindowsDriver._safe(build, Rect(0, 0, 0, 0))

    @staticmethod
    def _native_id(ctrl) -> str:
        rid = WindowsDriver._safe(lambda: ctrl.GetRuntimeId(), None)
        return "-".join(str(x) for x in rid) if rid else ""

    def _read_value(self, ctrl, opts: PruneOpts) -> str | None:
        if opts.redact_password and self._safe(lambda: bool(ctrl.IsPassword), False):
            return None
        vp = self._safe(lambda: ctrl.GetValuePattern(), None)
        if vp is None:
            return None
        value = self._safe(lambda: vp.Value, None)
        if value is None:
            return None
        if len(value) > opts.name_max_len:
            value = value[: opts.name_max_len]
        return value

    @staticmethod
    def _states(ctrl) -> list[str]:
        states: list[str] = []
        enabled = WindowsDriver._safe(lambda: bool(ctrl.IsEnabled), True)
        states.append("enabled" if enabled else "disabled")
        if WindowsDriver._safe(lambda: bool(ctrl.HasKeyboardFocus), False):
            states.append("focused")
        if WindowsDriver._safe(lambda: bool(ctrl.IsOffscreen), False):
            states.append("offscreen")
        sp = WindowsDriver._safe(lambda: ctrl.GetSelectionItemPattern(), None)
        if sp is not None and WindowsDriver._safe(lambda: bool(sp.IsSelected), False):
            states.append("selected")
        return states

    @staticmethod
    def _patterns(ctrl) -> list[str]:
        out: list[str] = []
        for label, meth in _PATTERN_PROBES:
            if WindowsDriver._safe(lambda m=meth: getattr(ctrl, m)(), None) is not None:
                out.append(label)
        return out

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default

    # --- actions -------------------------------------------------------------

    def _resolve(self, native_id: str):
        """Map a native_id back to its live control, re-validating identity so a
        changed UI surfaces as STALE_ELEMENT rather than acting on the wrong node
        (Driver Contract section D)."""
        ctrl = self._node_cache.get(native_id)
        if ctrl is None:
            return None
        if self._native_id(ctrl) != native_id:
            return None
        return ctrl

    def invoke(self, native_id: str) -> Result:
        ctrl = self._resolve(native_id)
        if ctrl is None:
            return Result.fail(STALE_ELEMENT, native_id)
        pattern = self._safe(lambda: ctrl.GetInvokePattern(), None)
        if pattern is None:
            return Result.fail(NOT_INVOKABLE, "no InvokePattern")
        authority_lost = False
        try:
            self._prepare_semantic_target(ctrl)
            self._mutate(pattern.Invoke)
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            self._finish_feedback(skip_delay=authority_lost)

    def set_value(self, native_id: str, text: str) -> Result:
        """Set a control's value via ValuePattern — focus-independent, robust to
        occlusion/DPI, and preferred over simulated typing (Driver Contract)."""
        ctrl = self._resolve(native_id)
        if ctrl is None:
            return Result.fail(STALE_ELEMENT, native_id)
        pattern = self._safe(lambda: ctrl.GetValuePattern(), None)
        if pattern is None:
            return Result.fail(NOT_INVOKABLE, "no ValuePattern")
        if self._safe(lambda: bool(pattern.IsReadOnly), False):
            return Result.fail(NOT_INVOKABLE, "value is read-only")
        authority_lost = False
        try:
            self._show_keyboard_feedback("typing")
            pacing: InteractionPacing | None = getattr(self, "_pacing", None)
            if pacing is not None:
                self._pause(pacing.pre_action_seconds)
            self._mutate(lambda: pattern.SetValue(text))
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            self._finish_feedback(skip_delay=authority_lost)

    def select(self, native_id: str) -> Result:
        ctrl = self._resolve(native_id)
        if ctrl is None:
            return Result.fail(STALE_ELEMENT, native_id)
        pattern = self._safe(lambda: ctrl.GetSelectionItemPattern(), None)
        if pattern is None:
            return Result.fail(NOT_INVOKABLE, "no SelectionItemPattern")
        authority_lost = False
        try:
            self._prepare_semantic_target(ctrl)
            self._mutate(pattern.Select)
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            self._finish_feedback(skip_delay=authority_lost)

    def type(self, text: str) -> Result:
        # Keyboard fallback for surfaces without a writable ValuePattern; targets
        # whatever holds focus, so callers must focus first.
        authority_lost = False
        try:
            interval = getattr(self, "_typing_interval", None)
            estimated_interval = 0.01 if interval is None else interval
            self._show_keyboard_feedback(
                "typing",
                total_units=len(text),
                estimated_seconds=max(0.15, len(text) * estimated_interval),
            )
            pacing: InteractionPacing | None = getattr(self, "_pacing", None)
            if pacing is not None:
                self._pause(pacing.pre_action_seconds)
            for character in text:
                batch = self._literal_character_input_batch(character)
                inserted = self._mutate(
                    lambda batch=batch: self._send_input_batch(batch),
                    native_input=True,
                )
                if inserted != len(batch):
                    raise OSError("SendInput did not insert the complete scalar")
                self._pause(estimated_interval)
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            self._finish_feedback(skip_delay=authority_lost)

    @staticmethod
    def _utf16_input_units(character: str) -> tuple[str, ...]:
        encoded = character.encode("utf-16-le", errors="surrogatepass")
        return tuple(
            chr(int.from_bytes(encoded[index : index + 2], "little"))
            for index in range(0, len(encoded), 2)
        )

    @classmethod
    def _literal_character_input_batch(cls, character: str) -> tuple[object, ...]:
        inputs = []
        for unit in cls._utf16_input_units(character):
            scan = ord(unit)
            inputs.extend(
                (
                    auto.KeyboardInput(
                        0,
                        scan,
                        auto.KeyboardEventFlag.KeyUnicode
                        | auto.KeyboardEventFlag.KeyDown,
                    ),
                    auto.KeyboardInput(
                        0,
                        scan,
                        auto.KeyboardEventFlag.KeyUnicode
                        | auto.KeyboardEventFlag.KeyUp,
                    ),
                )
            )
        return tuple(inputs)

    @staticmethod
    def _send_input_batch(inputs: tuple[object, ...]) -> int:
        """Submit one scalar and unwind a reported odd key-down prefix."""

        if not inputs:
            return 0

        def submit(batch: tuple[object, ...]) -> int:
            input_array = (auto.INPUT * len(batch))(*batch)
            input_pointer = ctypes.cast(input_array, ctypes.POINTER(auto.INPUT))
            return int(
                ctypes.windll.user32.SendInput(
                    len(batch),
                    input_pointer,
                    ctypes.sizeof(auto.INPUT),
                )
            )

        inserted = submit(inputs)
        if 0 < inserted < len(inputs) and inserted % 2:
            # The batch is ordered down/up pairs. If Win32 reports an odd
            # prefix, the next uninserted event is the matching key-up. This
            # direct bounded unwind must occur before call-local tick capture,
            # which can itself fail and hide ``inserted`` from the caller.
            try:
                submit((inputs[inserted],))
            except Exception:
                pass
        return inserted

    @staticmethod
    def _vk(token: str) -> int | None:
        t = token.strip().lower()
        if t in _MOD_KEYS:
            return _MOD_KEYS[t]
        if t in _NAMED_KEYS:
            return _NAMED_KEYS[t]
        if len(t) == 1 and t.isalnum():
            return ord(t.upper())
        if len(t) >= 2 and t[0] == "f" and t[1:].isdigit() and 1 <= int(t[1:]) <= 24:
            return 0x70 + int(t[1:]) - 1
        return None

    def key(self, combo: str) -> Result:
        """Send a key chord like 'Ctrl+S' to the foreground window via
        keybd_event. Modifiers held while the non-modifier keys are tapped."""
        tokens = [p for p in combo.replace(" ", "").split("+") if p]
        if not tokens:
            return Result.fail(DRIVER_ERROR, "empty combo")
        mods: list[int] = []
        keys: list[int] = []
        for tok in tokens:
            vk = self._vk(tok)
            if vk is None:
                return Result.fail(DRIVER_ERROR, f"unknown key {tok!r} in {combo!r}")
            (mods if tok.strip().lower() in _MOD_KEYS else keys).append(vk)
        user32 = ctypes.windll.user32
        held: list[int] = []
        authority_lost = False
        try:
            self._show_keyboard_feedback("key")
            pacing: InteractionPacing | None = getattr(self, "_pacing", None)
            if pacing is not None:
                self._pause(pacing.pre_action_seconds)
            for m in mods:
                def press_modifier(m=m) -> None:
                    held.append(m)
                    user32.keybd_event(m, 0, 0, 0)

                self._mutate(press_modifier, native_input=True)
            for k in keys:
                def press_key(k=k) -> None:
                    held.append(k)
                    user32.keybd_event(k, 0, 0, 0)

                self._mutate(press_key, native_input=True)
                self._mutate(
                    lambda k=k: user32.keybd_event(k, 0, _KEYEVENTF_KEYUP, 0),
                    native_input=True,
                )
                held.pop()
            for m in reversed(mods):
                self._mutate(
                    lambda m=m: user32.keybd_event(m, 0, _KEYEVENTF_KEYUP, 0),
                    native_input=True,
                )
                held.pop()
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            for vk in reversed(held):
                try:
                    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
                except Exception:
                    pass
            self._finish_feedback(skip_delay=authority_lost)

    def activate_window(self, window_id: str) -> Result:
        """Bring a window to the foreground (a prerequisite for keyboard input).
        Attach the caller to the foreground and target input queues while the
        native foreground calls run, then verify the final HWND."""
        try:
            hwnd = int(window_id)
        except (TypeError, ValueError):
            return Result.fail(DRIVER_ERROR, f"bad window_id {window_id!r}")
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        return _activate_window_with_api(
            hwnd,
            user32,
            ctypes.windll.kernel32,
            self._require_native_action_boundary(),
        )

    def click(self, x: int, y: int, button: str = "left", modifiers: list[str] | None = None) -> Result:
        """Coordinate click in the shared pixel space (DPI-aware). For ref-based
        actions prefer invoke/set_value — those are focus/occlusion independent."""
        downup = {
            "left": (0x0002, 0x0004),
            "right": (0x0008, 0x0010),
            "middle": (0x0020, 0x0040),
        }.get(button.lower())
        if downup is None:
            return Result.fail(DRIVER_ERROR, f"unknown button {button!r}")
        resolved_mod_vks = [self._vk(m) for m in (modifiers or [])]
        if any(v is None for v in resolved_mod_vks):
            return Result.fail(DRIVER_ERROR, f"unknown modifier in {modifiers!r}")
        mod_vks = [int(v) for v in resolved_mod_vks if v is not None]
        user32 = ctypes.windll.user32
        held_mods: list[int] = []
        mouse_held = False
        authority_lost = False
        try:
            self._move_pointer(user32, int(x), int(y), "click")
            for m in mod_vks:
                def press_modifier(m=m) -> None:
                    held_mods.append(m)
                    user32.keybd_event(m, 0, 0, 0)

                self._mutate(press_modifier, native_input=True)
            down, up = downup

            def press_mouse() -> None:
                nonlocal mouse_held
                mouse_held = True
                user32.mouse_event(down, 0, 0, 0, 0)

            self._mutate(press_mouse, native_input=True)
            self._mutate(
                lambda: user32.mouse_event(up, 0, 0, 0, 0),
                native_input=True,
            )
            mouse_held = False
            for m in reversed(mod_vks):
                self._mutate(
                    lambda m=m: user32.keybd_event(m, 0, _KEYEVENTF_KEYUP, 0),
                    native_input=True,
                )
                held_mods.pop()
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            if mouse_held:
                try:
                    user32.mouse_event(downup[1], 0, 0, 0, 0)
                except Exception:
                    pass
            for vk in reversed(held_mods):
                try:
                    user32.keybd_event(vk, 0, _KEYEVENTF_KEYUP, 0)
                except Exception:
                    pass
            self._finish_feedback(skip_delay=authority_lost)

    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Result:
        """Inject bounded horizontal and vertical wheel movement at one point."""

        user32 = ctypes.windll.user32
        authority_lost = False
        try:
            self._move_pointer(user32, int(x), int(y), "scroll")
            if delta_y:
                self._mutate(
                    lambda: user32.mouse_event(0x0800, 0, 0, int(delta_y), 0),
                    native_input=True,
                )
            if delta_x:
                self._mutate(
                    lambda: user32.mouse_event(0x1000, 0, 0, int(delta_x), 0),
                    native_input=True,
                )
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            self._finish_feedback(skip_delay=authority_lost)

    def drag(
        self, x: int, y: int, to_x: int, to_y: int, duration_ms: int = 250
    ) -> Result:
        """Inject one left-button drag with a bounded interpolated path."""

        user32 = ctypes.windll.user32
        steps = max(1, min(60, int(duration_ms) // 16 or 1))
        mouse_held = False
        authority_lost = False
        try:
            self._move_pointer(user32, int(x), int(y), "drag")

            def press_mouse() -> None:
                nonlocal mouse_held
                mouse_held = True
                user32.mouse_event(0x0002, 0, 0, 0, 0)

            self._mutate(press_mouse, native_input=True)
            for step in range(1, steps + 1):
                next_x = int(x + (to_x - x) * step / steps)
                next_y = int(y + (to_y - y) * step / steps)
                moved = self._mutate(
                    lambda next_x=next_x, next_y=next_y: user32.SetCursorPos(
                        next_x, next_y
                    ),
                    native_input=True,
                )
                if not moved:
                    raise OSError("SetCursorPos failed")
                self._show_pointer_feedback(next_x, next_y, "drag")
                if duration_ms:
                    self._pause(duration_ms / steps / 1000)
            self._mutate(
                lambda: user32.mouse_event(0x0004, 0, 0, 0, 0),
                native_input=True,
            )
            mouse_held = False
            return Result.success()
        except NativeAuthorityLost:
            authority_lost = True
            raise
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
        finally:
            if mouse_held:
                try:
                    user32.mouse_event(0x0004, 0, 0, 0, 0)
                except Exception:
                    pass
            self._finish_feedback(skip_delay=authority_lost)
