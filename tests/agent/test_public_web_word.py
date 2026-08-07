from __future__ import annotations

import asyncio
import json
import struct
import zipfile
import zlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from xml.etree import ElementTree

import pytest

from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.disposable_process import ProcessWindowSnapshot
from computer_use_agent.public_web_word import (
    ModelDrivenPublicWebWordProvider,
    PUBLIC_WEB_WORD_MARKER,
    PUBLIC_WEB_WORD_SOURCE_TITLE,
    PUBLIC_WEB_WORD_SOURCE_URL,
    PublicWebWordError,
    PublicWebWordProposalRejection,
    _document_text_semantically_contains_required,
)
from computer_use_agent.public_web_word_runtime import (
    PublicWebWordRequest,
    run_public_web_word_workflow,
    verify_public_web_word_document,
)
from computer_use_agent.tool_registry import (
    REVIEWED_TOOLS,
    ToolSpec,
    reviewed_mcp_descriptors,
)
from computer_use_agent.types import (
    JSONValue,
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    LedgerEvent,
    MemoryContextItem,
    ModelTurn,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    ProviderContinuationStrategy,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from computer_use_mcp.contract import DocumentTextBlock, DocumentTextResult
from computer_use_mcp.document_text import serialize_document_text

RUN_ID = "public-web-word-test"
SOURCE_TEXT = (
    "Microsoft Word supports real-time co-authoring when documents are stored "
    "in OneDrive or SharePoint. Collaborators can see changes as they happen. "
    "Comments and mentions help teams review feedback and notify people. "
    "Track Changes provides review history for collaborative editing."
)
NOTE = (
    f"\n\n{PUBLIC_WEB_WORD_MARKER}\n"
    f"Source: {PUBLIC_WEB_WORD_SOURCE_TITLE}\n"
    f"URL: {PUBLIC_WEB_WORD_SOURCE_URL}\n"
    "• Real-time co-authoring lets collaborators see document changes while "
    "files are stored in OneDrive or SharePoint.\n"
    "• Comments and mentions help teams review feedback and notify people "
    "about requested follow-up.\n"
    "• Track Changes provides review history for collaborative editing decisions."
)


def _document_envelope(text: str, scope: str) -> str:
    blocks = [
        DocumentTextBlock(value, None, index)
        for index, value in enumerate(text.splitlines())
    ]
    return serialize_document_text(
        DocumentTextResult(blocks, 0, "uia_text_pattern", True),
        scope,
    )


def _png(width: int, height: int) -> bytes:
    def chunk(name: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + name
            + data
            + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + b"\x00\x00\x00" * width for _ in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(
        b"IDAT", zlib.compress(rows)
    ) + chunk(b"IEND", b"")


def _call(run_id: str, turn_id: str, name: str, arguments: Mapping[str, JSONValue]) -> ToolCall:
    return ToolCall(
        CallIdentity(run_id, turn_id, f"call_{turn_id.removeprefix('turn_')}"),
        name,
        arguments,
    )


@dataclass
class WorkflowModel:
    expected_word_title: str
    repeat_pre_save_observation: bool = False
    name: str = "functional-model"
    continuation_strategy: ProviderContinuationStrategy = (
        ProviderContinuationStrategy.STATELESS_REPLAY
    )
    step: int = 0

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence[ToolSpec],
        memories: Sequence[MemoryContextItem] = (),
    ) -> ModelTurn:
        if self.step == 0:
            assert json.dumps(self.expected_word_title) in task
        if self.step == 11:
            screenshot = next(
                event.tool_result
                for event in reversed(ledger)
                if event.tool_result is not None
                and event.tool_result.tool_name == "screenshot"
            )
            assert len(screenshot.images) == 1
            assert screenshot.images[0].width == 800
            assert screenshot.images[0].height == 600
            assert len(screenshot.images[0].data) < 64 * 1024
        del ledger, tools, memories
        repeated_pre_save: tuple[
            tuple[str, Mapping[str, JSONValue]], ...
        ] = (
            (("document_text", {"scope": "202"}),)
            if self.repeat_pre_save_observation
            else ()
        )
        sequence: tuple[tuple[str, Mapping[str, JSONValue]], ...] = (
            ("list_windows", {}),
            ("activate_window", {"window_id": "101"}),
            ("ui_snapshot", {"scope": "101"}),
            ("document_text", {"scope": "101"}),
            ("key", {"combo": "PageDown"}),
            ("ui_snapshot", {"scope": "101"}),
            ("document_text", {"scope": "101"}),
            ("list_windows", {}),
            ("activate_window", {"window_id": "202"}),
            ("ui_snapshot", {"scope": "202"}),
            ("screenshot", {}),
            ("click", {"x": 401, "y": 302}),
            ("ui_snapshot", {"scope": "202"}),
            ("key", {"combo": "Ctrl+End"}),
            ("ui_snapshot", {"scope": "202"}),
            ("type", {"text": NOTE}),
            ("document_text", {"scope": "202"}),
            *repeated_pre_save,
            ("key", {"combo": "Ctrl+S"}),
            ("document_text", {"scope": "202"}),
        )
        calls: tuple[ToolCall, ...]
        if self.step < len(sequence):
            name, arguments = sequence[self.step]
            calls = (_call(run_id, turn_id, name, arguments),)
            text = "untrusted provider prose"
        else:
            calls = ()
            text = "provider self-report"
        self.step += 1
        return ModelTurn(
            run_id,
            turn_id,
            f"response_{turn_id}",
            text,
            calls,
            ModelUsage(10, 2),
        )

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        del run_id
        return {}

    def restore_continuation(
        self,
        run_id: str,
        state: Mapping[str, JSONValue],
        *,
        tools: Sequence[ToolSpec],
    ) -> None:
        del run_id, state, tools


def _append_note(document: Path, note: str) -> None:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(document) as package:
        entries = [(item, package.read(item.filename)) for item in package.infolist()]
    document_xml = next(value for item, value in entries if item.filename == "word/document.xml")
    root = ElementTree.fromstring(document_xml)
    body = root.find(f"{{{namespace}}}body")
    assert body is not None
    section = body.find(f"{{{namespace}}}sectPr")
    insert_at = len(body) if section is None else list(body).index(section)
    for line in note.strip().splitlines():
        paragraph = ElementTree.Element(f"{{{namespace}}}p")
        run = ElementTree.SubElement(paragraph, f"{{{namespace}}}r")
        text = ElementTree.SubElement(run, f"{{{namespace}}}t")
        text.text = line
        body.insert(insert_at, paragraph)
        insert_at += 1
    replacement = ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
    temporary = document.with_suffix(".writing.docx")
    with zipfile.ZipFile(temporary, "w") as package:
        for item, value in entries:
            package.writestr(
                item,
                replacement if item.filename == "word/document.xml" else value,
            )
    temporary.replace(document)


@dataclass
class WorkflowDesktop:
    document: Path
    reopen: bool = False
    reopen_text_mismatches: int = 0
    generation: int = 1
    satisfied_safety_baselines: frozenset[str] = frozenset(
        {"title_matched_image_redaction", "typed_text_audit_redaction"}
    )
    tool_calls: list[ToolCall] = field(default_factory=list)
    close_calls: int = 0
    pending_note: str | None = None
    persisted: bool = False
    reopen_document_text_calls: int = 0

    async def discover_tools(self):
        return reviewed_mcp_descriptors()

    async def call_tool(self, call: ToolCall) -> ToolResult:
        self.tool_calls.append(call)
        if call.name == "list_windows":
            if self.reopen:
                text = f'* 303 | winword.exe | "{self.document.name} - Word"'
            else:
                text = (
                    f'* 101 | chrome.exe | "{PUBLIC_WEB_WORD_SOURCE_TITLE} - Google Chrome"\n'
                    f'  202 | winword.exe | "{self.document.name} - Word"'
                )
        elif call.name == "ui_snapshot" and call.arguments["scope"] == "101":
            text = (
                f'ref_1 | document "{PUBLIC_WEB_WORD_SOURCE_TITLE}" | '
                "(1,2,1200,800) | enabled"
            )
        elif call.name == "ui_snapshot":
            document_states = (
                "enabled,focused"
                if any(item.name == "click" for item in self.tool_calls)
                else "enabled"
            )
            text = (
                f'ref_5 | document "{self.document.name} [Compatibility Mode]" | '
                f'(0,0,1200,800) | {document_states}\n'
                'ref_6 | edit "Search" | (560,20,180,30) | enabled '
                '| value="Search"\n'
                'ref_7 | edit "Page 1 content" | (1,2,800,600) | enabled'
            )
        elif call.name == "document_text" and call.arguments["scope"] == "101":
            text = _document_envelope(SOURCE_TEXT, "101")
        elif call.name == "document_text":
            if self.reopen:
                self.reopen_document_text_calls += 1
            visible = (
                NOTE
                if (
                    self.reopen
                    and self.reopen_document_text_calls > self.reopen_text_mismatches
                )
                or self.pending_note is not None
                else ""
            )
            if self.reopen and visible:
                visible = visible.replace("\n", " ")
            text = _document_envelope(visible, str(call.arguments["scope"]))
        else:
            text = ""
        if call.name == "type":
            assert call.arguments["text"] == NOTE
            self.pending_note = NOTE
        if (
            call.name == "key"
            and call.arguments["combo"] == "Ctrl+S"
            and self.pending_note is not None
            and not self.persisted
        ):
            _append_note(self.document, self.pending_note)
            self.persisted = True
        images = (
            (ImageContent("image/png", _png(800, 600), 800, 600),)
            if call.name == "screenshot"
            else ()
        )
        return ToolResult(
            call.identity,
            call.name,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
            sanitized_text="" if call.name == "type" else text,
            images=images,
        )

    async def close(self) -> None:
        self.close_calls += 1


class AllowWorkflowActions:
    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        return PolicyDecision(
            request.request_id,
            request.identity,
            request.call_digest,
            PolicyDecisionKind.ALLOW,
            "functional_test",
        )


class Process:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.terminated = 0
        self.killed = 0

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1

    def wait(self, timeout: float) -> int:
        del timeout
        return 0


class Windows:
    def __init__(self) -> None:
        self.closed: set[int] = set()

    def snapshot(self, pid: int) -> ProcessWindowSnapshot:
        visible = 0 if pid in self.closed else 1
        return ProcessWindowSnapshot(
            visible,
            visible,
            0,
            () if not visible else (str(pid),),
        )

    def request_close(self, pid: int) -> int:
        self.closed.add(pid)
        return 1


def _config(tmp_path: Path, monkeypatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "public-web-word",
        policy_version="public-web-word-test-v1",
        provider=ProviderConfig("openai", "functional-model"),
        mcp=MCPLaunchConfig(
            executable=(tmp_path / "guarded-desktop-mcp.exe").resolve(),
            args=(),
            cwd=tmp_path.resolve(),
            environment={
                "CUMCP_ALLOWLIST": "chrome.exe,winword.exe",
                "CUMCP_HUMAN_MAX_WAIT_SECONDS": "15",
                "CUMCP_HUMAN_STABLE_SAMPLES": "3",
            },
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=28,
            max_tool_calls=24,
            max_side_effects=7,
        ),
    )


def test_runtime_rejects_a_hand_edited_product_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    config = replace(
        config,
        mcp=replace(
            config.mcp,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
    )
    output = (tmp_path / "must-not-exist.docx").resolve()

    with pytest.raises(
        PublicWebWordError,
        match="PUBLIC_WEB_WORD_ALLOWLIST_MUST_BE_FIXED",
    ):
        asyncio.run(
            run_public_web_word_workflow(
                config,
                PublicWebWordRequest(output),
                provider=WorkflowModel(output.name),
                approvals=AllowWorkflowActions(),
                run_id=RUN_ID,
            )
        )

    assert not output.exists()


def test_runtime_requires_the_approval_idle_settling_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    config = replace(
        config,
        mcp=replace(
            config.mcp,
            environment={"CUMCP_ALLOWLIST": "chrome.exe,winword.exe"},
        ),
    )
    output = (tmp_path / "must-not-exist.docx").resolve()

    with pytest.raises(
        PublicWebWordError,
        match="PUBLIC_WEB_WORD_HUMAN_IDLE_PROFILE_REQUIRED",
    ):
        asyncio.run(
            run_public_web_word_workflow(
                config,
                PublicWebWordRequest(output),
                provider=WorkflowModel(output.name),
                approvals=AllowWorkflowActions(),
                run_id=RUN_ID,
            )
        )

    assert not output.exists()


def test_installed_workflow_authors_saves_reopens_and_reports_bounded_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    output = (tmp_path / "result.docx").resolve()
    chrome = (tmp_path / "chrome.exe").resolve()
    word = (tmp_path / "winword.exe").resolve()
    chrome.write_bytes(b"fixture")
    word.write_bytes(b"fixture")
    original = WorkflowDesktop(output)
    reopened = WorkflowDesktop(output, reopen=True, reopen_text_mismatches=1)
    desktops = iter((original, reopened))
    processes = iter((Process(202), Process(101), Process(303)))
    windows = Windows()

    result = asyncio.run(
        run_public_web_word_workflow(
            config,
            PublicWebWordRequest(output, chrome, word),
            provider=WorkflowModel(
                output.name,
                repeat_pre_save_observation=True,
            ),
            desktop_factory=lambda _config: next(desktops),
            approvals=AllowWorkflowActions(),
            launcher=lambda _arguments: next(processes),
            windows=windows,
            sleep=lambda _seconds: None,
            run_id=RUN_ID,
        )
    )

    payload = result.as_json()
    serialized = json.dumps(payload, sort_keys=True)
    assert NOTE not in serialized
    assert result.tool_calls == 22
    assert result.side_effects == 7
    assert result.bullet_count == 3
    assert result.proposal_corrections == 1
    assert result.post_save_verified is True
    assert result.reopen_verified is True
    assert all(item.window_cleanup_verified for item in result.fixture_cleanup)
    assert all(item.window_cleanup_verified for item in result.verifier_cleanup)
    assert verify_public_web_word_document(output, NOTE) == result.artifact_sha256
    assert original.close_calls == reopened.close_calls == 1
    assert reopened.reopen_document_text_calls == 2
    from computer_use_agent.product_receipt import read_product_receipt

    receipt = read_product_receipt(config.state_dir, RUN_ID)
    assert receipt.artifact_path == output
    assert receipt.artifact_sha256 == result.artifact_sha256
    assert receipt.saved_verified is receipt.reopen_verified is True
    assert receipt.fixture_cleanup_verified is receipt.verifier_cleanup_verified is True


def test_reopen_verifier_fails_after_one_fresh_text_retry(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    output = (tmp_path / "result.docx").resolve()
    chrome = (tmp_path / "chrome.exe").resolve()
    word = (tmp_path / "winword.exe").resolve()
    chrome.write_bytes(b"fixture")
    word.write_bytes(b"fixture")
    original = WorkflowDesktop(output)
    reopened = WorkflowDesktop(output, reopen=True, reopen_text_mismatches=2)
    desktops = iter((original, reopened))
    processes = iter((Process(202), Process(101), Process(303)))
    windows = Windows()

    with pytest.raises(
        PublicWebWordError,
        match="PUBLIC_WEB_WORD_REOPEN_TEXT_MISMATCH",
    ):
        asyncio.run(
            run_public_web_word_workflow(
                config,
                PublicWebWordRequest(output, chrome, word),
                provider=WorkflowModel(output.name),
                desktop_factory=lambda _config: next(desktops),
                approvals=AllowWorkflowActions(),
                launcher=lambda _arguments: next(processes),
                windows=windows,
                sleep=lambda _seconds: None,
                run_id=RUN_ID,
            )
        )

    assert reopened.reopen_document_text_calls == 2
    assert original.close_calls == reopened.close_calls == 1


def test_reopen_semantic_match_changes_only_whitespace() -> None:
    flattened = NOTE.replace("\n", " ")
    observed = _document_envelope(flattened, "303")

    assert _document_text_semantically_contains_required(observed, NOTE)
    assert not _document_text_semantically_contains_required(
        observed.replace("collaborators", "contributors"),
        NOTE,
    )


@dataclass
class CorrectionModel:
    name: str = "correction-model"
    continuation_strategy: ProviderContinuationStrategy = (
        ProviderContinuationStrategy.STATELESS_REPLAY
    )
    calls: int = 0

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence[ToolSpec],
        memories: Sequence[MemoryContextItem] = (),
    ) -> ModelTurn:
        del task, tools, memories
        self.calls += 1
        name = "activate_window" if self.calls == 1 else "list_windows"
        arguments: Mapping[str, JSONValue] = (
            {"window_id": "999"} if self.calls == 1 else {}
        )
        if self.calls == 2:
            assert ledger[-1].tool_result is not None
            assert ledger[-1].tool_result.code == "POLICY_DENIED"
        return ModelTurn(
            run_id,
            turn_id,
            f"correction_{self.calls}",
            "",
            (_call(run_id, turn_id, name, arguments),),
            ModelUsage(4, 1),
        )

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        del run_id
        return {}

    def restore_continuation(
        self,
        run_id: str,
        state: Mapping[str, JSONValue],
        *,
        tools: Sequence[ToolSpec],
    ) -> None:
        del run_id, state, tools


def test_one_invalid_model_proposal_is_corrected_before_desktop_dispatch() -> None:
    inner = CorrectionModel()
    provider = ModelDrivenPublicWebWordProvider(
        inner,
        PUBLIC_WEB_WORD_SOURCE_TITLE,
        "result.docx",
        "101",
        "202",
    )
    list_tool = tuple(
        tool
        for tool in REVIEWED_TOOLS
        if tool.name in {"list_windows", "activate_window"}
    )

    turn = asyncio.run(
        provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_1",
            task="fixed workflow",
            ledger=(),
            tools=list_tool,
        )
    )

    assert inner.calls == 2
    assert turn.tool_calls[0].name == "list_windows"
    assert turn.usage == ModelUsage(8, 2)
    assert provider.correction_count(RUN_ID) == 1


def test_unready_fixture_feedback_requires_a_fresh_window_list() -> None:
    call = _call(RUN_ID, "turn_2", "ui_snapshot", {"scope": "101"})
    rejection = PublicWebWordProposalRejection(
        attempt=1,
        max_attempts=2,
        code="PUBLIC_WEB_WORD_FIXTURES_NOT_OBSERVED",
        tool_names=("ui_snapshot",),
    )

    event = ModelDrivenPublicWebWordProvider._proposal_feedback_events(
        (call,), rejection
    )[0]

    assert event.tool_result is not None
    assert event.tool_result.dispatch is DispatchCertainty.NOT_DISPATCHED
    assert "Request only list_windows with no arguments" in (
        event.tool_result.sanitized_text
    )
    assert "both exact fixture titles" in event.tool_result.sanitized_text


def test_redundant_screenshot_feedback_names_the_exact_next_step() -> None:
    call = _call(RUN_ID, "turn_12", "screenshot", {})
    rejection = PublicWebWordProposalRejection(
        attempt=1,
        max_attempts=2,
        code="PUBLIC_WEB_WORD_SCREENSHOT_OUT_OF_SCOPE",
        tool_names=("screenshot",),
    )

    event = ModelDrivenPublicWebWordProvider._proposal_feedback_events(
        (call,), rejection
    )[0]

    assert event.tool_result is not None
    assert "do not request another screenshot" in event.tool_result.sanitized_text
    assert "combo Ctrl+End" in event.tool_result.sanitized_text


def test_repeated_editor_click_feedback_names_the_exact_next_step() -> None:
    call = _call(RUN_ID, "turn_13", "click", {"x": 401, "y": 302})
    rejection = PublicWebWordProposalRejection(
        attempt=1,
        max_attempts=2,
        code="PUBLIC_WEB_WORD_EDITOR_COORDINATE_INVALID",
        tool_names=("click",),
    )

    event = ModelDrivenPublicWebWordProvider._proposal_feedback_events(
        (call,), rejection
    )[0]

    assert event.tool_result is not None
    assert "do not click again" in event.tool_result.sanitized_text
    assert "combo Ctrl+End" in event.tool_result.sanitized_text


def test_redundant_pre_save_read_feedback_requires_save() -> None:
    call = _call(RUN_ID, "turn_18", "document_text", {"scope": "202"})
    rejection = PublicWebWordProposalRejection(
        attempt=1,
        max_attempts=2,
        code="PUBLIC_WEB_WORD_SAVE_REQUIRED",
        tool_names=("document_text",),
    )

    event = ModelDrivenPublicWebWordProvider._proposal_feedback_events(
        (call,), rejection
    )[0]

    assert event.tool_result is not None
    assert "combo Ctrl+S now" in event.tool_result.sanitized_text
    assert "do not observe again" in event.tool_result.sanitized_text
