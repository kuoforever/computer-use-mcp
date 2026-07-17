"""One fixed synthetic campaign observation through the Agent authority boundary.

This internal slice binds an already-claimed first campaign item to one
``list_windows`` observation.  Explicit extensions may reduce that correlated
text to a bounded non-sensitive window count, persist ``EXTRACTED``, verify the
canonical count, and persist its digest at ``COMMITTED``.  It has no provider,
CLI, free-form selector, side-effect, or campaign-specific MCP path.  A fixed
extension can finish the batch, write handoff, and transfer a fresh Runner run
to an exhausted resume decision using only durable campaign records.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from time import perf_counter_ns
from typing import Mapping

from .batch_coordinator import (
    BatchCoordinator,
    BatchCoordinatorError,
    BatchSession,
    BatchTransferredResumePreflight,
    BatchTransferredResumeState,
)
from .batching import BatchPlan, BatchPolicy, BatchUsage
from .campaign import (
    BatchStatus,
    CampaignHeartbeat,
    CampaignStatus,
    ItemStatus,
    ItemTransition,
)
from .grounding import GroundingState
from .runner import AgentRunner, PreparedRun, RunFailure
from .tool_registry import verify_discovered_tools
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall, ToolResult


SYNTHETIC_CAMPAIGN_KIND = "synthetic_read_only_observation"
SYNTHETIC_ITEM_KEY = "synthetic:list_windows"
SYNTHETIC_OBSERVATION_TOOL = "list_windows"
SYNTHETIC_OBSERVATION_TASK = "Observe the fixed synthetic campaign item"
SYNTHETIC_TURN_ID = "campaign_observation_1"
SYNTHETIC_CALL_ID = "campaign_observation_call_1"
MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS = 64 * 1024
SYNTHETIC_RESUME_TASK = "Resume the fixed synthetic campaign from durable state"
SYNTHETIC_RESUME_HEARTBEAT_SECONDS = 5 * 60
SYNTHETIC_BATCH_POLICY = BatchPolicy(max_items=1)


class CampaignObservationRuntimeError(RuntimeError):
    """Fixed failure from the bounded synthetic observation runtime."""


@dataclass(frozen=True)
class CampaignObservationOutcome:
    """Correlated Runner evidence and the persisted OBSERVED boundary."""

    state: RunState
    result: ToolResult
    observed: ItemTransition


@dataclass(frozen=True)
class CampaignExtractionOutcome:
    """Bounded non-sensitive extraction plus both persisted item boundaries."""

    state: RunState
    result: ToolResult
    observed: ItemTransition
    extracted: ItemTransition
    window_count: int


@dataclass(frozen=True)
class CampaignCommitOutcome:
    """Verified canonical count plus every persisted synthetic item boundary."""

    state: RunState
    result: ToolResult
    observed: ItemTransition
    extracted: ItemTransition
    committed: ItemTransition
    window_count: int
    content_digest: str


@dataclass(frozen=True)
class CampaignHandoffOutcome:
    """Committed item plus measured finished-batch and handoff evidence."""

    state: RunState
    result: ToolResult
    observed: ItemTransition
    extracted: ItemTransition
    committed: ItemTransition
    window_count: int
    content_digest: str
    usage: BatchUsage
    stop_code: str
    handoff: Mapping[str, object]


@dataclass(frozen=True)
class CampaignRestartResumeOutcome:
    """Fresh-run ownership and the durable exhausted-resume decision."""

    state: RunState
    heartbeat: CampaignHeartbeat
    resume: BatchTransferredResumePreflight
    handoff: Mapping[str, object]


def _finished_synthetic_session(
    coordinator: BatchCoordinator,
    *,
    campaign_id: str,
) -> tuple[BatchSession, BatchUsage, Mapping[str, object]]:
    """Rebuild the exact finished synthetic session from durable records."""

    store = coordinator.store
    manifest = store.read_manifest(campaign_id)
    projection = store.read_ledger(campaign_id)
    batches = store.read_batches(campaign_id)
    handoff = store.read_handoff(campaign_id)
    heartbeat = store.read_heartbeat(campaign_id)
    transitions = batches.transitions
    item = projection.items.get(SYNTHETIC_ITEM_KEY)
    if (
        manifest.kind != SYNTHETIC_CAMPAIGN_KIND
        or manifest.status is not CampaignStatus.RUNNING
        or set(projection.items) != {SYNTHETIC_ITEM_KEY}
        or item is None
        or item.ordinal != 1
        or item.status is not ItemStatus.COMMITTED
        or item.run_id is None
        or batches.active is not None
        or len(transitions) != 2
        or transitions[0].status is not BatchStatus.STARTED
        or transitions[1].status is not BatchStatus.FINISHED
        or (transitions[0].batch_id, transitions[0].run_id)
        != (transitions[1].batch_id, transitions[1].run_id)
        or transitions[1].run_id != item.run_id
        or transitions[1].stop_code != "ITEM_LIMIT"
        or transitions[1].items_completed != 1
        or handoff.get("last_run_id") != item.run_id
        or handoff.get("next_item_ordinal") != 2
        or handoff.get("completed_count") != 1
        or handoff.get("next_action") != "resume_batch"
        or handoff.get("required_observation")
        != "verify_current_page_and_account_state"
        or heartbeat is None
        or heartbeat.run_id != item.run_id
    ):
        raise CampaignObservationRuntimeError("CAMPAIGN_RESTART_STATE_INVALID")
    finished = transitions[1]
    session = BatchSession(
        campaign_id=campaign_id,
        batch_id=finished.batch_id,
        run_id=finished.run_id,
        policy=SYNTHETIC_BATCH_POLICY,
        plan=BatchPlan(item_keys=(SYNTHETIC_ITEM_KEY,), stop_reason=None),
    )
    usage = BatchUsage(
        items_completed=finished.items_completed,
        elapsed_seconds=finished.elapsed_seconds,
        provider_turns=finished.provider_turns,
        tool_calls=finished.tool_calls,
        input_tokens=finished.input_tokens,
        output_tokens=finished.output_tokens,
        screenshots=finished.screenshots,
        ocr_regions=finished.ocr_regions,
        consecutive_failures=finished.consecutive_failures,
    )
    return session, usage, handoff


def _claimed_synthetic_session(
    coordinator: BatchCoordinator,
    *,
    campaign_id: str,
    run_id: str,
) -> BatchSession:
    """Rebuild the one exact active claimed session from durable records."""

    store = coordinator.store
    manifest = store.read_manifest(campaign_id)
    projection = store.read_ledger(campaign_id)
    batches = store.read_batches(campaign_id)
    transitions = batches.transitions
    active = batches.active
    item = projection.items.get(SYNTHETIC_ITEM_KEY)
    if (
        manifest.kind != SYNTHETIC_CAMPAIGN_KIND
        or manifest.status is not CampaignStatus.RUNNING
        or set(projection.items) != {SYNTHETIC_ITEM_KEY}
        or item is None
        or item.ordinal != 1
        or item.status is not ItemStatus.CLAIMED
        or item.run_id != run_id
        or active is None
        or len(transitions) != 1
        or transitions[0].status is not BatchStatus.STARTED
        or (active.batch_id, active.run_id)
        != (transitions[0].batch_id, transitions[0].run_id)
        or active.run_id != run_id
    ):
        raise CampaignObservationRuntimeError("CAMPAIGN_CLAIMED_STATE_INVALID")
    return BatchSession(
        campaign_id=campaign_id,
        batch_id=active.batch_id,
        run_id=run_id,
        policy=SYNTHETIC_BATCH_POLICY,
        plan=BatchPlan(item_keys=(SYNTHETIC_ITEM_KEY,), stop_reason=None),
    )


def synthetic_window_count_digest(window_count: int) -> str:
    """Return the canonical digest for one non-sensitive synthetic result."""

    if (
        isinstance(window_count, bool)
        or not isinstance(window_count, int)
        or window_count < 0
    ):
        raise CampaignObservationRuntimeError("CAMPAIGN_COMMIT_RESULT_INVALID")
    encoded = json.dumps(
        {"window_count": window_count},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


async def _execute_claimed_synthetic_observation(
    runner: AgentRunner,
    prepared_run: PreparedRun,
    session: BatchSession,
    *,
    now: datetime,
    extract_window_count: bool,
    commit_window_count: bool,
    finish_handoff: bool,
) -> (
    CampaignObservationOutcome
    | CampaignExtractionOutcome
    | CampaignCommitOutcome
    | CampaignHandoffOutcome
):
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
        if (commit_window_count and not extract_window_count) or (
            finish_handoff and not commit_window_count
        ):
            raise CampaignObservationRuntimeError("CAMPAIGN_COMMIT_SEQUENCE_INVALID")
        if extract_window_count:
            if len(boundary.result.sanitized_text) > MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS:
                recorder.record(
                    state,
                    RunPhase.FAILED,
                    failure_code="CAMPAIGN_EXTRACTION_RESULT_TOO_LARGE",
                    run_duration_ms=max(
                        0, (perf_counter_ns() - started_ns) // 1_000_000
                    ),
                )
                raise CampaignObservationRuntimeError(
                    "CAMPAIGN_EXTRACTION_RESULT_TOO_LARGE"
                )
            window_count = sum(
                1
                for line in boundary.result.sanitized_text.splitlines()
                if line.strip()
            )
            try:
                extracted = coordinator.record_first_observed_item_extracted(
                    session,
                    now=now,
                    read_only_extraction_completed=True,
                )
            except BatchCoordinatorError as exc:
                recorder.record(
                    state,
                    RunPhase.FAILED,
                    failure_code="CAMPAIGN_EXTRACTION_PERSIST_FAILED",
                    run_duration_ms=max(
                        0, (perf_counter_ns() - started_ns) // 1_000_000
                    ),
                )
                raise CampaignObservationRuntimeError(
                    "CAMPAIGN_EXTRACTION_PERSIST_FAILED"
                ) from exc
            if extracted.status is not ItemStatus.EXTRACTED:
                raise CampaignObservationRuntimeError(
                    "CAMPAIGN_EXTRACTION_EVIDENCE_INVALID"
                )
            if commit_window_count:
                verified_window_count = sum(
                    1
                    for line in boundary.result.sanitized_text.splitlines()
                    if line.strip()
                )
                if verified_window_count != window_count:
                    raise CampaignObservationRuntimeError(
                        "CAMPAIGN_COMMIT_VERIFICATION_FAILED"
                    )
                content_digest = synthetic_window_count_digest(window_count)
                try:
                    committed = coordinator.record_first_extracted_item_committed(
                        session,
                        now=now,
                        bounded_result_verified=True,
                        content_digest=content_digest,
                    )
                except BatchCoordinatorError as exc:
                    recorder.record(
                        state,
                        RunPhase.FAILED,
                        failure_code="CAMPAIGN_COMMIT_PERSIST_FAILED",
                        run_duration_ms=max(
                            0, (perf_counter_ns() - started_ns) // 1_000_000
                        ),
                    )
                    raise CampaignObservationRuntimeError(
                        "CAMPAIGN_COMMIT_PERSIST_FAILED"
                    ) from exc
                if (
                    committed.status is not ItemStatus.COMMITTED
                    or committed.content_digest != content_digest
                ):
                    raise CampaignObservationRuntimeError(
                        "CAMPAIGN_COMMIT_EVIDENCE_INVALID"
                    )
                if finish_handoff:
                    usage = BatchUsage(
                        items_completed=1,
                        elapsed_seconds=max(
                            0, (perf_counter_ns() - started_ns) // 1_000_000_000
                        ),
                        provider_turns=state.budgets.model_turns_used,
                        tool_calls=state.budgets.tool_calls_used,
                        input_tokens=state.budgets.input_tokens_used,
                    )
                    try:
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
                    except BatchCoordinatorError as exc:
                        recorder.record(
                            state,
                            RunPhase.FAILED,
                            failure_code="CAMPAIGN_HANDOFF_PERSIST_FAILED",
                            run_duration_ms=max(
                                0, (perf_counter_ns() - started_ns) // 1_000_000
                            ),
                        )
                        raise CampaignObservationRuntimeError(
                            "CAMPAIGN_HANDOFF_PERSIST_FAILED"
                        ) from exc
                    if (
                        handoff.get("campaign_id") != session.campaign_id
                        or handoff.get("last_run_id") != session.run_id
                        or handoff.get("completed_count") != 1
                        or handoff.get("next_action") != "resume_batch"
                        or handoff.get("required_observation")
                        != "verify_current_page_and_account_state"
                    ):
                        raise CampaignObservationRuntimeError(
                            "CAMPAIGN_HANDOFF_EVIDENCE_INVALID"
                        )
        recorder.record(
            state,
            RunPhase.SUCCESS,
            run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
        )
        if finish_handoff:
            return CampaignHandoffOutcome(
                state=state,
                result=boundary.result,
                observed=observed,
                extracted=extracted,
                committed=committed,
                window_count=window_count,
                content_digest=content_digest,
                usage=usage,
                stop_code=stop_code,
                handoff=handoff,
            )
        if commit_window_count:
            return CampaignCommitOutcome(
                state=state,
                result=boundary.result,
                observed=observed,
                extracted=extracted,
                committed=committed,
                window_count=window_count,
                content_digest=content_digest,
            )
        if extract_window_count:
            return CampaignExtractionOutcome(
                state=state,
                result=boundary.result,
                observed=observed,
                extracted=extracted,
                window_count=window_count,
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


async def execute_claimed_synthetic_observation(
    runner: AgentRunner,
    prepared_run: PreparedRun,
    session: BatchSession,
    *,
    now: datetime,
) -> CampaignObservationOutcome:
    """Execute only the original correlated ``OBSERVED`` slice."""

    outcome = await _execute_claimed_synthetic_observation(
        runner,
        prepared_run,
        session,
        now=now,
        extract_window_count=False,
        commit_window_count=False,
        finish_handoff=False,
    )
    if not isinstance(outcome, CampaignObservationOutcome):
        raise CampaignObservationRuntimeError("CAMPAIGN_OBSERVATION_EVIDENCE_INVALID")
    return outcome


async def execute_claimed_synthetic_observation_and_extraction(
    runner: AgentRunner,
    prepared_run: PreparedRun,
    session: BatchSession,
    *,
    now: datetime,
) -> CampaignExtractionOutcome:
    """Observe once, extract only a bounded window count, and persist EXTRACTED."""

    outcome = await _execute_claimed_synthetic_observation(
        runner,
        prepared_run,
        session,
        now=now,
        extract_window_count=True,
        commit_window_count=False,
        finish_handoff=False,
    )
    if not isinstance(outcome, CampaignExtractionOutcome):
        raise CampaignObservationRuntimeError("CAMPAIGN_EXTRACTION_EVIDENCE_INVALID")
    return outcome


async def execute_claimed_synthetic_item_through_commit(
    runner: AgentRunner,
    prepared_run: PreparedRun,
    session: BatchSession,
    *,
    now: datetime,
) -> CampaignCommitOutcome:
    """Observe, extract, verify, and commit one fixed synthetic count digest."""

    outcome = await _execute_claimed_synthetic_observation(
        runner,
        prepared_run,
        session,
        now=now,
        extract_window_count=True,
        commit_window_count=True,
        finish_handoff=False,
    )
    if not isinstance(outcome, CampaignCommitOutcome):
        raise CampaignObservationRuntimeError("CAMPAIGN_COMMIT_EVIDENCE_INVALID")
    return outcome


async def execute_claimed_synthetic_item_through_handoff(
    runner: AgentRunner,
    prepared_run: PreparedRun,
    session: BatchSession,
    *,
    now: datetime,
) -> CampaignHandoffOutcome:
    """Commit one fixed count, finish its batch, and write current handoff."""

    outcome = await _execute_claimed_synthetic_observation(
        runner,
        prepared_run,
        session,
        now=now,
        extract_window_count=True,
        commit_window_count=True,
        finish_handoff=True,
    )
    if not isinstance(outcome, CampaignHandoffOutcome):
        raise CampaignObservationRuntimeError("CAMPAIGN_HANDOFF_EVIDENCE_INVALID")
    return outcome


async def execute_persisted_claimed_synthetic_item_through_handoff(
    runner: AgentRunner,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> CampaignHandoffOutcome:
    """Execute only the exact durable active synthetic claim through handoff."""

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
    ):
        if isinstance(runner, AgentRunner) and runner.ports is not None:
            await runner.ports.desktop.close()
        raise CampaignObservationRuntimeError("CAMPAIGN_CLAIMED_INPUT_INVALID")
    try:
        RunRecorder(runner.config.state_dir, run_id)
    except ValueError as exc:
        await runner.ports.desktop.close()
        raise CampaignObservationRuntimeError(
            "CAMPAIGN_CLAIMED_INPUT_INVALID"
        ) from exc

    try:
        prepared_run = runner.prepare(SYNTHETIC_OBSERVATION_TASK, run_id=run_id)
    except Exception:
        await runner.ports.desktop.close()
        raise
    try:
        coordinator = BatchCoordinator(
            prepared_run.campaign_store(runner.config.state_dir)
        )
        session = _claimed_synthetic_session(
            coordinator,
            campaign_id=campaign_id,
            run_id=run_id,
        )
    except Exception:
        try:
            await runner.ports.desktop.close()
        finally:
            prepared_run.close()
        raise
    return await execute_claimed_synthetic_item_through_handoff(
        runner,
        prepared_run,
        session,
        now=now,
    )


def resume_finished_synthetic_campaign_after_restart(
    runner: AgentRunner,
    *,
    campaign_id: str,
    replacement_run_id: str,
    now: datetime,
) -> CampaignRestartResumeOutcome:
    """Resume one finished synthetic campaign in a fresh Runner run.

    The caller supplies no task text or prior ``BatchSession``.  The fixed
    session is reconstructed only from the campaign's durable records.  This
    boundary transfers heartbeat ownership and proves that the one-item
    campaign has no eligible resume work; it does not complete the campaign or
    retire the heartbeat.
    """

    if (
        not isinstance(runner, AgentRunner)
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(replacement_run_id, str)
        or not replacement_run_id
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise CampaignObservationRuntimeError("CAMPAIGN_RESTART_INPUT_INVALID")

    try:
        recorder = RunRecorder(runner.config.state_dir, replacement_run_id)
    except ValueError as exc:
        raise CampaignObservationRuntimeError(
            "CAMPAIGN_RESTART_INPUT_INVALID"
        ) from exc
    prepared_run = runner.prepare(
        SYNTHETIC_RESUME_TASK,
        run_id=replacement_run_id,
    )
    state = prepared_run.state
    recorder_started = False
    started_ns = perf_counter_ns()
    try:
        recorder.start(state)
        recorder_started = True
        recorder.record(state, RunPhase.OBSERVING)
        store = prepared_run.campaign_store(runner.config.state_dir)
        coordinator = BatchCoordinator(store)
        session, usage, handoff = _finished_synthetic_session(
            coordinator,
            campaign_id=campaign_id,
        )
        replacement = CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=replacement_run_id,
            started_at=now.isoformat(timespec="seconds"),
            heartbeat_at=now.isoformat(timespec="seconds"),
            fresh_until=(
                now + timedelta(seconds=SYNTHETIC_RESUME_HEARTBEAT_SECONDS)
            ).isoformat(timespec="seconds"),
        )
        try:
            heartbeat = coordinator.replace_finished_run_heartbeat_owner(
                session,
                usage=usage,
                now=now,
                replacement=replacement,
            )
            recorder.record(state, RunPhase.PLANNING)
            resume = coordinator.inspect_transferred_run_resume(
                session,
                replacement_run_id=replacement_run_id,
                now=now,
                policy=SYNTHETIC_BATCH_POLICY,
            )
        except BatchCoordinatorError as exc:
            raise CampaignObservationRuntimeError(
                "CAMPAIGN_RESTART_RESUME_BLOCKED"
            ) from exc
        if (
            heartbeat != replacement
            or resume.state is not BatchTransferredResumeState.NO_ELIGIBLE_ITEMS
            or resume.item_keys
            or resume.finished_run_id != session.run_id
            or resume.replacement_run_id != replacement_run_id
            or resume.next_item_ordinal != 2
        ):
            raise CampaignObservationRuntimeError(
                "CAMPAIGN_RESTART_RESUME_EVIDENCE_INVALID"
            )
        recorder.record(
            state,
            RunPhase.SUCCESS,
            run_duration_ms=max(0, (perf_counter_ns() - started_ns) // 1_000_000),
        )
        return CampaignRestartResumeOutcome(
            state=state,
            heartbeat=heartbeat,
            resume=resume,
            handoff=handoff,
        )
    except CampaignObservationRuntimeError as exc:
        if recorder_started and recorder.phase not in {
            RunPhase.FAILED,
            RunPhase.SUCCESS,
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
                RunPhase.FAILED,
                failure_code="CAMPAIGN_RESTART_RESUME_FAILED",
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
        raise CampaignObservationRuntimeError(
            "CAMPAIGN_RESTART_RESUME_FAILED"
        ) from exc
    finally:
        prepared_run.close()


__all__ = [
    "CampaignObservationOutcome",
    "CampaignExtractionOutcome",
    "CampaignCommitOutcome",
    "CampaignHandoffOutcome",
    "CampaignRestartResumeOutcome",
    "CampaignObservationRuntimeError",
    "MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS",
    "SYNTHETIC_CALL_ID",
    "SYNTHETIC_BATCH_POLICY",
    "SYNTHETIC_CAMPAIGN_KIND",
    "SYNTHETIC_ITEM_KEY",
    "SYNTHETIC_OBSERVATION_TOOL",
    "SYNTHETIC_OBSERVATION_TASK",
    "SYNTHETIC_RESUME_HEARTBEAT_SECONDS",
    "SYNTHETIC_RESUME_TASK",
    "SYNTHETIC_TURN_ID",
    "execute_claimed_synthetic_observation",
    "execute_claimed_synthetic_observation_and_extraction",
    "execute_claimed_synthetic_item_through_commit",
    "execute_claimed_synthetic_item_through_handoff",
    "execute_persisted_claimed_synthetic_item_through_handoff",
    "resume_finished_synthetic_campaign_after_restart",
    "synthetic_window_count_digest",
]
