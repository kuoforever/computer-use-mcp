from __future__ import annotations

import asyncio
import json
from base64 import b64encode
from dataclasses import dataclass, field
from hashlib import sha256
from types import SimpleNamespace

import pytest

from computer_use_agent import final_response_wire
from computer_use_agent.executor_final import (
    FinalResponseObservation,
    FinalResponseRequest,
)
from computer_use_agent.final_response_wire import compile_final_response_wire
from computer_use_agent.providers.anthropic_final import (
    ANTHROPIC_FINAL_SYSTEM_PROMPT,
    AnthropicFinalResponseAdapter,
    AnthropicFinalResponseError,
)
from computer_use_agent.providers.openai_final import (
    OPENAI_FINAL_INSTRUCTIONS,
    OpenAIFinalResponseAdapter,
    OpenAIFinalResponseError,
)
from computer_use_agent.types import ImageContent


TASK = "Describe the visible status"
OBSERVATION = "untrusted desktop text"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + b"\x00\x00\x00\x01\x00\x00\x00\x01"


@dataclass
class ScriptedPort:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _request() -> FinalResponseRequest:
    image = ImageContent("image/png", PNG, 1, 1)
    observations = (
        FinalResponseObservation(
            step_id="step_1",
            tool_name="screenshot",
            arguments_json="{}",
            sanitized_text=OBSERVATION,
            images=(image,),
        ),
    )
    material = {
        "version": 1,
        "run_id": "run_1",
        "plan_id": "plan_1",
        "plan_digest": "a" * 64,
        "snapshot_sequence": 2,
        "turn_id": "executor_final_1",
        "task": TASK,
        "observations": [
            {
                "step_id": "step_1",
                "tool_name": "screenshot",
                "arguments": {},
                "sanitized_text": OBSERVATION,
                "images": [
                    {
                        "mime_type": "image/png",
                        "data": b64encode(PNG).decode("ascii"),
                        "width": 1,
                        "height": 1,
                    }
                ],
            }
        ],
    }
    digest = sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
            "utf-8"
        )
    ).hexdigest()
    return FinalResponseRequest(
        run_id="run_1",
        plan_id="plan_1",
        plan_digest="a" * 64,
        snapshot_sequence=2,
        turn_id="executor_final_1",
        task=TASK,
        observations=observations,
        request_digest=digest,
    )


def _openai_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_1",
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ],
        usage=SimpleNamespace(input_tokens=11, output_tokens=7),
    )


def _anthropic_response(text: str, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        id="msg_1",
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=13, output_tokens=5),
    )


def test_shared_wire_is_canonical_lossless_and_safely_represented() -> None:
    request = _request()
    wire = compile_final_response_wire(request)
    manifest = json.loads(wire.manifest_json)

    assert manifest["task"] == TASK
    assert manifest["request_digest"] == request.request_digest
    assert manifest["observations"][0]["sanitized_text"] == OBSERVATION
    descriptor = manifest["observations"][0]["images"][0]
    assert descriptor == {
        "image_index": 0,
        "mime_type": "image/png",
        "sha256": sha256(PNG).hexdigest(),
        "width": 1,
        "height": 1,
    }
    assert wire.images[0].data == PNG
    assert TASK not in repr(wire)
    assert OBSERVATION not in repr(wire)


def test_openai_final_uses_one_stateless_native_image_request() -> None:
    scripted = ScriptedPort([_openai_response("final answer")])
    adapter = OpenAIFinalResponseAdapter(model="gpt-test", responses=scripted)

    result = asyncio.run(adapter.create_final_response(_request()))

    assert result.text == "final answer"
    assert result.provider_response_id == "resp_1"
    assert result.usage.input_tokens == 11
    assert "final answer" not in repr(result)
    assert len(scripted.calls) == 1
    call = scripted.calls[0]
    assert set(call) == {"model", "instructions", "input", "max_output_tokens", "store"}
    assert call["instructions"] == OPENAI_FINAL_INSTRUCTIONS
    assert call["store"] is False
    assert not (
        {"tools", "parallel_tool_calls", "previous_response_id", "include", "text"}
        & set(call)
    )
    content = call["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert json.loads(content[0]["text"])["task"] == TASK
    assert content[1] == {
        "type": "input_image",
        "image_url": "data:image/png;base64," + b64encode(PNG).decode("ascii"),
        "detail": "auto",
    }


def test_anthropic_final_uses_one_stateless_native_image_request() -> None:
    scripted = ScriptedPort([_anthropic_response("final answer")])
    adapter = AnthropicFinalResponseAdapter(model="claude-test", messages=scripted)

    result = asyncio.run(adapter.create_final_response(_request()))

    assert result.text == "final answer"
    assert result.provider_response_id == "msg_1"
    assert result.usage.output_tokens == 5
    assert "final answer" not in repr(result)
    assert len(scripted.calls) == 1
    call = scripted.calls[0]
    assert set(call) == {"model", "max_tokens", "system", "messages"}
    assert call["system"] == ANTHROPIC_FINAL_SYSTEM_PROMPT
    assert not ({"tools", "tool_choice", "thinking", "metadata", "output_config"} & set(call))
    content = call["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert json.loads(content[0]["text"])["task"] == TASK
    assert content[1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": b64encode(PNG).decode("ascii"),
        },
    }


def test_anthropic_final_validates_then_discards_reasoning_before_text() -> None:
    response = _anthropic_response("final answer")
    response.content = [
        SimpleNamespace(
            type="thinking",
            thinking="private final reasoning",
            signature="signed-final-reasoning",
        ),
        SimpleNamespace(type="text", text="final answer", citations=None),
    ]
    scripted = ScriptedPort([response])
    adapter = AnthropicFinalResponseAdapter(model="minimax-test", messages=scripted)

    result = asyncio.run(adapter.create_final_response(_request()))

    assert result.text == "final answer"
    assert "private final reasoning" not in repr(result)
    assert "signed-final-reasoning" not in repr(result)


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="incomplete", output=[]),
        SimpleNamespace(status="completed", output=[]),
        SimpleNamespace(
            status="completed",
            output=[SimpleNamespace(type="function_call", name="click")],
        ),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(type="message", role="assistant", content=[]),
                SimpleNamespace(type="message", role="assistant", content=[]),
            ],
        ),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="refusal", refusal="no")],
                )
            ],
        ),
        _openai_response(""),
        SimpleNamespace(
            id="",
            status="completed",
            output=_openai_response("text").output,
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ),
        SimpleNamespace(
            id="resp_bad_usage",
            status="completed",
            output=_openai_response("text").output,
            usage=SimpleNamespace(input_tokens=-1, output_tokens=1),
        ),
    ],
)
def test_openai_invalid_refusal_or_tool_output_is_fixed(response: object) -> None:
    scripted = ScriptedPort([response])
    with pytest.raises(OpenAIFinalResponseError, match="OPENAI_FINAL_RESPONSE_INVALID"):
        asyncio.run(
            OpenAIFinalResponseAdapter(
                model="gpt-test", responses=scripted
            ).create_final_response(_request())
        )
    assert len(scripted.calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        _anthropic_response("no", stop_reason="refusal"),
        _anthropic_response("no", stop_reason="max_tokens"),
        SimpleNamespace(stop_reason="tool_use", content=[]),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="tool_use", id="tool_1")],
        ),
        SimpleNamespace(stop_reason="end_turn", content=[]),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="text", text="one"),
                SimpleNamespace(type="text", text="two"),
            ],
        ),
        SimpleNamespace(
            id="msg_reasoning_after_text",
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="text", text="one"),
                SimpleNamespace(
                    type="thinking", thinking="late", signature="signed-reasoning"
                ),
            ],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ),
        SimpleNamespace(
            id="msg_invalid_reasoning",
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="thinking", thinking="unsigned", signature=""),
                SimpleNamespace(type="text", text="one"),
            ],
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ),
        _anthropic_response(""),
        SimpleNamespace(
            id="",
            stop_reason="end_turn",
            content=_anthropic_response("text").content,
            usage=SimpleNamespace(input_tokens=1, output_tokens=1),
        ),
        SimpleNamespace(
            id="msg_bad_usage",
            stop_reason="end_turn",
            content=_anthropic_response("text").content,
            usage=SimpleNamespace(input_tokens=1, output_tokens=-1),
        ),
    ],
)
def test_anthropic_invalid_refusal_or_tool_output_is_fixed(response: object) -> None:
    scripted = ScriptedPort([response])
    with pytest.raises(AnthropicFinalResponseError, match="ANTHROPIC_FINAL_RESPONSE_INVALID"):
        asyncio.run(
            AnthropicFinalResponseAdapter(
                model="claude-test", messages=scripted
            ).create_final_response(_request())
        )
    assert len(scripted.calls) == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_byte_and_token_preflight_fail_before_provider_io(provider: str) -> None:
    scripted = ScriptedPort([])
    if provider == "openai":
        adapter = OpenAIFinalResponseAdapter(
            model="gpt-test", responses=scripted, max_request_bytes=1
        )
        error = OpenAIFinalResponseError
    else:
        adapter = AnthropicFinalResponseAdapter(
            model="claude-test", messages=scripted, max_request_bytes=1
        )
        error = AnthropicFinalResponseError
    with pytest.raises(error, match="REQUEST_TOO_LARGE"):
        asyncio.run(adapter.create_final_response(_request()))
    assert scripted.calls == []

    if provider == "openai":
        adapter = OpenAIFinalResponseAdapter(
            model="gpt-test",
            responses=scripted,
            context_window_tokens=100,
            output_token_reserve=50,
        )
    else:
        adapter = AnthropicFinalResponseAdapter(
            model="claude-test",
            messages=scripted,
            context_window_tokens=100,
            output_token_reserve=50,
        )
    with pytest.raises(error, match="TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(adapter.create_final_response(_request()))
    assert scripted.calls == []


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_provider_failure_is_fixed_never_retried_and_cancellation_propagates(
    provider: str,
) -> None:
    secret = "provider echoed private observation"
    success = _openai_response("later") if provider == "openai" else _anthropic_response("later")
    scripted = ScriptedPort([RuntimeError(secret), success])
    if provider == "openai":
        adapter = OpenAIFinalResponseAdapter(model="gpt-test", responses=scripted)
        error = OpenAIFinalResponseError
    else:
        adapter = AnthropicFinalResponseAdapter(model="claude-test", messages=scripted)
        error = AnthropicFinalResponseError
    with pytest.raises(error, match="REQUEST_FAILED") as captured:
        asyncio.run(adapter.create_final_response(_request()))
    assert secret not in str(captured.value)
    assert len(scripted.calls) == 1
    assert len(scripted.responses) == 1

    cancelled = ScriptedPort([asyncio.CancelledError()])
    adapter = (
        OpenAIFinalResponseAdapter(model="gpt-test", responses=cancelled)
        if provider == "openai"
        else AnthropicFinalResponseAdapter(model="claude-test", messages=cancelled)
    )
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(adapter.create_final_response(_request()))
    assert len(cancelled.calls) == 1


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_response_text_size_is_bounded_after_one_call(
    provider: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(final_response_wire, "MAX_FINAL_RESPONSE_TEXT_BYTES", 1)
    response = _openai_response("too long") if provider == "openai" else _anthropic_response("too long")
    scripted = ScriptedPort([response])
    adapter = (
        OpenAIFinalResponseAdapter(model="gpt-test", responses=scripted)
        if provider == "openai"
        else AnthropicFinalResponseAdapter(model="claude-test", messages=scripted)
    )
    error = OpenAIFinalResponseError if provider == "openai" else AnthropicFinalResponseError
    with pytest.raises(error, match="RESPONSE_TOO_LARGE"):
        asyncio.run(adapter.create_final_response(_request()))
    assert len(scripted.calls) == 1
