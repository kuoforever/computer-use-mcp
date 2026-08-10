from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Mapping

import pytest

from computer_use_agent.config import (
    AgentConfig,
    ContinuationConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.continuation import (
    ContinuationEnvelope,
    ContinuationError,
    RuntimeContinuationRecorder,
    continuation_path,
    read_continuation,
    write_continuation,
)
from computer_use_agent.fakes import FakeDesktopMCP, FakeModelProvider
from computer_use_agent.recovery import (
    LockedRecoveryPersistence,
    RecoveryExecutionError,
    RecoveryPlanError,
    execute_read_only_recovery_step,
    plan_read_only_recovery,
)
from computer_use_agent.reconstruction import OperationResult, ReconstructionAction
from computer_use_agent.run_lock import RunLock
from computer_use_agent.tool_registry import (
    REVIEWED_TOOLS,
    configured_optional_tool_names,
    reviewed_registry_digest,
)
from computer_use_agent.trace import (
    RunPhase,
    RunRecorder,
    TraceError,
    finalize_recovery_success,
    read_run_checkpoint,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    JSONValue,
    ModelUsage,
    ModelTurn,
    RecoveryStatus,
    RunBudget,
    RunState,
    ToolCall,
    ToolCallStatus,
    ToolEffect,
    ToolResult,
    ToolResultStatus,
)


E2_FIXTURE = Path(__file__).parents[2] / "evals" / "e2-crash-reconstruction.json"
E2_CASES = json.loads(E2_FIXTURE.read_text(encoding="utf-8"))["cases"]


def _config(tmp_path: Path, monkeypatch: object) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))  # type: ignore[attr-defined]
    return AgentConfig(
        state_dir=local / "computer-use-agent" / "recovery-test",
        policy_version="policy-v1",
        provider=ProviderConfig("openai", "model-v1"),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=4),
        continuation=ContinuationConfig(enabled=True),
    )


def _state(run_id: str = "run_1") -> RunState:
    return RunState(
        run_id,
        "Inspect windows",
        "policy-v1",
        0,
        RunBudget(4, 4, 8, model_turns_used=1),
    )


def _recorder(
    config: AgentConfig,
    state: RunState,
    *,
    provider_name: str = "openai",
    advertised_tool_names: frozenset[str] = frozenset(tool.name for tool in REVIEWED_TOOLS),
) -> RuntimeContinuationRecorder:
    return RuntimeContinuationRecorder(
        state_dir=config.state_dir,
        state=state,
        provider_name=provider_name,
        provider_model="model-v1",
        registry_digest=reviewed_registry_digest(
            configured_optional_tool_names(config.mcp.environment)
        ),
        advertised_tool_names=advertised_tool_names,
        ttl_seconds=900,
        mcp_generation=1,
    )


def _checkpoint(state: RunState, sequence: int) -> dict[str, object]:
    budget = state.budgets
    return {
        "run_id": state.run_id,
        "policy_version": state.policy_version,
        "task_length": len(state.task),
        "checkpoint_sequence": sequence,
        "recovery_status": state.recovery_status.value,
        "observation_epoch": state.observation_epoch,
        "verified_observation_epoch": state.verified_observation_epoch,
        "budgets": {
            "max_model_turns": budget.max_model_turns,
            "max_tool_calls": budget.max_tool_calls,
            "max_side_effects": budget.max_side_effects,
            "max_input_tokens": budget.max_input_tokens,
            "model_turns_used": budget.model_turns_used,
            "tool_calls_used": budget.tool_calls_used,
            "side_effects_used": budget.side_effects_used,
            "input_tokens_used": budget.input_tokens_used,
        },
    }


def _replace_next_step(
    config: AgentConfig,
    envelope: ContinuationEnvelope,
    next_step: str,
) -> ContinuationEnvelope:
    payload = json.loads(json.dumps(envelope.payload))
    payload.pop("payload_digest")
    payload["boundary"]["next_step"] = next_step
    return write_continuation(config.state_dir, payload)


def _safe_checkpoint(config: AgentConfig, state: RunState, sequence: int) -> dict[str, object]:
    recorder = RunRecorder(config.state_dir, state.run_id)
    recorder.start(state)
    if sequence >= 2:
        recorder.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    if sequence >= 3:
        recorder.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    while recorder.checkpoint_sequence < sequence:
        recorder.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    return read_run_checkpoint(config.state_dir, state.run_id)


def _completed_observation(
    config: AgentConfig,
    state: RunState,
    *,
    call: ToolCall,
    advertised_tool_names: frozenset[str],
    usage: ModelUsage | None = None,
) -> tuple[RunState, ContinuationEnvelope, ToolResult]:
    recorder = _recorder(
        config,
        state,
        advertised_tool_names=advertised_tool_names,
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    turn_usage = usage or ModelUsage()
    recorder.complete_provider(
        state,
        ModelTurn(
            state.run_id,
            "turn_1",
            "response_1",
            "",
            (call,),
            turn_usage,
        ),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": (turn_usage.input_tokens or 0)
            + (turn_usage.output_tokens or 0),
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=replace(state.budgets, tool_calls_used=1),
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="observation",
    )
    recorder.prepare_tool(tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4)
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    envelope = recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    return tool_state, envelope, result


def _completed_side_effect(
    config: AgentConfig,
    state: RunState,
    *,
    unknown: bool,
    status: ToolResultStatus | None = None,
    dispatch: DispatchCertainty | None = None,
    code: str | None = None,
) -> tuple[RunState, ContinuationEnvelope, ToolResult]:
    call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "click",
        {"ref": "ref_1"},
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        budgets=replace(
            state.budgets,
            tool_calls_used=1,
            side_effects_used=1,
        ),
        recovery_status=(
            RecoveryStatus.UNKNOWN_OUTCOME if unknown else RecoveryStatus.REQUIRES_REOBSERVATION
        ),
    )
    result = ToolResult(
        call.identity,
        call.name,
        status or (ToolResultStatus.UNKNOWN_OUTCOME if unknown else ToolResultStatus.SUCCESS),
        dispatch or DispatchCertainty.DISPATCHED,
        code=code if code is not None else ("NATIVE_AUTHORITY_LOST" if unknown else None),
    )
    recorder.prepare_tool(
        tool_state,
        call,
        effect=ToolEffect.SIDE_EFFECT,
        checkpoint_sequence=4,
    )
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    envelope = recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    return tool_state, envelope, result


def _provider_state_for_turn(
    provider_name: str,
    state: RunState,
    response_id: str,
    *,
    text: str,
    calls: tuple[ToolCall, ...],
    prior_state: Mapping[str, JSONValue] | None = None,
    prior_result: ToolResult | None = None,
    prior_results: tuple[ToolResult, ...] | None = None,
) -> Mapping[str, JSONValue]:
    if provider_name == "openai":
        prior_batches = [] if prior_state is None else prior_state.get("output_batches", [])
        assert isinstance(prior_batches, list)
        items: list[JSONValue] = [
            {
                "type": "function_call",
                "name": call.name,
                "call_id": call.identity.call_id,
                "arguments": json.dumps(
                    dict(call.arguments),
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
            for call in calls
        ]
        return {
            "response_id": response_id,
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [
                *prior_batches,
                {"response_id": response_id, "items": items},
            ],
        }
    prior_messages = [] if prior_state is None else prior_state.get("messages", [])
    assert isinstance(prior_messages, list)
    messages: list[JSONValue] = (
        [{"role": "user", "content": state.task}] if not prior_messages else list(prior_messages)
    )
    if prior_result is not None and prior_results is not None:
        raise AssertionError("pass either prior_result or prior_results")
    results = prior_results or (() if prior_result is None else (prior_result,))
    if results:
        content: list[JSONValue] = []
        for result in results:
            result_payload: dict[str, JSONValue] = {
                "ok": result.ok,
                "status": result.status.value,
            }
            if result.code is not None:
                result_payload["code"] = result.code
            if result.sanitized_text:
                result_payload["content"] = result.sanitized_text
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": result.identity.call_id,
                    "content": json.dumps(
                        result_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "is_error": not result.ok,
                }
            )
        messages.append(
            {
                "role": "user",
                "content": content,
            }
        )
    content: list[JSONValue] = []
    if text:
        content.append({"type": "text", "text": text})
    content.extend(
        {
            "type": "tool_use",
            "id": call.identity.call_id,
            "name": call.name,
            "input": dict(call.arguments),
        }
        for call in calls
    )
    messages.append({"role": "assistant", "content": content})
    return {"messages": messages}


def _completed_final_after_side_effect(
    config: AgentConfig,
    state: RunState,
    *,
    status: ToolResultStatus = ToolResultStatus.SUCCESS,
    dispatch: DispatchCertainty = DispatchCertainty.DISPATCHED,
    code: str | None = None,
    verify_after: bool = False,
    complete_final: bool = True,
    stop_with_verification_pending: bool = False,
) -> tuple[RunState, ContinuationEnvelope, int]:
    provider_name = config.provider.name
    recorder = _recorder(config, state, provider_name=provider_name)
    observation_call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "ui_snapshot",
        {},
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_1",
        text="",
        calls=(observation_call,),
    )
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (observation_call,)),
        provider_state=provider_state,
        checkpoint_sequence=3,
    )
    observed = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=replace(state.budgets, tool_calls_used=1),
    )
    recorder.prepare_tool(
        observed,
        observation_call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=4,
    )
    recorder.dispatch_tool(observed, checkpoint_sequence=5)
    observation_result = ToolResult(
        observation_call.identity,
        observation_call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="verified desktop state",
    )
    recorder.complete_tool(
        observed,
        observation_result,
        checkpoint_sequence=6,
    )

    action_call = ToolCall(
        CallIdentity(state.run_id, "turn_2", "call_2"),
        "click",
        {"ref": "ref_1"},
    )
    action_turn_state = replace(
        observed,
        budgets=replace(observed.budgets, model_turns_used=2),
    )
    recorder.prepare_provider(action_turn_state, "turn_2", checkpoint_sequence=7)
    recorder.dispatch_provider(action_turn_state, checkpoint_sequence=8)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_2",
        text="",
        calls=(action_call,),
        prior_state=provider_state,
        prior_result=observation_result,
    )
    recorder.complete_provider(
        action_turn_state,
        ModelTurn(state.run_id, "turn_2", "response_2", "", (action_call,)),
        provider_state=provider_state,
        checkpoint_sequence=9,
    )
    recovery_status = (
        RecoveryStatus.UNKNOWN_OUTCOME
        if status is ToolResultStatus.UNKNOWN_OUTCOME
        else RecoveryStatus.REQUIRES_REOBSERVATION
        if dispatch is not DispatchCertainty.NOT_DISPATCHED
        or code in {"HUMAN_ACTIVE", "DENIED_BY_GATE"}
        else RecoveryStatus.READY
    )
    action_state = replace(
        action_turn_state,
        verified_observation_epoch=(1 if recovery_status is RecoveryStatus.READY else None),
        budgets=replace(
            action_turn_state.budgets,
            tool_calls_used=2,
            side_effects_used=1,
        ),
        recovery_status=recovery_status,
    )
    recorder.prepare_tool(
        action_state,
        action_call,
        effect=ToolEffect.SIDE_EFFECT,
        checkpoint_sequence=10,
    )
    recorder.dispatch_tool(action_state, checkpoint_sequence=11)
    action_result = ToolResult(
        action_call.identity,
        action_call.name,
        status,
        dispatch,
        code=code,
    )
    action_envelope = recorder.complete_tool(
        action_state,
        action_result,
        checkpoint_sequence=12,
    )
    if not complete_final and not stop_with_verification_pending:
        return action_state, action_envelope, 12

    sequence = 12
    final_state = action_state
    latest_result = action_result
    next_turn = 3
    if verify_after or stop_with_verification_pending:
        verification_call = ToolCall(
            CallIdentity(state.run_id, "turn_3", "call_3"),
            "ui_snapshot",
            {},
        )
        verification_turn_state = replace(
            action_state,
            budgets=replace(action_state.budgets, model_turns_used=3),
        )
        recorder.prepare_provider(
            verification_turn_state,
            "turn_3",
            checkpoint_sequence=13,
        )
        recorder.dispatch_provider(verification_turn_state, checkpoint_sequence=14)
        provider_state = _provider_state_for_turn(
            provider_name,
            state,
            "response_3",
            text="",
            calls=(verification_call,),
            prior_state=provider_state,
            prior_result=action_result,
        )
        verification_envelope = recorder.complete_provider(
            verification_turn_state,
            ModelTurn(state.run_id, "turn_3", "response_3", "", (verification_call,)),
            provider_state=provider_state,
            checkpoint_sequence=15,
        )
        if stop_with_verification_pending:
            return verification_turn_state, verification_envelope, 15
        final_state = replace(
            verification_turn_state,
            observation_epoch=2,
            verified_observation_epoch=2,
            budgets=replace(verification_turn_state.budgets, tool_calls_used=3),
            recovery_status=RecoveryStatus.READY,
        )
        recorder.prepare_tool(
            final_state,
            verification_call,
            effect=ToolEffect.OBSERVATION,
            checkpoint_sequence=16,
        )
        recorder.dispatch_tool(final_state, checkpoint_sequence=17)
        verification_result = ToolResult(
            verification_call.identity,
            verification_call.name,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
            sanitized_text="verified desktop state",
        )
        recorder.complete_tool(
            final_state,
            verification_result,
            checkpoint_sequence=18,
        )
        latest_result = verification_result
        sequence = 18
        next_turn = 4

    final_state = replace(
        final_state,
        budgets=replace(final_state.budgets, model_turns_used=next_turn),
    )
    final_response = f"response_{next_turn}"
    recorder.prepare_provider(
        final_state,
        f"turn_{next_turn}",
        checkpoint_sequence=sequence + 1,
    )
    recorder.dispatch_provider(final_state, checkpoint_sequence=sequence + 2)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        final_response,
        text="done",
        calls=(),
        prior_state=provider_state,
        prior_result=latest_result,
    )
    envelope = recorder.complete_provider(
        final_state,
        ModelTurn(
            state.run_id,
            f"turn_{next_turn}",
            final_response,
            "done",
        ),
        provider_state=provider_state,
        checkpoint_sequence=sequence + 3,
    )
    return final_state, envelope, sequence + 3


def _completed_final_after_nonserial_turn(
    config: AgentConfig,
    state: RunState,
    *,
    call_names: tuple[str, str],
) -> tuple[RunState, ContinuationEnvelope, int]:
    provider_name = config.provider.name
    recorder = _recorder(config, state, provider_name=provider_name)
    observation_call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "ui_snapshot",
        {},
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_1",
        text="",
        calls=(observation_call,),
    )
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (observation_call,)),
        provider_state=provider_state,
        checkpoint_sequence=3,
    )
    current = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=replace(state.budgets, tool_calls_used=1),
    )
    recorder.prepare_tool(
        current,
        observation_call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=4,
    )
    recorder.dispatch_tool(current, checkpoint_sequence=5)
    observation_result = ToolResult(
        observation_call.identity,
        observation_call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="verified desktop state",
    )
    recorder.complete_tool(current, observation_result, checkpoint_sequence=6)

    calls = tuple(
        ToolCall(
            CallIdentity(state.run_id, "turn_2", f"call_{index}"),
            name,
            {} if name == "ui_snapshot" else {"ref": f"ref_{index}"},
        )
        for index, name in enumerate(call_names, start=2)
    )
    current = replace(current, budgets=replace(current.budgets, model_turns_used=2))
    recorder.prepare_provider(current, "turn_2", checkpoint_sequence=7)
    recorder.dispatch_provider(current, checkpoint_sequence=8)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_2",
        text="",
        calls=calls,
        prior_state=provider_state,
        prior_result=observation_result,
    )
    recorder.complete_provider(
        current,
        ModelTurn(state.run_id, "turn_2", "response_2", "", calls),
        provider_state=provider_state,
        checkpoint_sequence=9,
    )

    sequence = 9
    results: list[ToolResult] = []
    for call in calls:
        effect = (
            ToolEffect.OBSERVATION if call.name == "ui_snapshot" else ToolEffect.SIDE_EFFECT
        )
        budgets = replace(
            current.budgets,
            tool_calls_used=current.budgets.tool_calls_used + 1,
            side_effects_used=current.budgets.side_effects_used
            + int(effect is ToolEffect.SIDE_EFFECT),
        )
        if effect is ToolEffect.OBSERVATION:
            current = replace(
                current,
                observation_epoch=current.observation_epoch + 1,
                verified_observation_epoch=current.observation_epoch + 1,
                budgets=budgets,
                recovery_status=RecoveryStatus.READY,
            )
            sanitized_text = "verified desktop state"
        else:
            current = replace(
                current,
                verified_observation_epoch=None,
                budgets=budgets,
                recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
            )
            sanitized_text = ""
        recorder.prepare_tool(
            current,
            call,
            effect=effect,
            checkpoint_sequence=sequence + 1,
        )
        recorder.dispatch_tool(current, checkpoint_sequence=sequence + 2)
        result = ToolResult(
            call.identity,
            call.name,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
            sanitized_text=sanitized_text,
        )
        recorder.complete_tool(current, result, checkpoint_sequence=sequence + 3)
        results.append(result)
        sequence += 3

    current = replace(current, budgets=replace(current.budgets, model_turns_used=3))
    recorder.prepare_provider(current, "turn_3", checkpoint_sequence=sequence + 1)
    recorder.dispatch_provider(current, checkpoint_sequence=sequence + 2)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_3",
        text="done",
        calls=(),
        prior_state=provider_state,
        prior_results=tuple(results),
    )
    envelope = recorder.complete_provider(
        current,
        ModelTurn(state.run_id, "turn_3", "response_3", "done"),
        provider_state=provider_state,
        checkpoint_sequence=sequence + 3,
    )
    return current, envelope, sequence + 3


def _completed_final_after_abandoned_call(
    config: AgentConfig,
    state: RunState,
    *,
    abandoned_name: str,
) -> tuple[RunState, ContinuationEnvelope, int]:
    provider_name = config.provider.name
    recorder = _recorder(config, state, provider_name=provider_name)
    observation_call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "ui_snapshot",
        {},
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_1",
        text="",
        calls=(observation_call,),
    )
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (observation_call,)),
        provider_state=provider_state,
        checkpoint_sequence=3,
    )
    current = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=replace(state.budgets, tool_calls_used=1),
    )
    recorder.prepare_tool(
        current,
        observation_call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=4,
    )
    recorder.dispatch_tool(current, checkpoint_sequence=5)
    observation_result = ToolResult(
        observation_call.identity,
        observation_call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="verified desktop state",
    )
    recorder.complete_tool(current, observation_result, checkpoint_sequence=6)

    abandoned_call = ToolCall(
        CallIdentity(state.run_id, "turn_2", "call_2"),
        abandoned_name,
        {} if abandoned_name == "ui_snapshot" else {"ref": "ref_1"},
    )
    current = replace(current, budgets=replace(current.budgets, model_turns_used=2))
    recorder.prepare_provider(current, "turn_2", checkpoint_sequence=7)
    recorder.dispatch_provider(current, checkpoint_sequence=8)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_2",
        text="",
        calls=(abandoned_call,),
        prior_state=provider_state,
        prior_result=observation_result,
    )
    recorder.complete_provider(
        current,
        ModelTurn(state.run_id, "turn_2", "response_2", "", (abandoned_call,)),
        provider_state=provider_state,
        checkpoint_sequence=9,
    )

    current = replace(current, budgets=replace(current.budgets, model_turns_used=3))
    recorder.prepare_provider(current, "turn_3", checkpoint_sequence=10)
    recorder.dispatch_provider(current, checkpoint_sequence=11)
    provider_state = _provider_state_for_turn(
        provider_name,
        state,
        "response_3",
        text="done",
        calls=(),
        prior_state=provider_state,
    )
    envelope = recorder.complete_provider(
        current,
        ModelTurn(state.run_id, "turn_3", "response_3", "done"),
        provider_state=provider_state,
        checkpoint_sequence=12,
    )
    return current, envelope, 12


@pytest.mark.parametrize("authority_yield_code", ["HUMAN_ACTIVE", "DENIED_BY_GATE"])
def test_completed_authority_yield_requires_observation_without_action_replay(
    tmp_path: Path,
    monkeypatch: object,
    authority_yield_code: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state, envelope, sequence = _completed_final_after_side_effect(
        config,
        _state(),
        status=ToolResultStatus.REJECTED,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code=authority_yield_code,
        complete_final=False,
    )

    assert envelope.payload["observation"] == {
        "epoch": 1,
        "verified_epoch": None,
        "mcp_generation": 1,
    }
    assert envelope.payload["boundary"] == {
        "operation_kind": "tool",
        "stage": "completed",
        "operation_id": f"{state.run_id}:turn_2:call_2",
        "effect": "side_effect",
        "dispatch": "dispatched",
        "next_step": "mandatory_reobserve",
    }
    completed_result = envelope.payload["ledger"][-1]
    assert completed_result["kind"] == "tool_result"
    assert completed_result["data"]["status"] == "rejected"
    assert completed_result["data"]["dispatch"] == "not_dispatched"
    assert completed_result["data"]["code"] == authority_yield_code

    plan = plan_read_only_recovery(
        _checkpoint(state, sequence),
        envelope,
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE
    assert plan.decision.reason == "SIDE_EFFECT_COMPLETED"
    assert plan.call is not None
    assert plan.call.name == "ui_snapshot"
    assert plan.call.identity != CallIdentity(state.run_id, "turn_2", "call_2")


@pytest.mark.parametrize(
    "native_unknown_code",
    ["NATIVE_AUTHORITY_LOST", "NATIVE_OUTCOME_UNKNOWN"],
)
def test_completed_native_unknown_preserves_exact_dispatch_and_stops_recovery(
    tmp_path: Path,
    monkeypatch: object,
    native_unknown_code: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state, envelope, result = _completed_side_effect(
        config,
        _state(),
        unknown=True,
        code=native_unknown_code,
    )

    assert envelope.payload["boundary"]["dispatch"] == "dispatched"
    assert envelope.payload["boundary"]["next_step"] == "stop"
    assert envelope.operation_state.result is OperationResult.UNKNOWN_OUTCOME
    assert envelope.payload["ledger"][-1]["data"]["code"] == native_unknown_code

    plan = plan_read_only_recovery(
        _checkpoint(state, 6),
        envelope,
        config,
        task=state.task,
    )

    assert result.dispatch is DispatchCertainty.DISPATCHED
    assert result.code == native_unknown_code
    assert plan.decision.action is ReconstructionAction.HUMAN_REOBSERVE
    assert plan.decision.reason == "UNKNOWN_OUTCOME"


def test_legacy_v6_unknown_boundary_with_dispatched_ledger_remains_readable(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state, envelope, _result = _completed_side_effect(
        config,
        _state(),
        unknown=True,
    )
    payload = json.loads(json.dumps(envelope.payload))
    payload.pop("payload_digest")
    payload["boundary"]["dispatch"] = "unknown"
    legacy = write_continuation(config.state_dir, payload)

    plan = plan_read_only_recovery(
        _checkpoint(state, 6),
        legacy,
        config,
        task=state.task,
    )

    assert legacy.operation_state.result is OperationResult.UNKNOWN_OUTCOME
    assert plan.decision.action is ReconstructionAction.HUMAN_REOBSERVE


def test_dispatched_unknown_boundary_without_correlated_result_fails_closed(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state, envelope, _result = _completed_side_effect(
        config,
        _state(),
        unknown=True,
    )
    payload = json.loads(json.dumps(envelope.payload))
    payload.pop("payload_digest")
    payload["ledger"] = [event for event in payload["ledger"] if event["kind"] != "tool_result"]
    tampered = write_continuation(config.state_dir, payload)

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(
            _checkpoint(state, 6),
            tampered,
            config,
            task=state.task,
        )


@pytest.mark.parametrize(
    ("status", "dispatch", "code", "expected_boundary", "expected_action"),
    [
        (
            ToolResultStatus.UNKNOWN_OUTCOME,
            DispatchCertainty.UNKNOWN,
            "MCP_PROTOCOL_ERROR",
            "unknown",
            ReconstructionAction.HUMAN_REOBSERVE,
        ),
        (
            ToolResultStatus.ACTION_ERROR,
            DispatchCertainty.DISPATCHED,
            "DRIVER_ERROR",
            "dispatched",
            ReconstructionAction.START_NEW_RUN,
        ),
    ],
)
def test_recovery_synthesized_observation_result_preserves_stop_semantics(
    tmp_path: Path,
    monkeypatch: object,
    status: ToolResultStatus,
    dispatch: DispatchCertainty,
    code: str,
    expected_boundary: str,
    expected_action: ReconstructionAction,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state, envelope, _result = _completed_side_effect(
        config,
        _state(),
        unknown=False,
    )
    checkpoint = _safe_checkpoint(config, state, 6)
    plan = plan_read_only_recovery(
        checkpoint,
        envelope,
        config,
        task=state.task,
    )
    assert plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE
    assert plan.call is not None
    recovery_result = ToolResult(
        plan.call.identity,
        plan.call.name,
        status,
        dispatch,
        code=code,
    )
    desktop = FakeDesktopMCP(results=deque([recovery_result]))
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=None,
                desktop=desktop,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    completed = read_continuation(config.state_dir, state.run_id)
    completed_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    second_plan = plan_read_only_recovery(
        completed_checkpoint,
        completed,
        config,
        task=state.task,
    )

    assert completed.payload["boundary"]["dispatch"] == expected_boundary
    assert second_plan.decision.action is expected_action
    assert second_plan.decision.reason == (
        "UNKNOWN_OUTCOME"
        if expected_action is ReconstructionAction.HUMAN_REOBSERVE
        else "RECOVERY_STEP_COMPLETED"
    )


def test_completed_provider_reconstructs_exactly_one_pending_observation(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    turn = ModelTurn("run_1", "turn_1", "response_1", "", (call,))
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        turn,
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    envelope = read_continuation(config.state_dir, "run_1")

    plan = plan_read_only_recovery(_checkpoint(state, 3), envelope, config, task=state.task)

    assert plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION
    assert plan.call == call
    assert plan.result is None
    assert plan.decision.automatic_resume is False


def test_v8_recovery_requires_the_same_provider_region(
    tmp_path: Path, monkeypatch: object
) -> None:
    global_config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig("minimax", "model-v1", region="global"),
    )
    state = _state()
    recorder = RuntimeContinuationRecorder(
        state_dir=global_config.state_dir,
        state=state,
        provider_name="minimax",
        provider_model="model-v1",
        provider_region="global",
        provider_base_url="https://api.minimax.io/anthropic",
        registry_digest=reviewed_registry_digest(),
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        ttl_seconds=900,
        mcp_generation=1,
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "message_1", "done"),
        provider_state={
            "messages": [
                {"role": "user", "content": state.task},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                },
            ]
        },
        checkpoint_sequence=3,
    )
    envelope = read_continuation(global_config.state_dir, state.run_id)
    checkpoint = _checkpoint(state, 3)

    matching = plan_read_only_recovery(
        checkpoint, envelope, global_config, task=state.task
    )
    cn_config = replace(
        global_config,
        provider=ProviderConfig("minimax", "model-v1", region="cn"),
    )
    mismatched = plan_read_only_recovery(
        checkpoint, envelope, cn_config, task=state.task
    )

    assert matching.decision.action is ReconstructionAction.FINALIZE_SUCCESS
    assert mismatched.decision.action is ReconstructionAction.START_NEW_RUN
    assert mismatched.decision.reason == "CHECKPOINT_MISMATCH"


def test_completed_observation_reconstructs_result_without_mcp_replay(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    turn = ModelTurn("run_1", "turn_1", "response_1", "", (call,))
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        turn,
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = RunState(
        state.run_id,
        state.task,
        state.policy_version,
        1,
        RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
        verified_observation_epoch=1,
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder.prepare_tool(tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4)
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    envelope = read_continuation(config.state_dir, "run_1")

    plan = plan_read_only_recovery(
        _checkpoint(tool_state, 6), envelope, config, task=tool_state.task
    )

    assert plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER
    assert plan.result == result
    assert plan.call is None


def test_completed_final_provider_turn_plans_local_success_only(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "done"),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": [{"type": "message"}]}],
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, state.run_id),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS
    assert plan.decision.reason == "PROVIDER_COMPLETED_FINAL"
    assert plan.final_text == "done"
    assert plan.call is None
    assert plan.result is None


def test_final_provider_recovery_rejects_hidden_function_call_output(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "done"),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": [{"type": "function_call"}]}],
        },
        checkpoint_sequence=3,
    )

    with pytest.raises(RecoveryPlanError, match="CONTINUATION_PROVIDER_STATE_INVALID"):
        plan_read_only_recovery(
            _checkpoint(state, 3),
            read_continuation(config.state_dir, state.run_id),
            config,
            task=state.task,
        )


def test_completed_claude_final_turn_also_plans_local_success(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig("anthropic", "model-v1"),
    )
    state = _state()
    recorder = _recorder(config, state, provider_name="anthropic")
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "message_1", "done"),
        provider_state={
            "messages": [
                {"role": "user", "content": state.task},
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "done"}],
                },
            ]
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, state.run_id),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS
    assert plan.final_text == "done"


@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
@pytest.mark.parametrize(
    ("status", "dispatch", "code"),
    [
        (ToolResultStatus.SUCCESS, DispatchCertainty.DISPATCHED, None),
        (
            ToolResultStatus.ACTION_ERROR,
            DispatchCertainty.DISPATCHED,
            "DRIVER_ERROR",
        ),
        (
            ToolResultStatus.REJECTED,
            DispatchCertainty.NOT_DISPATCHED,
            "HUMAN_ACTIVE",
        ),
        (
            ToolResultStatus.REJECTED,
            DispatchCertainty.NOT_DISPATCHED,
            "DENIED_BY_GATE",
        ),
    ],
)
def test_completed_provider_final_preserves_required_verification(
    tmp_path: Path,
    monkeypatch: object,
    provider_name: str,
    status: ToolResultStatus,
    dispatch: DispatchCertainty,
    code: str | None,
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig(provider_name, "model-v1"),
    )
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
        status=status,
        dispatch=dispatch,
        code=code,
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)

    assert plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert plan.decision.reason == "VERIFICATION_REQUIRED"
    assert plan.final_text is None
    with pytest.raises(RecoveryExecutionError, match="^RECOVERY_PLAN_NOT_EXECUTABLE$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        with pytest.raises(
            RecoveryExecutionError,
            match="^RECOVERY_SUCCESS_NOT_APPLICABLE$",
        ):
            persistence.finalize_success(sequence)
        with pytest.raises(TraceError, match="^RECOVERY_SUCCESS_STATE_INVALID$"):
            finalize_recovery_success(
                config.state_dir,
                state.run_id,
                expected_sequence=sequence,
                final_text_length=len("done"),
            )
    finally:
        lock.release()

    assert provider.calls == []
    assert provider.continuation_state == {}
    assert provider.restored_tools == {}
    assert desktop.tool_calls == []
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
def test_successful_verification_allows_completed_provider_finalization(
    tmp_path: Path,
    monkeypatch: object,
    provider_name: str,
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig(provider_name, "model-v1"),
    )
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
        verify_after=True,
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)

    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)

    assert plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS
    assert plan.final_text == "done"
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        text, completed = persistence.finalize_success(sequence)
    finally:
        lock.release()

    assert text == "done"
    assert completed["phase"] == RunPhase.SUCCESS.value
    assert completed["recovery_status"] == RecoveryStatus.READY.value
    assert completed["observation_epoch"] == 2
    assert completed["verified_observation_epoch"] == 2
    assert not continuation_path(config.state_dir, state.run_id).exists()


@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "call_names",
    [
        ("click", "ui_snapshot"),
        ("ui_snapshot", "click"),
        ("click", "click"),
    ],
    ids=["action-observation", "observation-action", "action-action"],
)
def test_complete_ledger_rejects_historical_nonserial_side_effect_turn(
    tmp_path: Path,
    monkeypatch: object,
    provider_name: str,
    call_names: tuple[str, str],
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig(provider_name, "model-v1"),
    )
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_nonserial_turn(
        config,
        state,
        call_names=call_names,
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert provider.calls == []
    assert provider.continuation_state == {}
    assert provider.restored_tools == {}
    assert desktop.tool_calls == []
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
@pytest.mark.parametrize("abandoned_name", ["click", "ui_snapshot"])
def test_complete_ledger_rejects_abandoned_provider_call_before_later_turn(
    tmp_path: Path,
    monkeypatch: object,
    provider_name: str,
    abandoned_name: str,
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig(provider_name, "model-v1"),
    )
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_abandoned_call(
        config,
        state,
        abandoned_name=abandoned_name,
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert provider.calls == []
    assert provider.continuation_state == {}
    assert provider.restored_tools == {}
    assert desktop.tool_calls == []
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


@pytest.mark.parametrize("provider_name", ["openai", "anthropic"])
def test_known_not_dispatched_transport_result_does_not_create_verification_debt(
    tmp_path: Path,
    monkeypatch: object,
    provider_name: str,
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig(provider_name, "model-v1"),
    )
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
        status=ToolResultStatus.TRANSPORT_ERROR,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code="MCP_TIMEOUT_BEFORE_DISPATCH",
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)

    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)

    assert plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS
    assert plan.final_text == "done"


@pytest.mark.parametrize(
    ("status", "dispatch", "code", "expected_epoch", "expected_verified_epoch"),
    [
        (ToolResultStatus.SUCCESS, DispatchCertainty.DISPATCHED, None, 2, 2),
        (
            ToolResultStatus.ACTION_ERROR,
            DispatchCertainty.DISPATCHED,
            "DRIVER_ERROR",
            1,
            None,
        ),
        (
            ToolResultStatus.TRANSPORT_ERROR,
            DispatchCertainty.NOT_DISPATCHED,
            "MCP_TIMEOUT_BEFORE_DISPATCH",
            1,
            None,
        ),
    ],
    ids=["success", "dispatched-failure", "known-not-dispatched-failure"],
)
def test_recovery_mandatory_intent_establishes_debt_after_known_not_dispatched_action(
    tmp_path: Path,
    monkeypatch: object,
    status: ToolResultStatus,
    dispatch: DispatchCertainty,
    code: str | None,
    expected_epoch: int,
    expected_verified_epoch: int | None,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
        status=ToolResultStatus.TRANSPORT_ERROR,
        dispatch=DispatchCertainty.NOT_DISPATCHED,
        code="MCP_TIMEOUT_BEFORE_DISPATCH",
        complete_final=False,
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    assert plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE
    assert plan.call is not None
    result = ToolResult(
        plan.call.identity,
        plan.call.name,
        status,
        dispatch,
        code=code,
        sanitized_text="verified desktop state" if status is ToolResultStatus.SUCCESS else "",
    )
    statuses: list[str] = []

    def observe_phase(_phase: RunPhase) -> None:
        statuses.append(str(read_run_checkpoint(config.state_dir, state.run_id)["recovery_status"]))

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
            phase_observer=observe_phase,
        )
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=None,
                desktop=FakeDesktopMCP(results=deque([result])),
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    completed_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    completed_envelope = read_continuation(config.state_dir, state.run_id)
    completed_plan = plan_read_only_recovery(
        completed_checkpoint,
        completed_envelope,
        config,
        task=state.task,
    )
    assert statuses == [
        RecoveryStatus.REQUIRES_REOBSERVATION.value,
        RecoveryStatus.STOPPED.value,
    ]
    assert completed_envelope.payload["observation"]["epoch"] == expected_epoch
    assert (
        completed_envelope.payload["observation"]["verified_epoch"]
        == expected_verified_epoch
    )
    assert completed_checkpoint["recovery_status"] == RecoveryStatus.STOPPED.value
    assert completed_plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert completed_plan.decision.reason == "RECOVERY_STEP_COMPLETED"


def test_host_only_verification_clear_survives_unknown_recovered_observation(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    first_call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "ui_snapshot",
        {},
    )
    observed_state, envelope, _result = _completed_observation(
        config,
        state,
        call=first_call,
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
    )
    host_state = replace(
        observed_state,
        verified_observation_epoch=None,
        recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
    )
    payload = json.loads(json.dumps(envelope.payload))
    payload.pop("payload_digest")
    payload["observation"]["verified_epoch"] = None
    envelope = write_continuation(config.state_dir, payload)
    checkpoint = _safe_checkpoint(config, host_state, 6)
    initial_plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    assert initial_plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER

    pending_call = ToolCall(
        CallIdentity(state.run_id, "turn_2", "call_2"),
        "ui_snapshot",
        {},
    )
    provider = FakeModelProvider(
        turns=deque(
            [ModelTurn(state.run_id, "turn_2", "response_2", "", (pending_call,))]
        )
    )
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        continued = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=FakeDesktopMCP(),
                commit_intent=continued.commit_intent,
                commit_completion=continued.commit_completion,
            )
        )
        pending_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
        pending_envelope = read_continuation(config.state_dir, state.run_id)
        pending_plan = plan_read_only_recovery(
            pending_checkpoint,
            pending_envelope,
            config,
            task=state.task,
        )
        assert pending_plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION
        assert pending_plan.call == pending_call

        unknown_result = ToolResult(
            pending_call.identity,
            pending_call.name,
            ToolResultStatus.UNKNOWN_OUTCOME,
            DispatchCertainty.UNKNOWN,
            code="MCP_PROTOCOL_ERROR",
        )
        observed = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=pending_checkpoint,
            envelope=pending_envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        asyncio.run(
            execute_read_only_recovery_step(
                pending_checkpoint,
                pending_envelope,
                config,
                task=state.task,
                provider=None,
                desktop=FakeDesktopMCP(results=deque([unknown_result])),
                commit_intent=observed.commit_intent,
                commit_completion=observed.commit_completion,
            )
        )
    finally:
        lock.release()

    final_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    final_envelope = read_continuation(config.state_dir, state.run_id)
    final_plan = plan_read_only_recovery(
        final_checkpoint,
        final_envelope,
        config,
        task=state.task,
    )
    assert final_checkpoint["recovery_status"] == RecoveryStatus.UNKNOWN_OUTCOME.value
    assert final_checkpoint["observation_epoch"] == 1
    assert final_checkpoint["verified_observation_epoch"] is None
    assert final_envelope.payload["observation"]["verified_epoch"] is None
    assert final_plan.decision.action is ReconstructionAction.HUMAN_REOBSERVE
    assert final_plan.decision.reason == "UNKNOWN_OUTCOME"


def test_unknown_result_is_terminal_across_later_provider_events(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
        status=ToolResultStatus.UNKNOWN_OUTCOME,
        dispatch=DispatchCertainty.UNKNOWN,
        code="MCP_PROTOCOL_ERROR",
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(checkpoint, envelope, config, task=state.task)

    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


@pytest.mark.parametrize(
    "forgery",
    [
        "recovery_status",
        "observation_epoch",
        "verified_observation_epoch",
        "budget",
    ],
)
def test_checkpoint_certainty_and_counter_swaps_cannot_widen_finalization(
    tmp_path: Path,
    monkeypatch: object,
    forgery: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
    )
    canonical = _safe_checkpoint(config, checkpoint_state, sequence)
    checkpoint = json.loads(json.dumps(canonical))
    if forgery == "recovery_status":
        checkpoint["recovery_status"] = RecoveryStatus.READY.value
    elif forgery == "observation_epoch":
        checkpoint["observation_epoch"] = 0
    elif forgery == "verified_observation_epoch":
        checkpoint["verified_observation_epoch"] = 1
    else:
        checkpoint["budgets"]["tool_calls_used"] = 1
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()

    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)

    assert plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert plan.decision.reason == "CHECKPOINT_MISMATCH"
    assert plan.final_text is None
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


def test_colluding_ready_counters_cannot_override_ledger_verification_debt(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
    )
    payload = json.loads(json.dumps(envelope.payload))
    payload.pop("payload_digest")
    payload["observation"]["verified_epoch"] = 1
    forged = write_continuation(config.state_dir, payload)
    forged_state = replace(
        checkpoint_state,
        recovery_status=RecoveryStatus.READY,
        verified_observation_epoch=1,
    )
    checkpoint = _safe_checkpoint(config, forged_state, sequence)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(checkpoint, forged, config, task=state.task)

    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


def test_failed_recovered_observation_and_provider_final_preserve_verification_debt(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    checkpoint_state, envelope, sequence = _completed_final_after_side_effect(
        config,
        state,
        complete_final=False,
        stop_with_verification_pending=True,
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    initial_plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    assert initial_plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION
    assert initial_plan.call is not None
    failed_observation = ToolResult(
        initial_plan.call.identity,
        initial_plan.call.name,
        ToolResultStatus.ACTION_ERROR,
        DispatchCertainty.DISPATCHED,
        code="DRIVER_ERROR",
    )
    persisted_statuses: list[str] = []

    def observe_phase(_phase: RunPhase) -> None:
        persisted_statuses.append(
            str(read_run_checkpoint(config.state_dir, state.run_id)["recovery_status"])
        )

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
            phase_observer=observe_phase,
        )
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=None,
                desktop=FakeDesktopMCP(results=deque([failed_observation])),
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )

        failed_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
        failed_envelope = read_continuation(config.state_dir, state.run_id)
        continue_plan = plan_read_only_recovery(
            failed_checkpoint,
            failed_envelope,
            config,
            task=state.task,
        )
        assert continue_plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER
        provider = FakeModelProvider(
            turns=deque([ModelTurn(state.run_id, "turn_4", "response_4", "done")])
        )
        continued = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=failed_checkpoint,
            envelope=failed_envelope,
            config=config,
            task=state.task,
            lock=lock,
            phase_observer=observe_phase,
        )
        asyncio.run(
            execute_read_only_recovery_step(
                failed_checkpoint,
                failed_envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=None,
                commit_intent=continued.commit_intent,
                commit_completion=continued.commit_completion,
            )
        )
    finally:
        lock.release()

    final_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    final_envelope = read_continuation(config.state_dir, state.run_id)
    final_plan = plan_read_only_recovery(
        final_checkpoint,
        final_envelope,
        config,
        task=state.task,
    )
    assert persisted_statuses == [
        RecoveryStatus.REQUIRES_REOBSERVATION.value,
        RecoveryStatus.REQUIRES_REOBSERVATION.value,
        RecoveryStatus.REQUIRES_REOBSERVATION.value,
        RecoveryStatus.REQUIRES_REOBSERVATION.value,
    ]
    assert final_checkpoint["recovery_status"] == RecoveryStatus.REQUIRES_REOBSERVATION.value
    assert final_plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert final_plan.decision.reason == "VERIFICATION_REQUIRED"
    assert final_plan.final_text is None


def test_completed_provider_multiple_action_requests_are_blocked_as_one_terminal_step(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    calls = (
        ToolCall(
            CallIdentity(state.run_id, "turn_1", "call_1"),
            "click",
            {"ref": "ref_1"},
        ),
        ToolCall(
            CallIdentity(state.run_id, "turn_1", "call_2"),
            "key",
            {"combo": "CTRL+L"},
        ),
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", calls),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, state.run_id),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.FINALIZE_BLOCKED
    assert plan.decision.reason == "RECOVERED_ACTION_REQUESTED"
    assert plan.blocked_call_count == 2
    assert plan.call is None
    assert plan.result is None


@pytest.mark.parametrize("terminal_stage", ["dispatch_intent", "completed_unknown"])
def test_multi_observation_unknown_tool_state_requires_human_without_replay(
    tmp_path: Path,
    monkeypatch: object,
    terminal_stage: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    calls = (
        ToolCall(CallIdentity(state.run_id, "turn_1", "call_1"), "list_windows", {}),
        ToolCall(CallIdentity(state.run_id, "turn_1", "call_2"), "ui_snapshot", {}),
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", calls),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        budgets=replace(state.budgets, tool_calls_used=1),
        recovery_status=RecoveryStatus.UNKNOWN_OUTCOME,
    )
    recorder.prepare_tool(
        tool_state,
        calls[0],
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=4,
    )
    envelope = recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    sequence = 5
    if terminal_stage == "completed_unknown":
        envelope = recorder.complete_tool(
            tool_state,
            ToolResult(
                calls[0].identity,
                calls[0].name,
                ToolResultStatus.UNKNOWN_OUTCOME,
                DispatchCertainty.UNKNOWN,
                code="MCP_PROTOCOL_ERROR",
            ),
            checkpoint_sequence=6,
        )
        sequence = 6

    checkpoint = _safe_checkpoint(config, tool_state, sequence)
    plan = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    assert plan.decision.action is ReconstructionAction.HUMAN_REOBSERVE
    assert plan.decision.reason == "UNKNOWN_OUTCOME"
    assert plan.call is None
    assert plan.result is None
    with pytest.raises(RecoveryExecutionError, match="^RECOVERY_PLAN_NOT_EXECUTABLE$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert provider.calls == []
    assert provider.continuation_state == {}
    assert provider.restored_tools == {}
    assert desktop.tool_calls == []
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


def test_attach_drift_never_returns_external_work(tmp_path: Path, monkeypatch: object) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 2),
        read_continuation(config.state_dir, "run_1"),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.FAIL_CLOSED
    assert plan.call is None
    assert plan.result is None


def test_attach_rejects_provider_state_that_does_not_correlate_to_turn(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "different_response",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "different_response", "items": []}],
        },
        checkpoint_sequence=3,
    )

    with pytest.raises(RecoveryPlanError, match="CONTINUATION_PROVIDER_STATE_INVALID"):
        plan_read_only_recovery(
            _checkpoint(state, 3),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
        )


def test_attach_rejects_openai_token_state_that_does_not_correlate_to_turn(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 1,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )

    with pytest.raises(RecoveryPlanError, match="CONTINUATION_PROVIDER_STATE_INVALID"):
        plan_read_only_recovery(
            _checkpoint(state, 3),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
        )


def test_claude_attach_correlates_exact_tool_use_history(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        provider=ProviderConfig("anthropic", "model-v1"),
    )
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state, provider_name="anthropic")
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "messages": [
                {"role": "user", "content": state.task},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "call_1",
                            "name": "list_windows",
                            "input": {},
                        }
                    ],
                },
            ]
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, "run_1"),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.DISPATCH_OBSERVATION
    assert plan.call == call


def test_budget_counters_must_equal_a_fresh_ledger_fold(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = replace(
        _state(),
        budgets=RunBudget(4, 4, 8, model_turns_used=2),
    )
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )

    plan = plan_read_only_recovery(
        _checkpoint(state, 3),
        read_continuation(config.state_dir, "run_1"),
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert plan.call is None
    assert plan.result is None


@pytest.mark.parametrize(
    ("scenario", "replacement"),
    [
        ("provider_pending", "provider_continue"),
        ("provider_pending", "mandatory_reobserve"),
        ("provider_pending", "stop"),
        ("observation_completed", "dispatch_observation"),
        ("observation_completed", "mandatory_reobserve"),
        ("observation_completed", "stop"),
        ("side_effect_completed", "provider_continue"),
        ("side_effect_completed", "dispatch_observation"),
        ("side_effect_completed", "stop"),
    ],
)
def test_digest_valid_next_step_must_match_reconstructed_topology(
    tmp_path: Path,
    monkeypatch: object,
    scenario: str,
    replacement: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "click" if scenario == "side_effect_completed" else "list_windows",
        {"ref": "ref_1"} if scenario == "side_effect_completed" else {},
    )
    if scenario == "provider_pending":
        recorder = _recorder(config, state)
        recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
        recorder.dispatch_provider(state, checkpoint_sequence=2)
        envelope = recorder.complete_provider(
            state,
            ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
            provider_state={
                "response_id": "response_1",
                "prior_context_tokens": 0,
                "request_contract_digest": "0" * 64,
                "memory_context_used": False,
                "initial_input": state.task,
                "output_batches": [{"response_id": "response_1", "items": []}],
            },
            checkpoint_sequence=3,
        )
        checkpoint_state = state
        sequence = 3
        expected_step = "dispatch_observation"
    elif scenario == "observation_completed":
        checkpoint_state, envelope, _result = _completed_observation(
            config,
            state,
            call=call,
            advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        )
        sequence = 6
        expected_step = "provider_continue"
    else:
        checkpoint_state, envelope, _result = _completed_side_effect(
            config,
            state,
            unknown=False,
        )
        sequence = 6
        expected_step = "mandatory_reobserve"
    assert envelope.payload["boundary"]["next_step"] == expected_step
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    tampered = _replace_next_step(config, envelope, replacement)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(
            checkpoint,
            tampered,
            config,
            task=state.task,
        )

    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


@pytest.mark.parametrize("exhausted_dimension", ["model_turns", "input_tokens"])
def test_provider_budget_and_semantic_binding_precede_restore_intent_and_call(
    tmp_path: Path,
    monkeypatch: object,
    exhausted_dimension: str,
) -> None:
    max_model_turns = 1 if exhausted_dimension == "model_turns" else 4
    max_input_tokens = 1 if exhausted_dimension == "input_tokens" else 100
    input_tokens_used = 1 if exhausted_dimension == "input_tokens" else 0
    config = replace(
        _config(tmp_path, monkeypatch),
        policy=PolicyConfig(
            max_model_turns=max_model_turns,
            max_tool_calls=4,
            max_input_tokens=max_input_tokens,
        ),
    )
    state = RunState(
        "run_1",
        "Inspect windows",
        "policy-v1",
        0,
        RunBudget(
            max_model_turns,
            4,
            8,
            model_turns_used=1,
            max_input_tokens=max_input_tokens,
            input_tokens_used=input_tokens_used,
        ),
    )
    call = ToolCall(CallIdentity(state.run_id, "turn_1", "call_1"), "list_windows", {})
    checkpoint_state, envelope, _result = _completed_observation(
        config,
        state,
        call=call,
        advertised_tool_names=frozenset(tool.name for tool in REVIEWED_TOOLS),
        usage=ModelUsage(input_tokens=input_tokens_used, output_tokens=0),
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, 6)
    canonical = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    assert canonical.decision.action is ReconstructionAction.START_NEW_RUN
    assert canonical.decision.reason == "BUDGET_EXHAUSTED"

    tampered = _replace_next_step(config, envelope, "mandatory_reobserve")
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    provider = FakeModelProvider(
        turns=deque([ModelTurn(state.run_id, "turn_2", "response_2", "done")])
    )
    commits: list[object] = []

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                tampered,
                config,
                task=state.task,
                provider=provider,
                desktop=None,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert provider.calls == []
    assert provider.continuation_state == {}
    assert provider.restored_tools == {}
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


@pytest.mark.parametrize("scenario", ["provider_pending", "mandatory_reobserve"])
def test_tool_budget_and_semantic_binding_precede_intent_and_desktop_call(
    tmp_path: Path,
    monkeypatch: object,
    scenario: str,
) -> None:
    max_tool_calls = 0 if scenario == "provider_pending" else 1
    config = replace(
        _config(tmp_path, monkeypatch),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=max_tool_calls),
    )
    state = RunState(
        "run_1",
        "Inspect windows",
        "policy-v1",
        0,
        RunBudget(4, max_tool_calls, 8, model_turns_used=1),
    )
    if scenario == "provider_pending":
        call = ToolCall(CallIdentity(state.run_id, "turn_1", "call_1"), "list_windows", {})
        recorder = _recorder(config, state)
        recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
        recorder.dispatch_provider(state, checkpoint_sequence=2)
        envelope = recorder.complete_provider(
            state,
            ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
            provider_state={
                "response_id": "response_1",
                "prior_context_tokens": 0,
                "request_contract_digest": "0" * 64,
                "memory_context_used": False,
                "initial_input": state.task,
                "output_batches": [{"response_id": "response_1", "items": []}],
            },
            checkpoint_sequence=3,
        )
        checkpoint_state = state
        sequence = 3
    else:
        checkpoint_state, envelope, _result = _completed_side_effect(
            config,
            state,
            unknown=False,
        )
        sequence = 6
    checkpoint = _safe_checkpoint(config, checkpoint_state, sequence)
    canonical = plan_read_only_recovery(checkpoint, envelope, config, task=state.task)
    assert canonical.decision.action is ReconstructionAction.START_NEW_RUN
    assert canonical.decision.reason == "BUDGET_EXHAUSTED"

    tampered = _replace_next_step(config, envelope, "provider_continue")
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                tampered,
                config,
                task=state.task,
                provider=None,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert desktop.tool_calls == []
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


def test_prepared_observation_reuses_its_charged_call_and_budget(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = replace(
        _config(tmp_path, monkeypatch),
        policy=PolicyConfig(max_model_turns=4, max_tool_calls=1),
    )
    state = RunState(
        "run_1",
        "Inspect windows",
        "policy-v1",
        0,
        RunBudget(4, 1, 8, model_turns_used=1),
    )
    call = ToolCall(CallIdentity(state.run_id, "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    prepared_state = replace(
        state,
        budgets=replace(state.budgets, tool_calls_used=1),
    )
    envelope = recorder.prepare_tool(
        prepared_state,
        call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=4,
    )
    checkpoint = _safe_checkpoint(config, prepared_state, 4)
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    desktop = FakeDesktopMCP(results=deque([result]))
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        step = asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=None,
                desktop=desktop,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    tool_calls = [event for event in persisted.payload["ledger"] if event["kind"] == "tool_call"]
    assert step.tool_result == result
    assert desktop.tool_calls == [replace(call, status=ToolCallStatus.AUTHORIZED)]
    assert persisted.payload["budget"]["tool_calls_used"] == 1
    assert len(tool_calls) == 1
    assert persisted.payload["boundary"]["next_step"] == "provider_continue"


def test_forged_prepared_observation_after_side_effect_has_zero_authority(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state, envelope, _result = _completed_side_effect(
        config,
        _state(),
        unknown=False,
    )
    forged_call = ToolCall(
        CallIdentity(state.run_id, "forged_turn", "forged_call"),
        "list_windows",
        {},
    )
    payload = json.loads(json.dumps(envelope.payload))
    payload.pop("payload_digest")
    payload["checkpoint_sequence"] = 7
    payload["budget"]["tool_calls_used"] = 2
    payload["ledger"].append(
        {
            "kind": "tool_call",
            "event_id": f"{state.run_id}:recovery:{len(payload['ledger']) + 1}",
            "data": {
                "identity": {
                    "run_id": forged_call.identity.run_id,
                    "turn_id": forged_call.identity.turn_id,
                    "call_id": forged_call.identity.call_id,
                },
                "tool_name": forged_call.name,
                "arguments": dict(forged_call.arguments),
                "call_digest": forged_call.digest,
                "effect": "observation",
            },
        }
    )
    payload["boundary"] = {
        "operation_kind": "tool",
        "stage": "prepared",
        "operation_id": (
            f"{forged_call.identity.run_id}:{forged_call.identity.turn_id}:"
            f"{forged_call.identity.call_id}"
        ),
        "effect": "observation",
        "dispatch": "not_dispatched",
        "next_step": "stop",
    }
    forged = write_continuation(config.state_dir, payload)
    checkpoint_state = replace(
        state,
        budgets=replace(state.budgets, tool_calls_used=2),
    )
    checkpoint = _safe_checkpoint(config, checkpoint_state, 7)
    continuation_file = continuation_path(config.state_dir, state.run_id)
    checkpoint_file = RunRecorder(config.state_dir, state.run_id).checkpoint_path
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = checkpoint_file.read_bytes()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                forged,
                config,
                task=state.task,
                provider=None,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert desktop.tool_calls == []
    assert commits == []
    assert continuation_file.read_bytes() == before_continuation
    assert checkpoint_file.read_bytes() == before_checkpoint


def test_executor_commits_before_exactly_one_observation_dispatch(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    expected = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    desktop = FakeDesktopMCP(results=deque([expected]))
    commits: list[tuple[int, str, ReconstructionAction]] = []

    def commit(sequence: int, operation_id: str, action: ReconstructionAction) -> None:
        assert desktop.tool_calls == []
        commits.append((sequence, operation_id, action))

    step = asyncio.run(
        execute_read_only_recovery_step(
            _checkpoint(state, 3),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
            provider=FakeModelProvider(),
            desktop=desktop,
            commit_intent=commit,
        )
    )

    assert commits == [(3, "run_1:turn_1:call_1", ReconstructionAction.DISPATCH_OBSERVATION)]
    assert len(desktop.tool_calls) == 1
    assert desktop.tool_calls[0].status.value == "authorized"
    assert step.tool_result == expected


def test_executor_restores_then_commits_one_new_provider_continuation(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder.prepare_tool(tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4)
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    provider = FakeModelProvider(turns=deque([ModelTurn("run_1", "turn_2", "response_2", "done")]))
    commits: list[tuple[int, str, ReconstructionAction]] = []

    def commit(sequence: int, operation_id: str, action: ReconstructionAction) -> None:
        assert provider.calls == []
        assert provider.continuation_state["run_1"] == {
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        }
        commits.append((sequence, operation_id, action))

    step = asyncio.run(
        execute_read_only_recovery_step(
            _checkpoint(tool_state, 6),
            read_continuation(config.state_dir, "run_1"),
            config,
            task=state.task,
            provider=provider,
            desktop=FakeDesktopMCP(),
            commit_intent=commit,
        )
    )

    assert commits == [(6, "run_1:turn_2:provider", ReconstructionAction.CONTINUE_PROVIDER)]
    assert len(provider.calls) == 1
    assert provider.calls[0]["task"] == state.task
    ledger = provider.calls[0]["ledger"]
    assert isinstance(ledger, tuple) and ledger[0].tool_result == result
    assert step.model_turn is not None
    assert step.model_turn.provider_response_id == "response_2"


@pytest.mark.parametrize("current_baseline", [False, True])
def test_provider_recovery_uses_only_persisted_currently_safe_observations(
    current_baseline: bool,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "ui_snapshot", {})
    tool_state, envelope, _ = _completed_observation(
        config,
        state,
        call=call,
        advertised_tool_names=frozenset({"ui_snapshot", "ocr", "click"}),
    )
    provider = FakeModelProvider(turns=deque([ModelTurn("run_1", "turn_2", "response_2", "done")]))
    desktop = (
        FakeDesktopMCP(satisfied_safety_baselines=frozenset({"title_matched_image_redaction"}))
        if current_baseline
        else None
    )

    step = asyncio.run(
        execute_read_only_recovery_step(
            _checkpoint(tool_state, 6),
            envelope,
            config,
            task=state.task,
            provider=provider,
            desktop=desktop,
            commit_intent=lambda *_args: None,
        )
    )

    expected = ("ui_snapshot", "ocr") if current_baseline else ("ui_snapshot",)
    assert tuple(tool.name for tool in provider.restored_tools["run_1"]) == expected
    assert tuple(tool.name for tool in provider.calls[0]["tools"]) == expected
    assert all(tool.effect is ToolEffect.OBSERVATION for tool in provider.calls[0]["tools"])
    assert step.model_turn is not None
    assert step.model_turn.text == "done"


def test_provider_recovery_keeps_failed_browser_observation_withdrawn(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    base = _config(tmp_path, monkeypatch)
    config = replace(
        base,
        mcp=replace(
            base.mcp,
            environment={"CUMCP_BROWSER_OBSERVATION": "cdp"},
        ),
    )
    state = _state()
    call = ToolCall(
        CallIdentity(state.run_id, "turn_1", "call_1"),
        "browser_snapshot",
        {},
    )
    recorder = _recorder(
        config,
        state,
        advertised_tool_names=frozenset({"ui_snapshot", "browser_snapshot"}),
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn(state.run_id, "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        budgets=replace(state.budgets, tool_calls_used=1),
    )
    failed = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.ACTION_ERROR,
        DispatchCertainty.DISPATCHED,
        code="DRIVER_ERROR",
    )
    recorder.prepare_tool(
        tool_state,
        call,
        effect=ToolEffect.OBSERVATION,
        checkpoint_sequence=4,
    )
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    envelope = recorder.complete_tool(tool_state, failed, checkpoint_sequence=6)
    provider = FakeModelProvider(
        turns=deque([ModelTurn(state.run_id, "turn_2", "response_2", "done")])
    )

    step = asyncio.run(
        execute_read_only_recovery_step(
            _checkpoint(tool_state, 6),
            envelope,
            config,
            task=state.task,
            provider=provider,
            desktop=None,
            commit_intent=lambda *_args: None,
        )
    )

    expected = ("ui_snapshot",)
    assert tuple(tool.name for tool in provider.restored_tools[state.run_id]) == expected
    assert tuple(tool.name for tool in provider.calls[0]["tools"]) == expected
    assert step.model_turn is not None
    assert step.model_turn.text == "done"


def test_recovered_provider_turn_rejects_unadvertised_sibling_atomically(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    original = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "ui_snapshot", {})
    tool_state, envelope, _ = _completed_observation(
        config,
        state,
        call=original,
        advertised_tool_names=frozenset({"ui_snapshot"}),
    )
    valid = ToolCall(CallIdentity("run_1", "turn_2", "call_1"), "ui_snapshot", {})
    widened = ToolCall(CallIdentity("run_1", "turn_2", "call_2"), "list_windows", {})

    class RejectingExportProvider(FakeModelProvider):
        def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
            del run_id
            raise AssertionError("invalid recovered turn must not be exported")

    provider = RejectingExportProvider(
        turns=deque([ModelTurn("run_1", "turn_2", "response_2", "", (valid, widened))])
    )
    intents: list[tuple[int, str, ReconstructionAction]] = []
    completions: list[object] = []

    with pytest.raises(RecoveryExecutionError, match="^RECOVERY_PROVIDER_TOOL_NOT_ADVERTISED$"):
        asyncio.run(
            execute_read_only_recovery_step(
                _checkpoint(tool_state, 6),
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=None,
                commit_intent=lambda *args: intents.append(args),
                commit_completion=lambda *args: completions.append(args),
            )
        )

    assert intents == [(6, "run_1:turn_2:provider", ReconstructionAction.CONTINUE_PROVIDER)]
    assert completions == []
    assert tuple(tool.name for tool in provider.restored_tools["run_1"]) == ("ui_snapshot",)
    assert tuple(tool.name for tool in provider.calls[0]["tools"]) == ("ui_snapshot",)


def test_recovery_rejects_persisted_model_call_outside_bound_scope(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    widened = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(
        config,
        state,
        advertised_tool_names=frozenset({"ui_snapshot"}),
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    envelope = recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (widened,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(
            _checkpoint(state, 3),
            envelope,
            config,
            task=state.task,
        )


def test_recovery_rejects_completed_tool_that_does_not_match_provider_turn(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    provider_call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "ui_snapshot", {})
    recorder = _recorder(
        config,
        state,
        advertised_tool_names=frozenset({"ui_snapshot"}),
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (provider_call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    widened = ToolCall(provider_call.identity, "list_windows", {})
    tool_state = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
    )
    result = ToolResult(
        widened.identity,
        widened.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="window list",
    )
    recorder.prepare_tool(tool_state, widened, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4)
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    envelope = recorder.complete_tool(tool_state, result, checkpoint_sequence=6)

    with pytest.raises(RecoveryPlanError, match="^CONTINUATION_LEDGER_INVALID$"):
        plan_read_only_recovery(
            _checkpoint(tool_state, 6),
            envelope,
            config,
            task=state.task,
        )


def test_mandatory_reobservation_cannot_widen_original_tool_scope(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    action = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"),
        "activate_window",
        {"window_id": "window_1"},
    )
    recorder = _recorder(
        config,
        state,
        advertised_tool_names=frozenset({"activate_window"}),
    )
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (action,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": state.task,
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        budgets=RunBudget(
            4,
            4,
            8,
            model_turns_used=1,
            tool_calls_used=1,
            side_effects_used=1,
        ),
        recovery_status=RecoveryStatus.REQUIRES_REOBSERVATION,
    )
    result = ToolResult(
        action.identity,
        action.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="activated",
    )
    recorder.prepare_tool(tool_state, action, effect=ToolEffect.SIDE_EFFECT, checkpoint_sequence=4)
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    envelope = recorder.complete_tool(tool_state, result, checkpoint_sequence=6)

    plan = plan_read_only_recovery(
        _checkpoint(tool_state, 6),
        envelope,
        config,
        task=state.task,
    )

    assert plan.decision.action is ReconstructionAction.START_NEW_RUN
    assert plan.decision.reason == "RECOVERY_MANDATORY_OBSERVATION_NOT_ADVERTISED"
    assert plan.call is None
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []
    with pytest.raises(RecoveryExecutionError, match="^RECOVERY_PLAN_NOT_EXECUTABLE$"):
        asyncio.run(
            execute_read_only_recovery_step(
                _checkpoint(tool_state, 6),
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )
    assert commits == []
    assert provider.calls == []
    assert desktop.tool_calls == []


def test_executor_stale_attach_has_zero_commits_and_external_calls(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    provider = FakeModelProvider()
    desktop = FakeDesktopMCP()
    commits: list[object] = []

    with pytest.raises(RecoveryExecutionError, match="RECOVERY_PLAN_NOT_EXECUTABLE"):
        asyncio.run(
            execute_read_only_recovery_step(
                _checkpoint(state, 2),
                read_continuation(config.state_dir, "run_1"),
                config,
                task=state.task,
                provider=provider,
                desktop=desktop,
                commit_intent=lambda *args: commits.append(args),
            )
        )

    assert commits == []
    assert provider.calls == []
    assert desktop.tool_calls == []


def test_recovery_rejects_missing_current_safety_baseline_without_mutation(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"),
        "ocr",
        {"x": 0, "y": 0, "w": 10, "h": 10},
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    expected = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="recognized text",
    )
    desktop = FakeDesktopMCP(results=deque([expected]))
    continuation_file = continuation_path(config.state_dir, state.run_id)
    before_continuation = continuation_file.read_bytes()
    before_checkpoint = safe.checkpoint_path.read_bytes()
    observed_phases: list[RunPhase] = []

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
            phase_observer=observed_phases.append,
        )
        with pytest.raises(
            RecoveryExecutionError,
            match="^RECOVERY_SAFETY_BASELINE_UNSATISFIED$",
        ):
            asyncio.run(
                execute_read_only_recovery_step(
                    checkpoint,
                    envelope,
                    config,
                    task=state.task,
                    provider=None,
                    desktop=desktop,
                    commit_intent=persistence.commit_intent,
                    commit_completion=persistence.commit_completion,
                )
            )
    finally:
        lock.release()

    assert continuation_file.read_bytes() == before_continuation
    assert safe.checkpoint_path.read_bytes() == before_checkpoint
    assert read_continuation(config.state_dir, state.run_id).payload == envelope.payload
    assert read_run_checkpoint(config.state_dir, state.run_id) == checkpoint
    assert desktop.tool_calls == []
    assert list(desktop.results) == [expected]
    assert observed_phases == []


def test_locked_recovery_with_current_baseline_persists_observation_atomically(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"),
        "ocr",
        {"x": 0, "y": 0, "w": 10, "h": 10},
    )
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="recognized text",
    )
    desktop = FakeDesktopMCP(
        satisfied_safety_baselines=frozenset({"title_matched_image_redaction"}),
        results=deque([result]),
    )
    observed_phases: list[RunPhase] = []

    def observe_phase(phase: RunPhase) -> None:
        observed_phases.append(phase)
        if len(observed_phases) == 1:
            raise RuntimeError("progress unavailable")

    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
            phase_observer=observe_phase,
        )
        step = asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=None,
                desktop=desktop,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    current = read_run_checkpoint(config.state_dir, state.run_id)
    assert step.tool_result == result
    assert persisted.payload["checkpoint_sequence"] == 5
    assert current["checkpoint_sequence"] == 5
    assert persisted.payload["boundary"] == {
        "operation_kind": "tool",
        "stage": "completed",
        "operation_id": "run_1:turn_1:call_1",
        "effect": "observation",
        "dispatch": "dispatched",
        "next_step": "provider_continue",
    }
    assert persisted.payload["budget"]["tool_calls_used"] == 1
    assert persisted.payload["observation"]["verified_epoch"] == 1
    assert observed_phases == [RunPhase.EXECUTING, RunPhase.PLANNING]


def test_locked_recovery_leaves_durable_unknown_intent_when_external_call_fails(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(state)
    safe.record(state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        with pytest.raises(RuntimeError, match="no fake tool result"):
            asyncio.run(
                execute_read_only_recovery_step(
                    checkpoint,
                    envelope,
                    config,
                    task=state.task,
                    provider=None,
                    desktop=FakeDesktopMCP(),
                    commit_intent=persistence.commit_intent,
                    commit_completion=persistence.commit_completion,
                )
            )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    assert persisted.payload["checkpoint_sequence"] == 4
    assert persisted.payload["boundary"]["stage"] == "dispatch_intent"
    assert persisted.payload["boundary"]["dispatch"] == "unknown"

    repeated_desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    call.identity,
                    call.name,
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                )
            ]
        )
    )
    lock.acquire()
    try:
        repeated = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        with pytest.raises(RecoveryExecutionError, match="RECOVERY_SEQUENCE_MISMATCH"):
            asyncio.run(
                execute_read_only_recovery_step(
                    checkpoint,
                    envelope,
                    config,
                    task=state.task,
                    provider=None,
                    desktop=repeated_desktop,
                    commit_intent=repeated.commit_intent,
                    commit_completion=repeated.commit_completion,
                )
            )
    finally:
        lock.release()
    assert repeated_desktop.tool_calls == []


def test_locked_recovery_persists_provider_intent_and_completion(
    tmp_path: Path, monkeypatch: object
) -> None:
    config = _config(tmp_path, monkeypatch)
    state = _state()
    call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    recorder.complete_provider(
        state,
        ModelTurn("run_1", "turn_1", "response_1", "", (call,)),
        provider_state={
            "response_id": "response_1",
            "prior_context_tokens": 0,
            "request_contract_digest": "0" * 64,
            "memory_context_used": False,
            "initial_input": "Inspect windows",
            "output_batches": [{"response_id": "response_1", "items": []}],
        },
        checkpoint_sequence=3,
    )
    tool_state = replace(
        state,
        observation_epoch=1,
        verified_observation_epoch=1,
        budgets=RunBudget(4, 4, 8, model_turns_used=1, tool_calls_used=1),
    )
    result = ToolResult(
        call.identity,
        call.name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text="Notepad",
    )
    recorder.prepare_tool(tool_state, call, effect=ToolEffect.OBSERVATION, checkpoint_sequence=4)
    recorder.dispatch_tool(tool_state, checkpoint_sequence=5)
    recorder.complete_tool(tool_state, result, checkpoint_sequence=6)
    safe = RunRecorder(config.state_dir, state.run_id)
    safe.start(tool_state)
    safe.record(tool_state, RunPhase.OBSERVING, advance_checkpoint_sequence=True)
    safe.record(tool_state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    for _ in range(3):
        safe.record(tool_state, RunPhase.PLANNING, advance_checkpoint_sequence=True)
    checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
    envelope = read_continuation(config.state_dir, state.run_id)
    provider = FakeModelProvider(turns=deque([ModelTurn("run_1", "turn_2", "response_2", "done")]))
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        persistence = LockedRecoveryPersistence(
            state_dir=config.state_dir,
            checkpoint=checkpoint,
            envelope=envelope,
            config=config,
            task=state.task,
            lock=lock,
        )
        step = asyncio.run(
            execute_read_only_recovery_step(
                checkpoint,
                envelope,
                config,
                task=state.task,
                provider=provider,
                desktop=None,
                commit_intent=persistence.commit_intent,
                commit_completion=persistence.commit_completion,
            )
        )
    finally:
        lock.release()

    persisted = read_continuation(config.state_dir, state.run_id)
    assert step.model_turn is not None and step.model_turn.text == "done"
    assert persisted.payload["checkpoint_sequence"] == 8
    assert persisted.payload["provider_state"] == {
        "response_id": "response_2",
        "prior_context_tokens": 0,
        "request_contract_digest": "0" * 64,
        "memory_context_used": False,
        "initial_input": "Inspect windows",
        "output_batches": [
            {"response_id": "response_1", "items": []},
            {"response_id": "response_2", "items": []},
        ],
    }
    assert persisted.payload["budget"]["model_turns_used"] == 2
    assert persisted.payload["boundary"] == {
        "operation_kind": "provider",
        "stage": "completed",
        "operation_id": "run_1:turn_2:provider",
        "effect": None,
        "dispatch": "dispatched",
        "next_step": "stop",
    }


@pytest.mark.parametrize("case", E2_CASES, ids=lambda case: case["id"])
def test_e2_runtime_recovery_matrix_freezes_exact_new_external_calls(
    case: dict[str, object], tmp_path: Path, monkeypatch: object
) -> None:
    case_id = str(case["id"])
    config = _config(tmp_path, monkeypatch)
    if case_id == "e2_resume_budget_already_consumed":
        config = replace(
            config,
            policy=PolicyConfig(max_model_turns=1, max_tool_calls=4),
        )
        state = RunState(
            "run_1",
            "Inspect windows",
            "policy-v1",
            0,
            RunBudget(1, 4, 8, model_turns_used=1),
        )
    else:
        state = _state()

    observation_call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "list_windows", {})
    action_call = ToolCall(CallIdentity("run_1", "turn_1", "call_1"), "click", {"ref": "ref_1"})
    action_cases = {
        "e2_resume_provider_completed_action_pending",
        "e2_resume_action_completed",
        "e2_resume_action_dispatch_uncertain",
        "e2_resume_side_effect_then_crash_during_verification",
    }
    call = action_call if case_id in action_cases else observation_call
    recorder = _recorder(config, state)
    recorder.prepare_provider(state, "turn_1", checkpoint_sequence=1)
    recorder.dispatch_provider(state, checkpoint_sequence=2)
    boundary_sequence = 2
    checkpoint_state = state

    if case_id != "e2_resume_provider_dispatch_uncertain":
        final_response = case_id == "e2_resume_provider_completed_final"
        recorder.complete_provider(
            state,
            ModelTurn(
                "run_1",
                "turn_1",
                "response_1",
                "done" if final_response else "",
                () if final_response else (call,),
            ),
            provider_state={
                "response_id": "response_1",
                "prior_context_tokens": 0,
                "request_contract_digest": "0" * 64,
                "memory_context_used": False,
                "initial_input": "Inspect windows",
                "output_batches": [{"response_id": "response_1", "items": []}],
            },
            checkpoint_sequence=3,
        )
        boundary_sequence = 3

    tool_dispatch_cases = {
        "e2_resume_observation_completed",
        "e2_resume_observation_dispatch_uncertain",
        "e2_resume_action_completed",
        "e2_resume_action_dispatch_uncertain",
        "e2_resume_unknown_result_persisted",
        "e2_resume_budget_already_consumed",
        "e2_resume_side_effect_then_crash_during_verification",
    }
    if case_id in tool_dispatch_cases:
        effect = ToolEffect.SIDE_EFFECT if case_id in action_cases else ToolEffect.OBSERVATION
        checkpoint_state = replace(
            state,
            budgets=replace(
                state.budgets,
                tool_calls_used=1,
                side_effects_used=int(effect is ToolEffect.SIDE_EFFECT),
            ),
            recovery_status=(
                RecoveryStatus.REQUIRES_REOBSERVATION
                if effect is ToolEffect.SIDE_EFFECT
                else RecoveryStatus.READY
            ),
        )
        recorder.prepare_tool(checkpoint_state, call, effect=effect, checkpoint_sequence=4)
        recorder.dispatch_tool(checkpoint_state, checkpoint_sequence=5)
        boundary_sequence = 5
        uncertain_cases = {
            "e2_resume_observation_dispatch_uncertain",
            "e2_resume_action_dispatch_uncertain",
        }
        if case_id not in uncertain_cases:
            unknown = case_id == "e2_resume_unknown_result_persisted"
            result = ToolResult(
                call.identity,
                call.name,
                (ToolResultStatus.UNKNOWN_OUTCOME if unknown else ToolResultStatus.SUCCESS),
                DispatchCertainty.UNKNOWN if unknown else DispatchCertainty.DISPATCHED,
                sanitized_text="" if effect is ToolEffect.SIDE_EFFECT else "Notepad",
            )
            checkpoint_state = replace(
                checkpoint_state,
                observation_epoch=(1 if effect is ToolEffect.OBSERVATION and not unknown else 0),
                verified_observation_epoch=(
                    1 if effect is ToolEffect.OBSERVATION and not unknown else None
                ),
                recovery_status=(
                    RecoveryStatus.UNKNOWN_OUTCOME if unknown else checkpoint_state.recovery_status
                ),
            )
            recorder.complete_tool(checkpoint_state, result, checkpoint_sequence=6)
            boundary_sequence = 6

    if case_id == "e2_resume_side_effect_then_crash_during_verification":
        verification_call = ToolCall(
            CallIdentity("run_1", "recovery_8", "mandatory_ui_snapshot"),
            "ui_snapshot",
            {},
        )
        checkpoint_state = replace(
            checkpoint_state,
            budgets=replace(checkpoint_state.budgets, tool_calls_used=2),
        )
        recorder.prepare_tool(
            checkpoint_state,
            verification_call,
            effect=ToolEffect.OBSERVATION,
            checkpoint_sequence=7,
        )
        recorder.dispatch_tool(checkpoint_state, checkpoint_sequence=8)
        boundary_sequence = 8

    checkpoint_sequence = boundary_sequence
    if case_id in {
        "e2_resume_checkpoint_continuation_torn",
        "e2_resume_repeated_attach",
    }:
        checkpoint_sequence -= 1
    checkpoint = _safe_checkpoint(config, checkpoint_state, checkpoint_sequence)

    provider = FakeModelProvider(turns=deque([ModelTurn("run_1", "turn_2", "response_2", "done")]))
    desktop = FakeDesktopMCP(
        results=deque(
            [
                ToolResult(
                    observation_call.identity,
                    observation_call.name,
                    ToolResultStatus.SUCCESS,
                    DispatchCertainty.DISPATCHED,
                    sanitized_text="Notepad",
                )
            ]
        )
    )
    actual_calls: list[str] = []

    if case_id == "e2_resume_expired_or_symlinked_continuation":
        with pytest.raises(ContinuationError, match="CONTINUATION_EXPIRED"):
            read_continuation(
                config.state_dir,
                state.run_id,
                now=datetime.now(UTC) + timedelta(days=1),
            )
    else:
        envelope = read_continuation(config.state_dir, state.run_id)
        planning_config = (
            replace(config, provider=ProviderConfig("openai", "drifted-model"))
            if case_id == "e2_resume_identity_or_registry_drift"
            else config
        )
        plan = plan_read_only_recovery(checkpoint, envelope, planning_config, task=state.task)
        if plan.decision.action in {
            ReconstructionAction.DISPATCH_OBSERVATION,
            ReconstructionAction.CONTINUE_PROVIDER,
            ReconstructionAction.MANDATORY_REOBSERVE,
        }:
            if plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE:
                assert plan.call is not None
                desktop = FakeDesktopMCP(
                    results=deque(
                        [
                            ToolResult(
                                plan.call.identity,
                                plan.call.name,
                                ToolResultStatus.SUCCESS,
                                DispatchCertainty.DISPATCHED,
                                sanitized_text="verified desktop state",
                            )
                        ]
                    )
                )
            lock = RunLock(config.application_state_dir)
            lock.acquire()
            try:
                persistence = LockedRecoveryPersistence(
                    state_dir=config.state_dir,
                    checkpoint=checkpoint,
                    envelope=envelope,
                    config=config,
                    task=state.task,
                    lock=lock,
                )
                asyncio.run(
                    execute_read_only_recovery_step(
                        checkpoint,
                        envelope,
                        config,
                        task=state.task,
                        provider=(
                            provider
                            if plan.decision.action is ReconstructionAction.CONTINUE_PROVIDER
                            else None
                        ),
                        desktop=(
                            desktop
                            if plan.decision.action
                            in {
                                ReconstructionAction.DISPATCH_OBSERVATION,
                                ReconstructionAction.MANDATORY_REOBSERVE,
                            }
                            else None
                        ),
                        commit_intent=persistence.commit_intent,
                        commit_completion=persistence.commit_completion,
                    )
                )
            finally:
                lock.release()
            if plan.decision.action is ReconstructionAction.MANDATORY_REOBSERVE:
                completed = read_continuation(config.state_dir, state.run_id)
                completed_checkpoint = read_run_checkpoint(config.state_dir, state.run_id)
                assert completed.payload["boundary"]["next_step"] == "stop"
                assert completed_checkpoint["recovery_status"] == "stopped"
                second_plan = plan_read_only_recovery(
                    completed_checkpoint, completed, config, task=state.task
                )
                assert second_plan.decision.action is ReconstructionAction.START_NEW_RUN
        elif plan.decision.action is ReconstructionAction.FINALIZE_SUCCESS:
            lock = RunLock(config.application_state_dir)
            lock.acquire()
            try:
                persistence = LockedRecoveryPersistence(
                    state_dir=config.state_dir,
                    checkpoint=checkpoint,
                    envelope=envelope,
                    config=config,
                    task=state.task,
                    lock=lock,
                )
                text, completed_checkpoint = persistence.finalize_success(boundary_sequence)
            finally:
                lock.release()
            assert text == "done"
            assert completed_checkpoint["phase"] == RunPhase.SUCCESS.value
            assert completed_checkpoint["final_text_length"] == 4
            with pytest.raises(ContinuationError, match="CONTINUATION_READ_FAILED"):
                read_continuation(config.state_dir, state.run_id)
        elif plan.decision.action is ReconstructionAction.FINALIZE_BLOCKED:
            lock = RunLock(config.application_state_dir)
            lock.acquire()
            try:
                persistence = LockedRecoveryPersistence(
                    state_dir=config.state_dir,
                    checkpoint=checkpoint,
                    envelope=envelope,
                    config=config,
                    task=state.task,
                    lock=lock,
                )
                blocked_call_count, completed_checkpoint = persistence.finalize_blocked_action(
                    boundary_sequence
                )
            finally:
                lock.release()
            assert blocked_call_count == 1
            assert completed_checkpoint["phase"] == RunPhase.FAILED.value
            assert completed_checkpoint["failure_code"] == "RECOVERED_ACTION_REQUESTED"
            with pytest.raises(ContinuationError, match="CONTINUATION_READ_FAILED"):
                read_continuation(config.state_dir, state.run_id)
        actual_calls.extend(f"tool:{item.name}" for item in desktop.tool_calls)
        actual_calls.extend(f"provider:{item['turn_id']}" for item in provider.calls)

    assert actual_calls == case["runtime_calls"], case_id
    assert all(call_name != "tool:click" for call_name in actual_calls), case_id
