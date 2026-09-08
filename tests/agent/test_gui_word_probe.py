import asyncio
import base64
from dataclasses import replace
from fractions import Fraction
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from xml.etree import ElementTree
import zipfile

import pytest

from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import ToolResult, ToolResultStatus, DispatchCertainty, ImageContent
from computer_use_mcp import SUPPORTED_SAFETY_BASELINES
from computer_use_agent.content_handoff import ContentProfile, HostContentContext, candidate_digest, text_digest
from computer_use_agent.word_content_adapter import WordContentAdapter

ROOT = Path(__file__).resolve().parents[2]
P = runpy.run_path(str(ROOT / "scripts/probe_gui_word.py"))
H = runpy.run_path(str(Path(__file__).with_name("test_gui_host_source.py")))
W = runpy.run_path(str(Path(__file__).with_name("test_public_web_word.py")))


def append_exact(document, note):
    """Synthetic DOCX writer for tests; production continues to use the Runner."""
    text = P["_document_text"](document) + note
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(document) as package:
        entries = [(i, package.read(i.filename)) for i in package.infolist()]
    root = ElementTree.fromstring(next(raw for i, raw in entries if i.filename == "word/document.xml"))
    body = root.find(namespace + "body")
    for child in list(body):
        if child.tag != namespace + "sectPr":
            body.remove(child)
    for index, line in enumerate(text.split("\n")):
        p = ElementTree.Element(namespace + "p")
        r = ElementTree.SubElement(p, namespace + "r")
        ElementTree.SubElement(r, namespace + "t").text = line
        body.insert(index, p)
    with zipfile.ZipFile(document, "w") as package:
        for info, raw in entries:
            package.writestr(info, ElementTree.tostring(root) if info.filename == "word/document.xml" else raw)


def make_adapter(document, content):
    initial = P["_document_text"](document)
    c = dict(version=1, task_id="word-content-test", profile_id="word-summary-v1", operation="append_text",
             sources=[dict(source_id="synthetic", content_sha256=text_digest("Synthetic source"))],
             target=dict(target_id="test-document", initial_text_sha256=text_digest(initial)),
             content=dict(text=content, sha256=text_digest(content)),
             acceptance=dict(expected_text_sha256=text_digest(initial + content),
                             checks=["readback", "saved", "reopened"]))
    raw = json.dumps(c).encode()
    host = HostContentContext("word-content-test", "test-document",
                              {"synthetic": text_digest("Synthetic source")}, initial, candidate_digest(raw))
    return WordContentAdapter(raw, profile=ContentProfile("word-summary-v1", 900, 16000),
                              host=host, document=document)


def execute(tmp_path, monkeypatch, fault="", *, content_case=False, adapter=None, existing_document=None):
    host, desktop, driver, sessions = H["setup"](tmp_path, monkeypatch)
    # This transport fake deliberately has no native baseline attestation.
    # Simulate the real server's advertised baselines for this Host-boundary test.
    if fault != "baseline":
        monkeypatch.setattr(type(desktop), "satisfied_safety_baselines",
                            property(lambda self: SUPPORTED_SAFETY_BASELINES))
    config = replace(P["config_for"](), state_dir=host.config.state_dir, mcp=host.config.mcp)
    if fault == "budget":
        config = replace(config, policy=replace(config.policy, max_side_effects=0))
    if fault == "policy":
        config = replace(config, policy=replace(config.policy, mode="read_only"))
    permit = P["WordPermit"]()
    runner = AgentRunner(config, RunnerPorts(host.ports.provider, desktop, permit))
    document = existing_document or tmp_path / "gui-word-test.docx"
    if existing_document is None:
        document.write_bytes(P["_packaged_template_bytes"]())
    if fault.startswith("reopen") and not content_case:
        W["_append_note"](document, P["NOTE"])
    note = "\nReviewed synthetic content.\nSecond line stays exact." if content_case else P["NOTE"]
    if content_case and adapter is None:
        adapter = make_adapter(document, note)
    original = P["_document_text"](document)
    state = dict(actions=[], model=0, tick=7,
                 pending=P["NOTE"] if fault in {"save_only", "save_only_bad"} else "", snapshots=0)
    state["adapter"] = adapter

    async def call(c):
        text, images = "", ()
        if c.name == "list_windows":
            star = " " if fault == "foreground" and state["model"] else "*"
            text = f'{star} 314 | winword.exe | "{document.name} - Word"'
        elif c.name == "ui_snapshot":
            state["snapshots"] += 1
            focused = ",focused" if (state["actions"] or fault.startswith("save_only")) and fault != "focus" else ""
            left = 101 if fault == "layout" and state["model"] else 100
            text = (f'ref_1 | document "{document.name}" | (0,0,1000,800) | enabled{focused}\n'
                    f'ref_2 | edit "Page 1 content" | ({left},100,800,600) | enabled')
        elif c.name == "document_text":
            body = original + state["pending"]
            if fault == "content" and state["model"]:
                body += " unexpected"
            if fault == "write" and state["pending"]:
                body = original
            if fault == "whitespace" and state["pending"]:
                body = body.replace("\n", " ")
            if fault == "save_only_bad":
                body += "wrong"
            if fault == "reopen_bad":
                body = "wrong document"
            text = json.dumps(dict(source="document_text", scope="314", complete=True,
                truncated=False, omitted_blocks=0, semantic_source="uia_text_pattern",
                coordinate_space="primary_display_physical_pixels", blocks=[
                    dict(order=0, text="Calibri", bbox=[10, -50, 60, 20]),
                    dict(order=1, text=body, bbox=[0, 0, 1000, 800])]))
        elif c.name == "screenshot":
            images = (ImageContent("image/png", W["_png"](1000, 800), 1000, 800),)
        else:
            record = read_run_record(config.state_dir, c.identity.run_id)["state"]
            assert record["phase"] == "EXECUTING"
            assert record["budgets"]["side_effects_used"] == len(state["actions"]) + 1
            assert permit.armed is None
            state["actions"].append((c.name, dict(c.arguments)))
            if fault == "unknown":
                return ToolResult(c.identity, c.name, ToolResultStatus.UNKNOWN_OUTCOME,
                                  DispatchCertainty.UNKNOWN, code="UNKNOWN_OUTCOME")
            if c.name == "type":
                state["pending"] = c.arguments["text"]
            if c.name == "key" and c.arguments == {"combo": "Ctrl+S"}:
                if fault != "no_save":
                    (append_exact if content_case else W["_append_note"])(document, state["pending"])
            state["tick"] += 1  # Legitimate injected OS input.
        return ToolResult(c.identity, c.name, ToolResultStatus.SUCCESS,
                          DispatchCertainty.DISPATCHED, sanitized_text=text, images=images)

    desktop.call_tool = call
    api = SimpleNamespace(parse=lambda raw: (Fraction(0), Fraction(0)) if fault == "point"
                          else (Fraction(500), Fraction(500)))

    def worker(api, request):
        state["model"] += 1
        if fault == "disk_drift":
            append_exact(document, "Unexpected disk change")
        if fault == "input":
            state["tick"] += 1
        return dict(version=1, status="OK", request_id=request["request_id"],
                    context_digest="0" * 64 if fault == "binding" else request["context_digest"],
                    raw_output="private model response", model_requests=1,
                    model_id=P["INERT"]["MODEL"], revision=P["INERT"]["REVISION"],
                    adapter_sha256=P["INERT"]["ADAPTER"],
                    image_sha256=P["sha"](base64.b64decode(request["image_base64"])),
                    input_tokens=100, output_tokens=20, generation_seconds=2., peak_allocated_bytes=1000)

    result = asyncio.run(P["probe"]("314", document, api, runner=runner,
                                    tick=lambda: state["tick"], worker=worker,
                                    save_only=fault.startswith("save_only"), reopen=fault.startswith("reopen"),
                                    content_adapter=adapter))
    assert len(sessions) == 1 and desktop.closed and not runner.ports.provider.calls
    assert "private" not in str(result)
    return result, state, document


def test_reviewed_content_save_and_separate_reopen_use_existing_runner(tmp_path, monkeypatch):
    result, state, document = execute(tmp_path, monkeypatch, content_case=True)
    adapter = state["adapter"]
    assert result["outcome"] == "PASS", result
    assert state["actions"][2] == ("type", {"text": adapter.task.content})
    assert result["approval_requests"] == result["side_effects"] == 4
    assert result["tool_calls"] == 22
    assert adapter.phase == "saved"
    assert not result["content_handoff"]["complete_content_verified"]
    assert adapter.task.content not in json.dumps(result)
    reopened, reads, _ = execute(tmp_path, monkeypatch, "reopen", content_case=True,
                                  adapter=adapter, existing_document=document)
    assert reopened["outcome"] == "PASS", reopened
    assert reopened["content_handoff"]["complete_content_verified"]
    assert reopened["artifact_sha256"] == result["artifact_sha256"]
    assert reads["model"] == 0 and not reads["actions"]
    assert reopened["tool_calls"] == 2
    with pytest.raises(ValueError, match="WORD_ATTEMPT_CONSUMED"):
        adapter.begin(document, reopen=True, save_only=False)


@pytest.mark.parametrize("fault,count", [("disk_drift", 0), ("content", 0), ("policy", 0),
                                         ("budget", 0), ("unknown", 1), ("whitespace", 3), ("write", 3)])
def test_reviewed_content_failures_never_retry_or_save_bad_text(tmp_path, monkeypatch, fault, count):
    result, state, document = execute(tmp_path, monkeypatch, fault, content_case=True)
    assert result["outcome"] != "PASS"
    assert len(state["actions"]) == count
    assert state["adapter"].phase == "failed"
    with pytest.raises(ValueError, match="WORD_ATTEMPT_CONSUMED"):
        state["adapter"].begin(document, reopen=False, save_only=False)


def test_reviewed_reopen_requires_the_exact_saved_artifact(tmp_path, monkeypatch):
    _, state, document = execute(tmp_path, monkeypatch, content_case=True)
    adapter = state["adapter"]
    # Even equal text with different package bytes invalidates the saved receipt.
    with zipfile.ZipFile(document, "a") as package:
        package.writestr("extra.txt", "changed")
    with pytest.raises(ValueError, match="WORD_ARTIFACT_CHANGED"):
        adapter.begin(document, reopen=True, save_only=False)
    assert adapter.phase == "reopening"
    with pytest.raises(ValueError, match="WORD_ATTEMPT_CONSUMED"):
        adapter.begin(document, reopen=True, save_only=False)


def test_word_sequence_uses_host_wal_approval_and_durable_readback(tmp_path, monkeypatch):
    result, state, document = execute(tmp_path, monkeypatch)
    assert result["outcome"] == "PASS", result
    assert state["model"] == result["model_requests"] == 1
    assert state["actions"] == [("click", {"x": 500, "y": 400}),
        ("key", {"combo": "Ctrl+End"}), ("type", {"text": P["NOTE"]}), ("key", {"combo": "Ctrl+S"})]
    assert result["approval_requests"] == result["side_effects"] == 4
    assert result["tool_calls"] == 21 and result["host_model_turns"] == 0
    assert result["artifact_sha256"] == P["sha"](document.read_bytes())


@pytest.mark.parametrize("fault", ["save_only", "save_only_bad"])
def test_save_recovery_reobserves_exact_body_without_model_or_typing(tmp_path, monkeypatch, fault):
    result, state, _ = execute(tmp_path, monkeypatch, fault)
    assert state["model"] == 0
    assert result["model_requests"] == 0
    if fault == "save_only":
        assert result["outcome"] == "PASS", result
        assert state["actions"] == [("key", {"combo": "Ctrl+S"})]
    else:
        assert result["outcome"] != "PASS" and not state["actions"]


@pytest.mark.parametrize("fault", ["reopen", "reopen_bad"])
def test_reopen_uses_read_only_exact_file_body_comparison(tmp_path, monkeypatch, fault):
    result, state, _ = execute(tmp_path, monkeypatch, fault)
    assert not state["actions"] and state["model"] == 0
    assert result["tool_calls"] == 2 and result["side_effects"] == 0
    assert (result["outcome"] == "PASS") == (fault == "reopen")


@pytest.mark.parametrize("fault", ["foreground", "layout", "content", "point", "input", "binding", "policy", "budget"])
def test_invalid_proposal_or_context_never_dispatches(tmp_path, monkeypatch, fault):
    result, state, _ = execute(tmp_path, monkeypatch, fault)
    assert result["outcome"] != "PASS" and not state["actions"], result
    assert state["model"] == 1
    if fault == "input":
        assert result["outcome"] == "INVALID"


@pytest.mark.parametrize("fault,count", [("focus", 1), ("write", 3), ("unknown", 1), ("baseline", 2)])
def test_post_action_failure_never_replays_or_saves_unverified_text(tmp_path, monkeypatch, fault, count):
    result, state, _ = execute(tmp_path, monkeypatch, fault)
    assert result["outcome"] != "PASS" and len(state["actions"]) == count
    assert state["model"] == 1
    if fault == "unknown":
        assert result["phase"] == result["outcome"] == "UNKNOWN_OUTCOME"


@pytest.mark.parametrize("text", ["", 'ref_1 | edit "Search" | (0,0,500,500) | enabled',
    'ref_1 | edit "Page 1 content" | (0,0,500,500) | enabled,offscreen',
    'ref_1 | edit "Page 1 content" | (0,0,500,500) | disabled',
    'ref_1 | edit "Page 1 content" | (0,0,500,500) | enabled\n'
    'ref_2 | edit "Page 2 content" | (0,0,500,500) | enabled'])
def test_ambiguous_or_unusable_editor_rejects(text):
    with pytest.raises(ValueError):
        P["editor_bounds"](text)


@pytest.mark.parametrize("changed", ["prefix", "duplicate", "missing"])
def test_full_text_verification_preserves_template_and_exactly_one_note(changed):
    text = "original" + P["NOTE"]
    text = {"prefix": "wrong" + text, "duplicate": text + P["NOTE"], "missing": P["NOTE"]}[changed]
    with pytest.raises(ValueError):
        P["verify_text"](text, "original")


@pytest.mark.parametrize("fault", ["scope", "incomplete", "missing_box", "overlap", "duplicate", "no_body"])
def test_body_selection_rejects_ambiguous_or_incomplete_text(fault):
    body = dict(order=1, text="body", bbox=[0, 100, 1000, 800])
    extra = dict(order=0, text="Calibri", bbox=[10, 20, 60, 20])
    value = dict(source="document_text", scope="314", complete=True, truncated=False,
                 omitted_blocks=0, semantic_source="uia_text_pattern",
                 coordinate_space="primary_display_physical_pixels", blocks=[extra, body])
    if fault == "scope":
        value["scope"] = "999"
    elif fault == "incomplete":
        value.update(complete=False, truncated=True, omitted_blocks=1)
    elif fault == "missing_box":
        extra["bbox"] = None
    elif fault == "overlap":
        extra["bbox"] = [0, 90, 60, 30]
    elif fault == "duplicate":
        value["blocks"].append(dict(body, order=2))
    else:
        value["blocks"] = [extra]
    with pytest.raises(ValueError):
        P["body_text"](json.dumps(value), "314", [0, 100, 1000, 800])
