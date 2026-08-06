from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from computer_use_agent.planner import PlannerError, build_planner_request, request_task_plan
from computer_use_agent.planning import PlanStepAction
from computer_use_agent.providers.anthropic_planner import (
    ANTHROPIC_PLANNER_SYSTEM_PROMPT,
    AnthropicPlanner,
    AnthropicPlannerError,
)


@dataclass
class ScriptedMessages:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _request(*, tools: tuple[str, ...] = ("find",)):
    return build_planner_request(
        run_id="run_1",
        plan_id="plan_1",
        task="Find the Save button",
        allowed_tools=tools,
    )


def _response(text: str, *, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=text)],
    )


def _wire_candidate(*steps: dict[str, object]) -> str:
    return json.dumps({"version": 1, "steps": list(steps)})


def test_anthropic_planner_uses_one_stateless_tool_free_structured_request() -> None:
    scripted = ScriptedMessages(
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
    planner = AnthropicPlanner(model="claude-test", messages=scripted)
    request = _request()

    plan = asyncio.run(request_task_plan(planner, request))

    assert len(scripted.calls) == 1
    call = scripted.calls[0]
    assert call["model"] == "claude-test"
    assert call["max_tokens"] == planner.output_token_reserve
    assert call["system"] == ANTHROPIC_PLANNER_SYSTEM_PROMPT
    assert "copy literal" in ANTHROPIC_PLANNER_SYSTEM_PROMPT
    assert call["messages"] == [{"role": "user", "content": request.canonical_json}]
    assert not ({"tools", "tool_choice", "thinking", "metadata"} & set(call))
    assert set(call) == {"model", "max_tokens", "system", "messages", "output_config"}
    output_config = call["output_config"]
    assert isinstance(output_config, dict)
    response_format = output_config["format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    schema = response_format["schema"]
    assert isinstance(schema, dict)
    assert "maxItems" not in schema["properties"]["steps"]
    tool_step = schema["properties"]["steps"]["items"]["anyOf"][0]
    assert tool_step["properties"]["tool"]["enum"] == ["find"]
    assert tool_step["properties"]["arguments_json"] == {"type": "string"}
    assert tool_step["required"] == ["action", "tool", "arguments_json"]
    assert tool_step["additionalProperties"] is False
    assert plan.steps[0].action is PlanStepAction.TOOL
    assert dict(plan.steps[0].arguments) == {"query": "Save"}
    assert plan.steps[1].action is PlanStepAction.FINAL_RESPONSE


def test_anthropic_planner_with_empty_tool_scope_only_exposes_final_shape() -> None:
    scripted = ScriptedMessages([_response(_wire_candidate({"action": "final_response"}))])
    planner = AnthropicPlanner(model="claude-test", messages=scripted)

    plan = asyncio.run(request_task_plan(planner, _request(tools=())))

    schema = scripted.calls[0]["output_config"]["format"]["schema"]
    variants = schema["properties"]["steps"]["items"]["anyOf"]
    assert len(variants) == 1
    assert variants[0]["properties"]["action"]["const"] == "final_response"
    assert len(plan.steps) == 1


@pytest.mark.parametrize(
    "response",
    [
        _response("refused", stop_reason="refusal"),
        _response("{}", stop_reason="max_tokens"),
        SimpleNamespace(stop_reason="tool_use", content=[]),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="tool_use", id="toolu_1", input={})],
        ),
        SimpleNamespace(stop_reason="end_turn", content=[]),
        SimpleNamespace(
            stop_reason="end_turn",
            content=[
                SimpleNamespace(type="text", text="{}"),
                SimpleNamespace(type="text", text="{}"),
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
        "refusal",
        "max-tokens",
        "tool-stop",
        "tool-use",
        "missing-content",
        "extra-content",
        "non-json",
        "non-object-args",
        "scope",
    ),
)
def test_invalid_refusal_tool_use_or_out_of_scope_response_is_fixed(response: object) -> None:
    scripted = ScriptedMessages([response])
    planner = AnthropicPlanner(model="claude-test", messages=scripted)

    with pytest.raises(AnthropicPlannerError, match="ANTHROPIC_PLANNER_RESPONSE_INVALID"):
        asyncio.run(planner.create_candidate(_request()))

    assert len(scripted.calls) == 1


def test_exact_tool_argument_contract_is_still_enforced_by_host_compiler() -> None:
    secret = "not part of the reviewed schema"
    scripted = ScriptedMessages(
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
    planner = AnthropicPlanner(model="claude-test", messages=scripted)

    with pytest.raises(PlannerError, match="PLANNER_CANDIDATE_INVALID") as captured:
        asyncio.run(request_task_plan(planner, _request()))

    assert secret not in str(captured.value)
    assert len(scripted.calls) == 1


def test_oversized_provider_output_fails_after_one_call() -> None:
    scripted = ScriptedMessages([_response("x" * (64 * 1024 + 1))])
    planner = AnthropicPlanner(model="claude-test", messages=scripted)

    with pytest.raises(AnthropicPlannerError, match="ANTHROPIC_PLANNER_RESPONSE_TOO_LARGE"):
        asyncio.run(planner.create_candidate(_request()))

    assert len(scripted.calls) == 1


def test_byte_and_token_preflight_fail_before_network() -> None:
    byte_scripted = ScriptedMessages([])
    byte_planner = AnthropicPlanner(
        model="claude-test", messages=byte_scripted, max_request_bytes=1
    )
    with pytest.raises(AnthropicPlannerError, match="REQUEST_TOO_LARGE"):
        asyncio.run(byte_planner.create_candidate(_request()))
    assert byte_scripted.calls == []

    token_scripted = ScriptedMessages([])
    token_planner = AnthropicPlanner(
        model="claude-test",
        messages=token_scripted,
        context_window_tokens=100,
        output_token_reserve=50,
    )
    with pytest.raises(AnthropicPlannerError, match="TOKEN_WINDOW_EXCEEDED"):
        asyncio.run(token_planner.create_candidate(_request()))
    assert token_scripted.calls == []


def test_provider_failure_is_fixed_never_retried_and_cancellation_propagates() -> None:
    secret = "provider echoed private task"
    scripted = ScriptedMessages(
        [RuntimeError(secret), _response(_wire_candidate({"action": "final_response"}))]
    )
    planner = AnthropicPlanner(model="claude-test", messages=scripted)

    with pytest.raises(AnthropicPlannerError, match="ANTHROPIC_PLANNER_REQUEST_FAILED") as captured:
        asyncio.run(planner.create_candidate(_request()))
    assert secret not in str(captured.value)
    assert len(scripted.calls) == 1
    assert len(scripted.responses) == 1

    cancelled = ScriptedMessages([asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            AnthropicPlanner(model="claude-test", messages=cancelled).create_candidate(_request())
        )
    assert len(cancelled.calls) == 1
