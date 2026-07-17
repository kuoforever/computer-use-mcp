"""One fixed synthetic campaign observation through the Agent authority boundary.

This internal slice binds an already-claimed first campaign item to one
``list_windows`` observation.  It has no provider, CLI, free-form selector,
extraction, commit, resume, side-effect, or campaign-specific MCP path.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter_ns

from .batch_coordinator import BatchCoordinator, BatchCoordinatorError, BatchSession
from .campaign import ItemStatus, ItemTransition
from .grounding import GroundingState
from .runner import AgentRunner, PreparedRun, RunFailure
from .tool_registry import verify_discovered_tools
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall, ToolResult


SYNTHETIC_CAMPAIGN_KIND = "synthetic_read_only_observation"
SYNTHETIC_ITEM_KEY = "synthetic:list_windows"
SYNTHETIC_OBSERVATION_TOOL = "list_windows"
SYNTHETIC_TURN_ID = "campaign_observation_1"
SYNTHETIC_CALL_ID = "campaign_observation_call_1"


class CampaignObservationRuntimeError(RuntimeError):
    """Fixed failure from the bounded synthetic observation runtime."""


@dataclass(frozen=True)
class CampaignObservationOutcome:
    """Correlated Runner evidence and the persisted OBSERVED boundary."""

    state: RunState
    result: ToolResult
    observed: ItemTransition


async def execute_claimed_synthetic_observation(
    runner: AgentRunner,
    prepared_run: PreparedRun,
    session: BatchSession,
    *,
    now: datetime,
) -> CampaignObservationOutcome:
    """Observe the exact claimed synthetic item once, then persist OBSERVED.

    The prepared run owns the same application lock used by the campaign store.
    This function consumes and closes that run and the injected desktop port on
    every outcome.  A failed, uncorrelated, or uncertain result leaves the item
    at ``CLAIMED``.
    """

    if (
        not isinstance(runner, AgentRunner)
        or not isinstance(prepared_run, PreparedRun)
        or not isinstance(session, BatchSession)
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
    ):
        raise CampaignObservationRuntimeError("CAMPAIGN_OBSERVATION_INPUT_INVALID")
    if runner.ports is None:
        prepared_run.close()
        raise CampaignObservationRuntimeError("CAMPAIGN_OBSERVATION_PORTS_REQUIRED")
    if (
        prepared_run.closed
        or prepared_run.application_state_dir
        != runner.config.application_state_dir
    ):
        prepared_run.close()
        raise CampaignObservationRuntimeError("CAMPAIGN_OBSERVATION_RUNNER_MISMATCH")

    state = prepared_run.state
    recorder = RunRecorder(runner.config.state_dir, state.run_id)
    recorder_started = False
    started_ns = perf_counter_ns()
    store = prepared_run.campaign_store(runner.config.state_dir)
    coordinator = BatchCoordinator(store)
    try:
        manifest = store.read_manifest(session.campaign_id)
        if (
            prepared_run.closed
            or state.run_id != session.run_id
            or manifest.kind != SYNTHETIC_CAMPAIGN_KIND
            or session.plan.item_keys != (SYNTHETIC_ITEM_KEY,)
        ):
            raise CampaignObservationRuntimeError(
                "CAMPAIGN_OBSERVATION_BINDING_INVALID"
            )
        preflight = coordinator.inspect_first_claimed_item(session, now=now)
        if (
            not preflight.ready
            or preflight.item_key != SYNTHETIC_ITEM_KEY
        ):
            raise CampaignObservationRuntimeError(
                f"CAMPAIGN_OBSERVATION_BLOCKED_{preflight.state.value}"
            )

        recorder.start(state)
        recorder_started = True
        recorder.record(state, RunPhase.OBSERVING)
        discovered = await runner.ports.desktop.discover_tools()
        verify_discovered_tools(discovered)
        recorder.record(state, RunPhase.PLANNING)
        call = ToolCall(
            identity=CallIdentity(
                run_id=session.run_id,
                turn_id=SYNTHETIC_TURN_ID,
                call_id=SYNTHETIC_CALL_ID,
            ),
            name=SYNTHETIC_OBSERVATION_TOOL,
            arguments={},
        )
        try:
            boundary = await runner._execute_requested_call_boundary(
                state,
                call,
                grounding=GroundingState(),
                recorder=recorder,
                continuation=None,
            )
        except RunFailure as exc:
            state = exc.state
            phase = (
                RunPhase.UNKNOWN_OUTCOME
                if exc.code == "UNKNOWN_OUTCOME"
                else RunPhase.FAILED
            )
            recorder.record(
                state,
                phase,
                failure_code=exc.code,
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise CampaignObservationRuntimeError(exc.code) from exc

        state = boundary.state
        if not boundary.result.ok:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code="CAMPAIGN_OBSERVATION_TOOL_FAILED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise CampaignObservationRuntimeError(
                "CAMPAIGN_OBSERVATION_TOOL_FAILED"
            )
        try:
            observed = coordinator.record_first_claimed_item_observed(
                session,
                now=now,
                application_state_verified=True,
                item_identity_verified=True,
            )
        except BatchCoordinatorError as exc:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code="CAMPAIGN_OBSERVATION_PERSIST_FAILED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise CampaignObservationRuntimeError(
                "CAMPAIGN_OBSERVATION_PERSIST_FAILED"
            ) from exc
        if observed.status is not ItemStatus.OBSERVED:
            raise CampaignObservationRuntimeError(
                "CAMPAIGN_OBSERVATION_EVIDENCE_INVALID"
            )
        recorder.record(
            state,
            RunPhase.SUCCESS,
            run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
        )
        return CampaignObservationOutcome(
            state=state,
            result=boundary.result,
            observed=observed,
        )
    except asyncio.CancelledError:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.CANCELLED,
                failure_code="CANCELLED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise
    except CampaignObservationRuntimeError:
        raise
    except Exception as exc:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.UNKNOWN_OUTCOME,
                failure_code="CAMPAIGN_OBSERVATION_UNCERTAIN",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise CampaignObservationRuntimeError(
            "CAMPAIGN_OBSERVATION_UNCERTAIN"
        ) from exc
    finally:
        try:
            await runner.ports.desktop.close()
        finally:
            prepared_run.close()


__all__ = [
    "CampaignObservationOutcome",
    "CampaignObservationRuntimeError",
    "SYNTHETIC_CALL_ID",
    "SYNTHETIC_CAMPAIGN_KIND",
    "SYNTHETIC_ITEM_KEY",
    "SYNTHETIC_OBSERVATION_TOOL",
    "SYNTHETIC_TURN_ID",
    "execute_claimed_synthetic_observation",
]
