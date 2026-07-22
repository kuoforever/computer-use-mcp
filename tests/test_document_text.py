from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from computer_use_mcp.contract import (
    DocumentTextBlock,
    DocumentTextResult,
    DriverError,
    PruneOpts,
    Rect,
)
from computer_use_mcp.document_text import (
    MAX_DOCUMENT_BLOCKS,
    MAX_DOCUMENT_CHARS,
    DocumentTextError,
    serialize_document_text,
)
from computer_use_mcp.server import build_server


def _tool_text(result: object) -> str:
    content = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(item, "text", "") for item in content)


def test_envelope_reports_blocks_and_digests_the_kept_text() -> None:
    result = DocumentTextResult(
        blocks=[
            DocumentTextBlock("Job title", Rect(1, 2, 3, 4), 0),
            DocumentTextBlock("Description body", None, 1),
        ],
        truncated_blocks=0,
        source="uia_text_pattern",
        complete=True,
    )

    payload = json.loads(serialize_document_text(result, "foreground"))

    assert payload["source"] == "document_text"
    assert payload["scope"] == "foreground"
    assert payload["semantic_source"] == "uia_text_pattern"
    assert payload["complete"] is True
    assert payload["truncated"] is False
    assert payload["omitted_blocks"] == 0
    assert payload["blocks"][0]["bbox"] == [1, 2, 3, 4]
    assert payload["blocks"][1]["bbox"] is None
    assert payload["content_digest"] == hashlib.sha256(
        "Job title\nDescription body".encode("utf-8")
    ).hexdigest()


def test_block_cap_truncates_and_marks_incomplete() -> None:
    blocks = [DocumentTextBlock(f"b{index}", None, index) for index in range(MAX_DOCUMENT_BLOCKS + 5)]
    result = DocumentTextResult(blocks=blocks, truncated_blocks=0, source="uia_text_pattern", complete=True)

    payload = json.loads(serialize_document_text(result, "foreground"))

    assert len(payload["blocks"]) == MAX_DOCUMENT_BLOCKS
    assert payload["omitted_blocks"] == 5
    assert payload["truncated"] is True
    assert payload["complete"] is False


def test_char_cap_stops_before_exceeding_the_limit() -> None:
    big = "x" * (MAX_DOCUMENT_CHARS - 2)
    result = DocumentTextResult(
        blocks=[DocumentTextBlock(big, None, 0), DocumentTextBlock("yyy", None, 1)],
        truncated_blocks=0,
        source="uia_text_pattern",
        complete=True,
    )

    payload = json.loads(serialize_document_text(result, "foreground"))

    assert [block["text"] for block in payload["blocks"]] == [big]
    assert payload["omitted_blocks"] == 1
    assert payload["truncated"] is True


def test_driver_side_truncation_carries_into_the_envelope() -> None:
    result = DocumentTextResult(
        blocks=[DocumentTextBlock("kept", None, 0)],
        truncated_blocks=3,
        source="uia_text_pattern",
        complete=False,
    )

    payload = json.loads(serialize_document_text(result, "window:7"))

    assert payload["omitted_blocks"] == 3
    assert payload["truncated"] is True
    assert payload["complete"] is False


def test_serialize_rejects_a_non_result() -> None:
    with pytest.raises(DocumentTextError):
        serialize_document_text({"blocks": []}, "foreground")  # type: ignore[arg-type]


class _DocDriver:
    """A driver stub that only implements the document-text seam."""

    def __init__(self, result: DocumentTextResult) -> None:
        self.result = result
        self.scope: str | None = None

    def get_document_text(self, opts: PruneOpts) -> DocumentTextResult:
        self.scope = opts.scope
        return self.result


class _UnsupportedDriver:
    def get_document_text(self, opts: PruneOpts) -> DocumentTextResult:
        raise DriverError("DRIVER_ERROR", "document text is not supported by this backend")


def test_server_document_text_serializes_the_driver_result(tmp_path) -> None:
    driver = _DocDriver(
        DocumentTextResult(
            blocks=[DocumentTextBlock("Interested jobs", Rect(0, 0, 10, 2), 0)],
            truncated_blocks=0,
            source="uia_text_pattern",
            complete=True,
        )
    )
    server = build_server(
        driver=driver,
        start_estop=False,
        redact_titles=[],
        audit_path=tmp_path / "audit.jsonl",
    )

    result = asyncio.run(server.call_tool("document_text", {"scope": "window:42"}))
    payload = json.loads(_tool_text(result))

    assert driver.scope == "window:42"
    assert payload["blocks"][0]["text"] == "Interested jobs"


def test_server_document_text_fails_closed_on_an_unsupported_backend(tmp_path) -> None:
    server = build_server(
        driver=_UnsupportedDriver(),
        start_estop=False,
        redact_titles=[],
        audit_path=tmp_path / "audit.jsonl",
    )

    result = asyncio.run(server.call_tool("document_text", {}))

    assert _tool_text(result).startswith("ERROR DRIVER_ERROR")
