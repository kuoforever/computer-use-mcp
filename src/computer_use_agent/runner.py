"""Bounded provider-neutral Agent workflow for the local desktop bridge."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from uuid import uuid4

from .config import AgentConfig, READ_ONLY_MODE
from .policy import HostPolicy, PolicyDisposition
from .run_lock import RunLock
from .tool_registry import (
    REVIEWED_TOOLS,
    ToolValidationError,
    get_tool_spec,
    validate_tool_arguments,
    validate_tool_result,
    verify_discovered_tools,
)
from .types import (
    ApprovalPort,
    DesktopMCPPort,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    ModelProviderPort,
    ModelTurn,
    RecoveryStatus,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolCallStatus,
    ToolResult,
    ToolResultStatus,
)


class RunnerError(RuntimeError):
    """A fixed workflow failure that does not embed task or desktop content."""


class RunnerBudgetError(RunnerError):
    """Raised when a model or tool-call hard bound is reached."""


class RunFailure(RunnerError):
    """A reviewed failure code plus the canonical state reached before stopping."""

    def __init__(self, code: str, state: RunState) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("failure code must be a non-empty string")
        if not isinstance(state, RunState):
            raise ValueError("state must be a RunState")
        super().__init__(code)
        self.code = code
        self.state = state


@dataclass(frozen=True)
class RunOutcome:
    """Completed read-only run output and its final in-memory audit state."""

    text: str
    state: RunState


@dataclass(frozen=True)
class RunnerPorts:
    """Injected external boundaries used by the bounded workflow."""

    provider: ModelProviderPort
    desktop: DesktopMCPPort
    approvals: ApprovalPort


@dataclass
class PreparedRun:
    """An initial in-memory run state that owns one local run lock."""

    state: RunState
    _lock: RunLock = field(repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def closed(self) -> bool:
        return self._closed

    def close(self) -> None:
        if self._closed:
            return
        self._lock.release()
        self._closed = True

    def __enter__(self) -> "PreparedRun":
        if self._closed:
            raise RuntimeError("prepared run is already closed")
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()


class AgentRunner:
    """Prepare and execute a bounded provider-neutral read-only workflow."""

    def __init__(self, config: AgentConfig, ports: RunnerPorts | None = None) -> None:
        if not isinstance(config, AgentConfig):
            raise ValueError("config must be an AgentConfig")
        if ports is not None and not isinstance(ports, RunnerPorts):
            raise ValueError("ports must be RunnerPorts or None")
        self.config = config
        self.ports = ports
        self.policy = HostPolicy.from_config(config.policy_version, config.policy)

    def prepare(self, task: str, *, run_id: str | None = None) -> PreparedRun:
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        resolved_run_id = run_id or uuid4().hex
        if not isinstance(resolved_run_id, str) or not resolved_run_id.strip():
            raise ValueError("run_id must be a non-empty string")

        state = RunState(
            run_id=resolved_run_id,
            task=task,
            policy_version=self.policy.version,
            observation_epoch=0,
            budgets=self.policy.initial_budget(),
            event_log=(
                LedgerEvent(
                    event_id=f"{resolved_run_id}:event:1",
                    kind=LedgerEventKind.USER_TASK,
                    payload={"task_length": len(task)},
                ),
            ),
        )
        lock = RunLock(self.config.application_state_dir)
        lock.acquire()
        return PreparedRun(state=state, _lock=lock)

    @staticmethod
    def _event_id(state: RunState) -> str:
        return f"{state.run_id}:event:{len(state.event_log) + 1}"

    @staticmethod
    def _append(state: RunState, event: LedgerEvent, **changes: object) -> RunState:
        return replace(state, event_log=state.event_log + (event,), **changes)

    def _consume_model_turn(self, state: RunState, turn: ModelTurn) -> RunState:
        if state.budgets.model_turns_used >= state.budgets.max_model_turns:
            raise RunnerBudgetError("MODEL_TURN_BUDGET_EXHAUSTED")
        budget = replace(state.budgets, model_turns_used=state.budgets.model_turns_used + 1)
        return self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.MODEL_TURN,
                payload={
                    "provider_response_id": turn.provider_response_id,
                    "text_length": len(turn.text),
                    "tool_call_count": len(turn.tool_calls),
                    "input_tokens": turn.usage.input_tokens,
                    "output_tokens": turn.usage.output_tokens,
                },
            ),
            budgets=budget,
        )

    def _record_call(self, state: RunState, call: ToolCall) -> RunState:
        if state.budgets.tool_calls_used >= state.budgets.max_tool_calls:
            raise RunnerBudgetError("TOOL_CALL_BUDGET_EXHAUSTED")
        spec = get_tool_spec(call.name)
        normalized = validate_tool_arguments(call.name, call.arguments)
        if dict(call.arguments) != normalized:
            raise ToolValidationError("tool arguments are not in canonical form")
        budget = replace(state.budgets, tool_calls_used=state.budgets.tool_calls_used + 1)
        return self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.TOOL_CALL,
                identity=call.identity,
                safe_argument_summary=SafeArgumentSummary.from_tool_call(
                    call, sensitive_arguments=spec.sensitive_arguments
                ),
            ),
            budgets=budget,
        )

    def _record_result(self, state: RunState, result: ToolResult) -> RunState:
        observation_epoch = state.observation_epoch
        verified_epoch = state.verified_observation_epoch
        if result.ok:
            observation_epoch += 1
            verified_epoch = observation_epoch
        state = self._append(
            state,
            LedgerEvent(
                event_id=self._event_id(state),
                kind=LedgerEventKind.TOOL_RESULT,
                identity=result.identity,
                tool_result=result,
            ),
            observation_epoch=observation_epoch,
            verified_observation_epoch=verified_epoch,
            recovery_status=(
                RecoveryStatus.UNKNOWN_OUTCOME
                if result.status is ToolResultStatus.UNKNOWN_OUTCOME
                else state.recovery_status
            ),
        )
        if result.ok:
            state = self._append(
                state,
                LedgerEvent(
                    event_id=self._event_id(state),
                    kind=LedgerEventKind.OBSERVATION,
                    payload={
                        "tool_name": result.tool_name,
                        "observation_epoch": observation_epoch,
                    },
                    identity=result.identity,
                ),
            )
        return state

    async def run(self, task: str, *, run_id: str | None = None) -> RunOutcome:
        """Run a bounded read-only model/tool loop and release lock and desktop."""

        if self.ports is None:
            raise RunnerError("RUNNER_PORTS_REQUIRED")
        if self.config.policy.mode != READ_ONLY_MODE:
            raise RunnerError("READ_ONLY_RUNTIME_REQUIRED")

        prepared = self.prepare(task, run_id=run_id)
        state = prepared.state
        try:
            discovered = await self.ports.desktop.discover_tools()
            verify_discovered_tools(discovered)
            turn_index = 0
            while True:
                if state.budgets.model_turns_used >= state.budgets.max_model_turns:
                    raise RunFailure("MODEL_TURN_BUDGET_EXHAUSTED", state)
                turn_index += 1
                turn_id = f"turn_{turn_index}"
                turn = await self.ports.provider.create_turn(
                    run_id=state.run_id,
                    turn_id=turn_id,
                    task=state.task,
                    ledger=state.event_log,
                    tools=REVIEWED_TOOLS,
                )
                if turn.run_id != state.run_id or turn.turn_id != turn_id:
                    raise RunFailure("PROVIDER_TURN_IDENTITY_MISMATCH", state)
                state = self._consume_model_turn(state, turn)
                if not turn.tool_calls:
                    return RunOutcome(text=turn.text, state=state)

                for call in turn.tool_calls:
                    try:
                        state = self._record_call(state, call)
                    except RunnerBudgetError as exc:
                        raise RunFailure(str(exc), state) from exc
                    except ToolValidationError as exc:
                        raise RunFailure("SCHEMA_MISMATCH", state) from exc
                    spec = get_tool_spec(call.name)
                    if self.policy.disposition(spec) is not PolicyDisposition.ALLOW:
                        denied = ToolResult(
                            identity=call.identity,
                            tool_name=call.name,
                            status=ToolResultStatus.REJECTED,
                            dispatch=DispatchCertainty.NOT_DISPATCHED,
                            code="POLICY_DENIED",
                        )
                        state = self._record_result(state, denied)
                        raise RunFailure("POLICY_DENIED", state)
                    authorized_call = replace(call, status=ToolCallStatus.AUTHORIZED)
                    result = await self.ports.desktop.call_tool(authorized_call)
                    validate_tool_result(authorized_call, result)
                    state = self._record_result(state, result)
                    if result.status is ToolResultStatus.UNKNOWN_OUTCOME:
                        raise RunFailure("UNKNOWN_OUTCOME", state)
        finally:
            prepared.close()
            await self.ports.desktop.close()
