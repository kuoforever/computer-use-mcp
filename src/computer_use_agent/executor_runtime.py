"""First bounded runtime bridge from observation plans to the host call boundary."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from .continuation import RuntimeContinuationRecorder
from .executor import BoundedExecutorSession, ExecutorSessionError
from .grounding import GroundingState
from .planning import PlanStepStatus, TaskPlan
from .runner import AgentRunner, PreparedRun, RunFailure
from .trace import RunPhase, RunRecorder
from .tool_registry import reviewed_registry_digest, verify_discovered_tools
from .types import RunState, ToolResult


class ExecutorRuntimeError(RuntimeError):
    """A fixed failure from the bounded observation-only runtime session."""


@dataclass(frozen=True)
class RuntimePlanStepOutcome:
    """One observation result plus the exact host and plan state after it."""

    state: RunState
    result: ToolResult
    plan_sequence: int
    plan_digest: str


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
    ) -> None:
        self.runner = runner
        self.prepared_run = prepared_run
        self.contract = contract
        self.recorder = recorder
        self.continuation = continuation
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
        self.recorder.record(
            self.state,
            RunPhase.CANCELLED,
            failure_code="EXECUTOR_CANCELLED",
        )
        await self._shutdown(delete_continuation=True)

    async def execute_next_observation(self) -> RuntimePlanStepOutcome:
        """Execute one pending observation through the sole Runner boundary."""

        self._require_active()
        if self.runner.ports is None:
            raise ExecutorRuntimeError("EXECUTOR_RUNTIME_PORTS_REQUIRED")
        try:
            prepared = self.contract.prepare_next(self.state)
        except ExecutorSessionError as exc:
            raise ExecutorRuntimeError(str(exc)) from exc
        running = self.store.transition(
            self.state.run_id,
            prepared.step_id,
            PlanStepStatus.IN_PROGRESS,
            expected_sequence=prepared.snapshot_sequence,
            expected_plan_digest=prepared.plan_digest,
        )
        try:
            outcome = await self.runner._execute_requested_call_boundary(
                self.state,
                prepared.call,
                grounding=self.grounding,
                recorder=self.recorder,
                continuation=self.continuation,
            )
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
            except ExecutorSessionError:
                self.contract.close()
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code=failure.code,
            )
            await self._shutdown(delete_continuation=True)
            raise ExecutorRuntimeError(failure.code) from failure
        except BaseException:
            self.recorder.record(
                self.state,
                RunPhase.UNKNOWN_OUTCOME,
                failure_code="EXECUTOR_RUNTIME_UNCERTAIN",
            )
            await self._shutdown(delete_continuation=False)
            raise

        self.state = outcome.state
        self.grounding = outcome.grounding
        target = PlanStepStatus.COMPLETED if outcome.result.ok else PlanStepStatus.FAILED
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
            self.contract.accept_boundary_outcome(prepared, self.state)
        except ExecutorSessionError as exc:
            await self._shutdown(delete_continuation=False)
            raise ExecutorRuntimeError("EXECUTOR_RUNTIME_EVIDENCE_INVALID") from exc
        if not outcome.result.ok:
            self.recorder.record(
                self.state,
                RunPhase.FAILED,
                failure_code="EXECUTOR_TOOL_FAILED",
            )
            await self._shutdown(delete_continuation=True)
            raise ExecutorRuntimeError("EXECUTOR_TOOL_FAILED")
        return RuntimePlanStepOutcome(
            state=self.state,
            result=outcome.result,
            plan_sequence=finished.sequence,
            plan_digest=finished.plan.digest,
        )


async def open_runtime_executor_session(
    runner: AgentRunner, *, task: str, plan: TaskPlan
) -> RuntimeExecutorSession:
    """Open one new observation-only runtime session; never resume implicitly."""

    if not isinstance(runner, AgentRunner) or not isinstance(plan, TaskPlan):
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_INPUT_INVALID")
    if not isinstance(task, str) or not task:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_INPUT_INVALID")
    try:
        task_digest = sha256(task.encode("utf-8")).hexdigest()
    except UnicodeError as exc:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_TASK_MISMATCH") from exc
    if plan.task_digest != task_digest:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_TASK_MISMATCH")
    if not runner.config.continuation.enabled:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_WAL_REQUIRED")
    if runner.ports is None:
        raise ExecutorRuntimeError("EXECUTOR_RUNTIME_PORTS_REQUIRED")

    prepared_run = runner.prepare(task, run_id=plan.run_id)
    recorder = RunRecorder(runner.config.state_dir, plan.run_id)
    recorder_started = False
    continuation: RuntimeContinuationRecorder | None = None
    try:
        store = prepared_run.plan_store(runner.config.state_dir)
        store.create(plan)
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
            ttl_seconds=runner.config.continuation.ttl_seconds,
            mcp_generation=runner.ports.desktop.generation,
        )
        recorder.record(prepared_run.state, RunPhase.PLANNING)
        contract = BoundedExecutorSession(store, prepared_run.state)
        return RuntimeExecutorSession(
            runner=runner,
            prepared_run=prepared_run,
            contract=contract,
            recorder=recorder,
            continuation=continuation,
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
                    prepared_run.close()
        raise


__all__ = [
    "ExecutorRuntimeError",
    "RuntimeExecutorSession",
    "RuntimePlanStepOutcome",
    "open_runtime_executor_session",
]
