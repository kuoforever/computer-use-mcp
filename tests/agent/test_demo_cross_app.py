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
)
from computer_use_agent.fakes import FakeDesktopMCP
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    PolicyDecision,
    PolicyDecisionKind,
    ToolResult,
    ToolResultStatus,
)

RUN_ID = "cross-app-demo-test"
SUMMARY = f"\n{DEMO_TYPED_MARKER}\n- bounded fixture"


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
    provider = CrossAppDemoProvider(
        "Guarded Desktop Agent Demo Source test",
        "summary-test.rtf",
        SUMMARY,
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
