from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from computer_use_mcp.audit import AuditLog
from computer_use_mcp.contract import ProcRef, Result
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
