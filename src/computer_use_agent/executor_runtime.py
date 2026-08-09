"""Bounded tool and tool-free final-response plan runtime."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from time import perf_counter_ns

from .continuation import RuntimeContinuationRecorder, read_continuation
from .executor import BoundedExecutorSession, ExecutorSessionError
from .executor_final import (
    ExecutorFinalError,
    FinalResponsePort,
    compile_final_response_request,
    compile_hierarchical_side_effect_final_response_request,
)
from .grounding import GroundingState
from .hierarchical_control import TreeNodeKind, TreeValidationError, project_linear_plan
from .hierarchical_runtime import (
    HierarchicalRuntimeError,
    LinearTaskTreeProjection,
    runtime_policy_digest,
)
from .hierarchical_side_effects import (
    HierarchicalSideEffectError,
    validate_bounded_side_effect_plan,
)
from .planning import PlanStepAction, PlanStepStatus, TaskPlan
from .presence_lifecycle import FailSilentLifecycle
from .runner import AgentRunner, PreparedRun, RunDeferred, RunFailure
from .trace import RunPhase, RunRecorder
from .tool_registry import reviewed_registry_digest, verify_discovered_tools
from .types import ModelTurn, RecoveryStatus, RunState, ToolEffect, ToolResult


class ExecutorRuntimeError(RuntimeError):
    """A fixed failure from the bounded Runtime Executor session."""


@dataclass(frozen=True)
class RuntimePlanStepOutcome:
    """One tool result plus the exact host and plan state after it."""

    state: RunState
    result: ToolResult
    plan_sequence: int
    plan_digest: str
    tree_sequence: int | None = None
    tree_digest: str | None = None


@dataclass(frozen=True, repr=False)
class RuntimeFinalResponseOutcome:
    """One terminal result after every final-response ordering boundary."""

    text: str
    state: RunState
    provider_response_id: str
    plan_sequence: int
    plan_digest: str
    tree_sequence: int | None = None
    tree_digest: str | None = None

    def __repr__(self) -> str:
        return (
            "RuntimeFinalResponseOutcome("
            f"run_id={self.state.run_id!r}, text_length={len(self.text)}, "
            f"provider_response_id={self.provider_response_id!r}, "
            f"plan_sequence={self.plan_sequence}, plan_digest={self.plan_digest!r}, "
            f"tree_sequence={self.tree_sequence}, tree_digest={self.tree_digest!r})"
        )


class RuntimeExecutorSession:
    """Own one lock, recorder, WAL, grounding state, and MCP generation."""

    def __init__(
        self,
        *,
        runner: AgentRunner,
        prepared_run: PreparedRun,
        contract: BoundedExecutorSession,
        recorder: RunRecorder,
        continuation: RuntimeContinuationRecorder,
        presence: FailSilentLifecycle,
        progress: FailSilentLifecycle,
        tree_projection: LinearTaskTreeProjection | None = None,
        allow_side_effects: bool = False,
    ) -> None:
        self.runner = runner
        self.prepared_run = prepared_run
        self.contract = contract
        self.recorder = recorder
        self.continuation = continuation
        self.presence = presence
        self.progress = progress
        self.tree_projection = tree_projection
        self.allow_side_effects = allow_side_effects
        self.store = prepared_run.plan_store(runner.config.state_dir)
        self.state = prepared_run.state
        self.grounding = GroundingState()
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    def _require_active(self) -> None:
        if self._closed:
            raise ExecutorRuntimeError("EXECUTOR_RUNTIME_CLOSED")

    def _tree_metadata(self) -> tuple[int | None, str | None]:
        if self.tree_projection is None:
            return None, None
        snapshot = self.tree_projection.snapshot()
        return snapshot.sequence, snapshot.tree.digest

    async def _fail_tree_projection(
        self, *, code: str, delete_continuation: bool
    ) -> None:
        self.recorder.record(self.state, RunPhase.FAILED, failure_code=code)
        await self._shutdown(delete_continuation=delete_continuation)

    async def _shutdown(self, *, delete_continuation: bool) -> None:
        if self._closed:
            return
        self._closed = True
        self.contract.close()
        try:
            if delete_continuation:
                self.continuation.close()
        finally:
            try:
                if self.runner.ports is not None:
                    await self.runner.ports.desktop.close()
            finally:
                try:
                    self.presence.release()
                finally:
                    try:
                        self.progress.release()
                    finally:
                        self.prepared_run.close()

    async def preserve_and_close(self) -> None:
        """Release live resources while retaining WAL for conservative recovery."""

        self._require_active()
        self.recorder.record(
            self.state,
            RunPhase.FAILED,
            failure_code="EXECUTOR_SESSION_PRESERVED",
        )
        await self._shutdown(delete_continuation=False)

    async def cancel(self) -> None:
        """Cancel the next untouched plan step and delete completed WAL state."""

        self._require_active()
        snapshot = self.store.read(self.state.run_id)
        step = next(
            (item for item in snapshot.plan.steps if item.status is not PlanStepStatus.COMPLETED),
            None,
        )
        if step is None or step.status is not PlanStepStatus.PENDING:
            raise ExecutorRuntimeError("EXECUTOR_RUNTIME_CANCEL_UNSAFE")
        self.store.transition(
            self.state.run_id,
            step.step_id,
            PlanStepStatus.CANCELLED,
            expected_sequence=snapshot.sequence,
            expected_plan_digest=snapshot.plan.digest,
        )
        if self.tree_projection is not None:
            try:
                self.tree_projection.cancel_pending_step(step.step_id)
            except HierarchicalRuntimeError as exc:
                await self._fail_tree_projection(
                    code="EXECUTOR_TREE_COMMIT_FAILED",
                    delete_continuation=False,
                )
                raise ExecutorRuntimeError("EXECUTOR_TREE_COMMIT_FAILED") from exc
        self.recorder.record(
            self.state,
            RunPhase.CANCELLED,
            failure_code="EXECUTOR_CANCELLED",
        )
        await self._shutdown(delete_continuation=True)

    async def execute_next_tool(self) -> RuntimePlanStepOutcome:
        """Execute one pending reviewed tool through the sole Runner boundary."""

        self._require_active()
        if self.runner.ports is None:
            raise ExecutorRuntimeError("EXECUTOR_RUNTIME_PORTS_REQUIRED")
        try:
            prepared = self.contract.prepare_next(self.state)
        except ExecutorSessionError as exc:
            raise ExecutorRuntimeError(str(exc)) from exc
        if self.tree_projection is not None:
            try:
                self.tree_projection.start_step(
                    prepared.step_id, node_kind=TreeNodeKind.TOOL_STEP
                )
            except HierarchicalRuntimeError as exc:
                await self._fail_tree_projection(
                    code="EXECUTOR_TREE_PREPARE_FAILED",
                    delete_continuation=True,
                )
                raise ExecutorRuntimeError("EXECUTOR_TREE_PREPARE_FAILED") from exc
        try:
            running = self.store.transition(
                self.state.run_id,
                prepared.step_id,
                PlanStepStatus.IN_PROGRESS,
                expected_sequence=prepared.snapshot_sequence,
                expected_plan_digest=prepared.plan_digest,
            )
        except BaseException as exc:
            if self.tree_projection is None:
                raise
            try:
                self.tree_projection.reconcile_from_plan()
            except HierarchicalRuntimeError:
                pass
            await self._fail_tree_projection(
                code="EXECUTOR_PLAN_PREPARE_FAILED",
                delete_continuation=True,
            )
            raise ExecutorRuntimeError("EXECUTOR_PLAN_PREPARE_FAILED") from exc
        try:
            outcome = await self.runner._execute_requested_call_boundary(
                self.state,
                prepared.call,
                grounding=self.grounding,
                recorder=self.recorder,
                continuation=self.continuation,
                presence=self.presence,
                progress=self.progress,
            )
        except RunDeferred as deferred:
            self.state = deferred.state
            try:
                self.store.transition(
                    self.state.run_id,
                    prepared.step_id,
                    PlanStepStatus.BLOCKED,
                    expected_sequence=running.sequence,
                    expected_plan_digest=running.plan.digest,
                )
                self.contract.accept_boundary_outcome(
                    prepared,
                    self.state,
                    expected_status=PlanStepStatus.BLOCKED,
                )
                if self.tree_projection is not None:
                    self.tree_projection.finish_step(
                        prepared.step_id,
                        PlanStepStatus.BLOCKED,
                        node_kind=TreeNodeKind.TOOL_STEP,
                    )
            except BaseException as exc:
                self.recorder.record(
                    self.state,
                    RunPhase.FAILED,
                    failure_code="EXECUTOR_DEFER_COMMIT_FAILED",
                )
                await self._shutdown(delete_continuation=False)
                raise ExecutorRuntimeError("EXECUTOR_DEFER_COMMIT_FAILED") from exc
            self.recorder.record(
                self.state,
                RunPhase.PAUSED,
                failure_code="APPROVAL_DEFERRED",
            )
            await self._shutdown(delete_continuation=True)
            raise ExecutorRuntimeError("APPROVAL_DEFERRED") from deferred
        except RunFailure as failure:
            self.state = failure.state
            if failure.code == "UNKNOWN_OUTCOME":
                try:
                    self.contract.accept_boundary_outcome(prepared, self.state)
                except ExecutorSessionError as exc:
                    await self._shutdown(delete_continuation=False)
                    raise ExecutorRuntimeError("EXECUTOR_RUNTIME_EVIDENCE_INVALID") from exc
                self.recorder.record(
                    self.state,
                    RunPhase.UNKNOWN_OUTCOME,
                    failure_code="UNKNOWN_OUTCOME",
                )
                await self._shutdown(delete_continuation=False)
                raise ExecutorRuntimeError("UNKNOWN_OUTCOME") from failure

            try:
                self.store.transition(
                    self.state.run_id,
                    prepared.step_id,
                    PlanStepStatus.FAILED,
                    expected_sequence=running.sequence,
                    expected_plan_digest=running.plan.digest,
                )
            except BaseException as exc:
                self.recorder.record(
                    self.state,
                    RunPhase.FAILED,
                    failure_code="EXECUTOR_PLAN_COMMIT_FAILED",
                )
                await self._shutdown(delete_continuation=False)
                raise ExecutorRuntimeError("EXECUTOR_PLAN_COMMIT_FAILED") from exc
            try:
                self.contract.accept_boundary_outcome(prepared, self.state)
            except ExecutorSessionError as exc:
                if self.tree_projection is None:
                    self.contract.close()
                else:
                    await self._shutdown(delete_continuation=False)
                    raise ExecutorRuntimeError(
                        "EXECUTOR_RUNTIME_EVIDENCE_INVALID"
                    ) from exc
            if self.tree_projection is not None:
                try:
                    self.tree_projection.finish_step(
                        prepared.step_id,
                        PlanStepStatus.FAILED,
                        node_kind=TreeNodeKind.TOOL_STEP,
                    )
                except HierarchicalRuntimeError as exc:
                    await self._fail_tree_projection(
                        code="EXECUTOR_TREE_COMMIT_FAILED",
                        delete_continuation=False,
                    )
                    raise ExecutorRuntimeError("EXECUTOR_TREE_COMMIT_FAILED") from exc
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code=failure.code,
            )
            await self._shutdown(delete_continuation=True)
            raise ExecutorRuntimeError(failure.code) from failure
        except BaseException:
            if self.recorder.phase is not RunPhase.UNKNOWN_OUTCOME:
                self.recorder.record(
                    self.state,
                    RunPhase.UNKNOWN_OUTCOME,
                    failure_code="EXECUTOR_RUNTIME_UNCERTAIN",
                )
            await self._shutdown(delete_continuation=False)
            raise

        self.state = outcome.state
        self.grounding = outcome.grounding
        verification_blocked = (
            not outcome.result.ok
            and self.state.recovery_status is RecoveryStatus.REQUIRES_REOBSERVATION
        )
        target = (
            PlanStepStatus.BLOCKED
            if verification_blocked
            else PlanStepStatus.COMPLETED
            if outcome.result.ok
            else PlanStepStatus.FAILED
        )
        try:
            finished = self.store.transition(
                self.state.run_id,
                prepared.step_id,
                target,
                expected_sequence=running.sequence,
                expected_plan_digest=running.plan.digest,
            )
        except BaseException as exc:
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code="EXECUTOR_PLAN_COMMIT_FAILED",
            )
            await self._shutdown(delete_continuation=False)
            raise ExecutorRuntimeError("EXECUTOR_PLAN_COMMIT_FAILED") from exc
        try:
            self.contract.accept_boundary_outcome(
                prepared,
                self.state,
                expected_status=(PlanStepStatus.BLOCKED if verification_blocked else None),
            )
        except ExecutorSessionError as exc:
            await self._shutdown(delete_continuation=False)
            raise ExecutorRuntimeError("EXECUTOR_RUNTIME_EVIDENCE_INVALID") from exc
        if self.tree_projection is not None:
            try:
                self.tree_projection.finish_step(
                    prepared.step_id,
                    target,
                    node_kind=TreeNodeKind.TOOL_STEP,
                )
            except HierarchicalRuntimeError as exc:
                await self._fail_tree_projection(
                    code="EXECUTOR_TREE_COMMIT_FAILED",
                    delete_continuation=False,
                )
                raise ExecutorRuntimeError("EXECUTOR_TREE_COMMIT_FAILED") from exc
        if verification_blocked:
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code="EXECUTOR_VERIFICATION_REQUIRED",
            )
            await self._shutdown(delete_continuation=False)
            raise ExecutorRuntimeError("EXECUTOR_VERIFICATION_REQUIRED")
        if not outcome.result.ok:
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code="EXECUTOR_TOOL_FAILED",
            )
            await self._shutdown(delete_continuation=True)
            raise ExecutorRuntimeError("EXECUTOR_TOOL_FAILED")
        tree_sequence, tree_digest = self._tree_metadata()
        return RuntimePlanStepOutcome(
            state=self.state,
            result=outcome.result,
            plan_sequence=finished.sequence,
            plan_digest=finished.plan.digest,
            tree_sequence=tree_sequence,
            tree_digest=tree_digest,
        )

    async def execute_next_observation(self) -> RuntimePlanStepOutcome:
        """Execute one pending observation without accepting an action step."""

        self._require_active()
        snapshot = self.store.read(self.state.run_id)
        step = next(
            (
                item
                for item in snapshot.plan.steps
                if item.status is not PlanStepStatus.COMPLETED
            ),
            None,
        )
        if (
            step is None
            or step.action is not PlanStepAction.TOOL
            or step.effect is not ToolEffect.OBSERVATION
        ):
            raise ExecutorRuntimeError("EXECUTOR_SESSION_SIDE_EFFECT_UNSUPPORTED")
        return await self.execute_next_tool()

    async def execute_final_response(
        self, port: FinalResponsePort
    ) -> RuntimeFinalResponseOutcome:
        """Execute one tool-free final response through its dedicated WAL.

        The persisted plan and final-response WAL remain non-authorizing data.
        The provider is called exactly once, only after the final step is
        ``in_progress`` and dispatch intent is durable. Any later failure
        preserves both WALs, closes the session, and is never retried here.
        """

        self._require_active()
        if not isinstance(port, FinalResponsePort):
            raise ExecutorRuntimeError("EXECUTOR_FINAL_PORT_REQUIRED")

        snapshot = self.store.read(self.state.run_id)
        final_step = next(
            (
                step
                for step in snapshot.plan.steps
                if step.status is not PlanStepStatus.COMPLETED
            ),
            None,
        )
        if final_step is None or final_step.action is not PlanStepAction.FINAL_RESPONSE:
            raise ExecutorRuntimeError("EXECUTOR_FINAL_PLAN_NOT_READY")
        turn_id = "executor_final_1"
        try:
            compile_request = (
                compile_hierarchical_side_effect_final_response_request
                if self.allow_side_effects
                else compile_final_response_request
            )
            request = compile_request(
                snapshot,
                self.state,
                expected_sequence=snapshot.sequence,
                expected_plan_digest=snapshot.plan.digest,
                turn_id=turn_id,
            )
        except ExecutorFinalError as exc:
            raise ExecutorRuntimeError(str(exc)) from exc

        if self.tree_projection is not None:
            try:
                self.tree_projection.start_step(
                    final_step.step_id,
                    node_kind=TreeNodeKind.FINAL_RESPONSE,
                )
            except HierarchicalRuntimeError as exc:
                await self._fail_tree_projection(
                    code="EXECUTOR_TREE_PREPARE_FAILED",
                    delete_continuation=True,
                )
                raise ExecutorRuntimeError("EXECUTOR_TREE_PREPARE_FAILED") from exc

        final_store = self.prepared_run.final_response_store(
            self.runner.config.state_dir
        )
        intent_written = False
        try:
            source_continuation = read_continuation(
                self.runner.config.state_dir, self.state.run_id
            )
            continuation_digest = source_continuation.payload.get("payload_digest")
            if not isinstance(continuation_digest, str):
                raise ExecutorRuntimeError("EXECUTOR_FINAL_EVIDENCE_INVALID")
            prepared = final_store.create(
                request,
                step_id=final_step.step_id,
                checkpoint_sequence=self.recorder.checkpoint_sequence,
                continuation_digest=continuation_digest,
            )
            running = self.store.transition(
                self.state.run_id,
                final_step.step_id,
                PlanStepStatus.IN_PROGRESS,
                expected_sequence=snapshot.sequence,
                expected_plan_digest=snapshot.plan.digest,
            )
            intent = final_store.mark_dispatch_intent(
                self.state.run_id,
                expected_sequence=prepared.sequence,
                expected_digest=prepared.envelope_digest,
            )
            intent_written = True
            provider_started_ns = perf_counter_ns()
            result = await port.create_final_response(request)
            provider_latency_ms = max(
                0, (perf_counter_ns() - provider_started_ns) // 1_000_000
            )
            completed = final_store.complete(
                self.state.run_id,
                result,
                provider_latency_ms=provider_latency_ms,
                expected_sequence=intent.sequence,
                expected_digest=intent.envelope_digest,
            )
            if completed.result is None:
                raise ExecutorRuntimeError("EXECUTOR_FINAL_EVIDENCE_INVALID")
            durable_result = completed.result
            turn = ModelTurn(
                run_id=durable_result.run_id,
                turn_id=durable_result.turn_id,
                provider_response_id=durable_result.provider_response_id,
                text=durable_result.text,
                usage=durable_result.usage,
            )
            self.state = self.runner._consume_model_turn(
                self.state,
                turn,
                latency_ms=provider_latency_ms,
            )
            finished = self.store.transition(
                self.state.run_id,
                final_step.step_id,
                PlanStepStatus.COMPLETED,
                expected_sequence=running.sequence,
                expected_plan_digest=running.plan.digest,
            )
            if self.tree_projection is not None:
                self.tree_projection.finish_step(
                    final_step.step_id,
                    PlanStepStatus.COMPLETED,
                    node_kind=TreeNodeKind.FINAL_RESPONSE,
                )
            self.recorder.record(
                self.state,
                RunPhase.SUCCESS,
                final_text_length=len(durable_result.text),
            )
        except asyncio.CancelledError:
            if self.tree_projection is not None:
                try:
                    self.tree_projection.reconcile_from_plan()
                except HierarchicalRuntimeError:
                    pass
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code=(
                    "EXECUTOR_FINAL_UNCERTAIN"
                    if intent_written
                    else "EXECUTOR_FINAL_PREPARE_FAILED"
                ),
            )
            await self._shutdown(delete_continuation=False)
            raise
        except BaseException as exc:
            if self.tree_projection is not None:
                try:
                    self.tree_projection.reconcile_from_plan()
                except HierarchicalRuntimeError:
                    pass
            code = (
                "EXECUTOR_FINAL_UNCERTAIN"
                if intent_written
                else "EXECUTOR_FINAL_PREPARE_FAILED"
            )
            self.recorder.record(self.state, RunPhase.FAILED, failure_code=code)
            await self._shutdown(delete_continuation=False)
            raise ExecutorRuntimeError(code) from exc

        tree_sequence, tree_digest = self._tree_metadata()
        outcome = RuntimeFinalResponseOutcome(
            text=durable_result.text,
            state=self.state,
            provider_response_id=durable_result.provider_response_id,
            plan_sequence=finished.sequence,
            plan_digest=finished.plan.digest,
            tree_sequence=tree_sequence,
            tree_digest=tree_digest,
        )
        await self._shutdown(delete_continuation=True)
        return outcome


async def _open_runtime_executor_session(
    runner: AgentRunner,
    *,
    task: str,
    plan: TaskPlan,
    tree_id: str | None,
    allow_hierarchical_side_effects: bool = False,
) -> RuntimeExecutorSession:
    """Open one new runtime session, optionally with the exact H4 projection."""

    if (
        not isinstance(runner, AgentRunner)
        or not isinstance(plan, TaskPlan)
        or not isinstance(allow_hierarchical_side_effects, bool)
    ):
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_INPUT_INVALID")
    if not isinstance(task, str) or not task:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_INPUT_INVALID")
    try:
        task_digest = sha256(task.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_TASK_MISMATCH") from exc
    if plan.task_digest != task_digest:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_TASK_MISMATCH")
    if tree_id is not None and (not isinstance(tree_id, str) or not tree_id):
        raise ExecutorRuntimeError("EXECUTOR_TREE_PLAN_UNSAFE")
    if tree_id is None and allow_hierarchical_side_effects:
        raise ExecutorRuntimeError("EXECUTOR_TREE_PLAN_UNSAFE")
    if tree_id is not None and allow_hierarchical_side_effects:
        try:
            validate_bounded_side_effect_plan(plan)
        except HierarchicalSideEffectError as exc:
            raise ExecutorRuntimeError("EXECUTOR_TREE_PLAN_UNSAFE") from exc
    elif tree_id is not None and any(
        step.action is PlanStepAction.TOOL
        and step.effect is not ToolEffect.OBSERVATION
        for step in plan.steps
    ):
        raise ExecutorRuntimeError("EXECUTOR_TREE_PLAN_UNSAFE")
    if tree_id is not None:
        try:
            project_linear_plan(
                plan,
                tree_id=tree_id,
                policy_digest=runtime_policy_digest(runner.policy),
            )
        except (HierarchicalRuntimeError, TreeValidationError) as exc:
            raise ExecutorRuntimeError("EXECUTOR_TREE_INPUT_INVALID") from exc
    if not runner.config.continuation.enabled:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_WAL_REQUIRED")
    if runner.ports is None:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_PORTS_REQUIRED")

    prepared_run = runner.prepare(task, run_id=plan.run_id)
    presence = FailSilentLifecycle(runner.ports.presence)
    progress = FailSilentLifecycle(runner.ports.progress)

    def publish_operator_phase(phase: RunPhase) -> None:
        presence.on_phase(phase)
        progress.on_phase(phase)

    recorder = RunRecorder(
        runner.config.state_dir,
        plan.run_id,
        phase_observer=publish_operator_phase,
    )
    recorder_started = False
    continuation: RuntimeContinuationRecorder | None = None
    tree_projection: LinearTaskTreeProjection | None = None
    try:
        store = prepared_run.plan_store(runner.config.state_dir)
        store.create(plan)
        if tree_id is not None:
            create_projection = (
                LinearTaskTreeProjection.create_bounded_side_effect
                if allow_hierarchical_side_effects
                else LinearTaskTreeProjection.create
            )
            tree_projection = create_projection(
                store,
                prepared_run.tree_store(runner.config.state_dir),
                plan,
                tree_id=tree_id,
                policy_digest=runtime_policy_digest(runner.policy),
            )
        recorder.start(prepared_run.state)
        recorder_started = True
        recorder.record(prepared_run.state, RunPhase.OBSERVING)
        discovered = await runner.ports.desktop.discover_tools()
        verify_discovered_tools(discovered)
        continuation = RuntimeContinuationRecorder(
            state_dir=runner.config.state_dir,
            state=prepared_run.state,
            provider_name=runner.config.provider.name,
            provider_model=runner.config.provider.model,
            registry_digest=reviewed_registry_digest(),
            advertised_tool_names=frozenset(),
            ttl_seconds=runner.config.continuation.ttl_seconds,
            mcp_generation=runner.ports.desktop.generation,
        )
        recorder.record(prepared_run.state, RunPhase.PLANNING)
        contract = BoundedExecutorSession(
            store,
            prepared_run.state,
            allow_side_effects=allow_hierarchical_side_effects,
        )
        return RuntimeExecutorSession(
            runner=runner,
            prepared_run=prepared_run,
            contract=contract,
            recorder=recorder,
            continuation=continuation,
            presence=presence,
            progress=progress,
            tree_projection=tree_projection,
            allow_side_effects=allow_hierarchical_side_effects,
        )
    except BaseException:
        try:
            if recorder_started:
                recorder.record(
                    prepared_run.state,
                    RunPhase.FAILED,
                    failure_code="EXECUTOR_RUNTIME_OPEN_FAILED",
                )
        finally:
            try:
                if continuation is not None:
                    continuation.close()
            finally:
                try:
                    await runner.ports.desktop.close()
                finally:
                    try:
                        presence.release()
                    finally:
                        try:
                            progress.release()
                        finally:
                            prepared_run.close()
        raise


async def open_runtime_executor_session(
    runner: AgentRunner, *, task: str, plan: TaskPlan
) -> RuntimeExecutorSession:
    """Open one new observation-only runtime session; never resume implicitly."""

    return await _open_runtime_executor_session(
        runner,
        task=task,
        plan=plan,
        tree_id=None,
    )


async def open_hierarchical_runtime_executor_session(
    runner: AgentRunner,
    *,
    task: str,
    plan: TaskPlan,
    tree_id: str,
) -> RuntimeExecutorSession:
    """Open the H4 linear-tree projection over the sole existing runtime."""

    return await _open_runtime_executor_session(
        runner,
        task=task,
        plan=plan,
        tree_id=tree_id,
    )


async def open_hierarchical_side_effect_runtime_executor_session(
    runner: AgentRunner,
    *,
    task: str,
    plan: TaskPlan,
    tree_id: str,
) -> RuntimeExecutorSession:
    """Open one H7 sequence without adding an approval or dispatch path."""

    return await _open_runtime_executor_session(
        runner,
        task=task,
        plan=plan,
        tree_id=tree_id,
        allow_hierarchical_side_effects=True,
    )


__all__ = [
    "ExecutorRuntimeError",
    "RuntimeExecutorSession",
    "RuntimeFinalResponseOutcome",
    "RuntimePlanStepOutcome",
    "open_hierarchical_side_effect_runtime_executor_session",
    "open_hierarchical_runtime_executor_session",
    "open_runtime_executor_session",
]
