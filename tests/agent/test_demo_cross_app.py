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
    _window_id,
    project_demo_workflow,
)
from computer_use_agent.fakes import FakeDesktopMCP
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    PolicyDecision,
    PolicyDecisionKind,
    ToolResult,
    ToolResultStatus,
)
from computer_use_agent.workflow_checklist import (
    WorkflowStatus,
    WorkflowStepStatus,
)

RUN_ID = "cross-app-demo-test"
SUMMARY = f"\n{DEMO_TYPED_MARKER}\n- bounded fixture"
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
