from __future__ import annotations

import asyncio
import io
import inspect
import json
from collections import deque
from pathlib import Path
from typing import Never

import pytest
from PIL import Image as PILImage

from computer_use_agent import continuation as continuation_module
from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    PrivacyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import (
    ContinuationError,
    continuation_path,
    read_continuation,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.runner import AgentRunner, RunFailure, RunnerError, RunnerPorts
from computer_use_agent.privacy import (
    LocalPrivacyImageRedactor,
    RecognizedImageText,
    TOKEN_PATTERN,
)
from computer_use_agent.trace import RunPhase, read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEventKind,
    MemoryContextItem,
    ImageContent,
    ModelUsage,
    ModelTurn,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_model_turns: int = 4,
    max_tool_calls: int = 4,
    max_context_events: int = 128,
    max_input_tokens: int = 1_000_000,
    continuation_enabled: bool = False,
    privacy_enabled: bool = False,
) -> AgentConfig:
    local_app_data = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    return AgentConfig(
        state_dir=local_app_data / "computer-use-agent" / "runtime-test",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="test-model"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "computer-use-mcp.exe",
            args=(),
            cwd=tmp_path,
            environment={"CUMCP_ALLOWLIST": "notepad.exe"},
        ),
        policy=PolicyConfig(
            max_model_turns=max_model_turns,
            max_tool_calls=max_tool_calls,
            max_context_events=max_context_events,
            max_input_tokens=max_input_tokens,
        ),
        continuation=ContinuationConfig(enabled=continuation_enabled),
        privacy=PrivacyConfig(enabled=privacy_enabled),
    )


def _runner(
    config: AgentConfig,
    provider: FakeModelProvider,
    desktop: FakeDesktopMCP,
) -> AgentRunner:
    return AgentRunner(
        config,
        RunnerPorts(provider=provider, desktop=desktop, approvals=FakeApprovalPort()),
    )


def test_runner_has_one_mcp_dispatch_site_inside_the_shared_call_boundary() -> None:
    runner_source = inspect.getsource(AgentRunner)
    boundary_source = inspect.getsource(AgentRunner._execute_requested_call_boundary)

    dispatch = "await self.ports.desktop.call_tool(dispatch_call)"
    assert runner_source.count(dispatch) == 1
    assert boundary_source.count(dispatch) == 1
    assert "self.policy.disposition(spec)" in boundary_source
    assert "grounding.validate(" in boundary_source
    assert "self._consume_side_effect(state)" in boundary_source
    assert "request_approval(request)" in boundary_source
    assert "continuation.dispatch_tool(" in boundary_source
    assert "privacy.resolve_local_call(authorized_call)" in boundary_source
    assert "validate_tool_result(authorized_call, result)" in boundary_source
    assert "RunPhase.VERIFYING" in boundary_source


def test_cancellation_before_a_result_remains_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_cancelled_before_result"

    class BlockingProvider(FakeModelProvider):
        def __init__(self) -> None:
            super().__init__()
            self.entered = asyncio.Event()

        async def create_turn(self, **kwargs: object) -> ModelTurn:
            self.calls.append(dict(kwargs))
            self.entered.set()
            await asyncio.Event().wait()
            raise AssertionError("cancelled provider unexpectedly resumed")

    provider = BlockingProvider()
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)
    runner = _runner(config, provider, desktop)

    async def scenario() -> bool:
        task = asyncio.create_task(runner.run("Inspect", run_id=run_id))
        await provider.entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return task.cancelled()

    assert asyncio.run(scenario())
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "CANCELLED"
    assert record["state"]["failure_code"] == "CANCELLED"
    assert desktop.tool_calls == []
    assert desktop.close_calls == 1


def test_runner_advertises_only_the_caller_bounded_reviewed_tool_subset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity("run_subset", "turn_1", "call_1")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "run_subset",
                    "turn_1",
                    "response_1",
                    "",
                    (ToolCall(identity, "ui_snapshot", {}),),
                ),
                ModelTurn("run_subset", "turn_2", "response_2", "done"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity,
                    "ui_snapshot",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="none",
                )
            ]
        )
    )

    outcome = asyncio.run(
        _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
            "Observe one bounded item",
            run_id="run_subset",
            allowed_tool_names=frozenset({"ui_snapshot", "document_text"}),
        )
    )

    assert outcome.text == "done"
    assert [
        {tool.name for tool in call["tools"]} for call in provider.calls
    ] == [
        {"ui_snapshot", "document_text"},
        {"ui_snapshot", "document_text"},
    ]
    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]


def test_runner_rejects_an_entire_turn_before_persisting_an_unadvertised_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_unadvertised_turn"
    allowed = ToolCall(
        CallIdentity(run_id, "turn_1", "call_1"),
        "ui_snapshot",
        {},
    )
    unadvertised = ToolCall(
        CallIdentity(run_id, "turn_1", "call_2"),
        "list_windows",
        {},
    )

    class RejectingTurnProvider(FakeModelProvider):
        def export_continuation(self, run_id: str) -> Never:
            del run_id
            raise AssertionError("rejected provider turn must not be exported")

    provider = RejectingTurnProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id,
                    "turn_1",
                    "response_1",
                    "",
                    (allowed, unadvertised),
                )
            ]
        )
    )
    desktop = FakeDesktopMCP()
    approvals = FakeApprovalPort()
    config = _config(tmp_path, monkeypatch, continuation_enabled=True)
    persisted_boundaries: list[tuple[str, str]] = []
    original_write = continuation_module.write_continuation

    def capture_write(state_dir: Path, payload: object) -> object:
        assert isinstance(payload, dict)
        boundary = payload["boundary"]
        assert isinstance(boundary, dict)
        persisted_boundaries.append(
            (str(boundary["operation_kind"]), str(boundary["stage"]))
        )
        return original_write(state_dir, payload)

    monkeypatch.setattr(continuation_module, "write_continuation", capture_write)

    with pytest.raises(RunFailure, match="^PROVIDER_TOOL_NOT_ADVERTISED$"):
        asyncio.run(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, approvals),
            ).run(
                "Inspect",
                run_id=run_id,
                allowed_tool_names=frozenset({"ui_snapshot"}),
            )
        )

    assert {tool.name for tool in provider.calls[0]["tools"]} == {"ui_snapshot"}
    assert desktop.tool_calls == []
    assert approvals.requests == []
    assert persisted_boundaries == [
        ("provider", "prepared"),
        ("provider", "dispatch_intent"),
    ]
    assert not continuation_path(config.state_dir, run_id).exists()
    record = read_run_record(config.state_dir, run_id)
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "PROVIDER_TOOL_NOT_ADVERTISED"
    assert record["state"]["budgets"]["model_turns_used"] == 0
    assert record["state"]["budgets"]["tool_calls_used"] == 0
    assert [event["kind"] for event in record["events"]] == ["user_task"]


def test_runner_enforces_the_post_baseline_advertised_tool_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_filtered_tool"
    call = ToolCall(
        CallIdentity(run_id, "turn_1", "call_1"),
        "ocr",
        {"x": 0, "y": 0, "w": 10, "h": 10},
    )
    provider = FakeModelProvider(
        turns=deque([ModelTurn(run_id, "turn_1", "response_1", "", (call,))])
    )
    desktop = FakeDesktopMCP(satisfied_safety_baselines=frozenset())

    with pytest.raises(RunFailure, match="^PROVIDER_TOOL_NOT_ADVERTISED$"):
        asyncio.run(
            _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
                "Read a region",
                run_id=run_id,
                allowed_tool_names=frozenset({"ui_snapshot", "ocr"}),
            )
        )

    assert {tool.name for tool in provider.calls[0]["tools"]} == {"ui_snapshot"}
    assert desktop.tool_calls == []


def test_runner_rejects_unreviewed_or_mutable_tool_subset_before_opening_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = _runner(
        _config(tmp_path, monkeypatch),
        FakeModelProvider(),
        FakeDesktopMCP(),
    )

    with pytest.raises(ValueError, match="allowed_tool_names"):
        asyncio.run(
            runner.run(
                "Invalid tool scope",
                run_id="run_invalid_subset",
                allowed_tool_names=frozenset({"browser_eval"}),
            )
        )
    with pytest.raises(ValueError, match="allowed_tool_names"):
        asyncio.run(
            runner.run(
                "Mutable tool scope",
                run_id="run_mutable_subset",
                allowed_tool_names={"ui_snapshot"},  # type: ignore[arg-type]
            )
        )

    assert not runner.config.state_dir.exists()


def test_uncorrelated_result_fails_closed_with_post_request_ledger_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = ToolCall(
        identity=CallIdentity("run_1", "turn_1", "call_1"),
        name="list_windows",
        arguments={},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_1",
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
                    identity=CallIdentity("run_1", "turn_1", "wrong_call"),
                    tool_name="list_windows",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                )
            ]
        )
    )

    with pytest.raises(RunFailure, match="UNKNOWN_OUTCOME") as raised:
        asyncio.run(
            _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
                "Inspect open windows", run_id="run_1"
            )
        )

    assert raised.value.state.budgets.tool_calls_used == 1
    assert raised.value.state.event_log[-1].kind is LedgerEventKind.TOOL_CALL
    assert desktop.close_calls == 1


def test_read_only_observe_then_answer_is_bounded_and_canonical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity(run_id="run_1", turn_id="turn_1", call_id="call_1")
    call = ToolCall(identity=identity, name="list_windows", arguments={})
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_1",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                ),
                ModelTurn(
                    run_id="run_1",
                    turn_id="turn_2",
                    provider_response_id="response_2",
                    text="Notepad is open.",
                ),
            ]
        )
    )
    result = ToolResult(
        identity=identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text="window_1 | Notepad",
    )
    desktop = FakeDesktopMCP(results=deque([result]))

    config = _config(tmp_path, monkeypatch)
    outcome = asyncio.run(
        _runner(config, provider, desktop).run(
            "Inspect open windows", run_id="run_1"
        )
    )

    assert outcome.text == "Notepad is open."
    assert outcome.state.budgets.model_turns_used == 2
    assert outcome.state.budgets.tool_calls_used == 1
    assert outcome.state.observation_epoch == 1
    assert outcome.state.verified_observation_epoch == 1
    assert [event.kind for event in outcome.state.event_log] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
        LedgerEventKind.MODEL_TURN,
    ]
    assert desktop.tool_calls == [
        ToolCall(
            identity=call.identity,
            name=call.name,
            arguments=call.arguments,
            status=ToolCallStatus.AUTHORIZED,
        )
    ]
    assert desktop.close_calls == 1
    assert len(provider.calls) == 2
    assert provider.calls[1]["ledger"][-1].kind is LedgerEventKind.OBSERVATION
    record = read_run_record(config.state_dir, "run_1")
    assert record["state"]["phase"] == "SUCCESS"
    assert record["state"]["final_text_length"] == len(outcome.text)
    assert record["state"]["resume_allowed"] is False
    assert record["state"]["metrics"]["model_calls"] == 2
    assert record["state"]["metrics"]["tool_calls"] == 1
    assert record["state"]["metrics"]["tool_failures"] == 0
    assert record["state"]["metrics"]["provider_latency_ms"] >= 0
    assert record["state"]["metrics"]["tool_latency_ms"] >= 0
    assert record["state"]["metrics"]["run_duration_ms"] >= 0
    assert len(record["events"]) == len(outcome.state.event_log)
    lock_path = _config(tmp_path, monkeypatch).application_state_dir / "active-run.lock"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == {"released": True}


def test_runner_projects_durable_phases_and_releases_presence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity("run_presence", "turn_1", "call_1")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "run_presence", "turn_1", "response_1", "",
                    tool_calls=(ToolCall(identity, "list_windows", {}),),
                ),
                ModelTurn("run_presence", "turn_2", "response_2", "Done"),
            ]
        )
    )
    desktop = FakeDesktopMCP(results=deque([ToolResult(
        identity, "list_windows", ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
    )]))

    class Presence:
        def __init__(self) -> None:
            self.events: list[RunPhase | str] = []

        def on_phase(self, phase: RunPhase) -> None:
            self.events.append(phase)

        def estop(self) -> None:
            self.events.append("estop")

        def release(self) -> None:
            self.events.append("release")

    presence = Presence()
    progress = Presence()
    outcome = asyncio.run(AgentRunner(
        _config(tmp_path, monkeypatch),
        RunnerPorts(
            provider,
            desktop,
            FakeApprovalPort(),
            presence=presence,
            progress=progress,
        ),
    ).run("Inspect", run_id="run_presence"))

    assert outcome.text == "Done"
    expected_events = [
        RunPhase.CREATED, RunPhase.OBSERVING, RunPhase.PLANNING,
        RunPhase.PLANNING, RunPhase.EXECUTING, RunPhase.OBSERVING,
        RunPhase.PLANNING, RunPhase.PLANNING, RunPhase.SUCCESS, "release",
    ]
    assert presence.events == expected_events
    assert progress.events == expected_events


@pytest.mark.parametrize(
    ("code", "boundary"), [("ABORTED", "estop"), ("HUMAN_ACTIVE", "release")]
)
def test_runner_latches_presence_off_on_mcp_authority_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: str, boundary: str
) -> None:
    identity = CallIdentity("run_boundary", "turn_1", "call_1")
    provider = FakeModelProvider(turns=deque([
        ModelTurn(
            "run_boundary", "turn_1", "response_1", "",
            tool_calls=(ToolCall(identity, "list_windows", {}),),
        ),
        ModelTurn("run_boundary", "turn_2", "response_2", "Stopped"),
    ]))
    desktop = FakeDesktopMCP(results=deque([ToolResult(
        identity, "list_windows", ToolResultStatus.REJECTED,
        DispatchCertainty.NOT_DISPATCHED, code=code,
    )]))

    class Presence:
        def __init__(self) -> None:
            self.events: list[RunPhase | str] = []

        def on_phase(self, phase: RunPhase) -> None:
            self.events.append(phase)

        def estop(self) -> None:
            self.events.append("estop")

        def release(self) -> None:
            self.events.append("release")

    presence = Presence()
    progress = Presence()
    asyncio.run(AgentRunner(
        _config(tmp_path, monkeypatch),
        RunnerPorts(
            provider,
            desktop,
            FakeApprovalPort(),
            presence=presence,
            progress=progress,
        ),
    ).run("Inspect", run_id="run_boundary"))
    assert presence.events[-1] == boundary
    assert progress.events[-1] == ("estop" if code == "ABORTED" else "release")


def test_presence_failure_cannot_change_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenPresence:
        calls = 0

        def on_phase(self, _phase: RunPhase) -> None:
            self.calls += 1
            raise RuntimeError("surface unavailable")

        def estop(self) -> None:
            raise RuntimeError("surface unavailable")

        def release(self) -> None:
            raise RuntimeError("surface unavailable")

    presence = BrokenPresence()
    provider = FakeModelProvider(turns=deque([
        ModelTurn("run_broken", "turn_1", "response_1", "OK")
    ]))
    outcome = asyncio.run(AgentRunner(
        _config(tmp_path, monkeypatch),
        RunnerPorts(provider, FakeDesktopMCP(), FakeApprovalPort(), presence=presence),
    ).run("Answer", run_id="run_broken"))
    assert outcome.text == "OK"
    assert presence.calls == 1


def test_progress_failure_cannot_change_successful_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class BrokenProgress:
        calls = 0

        def on_phase(self, _phase: RunPhase) -> None:
            self.calls += 1
            raise RuntimeError("surface unavailable")

        def estop(self) -> None:
            raise RuntimeError("surface unavailable")

        def release(self) -> None:
            raise RuntimeError("surface unavailable")

    progress = BrokenProgress()
    provider = FakeModelProvider(turns=deque([
        ModelTurn("run_broken_progress", "turn_1", "response_1", "OK")
    ]))
    outcome = asyncio.run(AgentRunner(
        _config(tmp_path, monkeypatch),
        RunnerPorts(provider, FakeDesktopMCP(), FakeApprovalPort(), progress=progress),
    ).run("Answer", run_id="run_broken_progress"))
    assert outcome.text == "OK"
    assert progress.calls == 1


def test_runner_pseudonymizes_provider_and_ledger_text_then_restores_local_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_privacy"
    identity = CallIdentity(run_id, "turn_1", "call_1")

    class PrivacyAwareProvider:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def create_turn(self, **kwargs: object) -> ModelTurn:
            self.calls.append(dict(kwargs))
            if len(self.calls) == 1:
                task = kwargs["task"]
                assert isinstance(task, str)
                match = TOKEN_PATTERN.search(task)
                assert match is not None
                return ModelTurn(
                    run_id,
                    "turn_1",
                    "response_1",
                    "",
                    tool_calls=(
                        ToolCall(identity, "find", {"query": match.group(0)}),
                    ),
                )
            ledger = kwargs["ledger"]
            result_event = next(
                event
                for event in reversed(ledger)  # type: ignore[arg-type]
                if event.kind is LedgerEventKind.TOOL_RESULT
            )
            protected = result_event.tool_result.sanitized_text
            assert "alice@example.com" not in protected
            token = TOKEN_PATTERN.search(protected)
            assert token is not None
            return ModelTurn(
                run_id,
                "turn_2",
                "response_2",
                f"Found {token.group(0)}",
            )

    provider = PrivacyAwareProvider()
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=identity,
                    tool_name="find",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    sanitized_text="Owner alice@example.com",
                )
            ]
        )
    )
    config = _config(tmp_path, monkeypatch, privacy_enabled=True)

    outcome = asyncio.run(
        AgentRunner(
            config,
            RunnerPorts(
                provider=provider,  # type: ignore[arg-type]
                desktop=desktop,
                approvals=FakeApprovalPort(),
            ),
        ).run("Find alice@example.com", run_id=run_id)
    )

    assert outcome.text == "Found alice@example.com"
    assert "alice@example.com" not in outcome.state.task
    assert all("alice@example.com" not in str(call["task"]) for call in provider.calls)
    assert all(
        tool.name != "screenshot"
        for tool in provider.calls[0]["tools"]  # type: ignore[union-attr]
    )
    assert desktop.tool_calls[0].arguments["query"] == "alice@example.com"
    stored_result = next(
        event.tool_result
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
    )
    assert "alice@example.com" not in stored_result.sanitized_text


def test_runner_redacts_screenshot_before_ledger_and_provider_visibility(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_image_privacy"
    identity = CallIdentity(run_id, "turn_1", "call_image")
    png = io.BytesIO()
    PILImage.new("RGB", (220, 60), "white").save(png, format="PNG")
    raw_image = ImageContent("image/png", png.getvalue(), 220, 60)

    class ImageProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def create_turn(self, **kwargs: object) -> ModelTurn:
            self.calls += 1
            tools = kwargs["tools"]
            assert any(tool.name == "screenshot" for tool in tools)  # type: ignore[union-attr]
            if self.calls == 1:
                return ModelTurn(
                    run_id,
                    "turn_1",
                    "response_1",
                    "",
                    tool_calls=(ToolCall(identity, "screenshot", {}),),
                )
            ledger = kwargs["ledger"]
            result = next(
                event.tool_result
                for event in reversed(ledger)  # type: ignore[arg-type]
                if event.kind is LedgerEventKind.TOOL_RESULT
            )
            assert result.images[0].data != raw_image.data
            return ModelTurn(
                run_id,
                "turn_2",
                "response_2",
                "Found [EMAIL#1]",
            )

    class ImageRecognizer:
        async def recognize(
            self, image: ImageContent
        ) -> tuple[RecognizedImageText, ...]:
            assert image.data == raw_image.data
            return (RecognizedImageText("alice@example.com", 20, 15, 140, 22),)

    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=identity,
                    tool_name="screenshot",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    images=(raw_image,),
                )
            ]
        )
    )
    config = _config(tmp_path, monkeypatch, privacy_enabled=True)

    outcome = asyncio.run(
        AgentRunner(
            config,
            RunnerPorts(
                provider=ImageProvider(),  # type: ignore[arg-type]
                desktop=desktop,
                approvals=FakeApprovalPort(),
                image_redactor=LocalPrivacyImageRedactor(ImageRecognizer()),
            ),
        ).run("Inspect the screen", run_id=run_id)
    )

    assert outcome.text == "Found alice@example.com"
    stored = next(
        event.tool_result
        for event in outcome.state.event_log
        if event.kind is LedgerEventKind.TOOL_RESULT
    )
    assert stored.images[0].data != raw_image.data


def test_opt_in_runtime_writes_intent_before_provider_and_tool_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_wal"
    identity = CallIdentity(run_id, "turn_1", "call_1")
    config = _config(tmp_path, monkeypatch, continuation_enabled=True)
    observed_boundaries: list[tuple[str, str, int]] = []
    persisted_stages: list[tuple[str, str, int]] = []
    original_write = continuation_module.write_continuation

    def capture_write(state_dir: Path, payload: object) -> object:
        assert isinstance(payload, dict)
        boundary = payload["boundary"]
        assert isinstance(boundary, dict)
        persisted_stages.append(
            (
                str(boundary["operation_kind"]),
                str(boundary["stage"]),
                int(payload["checkpoint_sequence"]),
            )
        )
        return original_write(state_dir, payload)

    monkeypatch.setattr(continuation_module, "write_continuation", capture_write)

    def observe_boundary(kind: str) -> None:
        envelope = read_continuation(config.state_dir, run_id)
        boundary = envelope.payload["boundary"]
        assert isinstance(boundary, dict)
        observed_boundaries.append(
            (
                kind,
                str(boundary["stage"]),
                int(envelope.payload["checkpoint_sequence"]),
            )
        )

    class InspectingProvider(FakeModelProvider):
        async def create_turn(self, **kwargs: object) -> ModelTurn:
            observe_boundary("provider")
            return await super().create_turn(**kwargs)  # type: ignore[arg-type]

    class InspectingDesktop(FakeDesktopMCP):
        async def call_tool(self, call: ToolCall) -> ToolResult:
            observe_boundary("tool")
            return await super().call_tool(call)

    provider = InspectingProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id,
                    "turn_1",
                    "response_1",
                    "",
                    (ToolCall(identity, "list_windows", {}),),
                ),
                ModelTurn(run_id, "turn_2", "response_2", "done"),
            ]
        )
    )
    desktop = InspectingDesktop(
        results=deque(
            [
                ToolResult(
                    identity,
                    "list_windows",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="none",
                )
            ]
        )
    )

    outcome = asyncio.run(_runner(config, provider, desktop).run("Inspect", run_id=run_id))

    assert outcome.text == "done"
    assert [item[:2] for item in observed_boundaries] == [
        ("provider", "dispatch_intent"),
        ("tool", "dispatch_intent"),
        ("provider", "dispatch_intent"),
    ]
    sequences = [item[2] for item in observed_boundaries]
    assert sequences == sorted(sequences)
    assert len(set(sequences)) == len(sequences)
    assert [item[:2] for item in persisted_stages] == [
        ("provider", "prepared"),
        ("provider", "dispatch_intent"),
        ("provider", "completed"),
        ("tool", "prepared"),
        ("tool", "dispatch_intent"),
        ("tool", "completed"),
        ("provider", "prepared"),
        ("provider", "dispatch_intent"),
        ("provider", "completed"),
    ]
    assert [item[2] for item in persisted_stages] == list(
        range(persisted_stages[0][2], persisted_stages[0][2] + len(persisted_stages))
    )
    assert (
        read_run_record(config.state_dir, run_id)["state"]["checkpoint_sequence"]
        == persisted_stages[-1][2]
    )
    assert not continuation_path(config.state_dir, run_id).exists()


def test_continuation_intent_write_failure_stops_before_provider_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = "run_wal_failure"
    config = _config(tmp_path, monkeypatch, continuation_enabled=True)
    provider = FakeModelProvider(
        turns=deque([ModelTurn(run_id, "turn_1", "response_1", "done")])
    )
    desktop = FakeDesktopMCP()
    original_write = continuation_module.write_continuation

    def fail_intent(state_dir: Path, payload: object) -> object:
        assert isinstance(payload, dict)
        boundary = payload["boundary"]
        assert isinstance(boundary, dict)
        if boundary["stage"] == "dispatch_intent":
            raise ContinuationError("CONTINUATION_WRITE_FAILED")
        return original_write(state_dir, payload)

    monkeypatch.setattr(continuation_module, "write_continuation", fail_intent)

    with pytest.raises(ContinuationError, match="CONTINUATION_WRITE_FAILED"):
        asyncio.run(_runner(config, provider, desktop).run("Inspect", run_id=run_id))

    assert provider.calls == []
    assert desktop.tool_calls == []
    assert read_run_record(config.state_dir, run_id)["state"]["phase"] == "FAILED"
    assert not continuation_path(config.state_dir, run_id).exists()


def test_read_only_action_is_recorded_as_denied_and_never_dispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    call = ToolCall(
        identity=CallIdentity(run_id="run_2", turn_id="turn_1", call_id="call_1"),
        name="click",
        arguments={"ref": "ref_1"},
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_2",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(call,),
                )
            ]
        )
    )
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RunnerError, match="POLICY_DENIED"):
        asyncio.run(
            _runner(config, provider, desktop).run(
                "Click something", run_id="run_2"
            )
        )

    assert desktop.tool_calls == []
    assert desktop.close_calls == 1
    record = read_run_record(config.state_dir, "run_2")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "POLICY_DENIED"
    assert record["state"]["metrics"]["model_calls"] == 1
    assert record["state"]["metrics"]["tool_failures"] == 1


def test_model_turn_budget_stops_before_an_extra_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity(run_id="run_3", turn_id="turn_1", call_id="call_1")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_3",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="",
                    tool_calls=(
                        ToolCall(identity=identity, name="list_windows", arguments={}),
                    ),
                )
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity=identity,
                    tool_name="list_windows",
                    status=ToolResultStatus.SUCCESS,
                    dispatch=DispatchCertainty.DISPATCHED,
                    sanitized_text="none",
                )
            ]
        )
    )

    with pytest.raises(RunFailure, match="MODEL_TURN_BUDGET_EXHAUSTED"):
        asyncio.run(
            _runner(
                _config(tmp_path, monkeypatch, max_model_turns=1), provider, desktop
            ).run("Inspect", run_id="run_3")
        )

    assert len(provider.calls) == 1
    assert desktop.close_calls == 1


def test_provider_identity_mismatch_fails_before_desktop_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="wrong_run",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="done",
                )
            ]
        )
    )
    desktop = FakeDesktopMCP()

    with pytest.raises(RunnerError, match="PROVIDER_TURN_IDENTITY_MISMATCH"):
        asyncio.run(
            _runner(_config(tmp_path, monkeypatch), provider, desktop).run(
                "Inspect", run_id="run_4"
            )
        )

    assert desktop.tool_calls == []
    assert desktop.close_calls == 1


def test_reported_input_token_budget_stops_before_next_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = CallIdentity("run_tokens", "turn_1", "call_1")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "run_tokens",
                    "turn_1",
                    "response_1",
                    "",
                    (ToolCall(identity, "list_windows", {}),),
                    ModelUsage(input_tokens=10, output_tokens=1),
                ),
                ModelTurn("run_tokens", "turn_2", "response_2", "done"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    identity,
                    "list_windows",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="none",
                )
            ]
        )
    )

    with pytest.raises(RunFailure, match="INPUT_TOKEN_BUDGET_EXHAUSTED") as raised:
        asyncio.run(
            _runner(
                _config(tmp_path, monkeypatch, max_input_tokens=10), provider, desktop
            ).run("Inspect", run_id="run_tokens")
        )

    assert raised.value.state.budgets.input_tokens_used == 10
    assert len(provider.calls) == 1
    assert [call.name for call in desktop.tool_calls] == ["list_windows"]


def test_success_is_not_checkpointed_when_desktop_close_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CloseFailingDesktop(FakeDesktopMCP):
        async def close(self) -> None:
            self.close_calls += 1
            raise RuntimeError("raw-close-error")

    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="run_close_failure",
                    turn_id="turn_1",
                    provider_response_id="response_1",
                    text="would have succeeded",
                )
            ]
        )
    )
    desktop = CloseFailingDesktop()
    config = _config(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match="raw-close-error"):
        asyncio.run(
            _runner(config, provider, desktop).run(
                "Inspect", run_id="run_close_failure"
            )
        )

    record = read_run_record(config.state_dir, "run_close_failure")
    assert record["state"]["phase"] == "FAILED"
    assert record["state"]["failure_code"] == "RUN_FAILED"
    assert "final_text_length" not in record["state"]


def test_runner_reduces_only_provider_view_and_keeps_canonical_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_identity = CallIdentity("run_context", "turn_1", "call_1")
    second_identity = CallIdentity("run_context", "turn_2", "call_2")
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    "run_context",
                    "turn_1",
                    "response_1",
                    "",
                    (ToolCall(first_identity, "list_windows", {}),),
                ),
                ModelTurn(
                    "run_context",
                    "turn_2",
                    "response_2",
                    "",
                    (ToolCall(second_identity, "find", {"query": "Notepad"}),),
                ),
                ModelTurn("run_context", "turn_3", "response_3", "done"),
            ]
        )
    )
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    first_identity,
                    "list_windows",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="windows",
                ),
                ToolResult(
                    second_identity,
                    "find",
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="notepad",
                ),
            ]
        )
    )
    config = _config(tmp_path, monkeypatch, max_context_events=6)

    outcome = asyncio.run(
        _runner(config, provider, desktop).run("Inspect", run_id="run_context")
    )

    provider_ledger = provider.calls[2]["ledger"]
    assert [event.kind for event in provider_ledger] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.RECOVERY,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
    ]
    assert provider_ledger[1].payload["status"] == "context_truncated"
    assert len(outcome.state.event_log) == 10
    assert all(event.kind is not LedgerEventKind.RECOVERY for event in outcome.state.event_log)


def test_explicit_memory_reaches_provider_but_not_ledger_or_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "MEMORY_CONTEXT_PRIVATE_VALUE"
    provider = FakeModelProvider(
        turns=deque([ModelTurn("run_memory", "turn_1", "response_1", "done")])
    )
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)
    memory = MemoryContextItem("preference", marker, "user_confirmed", "global")

    outcome = asyncio.run(
        _runner(config, provider, desktop).run(
            "Inspect", run_id="run_memory", memories=(memory,)
        )
    )

    assert provider.calls[0]["memories"] == (memory,)
    assert marker not in repr(outcome.state.event_log)
    assert marker not in json.dumps(read_run_record(config.state_dir, "run_memory"))


def test_runner_rejects_oversized_memory_context_before_external_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    config = _config(tmp_path, monkeypatch)
    memory = MemoryContextItem("preference", "concise", "user_confirmed", "global")

    with pytest.raises(RunnerError, match="MEMORY_CONTEXT_LIMIT_EXCEEDED"):
        asyncio.run(
            _runner(config, provider, desktop).run(
                "Inspect", run_id="run_memory_limit", memories=(memory,) * 9
            )
        )

    assert provider.calls == []
    assert desktop.discovery_calls == 0
    assert not config.state_dir.exists()
