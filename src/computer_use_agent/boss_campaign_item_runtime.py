"""Process one exact claimed BOSS identity through a read-only handoff.

The first slice deliberately extracts only a bounded identity-presence proof
from one foreground interested-jobs ``ui_snapshot``.  It does not navigate,
persist page content, call a provider, or claim a caller-selected item.  The
existing batch plan selects the item, Runner remains the sole MCP authority,
and the one-tool batch limit forces a durable handoff after one commit.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import perf_counter_ns
from typing import Mapping

from .batch_coordinator import BatchCoordinator, BatchSession
from .batching import BatchPlan, BatchUsage
from .boss_campaign_batch_runtime import BOSS_BATCH_POLICY
from .boss_campaign_discovery import (
    BOSS_CAMPAIGN_KIND,
    boss_discovery_policy_digest,
    boss_discovery_schema_digest,
    boss_snapshot_source_digest,
    parse_boss_job_identities,
)
from .campaign import BatchStatus, CampaignStatus, ItemStatus
from .grounding import GroundingState
from .presence_lifecycle import FailSilentLifecycle
from .runner import AgentRunner, PreparedRun, RunFailure
from .tool_registry import verify_discovered_tools
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall, ToolResult


BOSS_ITEM_TASK = "Verify one exact claimed BOSS identity on the interested-jobs page"
BOSS_ITEM_TOOL = "ui_snapshot"
BOSS_ITEM_TURN_ID = "boss_claimed_item_1"
BOSS_ITEM_CALL_ID = "boss_claimed_item_call_1"


class BossCampaignItemRuntimeError(RuntimeError):
    """Fixed failure from the bounded BOSS claimed-item boundary."""


@dataclass(frozen=True)
class BossCampaignItemHandoffOutcome:
    """One committed identity proof plus measured finished-batch evidence."""

    state: RunState
    result: ToolResult
    claimed_item_ordinal: int
    content_digest: str
    source_digest: str
    usage: BatchUsage
    stop_code: str
    handoff: Mapping[str, object]


def boss_identity_presence_digest(*, item_key: str, source_digest: str) -> str:
    if (
        not isinstance(item_key, str)
        or not item_key.startswith("boss:job:")
        or not isinstance(source_digest, str)
        or len(source_digest) != 64
        or any(character not in "0123456789abcdef" for character in source_digest)
    ):
        raise BossCampaignItemRuntimeError("BOSS_ITEM_RESULT_INVALID")
    encoded = json.dumps(
        {
            "item_key": item_key,
            "source_digest": source_digest,
            "verification": "present_on_interested_jobs_page",
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def _claimed_boss_session(
    coordinator: BatchCoordinator,
    *,
    campaign_id: str,
    run_id: str,
) -> tuple[BatchSession, int, str]:
    store = coordinator.store
    manifest = store.read_manifest(campaign_id)
    projection = store.read_ledger(campaign_id)
    batches = store.read_batches(campaign_id)
    heartbeat = store.read_heartbeat(campaign_id)
    active = batches.active
    claimed = [
        item
        for item in projection.items.values()
        if item.status is ItemStatus.CLAIMED and item.run_id == run_id
    ]
    if len(claimed) != 1:
        raise BossCampaignItemRuntimeError("BOSS_ITEM_CLAIMED_STATE_INVALID")
    selected = claimed[0]
    tail = sorted(
        (
            item
            for item in projection.items.values()
            if item.ordinal >= selected.ordinal
            and (
                item is selected
                or item.status in {ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
            )
        ),
        key=lambda item: (item.ordinal, item.item_key),
    )[: BOSS_BATCH_POLICY.max_items]
    last = batches.transitions[-1] if batches.transitions else None
    if (
        manifest.kind != BOSS_CAMPAIGN_KIND
        or manifest.status is not CampaignStatus.RUNNING
        or manifest.policy_digest != boss_discovery_policy_digest()
        or manifest.schema_digest != boss_discovery_schema_digest()
        or active is None
        or last is None
        or last.status is not BatchStatus.STARTED
        or (active.batch_id, active.run_id) != (last.batch_id, last.run_id)
        or active.run_id != run_id
        or heartbeat is None
        or heartbeat.run_id != run_id
        or not tail
        or tail[0] is not selected
        or any(
            item.status not in {ItemStatus.CLAIMED, ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
            for item in tail
        )
    ):
        raise BossCampaignItemRuntimeError("BOSS_ITEM_CLAIMED_STATE_INVALID")
    return (
        BatchSession(
            campaign_id=campaign_id,
            batch_id=active.batch_id,
            run_id=run_id,
            policy=BOSS_BATCH_POLICY,
            plan=BatchPlan(
                item_keys=tuple(item.item_key for item in tail),
                stop_reason=None,
            ),
        ),
        selected.ordinal,
        selected.item_key,
    )


async def execute_claimed_boss_identity_through_handoff(
    runner: AgentRunner,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> BossCampaignItemHandoffOutcome:
    """Verify, commit, finish, and hand off one exact durable BOSS claim."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is None
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        if isinstance(runner, AgentRunner) and runner.ports is not None:
            await runner.ports.desktop.close()
        raise BossCampaignItemRuntimeError("BOSS_ITEM_INPUT_INVALID")
    try:
        recorder = RunRecorder(runner.config.state_dir, run_id)
    except ValueError as exc:
        await runner.ports.desktop.close()
        raise BossCampaignItemRuntimeError("BOSS_ITEM_INPUT_INVALID") from exc
    if recorder.checkpoint_path.exists() or recorder.trace_path.exists():
        await runner.ports.desktop.close()
        raise BossCampaignItemRuntimeError("BOSS_ITEM_RUN_EXISTS")
    try:
        prepared = runner.prepare(BOSS_ITEM_TASK, run_id=run_id)
    except Exception:
        await runner.ports.desktop.close()
        raise
    return await _execute_prepared_claimed_boss_identity(
        runner,
        prepared,
        recorder,
        campaign_id=campaign_id,
        now=now,
    )


async def _execute_prepared_claimed_boss_identity(
    runner: AgentRunner,
    prepared: PreparedRun,
    recorder: RunRecorder,
    *,
    campaign_id: str,
    now: datetime,
) -> BossCampaignItemHandoffOutcome:
    if runner.ports is None:
        prepared.close()
        raise BossCampaignItemRuntimeError("BOSS_ITEM_PORTS_REQUIRED")
    state = prepared.state
    presence = FailSilentLifecycle(runner.ports.presence)
    recorder.phase_observer = presence.on_phase
    recorder_started = False
    started_ns = perf_counter_ns()
    try:
        coordinator = BatchCoordinator(
            prepared.campaign_store(runner.config.state_dir)
        )
        session, claimed_ordinal, claimed_key = _claimed_boss_session(
            coordinator,
            campaign_id=campaign_id,
            run_id=state.run_id,
        )
        preflight = coordinator.inspect_next_claimed_item(
            session,
            usage=BatchUsage(),
            now=now,
        )
        if not preflight.ready or preflight.item_key != claimed_key:
            raise BossCampaignItemRuntimeError(
                f"BOSS_ITEM_OBSERVATION_BLOCKED_{preflight.state.value}"
            )

        recorder.start(state)
        recorder_started = True
        recorder.record(state, RunPhase.OBSERVING)
        discovered = await runner.ports.desktop.discover_tools()
        verify_discovered_tools(discovered)
        recorder.record(state, RunPhase.PLANNING)
        call = ToolCall(
            identity=CallIdentity(
                run_id=state.run_id,
                turn_id=BOSS_ITEM_TURN_ID,
                call_id=BOSS_ITEM_CALL_ID,
            ),
            name=BOSS_ITEM_TOOL,
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
            recorder.record(
                state,
                RunPhase.UNKNOWN_OUTCOME
                if exc.code == "UNKNOWN_OUTCOME"
                else RunPhase.FAILED,
                failure_code=exc.code,
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
            raise BossCampaignItemRuntimeError(exc.code) from exc
        state = boundary.state
        if not boundary.result.ok:
            raise BossCampaignItemRuntimeError("BOSS_ITEM_OBSERVATION_TOOL_FAILED")

        snapshot_text = boundary.result.sanitized_text
        identities = parse_boss_job_identities(snapshot_text)
        matched = tuple(
            identity for identity in identities if identity.item_key == claimed_key
        )
        if len(matched) != 1:
            raise BossCampaignItemRuntimeError("BOSS_ITEM_IDENTITY_NOT_PRESENT")
        source_digest = boss_snapshot_source_digest(snapshot_text)
        content_digest = boss_identity_presence_digest(
            item_key=claimed_key,
            source_digest=source_digest,
        )
        observed = coordinator.record_next_claimed_item_observed(
            session,
            usage=BatchUsage(),
            now=now,
            application_state_verified=True,
            item_identity_verified=True,
        )
        extracted = coordinator.record_next_observed_item_extracted(
            session,
            usage=BatchUsage(),
            now=now,
            read_only_extraction_completed=True,
        )
        committed = coordinator.record_next_extracted_item_committed(
            session,
            usage=BatchUsage(),
            now=now,
            bounded_result_verified=True,
            content_digest=content_digest,
        )
        if (
            observed.status is not ItemStatus.OBSERVED
            or extracted.status is not ItemStatus.EXTRACTED
            or committed.status is not ItemStatus.COMMITTED
            or committed.content_digest != content_digest
        ):
            raise BossCampaignItemRuntimeError("BOSS_ITEM_COMMIT_EVIDENCE_INVALID")

        usage = BatchUsage(
            items_completed=1,
            elapsed_seconds=max(
                0, (perf_counter_ns() - started_ns) // 1_000_000_000
            ),
            provider_turns=state.budgets.model_turns_used,
            tool_calls=state.budgets.tool_calls_used,
            input_tokens=state.budgets.input_tokens_used,
        )
        stop_code = coordinator.finish_continued_batch(
            session,
            usage=usage,
            now=now,
        )
        handoff = coordinator.write_finished_handoff(
            session,
            usage=usage,
            now=now,
        )
        completed_count = coordinator.store.read_ledger(
            campaign_id
        ).completed_count
        if (
            stop_code != "TOOL_CALL_LIMIT"
            or handoff.get("campaign_id") != campaign_id
            or handoff.get("last_run_id") != state.run_id
            or handoff.get("completed_count") != completed_count
            or handoff.get("next_item_ordinal") != claimed_ordinal + 1
        ):
            raise BossCampaignItemRuntimeError("BOSS_ITEM_HANDOFF_EVIDENCE_INVALID")
        recorder.record(
            state,
            RunPhase.SUCCESS,
            run_duration_ms=max(
                0, (perf_counter_ns() - started_ns) // 1_000_000
            ),
        )
        return BossCampaignItemHandoffOutcome(
            state=state,
            result=boundary.result,
            claimed_item_ordinal=claimed_ordinal,
            content_digest=content_digest,
            source_digest=source_digest,
            usage=usage,
            stop_code=stop_code,
            handoff=handoff,
        )
    except asyncio.CancelledError:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.CANCELLED,
                failure_code="CANCELLED",
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
        raise
    except BossCampaignItemRuntimeError as exc:
        if recorder_started and recorder.phase not in {
            RunPhase.FAILED,
            RunPhase.SUCCESS,
            RunPhase.UNKNOWN_OUTCOME,
        }:
            recorder.record(
                state,
                RunPhase.FAILED,
                failure_code=str(exc),
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
        raise
    except Exception as exc:
        if recorder_started:
            recorder.record(
                state,
                RunPhase.UNKNOWN_OUTCOME,
                failure_code="BOSS_ITEM_UNCERTAIN",
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
        raise BossCampaignItemRuntimeError("BOSS_ITEM_UNCERTAIN") from exc
    finally:
        try:
            presence.release()
        finally:
            try:
                await runner.ports.desktop.close()
            finally:
                prepared.close()


__all__ = [
    "BOSS_ITEM_CALL_ID",
    "BOSS_ITEM_TASK",
    "BOSS_ITEM_TOOL",
    "BOSS_ITEM_TURN_ID",
    "BossCampaignItemHandoffOutcome",
    "BossCampaignItemRuntimeError",
    "boss_identity_presence_digest",
    "execute_claimed_boss_identity_through_handoff",
]
