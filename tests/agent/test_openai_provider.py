from __future__ import annotations

import asyncio
import base64
import json
from hashlib import sha256
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.providers.openai import (
    MEMORY_RULE,
    OpenAIProviderError,
    OpenAIResponsesProvider,
    _instructions,
    _request_contract_digest,
    _tool_definitions,
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
    ProviderContinuationStrategy,
    SafeArgumentSummary,
    StatelessReplayBlocker,
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


@dataclass
class DumpedOutputItem:
    payload: dict[str, object]

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return self.payload


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


def _continuation_state(
    provider: OpenAIResponsesProvider,
    *,
    response_id: str = "response_1",
    prior_context_tokens: int = 14,
    memory_context_used: bool = False,
    initial_input: str = "Inspect",
    output_items: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    tools = _tool_definitions(REVIEWED_TOOLS, allow_actions=provider.allow_actions)
    instructions = _instructions(
        allow_actions=provider.allow_actions,
        memory_context_used=memory_context_used,
    )
    return {
        "response_id": response_id,
        "prior_context_tokens": prior_context_tokens,
        "request_contract_digest": _request_contract_digest(
            model=provider.model,
            instructions=instructions,
            tools=tools,
            allow_actions=provider.allow_actions,
            memory_context_used=memory_context_used,
            initial_input_digest=sha256(initial_input.encode("utf-8")).hexdigest(),
            max_request_bytes=provider.max_request_bytes,
            context_window_tokens=provider.context_window_tokens,
            output_token_reserve=provider.output_token_reserve,
        ),
        "memory_context_used": memory_context_used,
        "initial_input": initial_input,
        "output_batches": [
            {"response_id": response_id, "items": output_items or []}
        ],
    }


def test_openai_function_call_and_matching_output_continuation() -> None:
    scripted = ScriptedResponses(
        [
            _response(
                "response_1",
                output=[
                    DumpedOutputItem(
                        {
                            "type": "reasoning",
                            "id": "reasoning_1",
                            "content": [],
                            "summary": [],
                        }
                    ),
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
    assert provider.export_continuation("run_1")["output_batches"] == [
        {
            "response_id": "response_1",
            "items": [
                {
                    "type": "reasoning",
                    "id": "reasoning_1",
                    "content": [],
                    "summary": [],
                },
                {
                    "type": "function_call",
                    "name": "list_windows",
                    "call_id": "call_1",
                    "arguments": "{}",
                },
            ],
        },
        {"response_id": "response_2", "items": []},
    ]


def test_openai_declares_remote_chain_and_stateless_replay_blockers() -> None:
    scripted = ScriptedResponses([])
    provider = OpenAIResponsesProvider(model="test-model", responses=scripted)
    state_before = provider.export_continuation("run_readiness")

    readiness = provider.stateless_replay_readiness()

    assert provider.continuation_strategy is (
        ProviderContinuationStrategy.REMOTE_RESPONSE_ID
    )
    assert readiness.eligible is False
    assert readiness.blockers == (
        StatelessReplayBlocker.REPLAY_COMPILER_NOT_IMPLEMENTED,
    )
    assert provider.export_continuation("run_readiness") == state_before
    assert scripted.calls == []


@pytest.mark.parametrize(
    ("output", "error"),
    [
        ([SimpleNamespace(type="reasoning", content=[object()])], "OPENAI_RESPONSE_INVALID"),
        (
            [
                SimpleNamespace(
                    type="reasoning",
                    encrypted_content="x" * 10_000,
                )
            ],
            "OPENAI_RESPONSE_OUTPUT_TOO_LARGE",
        ),
    ],
)
def test_openai_output_item_persistence_is_bounded_and_atomic(
    output: list[object], error: str
) -> None:
    scripted = ScriptedResponses([_response("response_1", output=output)])
    provider = OpenAIResponsesProvider(
        model="test-model", responses=scripted, max_request_bytes=4_000
    )

    with pytest.raises(OpenAIProviderError, match=error):
        asyncio.run(
            provider.create_turn(
                run_id="run_output",
                turn_id="turn_1",
                task="Inspect",
                ledger=(),
                tools=REVIEWED_TOOLS,
            )
        )

    assert len(scripted.calls) == 1
    assert provider.export_continuation("run_output")["response_id"] is None
    assert provider.export_continuation("run_output")["output_batches"] == []


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


def test_openai_request_budget_fails_before_initial_or_continuation_network_call() -> None:
    initial = ScriptedResponses([_response("unused")])
    provider = OpenAIResponsesProvider(
        model="test-model", responses=initial, max_request_bytes=1024
    )

    with pytest.raises(OpenAIProviderError, match="OPENAI_REQUEST_TOO_LARGE"):
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
            _response("unused"),
        ]
    )
    provider = OpenAIResponsesProvider(
        model="test-model", responses=scripted, max_request_bytes=2_000
    )
    first = asyncio.run(
        provider.create_turn(
            run_id="run_continuation",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
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

    with pytest.raises(OpenAIProviderError, match="OPENAI_REQUEST_TOO_LARGE"):
        asyncio.run(
            provider.create_turn(
                run_id="run_continuation",
                turn_id="turn_2",
                task="Inspect",
                ledger=ledger,
                tools=REVIEWED_TOOLS,
            )
        )
    assert len(scripted.calls) == 1


def test_openai_token_window_fails_before_network_and_reserves_output() -> None:
    scripted = ScriptedResponses([_response("unused")])
    provider = OpenAIResponsesProvider(
        model="test-model",
        responses=scripted,
        max_request_bytes=100_000,
        context_window_tokens=2_000,
        output_token_reserve=256,
    )

    with pytest.raises(OpenAIProviderError, match="OPENAI_TOKEN_WINDOW_EXCEEDED"):
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


def test_openai_token_window_keeps_remote_context_and_image_result_atomic() -> None:
    scripted = ScriptedResponses(
        [
            _response(
                "response_1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="screenshot",
                        call_id="call_1",
                        arguments="{}",
                    )
                ],
            ),
            _response("unused"),
        ]
    )
    provider = OpenAIResponsesProvider(
        model="test-model",
        responses=scripted,
        max_request_bytes=100_000,
        context_window_tokens=2_000,
        output_token_reserve=256,
    )
    first = asyncio.run(
        provider.create_turn(
            run_id="run_atomic_window",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    assert provider._prior_context_tokens["run_atomic_window"] == 14

    result = ToolResult(
        identity=first.tool_calls[0].identity,
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(ImageContent("image/png", base64.b64decode(_PNG_BASE64), 1, 1),),
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

    with pytest.raises(OpenAIProviderError, match="OPENAI_TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(
            provider.create_turn(
                run_id="run_atomic_window",
                turn_id="turn_2",
                task="Inspect",
                ledger=ledger,
                tools=REVIEWED_TOOLS,
            )
        )

    assert len(scripted.calls) == 1


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
    assert provider.export_continuation("run_memory")["initial_input"] == (
        scripted.calls[0]["input"]
    )


def test_openai_restored_memory_marker_preserves_rule_without_replaying_content() -> None:
    scripted = ScriptedResponses([_response("response_2", text="done")])
    provider = OpenAIResponsesProvider(model="test-model", responses=scripted)
    provider.restore_continuation(
        "run_memory_restore",
        _continuation_state(provider, memory_context_used=True),
    )
    identity = CallIdentity("run_memory_restore", "turn_1", "call_1")
    result = ToolResult(
        identity,
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )

    asyncio.run(
        provider.create_turn(
            run_id="run_memory_restore",
            turn_id="turn_2",
            task="ORIGINAL_TASK_MUST_NOT_BE_SENT",
            ledger=(
                LedgerEvent("event_1", LedgerEventKind.MODEL_TURN),
                LedgerEvent(
                    "event_2",
                    LedgerEventKind.TOOL_RESULT,
                    identity=identity,
                    tool_result=result,
                ),
            ),
            tools=REVIEWED_TOOLS,
        )
    )

    request = scripted.calls[0]
    assert MEMORY_RULE in request["instructions"]
    assert "ORIGINAL_TASK_MUST_NOT_BE_SENT" not in json.dumps(request)
    assert "Optional memory context" not in json.dumps(request)
    assert provider.export_continuation("run_memory_restore")[
        "memory_context_used"
    ] is True
    assert provider.export_continuation("run_memory_restore")["initial_input"] == (
        "Inspect"
    )


def test_openai_active_chain_rejects_tool_contract_drift_before_network() -> None:
    scripted = ScriptedResponses([_response("response_1", text="done")])
    provider = OpenAIResponsesProvider(model="test-model", responses=scripted)
    asyncio.run(
        provider.create_turn(
            run_id="run_contract",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )

    with pytest.raises(OpenAIProviderError, match="OPENAI_REQUEST_CONTRACT_MISMATCH"):
        asyncio.run(
            provider.create_turn(
                run_id="run_contract",
                turn_id="turn_2",
                task="Inspect",
                ledger=(),
                tools=tuple(
                    tool for tool in REVIEWED_TOOLS if tool.name != "screenshot"
                ),
            )
        )

    assert len(scripted.calls) == 1


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("model", "different-model"),
        ("allow_actions", True),
        ("max_request_bytes", 2_000),
        ("context_window_tokens", 64_000),
        ("output_token_reserve", 2_048),
    ],
)
def test_openai_restore_rejects_contract_drift_before_state_or_network(
    field_name: str,
    value: object,
) -> None:
    source = OpenAIResponsesProvider(
        model="test-model", responses=ScriptedResponses([])
    )
    state = _continuation_state(source)
    scripted = ScriptedResponses([])
    target = OpenAIResponsesProvider(model="test-model", responses=scripted)
    setattr(target, field_name, value)

    with pytest.raises(OpenAIProviderError, match="OPENAI_REQUEST_CONTRACT_MISMATCH"):
        target.restore_continuation("run_contract", state)

    assert target.export_continuation("run_contract") == {
        "response_id": None,
        "prior_context_tokens": 0,
        "request_contract_digest": None,
        "memory_context_used": False,
        "initial_input": None,
        "output_batches": [],
    }
    assert scripted.calls == []


def test_openai_restore_rejects_initial_input_tampering_before_state() -> None:
    provider = OpenAIResponsesProvider(
        model="test-model", responses=ScriptedResponses([])
    )
    state = _continuation_state(provider)
    state["initial_input"] = "tampered"

    with pytest.raises(OpenAIProviderError, match="OPENAI_REQUEST_CONTRACT_MISMATCH"):
        provider.restore_continuation("run_contract", state)

    assert provider.export_continuation("run_contract")["response_id"] is None


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


def test_openai_restore_continues_previous_response_without_resending_task() -> None:
    scripted = ScriptedResponses([_response("response_2", text="done")])
    provider = OpenAIResponsesProvider(model="test-model", responses=scripted)
    provider.restore_continuation("run_restore", _continuation_state(provider))
    identity = CallIdentity("run_restore", "turn_1", "call_1")
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

    assert scripted.calls[0]["previous_response_id"] == "response_1"
    assert "ORIGINAL_TASK_MUST_NOT_BE_SENT" not in json.dumps(scripted.calls[0])
    assert provider.export_continuation("run_restore") == {
        "response_id": "response_2",
        "prior_context_tokens": 14,
        "request_contract_digest": _continuation_state(provider)[
            "request_contract_digest"
        ],
        "memory_context_used": False,
        "initial_input": "Inspect",
        "output_batches": [
            {"response_id": "response_1", "items": []},
            {"response_id": "response_2", "items": []},
        ],
    }


def test_openai_restore_preserves_remote_token_window_before_network() -> None:
    scripted = ScriptedResponses([_response("unused")])
    provider = OpenAIResponsesProvider(
        model="test-model",
        responses=scripted,
        max_request_bytes=100_000,
        context_window_tokens=2_000,
        output_token_reserve=256,
    )
    provider.restore_continuation(
        "run_restore_window",
        _continuation_state(provider, prior_context_tokens=1_900),
    )
    identity = CallIdentity("run_restore_window", "turn_1", "call_1")
    result = ToolResult(
        identity,
        "list_windows",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )

    with pytest.raises(OpenAIProviderError, match="OPENAI_TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(
            provider.create_turn(
                run_id="run_restore_window",
                turn_id="turn_2",
                task="Inspect",
                ledger=(
                    LedgerEvent("event_1", LedgerEventKind.MODEL_TURN),
                    LedgerEvent(
                        "event_2",
                        LedgerEventKind.TOOL_RESULT,
                        identity=identity,
                        tool_result=result,
                    ),
                ),
                tools=REVIEWED_TOOLS,
            )
        )

    assert scripted.calls == []


def test_openai_restore_rejects_invalid_or_repeated_attach() -> None:
    provider = OpenAIResponsesProvider(model="test-model", responses=ScriptedResponses([]))
    with pytest.raises(OpenAIProviderError, match="OPENAI_CONTINUATION_INVALID"):
        provider.restore_continuation(
            "run_1", {"response_id": None, "prior_context_tokens": 0}
        )
    with pytest.raises(OpenAIProviderError, match="OPENAI_CONTINUATION_INVALID"):
        provider.restore_continuation("run_1", {"response_id": "response_1"})
    provider.restore_continuation("run_1", _continuation_state(provider))
    with pytest.raises(OpenAIProviderError, match="OPENAI_CONTINUATION_ALREADY_ATTACHED"):
        provider.restore_continuation("run_1", _continuation_state(provider))
