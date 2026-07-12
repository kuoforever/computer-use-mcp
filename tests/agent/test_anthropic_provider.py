from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.providers.anthropic import (
    AnthropicMessagesProvider,
    AnthropicProviderError,
)
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.types import (
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    SafeArgumentSummary,
    ToolResult,
    ToolResultStatus,
)


@dataclass
class ScriptedMessages:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(
    response_id: str,
    *,
    content: list[object],
    stop_reason: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        content=content,
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=11, output_tokens=5),
    )


def test_claude_tool_use_and_adjacent_matching_tool_result() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_1",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="list_windows",
                        input={},
                    )
                ],
                stop_reason="tool_use",
            ),
            _response(
                "message_2",
                content=[SimpleNamespace(type="text", text="Notepad is open.")],
                stop_reason="end_turn",
            ),
        ]
    )
    provider = AnthropicMessagesProvider(model="test-model", messages=scripted)

    first = asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect windows",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    call = first.tool_calls[0]
    result = ToolResult(
        identity=call.identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad",
    )
    ledger = (
        LedgerEvent(
            event_id="event_1",
            kind=LedgerEventKind.MODEL_TURN,
            payload={"tool_call_count": 1},
        ),
        LedgerEvent(
            event_id="event_2",
            kind=LedgerEventKind.TOOL_CALL,
            identity=call.identity,
            safe_argument_summary=SafeArgumentSummary.from_tool_call(
                call, sensitive_arguments=()
            ),
        ),
        LedgerEvent(
            event_id="event_3",
            kind=LedgerEventKind.TOOL_RESULT,
            identity=call.identity,
            tool_result=result,
        ),
    )
    second = asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_2",
            task="Inspect windows",
            ledger=ledger,
            tools=REVIEWED_TOOLS,
        )
    )

    assert first.tool_calls[0].identity.call_id == "toolu_1"
    assert second.text == "Notepad is open."
    first_request, second_request = scripted.calls
    assert first_request["messages"] == [{"role": "user", "content": "Inspect windows"}]
    assert first_request["tool_choice"] == {
        "type": "auto",
        "disable_parallel_tool_use": True,
    }
    assert [tool["name"] for tool in first_request["tools"]] == [
        "ui_snapshot",
        "find",
        "list_windows",
    ]
    assert second_request["messages"] == [
        {"role": "user", "content": "Inspect windows"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "list_windows",
                    "input": {},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": (
                        '{"content":"window_1 | Notepad","ok":true,"status":"success"}'
                    ),
                    "is_error": False,
                }
            ],
        },
    ]


@pytest.mark.parametrize(
    "block",
    [
        SimpleNamespace(type="tool_use", id="toolu_1", name="click", input={"ref": "ref_1"}),
        SimpleNamespace(type="tool_use", id="toolu_1", name="list_windows", input={"extra": 1}),
        SimpleNamespace(type="thinking", thinking="unreviewed"),
    ],
)
def test_unadvertised_malformed_or_unreviewed_content_fails_closed(block: object) -> None:
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=ScriptedMessages(
            [_response("message_1", content=[block], stop_reason="tool_use")]
        ),
    )

    with pytest.raises(AnthropicProviderError):
        asyncio.run(
            provider.create_turn(
                run_id="run_1",
                turn_id="turn_1",
                task="Inspect",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )


@pytest.mark.parametrize(
    ("content", "stop_reason"),
    [
        ([SimpleNamespace(type="text", text="done")], "max_tokens"),
        (
            [SimpleNamespace(type="tool_use", id="toolu_1", name="list_windows", input={})],
            "end_turn",
        ),
    ],
)
def test_stop_reason_must_match_normalized_turn(
    content: list[object], stop_reason: str
) -> None:
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=ScriptedMessages(
            [_response("message_1", content=content, stop_reason=stop_reason)]
        ),
    )

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_STOP_REASON_INVALID"):
        asyncio.run(
            provider.create_turn(
                run_id="run_1",
                turn_id="turn_1",
                task="Inspect",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )


def test_anthropic_errors_do_not_echo_request_or_response_content() -> None:
    class BrokenMessages:
        async def create(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("task-secret provider-secret")

    provider = AnthropicMessagesProvider(model="test-model", messages=BrokenMessages())

    with pytest.raises(AnthropicProviderError) as raised:
        asyncio.run(
            provider.create_turn(
                run_id="run_1",
                turn_id="turn_1",
                task="task-secret",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )

    assert str(raised.value) == "ANTHROPIC_REQUEST_FAILED"


def test_approved_mode_advertises_reviewed_actions_but_not_type() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_1",
                content=[SimpleNamespace(type="text", text="done")],
                stop_reason="end_turn",
            )
        ]
    )
    provider = AnthropicMessagesProvider(
        model="test-model", messages=scripted, allow_actions=True
    )

    asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )

    assert [tool["name"] for tool in scripted.calls[0]["tools"]] == [
        "ui_snapshot",
        "find",
        "list_windows",
        "activate_window",
        "click",
        "key",
    ]
