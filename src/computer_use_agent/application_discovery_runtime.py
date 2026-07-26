"""One bounded adapter discovery pass through the sole Runner boundary.

Preparation opens no port and creates only the empty reviewed campaign for one
registered adapter kind.  Observation runs exactly one foreground
``ui_snapshot`` through the existing dispatch boundary, binds the adapter from
the durable manifest kind rather than from any caller argument, and persists
only prefixed public identities plus one discovery-pass record.

The provider is forbidden on this path, no action or navigation tool is
reachable, and the observed text is never written to a durable record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter_ns

from .application_campaign_discovery import (
    ApplicationDiscoveryError,
    ApplicationDiscoveryOutcome,
    create_application_discovery_campaign,
    inspect_application_discovery_campaign,
    record_application_snapshot_discoveries,
)
from .discovery_adapters import (
    DISCOVERY_OBSERVATION_TOOL,
    DiscoveryAdapterError,
    discovery_adapter_for_kind,
)
from .grounding import GroundingState
from .presence_lifecycle import FailSilentLifecycle
from .runner import AgentRunner, RunFailure
from .tool_registry import verify_discovered_tools
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall, ToolResult


APPLICATION_DISCOVERY_TASK = "Observe one foreground application discovery source"
APPLICATION_DISCOVERY_TURN_ID = "application_discovery_pass_1"
APPLICATION_DISCOVERY_CALL_ID = "application_discovery_pass_call_1"


class ApplicationDiscoveryRuntimeError(RuntimeError):
    """Fixed failure from the generic discovery observation boundary."""


@dataclass(frozen=True)
class ApplicationDiscoveryPreparationOutcome:
    campaign_id: str
    campaign_kind: str
    adapter_id: str
    run_id: str


@dataclass(frozen=True)
class ApplicationDiscoveryObservationOutcome:
    state: RunState
    result: ToolResult
    discovery: ApplicationDiscoveryOutcome


def _require_now(now: datetime) -> str:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise ApplicationDiscoveryRuntimeError("APPLICATION_DISCOVERY_TIME_INVALID")
    return now.isoformat(timespec="seconds")


def prepare_application_discovery_campaign(
    runner: AgentRunner,
    *,
    campaign_kind: str,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> ApplicationDiscoveryPreparationOutcome:
    """Create only the empty reviewed campaign for one registered adapter."""

    if not isinstance(runner, AgentRunner) or runner.ports is not None:
        raise ApplicationDiscoveryRuntimeError("APPLICATION_DISCOVERY_INPUT_INVALID")
    timestamp = _require_now(now)
    try:
        adapter = discovery_adapter_for_kind(campaign_kind)
    except DiscoveryAdapterError as exc:
        raise ApplicationDiscoveryRuntimeError(str(exc)) from exc
    prepared = runner.prepare(APPLICATION_DISCOVERY_TASK, run_id=run_id)
    try:
        manifest = create_application_discovery_campaign(
            prepared.campaign_store(runner.config.state_dir),
            adapter=adapter,
            campaign_id=campaign_id,
            created_at=timestamp,
        )
        return ApplicationDiscoveryPreparationOutcome(
            campaign_id=manifest.campaign_id,
            campaign_kind=manifest.kind,
            adapter_id=adapter.adapter_id,
            run_id=prepared.state.run_id,
        )
    except ApplicationDiscoveryError as exc:
        raise ApplicationDiscoveryRuntimeError(str(exc)) from exc
    finally:
        prepared.close()


async def execute_application_discovery_pass(
    runner: AgentRunner, *, campaign_id: str, run_id: str, now: datetime
) -> ApplicationDiscoveryObservationOutcome:
    """Observe the foreground once and persist only validated identities."""

    if not isinstance(runner, AgentRunner) or runner.ports is None:
        raise ApplicationDiscoveryRuntimeError("APPLICATION_DISCOVERY_PORTS_REQUIRED")
    timestamp = _require_now(now)
    try:
        prepared = runner.prepare(APPLICATION_DISCOVERY_TASK, run_id=run_id)
    except Exception:
        await runner.ports.desktop.close()
        raise
    state = prepared.state
    presence = FailSilentLifecycle(runner.ports.presence)
    recorder = RunRecorder(
        runner.config.state_dir,
        state.run_id,
        phase_observer=presence.on_phase,
    )
    recorder_started = False
    started_ns = perf_counter_ns()
    store = prepared.campaign_store(runner.config.state_dir)
    try:
        adapter = discovery_adapter_for_kind(store.read_manifest(campaign_id).kind)
        inspect_application_discovery_campaign(
            store,
            adapter=adapter,
            campaign_id=campaign_id,
            observed_at=timestamp,
        )
        recorder.start(state)
        recorder_started = True
        recorder.record(state, RunPhase.OBSERVING)
        discovered_tools = await runner.ports.desktop.discover_tools()
        verify_discovered_tools(discovered_tools)
        recorder.record(state, RunPhase.PLANNING)
        call = ToolCall(
            identity=CallIdentity(
                run_id=run_id,
                turn_id=APPLICATION_DISCOVERY_TURN_ID,
                call_id=APPLICATION_DISCOVERY_CALL_ID,
            ),
            name=DISCOVERY_OBSERVATION_TOOL,
            arguments={"scope": "foreground"},
        )
        try:
            boundary = await runner._execute_requested_call_boundary(
                state,
                call,
                grounding=GroundingState(),
                recorder=recorder,
                continuation=None,
                presence=presence,
            )
        except RunFailure as exc:
            state = exc.state
            phase = RunPhase.UNKNOWN_OUTCOME if exc.code == "UNKNOWN_OUTCOME" else RunPhase.FAILED
            recorder.record(
                state,
                phase,
                failure_code=exc.code,
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise ApplicationDiscoveryRuntimeError(exc.code) from exc
        state = boundary.state
        if not boundary.result.ok:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code="APPLICATION_DISCOVERY_TOOL_FAILED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise ApplicationDiscoveryRuntimeError("APPLICATION_DISCOVERY_TOOL_FAILED")
        try:
            discovery = record_application_snapshot_discoveries(
                store,
                adapter=adapter,
                campaign_id=campaign_id,
                snapshot_text=boundary.result.sanitized_text,
                observed_at=timestamp,
            )
        except ApplicationDiscoveryError as exc:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code=str(exc),
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise ApplicationDiscoveryRuntimeError(str(exc)) from exc
        recorder.record(
            state,
            RunPhase.SUCCESS,
            run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
        )
        return ApplicationDiscoveryObservationOutcome(state, boundary.result, discovery)
    except asyncio.CancelledError:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.CANCELLED,
                failure_code="CANCELLED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise
    except ApplicationDiscoveryRuntimeError:
        raise
    except (ApplicationDiscoveryError, DiscoveryAdapterError) as exc:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code=str(exc),
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise ApplicationDiscoveryRuntimeError(str(exc)) from exc
    except Exception as exc:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.UNKNOWN_OUTCOME,
                failure_code="APPLICATION_DISCOVERY_UNCERTAIN",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise ApplicationDiscoveryRuntimeError("APPLICATION_DISCOVERY_UNCERTAIN") from exc
    finally:
        try:
            presence.release()
        finally:
            try:
                await runner.ports.desktop.close()
            finally:
                prepared.close()


__all__ = [
    "APPLICATION_DISCOVERY_CALL_ID",
    "APPLICATION_DISCOVERY_TASK",
    "APPLICATION_DISCOVERY_TURN_ID",
    "ApplicationDiscoveryObservationOutcome",
    "ApplicationDiscoveryPreparationOutcome",
    "ApplicationDiscoveryRuntimeError",
    "execute_application_discovery_pass",
    "prepare_application_discovery_campaign",
]
