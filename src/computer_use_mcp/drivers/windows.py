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
from ctypes import wintypes

import mss
import mss.tools
import psutil
import uiautomation as auto

from ..contract import (
    CONTRACT_VERSION,
    DRIVER_ERROR,
    NOT_INVOKABLE,
    STALE_ELEMENT,
    Display,
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
}
_KEYEVENTF_KEYUP = 0x0002


class WindowsDriver(Driver):
    def __init__(self) -> None:
        # Backstop: real entrypoints set this earlier, before uiautomation import.
        self.dpi_mode = enable_dpi_awareness()
        # native_id -> live UIA control, repopulated each get_tree(); actions
        # resolve refs through it. The core owns ref<->native_id; this is the
        # driver-side native_id<->handle half of that mapping.
        self._node_cache: dict[str, object] = {}

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
        return int(ctypes.windll.user32.GetForegroundWindow())

    @staticmethod
    def _pid_of_hwnd(hwnd: int) -> int:
        pid = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)

    def foreground_owner_chain(self) -> list[ProcRef]:
        return self._chain_for_pid(self._pid_of_hwnd(self._foreground_hwnd()))

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
        self._node_cache = {}
        root = self._root_for_scope(opts)
        win_rect = self._rect_of(root)
        wanted = set(opts.resolved_types())

        nodes: list[Node] = []
        seen: dict[tuple, int] = {}
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
            node = self._maybe_node(ctrl, wanted, win_rect, opts)
            if node is None:
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
            if len(nodes) >= opts.max_nodes:
                truncated += 1
                continue
            if dedup_key is not None:
                seen[dedup_key] = len(nodes)
            nodes.append(node)
            if node.native_id:
                self._node_cache[node.native_id] = ctrl
        return TreeResult(nodes=nodes, truncated=truncated)

    def find(self, opts: PruneOpts, query: str) -> TreeResult:
        tree = self.get_tree(opts)
        q = query.lower()
        matched = [n for n in tree.nodes if q in n.name.lower() or q in n.role.lower()]
        return TreeResult(nodes=matched, truncated=tree.truncated)

    # --- node construction ---------------------------------------------------

    def _maybe_node(self, ctrl, wanted: set[str], win_rect: Rect, opts: PruneOpts) -> Node | None:
        role = self._role(ctrl)
        if role not in wanted:
            return None
        if self._safe(lambda: bool(ctrl.IsOffscreen), False) and not opts.include_offscreen:
            return None
        bbox = self._rect_of(ctrl)
        if bbox.w <= 0 or bbox.h <= 0:
            return None
        if not win_rect.intersects(bbox):
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
        try:
            pattern.Invoke()
            return Result.success()
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))

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
        try:
            pattern.SetValue(text)
            return Result.success()
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))

    def select(self, native_id: str) -> Result:
        ctrl = self._resolve(native_id)
        if ctrl is None:
            return Result.fail(STALE_ELEMENT, native_id)
        pattern = self._safe(lambda: ctrl.GetSelectionItemPattern(), None)
        if pattern is None:
            return Result.fail(NOT_INVOKABLE, "no SelectionItemPattern")
        try:
            pattern.Select()
            return Result.success()
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))

    def type(self, text: str) -> Result:
        # Keyboard fallback for surfaces without a writable ValuePattern; targets
        # whatever holds focus, so callers must focus first.
        try:
            auto.SendKeys(text, waitTime=0.0)
            return Result.success()
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))

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
        try:
            for m in mods:
                user32.keybd_event(m, 0, 0, 0)
            for k in keys:
                user32.keybd_event(k, 0, 0, 0)
                user32.keybd_event(k, 0, _KEYEVENTF_KEYUP, 0)
            for m in reversed(mods):
                user32.keybd_event(m, 0, _KEYEVENTF_KEYUP, 0)
            return Result.success()
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))

    def activate_window(self, window_id: str) -> Result:
        """Bring a window to the foreground (a prerequisite for keyboard input).
        Uses AttachThreadInput to bypass the SetForegroundWindow lock that
        otherwise blocks a background process from raising another window."""
        try:
            hwnd = int(window_id)
        except (TypeError, ValueError):
            return Result.fail(DRIVER_ERROR, f"bad window_id {window_id!r}")
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        try:
            fg = int(user32.GetForegroundWindow() or 0)
            if fg == hwnd:
                return Result.success()
            fg_thread = user32.GetWindowThreadProcessId(fg, None)
            tgt_thread = user32.GetWindowThreadProcessId(hwnd, None)
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            attached = bool(fg_thread != tgt_thread
                            and user32.AttachThreadInput(fg_thread, tgt_thread, True))
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(fg_thread, tgt_thread, False)
            if int(user32.GetForegroundWindow() or 0) == hwnd:
                return Result.success()
            return Result.fail(DRIVER_ERROR, "could not bring window to foreground")
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))

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
        mod_vks = [self._vk(m) for m in (modifiers or [])]
        if any(v is None for v in mod_vks):
            return Result.fail(DRIVER_ERROR, f"unknown modifier in {modifiers!r}")
        user32 = ctypes.windll.user32
        try:
            user32.SetCursorPos(int(x), int(y))
            for m in mod_vks:
                user32.keybd_event(m, 0, 0, 0)
            down, up = downup
            user32.mouse_event(down, 0, 0, 0, 0)
            user32.mouse_event(up, 0, 0, 0, 0)
            for m in reversed(mod_vks):
                user32.keybd_event(m, 0, _KEYEVENTF_KEYUP, 0)
            return Result.success()
        except Exception as exc:
            return Result.fail(DRIVER_ERROR, str(exc))
