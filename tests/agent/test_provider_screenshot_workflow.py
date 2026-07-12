from __future__ import annotations

import asyncio
import base64
import json
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from computer_use_agent.config import AgentConfig, MCPLaunchConfig, PolicyConfig, ProviderConfig
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP
from computer_use_agent.providers.anthropic import AnthropicMessagesProvider
from computer_use_agent.providers.openai import OpenAIResponsesProvider
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ModelProviderPort,
    ToolResult,
    ToolResultStatus,
)


_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class ScriptedResponses:
    def __init__(self, responses: list[object]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.responses.popleft()


class ScriptedMessages:
    def __init__(self, responses: list[object]) -> None:
        self.responses = deque(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        return self.responses.popleft()


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / provider,
        policy_version="readonly-v1",
        provider=ProviderConfig(name=provider, model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(),
    )


def _screenshot_result(run_id: str, call_id: str) -> ToolResult:
    return ToolResult(
        identity=CallIdentity(run_id, "turn_1", call_id),
        tool_name="screenshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        images=(
            ImageContent(
                "image/png",
                base64.b64decode(_PNG_BASE64),
                width=1,
                height=1,
            ),
        ),
    )


def _run(
    config: AgentConfig,
    provider: ModelProviderPort,
    desktop: FakeDesktopMCP,
    run_id: str,
) -> object:
    return asyncio.run(
        AgentRunner(
            config,
            RunnerPorts(
                provider=provider,
                desktop=desktop,
                approvals=FakeApprovalPort(),
            ),
        ).run("Describe the screenshot", run_id=run_id)
    )


def test_openai_runner_returns_screenshot_as_multimodal_function_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted = ScriptedResponses(
        [
            SimpleNamespace(
                id="response_1",
                output=[
                    SimpleNamespace(
                        type="function_call",
                        name="screenshot",
                        call_id="call_screenshot",
                        arguments="{}",
                    )
                ],
                output_text="",
                usage=SimpleNamespace(input_tokens=2, output_tokens=1),
            ),
            SimpleNamespace(
                id="response_2",
                output=[],
                output_text="Screenshot received.",
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            ),
        ]
    )
    provider = OpenAIResponsesProvider("test-model", scripted)
    desktop = FakeDesktopMCP(results=deque([_screenshot_result("run_openai", "call_screenshot")]))
    config = _config(tmp_path, monkeypatch, "openai")

    outcome = _run(config, provider, desktop, "run_openai")

    assert outcome.text == "Screenshot received."
    image_block = scripted.calls[1]["input"][0]["output"][1]
    assert image_block == {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{_PNG_BASE64}",
        "detail": "high",
    }
    record = read_run_record(config.state_dir, "run_openai")
    assert record["state"]["metrics"] == {
        "model_calls": 2,
        "tool_calls": 1,
        "input_tokens": 5,
        "output_tokens": 3,
        "provider_latency_ms": record["state"]["metrics"]["provider_latency_ms"],
        "tool_latency_ms": record["state"]["metrics"]["tool_latency_ms"],
        "tool_failures": 0,
        "image_results": 1,
        "retry_count": 0,
        "run_duration_ms": record["state"]["metrics"]["run_duration_ms"],
    }
    assert record["state"]["metrics"]["run_duration_ms"] >= 0
    assert _PNG_BASE64 not in json.dumps(record)


def test_claude_runner_returns_screenshot_as_nested_tool_result_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted = ScriptedMessages(
        [
            SimpleNamespace(
                id="message_1",
                content=[
                    SimpleNamespace(
                        type="tool_use",
                        id="toolu_screenshot",
                        name="screenshot",
                        input={},
                    )
                ],
                stop_reason="tool_use",
                usage=SimpleNamespace(input_tokens=2, output_tokens=1),
            ),
            SimpleNamespace(
                id="message_2",
                content=[SimpleNamespace(type="text", text="Screenshot received.")],
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=3, output_tokens=2),
            ),
        ]
    )
    provider = AnthropicMessagesProvider("test-model", scripted)
    desktop = FakeDesktopMCP(
        results=deque([_screenshot_result("run_anthropic", "toolu_screenshot")])
    )
    config = _config(tmp_path, monkeypatch, "anthropic")

    outcome = _run(config, provider, desktop, "run_anthropic")

    assert outcome.text == "Screenshot received."
    image_block = scripted.calls[1]["messages"][2]["content"][0]["content"][1]
    assert image_block == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": _PNG_BASE64,
        },
    }
    record = read_run_record(config.state_dir, "run_anthropic")
    assert record["state"]["metrics"]["input_tokens"] == 5
    assert record["state"]["metrics"]["output_tokens"] == 3
    assert record["state"]["metrics"]["image_results"] == 1
    assert _PNG_BASE64 not in json.dumps(record)
