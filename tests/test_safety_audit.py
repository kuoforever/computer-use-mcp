from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from computer_use_mcp.audit import AuditLog
from computer_use_mcp.contract import Node, ProcRef, Rect, Result, TreeResult
from computer_use_mcp.safety import EStop, is_dangerous, parse_combo, redact
from computer_use_mcp.server import build_server


SECRET = "typed-secret-" + "x" * 160


class AuditDriver:
    def __init__(
        self,
        *,
        idle_seconds: float = 10.0,
        foreground_name: str = "notepad.exe",
        echo_typed_text_on_error: bool = False,
    ) -> None:
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
        self.type_calls.append(text)
        if self.echo_typed_text_on_error:
            return Result.fail("DRIVER_ERROR", f"driver echoed {text}")
        return Result.success()

    def scroll(self, x: int, y: int, delta_x: int, delta_y: int) -> Result:
        self.scroll_calls.append((x, y, delta_x, delta_y))
        return Result.success()

    def drag(
        self, x: int, y: int, to_x: int, to_y: int, duration_ms: int
    ) -> Result:
        self.drag_calls.append((x, y, to_x, to_y, duration_ms))
        return Result.success()


class AuthorityDriver:
    def __init__(self, foreground_names: list[str] | None = None) -> None:
        self.foreground_names = foreground_names or ["notepad.exe"]
        self.action_calls: list[str] = []

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
        self.action_calls.append("activate_window")
        return Result.success()

    def click(self, _x: int, _y: int, button: str = "left") -> Result:
        self.action_calls.append(f"click:{button}")
        return Result.success()

    def scroll(self, _x: int, _y: int, _delta_x: int, _delta_y: int) -> Result:
        self.action_calls.append("scroll")
        return Result.success()

    def drag(
        self,
        _x: int,
        _y: int,
        _to_x: int,
        _to_y: int,
        _duration_ms: int,
    ) -> Result:
        self.action_calls.append("drag")
        return Result.success()

    def type(self, _text: str) -> Result:
        self.action_calls.append("type")
        return Result.success()

    def key(self, _combo: str) -> Result:
        self.action_calls.append("key")
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
        self.action_calls.append("invoke")
        return Result.success()


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
        (10.0, "notepad.exe", False, True, "ok", 1, "safe_local"),
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

    tool_text(asyncio.run(server.call_tool("type", {"text": SECRET, "ref": None})))
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


def test_activate_window_keeps_its_foreground_gate_exception(tmp_path: Path) -> None:
    driver = AuthorityDriver(["calc.exe"])
    server = build_server(
        allowlist=["notepad.exe"],
        driver=driver,
        start_estop=False,
        audit_path=str(tmp_path / "actions.jsonl"),
    )

    result = tool_text(
        asyncio.run(server.call_tool("activate_window", {"window_id": "window-1"}))
    )

    assert result == "ok"
    assert driver.action_calls == ["activate_window"]


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
