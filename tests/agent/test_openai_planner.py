from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

import computer_use_agent.providers.openai_planner as openai_planner_module
from computer_use_agent.planner import (
    PlannerError,
    build_planner_request,
    request_task_plan,
)
from computer_use_agent.planning import PlanStepAction
from computer_use_agent.provider_catalog import StructuredOutputMode
from computer_use_agent.providers.openai_planner import (
    OPENAI_PLANNER_INSTRUCTIONS,
    OpenAIPlanner,
    OpenAIPlannerError,
)


@dataclass
class ScriptedResponses:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_environment_constructor_uses_the_effective_route_for_fence_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = SimpleNamespace(responses=ScriptedResponses([]))
    monkeypatch.setattr(
        openai_planner_module,
        "openai_client_from_environment",
        lambda *_args, **_kwargs: client,
    )

    planner = OpenAIPlanner.from_environment(
        "qwen3.7-plus",
        provider_name="qwen",
        base_url=(
            "https://ws1.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
        ),
    )

    assert planner.strip_exact_json_fence is False


def _request(*, tools: tuple[str, ...] = ("find",)):
    return build_planner_request(
        run_id="run_1",
        plan_id="plan_1",
        task="Find the Save button",
        allowed_tools=tools,
    )


def _response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="completed",
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[SimpleNamespace(type="output_text", text=text)],
            )
        ],
    )


def _reasoning_response(text: str) -> SimpleNamespace:
    response = _response(text)
    response.output.insert(0, SimpleNamespace(type="reasoning", summary=[]))
    return response


def _wire_candidate(*steps: dict[str, object]) -> str:
    return json.dumps({"version": 1, "steps": list(steps)})


def test_openai_planner_uses_one_stateless_tool_free_structured_request() -> None:
    scripted = ScriptedResponses(
        [
            _response(
                _wire_candidate(
                    {
                        "action": "tool",
                        "tool": "find",
                        "arguments_json": '{"query":"Save"}',
                    },
                    {"action": "final_response"},
                )
            )
        ]
    )
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)
    request = _request()

    plan = asyncio.run(request_task_plan(planner, request))

    assert len(scripted.calls) == 1
    call = scripted.calls[0]
    assert call["model"] == "gpt-test"
    assert call["instructions"] == OPENAI_PLANNER_INSTRUCTIONS
    assert "copy literal" in OPENAI_PLANNER_INSTRUCTIONS
    assert call["input"] == request.canonical_json
    assert call["store"] is False
    assert call["max_output_tokens"] == planner.output_token_reserve
    assert not ({"tools", "parallel_tool_calls", "previous_response_id", "include"} & set(call))
    text = call["text"]
    assert isinstance(text, dict)
    response_format = text["format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    schema = response_format["schema"]
    assert isinstance(schema, dict)
    tool_step = schema["properties"]["steps"]["items"]["anyOf"][0]
    assert tool_step["properties"]["tool"]["enum"] == ["find"]
    assert tool_step["required"] == ["action", "tool", "arguments_json"]
    assert tool_step["additionalProperties"] is False
    assert plan.steps[0].action is PlanStepAction.TOOL
    assert dict(plan.steps[0].arguments) == {"query": "Save"}
    assert plan.steps[1].action is PlanStepAction.FINAL_RESPONSE


def test_openai_planner_with_empty_tool_scope_can_only_emit_final_response_shape() -> None:
    scripted = ScriptedResponses(
        [_response(_wire_candidate({"action": "final_response"}))]
    )
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)

    plan = asyncio.run(request_task_plan(planner, _request(tools=())))

    schema = scripted.calls[0]["text"]["format"]["schema"]
    variants = schema["properties"]["steps"]["items"]["anyOf"]
    assert variants == [
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "const": "final_response"}
            },
            "required": ["action"],
            "additionalProperties": False,
        }
    ]
    assert len(plan.steps) == 1


def test_known_reasoning_item_is_ignored_and_never_enters_candidate() -> None:
    secret = "untrusted hidden reasoning"
    scripted = ScriptedResponses(
        [_reasoning_response(_wire_candidate({"action": "final_response"}))]
    )
    scripted.responses[0].output[0].summary = [secret]
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)

    candidate = asyncio.run(planner.create_candidate(_request(tools=())))

    assert secret not in candidate
    assert json.loads(candidate) == {
        "version": 1,
        "steps": [{"action": "final_response"}],
    }


def test_exact_scoped_json_fence_is_removed_before_unchanged_host_compilation() -> None:
    candidate = _wire_candidate(
        {
            "action": "tool",
            "tool": "find",
            "arguments_json": '{"query":"Save"}',
        },
        {"action": "final_response"},
    )
    scripted = ScriptedResponses([_reasoning_response(f"```json\n{candidate}\n```")])
    planner = OpenAIPlanner(
        model="qwen3.7-plus",
        responses=scripted,
        name="qwen",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
        store_response=False,
        strip_exact_json_fence=True,
    )

    plan = asyncio.run(request_task_plan(planner, _request()))

    assert plan.steps[0].action is PlanStepAction.TOOL
    assert dict(plan.steps[0].arguments) == {"query": "Save"}
    assert plan.steps[1].action is PlanStepAction.FINAL_RESPONSE
    assert len(scripted.calls) == 1


@pytest.mark.parametrize(
    "wrapped",
    (
        "```json\n{candidate}\n```\n",
        " ```json\n{candidate}\n```",
        "```JSON\n{candidate}\n```",
        "```json\n```json\n{candidate}\n```\n```",
        "before\n```json\n{candidate}\n```",
    ),
)
def test_scoped_json_fence_normalization_rejects_every_nonexact_wrapper(
    wrapped: str,
) -> None:
    candidate = _wire_candidate({"action": "final_response"})
    scripted = ScriptedResponses([_response(wrapped.format(candidate=candidate))])
    planner = OpenAIPlanner(
        model="qwen3.7-plus",
        responses=scripted,
        name="qwen",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
        store_response=False,
        strip_exact_json_fence=True,
    )

    with pytest.raises(OpenAIPlannerError, match="OPENAI_PLANNER_RESPONSE_INVALID"):
        asyncio.run(planner.create_candidate(_request(tools=())))


def test_exact_json_fence_remains_invalid_without_the_scoped_normalization() -> None:
    candidate = _wire_candidate({"action": "final_response"})
    scripted = ScriptedResponses([_response(f"```json\n{candidate}\n```")])
    planner = OpenAIPlanner(
        model="qwen3.7-plus",
        responses=scripted,
        name="qwen",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
        store_response=False,
    )

    with pytest.raises(OpenAIPlannerError, match="OPENAI_PLANNER_RESPONSE_INVALID"):
        asyncio.run(planner.create_candidate(_request(tools=())))


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(status="incomplete", output=[]),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="refusal", refusal="private")],
                )
            ],
        ),
        SimpleNamespace(status="completed", output=[]),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(type="function_call", name="find", arguments="{}"),
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="output_text", text="{}")],
                ),
            ],
        ),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="output_text", text="{}")],
                ),
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[SimpleNamespace(type="output_text", text="{}")],
                ),
            ],
        ),
        SimpleNamespace(
            status="completed",
            output=[
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[
                        SimpleNamespace(type="output_text", text="{}"),
                        SimpleNamespace(type="output_text", text="{}"),
                    ],
                )
            ],
        ),
        _response("not json"),
        _response(
            _wire_candidate(
                {"action": "tool", "tool": "find", "arguments_json": "[]"},
                {"action": "final_response"},
            )
        ),
        _response(
            _wire_candidate(
                {"action": "tool", "tool": "click", "arguments_json": "{}"},
                {"action": "final_response"},
            )
        ),
    ],
    ids=(
        "incomplete",
        "refusal",
        "missing-output",
        "function-call-output",
        "extra-output",
        "extra-content",
        "non-json",
        "non-object-args",
        "scope",
    ),
)
def test_invalid_refusal_or_out_of_scope_response_is_fixed(response: object) -> None:
    scripted = ScriptedResponses([response])
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)

    with pytest.raises(OpenAIPlannerError, match="OPENAI_PLANNER_RESPONSE_INVALID"):
        asyncio.run(planner.create_candidate(_request()))

    assert len(scripted.calls) == 1


def test_exact_tool_argument_contract_is_still_enforced_by_host_compiler() -> None:
    secret = "not part of the reviewed schema"
    scripted = ScriptedResponses(
        [
            _response(
                _wire_candidate(
                    {
                        "action": "tool",
                        "tool": "find",
                        "arguments_json": json.dumps({"query": "Save", "secret": secret}),
                    },
                    {"action": "final_response"},
                )
            )
        ]
    )
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)

    with pytest.raises(PlannerError, match="PLANNER_CANDIDATE_INVALID") as captured:
        asyncio.run(request_task_plan(planner, _request()))

    assert secret not in str(captured.value)
    assert len(scripted.calls) == 1


def test_oversized_provider_output_fails_after_one_call() -> None:
    scripted = ScriptedResponses([_response("x" * (64 * 1024 + 1))])
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)

    with pytest.raises(OpenAIPlannerError, match="OPENAI_PLANNER_RESPONSE_TOO_LARGE"):
        asyncio.run(planner.create_candidate(_request()))

    assert len(scripted.calls) == 1


def test_scoped_fence_normalization_preserves_the_original_byte_limit() -> None:
    scripted = ScriptedResponses([_response(f"```json\n{'x' * (64 * 1024)}\n```")])
    planner = OpenAIPlanner(
        model="qwen3.7-plus",
        responses=scripted,
        name="qwen",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
        store_response=False,
        strip_exact_json_fence=True,
    )

    with pytest.raises(OpenAIPlannerError, match="OPENAI_PLANNER_RESPONSE_TOO_LARGE"):
        asyncio.run(planner.create_candidate(_request()))

    assert len(scripted.calls) == 1


def test_byte_and_token_preflight_fail_before_network() -> None:
    byte_scripted = ScriptedResponses([])
    byte_planner = OpenAIPlanner(
        model="gpt-test", responses=byte_scripted, max_request_bytes=1
    )
    with pytest.raises(OpenAIPlannerError, match="REQUEST_TOO_LARGE"):
        asyncio.run(byte_planner.create_candidate(_request()))
    assert byte_scripted.calls == []

    token_scripted = ScriptedResponses([])
    token_planner = OpenAIPlanner(
        model="gpt-test",
        responses=token_scripted,
        context_window_tokens=100,
        output_token_reserve=50,
    )
    with pytest.raises(OpenAIPlannerError, match="TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(token_planner.create_candidate(_request()))
    assert token_scripted.calls == []


def test_provider_failure_is_fixed_never_retried_and_cancellation_propagates() -> None:
    secret = "provider echoed private task"
    scripted = ScriptedResponses(
        [RuntimeError(secret), _response(_wire_candidate({"action": "final_response"}))]
    )
    planner = OpenAIPlanner(model="gpt-test", responses=scripted)

    with pytest.raises(OpenAIPlannerError, match="OPENAI_PLANNER_REQUEST_FAILED") as captured:
        asyncio.run(planner.create_candidate(_request()))
    assert secret not in str(captured.value)
    assert len(scripted.calls) == 1
    assert len(scripted.responses) == 1

    cancelled = ScriptedResponses([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(OpenAIPlanner(model="gpt-test", responses=cancelled).create_candidate(_request()))
    assert len(cancelled.calls) == 1
