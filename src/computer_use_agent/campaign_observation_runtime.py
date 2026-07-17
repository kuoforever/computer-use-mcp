"""One fixed synthetic campaign observation through the Agent authority boundary.

This internal slice binds an already-claimed first campaign item to one
``list_windows`` observation.  Explicit extensions may reduce that correlated
text to a bounded non-sensitive window count, persist ``EXTRACTED``, verify the
canonical count, and persist its digest at ``COMMITTED``.  It has no provider,
CLI, free-form selector, batch closing, resume, side-effect, or campaign-specific
MCP path.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import perf_counter_ns
from typing import Mapping

from .batch_coordinator import BatchCoordinator, BatchCoordinatorError, BatchSession
from .batching import BatchUsage
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
MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS = 64 * 1024


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


__all__ = [
    "CampaignObservationOutcome",
    "CampaignExtractionOutcome",
    "CampaignCommitOutcome",
    "CampaignHandoffOutcome",
    "CampaignObservationRuntimeError",
    "MAX_SYNTHETIC_EXTRACTION_TEXT_CHARS",
    "SYNTHETIC_CALL_ID",
    "SYNTHETIC_CAMPAIGN_KIND",
    "SYNTHETIC_ITEM_KEY",
    "SYNTHETIC_OBSERVATION_TOOL",
    "SYNTHETIC_TURN_ID",
    "execute_claimed_synthetic_observation",
    "execute_claimed_synthetic_observation_and_extraction",
    "execute_claimed_synthetic_item_through_commit",
    "execute_claimed_synthetic_item_through_handoff",
    "synthetic_window_count_digest",
]
