"""Strict planning and execution for reviewed read-only crash boundaries."""

from __future__ import annotations

from base64 import b64decode, b64encode
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from re import fullmatch
from typing import Callable, Mapping

from .config import AgentConfig
from .continuation import (
    ContinuationEnvelope,
    read_continuation,
    write_continuation,
)
from .reconstruction import (
    OperationEffect,
    OperationKind,
    OperationStage,
    OperationState,
    ReconstructionAction,
    ReconstructionContext,
    ReconstructionDecision,
    ReconstructionPhase,
    classify_operation_state,
)
from .tool_registry import (
    REVIEWED_TOOLS,
    ToolSpec,
    ToolValidationError,
    get_tool_spec,
    reviewed_registry_digest,
    validate_tool_arguments,
    validate_tool_result,
)
from .run_lock import RunLock
from .trace import (
    RunPhase,
    advance_recovery_checkpoint,
    finalize_recovery_blocked_action,
    finalize_recovery_success,
    read_run_checkpoint,
)
from .types import (
    CallIdentity,
    DesktopMCPPort,
    DispatchCertainty,
    ImageContent,
    JSONValue,
    LedgerEvent,
    LedgerEventKind,
    ModelProviderPort,
    ModelTurn,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


class RecoveryPlanError(RuntimeError):
    """Fixed attach failure that never embeds persisted sensitive content."""


class RecoveryExecutionError(RuntimeError):
    """Fixed one-step execution failure without persisted or provider content."""


@dataclass(frozen=True)
class ReadOnlyRecoveryPlan:
    decision: ReconstructionDecision
    call: ToolCall | None = None
    result: ToolResult | None = None
    final_text: str | None = None
    blocked_call_count: int | None = None

    def __post_init__(self) -> None:
        if self.decision.action is ReconstructionAction.DISPATCH_OBSERVATION:
            if (
                self.call is None
                or self.result is not None
                or self.final_text is not None
                or self.blocked_call_count is not None
            ):
                raise ValueError("observation dispatch plan requires exactly one call")
        elif self.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
            if (
                self.result is None
                or self.call is not None
                or self.final_text is not None
                or self.blocked_call_count is not None
            ):
                raise ValueError("provider continuation plan requires exactly one result")
        elif self.decision.action is ReconstructionAction.MANDATORY_REOBSERVE:
            if (
                self.call is None
                or self.result is not None
                or self.final_text is not None
                or self.blocked_call_count is not None
            ):
                raise ValueError("mandatory re-observation plan requires exactly one call")
        elif self.decision.action is ReconstructionAction.FINALIZE_SUCCESS:
            if (
                not isinstance(self.final_text, str)
                or self.call is not None
                or self.result is not None
                or self.blocked_call_count is not None
            ):
                raise ValueError("success finalization plan requires final text only")
        elif self.decision.action is ReconstructionAction.FINALIZE_BLOCKED:
            if (
                isinstance(self.blocked_call_count, bool)
                or not isinstance(self.blocked_call_count, int)
                or self.blocked_call_count < 1
                or self.call is not None
                or self.result is not None
                or self.final_text is not None
            ):
                raise ValueError("blocked finalization plan requires a call count only")
        elif (
            self.call is not None
            or self.result is not None
            or self.final_text is not None
            or self.blocked_call_count is not None
        ):
            raise ValueError("non-executable recovery plan cannot carry external work")


@dataclass(frozen=True)
class ReadOnlyRecoveryStep:
    plan: ReadOnlyRecoveryPlan
    tool_result: ToolResult | None = None
    model_turn: ModelTurn | None = None
    provider_state: Mapping[str, JSONValue] | None = None

    def __post_init__(self) -> None:
        if self.plan.decision.action in {
            ReconstructionAction.DISPATCH_OBSERVATION,
            ReconstructionAction.MANDATORY_REOBSERVE,
        }:
            if (
                self.tool_result is None
                or self.model_turn is not None
                or self.provider_state is not None
            ):
                raise ValueError("observation recovery requires exactly one tool result")
        elif self.plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
            if (
                self.model_turn is None
                or self.tool_result is not None
                or self.provider_state is None
            ):
                raise ValueError("provider recovery requires exactly one model turn")
        else:
            raise ValueError("a recovery step requires an executable plan")


@dataclass(frozen=True)
class _RecoveryTopology:
    """Ledger-proven meaning of one non-authoritative boundary."""

    operation: OperationState
    pending_effect: OperationEffect | None = None
    call: ToolCall | None = None
    result: ToolResult | None = None
    final_text: str | None = None
    blocked_call_count: int | None = None
    recovery_step_completed: bool = False


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecoveryPlanError(code)
    return value


def _identity(value: object, run_id: str) -> CallIdentity:
    raw = _mapping(value, "CONTINUATION_LEDGER_INVALID")
    if set(raw) != {"run_id", "turn_id", "call_id"} or raw.get("run_id") != run_id:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        return CallIdentity(str(raw["run_id"]), str(raw["turn_id"]), str(raw["call_id"]))
    except (KeyError, ValueError) as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc


def _ledger(envelope: ContinuationEnvelope) -> list[Mapping[str, object]]:
    raw = envelope.payload["ledger"]
    if not isinstance(raw, list) or not raw:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return [_mapping(event, "CONTINUATION_LEDGER_INVALID") for event in raw]


def _advertised_tool_names(envelope: ContinuationEnvelope) -> frozenset[str]:
    raw = envelope.payload.get("advertised_tool_names")
    if not isinstance(raw, list) or not all(isinstance(name, str) for name in raw):
        raise RecoveryPlanError("CONTINUATION_INVALID")
    return frozenset(raw)


def _validate_model_turn_tool_scope(envelope: ContinuationEnvelope) -> None:
    advertised = _advertised_tool_names(envelope)
    for event in _ledger(envelope):
        if event.get("kind") != "model_turn":
            continue
        data = _mapping(event.get("data"), "CONTINUATION_LEDGER_INVALID")
        calls = data.get("tool_calls")
        if not isinstance(calls, list):
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        for item in calls:
            call = _mapping(item, "CONTINUATION_LEDGER_INVALID")
            name = call.get("tool_name")
            if not isinstance(name, str) or name not in advertised:
                raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")


def _recovery_tools(
    envelope: ContinuationEnvelope, desktop: DesktopMCPPort | None
) -> tuple[ToolSpec, ...]:
    advertised = _advertised_tool_names(envelope)
    satisfied = frozenset() if desktop is None else desktop.satisfied_safety_baselines
    return tuple(
        tool
        for tool in REVIEWED_TOOLS
        if tool.name in advertised
        and tool.effect is ToolEffect.OBSERVATION
        and set(tool.required_safety_baselines).issubset(satisfied)
    )


def _last_event(events: list[Mapping[str, object]], kind: str) -> Mapping[str, object]:
    for event in reversed(events):
        if event.get("kind") == kind:
            return _mapping(event.get("data"), "CONTINUATION_LEDGER_INVALID")
    raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")


def _fold_budget(events: list[Mapping[str, object]]) -> dict[str, int]:
    model_turns = 0
    tool_calls = 0
    side_effects = 0
    input_tokens = 0
    for event in events:
        kind = event.get("kind")
        data = _mapping(event.get("data"), "CONTINUATION_LEDGER_INVALID")
        if kind == "model_turn":
            usage = _mapping(data.get("usage"), "CONTINUATION_LEDGER_INVALID")
            raw_input_tokens = usage.get("input_tokens")
            if raw_input_tokens is None:
                raw_input_tokens = 0
            elif (
                isinstance(raw_input_tokens, bool)
                or not isinstance(raw_input_tokens, int)
                or raw_input_tokens < 0
            ):
                raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
            model_turns += 1
            input_tokens += raw_input_tokens
        elif kind == "tool_call":
            effect = data.get("effect")
            if effect not in {ToolEffect.OBSERVATION.value, ToolEffect.SIDE_EFFECT.value}:
                raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
            tool_calls += 1
            side_effects += int(effect == ToolEffect.SIDE_EFFECT.value)
    return {
        "model_turns_used": model_turns,
        "tool_calls_used": tool_calls,
        "side_effects_used": side_effects,
        "input_tokens_used": input_tokens,
    }


def _validated_call(name: str, identity: CallIdentity, arguments: object) -> ToolCall:
    try:
        validated = validate_tool_arguments(name, arguments)  # type: ignore[arg-type]
        return ToolCall(identity, name, validated)
    except (ToolValidationError, TypeError, ValueError) as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc


def _validate_provider_correlation(
    envelope: ContinuationEnvelope, calls: tuple[ToolCall, ...]
) -> None:
    if not calls:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    if _pending_calls(envelope) != calls:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    payload = envelope.payload
    provider = _mapping(payload.get("provider"), "CONTINUATION_PROVIDER_STATE_INVALID")
    state = _mapping(payload.get("provider_state"), "CONTINUATION_PROVIDER_STATE_INVALID")
    model_turn = _last_event(_ledger(envelope), "model_turn")
    if provider.get("name") == "openai":
        usage = _mapping(model_turn.get("usage"), "CONTINUATION_PROVIDER_STATE_INVALID")
        raw_input_tokens = usage.get("input_tokens")
        raw_output_tokens = usage.get("output_tokens")
        if (
            state.get("response_id") != model_turn.get("provider_response_id")
            or isinstance(raw_input_tokens, bool)
            or raw_input_tokens is not None
            and (not isinstance(raw_input_tokens, int) or raw_input_tokens < 0)
            or isinstance(raw_output_tokens, bool)
            or raw_output_tokens is not None
            and (not isinstance(raw_output_tokens, int) or raw_output_tokens < 0)
            or state.get("prior_context_tokens")
            != (raw_input_tokens or 0) + (raw_output_tokens or 0)
        ):
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
        return
    messages = state.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
    assistant = _mapping(messages[-1], "CONTINUATION_PROVIDER_STATE_INVALID")
    content = assistant.get("content")
    if assistant.get("role") != "assistant" or not isinstance(content, list):
        raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
    tool_uses = [
        block for block in content if isinstance(block, Mapping) and block.get("type") == "tool_use"
    ]
    if len(tool_uses) != len(calls):
        raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
    for tool_use, call in zip(tool_uses, calls, strict=True):
        if (
            tool_use.get("id") != call.identity.call_id
            or tool_use.get("name") != call.name
            or tool_use.get("input") != call.arguments
        ):
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")


def _pending_calls(envelope: ContinuationEnvelope) -> tuple[ToolCall, ...]:
    data = _last_event(_ledger(envelope), "model_turn")
    calls = data.get("tool_calls")
    if not isinstance(calls, list) or not calls:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    validated: list[ToolCall] = []
    identities: set[CallIdentity] = set()
    for item in calls:
        raw = _mapping(item, "CONTINUATION_LEDGER_INVALID")
        if set(raw) != {"identity", "tool_name", "arguments", "call_digest"}:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        identity = _identity(raw["identity"], str(envelope.payload["run_id"]))
        name = raw.get("tool_name")
        if not isinstance(name, str) or identity in identities:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        call = _validated_call(name, identity, raw.get("arguments"))
        if raw.get("call_digest") != call.digest:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        identities.add(identity)
        validated.append(call)
    return tuple(validated)


def _pending_observation(envelope: ContinuationEnvelope) -> ToolCall:
    calls = _pending_calls(envelope)
    if len(calls) != 1 or get_tool_spec(calls[0].name).effect is not ToolEffect.OBSERVATION:
        raise RecoveryPlanError("PENDING_SIDE_EFFECT")
    return calls[0]


def _pending_side_effects(envelope: ContinuationEnvelope) -> tuple[ToolCall, ...]:
    calls = _pending_calls(envelope)
    if not any(get_tool_spec(call.name).effect is ToolEffect.SIDE_EFFECT for call in calls):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return calls


def _persisted_tool_call(
    envelope: ContinuationEnvelope,
    data: Mapping[str, object],
    *,
    required_effect: ToolEffect | None = None,
) -> tuple[ToolCall, ToolEffect]:
    if set(data) != {
        "identity",
        "tool_name",
        "arguments",
        "call_digest",
        "effect",
    }:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    identity = _identity(data.get("identity"), str(envelope.payload["run_id"]))
    name = data.get("tool_name")
    if not isinstance(name, str) or name not in _advertised_tool_names(envelope):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        effect = get_tool_spec(name).effect
    except ToolValidationError as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc
    if data.get("effect") != effect.value or (
        required_effect is not None and effect is not required_effect
    ):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    call = _validated_call(name, identity, data.get("arguments"))
    if data.get("call_digest") != call.digest:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return call, effect


def _persisted_tool_result(
    envelope: ContinuationEnvelope,
    data: Mapping[str, object],
    call: ToolCall,
) -> ToolResult:
    result_identity = _identity(data.get("identity"), str(envelope.payload["run_id"]))
    if result_identity != call.identity or data.get("tool_name") != call.name:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        status = ToolResultStatus(str(data["status"]))
        dispatch = DispatchCertainty(str(data["dispatch"]))
        images_raw = data.get("images", [])
        if not isinstance(images_raw, list):
            raise ValueError
        images = tuple(
            ImageContent(
                mime_type=str(_mapping(image, "CONTINUATION_LEDGER_INVALID")["mime_type"]),
                data=b64decode(
                    str(_mapping(image, "CONTINUATION_LEDGER_INVALID")["data"]), validate=True
                ),
                width=int(_mapping(image, "CONTINUATION_LEDGER_INVALID")["width"]),
                height=int(_mapping(image, "CONTINUATION_LEDGER_INVALID")["height"]),
            )
            for image in images_raw
        )
        code = data.get("code")
        if code is not None and not isinstance(code, str):
            raise ValueError
        result_text = data.get("sanitized_text", "")
        if not isinstance(result_text, str):
            raise ValueError
        return ToolResult(
            result_identity,
            call.name,
            status,
            dispatch,
            sanitized_text=result_text,
            code=code,
            images=images,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc


def _completed_tool_pair(
    envelope: ContinuationEnvelope,
    call_event: Mapping[str, object],
    result_event: Mapping[str, object],
    *,
    required_effect: ToolEffect,
) -> tuple[ToolCall, ToolResult]:
    if call_event.get("kind") != "tool_call" or result_event.get("kind") != "tool_result":
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    call_data = _mapping(call_event.get("data"), "CONTINUATION_LEDGER_INVALID")
    result_data = _mapping(result_event.get("data"), "CONTINUATION_LEDGER_INVALID")
    call, _effect = _persisted_tool_call(envelope, call_data, required_effect=required_effect)
    return call, _persisted_tool_result(envelope, result_data, call)


def _completed_tool(
    envelope: ContinuationEnvelope, *, required_effect: ToolEffect
) -> tuple[ToolCall, ToolResult]:
    events = _ledger(envelope)
    if len(events) < 2:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return _completed_tool_pair(
        envelope,
        events[-2],
        events[-1],
        required_effect=required_effect,
    )


def _completed_observation(envelope: ContinuationEnvelope) -> tuple[ToolCall, ToolResult]:
    return _completed_tool(envelope, required_effect=ToolEffect.OBSERVATION)


def _completed_side_effect(envelope: ContinuationEnvelope) -> tuple[ToolCall, ToolResult]:
    return _completed_tool(envelope, required_effect=ToolEffect.SIDE_EFFECT)


def _completed_final_text(envelope: ContinuationEnvelope) -> str:
    events = _ledger(envelope)
    data = _last_event(events, "model_turn")
    if set(data) != {
        "run_id",
        "turn_id",
        "provider_response_id",
        "text",
        "usage",
        "tool_calls",
    }:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    run_id = str(envelope.payload["run_id"])
    turn_id = data.get("turn_id")
    text = data.get("text")
    calls = data.get("tool_calls")
    response_id = data.get("provider_response_id")
    if (
        data.get("run_id") != run_id
        or not isinstance(turn_id, str)
        or fullmatch(r"turn_[1-9][0-9]{0,8}", turn_id) is None
        or not isinstance(text, str)
        or not isinstance(calls, list)
        or calls
        or not isinstance(response_id, str)
        or not response_id
        or envelope.operation_state.operation_id != f"{run_id}:{turn_id}:provider"
    ):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    provider = _mapping(envelope.payload.get("provider"), "CONTINUATION_PROVIDER_STATE_INVALID")
    state = _mapping(envelope.payload.get("provider_state"), "CONTINUATION_PROVIDER_STATE_INVALID")
    if provider.get("name") == "openai":
        usage = _mapping(data.get("usage"), "CONTINUATION_PROVIDER_STATE_INVALID")
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if (
            state.get("response_id") != response_id
            or isinstance(input_tokens, bool)
            or input_tokens is not None
            and (not isinstance(input_tokens, int) or input_tokens < 0)
            or isinstance(output_tokens, bool)
            or output_tokens is not None
            and (not isinstance(output_tokens, int) or output_tokens < 0)
            or state.get("prior_context_tokens") != (input_tokens or 0) + (output_tokens or 0)
        ):
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
        batches = state.get("output_batches")
        if not isinstance(batches, list) or not batches:
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
        last_batch = _mapping(batches[-1], "CONTINUATION_PROVIDER_STATE_INVALID")
        items = last_batch.get("items")
        if not isinstance(items, list) or any(
            isinstance(item, Mapping) and item.get("type") == "function_call" for item in items
        ):
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
    else:
        messages = state.get("messages")
        if not isinstance(messages, list) or not messages:
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
        assistant = _mapping(messages[-1], "CONTINUATION_PROVIDER_STATE_INVALID")
        content = assistant.get("content")
        if (
            assistant.get("role") != "assistant"
            or not isinstance(content, list)
            or any(
                isinstance(block, Mapping) and block.get("type") == "tool_use" for block in content
            )
        ):
            raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
    return text


def _provider_completed_topology(
    envelope: ContinuationEnvelope,
) -> _RecoveryTopology:
    events = _ledger(envelope)
    if events[-1].get("kind") != "model_turn":
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    data = _mapping(events[-1].get("data"), "CONTINUATION_LEDGER_INVALID")
    calls_raw = data.get("tool_calls")
    if not isinstance(calls_raw, list):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    operation = envelope.operation_state
    if not calls_raw:
        return _RecoveryTopology(
            operation,
            final_text=_completed_final_text(envelope),
        )

    calls = _pending_calls(envelope)
    run_id = str(envelope.payload["run_id"])
    turn_id = data.get("turn_id")
    if (
        data.get("run_id") != run_id
        or not isinstance(turn_id, str)
        or fullmatch(r"turn_[1-9][0-9]{0,8}", turn_id) is None
        or operation.operation_id != f"{run_id}:{turn_id}:provider"
        or any(call.identity.turn_id != turn_id for call in calls)
    ):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    _validate_provider_correlation(envelope, calls)
    effects = tuple(get_tool_spec(call.name).effect for call in calls)
    if all(effect is ToolEffect.OBSERVATION for effect in effects):
        if len(calls) != 1:
            raise RecoveryPlanError("PENDING_SIDE_EFFECT")
        return _RecoveryTopology(
            operation,
            pending_effect=OperationEffect.OBSERVATION,
            call=calls[0],
        )
    return _RecoveryTopology(
        operation,
        pending_effect=OperationEffect.SIDE_EFFECT,
        blocked_call_count=len(calls),
    )


def _next_provider_operation_id(envelope: ContinuationEnvelope) -> str:
    model_turns = sum(event.get("kind") == "model_turn" for event in _ledger(envelope))
    return f"{envelope.payload['run_id']}:turn_{model_turns + 1}:provider"


def _tool_lineage(
    envelope: ContinuationEnvelope,
    events: list[Mapping[str, object]],
    call_index: int,
    call: ToolCall,
    effect: ToolEffect,
) -> str:
    try:
        provider_calls = _pending_calls(envelope)
        _validate_provider_correlation(envelope, provider_calls)
        if call not in provider_calls:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        if len(provider_calls) > 1 and any(
            get_tool_spec(item.name).effect is not ToolEffect.OBSERVATION
            for item in provider_calls
        ):
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        return "provider" if provider_calls == (call,) else "provider_multi"
    except RecoveryPlanError as provider_error:
        if call_index < 2 or effect is not ToolEffect.OBSERVATION:
            raise provider_error
        try:
            prior_call, prior_result = _completed_tool_pair(
                envelope,
                events[call_index - 2],
                events[call_index - 1],
                required_effect=ToolEffect.SIDE_EFFECT,
            )
            if prior_result.status is ToolResultStatus.UNKNOWN_OUTCOME:
                raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
            _validate_provider_correlation(envelope, (prior_call,))
        except RecoveryPlanError:
            raise provider_error
        return "verification"


def _is_recovery_mandatory_call(
    envelope: ContinuationEnvelope,
    call: ToolCall,
    stage: OperationStage,
    lineage: str,
) -> bool:
    if lineage != "verification" or stage is OperationStage.PREPARED:
        return False
    sequence = envelope.payload["checkpoint_sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise RecoveryPlanError("CONTINUATION_INVALID")
    recovery_sequence = sequence if stage is OperationStage.DISPATCH_INTENT else sequence - 1
    return (
        recovery_sequence >= 1
        and call.identity.turn_id == f"recovery_{recovery_sequence}"
        and call.identity.call_id == "mandatory_ui_snapshot"
        and call.name == "ui_snapshot"
        and dict(call.arguments) == {}
    )


def _tool_topology(envelope: ContinuationEnvelope) -> _RecoveryTopology:
    events = _ledger(envelope)
    operation = envelope.operation_state
    completed = operation.stage is OperationStage.COMPLETED
    call_index = len(events) - (2 if completed else 1)
    if call_index < 0 or events[call_index].get("kind") != "tool_call":
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    call_data = _mapping(events[call_index].get("data"), "CONTINUATION_LEDGER_INVALID")
    call, effect = _persisted_tool_call(envelope, call_data)
    expected_id = f"{call.identity.run_id}:{call.identity.turn_id}:{call.identity.call_id}"
    if operation.operation_id != expected_id or operation.effect is not OperationEffect(
        effect.value
    ):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    lineage = _tool_lineage(envelope, events, call_index, call, effect)
    recovery_mandatory_call = _is_recovery_mandatory_call(
        envelope, call, operation.stage, lineage
    )
    if lineage == "verification" and not recovery_mandatory_call:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    if lineage == "provider_multi" and operation.stage is OperationStage.PREPARED:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    boundary = _mapping(envelope.payload["boundary"], "CONTINUATION_INVALID")
    next_step = boundary.get("next_step")
    dispatch = boundary.get("dispatch")

    if operation.stage is OperationStage.PREPARED:
        if dispatch != "not_dispatched" or next_step != "stop":
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        return _RecoveryTopology(operation, call=call)
    if operation.stage is OperationStage.DISPATCH_INTENT:
        if dispatch != "unknown" or next_step != "stop":
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        return _RecoveryTopology(operation, call=call)

    if events[-1].get("kind") != "tool_result":
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    result_data = _mapping(events[-1].get("data"), "CONTINUATION_LEDGER_INVALID")
    result = _persisted_tool_result(envelope, result_data, call)
    unknown = result.status is ToolResultStatus.UNKNOWN_OUTCOME
    if lineage == "provider_multi" and not unknown:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    if unknown:
        valid_dispatch = dispatch in {"dispatched", "unknown"} and (
            dispatch != "dispatched" or result.dispatch is DispatchCertainty.DISPATCHED
        )
    else:
        valid_dispatch = dispatch == "dispatched"
    expected_next_step = (
        "stop"
        if unknown or recovery_mandatory_call
        else ("provider_continue" if effect is ToolEffect.OBSERVATION else "mandatory_reobserve")
    )
    if not valid_dispatch or next_step != expected_next_step:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return _RecoveryTopology(
        operation,
        call=call,
        result=result,
        recovery_step_completed=recovery_mandatory_call and not unknown,
    )


def _validated_recovery_topology(
    envelope: ContinuationEnvelope,
) -> _RecoveryTopology:
    boundary = _mapping(envelope.payload["boundary"], "CONTINUATION_INVALID")
    operation = envelope.operation_state
    if operation.kind is OperationKind.TOOL:
        return _tool_topology(envelope)

    next_step = boundary.get("next_step")
    dispatch = boundary.get("dispatch")
    raw_effect = boundary.get("effect")
    if operation.stage is OperationStage.PREPARED:
        if (
            raw_effect is not None
            or dispatch != "not_dispatched"
            or next_step != "stop"
            or operation.operation_id != _next_provider_operation_id(envelope)
        ):
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        return _RecoveryTopology(operation)
    if operation.stage is OperationStage.DISPATCH_INTENT:
        if (
            raw_effect is not None
            or dispatch != "unknown"
            or next_step != "stop"
            or operation.operation_id != _next_provider_operation_id(envelope)
        ):
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        return _RecoveryTopology(operation)
    if dispatch != "dispatched":
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    topology = _provider_completed_topology(envelope)
    expected_effect = None if topology.pending_effect is None else topology.pending_effect.value
    expected_next_step = (
        "dispatch_observation" if topology.pending_effect is OperationEffect.OBSERVATION else "stop"
    )
    if raw_effect != expected_effect or next_step != expected_next_step:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return topology


def _recovery_budget_available(
    action: ReconstructionAction,
    topology: _RecoveryTopology,
    budget: Mapping[str, object],
) -> bool:
    if action is ReconstructionAction.CONTINUE_PROVIDER:
        return int(budget["model_turns_used"]) < int(budget["max_model_turns"]) and int(
            budget["input_tokens_used"]
        ) < int(budget["max_input_tokens"])
    if action is ReconstructionAction.DISPATCH_OBSERVATION:
        if (
            topology.operation.kind is OperationKind.TOOL
            and topology.operation.stage is OperationStage.PREPARED
        ):
            return int(budget["tool_calls_used"]) <= int(budget["max_tool_calls"])
        return int(budget["tool_calls_used"]) < int(budget["max_tool_calls"])
    if action is ReconstructionAction.MANDATORY_REOBSERVE:
        return int(budget["tool_calls_used"]) < int(budget["max_tool_calls"])
    return True


def plan_read_only_recovery(
    checkpoint: Mapping[str, JSONValue],
    envelope: ContinuationEnvelope,
    config: AgentConfig,
    *,
    task: str,
) -> ReadOnlyRecoveryPlan:
    """Validate current code/config against one artifact and return no-I/O work."""

    if not isinstance(checkpoint, Mapping) or not isinstance(config, AgentConfig):
        raise ValueError("checkpoint and config have invalid types")
    payload = envelope.payload
    _validate_model_turn_tool_scope(envelope)
    provider = _mapping(payload["provider"], "CHECKPOINT_MISMATCH")
    budget = _mapping(payload["budget"], "CONTINUATION_INVALID")
    expected_limits = {
        "max_model_turns": config.policy.max_model_turns,
        "max_tool_calls": config.policy.max_tool_calls,
        "max_side_effects": config.policy.max_side_effects,
        "max_input_tokens": config.policy.max_input_tokens,
    }
    folded_budget = _fold_budget(_ledger(envelope))
    identity_matches = (
        checkpoint.get("run_id") == payload["run_id"]
        and checkpoint.get("policy_version") == payload["policy_version"] == config.policy_version
        and checkpoint.get("task_length") == len(task)
        and payload["task"] == task
        and provider.get("name") == config.provider.name
        and provider.get("model") == config.provider.model
        and payload["registry_digest"] == reviewed_registry_digest()
        and all(budget.get(name) == value for name, value in expected_limits.items())
        and all(budget.get(name) == value for name, value in folded_budget.items())
    )
    sequence_matches = checkpoint.get("checkpoint_sequence") == payload["checkpoint_sequence"]
    topology = _validated_recovery_topology(envelope)
    context = ReconstructionContext(
        identity_matches=identity_matches,
        sequence_matches=sequence_matches,
        budget_available=True,
        pending_effect=topology.pending_effect,
    )
    decision = classify_operation_state(topology.operation, context=context)
    if decision.action is ReconstructionAction.HUMAN_REOBSERVE:
        plan = ReadOnlyRecoveryPlan(decision)
    elif decision.action is ReconstructionAction.FINALIZE_BLOCKED:
        if topology.blocked_call_count is None:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        plan = ReadOnlyRecoveryPlan(decision, blocked_call_count=topology.blocked_call_count)
    elif decision.action is ReconstructionAction.FINALIZE_SUCCESS:
        if topology.final_text is None:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        plan = ReadOnlyRecoveryPlan(decision, final_text=topology.final_text)
    elif decision.action is ReconstructionAction.DISPATCH_OBSERVATION:
        if topology.call is None:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        plan = ReadOnlyRecoveryPlan(decision, call=topology.call)
    elif decision.action is ReconstructionAction.CONTINUE_PROVIDER:
        if topology.recovery_step_completed:
            plan = ReadOnlyRecoveryPlan(
                ReconstructionDecision(
                    ReconstructionAction.START_NEW_RUN,
                    "RECOVERY_STEP_COMPLETED",
                    ReconstructionPhase.FAILED,
                )
            )
        elif topology.result is None:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        else:
            plan = ReadOnlyRecoveryPlan(decision, result=topology.result)
    elif decision.action is ReconstructionAction.MANDATORY_REOBSERVE:
        if topology.result is None:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        if "ui_snapshot" not in _advertised_tool_names(envelope):
            plan = ReadOnlyRecoveryPlan(
                ReconstructionDecision(
                    ReconstructionAction.START_NEW_RUN,
                    "RECOVERY_MANDATORY_OBSERVATION_NOT_ADVERTISED",
                    ReconstructionPhase.FAILED,
                )
            )
        else:
            sequence = payload["checkpoint_sequence"]
            if isinstance(sequence, bool) or not isinstance(sequence, int):
                raise RecoveryPlanError("CONTINUATION_INVALID")
            identity = CallIdentity(
                str(payload["run_id"]),
                f"recovery_{sequence + 1}",
                "mandatory_ui_snapshot",
            )
            for event in _ledger(envelope):
                data = _mapping(event.get("data"), "CONTINUATION_LEDGER_INVALID")
                raw_identity = data.get("identity")
                if isinstance(raw_identity, Mapping) and raw_identity == {
                    "run_id": identity.run_id,
                    "turn_id": identity.turn_id,
                    "call_id": identity.call_id,
                }:
                    raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
            plan = ReadOnlyRecoveryPlan(decision, call=ToolCall(identity, "ui_snapshot", {}))
    else:
        plan = ReadOnlyRecoveryPlan(decision)

    if not _recovery_budget_available(plan.decision.action, topology, budget):
        exhausted = classify_operation_state(
            topology.operation,
            context=replace(context, budget_available=False),
        )
        return ReadOnlyRecoveryPlan(exhausted)
    return plan


class LockedRecoveryPersistence:
    """Durably commit one reviewed recovery step while one run lock is held."""

    def __init__(
        self,
        *,
        state_dir: Path,
        checkpoint: Mapping[str, JSONValue],
        envelope: ContinuationEnvelope,
        config: AgentConfig,
        task: str,
        lock: RunLock,
        phase_observer: Callable[[RunPhase], None] | None = None,
    ) -> None:
        if not lock.acquired or lock.lock_dir.resolve(
            strict=False
        ) != config.application_state_dir.resolve(strict=False):
            raise RecoveryExecutionError("RECOVERY_RUN_LOCK_REQUIRED")
        if state_dir != config.state_dir or not config.continuation.enabled:
            raise RecoveryExecutionError("RECOVERY_CONTINUATION_DISABLED")
        self.state_dir = state_dir
        self.run_id = str(envelope.payload["run_id"])
        self.config = config
        self.task = task
        self.lock = lock
        self.plan = plan_read_only_recovery(checkpoint, envelope, config, task=task)
        self._envelope = envelope
        self._intent_operation_id: str | None = None
        if phase_observer is not None and not callable(phase_observer):
            raise ValueError("phase_observer must be callable")
        self._phase_observer = phase_observer

    @staticmethod
    def _copy_payload(envelope: ContinuationEnvelope) -> dict[str, object]:
        return {key: value for key, value in envelope.payload.items() if key != "payload_digest"}

    def _assert_locked(self) -> None:
        if not self.lock.acquired:
            raise RecoveryExecutionError("RECOVERY_RUN_LOCK_REQUIRED")

    def _notify_phase(self, phase: RunPhase) -> None:
        if self._phase_observer is None:
            return
        try:
            self._phase_observer(phase)
        except Exception:
            pass

    def _current(self, expected_sequence: int) -> tuple[dict[str, JSONValue], ContinuationEnvelope]:
        self._assert_locked()
        checkpoint = read_run_checkpoint(self.state_dir, self.run_id)
        envelope = read_continuation(self.state_dir, self.run_id)
        if (
            checkpoint.get("checkpoint_sequence") != expected_sequence
            or envelope.payload.get("checkpoint_sequence") != expected_sequence
            or envelope.payload.get("payload_digest")
            != self._envelope.payload.get("payload_digest")
        ):
            raise RecoveryExecutionError("RECOVERY_SEQUENCE_MISMATCH")
        return checkpoint, envelope

    def _commit_payload(
        self,
        payload: dict[str, object],
        *,
        expected_sequence: int,
        phase: RunPhase,
        recovery_status: str,
    ) -> None:
        new_sequence = expected_sequence + 1
        payload["checkpoint_sequence"] = new_sequence
        payload["expires_at"] = (
            datetime.now(UTC) + timedelta(seconds=self.config.continuation.ttl_seconds)
        ).isoformat()
        written = write_continuation(self.state_dir, payload)
        budget = written.payload["budget"]
        observation = written.payload["observation"]
        if not isinstance(budget, Mapping) or not isinstance(observation, Mapping):
            raise RecoveryExecutionError("RECOVERY_PERSISTENCE_INVALID")
        advance_recovery_checkpoint(
            self.state_dir,
            self.run_id,
            expected_sequence=expected_sequence,
            new_sequence=new_sequence,
            phase=phase,
            budgets=budget,
            observation_epoch=int(observation["epoch"]),
            verified_observation_epoch=(
                None
                if observation["verified_epoch"] is None
                else int(observation["verified_epoch"])
            ),
            recovery_status=recovery_status,
        )
        self._envelope = written
        self._notify_phase(phase)

    def commit_intent(self, sequence: int, operation_id: str, action: ReconstructionAction) -> None:
        """Persist a new, uniquely identified dispatch intent before I/O."""

        checkpoint, envelope = self._current(sequence)
        current_plan = plan_read_only_recovery(checkpoint, envelope, self.config, task=self.task)
        topology = _validated_recovery_topology(envelope)
        current_budget = _mapping(envelope.payload["budget"], "CONTINUATION_INVALID")
        if (
            action is not self.plan.decision.action
            or current_plan != self.plan
            or not _recovery_budget_available(action, topology, current_budget)
            or self._intent_operation_id is not None
        ):
            raise RecoveryExecutionError("RECOVERY_INTENT_MISMATCH")
        payload = self._copy_payload(envelope)
        boundary = payload.get("boundary")
        ledger = payload.get("ledger")
        budget = payload.get("budget")
        if (
            not isinstance(boundary, Mapping)
            or not isinstance(ledger, list)
            or not isinstance(budget, Mapping)
        ):
            raise RecoveryExecutionError("RECOVERY_PERSISTENCE_INVALID")
        updated_budget = dict(budget)
        updated_ledger = list(ledger)
        if action in {
            ReconstructionAction.DISPATCH_OBSERVATION,
            ReconstructionAction.MANDATORY_REOBSERVE,
        }:
            call = self.plan.call
            if call is None or operation_id != (
                f"{call.identity.run_id}:{call.identity.turn_id}:{call.identity.call_id}"
            ):
                raise RecoveryExecutionError("RECOVERY_INTENT_MISMATCH")
            reuse_prepared_call = (
                action is ReconstructionAction.DISPATCH_OBSERVATION
                and topology.operation.kind is OperationKind.TOOL
                and topology.operation.stage is OperationStage.PREPARED
            )
            if reuse_prepared_call:
                if topology.call != call:
                    raise RecoveryExecutionError("RECOVERY_INTENT_MISMATCH")
            else:
                tool_calls_used = int(updated_budget["tool_calls_used"])
                max_tool_calls = int(updated_budget["max_tool_calls"])
                if tool_calls_used >= max_tool_calls:
                    raise RecoveryExecutionError("RECOVERY_INTENT_MISMATCH")
                updated_budget["tool_calls_used"] = tool_calls_used + 1
                updated_ledger.append(
                    {
                        "kind": "tool_call",
                        "event_id": f"{self.run_id}:recovery:{len(updated_ledger) + 1}",
                        "data": {
                            "identity": {
                                "run_id": call.identity.run_id,
                                "turn_id": call.identity.turn_id,
                                "call_id": call.identity.call_id,
                            },
                            "tool_name": call.name,
                            "arguments": dict(call.arguments),
                            "call_digest": call.digest,
                            "effect": ToolEffect.OBSERVATION.value,
                        },
                    }
                )
            kind = "tool"
            effect: str | None = ToolEffect.OBSERVATION.value
            phase = (
                RunPhase.VERIFYING
                if action is ReconstructionAction.MANDATORY_REOBSERVE
                else RunPhase.EXECUTING
            )
        elif action is ReconstructionAction.CONTINUE_PROVIDER:
            if operation_id != f"{self.run_id}:turn_{self._next_turn_number()}:provider":
                raise RecoveryExecutionError("RECOVERY_INTENT_MISMATCH")
            kind = "provider"
            effect = None
            phase = RunPhase.PLANNING
        else:
            raise RecoveryExecutionError("RECOVERY_PLAN_NOT_EXECUTABLE")
        payload["ledger"] = updated_ledger
        payload["budget"] = updated_budget
        payload["boundary"] = {
            "operation_kind": kind,
            "stage": "dispatch_intent",
            "operation_id": operation_id,
            "effect": effect,
            "dispatch": "unknown",
            "next_step": "stop",
        }
        self._commit_payload(
            payload,
            expected_sequence=sequence,
            phase=phase,
            recovery_status=(
                "requires_reobservation"
                if action is ReconstructionAction.MANDATORY_REOBSERVE
                else "ready"
            ),
        )
        self._intent_operation_id = operation_id

    def _next_turn_number(self) -> int:
        result = self.plan.result
        if result is None:
            raise RecoveryExecutionError("RECOVERY_TURN_ID_INVALID")
        match = fullmatch(r"turn_([1-9][0-9]{0,8})", result.identity.turn_id)
        if match is None:
            raise RecoveryExecutionError("RECOVERY_TURN_ID_INVALID")
        return int(match.group(1)) + 1

    def commit_completion(
        self,
        sequence: int,
        operation_id: str,
        step: ReadOnlyRecoveryStep,
    ) -> None:
        """Persist the normalized completion; an error leaves intent unknown."""

        _, envelope = self._current(sequence)
        if operation_id != self._intent_operation_id or step.plan != self.plan:
            raise RecoveryExecutionError("RECOVERY_COMPLETION_MISMATCH")
        payload = self._copy_payload(envelope)
        ledger = payload.get("ledger")
        budget = payload.get("budget")
        observation = payload.get("observation")
        if (
            not isinstance(ledger, list)
            or not isinstance(budget, Mapping)
            or not isinstance(observation, Mapping)
        ):
            raise RecoveryExecutionError("RECOVERY_PERSISTENCE_INVALID")
        updated_ledger = list(ledger)
        updated_budget = dict(budget)
        updated_observation = dict(observation)
        effect: str | None
        next_step: str
        recovery_status = "ready"
        if step.tool_result is not None:
            result = step.tool_result
            updated_ledger.append(
                {
                    "kind": "tool_result",
                    "event_id": f"{self.run_id}:recovery:{len(updated_ledger) + 1}",
                    "data": {
                        "identity": {
                            "run_id": result.identity.run_id,
                            "turn_id": result.identity.turn_id,
                            "call_id": result.identity.call_id,
                        },
                        "tool_name": result.tool_name,
                        "status": result.status.value,
                        "dispatch": result.dispatch.value,
                        "code": result.code,
                        "sanitized_text": result.sanitized_text,
                        "images": [
                            {
                                "mime_type": image.mime_type,
                                "data": b64encode(image.data).decode("ascii"),
                                "width": image.width,
                                "height": image.height,
                            }
                            for image in result.images
                        ],
                    },
                }
            )
            if result.ok:
                epoch = int(updated_observation["epoch"]) + 1
                updated_observation["epoch"] = epoch
                updated_observation["verified_epoch"] = epoch
            mandatory = step.plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE
            next_step = "stop" if mandatory else "provider_continue"
            if mandatory:
                recovery_status = "stopped"
            if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
                recovery_status = "unknown_outcome"
                next_step = "stop"
            effect = ToolEffect.OBSERVATION.value
        elif step.model_turn is not None and step.provider_state is not None:
            turn = step.model_turn
            updated_budget["model_turns_used"] = int(updated_budget["model_turns_used"]) + 1
            updated_budget["input_tokens_used"] = int(updated_budget["input_tokens_used"]) + int(
                turn.usage.input_tokens or 0
            )
            updated_ledger.append(
                {
                    "kind": "model_turn",
                    "event_id": f"{self.run_id}:recovery:{len(updated_ledger) + 1}",
                    "data": {
                        "run_id": turn.run_id,
                        "turn_id": turn.turn_id,
                        "provider_response_id": turn.provider_response_id,
                        "text": turn.text,
                        "usage": {
                            "input_tokens": turn.usage.input_tokens,
                            "output_tokens": turn.usage.output_tokens,
                        },
                        "tool_calls": [
                            {
                                "identity": {
                                    "run_id": call.identity.run_id,
                                    "turn_id": call.identity.turn_id,
                                    "call_id": call.identity.call_id,
                                },
                                "tool_name": call.name,
                                "arguments": dict(call.arguments),
                                "call_digest": call.digest,
                            }
                            for call in turn.tool_calls
                        ],
                    },
                }
            )
            payload["provider_state"] = dict(step.provider_state)
            effects = [get_tool_spec(call.name).effect for call in turn.tool_calls]
            effect = (
                ToolEffect.OBSERVATION.value
                if effects and all(item is ToolEffect.OBSERVATION for item in effects)
                else ToolEffect.SIDE_EFFECT.value
                if effects
                else None
            )
            next_step = "dispatch_observation" if effect == ToolEffect.OBSERVATION.value else "stop"
        else:
            raise RecoveryExecutionError("RECOVERY_COMPLETION_MISMATCH")
        payload["ledger"] = updated_ledger
        payload["budget"] = updated_budget
        payload["observation"] = updated_observation
        payload["boundary"] = {
            "operation_kind": "tool" if step.tool_result is not None else "provider",
            "stage": "completed",
            "operation_id": operation_id,
            "effect": effect,
            "dispatch": "unknown" if recovery_status == "unknown_outcome" else "dispatched",
            "next_step": next_step,
        }
        self._commit_payload(
            payload,
            expected_sequence=sequence,
            phase=(
                RunPhase.UNKNOWN_OUTCOME
                if recovery_status == "unknown_outcome"
                else (
                    RunPhase.VERIFYING
                    if step.plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE
                    else RunPhase.PLANNING
                )
            ),
            recovery_status=recovery_status,
        )

    def finalize_success(self, sequence: int) -> tuple[str, Mapping[str, JSONValue]]:
        """Close a fully persisted final response without external dispatch."""

        checkpoint, envelope = self._current(sequence)
        plan = plan_read_only_recovery(checkpoint, envelope, self.config, task=self.task)
        if (
            plan.decision.action is not ReconstructionAction.FINALIZE_SUCCESS
            or plan.final_text is None
        ):
            raise RecoveryExecutionError("RECOVERY_SUCCESS_NOT_APPLICABLE")
        completed = finalize_recovery_success(
            self.state_dir,
            self.run_id,
            expected_sequence=sequence,
            final_text_length=len(plan.final_text),
        )
        self._notify_phase(RunPhase.SUCCESS)
        return plan.final_text, completed

    def finalize_blocked_action(self, sequence: int) -> tuple[int, Mapping[str, JSONValue]]:
        """Fail one complete recovered action request without dispatching it."""

        checkpoint, envelope = self._current(sequence)
        plan = plan_read_only_recovery(checkpoint, envelope, self.config, task=self.task)
        if (
            plan.decision.action is not ReconstructionAction.FINALIZE_BLOCKED
            or plan.blocked_call_count is None
        ):
            raise RecoveryExecutionError("RECOVERY_BLOCKED_NOT_APPLICABLE")
        completed = finalize_recovery_blocked_action(
            self.state_dir,
            self.run_id,
            expected_sequence=sequence,
        )
        self._notify_phase(RunPhase.FAILED)
        return plan.blocked_call_count, completed


async def execute_read_only_recovery_step(
    checkpoint: Mapping[str, JSONValue],
    envelope: ContinuationEnvelope,
    config: AgentConfig,
    *,
    task: str,
    provider: ModelProviderPort | None,
    desktop: DesktopMCPPort | None,
    commit_intent: Callable[[int, str, ReconstructionAction], None],
    commit_completion: Callable[[int, str, ReadOnlyRecoveryStep], None] | None = None,
    use_stateless_replay: bool = False,
) -> ReadOnlyRecoveryStep:
    """Commit and execute exactly one newly authorized read-only boundary.

    The caller must invoke this while holding the run lock. ``commit_intent``
    must atomically compare the supplied checkpoint sequence, advance it, and
    durably persist the new dispatch intent before returning.
    """

    if not callable(commit_intent):
        raise ValueError("commit_intent must be callable")
    plan = plan_read_only_recovery(checkpoint, envelope, config, task=task)
    sequence = envelope.payload["checkpoint_sequence"]
    run_id = envelope.payload["run_id"]
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        raise RecoveryExecutionError("RECOVERY_SEQUENCE_INVALID")
    if not isinstance(run_id, str):
        raise RecoveryExecutionError("RECOVERY_IDENTITY_INVALID")
    topology = _validated_recovery_topology(envelope)
    budget = _mapping(envelope.payload["budget"], "CONTINUATION_INVALID")
    if not _recovery_budget_available(plan.decision.action, topology, budget):
        raise RecoveryExecutionError("RECOVERY_BUDGET_EXHAUSTED")

    if plan.decision.action in {
        ReconstructionAction.DISPATCH_OBSERVATION,
        ReconstructionAction.MANDATORY_REOBSERVE,
    }:
        assert plan.call is not None
        if desktop is None:
            raise RecoveryExecutionError("RECOVERY_DESKTOP_REQUIRED")
        spec = get_tool_spec(plan.call.name)
        if not set(spec.required_safety_baselines).issubset(desktop.satisfied_safety_baselines):
            raise RecoveryExecutionError("RECOVERY_SAFETY_BASELINE_UNSATISFIED")
        operation_id = (
            f"{plan.call.identity.run_id}:{plan.call.identity.turn_id}:{plan.call.identity.call_id}"
        )
        commit_intent(sequence, operation_id, plan.decision.action)
        authorized = replace(plan.call, status=ToolCallStatus.AUTHORIZED)
        result = await desktop.call_tool(authorized)
        if result.identity != plan.call.identity or result.tool_name != plan.call.name:
            raise RecoveryExecutionError("RECOVERY_TOOL_RESULT_IDENTITY_MISMATCH")
        try:
            validate_tool_result(authorized, result)
        except ToolValidationError as exc:
            raise RecoveryExecutionError("RECOVERY_TOOL_RESULT_INVALID") from exc
        step = ReadOnlyRecoveryStep(plan, tool_result=result)
        if commit_completion is not None:
            commit_completion(sequence + 1, operation_id, step)
        return step

    if plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
        assert plan.result is not None
        if provider is None:
            raise RecoveryExecutionError("RECOVERY_PROVIDER_REQUIRED")
        match = fullmatch(r"turn_([1-9][0-9]{0,8})", plan.result.identity.turn_id)
        if match is None:
            raise RecoveryExecutionError("RECOVERY_TURN_ID_INVALID")
        turn_id = f"turn_{int(match.group(1)) + 1}"
        provider_state = envelope.payload["provider_state"]
        if not isinstance(provider_state, Mapping):
            raise RecoveryExecutionError("RECOVERY_PROVIDER_STATE_INVALID")
        recovery_tools = _recovery_tools(envelope, desktop)
        advertised_tool_names = frozenset(tool.name for tool in recovery_tools)
        provider.restore_continuation(run_id, provider_state, tools=recovery_tools)
        if use_stateless_replay:
            prepare_replay = getattr(provider, "prepare_stateless_replay", None)
            if not callable(prepare_replay):
                raise RecoveryExecutionError("STATELESS_REPLAY_UNAVAILABLE")
            prepare_replay(run_id, envelope, tools=recovery_tools)
        operation_id = f"{run_id}:{turn_id}:provider"
        commit_intent(sequence, operation_id, plan.decision.action)
        ledger = (
            LedgerEvent(
                event_id=f"{run_id}:recovery:provider_input",
                kind=LedgerEventKind.TOOL_RESULT,
                identity=plan.result.identity,
                tool_result=plan.result,
            ),
        )
        turn = await provider.create_turn(
            run_id=run_id,
            turn_id=turn_id,
            task=task,
            ledger=ledger,
            tools=recovery_tools,
        )
        if turn.run_id != run_id or turn.turn_id != turn_id:
            raise RecoveryExecutionError("RECOVERY_PROVIDER_TURN_IDENTITY_MISMATCH")
        if any(call.name not in advertised_tool_names for call in turn.tool_calls):
            raise RecoveryExecutionError("RECOVERY_PROVIDER_TOOL_NOT_ADVERTISED")
        try:
            for call in turn.tool_calls:
                if call.identity.run_id != run_id or call.identity.turn_id != turn_id:
                    raise ToolValidationError("tool-call identity mismatch")
                if dict(call.arguments) != validate_tool_arguments(call.name, call.arguments):
                    raise ToolValidationError("tool arguments are not canonical")
        except ToolValidationError as exc:
            raise RecoveryExecutionError("RECOVERY_PROVIDER_TURN_INVALID") from exc
        step = ReadOnlyRecoveryStep(
            plan,
            model_turn=turn,
            provider_state=provider.export_continuation(run_id),
        )
        if commit_completion is not None:
            commit_completion(sequence + 1, operation_id, step)
        return step

    raise RecoveryExecutionError("RECOVERY_PLAN_NOT_EXECUTABLE")


__all__ = [
    "ReadOnlyRecoveryPlan",
    "ReadOnlyRecoveryStep",
    "LockedRecoveryPersistence",
    "RecoveryExecutionError",
    "RecoveryPlanError",
    "execute_read_only_recovery_step",
    "plan_read_only_recovery",
]
