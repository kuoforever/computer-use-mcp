"""Bounded serialization for the document-text observation source.

Document text is the ladder rung between the interactive UIA snapshot and OCR:
it returns text an application or browser exposes through a real semantic
channel, not a dump of the accessibility tree or hidden state. The driver
produces the blocks; this module bounds them and projects the fixed envelope,
so the char/block caps and truncation accounting are testable without a desktop.
"""
from __future__ import annotations

import hashlib
import json

from .contract import DocumentTextResult, Rect

MAX_DOCUMENT_BLOCKS = 200
MAX_DOCUMENT_CHARS = 20_000


class DocumentTextError(RuntimeError):
    """A stable document-text failure safe to return through the tool boundary."""


def _bbox(rect: Rect | None) -> list[int] | None:
    if rect is None:
        return None
    return [rect.x, rect.y, rect.w, rect.h]


def serialize_document_text(result: DocumentTextResult, scope: str) -> str:
    """Return the observation envelope for one bounded document-text result.

    The block and character caps are applied here, and the content digest
    covers exactly the text the caller receives so a truncated payload cannot
    masquerade as the whole document.
    """

    if not isinstance(result, DocumentTextResult):
        raise DocumentTextError("DOCUMENT_TEXT_INVALID: result must be a DocumentTextResult")

    blocks: list[dict[str, object]] = []
    kept_text: list[str] = []
    chars = 0
    omitted = result.truncated_blocks
    for index, block in enumerate(result.blocks):
        if len(blocks) >= MAX_DOCUMENT_BLOCKS or chars + len(block.text) > MAX_DOCUMENT_CHARS:
            omitted += len(result.blocks) - index
            break
        chars += len(block.text)
        kept_text.append(block.text)
        blocks.append(
            {
                "order": block.order,
                "text": block.text,
                "bbox": _bbox(block.bbox),
            }
        )

    digest = hashlib.sha256("\n".join(kept_text).encode("utf-8")).hexdigest()
    complete = result.complete and omitted == 0
    payload = {
        "source": "document_text",
        "scope": scope,
        "coordinate_space": "primary_display_physical_pixels",
        "semantic_source": result.source,
        "complete": complete,
        "truncated": not complete,
        "omitted_blocks": omitted,
        "content_digest": digest,
        "blocks": blocks,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
