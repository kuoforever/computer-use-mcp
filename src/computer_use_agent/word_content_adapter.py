"""Private content binding for the opt-in Word probe; never dispatches actions."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import time
from xml.etree import ElementTree
import zipfile

from .content_handoff import (
    ContentHandoffError, ContentProfile, HostContentContext, bind_content_task,
    safe_content_receipt, text_digest, verify_content_results,
)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_DOCX_BYTES = 8 * 1024 * 1024


def document_snapshot(document: Path) -> tuple[str, str]:
    """Bind a bounded byte snapshot to exact supported main-body paragraph text.

    Tables, fields, tracked changes, drawings, tabs and breaks are unsupported.
    No claim about rich formatting, headers, atomic capture or visible UI is made.
    """
    try:
        with document.open("rb") as stream:
            raw = stream.read(MAX_DOCX_BYTES + 1)
        if len(raw) > MAX_DOCX_BYTES:
            raise ContentHandoffError("WORD_PACKAGE_SIZE")
        with zipfile.ZipFile(BytesIO(raw)) as package:
            if package.namelist().count("word/document.xml") != 1:
                raise ContentHandoffError("WORD_PACKAGE")
            info = package.getinfo("word/document.xml")
            if info.file_size > 1024 * 1024:
                raise ContentHandoffError("WORD_XML_SIZE")
            with package.open(info) as member:
                xml = member.read(1024 * 1024 + 1)
            if len(xml) > 1024 * 1024:
                raise ContentHandoffError("WORD_XML_SIZE")
        # Restrict this plain-text profile to UTF-8 XML; also reject entity/DTD
        # syntax before parsing, including unsupported UTF-16 with embedded NULs.
        decoded = xml.decode("utf-8")
        if "<!DOCTYPE" in decoded or "<!ENTITY" in decoded or "\x00" in decoded:
            raise ContentHandoffError("WORD_XML")
        root = ElementTree.fromstring(xml)
        body = root.find(W + "body")
        if root.tag != W + "document" or body is None or any(node.tag not in {W + "p", W + "sectPr"} for node in body):
            raise ContentHandoffError("WORD_BODY")
        forbidden = {W + name for name in ("tab", "br", "cr", "drawing", "pict", "object",
                                           "fldChar", "instrText", "fldSimple", "ins", "del", "tbl")}
        if any(node.tag in forbidden for node in body.iter()):
            raise ContentHandoffError("WORD_UNSUPPORTED")
        text = "\n".join("".join(node.text or "" for node in p.iter(W + "t"))
                         for p in body if p.tag == W + "p")
        if len(text.encode("utf-8")) > 32768 or any(ord(c) < 32 and c != "\n" for c in text):
            raise ContentHandoffError("WORD_BODY")
        return hashlib.sha256(raw).hexdigest(), text
    except ContentHandoffError:
        raise
    except (OSError, KeyError, ValueError, ElementTree.ParseError, zipfile.BadZipFile, RuntimeError):
        raise ContentHandoffError("WORD_PACKAGE") from None


class WordContentAdapter:
    """Process-local one-use state; not durable deduplication or an approval port.

    Construction requires trusted Host review. A failed/unknown main attempt is
    consumed; recovery is deliberately unavailable. No raw payload is exposed in
    the safe receipt. Save and read-only reopen are separately consumed phases.
    """

    def __init__(self, raw: bytes, *, profile: ContentProfile,
                 host: HostContentContext, document: Path):
        self.task = bind_content_task(raw, profile=profile, host=host)
        self.document = document.resolve(strict=True)
        if self.document.suffix.lower() != ".docx" or "\t" in self.task.content:
            raise ContentHandoffError("WORD_PROFILE")
        self.initial_artifact_sha, initial = document_snapshot(self.document)
        if text_digest(initial) != self.task.initial_text_sha256:
            raise ContentHandoffError("WORD_INITIAL")
        self.initial = initial
        self.expected = initial + self.task.content
        self.phase = "new"
        self.saved_artifact_sha: str | None = None
        self.readback: str | None = None

    def begin(self, document: Path, *, reopen: bool, save_only: bool) -> str:
        required = "saved" if reopen else "new"
        if self.phase != required:
            raise ContentHandoffError("WORD_ATTEMPT_CONSUMED")
        self.phase = "reopening" if reopen else "writing"
        if save_only or document.resolve(strict=True) != self.document:
            raise ContentHandoffError("WORD_TARGET")
        digest, body = document_snapshot(self.document)
        expected_digest = self.saved_artifact_sha if reopen else self.initial_artifact_sha
        if digest != expected_digest or body != (self.expected if reopen else self.initial):
            raise ContentHandoffError("WORD_ARTIFACT_CHANGED")
        return self.expected if reopen else self.initial

    def revalidate_initial(self) -> None:
        if self.phase != "writing":
            raise ContentHandoffError("WORD_PHASE")
        digest, body = document_snapshot(self.document)
        if digest != self.initial_artifact_sha or body != self.initial:
            raise ContentHandoffError("WORD_ARTIFACT_CHANGED")

    def record_readback(self, body: str) -> None:
        if self.phase != "writing" or body != self.expected:
            raise ContentHandoffError("WORD_READBACK")
        self.readback = body

    def record_saved(self, body: str) -> str:
        if self.phase != "writing" or self.readback is None or body != self.expected:
            raise ContentHandoffError("WORD_SAVE")
        digest, disk = document_snapshot(self.document)
        if disk != self.expected:
            raise ContentHandoffError("WORD_SAVE")
        self.saved_artifact_sha = digest
        self.phase = "saved"
        return digest

    def record_reopened(self, body: str) -> str:
        if self.phase != "reopening" or self.readback is None:
            raise ContentHandoffError("WORD_REOPEN")
        digest, disk = document_snapshot(self.document)
        if digest != self.saved_artifact_sha or disk != self.expected:
            raise ContentHandoffError("WORD_ARTIFACT_CHANGED")
        verify_content_results(self.task, target_id=self.task.target_id,
                               observations={"readback": self.readback, "saved": disk, "reopened": body})
        self.phase = "complete"
        return digest

    def wait_saved(self, body: str) -> str:
        """At most 51 bounded file reads; never repeats a GUI save or write."""
        if self.phase != "writing" or self.readback is None or body != self.expected:
            raise ContentHandoffError("WORD_SAVE")
        for attempt in range(51):
            try:
                return self.record_saved(body)
            except ContentHandoffError as exc:
                if str(exc) not in {"WORD_SAVE", "WORD_PACKAGE"} or attempt == 50:
                    raise
                time.sleep(0.1)
        raise ContentHandoffError("WORD_SAVE")  # Defensive, loop always returns/raises.

    def receipt(self) -> dict[str, object]:
        return dict(safe_content_receipt(self.task), adapter_phase=self.phase,
                    initial_artifact_sha256=self.initial_artifact_sha,
                    saved_artifact_sha256=self.saved_artifact_sha,
                    complete_content_verified=self.phase == "complete")
