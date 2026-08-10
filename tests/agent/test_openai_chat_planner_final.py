from __future__ import annotations

import asyncio
import json
from base64 import b64encode
from dataclasses import dataclass, field
from hashlib import sha256
from types import SimpleNamespace

import pytest

from computer_use_agent.executor_final import (
    FinalResponseObservation,
    FinalResponseRequest,
)
from computer_use_agent.planner import build_planner_request, request_task_plan
from computer_use_agent.planning import PlanStepAction
from computer_use_agent.provider_catalog import StructuredOutputMode
from computer_use_agent.providers.openai_chat_final import (
    OpenAIChatFinalResponseAdapter,
    OpenAIChatFinalResponseError,
)
from computer_use_agent.providers.openai_chat_planner import OpenAIChatPlanner
from computer_use_agent.types import ImageContent


PNG = (
    b"\x89PNG\r\n\x1a\n"
    + b"\x00\x00\x00\rIHDR"
    + b"\x00\x00\x00\x01\x00\x00\x00\x01"
)


@dataclass
class ScriptedCompletions:
    responses: list[object]
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _response(text: str, *, response_id: str = "chat_1") -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=text),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=9, completion_tokens=3),
    )


def _final_request(*, image: bool) -> FinalResponseRequest:
    images = (ImageContent("image/png", PNG, 1, 1),) if image else ()
    observations = (
        FinalResponseObservation(
            step_id="step_1",
            tool_name="screenshot" if image else "list_windows",
            arguments_json="{}",
            sanitized_text="visible status",
            images=images,
        ),
    )
    material = {
        "version": 1,
        "run_id": "run_1",
        "plan_id": "plan_1",
        "plan_digest": "a" * 64,
        "snapshot_sequence": 1,
        "turn_id": "executor_final_1",
        "task": "Describe status",
        "observations": [
            {
                "step_id": "step_1",
                "tool_name": "screenshot" if image else "list_windows",
                "arguments": {},
                "sanitized_text": "visible status",
                "images": [
                    {
                        "mime_type": item.mime_type,
                        "data": b64encode(item.data).decode("ascii"),
                        "width": item.width,
                        "height": item.height,
                    }
                    for item in images
                ],
            }
        ],
    }
    digest = sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return FinalResponseRequest(
        run_id="run_1",
        plan_id="plan_1",
        plan_digest="a" * 64,
        snapshot_sequence=1,
        turn_id="executor_final_1",
        task="Describe status",
        observations=observations,
        request_digest=digest,
    )


def test_chat_planner_uses_json_object_and_host_compiles_exact_plan() -> None:
    wire = json.dumps(
        {
            "version": 1,
            "steps": [
                {"action": "tool", "tool": "list_windows", "arguments_json": "{}"},
                {"action": "final_response"},
            ],
        }
    )
    scripted = ScriptedCompletions([_response(wire)])
    planner = OpenAIChatPlanner(
        model="kimi-k2.6",
        completions=scripted,
        name="kimi",
        structured_output=StructuredOutputMode.JSON_OBJECT,
        max_tokens_parameter="max_completion_tokens",
    )
    request = build_planner_request(
        run_id="run_1",
        plan_id="plan_1",
        task="List windows",
        allowed_tools=("list_windows",),
    )
    plan = asyncio.run(request_task_plan(planner, request))
    assert scripted.calls[0]["response_format"] == {"type": "json_object"}
    assert scripted.calls[0]["max_completion_tokens"] == planner.output_token_reserve
    assert plan.steps[0].action is PlanStepAction.TOOL
    assert plan.steps[1].action is PlanStepAction.FINAL_RESPONSE


def test_local_openai_planner_uses_prompt_schema_without_native_extensions() -> None:
    wire = json.dumps({"version": 1, "steps": [{"action": "final_response"}]})
    scripted = ScriptedCompletions([_response(wire)])
    planner = OpenAIChatPlanner(
        model="qwen3:8b",
        completions=scripted,
        name="local_openai",
        structured_output=StructuredOutputMode.PROMPT_ONLY,
    )
    request = build_planner_request(
        run_id="run_local",
        plan_id="plan_local",
        task="Summarize the observation",
        allowed_tools=(),
    )

    plan = asyncio.run(request_task_plan(planner, request))

    call = scripted.calls[0]
    assert "response_format" not in call
    assert "Required output JSON Schema" in call["messages"][0]["content"]
    assert len(plan.steps) == 1
    assert plan.steps[0].action is PlanStepAction.FINAL_RESPONSE


def test_kimi_final_sends_native_data_url_and_deepseek_fails_before_network() -> None:
    kimi_port = ScriptedCompletions([_response("done")])
    kimi = OpenAIChatFinalResponseAdapter(
        model="kimi-k2.6",
        completions=kimi_port,
        name="kimi",
        supports_images=True,
        max_tokens_parameter="max_completion_tokens",
    )
    result = asyncio.run(kimi.create_final_response(_final_request(image=True)))
    assert result.text == "done"
    content = kimi_port.calls[0]["messages"][1]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")

    deepseek_port = ScriptedCompletions([_response("must not be used")])
    deepseek = OpenAIChatFinalResponseAdapter(
        model="deepseek-v4-pro",
        completions=deepseek_port,
        name="deepseek",
        supports_images=False,
    )
    with pytest.raises(OpenAIChatFinalResponseError, match="IMAGES_UNSUPPORTED"):
        asyncio.run(deepseek.create_final_response(_final_request(image=True)))
    assert deepseek_port.calls == []
