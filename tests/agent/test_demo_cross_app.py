from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

import pytest

from computer_use_agent.config import (
    APPROVED_ACTIONS_MODE,
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.demo_cross_app import (
    DEMO_COMPLETE_TEXT,
    DEMO_TYPED_MARKER,
    CrossAppDemoError,
    CrossAppDemoProvider,
    DemoProposalRejection,
    ModelDrivenCrossAppDemoProvider,
    ModelDrivenDemoError,
    _post_save_verified,
    _window_id,
    project_demo_workflow,
)
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.tool_registry import REVIEWED_TOOLS, get_tool_spec
from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    ModelTurn,
    ModelUsage,
    PolicyDecision,
    PolicyDecisionKind,
    SafeArgumentSummary,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from computer_use_agent.workflow_checklist import (
    WorkflowStatus,
    WorkflowStepStatus,
)

RUN_ID = "cross-app-demo-test"
SOURCE_TITLE = "Guarded Desktop Agent Demo Source test"
SOURCE_URL = "https://support.microsoft.com/example-source"
SUMMARY = (
    f"\n\n{DEMO_TYPED_MARKER}\n"
    f"Source: {SOURCE_TITLE}\n"
    f"URL: {SOURCE_URL}\n"
    "- People collaborating can see presence and live document changes together.\n"
    "- Older versions can edit together but require periodic saves to exchange changes.\n"
)
_LIST_WINDOWS_ONLY = tuple(
    tool for tool in REVIEWED_TOOLS if tool.name == "list_windows"
)


def test_controlled_demo_provider_steps_map_to_human_workflow_chapters() -> None:
    expected = {
        0: ("review_public_source", 1),
        5: ("review_public_source", 1),
        6: ("open_research_brief", 2),
        8: ("open_research_brief", 2),
        9: ("add_verified_note", 3),
        14: ("add_verified_note", 3),
        15: ("save_research_brief", 4),
        16: ("verify_saved_document", 5),
        17: ("verify_saved_document", 5),
    }

    for provider_step, (current_step_id, completed_count) in expected.items():
        checklist = project_demo_workflow(provider_step)
        assert checklist.current_step_id == current_step_id
        assert sum(
            row.status is WorkflowStepStatus.COMPLETED
            for row in checklist.steps
        ) == completed_count

    ready = project_demo_workflow(18, status=WorkflowStatus.READY)
    assert ready.current_step_id is None
    assert all(
        row.status is WorkflowStepStatus.COMPLETED
        for row in ready.steps
    )


def test_controlled_demo_workflow_mapping_fails_closed() -> None:
    for provider_step in (-1, 19, True):
        with pytest.raises(ValueError, match="provider step is invalid"):
            project_demo_workflow(provider_step)
    with pytest.raises(ValueError, match="cannot be ready"):
        project_demo_workflow(17, status=WorkflowStatus.READY)
    with pytest.raises(ValueError, match="must be ready"):
        project_demo_workflow(18)


def test_cancelled_demo_keeps_its_prefix_without_claiming_a_current_chapter() -> None:
    checklist = project_demo_workflow(9, status=WorkflowStatus.CANCELLED)

    assert checklist.status is WorkflowStatus.CANCELLED
    assert checklist.current_step_id is None
    assert checklist.completed_count == 3
    assert checklist.not_started_count == 3
    assert all(
        row.status is not WorkflowStepStatus.IN_PROGRESS for row in checklist.steps
    )


def test_a_failing_step_observer_never_changes_the_demo() -> None:
    def explode(_: int) -> None:
        raise RuntimeError("observer failure must stay outside the Demo")

    provider = CrossAppDemoProvider(
        "Guarded Desktop Agent Demo Source test",
        "summary-test.rtf",
        SUMMARY,
        on_provider_step=explode,
    )

    async def scenario() -> None:
        turn = await provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_1",
            task="controlled",
            ledger=(),
            tools=_LIST_WINDOWS_ONLY,
        )
        assert turn.tool_calls[0].name == "list_windows"

    asyncio.run(scenario())
    assert provider.on_provider_step is None, "a failed observer is dropped, not retried"


def _result(
    turn: int,
    name: str,
    text: str = "",
) -> ToolResult:
    return ToolResult(
        CallIdentity(RUN_ID, f"turn_{turn}", f"call_{turn}"),
        name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text=text,
    )


def _completed_call(
    index: int,
    name: str,
    arguments: dict[str, object],
    text: str = "",
) -> tuple[LedgerEvent, LedgerEvent]:
    identity = CallIdentity(RUN_ID, f"turn_{index}", f"call_{index}")
    call = ToolCall(identity, name, arguments)
    spec = get_tool_spec(name)
    result = ToolResult(
        identity,
        name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text=text,
    )
    return (
        LedgerEvent(
            event_id=f"event_{index}_call",
            kind=LedgerEventKind.TOOL_CALL,
            identity=identity,
            safe_argument_summary=SafeArgumentSummary.from_tool_call(
                call, sensitive_arguments=spec.sensitive_arguments
            ),
        ),
        LedgerEvent(
            event_id=f"event_{index}_result",
            kind=LedgerEventKind.TOOL_RESULT,
            identity=identity,
            tool_result=result,
        ),
    )


def _model_ledger(*, post_save: bool = False) -> tuple[LedgerEvent, ...]:
    windows = (
        '* 101 | chrome.exe | "Guarded Desktop Agent Demo Source test - Google Chrome"\n'
        '  202 | winword.exe | "summary-test.rtf [Compatibility Mode] - Word"'
    )
    pairs = [
        _completed_call(1, "list_windows", {}, windows),
        _completed_call(2, "activate_window", {"window_id": "101"}),
        _completed_call(
            3,
            "ui_snapshot",
            {"scope": "101"},
            'ref_1 | document "Guarded Desktop Agent Demo Source test" | '
            "(1,2,300,400) | enabled",
        ),
        _completed_call(
            4,
            "ocr",
            {"x": 0, "y": 0, "w": 1920, "h": 1080},
            '{"source":"ocr","complete":true,"runs":['
            '{"text":"People collaborating can see presence and live document changes; '
            'older versions require periodic saves to exchange changes."}],'
            '"coordinate_space":"primary_display_physical_pixels"}',
        ),
        _completed_call(5, "activate_window", {"window_id": "202"}),
        _completed_call(
            6,
            "ui_snapshot",
            {"scope": "202"},
            'ref_7 | edit "页面 1 内容" | (1,2,300,400) | enabled',
        ),
        _completed_call(7, "key", {"combo": "Ctrl+End"}),
        _completed_call(
            8,
            "ui_snapshot",
            {"scope": "202"},
            'ref_7 | edit "页面 1 内容" | (1,2,300,400) | enabled',
        ),
        _completed_call(9, "type", {"text": SUMMARY}),
        _completed_call(10, "document_text", {"scope": "202"}, SUMMARY),
    ]
    if post_save:
        pairs.extend(
            (
                _completed_call(11, "key", {"combo": "Ctrl+S"}),
                _completed_call(12, "document_text", {"scope": "202"}, SUMMARY),
            )
        )
    return tuple(event for pair in pairs for event in pair)


def _wrapped_model(
    turn: ModelTurn, *, max_proposal_corrections: int = 0
) -> ModelDrivenCrossAppDemoProvider:
    return ModelDrivenCrossAppDemoProvider(
        inner=FakeModelProvider(turns=deque((turn,))),
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment="summary-test.rtf",
        source_url=SOURCE_URL,
        max_proposal_corrections=max_proposal_corrections,
    )


def test_model_driven_demo_accepts_exact_payload_but_discards_provider_prose() -> None:
    turn = ModelTurn(
        RUN_ID,
        "turn_10",
        "response_10",
        "I think this is safe",
        (
            ToolCall(
                CallIdentity(RUN_ID, "turn_10", "call_10"),
                "type",
                {"text": SUMMARY},
            ),
        ),
    )
    provider = _wrapped_model(turn)

    result = asyncio.run(
        provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_10",
            task="bounded",
            ledger=_model_ledger()[:-4],
            tools=REVIEWED_TOOLS,
        )
    )

    assert result.text == ""
    assert result.tool_calls[0].arguments == {"text": SUMMARY}


def test_model_driven_demo_allows_bounded_document_read_in_exact_chrome() -> None:
    turn = ModelTurn(
        RUN_ID,
        "turn_4",
        "response_4",
        "",
        (
            ToolCall(
                CallIdentity(RUN_ID, "turn_4", "call_4"),
                "document_text",
                {"scope": "101"},
            ),
        ),
    )
    provider = _wrapped_model(turn)

    result = asyncio.run(
        provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_4",
            task="bounded",
            ledger=_model_ledger()[:6],
            tools=REVIEWED_TOOLS,
        )
    )

    assert result.tool_calls[0].arguments == {"scope": "101"}


def test_semantic_chrome_text_can_satisfy_source_evidence_without_ocr() -> None:
    ledger = (
        *_model_ledger()[:6],
        *_completed_call(
            4,
            "document_text",
            {"scope": "101"},
            "Word supports collaboration and co-authoring.",
        ),
    )
    turn = ModelTurn(
        RUN_ID,
        "turn_5",
        "response_5",
        "",
        (
            ToolCall(
                CallIdentity(RUN_ID, "turn_5", "call_5"),
                "activate_window",
                {"window_id": "202"},
            ),
        ),
    )
    provider = _wrapped_model(turn)

    result = asyncio.run(
        provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_5",
            task="bounded",
            ledger=ledger,
            tools=REVIEWED_TOOLS,
        )
    )

    assert result.tool_calls[0].arguments == {"window_id": "202"}


@pytest.mark.parametrize(
    ("name", "arguments", "error"),
    [
        ("activate_window", {"window_id": "999"}, "WINDOW_OUT_OF_SCOPE"),
        ("ui_snapshot", {"scope": "foreground"}, "AMBIENT_SCOPE_FORBIDDEN"),
        ("document_text", {"scope": "all"}, "AMBIENT_SCOPE_FORBIDDEN"),
        ("click", {"x": 10, "y": 20}, "EDITOR_REF_INVALID"),
        ("type", {"text": "model chose different text"}, "TYPED_PAYLOAD_INVALID"),
        ("key", {"combo": "Alt+F4"}, "KEY_OUT_OF_SCOPE"),
        ("screenshot", {}, "TOOL_OUT_OF_SCOPE"),
    ],
)
def test_model_driven_demo_rejects_escape_attempts_before_runner_dispatch(
    name: str,
    arguments: dict[str, object],
    error: str,
) -> None:
    turn = ModelTurn(
        RUN_ID,
        "turn_10",
        "response_10",
        "",
        (ToolCall(CallIdentity(RUN_ID, "turn_10", "call_10"), name, arguments),),
    )
    provider = _wrapped_model(turn)

    with pytest.raises(ModelDrivenDemoError, match=error):
        asyncio.run(
            provider.create_turn(
                run_id=RUN_ID,
                turn_id="turn_10",
                task="bounded",
                ledger=_model_ledger(),
                tools=REVIEWED_TOOLS,
            )
        )


def test_model_driven_demo_replans_after_known_not_dispatched_rejection() -> None:
    first = ModelTurn(
        RUN_ID,
        "turn_10",
        "response_rejected",
        "save now",
        (
            ToolCall(
                CallIdentity(RUN_ID, "turn_10", "call_rejected"),
                "key",
                {"combo": "Ctrl+S"},
            ),
        ),
        ModelUsage(input_tokens=10, output_tokens=2),
    )
    corrected = ModelTurn(
        RUN_ID,
        "turn_10",
        "response_corrected",
        "verify first",
        (
            ToolCall(
                CallIdentity(RUN_ID, "turn_10", "call_corrected"),
                "document_text",
                {"scope": "202"},
            ),
        ),
        ModelUsage(input_tokens=11, output_tokens=3),
    )
    inner = FakeModelProvider(turns=deque((first, corrected)))
    rejections: list[DemoProposalRejection] = []
    provider = ModelDrivenCrossAppDemoProvider(
        inner=inner,
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment="summary-test.rtf",
        source_url=SOURCE_URL,
        on_proposal_rejected=rejections.append,
    )

    result = asyncio.run(
        provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_10",
            task="bounded",
            ledger=_model_ledger()[:-2],
            tools=REVIEWED_TOOLS,
        )
    )

    assert result.provider_response_id == "response_corrected"
    assert result.tool_calls[0].name == "document_text"
    assert result.usage == ModelUsage(input_tokens=21, output_tokens=5)
    assert rejections == [
        DemoProposalRejection(
            attempt=1,
            max_attempts=2,
            code="DEMO_MODEL_SAVE_NOT_VERIFIED",
            tool_names=("key",),
        )
    ]
    feedback = inner.calls[1]["ledger"][-1]
    assert isinstance(feedback, LedgerEvent)
    assert feedback.tool_result is not None
    assert feedback.tool_result.status is ToolResultStatus.REJECTED
    assert feedback.tool_result.dispatch is DispatchCertainty.NOT_DISPATCHED
    assert feedback.tool_result.code == "POLICY_DENIED"
    assert "DEMO_MODEL_SAVE_NOT_VERIFIED" in feedback.tool_result.sanitized_text


def test_model_driven_demo_correction_budget_remains_fail_closed() -> None:
    invalid_turns = deque(
        ModelTurn(
            RUN_ID,
            "turn_10",
            f"response_{index}",
            "",
            (
                ToolCall(
                    CallIdentity(RUN_ID, "turn_10", f"call_{index}"),
                    "key",
                    {"combo": "Alt+F4"},
                ),
            ),
        )
        for index in range(3)
    )
    inner = FakeModelProvider(turns=invalid_turns)
    provider = ModelDrivenCrossAppDemoProvider(
        inner=inner,
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment="summary-test.rtf",
        source_url=SOURCE_URL,
    )

    with pytest.raises(ModelDrivenDemoError, match="KEY_OUT_OF_SCOPE"):
        asyncio.run(
            provider.create_turn(
                run_id=RUN_ID,
                turn_id="turn_10",
                task="bounded",
                ledger=_model_ledger(),
                tools=REVIEWED_TOOLS,
            )
        )

    assert len(inner.calls) == 3


def test_model_driven_demo_refuses_early_finish_and_normalizes_verified_finish() -> None:
    early = _wrapped_model(ModelTurn(RUN_ID, "turn_10", "early", "done"))
    with pytest.raises(ModelDrivenDemoError, match="FINISHED_BEFORE_VERIFICATION"):
        asyncio.run(
            early.create_turn(
                run_id=RUN_ID,
                turn_id="turn_10",
                task="bounded",
                ledger=_model_ledger(),
                tools=REVIEWED_TOOLS,
            )
        )

    steps: list[int] = []
    inner = FakeModelProvider(
        turns=deque((ModelTurn(RUN_ID, "turn_12", "verified", "model prose"),))
    )
    verified = ModelDrivenCrossAppDemoProvider(
        inner=inner,
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment="summary-test.rtf",
        source_url=SOURCE_URL,
        on_provider_step=steps.append,
    )
    verified._accepted_notes[RUN_ID] = SUMMARY
    result = asyncio.run(
        verified.create_turn(
            run_id=RUN_ID,
            turn_id="turn_12",
            task="bounded",
            ledger=_model_ledger(post_save=True),
            tools=REVIEWED_TOOLS,
        )
    )

    assert result.text == DEMO_COMPLETE_TEXT
    assert steps == [17, 18]


def test_post_save_marker_must_come_from_the_exact_word_scope() -> None:
    ledger = (
        *_model_ledger(),
        *_completed_call(11, "key", {"combo": "Ctrl+S"}),
        *_completed_call(12, "document_text", {"scope": "101"}, SUMMARY),
    )

    assert not _post_save_verified(ledger, word_window_id="202")


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("PAGEDOWN", "PageDown"),
        ("Page_Down", "PageDown"),
        ("CTRL+END", "Ctrl+End"),
        ("Control+S", "Ctrl+S"),
    ],
)
def test_model_demo_normalizes_only_reviewed_key_aliases(
    alias: str, canonical: str
) -> None:
    call = ToolCall(
        CallIdentity(RUN_ID, "turn_alias", "call_alias"),
        "key",
        {"combo": alias},
    )

    normalized = ModelDrivenCrossAppDemoProvider._normalize_reviewed_key_alias(call)

    assert normalized.arguments == {"combo": canonical}
    assert normalized.identity == call.identity


def test_model_demo_does_not_normalize_an_unreviewed_key() -> None:
    call = ToolCall(
        CallIdentity(RUN_ID, "turn_alias", "call_alias"),
        "key",
        {"combo": "Ctrl+A"},
    )

    assert (
        ModelDrivenCrossAppDemoProvider._normalize_reviewed_key_alias(call) is call
    )


def test_model_demo_validates_generated_brief_without_substituting_host_text() -> None:
    provider = ModelDrivenCrossAppDemoProvider(
        inner=FakeModelProvider(),
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment="summary-test.rtf",
        source_url=SOURCE_URL,
    )

    alternative = (
        f"\n\n{DEMO_TYPED_MARKER}\n"
        f"Source: {SOURCE_TITLE}\n"
        f"URL: {SOURCE_URL}\n"
        "- Live collaboration exposes presence while people edit document changes.\n"
        "- Periodic saves let older versions exchange edits without live updates.\n"
    )

    assert alternative != SUMMARY
    assert provider._valid_source_brief(SUMMARY, _model_ledger(), "101")
    assert provider._valid_source_brief(alternative, _model_ledger(), "101")
    assert not provider._valid_source_brief(
        SUMMARY.replace(SOURCE_URL, "https://example.invalid"),
        _model_ledger(),
        "101",
    )
    assert not provider._valid_source_brief(
        SUMMARY.replace(
            "People collaborating can see presence and live document changes together.",
            "A completely unrelated weather forecast belongs in this report.",
        ),
        _model_ledger(),
        "101",
    )


def test_model_driven_demo_allows_only_one_call_per_turn() -> None:
    calls = tuple(
        ToolCall(CallIdentity(RUN_ID, "turn_1", f"call_{index}"), "list_windows", {})
        for index in (1, 2)
    )
    provider = _wrapped_model(ModelTurn(RUN_ID, "turn_1", "response_1", "", calls))

    with pytest.raises(ModelDrivenDemoError, match="MULTIPLE_CALLS"):
        asyncio.run(
            provider.create_turn(
                run_id=RUN_ID,
                turn_id="turn_1",
                task="bounded",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )


class AllowExactActions:
    focus_taking = True

    def __init__(self) -> None:
        self.requests: list[ApprovalRequest] = []

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        return PolicyDecision(
            request.request_id,
            request.identity,
            request.call_digest,
            PolicyDecisionKind.ALLOW,
            "test_operator",
        )


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "cross-app",
        policy_version="cross-app-demo-test-v1",
        provider=ProviderConfig("openai", "controlled-demo"),
        mcp=MCPLaunchConfig(
            executable=(tmp_path / "guarded-desktop-mcp.exe").resolve(),
            args=(),
            cwd=tmp_path.resolve(),
            environment={"CUMCP_ALLOWLIST": "chrome.exe,winword.exe"},
        ),
        policy=PolicyConfig(
            mode=APPROVED_ACTIONS_MODE,
            max_model_turns=20,
            max_tool_calls=20,
            max_side_effects=7,
        ),
    )


def test_controlled_cross_app_demo_uses_runner_approval_and_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boundaries: list[int] = []
    provider = CrossAppDemoProvider(
        "Guarded Desktop Agent Demo Source test",
        "summary-test.rtf",
        SUMMARY,
        on_provider_step=boundaries.append,
    )
    desktop = FakeDesktopMCP(
        satisfied_safety_baselines=frozenset(
            {
                "title_matched_image_redaction",
                "typed_text_audit_redaction",
            }
        ),
        results=deque(
            (
                _result(
                    1,
                    "list_windows",
                    '* 101 | chrome.exe | "Guarded Desktop Agent Demo Source test - Google Chrome"\n'
                    '  202 | winword.exe | "summary-test.rtf [Compatibility Mode] - Word"',
                ),
                _result(
                    2,
                    "activate_window",
                ),
                _result(
                    3,
                    "ui_snapshot",
                    'ref_1 | document "Guarded Desktop Agent Demo Source test" '
                    "| (1,2,300,400) | enabled",
                ),
                _result(
                    4,
                    "ocr",
                    '{"source":"ocr","complete":true,"runs":['
                    '{"text":"Runtime"},{"text":"Safety"},{"text":"Recovery"}],'
                    '"coordinate_space":"primary_display_physical_pixels"}',
                ),
                _result(
                    5,
                    "key",
                ),
                _result(
                    6,
                    "ui_snapshot",
                    'ref_1 | document "Guarded Desktop Agent Demo Source test" '
                    "| (1,2,300,400) | enabled",
                ),
                _result(
                    7,
                    "list_windows",
                    '* 101 | chrome.exe | "Guarded Desktop Agent Demo Source test - Google Chrome"\n'
                    '  202 | winword.exe | "summary-test.rtf [Compatibility Mode] - Word"',
                ),
                _result(8, "activate_window"),
                _result(
                    9,
                    "ui_snapshot",
                    'ref_7 | edit "页面 1 内容" | (1,2,300,400) | enabled',
                ),
                _result(10, "click"),
                _result(
                    11,
                    "ui_snapshot",
                    'ref_7 | edit "页面 1 内容" | (1,2,300,400) | enabled',
                ),
                _result(12, "key"),
                _result(
                    13,
                    "ui_snapshot",
                    'ref_7 | edit "页面 1 内容" | (1,2,300,400) | enabled',
                ),
                _result(14, "type"),
                _result(15, "document_text", SUMMARY),
                _result(16, "key"),
                _result(17, "document_text", SUMMARY),
            )
        ),
    )
    approvals = AllowExactActions()
    outcome = asyncio.run(
        AgentRunner(
            _config(tmp_path, monkeypatch),
            RunnerPorts(provider, desktop, approvals),
        ).run(
            "Run controlled cross-application fixture",
            run_id=RUN_ID,
            allowed_tool_names=frozenset(
                {
                        "list_windows",
                        "document_text",
                        "ocr",
                        "activate_window",
                    "ui_snapshot",
                    "click",
                    "type",
                    "key",
                }
            ),
        )
    )

    assert outcome.text == DEMO_COMPLETE_TEXT
    assert [call.name for call in desktop.tool_calls] == [
        "list_windows",
        "activate_window",
        "ui_snapshot",
        "ocr",
        "key",
        "ui_snapshot",
        "list_windows",
        "activate_window",
        "ui_snapshot",
        "click",
        "ui_snapshot",
        "key",
        "ui_snapshot",
        "type",
        "document_text",
        "key",
        "document_text",
    ]
    assert [request.tool_name for request in approvals.requests] == [
        "activate_window",
        "key",
        "activate_window",
        "click",
        "key",
        "type",
        "key",
    ]
    type_request = approvals.requests[5]
    assert type_request.safe_argument_summary.values == {
        "text_present": True,
        "text_length": len(SUMMARY),
        "ref_supplied": False,
    }
    assert SUMMARY not in repr(outcome.state.event_log)
    # The passive HUD observer sees every fixed boundary in order, ending at the
    # terminal one. It receives integers only: no prose, window id, or content.
    assert boundaries == list(range(1, 19))


def test_model_driven_demo_chooses_a_shorter_verified_path_through_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def requested(
        turn: int, name: str | None = None, arguments: dict[str, object] | None = None
    ) -> ModelTurn:
        calls = (
            ()
            if name is None
            else (
                ToolCall(
                    CallIdentity(RUN_ID, f"turn_{turn}", f"call_{turn}"),
                    name,
                    arguments or {},
                ),
            )
        )
        return ModelTurn(
            RUN_ID,
            f"turn_{turn}",
            f"model_response_{turn}",
            "model completion claim" if name is None else "model rationale",
            calls,
        )

    inner = FakeModelProvider(
        turns=deque(
            (
                requested(1, "list_windows"),
                requested(2, "activate_window", {"window_id": "101"}),
                requested(3, "ui_snapshot", {"scope": "101"}),
                requested(4, "ocr", {"x": 0, "y": 0, "w": 1920, "h": 1080}),
                requested(5, "list_windows"),
                requested(6, "activate_window", {"window_id": "202"}),
                requested(7, "ui_snapshot", {"scope": "202"}),
                requested(8, "click", {"ref": "ref_7"}),
                requested(9, "ui_snapshot", {"scope": "202"}),
                requested(10, "key", {"combo": "Ctrl+End"}),
                requested(11, "ui_snapshot", {"scope": "202"}),
                requested(12, "type", {"text": SUMMARY}),
                requested(13, "document_text", {"scope": "202"}),
                requested(14, "key", {"combo": "Ctrl+S"}),
                requested(15, "document_text", {"scope": "202"}),
                requested(16),
            )
        )
    )
    provider = ModelDrivenCrossAppDemoProvider(
        inner=inner,
        chrome_title_fragment=SOURCE_TITLE,
        word_title_fragment="summary-test.rtf",
        source_url=SOURCE_URL,
    )
    window_list = (
        '* 101 | chrome.exe | "Guarded Desktop Agent Demo Source test - Google Chrome"\n'
        '  202 | winword.exe | "summary-test.rtf [Compatibility Mode] - Word"'
    )
    chrome_snapshot = (
        'ref_1 | document "Guarded Desktop Agent Demo Source test" '
        "| (1,2,300,400) | enabled"
    )
    word_snapshot = 'ref_7 | edit "页面 1 内容" | (1,2,300,400) | enabled'
    desktop = FakeDesktopMCP(
        satisfied_safety_baselines=frozenset(
            {"title_matched_image_redaction", "typed_text_audit_redaction"}
        ),
        results=deque(
            (
                _result(1, "list_windows", window_list),
                _result(2, "activate_window"),
                _result(3, "ui_snapshot", chrome_snapshot),
                    _result(
                        4,
                        "ocr",
                        '{"source":"ocr","complete":true,"runs":['
                        '{"text":"People collaborating can see presence and live '
                        'document changes; older versions require periodic saves to '
                        'exchange changes."}],'
                        '"coordinate_space":"primary_display_physical_pixels"}',
                    ),
                _result(5, "list_windows", window_list),
                _result(6, "activate_window"),
                _result(7, "ui_snapshot", word_snapshot),
                _result(8, "click"),
                _result(9, "ui_snapshot", word_snapshot),
                _result(10, "key"),
                _result(11, "ui_snapshot", word_snapshot),
                _result(12, "type"),
                _result(13, "document_text", SUMMARY),
                _result(14, "key"),
                _result(15, "document_text", SUMMARY),
            )
        ),
    )
    approvals = AllowExactActions()

    outcome = asyncio.run(
        AgentRunner(
            _config(tmp_path, monkeypatch),
            RunnerPorts(provider, desktop, approvals),
        ).run(
            "Model chooses the bounded path",
            run_id=RUN_ID,
            allowed_tool_names=frozenset(
                {
                    "list_windows",
                    "document_text",
                    "ocr",
                    "activate_window",
                    "ui_snapshot",
                    "click",
                    "type",
                    "key",
                }
            ),
        )
    )

    assert outcome.text == DEMO_COMPLETE_TEXT
    assert len(inner.calls) == 16
    assert outcome.state.budgets.tool_calls_used == 15
    assert outcome.state.budgets.side_effects_used == 6
    assert [request.tool_name for request in approvals.requests] == [
        "activate_window",
        "activate_window",
        "click",
        "key",
        "type",
        "key",
    ]


def test_controlled_provider_rejects_a_missing_required_tool() -> None:
    provider = CrossAppDemoProvider(
        "Guarded Desktop Agent Demo Source test",
        "summary-test.rtf",
        SUMMARY,
    )

    async def scenario() -> None:
        first = await provider.create_turn(
            run_id=RUN_ID,
            turn_id="turn_1",
            task="controlled",
            ledger=(),
            tools=(),
        )
        assert first.tool_calls[0].name == "list_windows"

    with pytest.raises(CrossAppDemoError, match="DEMO_REQUIRED_TOOL_NOT_ADVERTISED"):
        asyncio.run(scenario())


def test_foreground_requirement_ignores_a_stale_same_title_browser() -> None:
    windows = (
        '  101 | chrome.exe | "Public article - Google Chrome"\n'
        '* 303 | chrome.exe | "Public article - Google Chrome"'
    )

    assert _window_id(
        windows,
        owner="chrome.exe",
        title_fragment="Public article",
        require_foreground=True,
    ) == "303"
