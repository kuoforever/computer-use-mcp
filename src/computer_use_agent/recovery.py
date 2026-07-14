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
    ReconstructionAction,
    ReconstructionContext,
    ReconstructionDecision,
    ReconstructionPhase,
    classify_operation_state,
)
from .tool_registry import (
    REVIEWED_TOOLS,
    ToolValidationError,
    get_tool_spec,
    reviewed_registry_digest,
    validate_tool_arguments,
    validate_tool_result,
)
from .run_lock import RunLock
from .trace import RunPhase, advance_recovery_checkpoint, read_run_checkpoint
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
        elif self.decision.action is ReconstructionAction.MANDATORY_REOBSERVE:
            if self.call is None or self.result is not None:
                raise ValueError("mandatory re-observation plan requires exactly one call")
        elif self.call is not None or self.result is not None:
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
        usage = _mapping(
            model_turn.get("usage"), "CONTINUATION_PROVIDER_STATE_INVALID"
        )
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


def _completed_tool(
    envelope: ContinuationEnvelope, *, required_effect: ToolEffect
) -> tuple[ToolCall, ToolResult]:
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
    if spec.effect is not required_effect:
        raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
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


def _completed_observation(envelope: ContinuationEnvelope) -> tuple[ToolCall, ToolResult]:
    return _completed_tool(envelope, required_effect=ToolEffect.OBSERVATION)


def _completed_side_effect(envelope: ContinuationEnvelope) -> tuple[ToolCall, ToolResult]:
    return _completed_tool(envelope, required_effect=ToolEffect.SIDE_EFFECT)


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
    if next_step in {"dispatch_observation", "mandatory_reobserve"}:
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
        if next_step == "stop":
            return ReadOnlyRecoveryPlan(
                ReconstructionDecision(
                    ReconstructionAction.START_NEW_RUN,
                    "RECOVERY_STEP_COMPLETED",
                    ReconstructionPhase.FAILED,
                )
            )
        call, result = _completed_observation(envelope)
        expected_id = (
            f"{result.identity.run_id}:{result.identity.turn_id}:{result.identity.call_id}"
        )
        if envelope.operation_state.operation_id != expected_id:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        _validate_provider_correlation(envelope, call)
        return ReadOnlyRecoveryPlan(decision, result=result)
    if decision.action is ReconstructionAction.MANDATORY_REOBSERVE:
        call, result = _completed_side_effect(envelope)
        expected_id = (
            f"{result.identity.run_id}:{result.identity.turn_id}:{result.identity.call_id}"
        )
        if envelope.operation_state.operation_id != expected_id:
            raise RecoveryPlanError("CONTINUATION_LEDGER_INVALID")
        _validate_provider_correlation(envelope, call)
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
        mandatory_call = ToolCall(identity, "ui_snapshot", {})
        return ReadOnlyRecoveryPlan(decision, call=mandatory_call)
    return ReadOnlyRecoveryPlan(decision)


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
    ) -> None:
        if (
            not lock.acquired
            or lock.lock_dir.resolve(strict=False)
            != config.application_state_dir.resolve(strict=False)
        ):
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

    @staticmethod
    def _copy_payload(envelope: ContinuationEnvelope) -> dict[str, object]:
        return {
            key: value
            for key, value in envelope.payload.items()
            if key != "payload_digest"
        }

    def _assert_locked(self) -> None:
        if not self.lock.acquired:
            raise RecoveryExecutionError("RECOVERY_RUN_LOCK_REQUIRED")

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

    def commit_intent(
        self, sequence: int, operation_id: str, action: ReconstructionAction
    ) -> None:
        """Persist a new, uniquely identified dispatch intent before I/O."""

        _, envelope = self._current(sequence)
        if action is not self.plan.decision.action or self._intent_operation_id is not None:
            raise RecoveryExecutionError("RECOVERY_INTENT_MISMATCH")
        payload = self._copy_payload(envelope)
        boundary = payload.get("boundary")
        ledger = payload.get("ledger")
        budget = payload.get("budget")
        if not isinstance(boundary, Mapping) or not isinstance(ledger, list) or not isinstance(budget, Mapping):
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
            updated_budget["tool_calls_used"] = int(updated_budget["tool_calls_used"]) + 1
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
        if not isinstance(ledger, list) or not isinstance(budget, Mapping) or not isinstance(observation, Mapping):
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
            mandatory = (
                step.plan.decision.action
                is ReconstructionAction.MANDATORY_REOBSERVE
            )
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
                else ToolEffect.SIDE_EFFECT.value if effects else None
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
                    if step.plan.decision.action
                    is ReconstructionAction.MANDATORY_REOBSERVE
                    else RunPhase.PLANNING
                )
            ),
            recovery_status=recovery_status,
        )


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

    if plan.decision.action in {
        ReconstructionAction.DISPATCH_OBSERVATION,
        ReconstructionAction.MANDATORY_REOBSERVE,
    }:
        assert plan.call is not None
        if desktop is None:
            raise RecoveryExecutionError("RECOVERY_DESKTOP_REQUIRED")
        operation_id = (
            f"{plan.call.identity.run_id}:{plan.call.identity.turn_id}:"
            f"{plan.call.identity.call_id}"
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
        provider.restore_continuation(run_id, provider_state)
        if use_stateless_replay:
            prepare_replay = getattr(provider, "prepare_stateless_replay", None)
            if not callable(prepare_replay):
                raise RecoveryExecutionError("STATELESS_REPLAY_UNAVAILABLE")
            prepare_replay(run_id, envelope)
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
        try:
            for call in turn.tool_calls:
                if call.identity.run_id != run_id or call.identity.turn_id != turn_id:
                    raise ToolValidationError("tool-call identity mismatch")
                if dict(call.arguments) != validate_tool_arguments(
                    call.name, call.arguments
                ):
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
