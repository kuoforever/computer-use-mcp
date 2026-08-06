from __future__ import annotations

import asyncio
import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from PIL import Image

from computer_use_mcp.audit import AuditLog
from computer_use_mcp.contract import Image as ScreenImage
from computer_use_mcp.contract import Node, ProcRef, Rect, Result, TreeResult, Window
from computer_use_mcp.human_activity import HumanInputCapture
from computer_use_mcp.native_authority import NativeActionBoundary
from computer_use_mcp.safety import EStop, is_dangerous, parse_combo, redact
from computer_use_mcp.server import build_server


SECRET = "typed-secret-" + "x" * 160
ACTIVATION_TARGET_AUTHORITY_LOST = (
    "NATIVE_AUTHORITY_LOST: activation target identity unavailable"
)


class AtomicBoundaryDriver:
    def __init__(self) -> None:
        self.native_boundary: NativeActionBoundary | None = None

    def bind_native_action_boundary(self, boundary: NativeActionBoundary) -> None:
        boundary.bind(self)
        self.native_boundary = boundary

    def _mutate(self, operation, *, native_input: bool = False):
        assert self.native_boundary is not None
        return self.native_boundary.mutate(operation, native_input=native_input)


class AuditDriver(AtomicBoundaryDriver):
    def __init__(
        self,
        *,
        idle_seconds: float = 10.0,
        foreground_name: str = "notepad.exe",
        echo_typed_text_on_error: bool = False,
    ) -> None:
        super().__init__()
        self.idle_seconds = idle_seconds
        self.foreground_name = foreground_name
        self.echo_typed_text_on_error = echo_typed_text_on_error
        self.type_calls: list[str] = []
        self.scroll_calls: list[tuple[int, int, int, int]] = []
        self.drag_calls: list[tuple[int, int, int, int, int]] = []

    def last_input_idle_seconds(self) -> float:
        return self.idle_seconds

    def last_input_tick(self) -> int:
        return 1

    def foreground_owner_chain(self) -> list[ProcRef]:
        return [ProcRef(pid=1, name=self.foreground_name)]

    def type(self, text: str) -> Result:
        self._mutate(lambda: self.type_calls.append(text), native_input=True)
        if self.echo_typed_text_on_error:
            return Result.fail("DRIVER_ERROR", f"driver echoed {text}")
        return Result.success()

    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Result:
        self._mutate(
            lambda: self.scroll_calls.append((x, y, delta_x, delta_y)),
            native_input=True,
        )
        return Result.success()

    def drag(
        self, x: int, y: int, to_x: int, to_y: int, duration_ms: int
    ) -> Result:
        self._mutate(
            lambda: self.drag_calls.append((x, y, to_x, to_y, duration_ms)),
            native_input=True,
        )
        return Result.success()


class AuthorityDriver(AtomicBoundaryDriver):
    def __init__(self, foreground_names: list[str] | None = None) -> None:
        super().__init__()
        self.foreground_names = foreground_names or ["notepad.exe"]
        self.action_calls: list[str] = []

    def list_windows(self) -> list[Window]:
        owner = ProcRef(pid=100, name=self.foreground_names[0])
        return [
            Window(
                id="window-1",
                title="Target",
                bounds=Rect(0, 0, 100, 100),
                owner=owner,
                owner_chain=[owner],
                is_foreground=False,
            )
        ]

    def capture_screen(self, _region: Rect | None = None) -> ScreenImage:
        raw = io.BytesIO()
        Image.new("RGB", (1, 1), (255, 255, 255)).save(raw, format="PNG")
        return ScreenImage(png=raw.getvalue(), width=1, height=1, scale=1.0)

    def last_input_idle_seconds(self) -> float:
        return 10.0

    def last_input_tick(self) -> int:
        return 1

    def foreground_owner_chain(self) -> list[ProcRef]:
        if len(self.foreground_names) > 1:
            name = self.foreground_names.pop(0)
        else:
            name = self.foreground_names[0]
        return [ProcRef(pid=1, name=name)]

    def activate_window(self, _window_id: str) -> Result:
        self._mutate(lambda: self.action_calls.append("activate_window"))
        return Result.success()

    def click(self, _x: int, _y: int, button: str = "left") -> Result:
        self._mutate(
            lambda: self.action_calls.append(f"click:{button}"),
            native_input=True,
        )
        return Result.success()

    def scroll(self, _x: int, _y: int, _delta_x: int, _delta_y: int) -> Result:
        self._mutate(lambda: self.action_calls.append("scroll"), native_input=True)
        return Result.success()

    def drag(
        self,
        _x: int,
        _y: int,
        _to_x: int,
        _to_y: int,
        _duration_ms: int,
    ) -> Result:
        self._mutate(lambda: self.action_calls.append("drag"), native_input=True)
        return Result.success()

    def type(self, _text: str) -> Result:
        self._mutate(lambda: self.action_calls.append("type"), native_input=True)
        return Result.success()

    def key(self, _combo: str) -> Result:
        self._mutate(lambda: self.action_calls.append("key"), native_input=True)
        return Result.success()

    def get_tree(self, _opts) -> TreeResult:
        return TreeResult(
            [
                Node(
                    native_id="delete-control",
                    role="Button",
                    name="Delete",
                    value=None,
                    bbox=Rect(10, 10, 20, 20),
                    states=["enabled"],
                    patterns=["invoke"],
                )
            ],
            truncated=0,
        )

    def invoke(self, _native_id: str) -> Result:
        self._mutate(lambda: self.action_calls.append("invoke"))
        return Result.success()


class AttributionDriver(AuthorityDriver):
    def __init__(self, *, fail_key: bool = False) -> None:
        super().__init__()
        self.idle_seconds = 10.0
        self.input_tick = 1
        self.fail_key = fail_key
        self.set_value_calls: list[str] = []

    def last_input_idle_seconds(self) -> float:
        return self.idle_seconds

    def last_input_tick(self) -> int:
        return self.input_tick

    def get_tree(self, _opts) -> TreeResult:
        return TreeResult(
            [
                Node(
                    native_id="preview-control",
                    role="Button",
                    name="Preview",
                    value=None,
                    bbox=Rect(10, 10, 20, 20),
                    states=["enabled"],
                    patterns=["invoke"],
                ),
                Node(
                    native_id="notes-control",
                    role="Edit",
                    name="Notes",
                    value="existing text",
                    bbox=Rect(40, 10, 80, 20),
                    states=["enabled"],
                    patterns=["value"],
                ),
            ],
            truncated=0,
        )

    def invoke(self, _native_id: str) -> Result:
        def invoke() -> None:
            self.action_calls.append("invoke")
            self.input_tick += 1
            self.idle_seconds = 0.1

        self._mutate(invoke)
        return Result.success()

    def click(self, _x: int, _y: int, button: str = "left") -> Result:
        def click() -> None:
            self.action_calls.append(f"click:{button}")
            self.input_tick += 1
            self.idle_seconds = 0.1

        self._mutate(click, native_input=True)
        return Result.success()

    def key(self, _combo: str) -> Result:
        def key() -> None:
            self.action_calls.append("key")
            self.input_tick += 1
            self.idle_seconds = 0.1

        self._mutate(key, native_input=True)
        if self.fail_key:
            return Result.fail("DRIVER_ERROR", "injected failure")
        return Result.success()

    def set_value(self, _native_id: str, text: str) -> Result:
        def set_value() -> None:
            self.action_calls.append("set_value")
            self.set_value_calls.append(text)

        self._mutate(set_value)
        return Result.success()


class AttemptFailureDriver(AttributionDriver):
    def get_tree(self, _opts) -> TreeResult:
        return TreeResult(
            [
                Node(
                    native_id="invoke-control",
                    role="Button",
                    name="Preview",
                    value=None,
                    bbox=Rect(10, 10, 20, 20),
                    states=["enabled"],
                    patterns=["invoke"],
                ),
                Node(
                    native_id="select-control",
                    role="RadioButton",
                    name="Choice",
                    value=None,
                    bbox=Rect(40, 10, 20, 20),
                    states=["enabled"],
                    patterns=["selectionitem"],
                ),
                Node(
                    native_id="value-control",
                    role="Edit",
                    name="Notes",
                    value="existing text",
                    bbox=Rect(70, 10, 80, 20),
                    states=["enabled"],
                    patterns=["value"],
                ),
            ],
            truncated=0,
        )

    def _fail_after_attempt(
        self,
        label: str,
        *,
        native_input: bool = False,
    ) -> Result:
        self._mutate(
            lambda: self.action_calls.append(label),
            native_input=native_input,
        )
        return Result.fail("DRIVER_ERROR", f"native failure exposed {SECRET}")

    def activate_window(self, _window_id: str) -> Result:
        return self._fail_after_attempt("activate_window")

    def click(self, _x: int, _y: int, button: str = "left") -> Result:
        return self._fail_after_attempt(f"click:{button}", native_input=True)

    def scroll(self, _x: int, _y: int, _delta_x: int, _delta_y: int) -> Result:
        return self._fail_after_attempt("scroll", native_input=True)

    def drag(
        self,
        _x: int,
        _y: int,
        _to_x: int,
        _to_y: int,
        _duration_ms: int,
    ) -> Result:
        return self._fail_after_attempt("drag", native_input=True)

    def type(self, _text: str) -> Result:
        return self._fail_after_attempt("type", native_input=True)

    def key(self, _combo: str) -> Result:
        return self._fail_after_attempt("key", native_input=True)

    def invoke(self, _native_id: str) -> Result:
        return self._fail_after_attempt("invoke")

    def select(self, _native_id: str) -> Result:
        return self._fail_after_attempt("select")

    def set_value(self, _native_id: str, _text: str) -> Result:
        return self._fail_after_attempt("set_value")


class MultiEventDriver(AttributionDriver):
    def __init__(self, after_first=None) -> None:
        super().__init__()
        self.after_first = after_first

    def key(self, _combo: str) -> Result:
        def event(label: str, *, first: bool = False) -> None:
            self.action_calls.append(label)
            self.input_tick += 1
            self.idle_seconds = 0.1
            if first and self.after_first is not None:
                self.after_first()

        self._mutate(lambda: event("key:first", first=True), native_input=True)
        self._mutate(lambda: event("key:second"), native_input=True)
        return Result.success()


class NoteTrackingActivity:
    def __init__(self) -> None:
        self.note_calls = 0
        self.final_calls: list[
            tuple[HumanInputCapture | None, HumanInputCapture | None]
        ] = []

    def wait_until_stable(self) -> None:
        return None

    def capture(self) -> HumanInputCapture:
        return HumanInputCapture(1)

    def final_blocking_reason(
        self,
        readiness: HumanInputCapture | None,
        *,
        allowed_confirmation: HumanInputCapture | None = None,
    ) -> None:
        self.final_calls.append((readiness, allowed_confirmation))
        return None

    def note_agent_action(self) -> None:
        self.note_calls += 1


def tool_text(result) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(item, "text", "") for item in content)


def _read_single_record(path: Path) -> tuple[str, dict]:
    raw = path.read_text(encoding="utf-8")
    return raw, json.loads(raw)


def _assert_secret_absent(raw: str, secret: str) -> None:
    if secret:
        assert secret not in raw
        assert secret[: min(120, len(secret))] not in raw


def test_dangerous_keywords_and_combo_parsing() -> None:
    assert is_dangerous('Button "发送"')
    assert is_dangerous('Button "Submit form"')
    assert not is_dangerous('Button "Preview"')
    assert parse_combo("Ctrl + Alt + Q") == [0x11, 0x12, ord("Q")]
    assert parse_combo("Ctrl+unknown+F24") == [0x11, 0x87]


def test_redact_covers_exactly_the_requested_rectangle() -> None:
    image = Image.new("RGB", (5, 5), (255, 255, 255))
    raw = io.BytesIO()
    image.save(raw, format="PNG")

    redacted = Image.open(io.BytesIO(redact(raw.getvalue(), [(1, 1, 2, 2)]))).convert("RGB")

    assert redacted.getpixel((1, 1)) == (0, 0, 0)
    assert redacted.getpixel((2, 2)) == (0, 0, 0)
    assert redacted.getpixel((3, 3)) == (255, 255, 255)


@pytest.mark.parametrize("secret", ["", "short-secret", SECRET])
def test_audit_log_type_records_only_allowlisted_non_reversible_metadata(
    tmp_path: Path, secret: str
) -> None:
    audit = AuditLog(tmp_path / "nested" / "actions.jsonl")
    record = audit.record(
        "type",
        {
            "text": secret,
            "ref": f"ref-{secret}",
            "alias": secret,
            "nested": {"copy": secret},
            "control_mode": [secret],
        },
        secret,
        secret,
    )
    raw, saved = _read_single_record(audit.path)

    assert record == saved
    assert saved["args"] == {
        "text_present": True,
        "text_length": len(secret),
        "ref_supplied": True,
    }
    assert saved["decision"] == "redacted"
    assert saved["result"] == {"present": True, "length": len(secret)}
    _assert_secret_absent(raw, secret)


@pytest.mark.parametrize(
    (
        "idle_seconds",
        "foreground_name",
        "engage_estop",
        "echo_error",
        "decision",
        "type_calls",
        "control_mode",
    ),
    [
        (10.0, "notepad.exe", False, False, "ok", 1, "safe_local"),
        (0.1, "notepad.exe", False, False, "human_active", 0, "safe_local"),
        (10.0, "calc.exe", False, False, "gate_denied", 0, "safe_local"),
        (10.0, "notepad.exe", True, False, "estop", 0, "safe_local"),
        (10.0, "notepad.exe", False, True, "unknown_outcome", 1, "safe_local"),
        (10.0, "notepad.exe", True, False, "estop", 0, "full_control_local"),
    ],
)
def test_server_never_writes_typed_text_for_any_type_audit_path(
    tmp_path: Path,
    idle_seconds: float,
    foreground_name: str,
    engage_estop: bool,
    echo_error: bool,
    decision: str,
    type_calls: int,
    control_mode: str,
) -> None:
    audit_path = tmp_path / "actions.jsonl"
    driver = AuditDriver(
        idle_seconds=idle_seconds,
        foreground_name=foreground_name,
        echo_typed_text_on_error=echo_error,
    )
    estop = EStop()
    if engage_estop:
        estop.engage()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        estop=estop,
        start_estop=False,
        audit_path=str(audit_path),
        control_mode=control_mode,
    )

    result = tool_text(
        asyncio.run(server.call_tool("type", {"text": SECRET, "ref": None}))
    )
    raw, record = _read_single_record(audit_path)

    assert record["tool"] == "type"
    assert record["decision"] == decision
    assert record["args"] == {
        "text_present": True,
        "text_length": len(SECRET),
        "ref_supplied": False,
        "control_mode": control_mode,
    }
    assert record["result"]["present"] is True
    assert isinstance(record["result"]["length"], int)
    assert len(driver.type_calls) == type_calls
    if echo_error:
        assert result == (
            "ERROR NATIVE_OUTCOME_UNKNOWN: "
            "native action outcome unknown after dispatch"
        )
    _assert_secret_absent(raw, SECRET)


def test_scroll_and_drag_share_the_guard_and_audit_action_boundary(
    tmp_path: Path,
) -> None:
    audit_path = tmp_path / "actions.jsonl"
    driver = AuditDriver()
    server = build_server(
        driver=driver,
        start_estop=False,
        audit_path=str(audit_path),
        control_mode="full_control_local",
    )

    assert "ok" in tool_text(
        asyncio.run(
            server.call_tool(
                "scroll",
                {"x": 10, "y": 20, "delta_x": 0, "delta_y": -120},
            )
        )
    )
    assert "ok" in tool_text(
        asyncio.run(
            server.call_tool(
                "drag",
                {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": 0},
            )
        )
    )

    records = [
        json.loads(line)
        for line in audit_path.read_text(encoding="utf-8").splitlines()
    ]
    assert driver.scroll_calls == [(10, 20, 0, -120)]
    assert driver.drag_calls == [(10, 20, 30, 40, 0)]
    assert [record["tool"] for record in records] == ["scroll", "drag"]
    assert all(record["decision"] == "ok" for record in records)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("scroll", {"x": 1, "y": 2, "delta_x": 0, "delta_y": 0}),
        ("scroll", {"x": 1, "y": 2, "delta_x": 0, "delta_y": 2401}),
        (
            "drag",
            {"x": 1, "y": 2, "to_x": 1, "to_y": 2, "duration_ms": 250},
        ),
        (
            "drag",
            {"x": 1, "y": 2, "to_x": 3, "to_y": 4, "duration_ms": 5001},
        ),
    ],
)
def test_server_rejects_unbounded_or_noop_motion_before_driver(
    tmp_path: Path, tool: str, arguments: dict[str, int]
) -> None:
    driver = AuditDriver()
    server = build_server(
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
        control_mode="full_control_local",
    )

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))

    assert "ERROR DRIVER_ERROR" in result
    assert driver.scroll_calls == []
    assert driver.drag_calls == []


def test_semantic_ref_click_preserves_concurrent_human_input_authority(
    tmp_path: Path,
) -> None:
    driver = AttributionDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        dangerous_confirmation=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))

    semantic = tool_text(
        asyncio.run(
            server.call_tool("click", {"ref": "ref_1", "x": None, "y": None})
        )
    )
    native = tool_text(
        asyncio.run(
            server.call_tool("click", {"ref": None, "x": 50, "y": 60})
        )
    )

    assert semantic == "ok"
    assert native.startswith("HUMAN_ACTIVE:")
    assert driver.action_calls == ["invoke"]


def test_successful_native_input_is_attributed_without_self_blocking(
    tmp_path: Path,
) -> None:
    driver = AttributionDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    first = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
    second = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))

    assert first == "ok"
    assert second == "ok"
    assert driver.action_calls == ["key", "key"]


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("click", {"ref": None, "x": 10, "y": 20}),
        ("scroll", {"x": 10, "y": 20, "delta_x": 0, "delta_y": -120}),
        (
            "drag",
            {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": 0},
        ),
        ("type", {"text": "safe text", "ref": None}),
        ("key", {"combo": "Ctrl+S"}),
    ],
)
def test_each_successful_native_input_route_claims_one_agent_tick(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
) -> None:
    activity = NoteTrackingActivity()
    driver = AttributionDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))

    assert result == "ok"
    assert activity.note_calls == 1


@pytest.mark.parametrize(
    ("tool", "arguments", "expected_calls", "expected_prefix", "decision"),
    [
        (
            "scroll",
            {"x": 1, "y": 2, "delta_x": 0, "delta_y": 2401},
            [],
            "ERROR DRIVER_ERROR:",
            "ok",
        ),
        (
            "drag",
            {"x": 1, "y": 2, "to_x": 1, "to_y": 2, "duration_ms": 250},
            [],
            "ERROR DRIVER_ERROR:",
            "ok",
        ),
        (
            "key",
            {"combo": "Ctrl+S"},
            ["key"],
            "ERROR NATIVE_OUTCOME_UNKNOWN:",
            "unknown_outcome",
        ),
    ],
)
def test_invalid_noop_or_failed_input_does_not_claim_an_agent_tick(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
    expected_calls: list[str],
    expected_prefix: str,
    decision: str,
) -> None:
    activity = NoteTrackingActivity()
    driver = AttributionDriver(fail_key=tool == "key")
    audit_path = tmp_path / "actions.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(audit_path),
    )

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))
    _, record = _read_single_record(audit_path)

    assert result.startswith(expected_prefix)
    assert activity.note_calls == 0
    assert driver.action_calls == expected_calls
    assert record["decision"] == decision


@pytest.mark.parametrize(
    ("tool", "arguments", "expected_call", "snapshot_first"),
    [
        ("activate_window", {"window_id": "window-1"}, "activate_window", False),
        ("click", {"ref": None, "x": 10, "y": 20}, "click:left", False),
        (
            "scroll",
            {"x": 10, "y": 20, "delta_x": 0, "delta_y": -120},
            "scroll",
            False,
        ),
        (
            "drag",
            {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": 0},
            "drag",
            False,
        ),
        ("type", {"text": SECRET, "ref": None}, "type", False),
        ("key", {"combo": "Ctrl+S"}, "key", False),
        ("click", {"ref": "ref_1", "x": None, "y": None}, "invoke", True),
        ("click", {"ref": "ref_2", "x": None, "y": None}, "select", True),
        ("type", {"text": SECRET, "ref": "ref_3"}, "set_value", True),
    ],
)
def test_failed_windows_action_after_attempt_is_fixed_redacted_unknown(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
    expected_call: str,
    snapshot_first: bool,
) -> None:
    activity = NoteTrackingActivity()
    driver = AttemptFailureDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        dangerous_confirmation=False,
        audit_path=str(audit_path),
    )
    if snapshot_first:
        asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))
    if tool == "activate_window":
        asyncio.run(server.call_tool("list_windows", {}))

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))
    raw = audit_path.read_text(encoding="utf-8")
    record = json.loads(raw.splitlines()[-1])

    assert result == (
        "ERROR NATIVE_OUTCOME_UNKNOWN: "
        "native action outcome unknown after dispatch"
    )
    assert driver.action_calls == [expected_call]
    assert activity.note_calls == 0
    assert record["tool"] == tool
    assert record["decision"] == "unknown_outcome"
    _assert_secret_absent(raw, SECRET)


def test_zero_attempt_driver_failure_retains_existing_action_error(
    tmp_path: Path,
) -> None:
    class ZeroAttemptFailureDriver(AttributionDriver):
        def key(self, _combo: str) -> Result:
            self.action_calls.append("key:zero-attempt-failure")
            return Result.fail("DRIVER_ERROR", "zero-attempt failure")

    driver = ZeroAttemptFailureDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(audit_path),
    )

    result = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
    _, record = _read_single_record(audit_path)

    assert result == "ERROR DRIVER_ERROR: zero-attempt failure"
    assert driver.action_calls == ["key:zero-attempt-failure"]
    assert record["decision"] == "ok"


@pytest.mark.parametrize(
    ("case", "arguments", "expected_prefix", "snapshot_first"),
    [
        (
            "stale",
            {"ref": "ref_999", "x": None, "y": None},
            "ERROR STALE_ELEMENT:",
            False,
        ),
        (
            "missing_pattern",
            {"ref": "ref_1", "x": None, "y": None},
            "ERROR NOT_INVOKABLE:",
            True,
        ),
        (
            "bad_arguments",
            {"ref": None, "x": None, "y": None},
            "ERROR DRIVER_ERROR:",
            False,
        ),
    ],
)
def test_zero_attempt_ref_and_argument_failures_keep_existing_certainty(
    tmp_path: Path,
    case: str,
    arguments: dict[str, object],
    expected_prefix: str,
    snapshot_first: bool,
) -> None:
    class ZeroAttemptControlDriver(AttributionDriver):
        def get_tree(self, _opts) -> TreeResult:
            return TreeResult(
                [
                    Node(
                        native_id="unsupported-control",
                        role="Text",
                        name="Unsupported",
                        value=None,
                        bbox=Rect(10, 10, 20, 20),
                        states=["enabled"],
                        patterns=[],
                    )
                ],
                truncated=0,
            )

    driver = ZeroAttemptControlDriver()
    audit_path = tmp_path / f"{case}.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        dangerous_confirmation=False,
        audit_path=str(audit_path),
    )
    if snapshot_first:
        asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))

    result = tool_text(asyncio.run(server.call_tool("click", arguments)))
    record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[-1])

    assert result.startswith(expected_prefix)
    assert "NATIVE_OUTCOME_UNKNOWN" not in result
    assert driver.action_calls == []
    assert record["decision"] == "ok"


def test_native_exception_after_attempt_is_redacted_after_bounded_cleanup(
    tmp_path: Path,
) -> None:
    class RaisingKeyDriver(AttributionDriver):
        def __init__(self) -> None:
            super().__init__()
            self.cleanup_calls: list[str] = []

        def key(self, _combo: str) -> Result:
            def raise_after_effect() -> None:
                self.action_calls.append("key")
                raise RuntimeError(f"native exception exposed {SECRET}")

            try:
                return self._mutate(raise_after_effect, native_input=True)
            finally:
                self.cleanup_calls.append("key-release")

    activity = NoteTrackingActivity()
    driver = RaisingKeyDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(audit_path),
    )

    result = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
    raw, record = _read_single_record(audit_path)

    assert result == (
        "ERROR NATIVE_OUTCOME_UNKNOWN: "
        "native action outcome unknown after dispatch"
    )
    assert driver.action_calls == ["key"]
    assert driver.cleanup_calls == ["key-release"]
    assert activity.note_calls == 0
    assert record["decision"] == "unknown_outcome"
    _assert_secret_absent(raw, SECRET)


def test_activation_does_not_claim_an_agent_input_tick(tmp_path: Path) -> None:
    activity = NoteTrackingActivity()
    driver = AttributionDriver()
    server = build_server(
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("list_windows", {}))

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "window-1"}))
    )

    assert result == "ok"
    assert activity.note_calls == 0
    assert driver.action_calls == ["activate_window"]


def test_semantic_ref_type_is_not_attributed_and_stays_redacted(
    tmp_path: Path,
) -> None:
    activity = NoteTrackingActivity()
    driver = AttributionDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(audit_path),
    )
    asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))

    result = tool_text(
        asyncio.run(server.call_tool("type", {"text": SECRET, "ref": "ref_2"}))
    )
    raw, record = _read_single_record(audit_path)

    assert result == "ok"
    assert driver.action_calls == ["set_value"]
    assert driver.set_value_calls == [SECRET]
    assert activity.note_calls == 0
    assert record["args"] == {
        "text_present": True,
        "text_length": len(SECRET),
        "ref_supplied": True,
        "control_mode": "safe_local",
    }
    assert record["result"] == {"present": True, "length": 2}
    _assert_secret_absent(raw, SECRET)


ACTION_CASES = (
    ("activate_window", {"window_id": "window-1"}),
    ("click", {"ref": None, "x": 10, "y": 20}),
    ("scroll", {"x": 10, "y": 20, "delta_x": 0, "delta_y": -120}),
    (
        "drag",
        {"x": 10, "y": 20, "to_x": 30, "to_y": 40, "duration_ms": 0},
    ),
    ("type", {"text": "safe text", "ref": None}),
    ("key", {"combo": "Ctrl+S"}),
)


@pytest.mark.parametrize(("tool", "arguments"), ACTION_CASES)
def test_estop_engaged_during_human_idle_wait_denies_final_dispatch(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
) -> None:
    driver = AuthorityDriver()
    estop = EStop()

    class EngagingActivity:
        def wait_until_stable(self) -> None:
            estop.engage()
            return None

        def capture(self) -> HumanInputCapture:
            return HumanInputCapture(1)

    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        estop=estop,
        start_estop=False,
        human_activity=EngagingActivity(),
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))

    assert result.startswith("ABORTED:")
    assert driver.action_calls == []


@pytest.mark.parametrize(("tool", "arguments"), ACTION_CASES[1:])
def test_foreground_change_after_initial_gate_denies_final_dispatch(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
) -> None:
    driver = AuthorityDriver(["notepad.exe", "calc.exe"])
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))

    assert result.startswith("DENIED by gate:")
    assert driver.action_calls == []


@pytest.mark.parametrize(("tool", "arguments"), ACTION_CASES[1:])
def test_human_input_during_foreground_retry_denies_final_dispatch(
    tmp_path: Path,
    tool: str,
    arguments: dict[str, object],
) -> None:
    class HumanDuringForegroundRetryDriver(AuthorityDriver):
        def __init__(self) -> None:
            super().__init__(["calc.exe", "notepad.exe", "notepad.exe"])
            self.idle_seconds = 10.0
            self.input_tick = 1
            self.foreground_checks = 0

        def last_input_idle_seconds(self) -> float:
            return self.idle_seconds

        def last_input_tick(self) -> int:
            return self.input_tick

        def foreground_owner_chain(self) -> list[ProcRef]:
            chain = super().foreground_owner_chain()
            self.foreground_checks += 1
            if self.foreground_checks == 1:
                self.idle_seconds = 0.1
                self.input_tick = 2
            return chain

    audit_path = tmp_path / "actions.jsonl"
    driver = HumanDuringForegroundRetryDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        dangerous_confirmation=False,
        audit_path=str(audit_path),
    )

    result = tool_text(asyncio.run(server.call_tool(tool, arguments)))
    _, record = _read_single_record(audit_path)

    assert result.startswith("HUMAN_ACTIVE:")
    assert driver.foreground_checks == 3
    assert driver.action_calls == []
    assert record["decision"] == "human_active"


def test_activate_window_rechecks_human_input_without_a_foreground_gate(
    tmp_path: Path,
) -> None:
    class HumanAfterReadinessDriver(AuthorityDriver):
        def __init__(self) -> None:
            super().__init__()
            self.input_tick_calls = 0

        def last_input_idle_seconds(self) -> float:
            return 10.0 if self.input_tick_calls == 0 else 0.1

        def last_input_tick(self) -> int:
            self.input_tick_calls += 1
            return 1 if self.input_tick_calls == 1 else 2

    driver = HumanAfterReadinessDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("list_windows", {}))

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "window-1"}))
    )

    assert result.startswith("HUMAN_ACTIVE:")
    assert driver.foreground_names == ["notepad.exe"]
    assert driver.action_calls == []


def test_activate_window_keeps_its_foreground_gate_exception(tmp_path: Path) -> None:
    driver = AuthorityDriver(["calc.exe"])
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("list_windows", {}))

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "window-1"}))
    )

    assert result == "ok"
    assert driver.action_calls == ["activate_window"]


class ActivationOwnerReuseDriver(AuthorityDriver):
    OWNER_A = ProcRef(pid=100, name="notepad.exe")
    OWNER_B = ProcRef(pid=200, name="secrets.exe")

    def __init__(self) -> None:
        super().__init__()
        self.window_owner: ProcRef | None = self.OWNER_A
        self.activation_entries = 0
        self.native_mutations: list[str] = []
        self.window_reads = 0
        self.raise_window_read = False
        self.raise_window_read_at: int | None = None
        self.additional_window_owner: ProcRef | None = None
        self.drift_before_first = False
        self.drift_after_first = False
        self.drift_after_last = False

    def list_windows(self) -> list[Window]:
        self.window_reads += 1
        if self.raise_window_read or self.window_reads == self.raise_window_read_at:
            raise RuntimeError("injected window enumeration failure")
        if self.window_owner is None:
            return []
        owner = ProcRef(pid=self.window_owner.pid, name=self.window_owner.name)
        windows = [
            Window(
                id="42",
                title="Reusable target",
                bounds=Rect(0, 0, 100, 100),
                owner=owner,
                owner_chain=[owner],
                is_foreground=False,
            )
        ]
        if self.additional_window_owner is not None:
            additional_owner = ProcRef(
                pid=self.additional_window_owner.pid,
                name=self.additional_window_owner.name,
            )
            windows.append(
                Window(
                    id="42",
                    title="Ambiguous target",
                    bounds=Rect(0, 0, 100, 100),
                    owner=additional_owner,
                    owner_chain=[additional_owner],
                    is_foreground=False,
                )
            )
        return windows

    def activate_window(self, _window_id: str) -> Result:
        self.activation_entries += 1
        if self.drift_before_first:
            self.drift_before_first = False
            self.window_owner = self.OWNER_B

        def first_mutation() -> None:
            self.native_mutations.append("first")
            if self.drift_after_first:
                self.drift_after_first = False
                self.window_owner = self.OWNER_B

        self._mutate(first_mutation)

        def second_mutation() -> None:
            self.native_mutations.append("second")
            if self.drift_after_last:
                self.drift_after_last = False
                self.window_owner = self.OWNER_B

        self._mutate(second_mutation)
        return Result.success()


def _activation_server(
    tmp_path: Path,
    driver: ActivationOwnerReuseDriver,
    *,
    control_mode: str = "safe_local",
):
    return build_server(
        allowlist=["notepad.exe", "secrets.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
        control_mode=control_mode,
    )


def test_screenshot_uses_normalized_environment_redaction_titles(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CUMCP_REDACT_TITLES", "KeePass, Reusable")
    server = _activation_server(tmp_path, ActivationOwnerReuseDriver())

    result = asyncio.run(server.call_tool("screenshot", {}))
    content = result[0] if isinstance(result, tuple) else result
    screenshot = Image.open(io.BytesIO(base64.b64decode(content[0].data))).convert("RGB")

    assert screenshot.getpixel((0, 0)) == (0, 0, 0)


def test_activate_window_requires_a_model_visible_window_binding(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = _activation_server(tmp_path, driver)

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )
    _, record = _read_single_record(audit_path)

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.window_reads == 0
    assert driver.activation_entries == 0
    assert driver.native_mutations == []
    assert record["decision"] == "authority_lost"


def test_activate_window_accepts_a_stable_observed_owner(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    observed = tool_text(asyncio.run(server.call_tool("list_windows", {})))

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert '42 | notepad.exe | "Reusable target"' in observed
    assert result == "ok"
    assert driver.activation_entries == 1
    assert driver.native_mutations == ["first", "second"]


@pytest.mark.parametrize("control_mode", ["safe_local", "full_control_local"])
def test_activate_window_rechecks_owner_before_first_native_mutation(
    tmp_path: Path,
    control_mode: str,
) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver, control_mode=control_mode)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.drift_before_first = True

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 1
    assert driver.native_mutations == []


def test_activate_window_rechecks_estop_after_target_enumeration(tmp_path: Path) -> None:
    estop = EStop()

    class EngagingTargetProbeDriver(ActivationOwnerReuseDriver):
        def list_windows(self) -> list[Window]:
            windows = super().list_windows()
            if self.window_reads == 3:
                estop.engage()
            return windows

    driver = EngagingTargetProbeDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        estop=estop,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("list_windows", {}))

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result.startswith("ABORTED:")
    assert driver.window_reads == 3
    assert driver.activation_entries == 1
    assert driver.native_mutations == []


@pytest.mark.parametrize(
    "replacement",
    [
        ProcRef(pid=200, name="notepad.exe"),
        ProcRef(pid=100, name="secrets.exe"),
    ],
)
def test_activate_window_binds_both_owner_pid_and_name(
    tmp_path: Path,
    replacement: ProcRef,
) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.window_owner = replacement

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_activate_window_owner_loss_after_attempt_is_unknown_and_stops(
    tmp_path: Path,
) -> None:
    driver = ActivationOwnerReuseDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.drift_after_first = True

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )
    _, record = _read_single_record(audit_path)

    assert result == (
        "ERROR NATIVE_AUTHORITY_LOST: "
        "native action authority changed after dispatch"
    )
    assert driver.activation_entries == 1
    assert driver.native_mutations == ["first"]
    assert record["decision"] == "unknown_outcome"


def test_activate_window_owner_loss_after_last_attempt_is_not_reported_success(
    tmp_path: Path,
) -> None:
    driver = ActivationOwnerReuseDriver()
    audit_path = tmp_path / "actions.jsonl"
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.drift_after_last = True

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )
    _, record = _read_single_record(audit_path)

    assert result == (
        "ERROR NATIVE_AUTHORITY_LOST: "
        "native action authority changed after dispatch"
    )
    assert driver.activation_entries == 1
    assert driver.native_mutations == ["first", "second"]
    assert record["decision"] == "unknown_outcome"


def test_activate_window_rejects_a_disappeared_observed_target(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.window_owner = None

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_duplicate_window_ids_never_bind_or_validate_activation_owner(
    tmp_path: Path,
) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    driver.additional_window_owner = ProcRef(pid=0, name="")
    asyncio.run(server.call_tool("list_windows", {}))

    unbound = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )
    driver.additional_window_owner = None
    asyncio.run(server.call_tool("list_windows", {}))
    driver.additional_window_owner = driver.OWNER_B
    ambiguous = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert unbound == ACTIVATION_TARGET_AUTHORITY_LOST
    assert ambiguous == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


@pytest.mark.parametrize(
    "invalid_owner",
    [
        ProcRef(pid=0, name="notepad.exe"),
        ProcRef(pid=100, name=""),
    ],
)
def test_invalid_unique_window_owner_never_binds_activation(
    tmp_path: Path,
    invalid_owner: ProcRef,
) -> None:
    driver = ActivationOwnerReuseDriver()
    driver.window_owner = invalid_owner
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_inflight_activation_never_follows_a_concurrent_rebinding(tmp_path: Path) -> None:
    class BlockingActivity(NoteTrackingActivity):
        def __init__(self) -> None:
            super().__init__()
            self.waiting = Event()
            self.release = Event()
            self.wait_calls = 0

        def wait_until_stable(self) -> None:
            self.wait_calls += 1
            if self.wait_calls == 1:
                self.waiting.set()
                assert self.release.wait(timeout=5)
            return None

    activity = BlockingActivity()
    driver = ActivationOwnerReuseDriver()
    server = build_server(
        allowlist=["notepad.exe", "secrets.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("list_windows", {}))

    with ThreadPoolExecutor(max_workers=1) as executor:
        inflight = executor.submit(
            lambda: tool_text(
                asyncio.run(
                    server.call_tool("activate_window", {"window_id": "42"})
                )
            )
        )
        assert activity.waiting.wait(timeout=5)
        driver.window_owner = driver.OWNER_B
        asyncio.run(server.call_tool("list_windows", {}))
        activity.release.set()
        old_result = inflight.result(timeout=5)

    new_result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert old_result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert new_result == "ok"
    assert driver.activation_entries == 1
    assert driver.native_mutations == ["first", "second"]


def test_empty_model_visible_list_clears_activation_bindings(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.window_owner = None

    observed = tool_text(asyncio.run(server.call_tool("list_windows", {})))
    driver.window_owner = driver.OWNER_A
    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert observed == "(no windows)"
    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_internal_window_reads_cannot_rebind_activation_owner(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.window_owner = driver.OWNER_B

    assert driver.window_reads == 1
    asyncio.run(server.call_tool("screenshot", {}))
    assert driver.window_reads == 2
    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.window_reads == 3
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_failed_model_visible_list_cannot_rebind_activation_owner(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.window_owner = driver.OWNER_B
    driver.raise_window_read = True

    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("list_windows", {}))
    driver.raise_window_read = False
    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_activation_owner_probe_failure_is_known_not_dispatched(tmp_path: Path) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.raise_window_read_at = 2

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert result == ACTIVATION_TARGET_AUTHORITY_LOST
    assert driver.activation_entries == 0
    assert driver.native_mutations == []


def test_activate_window_requires_fresh_list_after_owner_replacement(
    tmp_path: Path,
) -> None:
    driver = ActivationOwnerReuseDriver()
    server = _activation_server(tmp_path, driver)
    asyncio.run(server.call_tool("list_windows", {}))
    driver.window_owner = driver.OWNER_B

    first = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )
    second = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )
    observed = tool_text(asyncio.run(server.call_tool("list_windows", {})))
    rebound = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "42"}))
    )

    assert first == ACTIVATION_TARGET_AUTHORITY_LOST
    assert second == ACTIVATION_TARGET_AUTHORITY_LOST
    assert '42 | secrets.exe | "Reusable target"' in observed
    assert rebound == "ok"
    assert driver.activation_entries == 1
    assert driver.native_mutations == ["first", "second"]


def test_dangerous_confirmation_cannot_outlive_foreground_authority(
    tmp_path: Path,
) -> None:
    driver = AuthorityDriver(["notepad.exe"])

    def confirm_and_change_foreground(_prompt: str) -> bool:
        driver.foreground_names[:] = ["calc.exe"]
        return True

    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        confirmer=confirm_and_change_foreground,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))

    result = tool_text(
        asyncio.run(server.call_tool("click", {"ref": "ref_1", "x": None, "y": None}))
    )

    assert result.startswith("DENIED by gate:")
    assert driver.action_calls == []


def test_dangerous_confirmation_tick_is_allowed_once_for_its_click(
    tmp_path: Path,
) -> None:
    class ConfirmingDriver(AuthorityDriver):
        def __init__(self) -> None:
            super().__init__()
            self.idle_seconds = 10.0
            self.input_tick = 1

        def last_input_idle_seconds(self) -> float:
            return self.idle_seconds

        def last_input_tick(self) -> int:
            return self.input_tick

    driver = ConfirmingDriver()

    def confirm(_prompt: str) -> bool:
        driver.idle_seconds = 0.1
        driver.input_tick = 2
        return True

    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        confirmer=confirm,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))

    confirmed = tool_text(
        asyncio.run(server.call_tool("click", {"ref": "ref_1", "x": None, "y": None}))
    )
    next_action = tool_text(
        asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"}))
    )

    assert confirmed == "ok"
    assert next_action.startswith("HUMAN_ACTIVE:")
    assert driver.action_calls == ["invoke"]


@pytest.mark.parametrize("control_mode", ["safe_local", "full_control_local"])
def test_estop_loss_after_partial_native_input_is_unknown_and_stops(
    tmp_path: Path,
    control_mode: str,
) -> None:
    estop = EStop()
    driver = MultiEventDriver(after_first=estop.engage)
    audit_path = tmp_path / f"{control_mode}.jsonl"
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        estop=estop,
        start_estop=False,
        audit_path=str(audit_path),
        control_mode=control_mode,
    )

    result = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]

    assert result == (
        "ERROR NATIVE_AUTHORITY_LOST: "
        "native action authority changed after dispatch"
    )
    assert driver.action_calls == ["key:first"]
    assert len(records) == 1
    assert records[0]["decision"] == "unknown_outcome"


def test_foreground_loss_after_partial_native_input_is_unknown_and_stops(
    tmp_path: Path,
) -> None:
    driver = MultiEventDriver()
    driver.after_first = lambda: setattr(driver, "foreground_names", ["calc.exe"])
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))

    assert result.startswith("ERROR NATIVE_AUTHORITY_LOST:")
    assert driver.action_calls == ["key:first"]


def test_call_local_agent_input_tick_allows_the_next_event_and_next_call(
    tmp_path: Path,
) -> None:
    driver = MultiEventDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    first = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))
    second = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))

    assert first == second == "ok"
    assert driver.action_calls == ["key:first", "key:second"] * 2


def test_call_local_agent_input_tick_is_consumed_by_exactly_one_checkpoint(
    tmp_path: Path,
) -> None:
    class OneInputThenTwoChecksDriver(AuthorityDriver):
        def key(self, _combo: str) -> Result:
            self._mutate(
                lambda: self.action_calls.append("key:first"),
                native_input=True,
            )
            self._mutate(lambda: self.action_calls.append("key:second"))
            self._mutate(lambda: self.action_calls.append("key:third"))
            return Result.success()

    class OneShotActivity(NoteTrackingActivity):
        def final_blocking_reason(
            self,
            readiness: HumanInputCapture | None,
            *,
            allowed_confirmation: HumanInputCapture | None = None,
        ) -> str | None:
            self.final_calls.append((readiness, allowed_confirmation))
            if len(self.final_calls) == 4 and allowed_confirmation is None:
                return "human input changed after action readiness"
            return None

    activity = OneShotActivity()
    driver = OneInputThenTwoChecksDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))

    assert result.startswith("ERROR NATIVE_AUTHORITY_LOST:")
    assert driver.action_calls == ["key:first", "key:second"]
    assert [allowed for _readiness, allowed in activity.final_calls] == [
        None,
        None,
        HumanInputCapture(1),
        None,
    ]


def test_human_loss_after_partial_native_input_is_unknown_and_stops(
    tmp_path: Path,
) -> None:
    class DriftingActivity(NoteTrackingActivity):
        def final_blocking_reason(
            self,
            readiness: HumanInputCapture | None,
            *,
            allowed_confirmation: HumanInputCapture | None = None,
        ) -> str | None:
            self.final_calls.append((readiness, allowed_confirmation))
            return "human input changed after action readiness" if len(self.final_calls) == 3 else None

    activity = DriftingActivity()
    driver = MultiEventDriver()
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        human_activity=activity,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(asyncio.run(server.call_tool("key", {"combo": "Ctrl+S"})))

    assert result.startswith("ERROR NATIVE_AUTHORITY_LOST:")
    assert driver.action_calls == ["key:first"]


def test_input_after_dangerous_confirmation_invalidates_its_exact_tick(
    tmp_path: Path,
) -> None:
    class PostConfirmationInputDriver(AuthorityDriver):
        def __init__(self) -> None:
            super().__init__()
            self.idle_seconds = 10.0
            self.input_tick = 1
            self.foreground_checks = 0

        def last_input_idle_seconds(self) -> float:
            return self.idle_seconds

        def last_input_tick(self) -> int:
            return self.input_tick

        def foreground_owner_chain(self) -> list[ProcRef]:
            self.foreground_checks += 1
            if self.foreground_checks == 2:
                self.input_tick = 3
                self.idle_seconds = 0.1
            return super().foreground_owner_chain()

    driver = PostConfirmationInputDriver()

    def confirm(_prompt: str) -> bool:
        driver.input_tick = 2
        driver.idle_seconds = 0.1
        return True

    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        confirmer=confirm,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )
    asyncio.run(server.call_tool("ui_snapshot", {"scope": "foreground"}))

    result = tool_text(
        asyncio.run(server.call_tool("click", {"ref": "ref_1", "x": None, "y": None}))
    )

    assert result.startswith("HUMAN_ACTIVE:")
    assert driver.foreground_checks == 2
    assert driver.action_calls == []
