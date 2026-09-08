import json
from pathlib import Path
import zipfile

import pytest

from computer_use_agent.content_handoff import (
    ContentHandoffError, ContentProfile, HostContentContext, candidate_digest, text_digest,
)
from computer_use_agent.word_content_adapter import WordContentAdapter, document_snapshot

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def package(path, body="<w:p><w:r><w:t>Initial</w:t></w:r></w:p>", *, raw=None):
    xml = raw or f'<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>'.encode()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", xml)


def adapter_for(path: Path, content="\nReviewed content"):
    _, initial = document_snapshot(path)
    source = text_digest("Synthetic source")
    candidate = dict(version=1, task_id="test", profile_id="word-v1", operation="append_text",
                     sources=[dict(source_id="source", content_sha256=source)],
                     target=dict(target_id="document", initial_text_sha256=text_digest(initial)),
                     content=dict(text=content, sha256=text_digest(content)),
                     acceptance=dict(expected_text_sha256=text_digest(initial + content),
                                     checks=["readback", "saved", "reopened"]))
    raw = json.dumps(candidate).encode()
    return WordContentAdapter(raw, document=path, profile=ContentProfile("word-v1", 900, 16000),
                               host=HostContentContext("test", "document", {"source": source},
                                                       initial, candidate_digest(raw)))


@pytest.mark.parametrize("body", ["<w:tbl/>", "<w:altChunk/>",
    "<w:p><w:r><w:tab/></w:r></w:p>", "<w:p><w:r><w:br/></w:r></w:p>",
    "<w:p><w:ins/></w:p>", "<w:p><w:del/></w:p>",
    "<w:p><w:r><w:instrText>hidden</w:instrText></w:r></w:p>",
    "<w:p><w:r><w:drawing/></w:r></w:p>"])
def test_unsupported_document_semantics_are_not_silently_dropped(tmp_path, body):
    document = tmp_path / "test.docx"
    package(document, body)
    with pytest.raises(ContentHandoffError):
        document_snapshot(document)


@pytest.mark.parametrize("kind", ["invalid_zip", "missing_xml", "duplicate_xml", "large_xml", "dtd", "utf16"])
def test_package_bounds_and_parser_fail_closed(tmp_path, kind):
    document = tmp_path / "test.docx"
    if kind == "invalid_zip":
        document.write_bytes(b"private invalid package")
    elif kind == "missing_xml":
        with zipfile.ZipFile(document, "w") as archive:
            archive.writestr("other.xml", "private")
    elif kind == "large_xml":
        package(document, raw=b"x" * (1024 * 1024 + 1))
    elif kind == "duplicate_xml":
        package(document)
        with zipfile.ZipFile(document, "a") as archive, pytest.warns(UserWarning):
            archive.writestr("word/document.xml", "private")
    else:
        xml = f'<!DOCTYPE x [<!ENTITY x "private">]><w:document xmlns:w="{NS}"><w:body/></w:document>'
        package(document, raw=xml.encode("utf-16") if kind == "utf16" else xml.encode())
    with pytest.raises(ContentHandoffError) as error:
        document_snapshot(document)
    assert "private" not in str(error.value)


def test_snapshot_binds_exact_whitespace_and_empty_paragraphs(tmp_path):
    document = tmp_path / "test.docx"
    package(document, '<w:p><w:r><w:t> A  B </w:t></w:r></w:p><w:p/><w:p><w:r><w:t>C</w:t></w:r></w:p>')
    _, text = document_snapshot(document)
    assert text == " A  B \n\nC"


def test_adapter_rejects_tabs_and_save_recovery(tmp_path):
    document = tmp_path / "test.docx"
    package(document)
    with pytest.raises(ContentHandoffError, match="WORD_PROFILE"):
        adapter_for(document, "\nA\tB")
    adapter = adapter_for(document)
    with pytest.raises(ContentHandoffError, match="WORD_TARGET"):
        adapter.begin(document, reopen=False, save_only=True)
    with pytest.raises(ContentHandoffError, match="WORD_ATTEMPT_CONSUMED"):
        adapter.begin(document, reopen=False, save_only=False)


def test_no_reopen_before_save_or_save_before_verified_readback(tmp_path):
    document = tmp_path / "test.docx"
    package(document)
    adapter = adapter_for(document)
    with pytest.raises(ContentHandoffError, match="WORD_ATTEMPT_CONSUMED"):
        adapter.begin(document, reopen=True, save_only=False)
    adapter.begin(document, reopen=False, save_only=False)
    with pytest.raises(ContentHandoffError, match="WORD_SAVE"):
        adapter.record_saved(adapter.expected)
    adapter.record_readback(adapter.expected)
    with pytest.raises(ContentHandoffError, match="WORD_SAVE"):
        adapter.record_saved(adapter.expected)  # Disk still has the initial body.


def test_host_target_path_and_initial_artifact_cannot_drift(tmp_path):
    document = tmp_path / "test.docx"
    other = tmp_path / "other.docx"
    package(document)
    package(other)
    adapter = adapter_for(document)
    with pytest.raises(ContentHandoffError, match="WORD_TARGET"):
        adapter.begin(other, reopen=False, save_only=False)
    adapter = adapter_for(document)
    package(document, '<w:p><w:r><w:t>Other body</w:t></w:r></w:p>')
    with pytest.raises(ContentHandoffError, match="WORD_ARTIFACT_CHANGED"):
        adapter.begin(document, reopen=False, save_only=False)


def test_durability_wait_only_retries_bounded_file_observations(tmp_path, monkeypatch):
    document = tmp_path / "test.docx"
    package(document)
    adapter = adapter_for(document)
    adapter.begin(document, reopen=False, save_only=False)
    adapter.record_readback(adapter.expected)
    waits = []
    monkeypatch.setattr("computer_use_agent.word_content_adapter.time.sleep", waits.append)
    with pytest.raises(ContentHandoffError, match="WORD_SAVE"):
        adapter.wait_saved(adapter.expected)
    assert waits == [0.1] * 50
    assert adapter.phase == "writing"  # No action or synthesized save evidence.
    package(document, '<w:p><w:r><w:t>Initial</w:t></w:r></w:p>'
                      '<w:p><w:r><w:t>Reviewed content</w:t></w:r></w:p>')
    assert adapter.wait_saved(adapter.expected) == document_snapshot(document)[0]
    assert adapter.phase == "saved"
