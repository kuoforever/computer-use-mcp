from __future__ import annotations

import io
import json

from PIL import Image

from computer_use_mcp.audit import AuditLog
from computer_use_mcp.safety import is_dangerous, parse_combo, redact


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


def test_audit_log_writes_jsonl_and_truncates_long_strings(tmp_path) -> None:
    audit = AuditLog(tmp_path / "nested" / "actions.jsonl")

    record = audit.record("type", {"text": "x" * 121}, "ok", "done")
    saved = json.loads(audit.path.read_text(encoding="utf-8"))

    assert record == saved
    assert saved["args"]["text"] == "x" * 120 + "…"
    assert saved["decision"] == "ok"
