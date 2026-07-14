"""Strict, pure planning for the two reviewed read-only crash boundaries."""
from __future__ import annotations

from base64 import b64decode
from dataclasses import dataclass, replace
from re import fullmatch
from typing import Callable, Mapping

from .config import AgentConfig
from .continuation import ContinuationEnvelope
from .reconstruction import (
    OperationEffect,
    ReconstructionAction,
    ReconstructionContext,
    ReconstructionDecision,
    classify_operation_state,
)
from .tool_registry import (
    REVIEWED_TOOLS,
    ToolValidationError,
    get_tool_spec,
    reviewed_registry_digest,
    validate_tool_arguments,
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

    def __post_init__(self) -> None:
        if self.decision.action is ReconstructionAction.DISPATCH_OBSERVATION:
            if self.call is None or self.result is not None:
                raise ValueError("observation dispatch plan requires exactly one call")
        elif self.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
            if self.result is None or self.call is not None:
                raise ValueError("provider continuation plan requires exactly one result")
        elif self.call is not None or self.result is not None:
            raise ValueError("non-executable recovery plan cannot carry external work")


@dataclass(frozen=True)
class ReadOnlyRecoveryStep:
    plan: ReadOnlyRecoveryPlan
    tool_result: ToolResult | None = None
    model_turn: ModelTurn | None = None

    def __post_init__(self) -> None:
        if self.plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION:
            if self.tool_result is None or self.model_turn is not None:
                raise ValueError("observation recovery requires exactly one tool result")
        elif self.plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
            if self.model_turn is None or self.tool_result is not None:
                raise ValueError("provider recovery requires exactly one model turn")
        else:
            raise ValueError("a recovery step requires an executable plan")


def _mapping(value: object, code: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RecoveryPlanError(code)
    return value


def _identity(value: object, run_id: str) -> CallIdentity:
    raw = _mapping(value, "CONTINUATION_LEDGER_INVALID")
    if set(raw) != {"run_id", "turn_id", "call_id"} or raw.get("run_id") != run_id:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        return CallIdentity(
            str(raw["run_id"]), str(raw["turn_id"]), str(raw["call_id"])
        )
    except (KeyError, ValueError) as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc


def _ledger(envelope: ContinuationEnvelope) -> list[Mapping[str, object]]:
    raw = envelope.payload["ledger"]
    if not isinstance(raw, list) or not raw:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return [_mapping(event, "CONTINUATION_LEDGER_INVALID") for event in raw]


def _last_event(
    events: list[Mapping[str, object]], kind: str
) -> Mapping[str, object]:
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
    envelope: ContinuationEnvelope, call: ToolCall
) -> None:
    payload = envelope.payload
    provider = _mapping(payload.get("provider"), "CONTINUATION_PROVIDER_STATE_INVALID")
    state = _mapping(
        payload.get("provider_state"), "CONTINUATION_PROVIDER_STATE_INVALID"
    )
    model_turn = _last_event(_ledger(envelope), "model_turn")
    if provider.get("name") == "openai":
        if state.get("response_id") != model_turn.get("provider_response_id"):
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
        block
        for block in content
        if isinstance(block, Mapping) and block.get("type") == "tool_use"
    ]
    if len(tool_uses) != 1:
        raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")
    tool_use = tool_uses[0]
    if (
        tool_use.get("id") != call.identity.call_id
        or tool_use.get("name") != call.name
        or tool_use.get("input") != call.arguments
    ):
        raise RecoveryPlanError("CONTINUATION_PROVIDER_STATE_INVALID")


def _pending_observation(envelope: ContinuationEnvelope) -> ToolCall:
    data = _last_event(_ledger(envelope), "model_turn")
    calls = data.get("tool_calls")
    if not isinstance(calls, list) or len(calls) != 1:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    raw = _mapping(calls[0], "CONTINUATION_LEDGER_INVALID")
    if set(raw) != {"identity", "tool_name", "arguments", "call_digest"}:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    identity = _identity(raw["identity"], str(envelope.payload["run_id"]))
    name = raw.get("tool_name")
    if not isinstance(name, str):
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        spec = get_tool_spec(name)
    except ToolValidationError as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc
    if spec.effect is not ToolEffect.OBSERVATION:
        raise RecoveryPlanError("PENDING_SIDE_EFFECT")
    call = _validated_call(name, identity, raw.get("arguments"))
    if raw.get("call_digest") != call.digest:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    return call


def _completed_observation(envelope: ContinuationEnvelope) -> tuple[ToolCall, ToolResult]:
    events = _ledger(envelope)
    call_data = _last_event(events, "tool_call")
    result_data = _last_event(events, "tool_result")
    call_identity = _identity(call_data.get("identity"), str(envelope.payload["run_id"]))
    result_identity = _identity(
        result_data.get("identity"), str(envelope.payload["run_id"])
    )
    if call_identity != result_identity:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    name = call_data.get("tool_name")
    if not isinstance(name, str) or result_data.get("tool_name") != name:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        spec = get_tool_spec(name)
    except ToolValidationError as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc
    if spec.effect is not ToolEffect.OBSERVATION:
        raise RecoveryPlanError("PENDING_SIDE_EFFECT")
    call = _validated_call(name, call_identity, call_data.get("arguments"))
    if call_data.get("call_digest") != call.digest:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
    try:
        status = ToolResultStatus(str(result_data["status"]))
        dispatch = DispatchCertainty(str(result_data["dispatch"]))
        images_raw = result_data.get("images", [])
        if not isinstance(images_raw, list):
            raise ValueError
        images = tuple(
            ImageContent(
                mime_type=str(_mapping(image, "CONTINUATION_LEDGER_INVALID")["mime_type"]),
                data=b64decode(str(_mapping(image, "CONTINUATION_LEDGER_INVALID")["data"]), validate=True),
                width=int(_mapping(image, "CONTINUATION_LEDGER_INVALID")["width"]),
                height=int(_mapping(image, "CONTINUATION_LEDGER_INVALID")["height"]),
            )
            for image in images_raw
        )
        code = result_data.get("code")
        if code is not None and not isinstance(code, str):
            raise ValueError
        text = result_data.get("sanitized_text", "")
        if not isinstance(text, str):
            raise ValueError
        return (
            call,
            ToolResult(
                result_identity,
                name,
                status,
                dispatch,
                sanitized_text=text,
                code=code,
                images=images,
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID") from exc


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
    boundary = _mapping(payload["boundary"], "CONTINUATION_INVALID")
    raw_effect = boundary.get("effect")
    pending_effect = None if raw_effect is None else OperationEffect(str(raw_effect))
    next_step = boundary.get("next_step")
    if next_step == "dispatch_observation":
        budget_available = int(budget["tool_calls_used"]) < int(budget["max_tool_calls"])
    elif next_step == "provider_continue":
        budget_available = (
            int(budget["model_turns_used"]) < int(budget["max_model_turns"])
            and int(budget["input_tokens_used"]) < int(budget["max_input_tokens"])
        )
    else:
        budget_available = True
    context = ReconstructionContext(
        identity_matches=identity_matches,
        sequence_matches=sequence_matches,
        budget_available=budget_available,
        pending_effect=pending_effect,
    )
    decision = classify_operation_state(envelope.operation_state, context=context)
    if decision.action is ReconstructionAction.DISPATCH_OBSERVATION:
        call = _pending_observation(envelope)
        expected_id = f"{call.identity.run_id}:{call.identity.turn_id}:provider"
        if envelope.operation_state.operation_id != expected_id:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        _validate_provider_correlation(envelope, call)
        return ReadOnlyRecoveryPlan(decision, call=call)
    if decision.action is ReconstructionAction.CONTINUE_PROVIDER:
        call, result = _completed_observation(envelope)
        expected_id = (
            f"{result.identity.run_id}:{result.identity.turn_id}:{result.identity.call_id}"
        )
        if envelope.operation_state.operation_id != expected_id:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        _validate_provider_correlation(envelope, call)
        return ReadOnlyRecoveryPlan(decision, result=result)
    return ReadOnlyRecoveryPlan(decision)


async def execute_read_only_recovery_step(
    checkpoint: Mapping[str, JSONValue],
    envelope: ContinuationEnvelope,
    config: AgentConfig,
    *,
    task: str,
    provider: ModelProviderPort,
    desktop: DesktopMCPPort,
    commit_intent: Callable[[int, str, ReconstructionAction], None],
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

    if plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION:
        assert plan.call is not None
        operation_id = (
            f"{plan.call.identity.run_id}:{plan.call.identity.turn_id}:"
            f"{plan.call.identity.call_id}"
        )
        commit_intent(sequence, operation_id, plan.decision.action)
        authorized = replace(plan.call, status=ToolCallStatus.AUTHORIZED)
        result = await desktop.call_tool(authorized)
        if result.identity != plan.call.identity or result.tool_name != plan.call.name:
            raise RecoveryExecutionError("RECOVERY_TOOL_RESULT_IDENTITY_MISMATCH")
        return ReadOnlyRecoveryStep(plan, tool_result=result)

    if plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER:
        assert plan.result is not None
        match = fullmatch(r"turn_([1-9][0-9]{0,8})", plan.result.identity.turn_id)
        if match is None:
            raise RecoveryExecutionError("RECOVERY_TURN_ID_INVALID")
        turn_id = f"turn_{int(match.group(1)) + 1}"
        provider_state = envelope.payload["provider_state"]
        if not isinstance(provider_state, Mapping):
            raise RecoveryExecutionError("RECOVERY_PROVIDER_STATE_INVALID")
        provider.restore_continuation(run_id, provider_state)
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
            tools=REVIEWED_TOOLS,
        )
        if turn.run_id != run_id or turn.turn_id != turn_id:
            raise RecoveryExecutionError("RECOVERY_PROVIDER_TURN_IDENTITY_MISMATCH")
        return ReadOnlyRecoveryStep(plan, model_turn=turn)

    raise RecoveryExecutionError("RECOVERY_PLAN_NOT_EXECUTABLE")


__all__ = [
    "ReadOnlyRecoveryPlan",
    "ReadOnlyRecoveryStep",
    "RecoveryExecutionError",
    "RecoveryPlanError",
    "execute_read_only_recovery_step",
    "plan_read_only_recovery",
]
