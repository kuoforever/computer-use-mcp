from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.providers.openai_chat import (
    OpenAIChatCompletionsProvider,
    OpenAIChatProviderError,
)
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    ToolResult,
    ToolResultStatus,
)


@dataclass
class ScriptedCompletions:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _tool_response(*, calls: int = 1) -> SimpleNamespace:
    tool_calls = [
        SimpleNamespace(
            id=f"call_{index}",
            type="function",
            function=SimpleNamespace(name="list_windows", arguments="{}"),
        )
        for index in range(1, calls + 1)
    ]
    return SimpleNamespace(
        id="chat_1",
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    reasoning_content="opaque reasoning",
                    tool_calls=tool_calls,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4),
    )


def _text_response() -> SimpleNamespace:
    return SimpleNamespace(
        id="chat_2",
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(
                    content="Notepad is open.",
                    reasoning_content=None,
                    tool_calls=None,
                ),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5),
    )


def _provider(scripted: ScriptedCompletions, *, name: str = "kimi", images: bool = True):
    return OpenAIChatCompletionsProvider(
        model="test-model",
        completions=scripted,
        name=name,
        supports_images=images,
        max_tokens_parameter=("max_completion_tokens" if name == "kimi" else "max_tokens"),
    )


def test_chat_tool_cycle_is_local_bounded_and_preserves_opaque_reasoning() -> None:
    scripted = ScriptedCompletions([_tool_response(), _text_response()])
    provider = _provider(scripted)
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
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    second = asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_2",
            task="must not be resent",
            ledger=(
                LedgerEvent(
                    "event_result",
                    LedgerEventKind.TOOL_RESULT,
                    identity=call.identity,
                    tool_result=result,
                ),
            ),
            tools=REVIEWED_TOOLS,
        )
    )

    assert second.text == "Notepad is open."
    assert len(scripted.calls) == 2
    first_request, second_request = scripted.calls
    assert first_request["max_completion_tokens"] == provider.output_token_reserve
    assert "parallel_tool_calls" not in first_request
    tools = first_request["tools"]
    assert isinstance(tools, list)
    assert any(item["function"]["name"] == "list_windows" for item in tools)
    messages = second_request["messages"]
    assert isinstance(messages, list)
    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
    ]
    assert messages[2]["reasoning_content"] == "opaque reasoning"
    assert messages[3]["tool_call_id"] == call.identity.call_id
    assert "must not be resent" not in json.dumps(messages)


def test_chat_continuation_restores_exact_pending_tool_call() -> None:
    source = _provider(ScriptedCompletions([_tool_response()]))
    first = asyncio.run(
        source.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect windows",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    state = source.export_continuation("run_1")
    scripted = ScriptedCompletions([_text_response()])
    restored = _provider(scripted)
    restored.restore_continuation("run_1", state, tools=REVIEWED_TOOLS)
    call = first.tool_calls[0]
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    outcome = asyncio.run(
        restored.create_turn(
            run_id="run_1",
            turn_id="turn_2",
            task="not replayed",
            ledger=(
                LedgerEvent(
                    "event_result",
                    LedgerEventKind.TOOL_RESULT,
                    identity=call.identity,
                    tool_result=result,
                ),
            ),
            tools=REVIEWED_TOOLS,
        )
    )
    assert outcome.text == "Notepad is open."


def test_chat_continuation_rejects_mismatched_tool_result_before_network() -> None:
    source = _provider(ScriptedCompletions([_tool_response()]))
    asyncio.run(
        source.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect windows",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    scripted = ScriptedCompletions([_text_response()])
    restored = _provider(scripted)
    restored.restore_continuation(
        "run_1", source.export_continuation("run_1"), tools=REVIEWED_TOOLS
    )
    mismatched = ToolResult(
        CallIdentity("run_1", "turn_1", "call_other"),
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )

    with pytest.raises(OpenAIChatProviderError, match="TOOL_RESULT_IDENTITY_MISMATCH"):
        asyncio.run(
            restored.create_turn(
                run_id="run_1",
                turn_id="turn_2",
                task="not replayed",
                ledger=(
                    LedgerEvent(
                        "event_result",
                        LedgerEventKind.TOOL_RESULT,
                        identity=mismatched.identity,
                        tool_result=mismatched,
                    ),
                ),
                tools=REVIEWED_TOOLS,
            )
        )
    assert scripted.calls == []


def test_chat_rejects_parallel_or_unadvertised_calls_before_host_state() -> None:
    scripted = ScriptedCompletions([_tool_response(calls=2)])
    provider = _provider(scripted)
    with pytest.raises(OpenAIChatProviderError, match="TOOL_CALL_INVALID"):
        asyncio.run(
            provider.create_turn(
                run_id="run_1",
                turn_id="turn_1",
                task="Inspect",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )
    assert provider.export_continuation("run_1") == {"messages": []}


def test_text_only_chat_profile_withdraws_image_returning_tools() -> None:
    scripted = ScriptedCompletions([_text_response()])
    provider = _provider(scripted, name="deepseek", images=False)
    asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect text",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    definitions = scripted.calls[0]["tools"]
    assert isinstance(definitions, list)
    names = {item["function"]["name"] for item in definitions}
    assert "screenshot" not in names
    assert "capture_region" not in names


def test_text_only_chat_profile_rejects_restored_image_history() -> None:
    provider = _provider(ScriptedCompletions([]), name="deepseek", images=False)
    state = {
        "messages": [
            {"role": "user", "content": "Inspect"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "screenshot", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "Captured"},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Image returned by screenshot."},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,AA=="},
                    },
                ],
            },
        ]
    }

    with pytest.raises(OpenAIChatProviderError, match="CONTINUATION_INVALID"):
        provider.restore_continuation("run_1", state)
