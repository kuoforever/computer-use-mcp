"""Runner telemetry: structure, privacy, and non-authority.

Telemetry observes a run. It must never change one, so the failure cases here
matter more than the happy path.
"""

from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

import pytest

from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    PrivacyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerPorts
from computer_use_agent.telemetry import InMemoryTelemetry, NoOpTelemetry
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ModelTurn,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)



def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "telemetry-test",
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

TASK = "Inspect the open windows and report the count"


def _observe_then_answer() -> tuple[FakeModelProvider, FakeDesktopMCP]:
    call = ToolCall(
        identity=CallIdentity("run_t", "turn_1", "call_1"),
        name="list_windows",
        arguments={},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_t",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                ),
                ModelTurn(
                    run_id="run_t",
                    turn_id="turn_2",
                    provider_response_id="response_2",
                    text="There are three windows.",
                    tool_calls=(),
                ),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=CallIdentity("run_t", "turn_1", "call_1"),
                    tool_name="list_windows",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    sanitized_text="3 windows",
                )
            ]
        )
    )
    return provider, desktop


def _run(config, provider, desktop, telemetry=None):
    return asyncio.run(
        AgentRunner(
            config,
            RunnerPorts(
                provider=provider,
                desktop=desktop,
                approvals=FakeApprovalPort(),
                telemetry=telemetry,
            ),
        ).run(TASK, run_id="run_t")
    )


def test_default_runner_uses_the_noop_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider, desktop = _observe_then_answer()
    runner = AgentRunner(
        _config(tmp_path, monkeypatch),
        RunnerPorts(provider=provider, desktop=desktop, approvals=FakeApprovalPort()),
    )
    assert isinstance(runner.telemetry, NoOpTelemetry)


def test_run_emits_a_root_span_with_a_tool_boundary_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    telemetry = InMemoryTelemetry()
    provider, desktop = _observe_then_answer()

    outcome = _run(_config(tmp_path, monkeypatch), provider, desktop, telemetry)
    assert outcome.text == "There are three windows."

    roots = telemetry.roots()
    assert [span.name for span in roots] == ["agent.run"]
    root = roots[0]
    assert root.ended
    assert root.attributes["run.phase"] == "completed"
    assert root.attributes["run.resumed"] is False
    assert isinstance(root.attributes["duration.ms"], int)

    boundaries = telemetry.named("tool.boundary")
    assert len(boundaries) == 1
    boundary = boundaries[0]
    assert boundary.parent is root
    assert boundary.attributes["tool.name"] == "list_windows"
    assert boundary.attributes["tool.effect"] == "observation"
    assert boundary.attributes["result.status"] == "success"
    assert boundary.attributes["dispatch.certainty"] == "dispatched"


def test_spans_carry_no_task_or_desktop_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    telemetry = InMemoryTelemetry()
    provider, desktop = _observe_then_answer()
    _run(_config(tmp_path, monkeypatch), provider, desktop, telemetry)

    recorded = " ".join(
        f"{name}={value}"
        for span in telemetry.spans
        for name, value in span.attributes.items()
    )
    for leaked in (TASK, "There are three windows.", "3 windows"):
        assert leaked not in recorded
    # The run id is a correlation handle, not an attribute of these spans.
    assert "run_t" not in recorded


def test_failed_run_marks_the_root_span_and_records_the_boundary_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    telemetry = InMemoryTelemetry()
    call = ToolCall(
        identity=CallIdentity("run_t", "turn_1", "call_1"),
        name="list_windows",
        arguments={},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_t",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                )
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=CallIdentity("run_t", "turn_1", "wrong_call"),
                    tool_name="list_windows",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                )
            ]
        )
    )

    with pytest.raises(RunFailure, match="UNKNOWN_OUTCOME"):
        _run(_config(tmp_path, monkeypatch), provider, desktop, telemetry)

    root = telemetry.roots()[0]
    assert root.attributes["run.phase"] == "failed"
    assert root.ended
    boundary = telemetry.named("tool.boundary")[0]
    assert boundary.error_code == "UNKNOWN_OUTCOME"
    assert boundary.ended


class _ExplodingTelemetry:
    """Every telemetry entry point raises."""

    def start_span(self, name, *, attributes=None):
        raise RuntimeError("exporter unavailable")

    def record_metric(self, name, value, *, attributes=None):
        raise RuntimeError("exporter unavailable")


class _ExplodingSpanTelemetry:
    """Span creation succeeds, then every span method raises."""

    class _Span:
        def set_attributes(self, attributes):
            raise RuntimeError("attribute rejected")

        def record_error(self, code):
            raise RuntimeError("error rejected")

        def end(self):
            raise RuntimeError("flush failed")

        def __enter__(self):
            return self

        def __exit__(self, *_):
            raise RuntimeError("flush failed")

    def start_span(self, name, *, attributes=None):
        return self._Span()

    def record_metric(self, name, value, *, attributes=None):
        raise RuntimeError("exporter unavailable")


@pytest.mark.parametrize(
    "telemetry", [_ExplodingTelemetry(), _ExplodingSpanTelemetry()]
)
def test_a_failing_telemetry_port_cannot_fail_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, telemetry: object
) -> None:
    """The whole point: an exporter problem is not a run problem."""
    provider, desktop = _observe_then_answer()

    outcome = _run(_config(tmp_path, monkeypatch), provider, desktop, telemetry)

    assert outcome.text == "There are three windows."
    assert desktop.close_calls == 1


def test_telemetry_does_not_change_the_run_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run with an exporter must reach the same state as one without."""
    without = _run(*(_config(tmp_path / "a", monkeypatch), *_observe_then_answer()))
    with_telemetry = _run(
        _config(tmp_path / "b", monkeypatch),
        *_observe_then_answer(),
        InMemoryTelemetry(),
    )

    assert without.text == with_telemetry.text
    assert without.state.budgets.tool_calls_used == with_telemetry.state.budgets.tool_calls_used
    assert [event.kind for event in without.state.event_log] == [
        event.kind for event in with_telemetry.state.event_log
    ]
