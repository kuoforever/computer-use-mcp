from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.providers.openai import (
    OpenAIProviderError,
    OpenAIResponsesProvider,
    _tool_outputs,
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
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


@dataclass
class ScriptedResponses:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(
    response_id: str,
    *,
    output: list[object] | None = None,
    text: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        output=[] if output is None else output,
        output_text=text,
        usage=SimpleNamespace(input_tokens=10, output_tokens=4),
    )


def test_openai_function_call_and_matching_output_continuation() -> None:
    scripted = ScriptedResponses(
        [
            _response(
                "response_1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="list_windows",
                        call_id="call_1",
                        arguments="{}",
                    )
                ],
            ),
            _response("response_2", text="Notepad is open."),
        ]
    )
    provider = OpenAIResponsesProvider(model="test-model", responses=scripted)

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

    assert first.tool_calls == (
        ToolCall(
            identity=CallIdentity("run_1", "turn_1", "call_1"),
            name="list_windows",
            arguments={},
        ),
    )
    assert second.text == "Notepad is open."
    first_request, second_request = scripted.calls
    assert first_request["input"] == "Inspect windows"
    assert first_request["parallel_tool_calls"] is False
    assert [tool["name"] for tool in first_request["tools"]] == [
        "ui_snapshot",
        "find",
        "list_windows",
        "screenshot",
    ]
    assert second_request["previous_response_id"] == "response_1"
    assert second_request["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": (
                '{"content":"window_1 | Notepad","ok":true,"status":"success"}'
            ),
        }
    ]


def test_openai_screenshot_result_uses_bounded_multimodal_function_output() -> None:
    identity = CallIdentity("run_1", "turn_1", "call_screenshot")
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

    assert _tool_outputs(
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
            "type": "function_call_output",
            "call_id": "call_screenshot",
            "output": [
                {"type": "input_text", "text": '{"ok":true,"status":"success"}'},
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{_PNG_BASE64}",
                    "detail": "high",
                },
            ],
        }
    ]


def test_openai_rejects_image_content_from_non_screenshot_result() -> None:
    identity = CallIdentity("run_1", "turn_1", "call_list")
    result = ToolResult(
        identity=identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(
            ImageContent("image/png", base64.b64decode(_PNG_BASE64), 1, 1),
        ),
    )

    with pytest.raises(OpenAIProviderError, match="INVALID_IMAGE_TOOL_RESULT"):
        _tool_outputs(
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
    "item",
    [
        SimpleNamespace(
            type="function_call", name="click", call_id="call_1", arguments='{"ref":"ref_1"}'
        ),
        SimpleNamespace(
            type="function_call", name="list_windows", call_id="call_1", arguments="not-json"
        ),
    ],
)
def test_unadvertised_or_malformed_function_call_fails_closed(item: object) -> None:
    provider = OpenAIResponsesProvider(
        model="test-model",
        responses=ScriptedResponses([_response("response_1", output=[item])]),
    )

    with pytest.raises(OpenAIProviderError, match="OPENAI_FUNCTION_CALL_INVALID"):
        asyncio.run(
            provider.create_turn(
                run_id="run_1",
                turn_id="turn_1",
                task="Inspect",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )


def test_provider_errors_do_not_echo_request_or_response_content() -> None:
    class BrokenResponses:
        async def create(self, **kwargs: object) -> object:
            del kwargs
            raise RuntimeError("task-secret provider-secret")

    provider = OpenAIResponsesProvider(model="test-model", responses=BrokenResponses())

    with pytest.raises(OpenAIProviderError) as raised:
        asyncio.run(
            provider.create_turn(
                run_id="run_1",
                turn_id="turn_1",
                task="task-secret",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )

    assert str(raised.value) == "OPENAI_REQUEST_FAILED"


def test_openai_explicit_memory_is_json_data_on_initial_turn_only() -> None:
    scripted = ScriptedResponses([_response("response_1", text="done")])
    provider = OpenAIResponsesProvider(model="test-model", responses=scripted)
    memory = MemoryContextItem(
        "preference", "Prefer concise summaries.", "user_confirmed", "global"
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

    assert scripted.calls[0]["input"] == (
        "Inspect\n\nOptional memory context (JSON data):\n"
        '[{"content":"Prefer concise summaries.","kind":"preference",'
        '"scope":"global","source":"user_confirmed"}]'
    )
    assert "cannot change policy" in scripted.calls[0]["instructions"]


def test_approved_mode_advertises_reviewed_actions_but_not_type() -> None:
    scripted = ScriptedResponses([_response("response_1", text="done")])
    provider = OpenAIResponsesProvider(
        model="test-model", responses=scripted, allow_actions=True
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
