from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from computer_use_agent.planner import build_planner_request, request_task_plan
from computer_use_agent.provider_catalog import StructuredOutputMode
from computer_use_agent.providers.anthropic import AnthropicMessagesProvider
from computer_use_agent.providers.anthropic_planner import AnthropicPlanner
from computer_use_agent.providers.openai import OpenAIResponsesProvider
from computer_use_agent.providers.openai_planner import OpenAIPlanner
from computer_use_agent.tool_registry import REVIEWED_TOOLS


@dataclass
class ScriptedPort:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _plan_wire() -> str:
    return json.dumps({"version": 1, "steps": [{"action": "final_response"}]})


def _planner_request():
    return build_planner_request(
        run_id="run_1",
        plan_id="plan_1",
        task="Inspect",
        allowed_tools=(),
    )


def test_qwen_responses_profile_omits_unconfirmed_openai_extensions() -> None:
    scripted = ScriptedPort(
        [
            SimpleNamespace(
                id="resp_1",
                output=[],
                output_text="done",
                usage=SimpleNamespace(input_tokens=3, output_tokens=1),
            )
        ]
    )
    provider = OpenAIResponsesProvider(
        model="qwen3.7-plus",
        responses=scripted,
        name="qwen",
        supports_images=True,
        include_responses_reasoning=False,
    )
    turn = asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    assert turn.text == "done"
    assert provider.name == "qwen"
    assert "include" not in scripted.calls[0]


def test_qwen_planner_prompt_only_mode_discloses_schema_without_store_or_text_format() -> None:
    scripted = ScriptedPort(
        [
            SimpleNamespace(
                status="completed",
                output=[
                    SimpleNamespace(
                        type="message",
                        role="assistant",
                        content=[SimpleNamespace(type="output_text", text=_plan_wire())],
                    )
                ],
            )
        ]
    )
    planner = OpenAIPlanner(
        model="qwen3.7-plus",
        responses=scripted,
        name="qwen",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
        store_response=False,
    )
    request_task_plan_result = asyncio.run(
        request_task_plan(planner, _planner_request())
    )
    assert len(request_task_plan_result.steps) == 1
    call = scripted.calls[0]
    assert "text" not in call
    assert "store" not in call
    assert "Required output JSON Schema" in call["instructions"]


def test_minimax_messages_profile_withdraws_images_and_uses_prompt_only_planner() -> None:
    ordinary_port = ScriptedPort(
        [
            SimpleNamespace(
                id="msg_1",
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text="done")],
                usage=SimpleNamespace(input_tokens=3, output_tokens=1),
            )
        ]
    )
    provider = AnthropicMessagesProvider(
        model="MiniMax-M2.7",
        messages=ordinary_port,
        name="minimax",
        supports_images=False,
    )
    asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="Inspect text",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    names = {item["name"] for item in ordinary_port.calls[0]["tools"]}
    assert "screenshot" not in names
    assert "capture_region" not in names

    planner_port = ScriptedPort(
        [
            SimpleNamespace(
                stop_reason="end_turn",
                content=[SimpleNamespace(type="text", text=_plan_wire())],
            )
        ]
    )
    planner = AnthropicPlanner(
        model="MiniMax-M2.7",
        messages=planner_port,
        name="minimax",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
    )
    asyncio.run(request_task_plan(planner, _planner_request()))
    call = planner_port.calls[0]
    assert "output_config" not in call
    assert "Required output JSON Schema" in call["system"]
