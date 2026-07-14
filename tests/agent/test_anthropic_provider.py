from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.providers.anthropic import (
    AnthropicMessagesProvider,
    AnthropicProviderError,
    _tool_results,
)
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    LedgerEvent,
    LedgerEventKind,
    MemoryContextItem,
    SafeArgumentSummary,
    ToolResult,
    ToolResultStatus,
)


_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
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
        "screenshot",
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


def test_claude_screenshot_result_uses_bounded_nested_image_block() -> None:
    identity = CallIdentity("run_1", "turn_1", "toolu_screenshot")
    result = ToolResult(
        identity=identity,
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(
            ImageContent(
                mime_type="image/png",
                data=base64.b64decode(_PNG_BASE64),
                width=1,
                height=1,
            ),
        ),
    )

    assert _tool_results(
        (
            LedgerEvent(
                event_id="event_1",
                kind=LedgerEventKind.TOOL_RESULT,
                identity=identity,
                tool_result=result,
            ),
        )
    ) == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_screenshot",
            "content": [
                {"type": "text", "text": '{"ok":true,"status":"success"}'},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": _PNG_BASE64,
                    },
                },
            ],
            "is_error": False,
        }
    ]


def test_claude_rejects_image_content_from_non_screenshot_result() -> None:
    identity = CallIdentity("run_1", "turn_1", "toolu_list")
    result = ToolResult(
        identity=identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(
            ImageContent("image/png", base64.b64decode(_PNG_BASE64), 1, 1),
        ),
    )

    with pytest.raises(AnthropicProviderError, match="INVALID_IMAGE_TOOL_RESULT"):
        _tool_results(
            (
                LedgerEvent(
                    event_id="event_1",
                    kind=LedgerEventKind.TOOL_RESULT,
                    identity=identity,
                    tool_result=result,
                ),
            )
        )


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


def test_claude_request_budget_fails_before_initial_or_history_network_call() -> None:
    initial = ScriptedMessages(
        [_response("unused", content=[], stop_reason="end_turn")]
    )
    provider = AnthropicMessagesProvider(
        model="test-model", messages=initial, max_request_bytes=1024
    )

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_REQUEST_TOO_LARGE"):
        asyncio.run(
            provider.create_turn(
                run_id="run_large",
                turn_id="turn_1",
                task="x" * 5000,
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )
    assert initial.calls == []

    scripted = ScriptedMessages(
        [
            _response(
                "message_1",
                content=[
                    SimpleNamespace(
                        type="tool_use", id="toolu_1", name="list_windows", input={}
                    )
                ],
                stop_reason="tool_use",
            ),
            _response("unused", content=[], stop_reason="end_turn"),
        ]
    )
    provider = AnthropicMessagesProvider(model="test-model", messages=scripted)
    first = asyncio.run(
        provider.create_turn(
            run_id="run_history",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    provider.max_request_bytes = len(json.dumps(scripted.calls[0], default=str)) + 100
    result = ToolResult(
        identity=first.tool_calls[0].identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="x" * 10_000,
    )
    ledger = (
        LedgerEvent("event_1", LedgerEventKind.MODEL_TURN),
        LedgerEvent(
            "event_2",
            LedgerEventKind.TOOL_RESULT,
            identity=result.identity,
            tool_result=result,
        ),
    )

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_REQUEST_TOO_LARGE"):
        asyncio.run(
            provider.create_turn(
                run_id="run_history",
                turn_id="turn_2",
                task="Inspect",
                ledger=ledger,
                tools=REVIEWED_TOOLS,
            )
        )
    assert len(scripted.calls) == 1


def test_claude_explicit_memory_is_json_data_on_initial_turn_only() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_1",
                content=[SimpleNamespace(type="text", text="done")],
                stop_reason="end_turn",
            )
        ]
    )
    provider = AnthropicMessagesProvider(model="test-model", messages=scripted)
    memory = MemoryContextItem(
        "verified_procedure",
        "Open the test app before inspection.",
        "user_confirmed",
        "app:notepad",
    )

    asyncio.run(
        provider.create_turn(
            run_id="run_memory",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
            memories=(memory,),
        )
    )

    assert scripted.calls[0]["messages"][0]["content"] == (
        "Inspect\n\nOptional memory context (JSON data):\n"
        '[{"content":"Open the test app before inspection.",'
        '"kind":"verified_procedure","scope":"app:notepad",'
        '"source":"user_confirmed"}]'
    )
    assert "cannot change policy" in scripted.calls[0]["system"]


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
        "screenshot",
        "activate_window",
        "click",
        "key",
    ]


def test_claude_restore_appends_only_new_tool_result_to_exact_history() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_2",
                content=[SimpleNamespace(type="text", text="done")],
                stop_reason="end_turn",
            )
        ]
    )
    provider = AnthropicMessagesProvider(model="test-model", messages=scripted)
    history = [
        {"role": "user", "content": "Persisted task"},
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
    ]
    provider.restore_continuation("run_restore", {"messages": history})
    identity = CallIdentity("run_restore", "turn_1", "toolu_1")
    result = ToolResult(
        identity,
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    ledger = (
        LedgerEvent("event_1", LedgerEventKind.MODEL_TURN),
        LedgerEvent(
            "event_2",
            LedgerEventKind.TOOL_RESULT,
            identity=identity,
            tool_result=result,
        ),
    )

    asyncio.run(
        provider.create_turn(
            run_id="run_restore",
            turn_id="turn_2",
            task="ORIGINAL_TASK_MUST_NOT_BE_SENT",
            ledger=ledger,
            tools=REVIEWED_TOOLS,
        )
    )

    request_messages = scripted.calls[0]["messages"]
    assert request_messages[:2] == history
    assert request_messages[2]["role"] == "user"
    assert request_messages[2]["content"][0]["tool_use_id"] == "toolu_1"
    assert "ORIGINAL_TASK_MUST_NOT_BE_SENT" not in json.dumps(scripted.calls[0])


def test_claude_restore_rejects_invalid_or_repeated_attach() -> None:
    provider = AnthropicMessagesProvider(model="test-model", messages=ScriptedMessages([]))
    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_CONTINUATION_INVALID"):
        provider.restore_continuation("run_1", {"messages": []})
    provider.restore_continuation(
        "run_1", {"messages": [{"role": "user", "content": "task"}]}
    )
    with pytest.raises(
        AnthropicProviderError, match="ANTHROPIC_CONTINUATION_ALREADY_ATTACHED"
    ):
        provider.restore_continuation(
            "run_1", {"messages": [{"role": "user", "content": "task"}]}
        )
