"""One fixed BOSS discovery-page observation through the Runner boundary."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from time import perf_counter_ns

from .boss_campaign_discovery import (
    BossCampaignDiscoveryError,
    BossDiscoveryOutcome,
    create_boss_discovery_campaign,
    inspect_boss_discovery_campaign,
    record_boss_snapshot_discoveries,
)
from .grounding import GroundingState
from .runner import AgentRunner, RunFailure
from .tool_registry import verify_discovered_tools
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall, ToolResult


BOSS_DISCOVERY_TASK = "Observe one fixed BOSS interested-jobs discovery page"
BOSS_DISCOVERY_TOOL = "ui_snapshot"
BOSS_DISCOVERY_TURN_ID = "boss_discovery_page_1"
BOSS_DISCOVERY_CALL_ID = "boss_discovery_page_call_1"


class BossCampaignObservationRuntimeError(RuntimeError):
    """Fixed failure from the BOSS discovery observation boundary."""


@dataclass(frozen=True)
class BossCampaignPreparationOutcome:
    campaign_id: str
    campaign_kind: str
    run_id: str


@dataclass(frozen=True)
class BossCampaignObservationOutcome:
    state: RunState
    result: ToolResult
    discovery: BossDiscoveryOutcome


def _require_now(now: datetime) -> str:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise BossCampaignObservationRuntimeError("BOSS_OBSERVATION_TIME_INVALID")
    return now.isoformat(timespec="seconds")


def prepare_boss_discovery_campaign(
    runner: AgentRunner, *, campaign_id: str, run_id: str, now: datetime
) -> BossCampaignPreparationOutcome:
    """Create only the fixed BOSS discovery campaign without external ports."""

    if not isinstance(runner, AgentRunner) or runner.ports is not None:
        raise BossCampaignObservationRuntimeError("BOSS_PREPARATION_INPUT_INVALID")
    timestamp = _require_now(now)
    prepared = runner.prepare(BOSS_DISCOVERY_TASK, run_id=run_id)
    try:
        manifest = create_boss_discovery_campaign(
            prepared.campaign_store(runner.config.state_dir),
            campaign_id=campaign_id,
            created_at=timestamp,
        )
        return BossCampaignPreparationOutcome(
            campaign_id=manifest.campaign_id,
            campaign_kind=manifest.kind,
            run_id=prepared.state.run_id,
        )
    except BossCampaignDiscoveryError as exc:
        raise BossCampaignObservationRuntimeError(str(exc)) from exc
    finally:
        prepared.close()


async def execute_boss_discovery_page(
    runner: AgentRunner, *, campaign_id: str, run_id: str, now: datetime
) -> BossCampaignObservationOutcome:
    """Observe the foreground once and persist only validated BOSS identities."""

    if not isinstance(runner, AgentRunner) or runner.ports is None:
        raise BossCampaignObservationRuntimeError("BOSS_OBSERVATION_PORTS_REQUIRED")
    timestamp = _require_now(now)
    try:
        prepared = runner.prepare(BOSS_DISCOVERY_TASK, run_id=run_id)
    except Exception:
        await runner.ports.desktop.close()
        raise
    state = prepared.state
    recorder = RunRecorder(runner.config.state_dir, state.run_id)
    recorder_started = False
    started_ns = perf_counter_ns()
    store = prepared.campaign_store(runner.config.state_dir)
    try:
        inspect_boss_discovery_campaign(store, campaign_id=campaign_id, observed_at=timestamp)
        recorder.start(state)
        recorder_started = True
        recorder.record(state, RunPhase.OBSERVING)
        discovered_tools = await runner.ports.desktop.discover_tools()
        verify_discovered_tools(discovered_tools)
        recorder.record(state, RunPhase.PLANNING)
        call = ToolCall(
            identity=CallIdentity(
                run_id=run_id,
                turn_id=BOSS_DISCOVERY_TURN_ID,
                call_id=BOSS_DISCOVERY_CALL_ID,
            ),
            name=BOSS_DISCOVERY_TOOL,
            arguments={"scope": "foreground"},
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
            phase = RunPhase.UNKNOWN_OUTCOME if exc.code == "UNKNOWN_OUTCOME" else RunPhase.FAILED
            recorder.record(
                state,
                phase,
                failure_code=exc.code,
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise BossCampaignObservationRuntimeError(exc.code) from exc
        state = boundary.state
        if not boundary.result.ok:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code="BOSS_OBSERVATION_TOOL_FAILED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise BossCampaignObservationRuntimeError("BOSS_OBSERVATION_TOOL_FAILED")
        try:
            discovery = record_boss_snapshot_discoveries(
                store,
                campaign_id=campaign_id,
                snapshot_text=boundary.result.sanitized_text,
                observed_at=timestamp,
            )
        except BossCampaignDiscoveryError as exc:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code=str(exc),
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
            raise BossCampaignObservationRuntimeError(str(exc)) from exc
        recorder.record(
            state,
            RunPhase.SUCCESS,
            run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
        )
        return BossCampaignObservationOutcome(state, boundary.result, discovery)
    except asyncio.CancelledError:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.CANCELLED,
                failure_code="CANCELLED",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise
    except BossCampaignObservationRuntimeError:
        raise
    except BossCampaignDiscoveryError as exc:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code=str(exc),
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise BossCampaignObservationRuntimeError(str(exc)) from exc
    except Exception as exc:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.UNKNOWN_OUTCOME,
                failure_code="BOSS_OBSERVATION_UNCERTAIN",
                run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
            )
        raise BossCampaignObservationRuntimeError("BOSS_OBSERVATION_UNCERTAIN") from exc
    finally:
        try:
            await runner.ports.desktop.close()
        finally:
            prepared.close()


__all__ = [
    "BOSS_DISCOVERY_CALL_ID",
    "BOSS_DISCOVERY_TASK",
    "BOSS_DISCOVERY_TOOL",
    "BOSS_DISCOVERY_TURN_ID",
    "BossCampaignObservationOutcome",
    "BossCampaignObservationRuntimeError",
    "BossCampaignPreparationOutcome",
    "execute_boss_discovery_page",
    "prepare_boss_discovery_campaign",
]
