from __future__ import annotations

import pytest

from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    LedgerEvent,
    LedgerEventKind,
    ModelTurn,
    PolicyDecision,
    PolicyDecisionKind,
    ProviderContinuationStrategy,
    RecoveryStatus,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    StatelessReplayBlocker,
    StatelessReplayReadiness,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
    to_json_value,
)


def _identity(call_id: str = "call_1", turn_id: str = "turn_1") -> CallIdentity:
    return CallIdentity(run_id="run_1", turn_id=turn_id, call_id=call_id)


def _call(
    *,
    name: str = "find",
    arguments: dict[str, object] | None = None,
    call_id: str = "call_1",
    turn_id: str = "turn_1",
    status: ToolCallStatus = ToolCallStatus.REQUESTED,
) -> ToolCall:
    return ToolCall(
        identity=_identity(call_id, turn_id),
        name=name,
        arguments=arguments or {"query": "Save"},
        status=status,
    )


def test_tool_call_deeply_freezes_arguments() -> None:
    arguments = {"query": {"nested": ["Save"]}}
    call = _call(arguments=arguments)

    arguments["query"]["nested"].append("Delete")

    assert to_json_value(call.arguments) == {"query": {"nested": ["Save"]}}
    with pytest.raises(TypeError):
        call.arguments["query"]["nested"] += ("Delete",)  # type: ignore[index,operator]


def test_model_turn_rejects_duplicate_tool_call_ids_and_host_lifecycle_status() -> None:
    call = _call()

    with pytest.raises(ValueError, match="unique"):
        ModelTurn(
            run_id="run_1",
            turn_id="turn_1",
            provider_response_id="response_1",
            text="",
            tool_calls=(call, call),
        )
    with pytest.raises(ValueError, match="requested"):
        ModelTurn(
            run_id="run_1",
            turn_id="turn_1",
            provider_response_id="response_1",
            text="",
            tool_calls=(_call(status=ToolCallStatus.AUTHORIZED),),
        )


def test_stateless_replay_readiness_is_structured_and_fail_closed() -> None:
    readiness = StatelessReplayReadiness(
        ProviderContinuationStrategy.REMOTE_RESPONSE_ID,
        (StatelessReplayBlocker.REPLAY_COMPILER_NOT_IMPLEMENTED,),
    )

    assert readiness.eligible is False
    with pytest.raises(ValueError, match="unique"):
        StatelessReplayReadiness(
            ProviderContinuationStrategy.REMOTE_RESPONSE_ID,
            (
                StatelessReplayBlocker.REPLAY_COMPILER_NOT_IMPLEMENTED,
                StatelessReplayBlocker.REPLAY_COMPILER_NOT_IMPLEMENTED,
            ),
        )


def test_tool_result_distinguishes_action_and_transport_failures() -> None:
    identity = _identity()
    action_error = ToolResult(
        identity=identity,
        tool_name="find",
        status=ToolResultStatus.ACTION_ERROR,
        dispatch=DispatchCertainty.DISPATCHED,
        code="DRIVER_ERROR",
    )
    transport_error = ToolResult(
        identity=identity,
        tool_name="find",
        status=ToolResultStatus.TRANSPORT_ERROR,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code="MCP_TIMEOUT_BEFORE_DISPATCH",
    )

    assert action_error.status is ToolResultStatus.ACTION_ERROR
    assert transport_error.dispatch is DispatchCertainty.NOT_DISPATCHED
    unknown_after_response = ToolResult(
        identity=identity,
        tool_name="find",
        status=ToolResultStatus.UNKNOWN_OUTCOME,
        dispatch=DispatchCertainty.DISPATCHED,
        code="MCP_PROTOCOL_ERROR",
    )
    assert unknown_after_response.dispatch is DispatchCertainty.DISPATCHED
    with pytest.raises(ValueError, match="requires dispatch"):
        ToolResult(
            identity=identity,
            tool_name="find",
            status=ToolResultStatus.ACTION_ERROR,
            dispatch=DispatchCertainty.NOT_DISPATCHED,
            code="DRIVER_ERROR",
        )


def test_screenshot_result_requires_bounded_png_with_dimensions() -> None:
    identity = _identity()
    with pytest.raises(ValueError, match="requires parsed image"):
        ToolResult(
            identity=identity,
            tool_name="screenshot",
            status=ToolResultStatus.SUCCESS,
            dispatch=DispatchCertainty.DISPATCHED,
        )
    with pytest.raises(ValueError, match="only image/png"):
        ImageContent(mime_type="image/svg+xml", data=b"<svg />", width=1, height=1)
    with pytest.raises(ValueError, match="dimensions must match"):
        ImageContent(
            mime_type="image/png",
            data=(
                b"\x89PNG\r\n\x1a\n"
                + (13).to_bytes(4, "big")
                + b"IHDR"
                + (1).to_bytes(4, "big")
                + (1).to_bytes(4, "big")
                + b"\x08\x06\x00\x00\x00"
                + b"\x00\x00\x00\x00"
            ),
            width=2,
            height=1,
        )


def test_approval_request_redacts_typed_text_and_binds_replies_to_a_call_digest() -> None:
    call = _call(name="type", arguments={"text": "secret-value", "ref": "ref_1"})
    request = ApprovalRequest.from_tool_call(
        request_id="approval_1",
        call=call,
        reason="state-changing action",
        sensitive_arguments=("text",),
    )
    matching = PolicyDecision(
        request_id="approval_1",
        identity=call.identity,
        call_digest=call.digest,
        kind=PolicyDecisionKind.ALLOW,
        reason="operator approved",
    )
    stale = PolicyDecision(
        request_id="approval_0",
        identity=call.identity,
        call_digest=call.digest,
        kind=PolicyDecisionKind.ALLOW,
        reason="operator approved",
    )

    assert "secret-value" not in repr(request.safe_argument_summary)
    assert request.safe_argument_summary.values["text_length"] == len("secret-value")
    assert request.matches(matching) is True
    assert request.matches(stale) is False
    with pytest.raises(ValueError, match="must not retain"):
        SafeArgumentSummary(
            tool_name="type",
            values={"text": "secret-value", "text_present": True, "text_length": 12, "ref_supplied": False},
            redacted_fields=("text",),
        )
    with pytest.raises(ValueError, match="only reviewed"):
        SafeArgumentSummary(
            tool_name="type",
            values={"text_present": True, "text_length": 12, "ref_supplied": False, "other": "secret"},
            redacted_fields=("text",),
        )


def test_ledger_requires_safe_call_summaries_and_globally_unique_call_identity() -> None:
    call = _call(name="type", arguments={"text": "secret-value"})
    summary = SafeArgumentSummary.from_tool_call(call, sensitive_arguments=("text",))
    with pytest.raises(ValueError, match="must not retain"):
        LedgerEvent(
            event_id="event_bad",
            kind=LedgerEventKind.TOOL_CALL,
            identity=call.identity,
            safe_argument_summary=summary,
            payload={"text": "secret-value"},
        )

    first = LedgerEvent(
        event_id="event_1",
        kind=LedgerEventKind.TOOL_CALL,
        identity=call.identity,
        safe_argument_summary=summary,
    )
    repeated = LedgerEvent(
        event_id="event_2",
        kind=LedgerEventKind.TOOL_CALL,
        identity=call.identity,
        safe_argument_summary=summary,
    )
    budget = RunBudget(max_model_turns=1, max_tool_calls=2, max_side_effects=1)

    with pytest.raises(ValueError, match="same call identity"):
        RunState(
            run_id="run_1",
            task="Inspect",
            policy_version="phase0",
            observation_epoch=0,
            budgets=budget,
            event_log=(first, repeated),
        )


def test_run_state_rejects_a_verified_epoch_after_the_current_epoch() -> None:
    event = LedgerEvent(event_id="event_1", kind=LedgerEventKind.USER_TASK, payload={"task": "Inspect"})
    budget = RunBudget(max_model_turns=1, max_tool_calls=1, max_side_effects=0)

    with pytest.raises(ValueError, match="verified_observation_epoch"):
        RunState(
            run_id="run_1",
            task="Inspect",
            policy_version="phase0",
            observation_epoch=1,
            verified_observation_epoch=2,
            budgets=budget,
            event_log=(event,),
        )


def test_unknown_tool_outcome_requires_unknown_outcome_recovery_state() -> None:
    call = _call()
    summary = SafeArgumentSummary.from_tool_call(call, sensitive_arguments=())
    call_event = LedgerEvent(
        event_id="event_1",
        kind=LedgerEventKind.TOOL_CALL,
        identity=call.identity,
        safe_argument_summary=summary,
    )
    result_event = LedgerEvent(
        event_id="event_2",
        kind=LedgerEventKind.TOOL_RESULT,
        identity=call.identity,
        tool_result=ToolResult(
            identity=call.identity,
            tool_name="find",
            status=ToolResultStatus.UNKNOWN_OUTCOME,
            dispatch=DispatchCertainty.UNKNOWN,
        ),
    )
    budget = RunBudget(max_model_turns=1, max_tool_calls=1, max_side_effects=0)

    with pytest.raises(ValueError, match="unknown tool outcome"):
        RunState(
            run_id="run_1",
            task="Inspect",
            policy_version="phase0",
            observation_epoch=0,
            budgets=budget,
            event_log=(call_event, result_event),
        )
    state = RunState(
        run_id="run_1",
        task="Inspect",
        policy_version="phase0",
        observation_epoch=0,
        budgets=budget,
        event_log=(call_event, result_event),
        recovery_status=RecoveryStatus.UNKNOWN_OUTCOME,
    )

    assert state.recovery_status is RecoveryStatus.UNKNOWN_OUTCOME
