"""OpenTelemetry adapter, verified against a real OTel SDK in-memory exporter.

These tests use the actual SDK rather than a hand-written double, so what is
asserted is what an exporter would really receive.
"""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

import pytest

from computer_use_agent.telemetry import TelemetryError

pytest.importorskip("opentelemetry.sdk.trace", reason="observability extra not installed")

from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)

from computer_use_agent.config import (  # noqa: E402
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    PrivacyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import (  # noqa: E402
    FakeApprovalPort,
    FakeDesktopMCP,
    FakeModelProvider,
)
from computer_use_agent.runner import AgentRunner, RunnerPorts  # noqa: E402
from computer_use_agent.telemetry_otel import OpenTelemetryAdapter  # noqa: E402
from computer_use_agent.types import (  # noqa: E402
    CallIdentity,
    DispatchCertainty,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)

TASK = "Inspect the open windows and report the count"
ANSWER = "There are three windows."
RESULT_TEXT = "3 windows"


@pytest.fixture
def exporter_and_adapter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter, OpenTelemetryAdapter(provider.get_tracer("test"))


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "otel-test",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=4),
        continuation=ContinuationConfig(enabled=False),
        privacy=PrivacyConfig(enabled=False),
    )


def _ports(telemetry):
    call = ToolCall(
        identity=CallIdentity("run_o", "turn_1", "call_1"),
        name="list_windows",
        arguments={},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_o",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                ),
                ModelTurn(
                    run_id="run_o",
                    turn_id="turn_2",
                    provider_response_id="response_2",
                    text=ANSWER,
                    tool_calls=(),
                ),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=CallIdentity("run_o", "turn_1", "call_1"),
                    tool_name="list_windows",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    sanitized_text=RESULT_TEXT,
                )
            ]
        )
    )
    return RunnerPorts(
        provider=provider,
        desktop=desktop,
        approvals=FakeApprovalPort(),
        telemetry=telemetry,
    )


def test_exported_spans_have_the_documented_parent_child_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exporter_and_adapter
) -> None:
    exporter, adapter = exporter_and_adapter

    outcome = asyncio.run(
        AgentRunner(_config(tmp_path, monkeypatch), _ports(adapter)).run(
            TASK, run_id="run_o"
        )
    )
    assert outcome.text == ANSWER

    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"agent.run", "tool.boundary"}
    root = spans["agent.run"]
    boundary = spans["tool.boundary"]
    assert root.parent is None
    assert boundary.parent is not None
    assert boundary.parent.span_id == root.context.span_id
    assert boundary.context.trace_id == root.context.trace_id


def test_exported_attributes_are_codes_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exporter_and_adapter
) -> None:
    exporter, adapter = exporter_and_adapter
    asyncio.run(
        AgentRunner(_config(tmp_path, monkeypatch), _ports(adapter)).run(
            TASK, run_id="run_o"
        )
    )
    spans = {span.name: span for span in exporter.get_finished_spans()}
    boundary = dict(spans["tool.boundary"].attributes)
    assert boundary["tool.name"] == "list_windows"
    assert boundary["tool.effect"] == "observation"
    assert boundary["result.status"] == "success"
    assert boundary["dispatch.certainty"] == "dispatched"
    assert isinstance(boundary["duration.ms"], int)
    assert dict(spans["agent.run"].attributes)["run.phase"] == "completed"


def test_nothing_content_bearing_reaches_the_exporter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exporter_and_adapter
) -> None:
    """The exporter is where data leaves the machine, so assert absence here."""
    exporter, adapter = exporter_and_adapter
    asyncio.run(
        AgentRunner(_config(tmp_path, monkeypatch), _ports(adapter)).run(
            TASK, run_id="run_o"
        )
    )
    exported = ""
    for span in exporter.get_finished_spans():
        exported += span.name
        exported += "".join(f"{k}={v}" for k, v in dict(span.attributes).items())
        exported += str(span.status.description or "")
        for event in span.events:
            exported += event.name + str(dict(event.attributes or {}))

    for leaked in (TASK, ANSWER, RESULT_TEXT, "run_o"):
        assert leaked not in exported


def test_adapter_rejects_unreviewed_attributes_before_export(
    exporter_and_adapter,
) -> None:
    """Validation is not skipped just because a real exporter is attached."""
    exporter, adapter = exporter_and_adapter
    span = adapter.start_span("agent.run")
    with pytest.raises(TelemetryError):
        span.set_attributes({"task.text": "open the invoice"})
    with pytest.raises(TelemetryError):
        span.set_attributes({"tool.invocation_count": 3})
    span.end()
    assert exporter.get_finished_spans()[0].name == "agent.run"


def test_error_status_carries_a_fixed_code_not_a_message(
    exporter_and_adapter,
) -> None:
    exporter, adapter = exporter_and_adapter
    span = adapter.start_span("tool.boundary")
    with pytest.raises(TelemetryError):
        span.record_error("Traceback (most recent call last):\n  File ...")
    span.record_error("POLICY_DENIED")
    span.end()

    exported = exporter.get_finished_spans()[0]
    assert exported.status.description == "POLICY_DENIED"
    assert dict(exported.attributes)["result.code"] == "POLICY_DENIED"


def test_sibling_spans_do_not_nest(exporter_and_adapter) -> None:
    """Context must be detached on end, or every later span becomes a child."""
    exporter, adapter = exporter_and_adapter
    root = adapter.start_span("agent.run")
    first = adapter.start_span("tool.boundary")
    first.end()
    second = adapter.start_span("tool.boundary")
    second.end()
    root.end()

    spans = exporter.get_finished_spans()
    boundaries = [span for span in spans if span.name == "tool.boundary"]
    root_span = next(span for span in spans if span.name == "agent.run")
    assert len(boundaries) == 2
    for boundary in boundaries:
        assert boundary.parent.span_id == root_span.context.span_id


def test_metrics_are_dropped_without_a_meter(exporter_and_adapter) -> None:
    """A tracer-only adapter must not fail on a metric call."""
    _, adapter = exporter_and_adapter
    adapter.record_metric("agent_runs_total", 1, attributes={"run.phase": "completed"})
    with pytest.raises(TelemetryError):
        adapter.record_metric("agent_runs_total", True)
