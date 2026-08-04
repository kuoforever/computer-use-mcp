from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.providers.anthropic import (
    CONTEXT_PACKING_NOTICE,
    AnthropicMessagesProvider,
    AnthropicProviderError,
    _tool_results,
)
from computer_use_agent.provider_instructions import ActionInstructionProfile
from computer_use_agent.token_window import conservative_input_token_bound
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    LedgerEvent,
    LedgerEventKind,
    MemoryContextItem,
    ProviderContinuationStrategy,
    SafeArgumentSummary,
    ToolResult,
    ToolResultStatus,
)


_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_claude_declares_local_message_history_continuation() -> None:
    scripted = ScriptedMessages([])
    provider = AnthropicMessagesProvider(model="test-model", messages=scripted)

    assert provider.continuation_strategy is (
        ProviderContinuationStrategy.LOCAL_MESSAGE_HISTORY
    )
    assert scripted.calls == []


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


def test_claude_cross_app_demo_profile_is_closed_and_advertises_actions() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_demo",
                content=[SimpleNamespace(type="text", text="done")],
                stop_reason="end_turn",
            )
        ]
    )
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=scripted,
        allow_actions=True,
        action_instruction_profile=ActionInstructionProfile.CROSS_APP_DEMO,
    )

    asyncio.run(
        provider.create_turn(
            run_id="run_demo",
            turn_id="turn_1",
            task="bounded demo",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )

    request = scripted.calls[0]
    assert "disposable" in str(request["system"])
    assert "collect both a Chrome ui_snapshot" in str(request["system"])
    assert "document_text alone is not enough" in str(request["system"])
    assert "does not ground keyboard input" in str(request["system"])
    assert "Never use Ctrl+A" in str(request["system"])
    assert "never substitutes a prewritten answer" in str(request["system"])
    assert "type" in {tool["name"] for tool in request["tools"]}


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
        "capture_region",
        "document_text",
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


def test_claude_preserves_opaque_reasoning_blocks_across_tool_result() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_1",
                content=[
                    SimpleNamespace(
                        type="thinking",
                        thinking="",
                        signature="signed-thinking",
                    ),
                    SimpleNamespace(
                        type="redacted_thinking",
                        data="encrypted-redacted-thinking",
                    ),
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_1",
                        name="list_windows",
                        input={},
                    ),
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
            run_id="run_reasoning",
            turn_id="turn_1",
            task="Inspect windows",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    assert first.text == ""
    call = first.tool_calls[0]
    result = ToolResult(
        identity=call.identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad",
    )
    ledger = (
        LedgerEvent("event_1", LedgerEventKind.MODEL_TURN),
        LedgerEvent(
            "event_2",
            LedgerEventKind.TOOL_RESULT,
            identity=call.identity,
            tool_result=result,
        ),
    )

    second = asyncio.run(
        provider.create_turn(
            run_id="run_reasoning",
            turn_id="turn_2",
            task="Inspect windows",
            ledger=ledger,
            tools=REVIEWED_TOOLS,
        )
    )

    assert second.text == "Notepad is open."
    assert scripted.calls[1]["messages"][1]["content"] == [
        {
            "type": "thinking",
            "thinking": "",
            "signature": "signed-thinking",
        },
        {
            "type": "redacted_thinking",
            "data": "encrypted-redacted-thinking",
        },
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "list_windows",
            "input": {},
        },
    ]
    assert "signed-thinking" not in second.text
    assert "encrypted-redacted-thinking" not in second.text


@pytest.mark.parametrize(
    "block",
    [
        {"type": "thinking", "thinking": "summary", "signature": ""},
        {"type": "thinking", "thinking": 1, "signature": "signature"},
        {
            "type": "thinking",
            "thinking": "summary",
            "signature": "signature",
            "extra": "field",
        },
        {"type": "redacted_thinking", "data": ""},
        {"type": "redacted_thinking", "data": 1},
        {"type": "redacted_thinking", "data": "opaque", "extra": "field"},
    ],
)
def test_claude_rejects_malformed_reasoning_blocks(block: object) -> None:
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=ScriptedMessages(
            [_response("message_1", content=[block], stop_reason="end_turn")]
        ),
    )

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_RESPONSE_INVALID"):
        asyncio.run(
            provider.create_turn(
                run_id="run_reasoning",
                turn_id="turn_1",
                task="Inspect",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )


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


def test_claude_token_window_fails_before_network_and_reserves_output() -> None:
    scripted = ScriptedMessages(
        [_response("unused", content=[], stop_reason="end_turn")]
    )
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=scripted,
        max_tokens=256,
        max_request_bytes=100_000,
        context_window_tokens=2_000,
    )

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(
            provider.create_turn(
                run_id="run_token_window",
                turn_id="turn_1",
                task="x" * 5_000,
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )

    assert scripted.calls == []
    assert provider.export_continuation("run_token_window") == {"messages": []}


def test_claude_token_window_drops_only_oldest_complete_group() -> None:
    scripted = ScriptedMessages(
        [
            _response(
                "message_1",
                content=[
                    SimpleNamespace(
                        type="thinking",
                        thinking="old reasoning",
                        signature="old-signature",
                    ),
                    SimpleNamespace(
                        type="tool_use", id="toolu_1", name="list_windows", input={}
                    )
                ],
                stop_reason="tool_use",
            ),
            _response(
                "message_2",
                content=[
                    SimpleNamespace(
                        type="redacted_thinking",
                        data="new-redacted-reasoning",
                    ),
                    SimpleNamespace(
                        type="tool_use", id="toolu_2", name="screenshot", input={}
                    )
                ],
                stop_reason="tool_use",
            ),
            _response(
                "message_3",
                content=[SimpleNamespace(type="text", text="done")],
                stop_reason="end_turn",
            ),
        ]
    )
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=scripted,
        max_request_bytes=100_000,
        context_window_tokens=100_000,
    )
    first = asyncio.run(
        provider.create_turn(
            run_id="run_pack",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    first_result = ToolResult(
        first.tool_calls[0].identity,
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="old observation " * 1_000,
    )
    first_ledger = (
        LedgerEvent("event_1", LedgerEventKind.MODEL_TURN),
        LedgerEvent(
            "event_2",
            LedgerEventKind.TOOL_RESULT,
            identity=first_result.identity,
            tool_result=first_result,
        ),
    )
    second = asyncio.run(
        provider.create_turn(
            run_id="run_pack",
            turn_id="turn_2",
            task="Inspect",
            ledger=first_ledger,
            tools=REVIEWED_TOOLS,
        )
    )
    second_result = ToolResult(
        second.tool_calls[0].identity,
        "screenshot",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        images=(ImageContent("image/png", base64.b64decode(_PNG_BASE64), 1, 1),),
    )
    second_ledger = (
        LedgerEvent("event_3", LedgerEventKind.MODEL_TURN),
        LedgerEvent(
            "event_4",
            LedgerEventKind.TOOL_RESULT,
            identity=second_result.identity,
            tool_result=second_result,
        ),
    )

    full_request = dict(scripted.calls[1])
    full_messages = [
        *provider._history["run_pack"],
        {"role": "user", "content": _tool_results(second_ledger)},
    ]
    full_request["messages"] = full_messages
    packed_request = dict(full_request)
    packed_request["messages"] = [full_messages[0], *full_messages[-2:]]
    packed_request["system"] = full_request["system"] + "\n\n" + CONTEXT_PACKING_NOTICE
    provider.context_window_tokens = (
        conservative_input_token_bound(packed_request) + provider.max_tokens
    )
    assert (
        conservative_input_token_bound(full_request) + provider.max_tokens
        > provider.context_window_tokens
    )

    final = asyncio.run(
        provider.create_turn(
            run_id="run_pack",
            turn_id="turn_3",
            task="Inspect",
            ledger=second_ledger,
            tools=REVIEWED_TOOLS,
        )
    )

    assert final.text == "done"
    assert len(scripted.calls) == 3
    packed_messages = scripted.calls[2]["messages"]
    assert [message["role"] for message in packed_messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert packed_messages[1]["content"][0] == {
        "type": "redacted_thinking",
        "data": "new-redacted-reasoning",
    }
    assert packed_messages[1]["content"][1]["id"] == "toolu_2"
    assert packed_messages[2]["content"][0]["tool_use_id"] == "toolu_2"
    assert packed_messages[2]["content"][0]["content"][1]["type"] == "image"
    assert CONTEXT_PACKING_NOTICE in scripted.calls[2]["system"]
    assert "old observation" not in json.dumps(scripted.calls[2])
    assert "old reasoning" not in json.dumps(scripted.calls[2])
    assert "old-signature" not in json.dumps(scripted.calls[2])


def test_claude_mandatory_latest_group_overflow_fails_without_history_mutation() -> None:
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
    provider = AnthropicMessagesProvider(
        model="test-model",
        messages=scripted,
        max_request_bytes=100_000,
        context_window_tokens=100_000,
    )
    first = asyncio.run(
        provider.create_turn(
            run_id="run_mandatory_overflow",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    result = ToolResult(
        first.tool_calls[0].identity,
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="required latest observation " * 1_000,
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
    history_before = provider.export_continuation("run_mandatory_overflow")
    provider.context_window_tokens = 2_000

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(
            provider.create_turn(
                run_id="run_mandatory_overflow",
                turn_id="turn_2",
                task="Inspect",
                ledger=ledger,
                tools=REVIEWED_TOOLS,
            )
        )

    assert len(scripted.calls) == 1
    assert provider.export_continuation("run_mandatory_overflow") == history_before


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
        "capture_region",
        "document_text",
        "activate_window",
        "click",
        "scroll",
        "drag",
        "key",
    ]
    click_definition = next(
        tool for tool in scripted.calls[0]["tools"] if tool["name"] == "click"
    )
    assert "oneOf" not in click_definition["input_schema"]
    assert click_definition["input_schema"]["properties"] == {
        "ref": {"minLength": 1, "type": "string"},
        "x": {"type": "integer"},
        "y": {"type": "integer"},
    }
    strict_click = next(tool for tool in REVIEWED_TOOLS if tool.name == "click")
    assert "oneOf" in strict_click.input_schema


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
                    "type": "thinking",
                    "thinking": "",
                    "signature": "persisted-signature",
                },
                {
                    "type": "redacted_thinking",
                    "data": "persisted-redacted-data",
                },
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


@pytest.mark.parametrize(
    "reasoning_block",
    [
        {"type": "thinking", "thinking": "summary"},
        {"type": "thinking", "thinking": "summary", "signature": ""},
        {"type": "redacted_thinking", "data": ""},
        {"type": "redacted_thinking", "data": "opaque", "extra": "field"},
    ],
)
def test_claude_restore_rejects_malformed_reasoning_blocks(
    reasoning_block: dict[str, object],
) -> None:
    provider = AnthropicMessagesProvider(model="test-model", messages=ScriptedMessages([]))
    history = [
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": [
                reasoning_block,
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "list_windows",
                    "input": {},
                },
            ],
        },
    ]

    with pytest.raises(AnthropicProviderError, match="ANTHROPIC_CONTINUATION_INVALID"):
        provider.restore_continuation("run_reasoning", {"messages": history})
