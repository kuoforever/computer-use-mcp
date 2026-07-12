from __future__ import annotations

from computer_use_agent.context import ContextBudgetError, reduce_ledger
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    SafeArgumentSummary,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def _ledger() -> tuple[LedgerEvent, ...]:
    events: list[LedgerEvent] = [
        LedgerEvent("event_1", LedgerEventKind.USER_TASK, {"task_length": 7})
    ]
    for turn_number, tool_name, arguments in (
        (1, "list_windows", {}),
        (2, "find", {"query": "Notepad"}),
    ):
        identity = CallIdentity("run_context", f"turn_{turn_number}", f"call_{turn_number}")
        call = ToolCall(identity, tool_name, arguments)
        result = ToolResult(
            identity,
            tool_name,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
            sanitized_text="untrusted observation",
        )
        events.extend(
            [
                LedgerEvent(
                    f"event_{len(events) + 1}",
                    LedgerEventKind.MODEL_TURN,
                    {"tool_call_count": 1},
                ),
                LedgerEvent(
                    f"event_{len(events) + 2}",
                    LedgerEventKind.TOOL_CALL,
                    identity=identity,
                    safe_argument_summary=SafeArgumentSummary.from_tool_call(
                        call, sensitive_arguments=()
                    ),
                ),
                LedgerEvent(
                    f"event_{len(events) + 3}",
                    LedgerEventKind.TOOL_RESULT,
                    identity=identity,
                    tool_result=result,
                ),
                LedgerEvent(
                    f"event_{len(events) + 4}",
                    LedgerEventKind.OBSERVATION,
                    {"tool_name": tool_name, "observation_epoch": turn_number},
                    identity=identity,
                ),
            ]
        )
    return tuple(events)


def test_reducer_preserves_latest_continuation_pair_and_explicit_marker() -> None:
    reduced = reduce_ledger(_ledger(), max_events=6, run_id="run_context")

    assert [event.kind for event in reduced] == [
        LedgerEventKind.USER_TASK,
        LedgerEventKind.RECOVERY,
        LedgerEventKind.MODEL_TURN,
        LedgerEventKind.TOOL_CALL,
        LedgerEventKind.TOOL_RESULT,
        LedgerEventKind.OBSERVATION,
    ]
    assert reduced[1].payload == {"status": "context_truncated", "dropped_event_count": 4}
    assert reduced[3].identity == reduced[4].identity == reduced[5].identity
    assert reduced[3].safe_argument_summary.tool_name == "find"


def test_reducer_returns_original_identity_when_within_budget() -> None:
    ledger = _ledger()

    assert reduce_ledger(ledger, max_events=len(ledger), run_id="run_context") == ledger


def test_required_latest_context_fails_closed_when_budget_is_too_small() -> None:
    try:
        reduce_ledger(_ledger(), max_events=5, run_id="run_context")
    except ContextBudgetError as exc:
        assert str(exc) == "CONTEXT_REQUIRED_EVENTS_EXCEED_BUDGET"
    else:
        raise AssertionError("required context unexpectedly fit")
