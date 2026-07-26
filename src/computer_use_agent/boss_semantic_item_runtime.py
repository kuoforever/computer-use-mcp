"""Execute one claimed BOSS item through a bounded semantic observation loop.

The runtime preserves the retained identity-only worker and adds a separate
one-item policy.  It dispatches every observation through the sole Runner call
boundary, exposes only the exact next observation tool to the provider, accepts
only strict assessment/result JSON, and commits only a locally revalidated
semantic result.  It never navigates or performs a side effect.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from time import perf_counter_ns
from typing import Mapping, Sequence

from .batch_coordinator import BatchCoordinator, BatchSession
from .batching import BatchPlan, BatchUsage
from .boss_campaign_batch_runtime import BOSS_SEMANTIC_BATCH_POLICY
from .boss_campaign_discovery import (
    BOSS_CAMPAIGN_KIND,
    boss_discovery_policy_digest,
    boss_discovery_schema_digest,
    parse_boss_job_identities,
)
from .boss_semantic_extraction import (
    BOSS_OBSERVATION_LADDER,
    BossIncompleteReason,
    BossObservationAttempt,
    BossObservationDecisionState,
    BossObservationSource,
    BossObservationStatus,
    BossSemanticClassification,
    BossSemanticContractError,
    BossSemanticReason,
    BossSemanticResult,
    boss_initial_classification_policy_digest,
    boss_semantic_result_schema,
    decide_next_boss_observation,
    parse_boss_semantic_result,
)
from .campaign import (
    BatchStatus,
    CampaignStatus,
    ItemStatus,
    ItemTransition,
)
from .config import READ_ONLY_MODE
from .context import ContextBudgetError, reduce_ledger
from .grounding import GroundingState
from .privacy import PrivacyError, PrivacySession
from .runner import AgentRunner, PreparedRun, RunFailure, RunnerBudgetError
from .tool_registry import ToolSpec, get_tool_spec, verify_discovered_tools
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall, ToolResult


BOSS_SEMANTIC_ITEM_TASK = (
    "Extract one already-claimed BOSS job using only the disclosed next "
    "observation tool. Return only strict JSON. Company, role, and location "
    "are required; compensation and experience may be null. No user job "
    "preference is configured, so classification must be INSUFFICIENT_EVIDENCE "
    "with only the INSUFFICIENT_EVIDENCE reason."
)
BOSS_SEMANTIC_INITIAL_TURN_ID = "boss_semantic_initial_observation"
BOSS_SEMANTIC_INITIAL_CALL_ID = "boss_semantic_initial_call"
MAX_BOSS_PROVIDER_TEXT_CHARS = 8 * 1024
_BBOX = re.compile(r"\| \((-?\d+),(-?\d+),(\d+),(\d+)\) \|")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class BossSemanticItemRuntimeError(RuntimeError):
    """Fixed failure from the bounded semantic item runtime."""


@dataclass(frozen=True)
class BossSemanticItemOutcome:
    """Committed semantic digest or durable terminal handoff evidence."""

    state: RunState
    claimed_item_ordinal: int
    semantic_result: BossSemanticResult | None
    attempts: tuple[BossObservationAttempt, ...]
    usage: BatchUsage
    stop_code: str
    handoff: Mapping[str, object]


@dataclass(frozen=True)
class _Assessment:
    status: BossObservationStatus
    content_digest: str
    incomplete_reason: BossIncompleteReason | None


def _strict_object(text: str) -> dict[str, object]:
    if (
        not isinstance(text, str)
        or not text
        or len(text) > MAX_BOSS_PROVIDER_TEXT_CHARS
    ):
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_PROVIDER_TEXT_INVALID")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise BossSemanticItemRuntimeError(
                    "BOSS_SEMANTIC_PROVIDER_JSON_DUPLICATE"
                )
            result[key] = value
        return result

    try:
        parsed = json.loads(text, object_pairs_hook=pairs)
    except BossSemanticItemRuntimeError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise BossSemanticItemRuntimeError(
            "BOSS_SEMANTIC_PROVIDER_JSON_INVALID"
        ) from exc
    if not isinstance(parsed, dict):
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_PROVIDER_JSON_INVALID")
    return parsed


def _parse_assessment(text: str) -> _Assessment:
    value = _strict_object(text)
    allowed = {"status", "content_digest", "incomplete_reason"}
    if set(value) - allowed or "status" not in value or "content_digest" not in value:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_ASSESSMENT_INVALID")
    try:
        status = BossObservationStatus(value["status"])
    except (TypeError, ValueError) as exc:
        raise BossSemanticItemRuntimeError(
            "BOSS_SEMANTIC_ASSESSMENT_INVALID"
        ) from exc
    digest = value["content_digest"]
    if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_ASSESSMENT_INVALID")
    raw_reason = value.get("incomplete_reason")
    try:
        reason = (
            None
            if raw_reason is None
            else BossIncompleteReason(raw_reason)
        )
        attempt = BossObservationAttempt(
            source=BossObservationSource.UIA,
            status=status,
            content_digest=digest,
            incomplete_reason=reason,
        )
    except (TypeError, ValueError, BossSemanticContractError) as exc:
        raise BossSemanticItemRuntimeError(
            "BOSS_SEMANTIC_ASSESSMENT_INVALID"
        ) from exc
    if (status is BossObservationStatus.INCOMPLETE) != (
        "incomplete_reason" in value
    ):
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_ASSESSMENT_INVALID")
    return _Assessment(
        status=attempt.status,
        content_digest=attempt.content_digest,
        incomplete_reason=attempt.incomplete_reason,
    )


def boss_tool_result_content_digest(result: ToolResult) -> str:
    """Digest exactly the bounded text and image metadata/bytes seen by the host."""

    if not isinstance(result, ToolResult) or not result.ok:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_RESULT_DIGEST_INVALID")
    material = {
        "images": [
            {
                "byte_length": len(image.data),
                "height": image.height,
                "mime_type": image.mime_type,
                "sha256": sha256(image.data).hexdigest(),
                "width": image.width,
            }
            for image in result.images
        ],
        "sanitized_text": result.sanitized_text,
        "tool_name": result.tool_name,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


def _claimed_region(snapshot_text: str, claimed_key: str) -> dict[str, int]:
    public_id = claimed_key.removeprefix("boss:job:")
    matching = [
        line
        for line in snapshot_text.splitlines()
        if f"/job_detail/{public_id}.html" in line
        and "personal_interest_brand" in line
    ]
    if len(matching) != 1:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_REGION_INVALID")
    match = _BBOX.search(matching[0])
    if match is None:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_REGION_INVALID")
    x, y, w, h = (int(value) for value in match.groups())
    if x < 0 or y < 0 or w <= 0 or h <= 0 or w * h > 4_000_000:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_REGION_INVALID")
    return {"x": x, "y": y, "w": w, "h": h}


def _source_tool(
    source: BossObservationSource,
    *,
    region: Mapping[str, int],
) -> tuple[str, dict[str, object]]:
    if source is BossObservationSource.UIA:
        return "ui_snapshot", {"scope": "foreground"}
    if source is BossObservationSource.DOCUMENT_TEXT:
        return "document_text", {"scope": "foreground"}
    if source is BossObservationSource.OCR:
        return "ocr", dict(region)
    if source is BossObservationSource.CROPPED_IMAGE:
        return "capture_region", dict(region)
    if source is BossObservationSource.SCREENSHOT:
        return "screenshot", {}
    raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_SOURCE_INVALID")


def _claimed_semantic_session(
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
    last = batches.transitions[-1] if batches.transitions else None
    claimed = [
        item
        for item in projection.items.values()
        if item.status is ItemStatus.CLAIMED and item.run_id == run_id
    ]
    if len(claimed) != 1:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_CLAIMED_STATE_INVALID")
    selected = claimed[0]
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
        or selected.ordinal <= 0
        or not selected.item_key.startswith("boss:job:")
    ):
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_CLAIMED_STATE_INVALID")
    return (
        BatchSession(
            campaign_id=campaign_id,
            batch_id=active.batch_id,
            run_id=run_id,
            policy=BOSS_SEMANTIC_BATCH_POLICY,
            plan=BatchPlan(item_keys=(selected.item_key,), stop_reason=None),
        ),
        selected.ordinal,
        selected.item_key,
    )


def _provider_task() -> str:
    return (
        BOSS_SEMANTIC_ITEM_TASK
        + "\nClassification policy digest: "
        + boss_initial_classification_policy_digest()
        + "\nResult schema: "
        + json.dumps(
            boss_semantic_result_schema(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\nTo request the disclosed next tool, return assessment JSON with "
        + "status=INCOMPLETE, the exact prior content_digest, and one fixed "
        + "incomplete_reason. With no tool call, return either the exact result "
        + "schema or terminal assessment JSON."
    )


def _usage(
    state: RunState,
    *,
    started_ns: int,
    output_tokens: int,
    attempts: Sequence[BossObservationAttempt],
    completed: bool,
    failed: bool = False,
) -> BatchUsage:
    return BatchUsage(
        items_completed=1 if completed else 0,
        elapsed_seconds=max(0, (perf_counter_ns() - started_ns) // 1_000_000_000),
        provider_turns=state.budgets.model_turns_used,
        tool_calls=state.budgets.tool_calls_used,
        input_tokens=state.budgets.input_tokens_used,
        output_tokens=output_tokens,
        screenshots=sum(
            attempt.source
            in {BossObservationSource.CROPPED_IMAGE, BossObservationSource.SCREENSHOT}
            for attempt in attempts
        ),
        ocr_regions=sum(
            attempt.source is BossObservationSource.OCR for attempt in attempts
        ),
        consecutive_failures=1 if failed else 0,
    )


def _terminalize_item(
    coordinator: BatchCoordinator,
    session: BatchSession,
    *,
    now: datetime,
    status: BossObservationStatus,
) -> None:
    projection = coordinator.store.read_ledger(session.campaign_id)
    item = projection.items.get(session.plan.item_keys[0])
    if item is None or item.status is not ItemStatus.OBSERVED:
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_TERMINAL_STATE_INVALID")
    target = (
        ItemStatus.CHALLENGE
        if status
        in {
            BossObservationStatus.AUTH_REQUIRED,
            BossObservationStatus.CHALLENGE_REQUIRED,
            BossObservationStatus.SITE_BLOCKED,
        }
        else ItemStatus.RETRYABLE
    )
    coordinator.store.append(
        session.campaign_id,
        ItemTransition(
            sequence=1,
            ordinal=item.ordinal,
            item_key=item.item_key,
            status=target,
            attempt=item.attempt,
            at=now.isoformat(timespec="seconds"),
            run_id=session.run_id,
            boundary="semantic_handoff",
            code=status.value,
        ),
    )


async def execute_claimed_boss_semantics_through_handoff(
    runner: AgentRunner,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> BossSemanticItemOutcome:
    """Observe, strictly extract, commit, finish, and hand off one claimed item."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is None
        or runner.config.policy.mode != READ_ONLY_MODE
        or runner.config.policy.max_side_effects != 0
        or runner.config.policy.max_model_turns < 5
        or runner.config.policy.max_tool_calls < 5
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
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_INPUT_INVALID")

    task = _provider_task()
    privacy = (
        PrivacySession(runner.config.privacy, run_id)
        if runner.config.privacy.enabled
        else None
    )
    if privacy is not None:
        try:
            task = privacy.protect_task(task)
        except PrivacyError as exc:
            await runner.ports.desktop.close()
            raise BossSemanticItemRuntimeError(str(exc)) from exc
    try:
        prepared = runner.prepare(task, run_id=run_id)
    except Exception:
        await runner.ports.desktop.close()
        raise
    recorder = RunRecorder(runner.config.state_dir, run_id)
    if recorder.checkpoint_path.exists() or recorder.trace_path.exists():
        await runner.ports.desktop.close()
        prepared.close()
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_RUN_EXISTS")
    return await _execute_prepared_semantic_item(
        runner,
        prepared,
        recorder,
        campaign_id=campaign_id,
        now=now,
        privacy=privacy,
    )


async def _execute_prepared_semantic_item(
    runner: AgentRunner,
    prepared: PreparedRun,
    recorder: RunRecorder,
    *,
    campaign_id: str,
    now: datetime,
    privacy: PrivacySession | None,
) -> BossSemanticItemOutcome:
    if runner.ports is None:
        prepared.close()
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_PORTS_REQUIRED")
    state = prepared.state
    grounding = GroundingState()
    attempts: list[BossObservationAttempt] = []
    output_tokens = 0
    started_ns = perf_counter_ns()
    recorder_started = False
    try:
        coordinator = BatchCoordinator(
            prepared.campaign_store(runner.config.state_dir)
        )
        session, claimed_ordinal, claimed_key = _claimed_semantic_session(
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
            raise BossSemanticItemRuntimeError(
                f"BOSS_SEMANTIC_OBSERVATION_BLOCKED_{preflight.state.value}"
            )

        recorder.start(state)
        recorder_started = True
        recorder.record(state, RunPhase.OBSERVING)
        discovered = await runner.ports.desktop.discover_tools()
        verify_discovered_tools(discovered)
        recorder.record(state, RunPhase.PLANNING)
        initial_call = ToolCall(
            identity=CallIdentity(
                state.run_id,
                BOSS_SEMANTIC_INITIAL_TURN_ID,
                BOSS_SEMANTIC_INITIAL_CALL_ID,
            ),
            name="ui_snapshot",
            arguments={"scope": "foreground"},
        )
        boundary = await runner._execute_requested_call_boundary(
            state,
            initial_call,
            grounding=grounding,
            recorder=recorder,
            continuation=None,
            privacy=privacy,
        )
        state, grounding = boundary.state, boundary.grounding
        if not boundary.result.ok:
            raise BossSemanticItemRuntimeError(
                "BOSS_SEMANTIC_OBSERVATION_TOOL_FAILED"
            )
        identities = parse_boss_job_identities(boundary.result.sanitized_text)
        if sum(identity.item_key == claimed_key for identity in identities) != 1:
            raise BossSemanticItemRuntimeError(
                "BOSS_SEMANTIC_IDENTITY_NOT_PRESENT"
            )
        region = _claimed_region(boundary.result.sanitized_text, claimed_key)
        observed = coordinator.record_next_claimed_item_observed(
            session,
            usage=BatchUsage(),
            now=now,
            application_state_verified=True,
            item_identity_verified=True,
        )
        if observed.status is not ItemStatus.OBSERVED:
            raise BossSemanticItemRuntimeError(
                "BOSS_SEMANTIC_OBSERVATION_EVIDENCE_INVALID"
            )

        current_source = BossObservationSource.UIA
        current_result = boundary.result
        turn_index = 0
        while True:
            if turn_index >= BOSS_SEMANTIC_BATCH_POLICY.max_provider_turns:
                raise BossSemanticItemRuntimeError(
                    "BOSS_SEMANTIC_PROVIDER_TURN_LIMIT"
                )
            current_digest = boss_tool_result_content_digest(current_result)
            next_index = BOSS_OBSERVATION_LADDER.index(current_source) + 1
            next_source = (
                None
                if next_index >= len(BOSS_OBSERVATION_LADDER)
                else BOSS_OBSERVATION_LADDER[next_index]
            )
            tools: tuple[ToolSpec, ...] = ()
            expected_tool: str | None = None
            expected_arguments: dict[str, object] | None = None
            if next_source is not None:
                expected_tool, expected_arguments = _source_tool(
                    next_source,
                    region=region,
                )
                tools = (get_tool_spec(expected_tool),)

            turn_index += 1
            turn_id = f"boss_semantic_turn_{turn_index}"
            try:
                ledger = reduce_ledger(
                    state.event_log,
                    max_events=runner.config.policy.max_context_events,
                    run_id=state.run_id,
                )
            except ContextBudgetError as exc:
                raise BossSemanticItemRuntimeError(str(exc)) from exc
            provider_started_ns = perf_counter_ns()
            turn = await runner.ports.provider.create_turn(
                run_id=state.run_id,
                turn_id=turn_id,
                task=state.task,
                ledger=ledger,
                tools=tools,
                memories=(),
            )
            if turn.run_id != state.run_id or turn.turn_id != turn_id:
                raise BossSemanticItemRuntimeError(
                    "BOSS_SEMANTIC_PROVIDER_IDENTITY_MISMATCH"
                )
            if privacy is not None:
                try:
                    privacy.validate_model_text(turn.text)
                    for call in turn.tool_calls:
                        privacy.validate_tool_call(call)
                except PrivacyError as exc:
                    raise BossSemanticItemRuntimeError(str(exc)) from exc
            try:
                state = runner._consume_model_turn(
                    state,
                    turn,
                    latency_ms=max(
                        0,
                        (perf_counter_ns() - provider_started_ns) // 1_000_000,
                    ),
                )
            except RunnerBudgetError as exc:
                raise BossSemanticItemRuntimeError(str(exc)) from exc
            output_tokens += turn.usage.output_tokens or 0
            recorder.record(state, RunPhase.PLANNING)
            provider_text = (
                turn.text
                if privacy is None
                else privacy.restore_text(turn.text)
            )

            if turn.tool_calls:
                if (
                    len(turn.tool_calls) != 1
                    or next_source is None
                    or expected_tool is None
                    or expected_arguments is None
                ):
                    raise BossSemanticItemRuntimeError(
                        "BOSS_SEMANTIC_TOOL_SEQUENCE_INVALID"
                    )
                assessment = _parse_assessment(provider_text)
                if (
                    assessment.status is not BossObservationStatus.INCOMPLETE
                    or assessment.content_digest != current_digest
                ):
                    raise BossSemanticItemRuntimeError(
                        "BOSS_SEMANTIC_ASSESSMENT_MISMATCH"
                    )
                attempt = BossObservationAttempt(
                    source=current_source,
                    status=assessment.status,
                    content_digest=current_digest,
                    incomplete_reason=assessment.incomplete_reason,
                )
                decision = decide_next_boss_observation((*attempts, attempt))
                call = turn.tool_calls[0]
                if (
                    decision.state is not BossObservationDecisionState.OBSERVE
                    or decision.next_source is not next_source
                    or call.name != expected_tool
                    or dict(call.arguments) != expected_arguments
                ):
                    raise BossSemanticItemRuntimeError(
                        "BOSS_SEMANTIC_TOOL_SEQUENCE_INVALID"
                    )
                attempts.append(attempt)
                try:
                    boundary = await runner._execute_requested_call_boundary(
                        state,
                        call,
                        grounding=grounding,
                        recorder=recorder,
                        continuation=None,
                        privacy=privacy,
                    )
                except RunFailure as exc:
                    if (
                        exc.code != "POLICY_DENIED"
                        or not get_tool_spec(call.name).required_safety_baselines
                    ):
                        raise
                    state = exc.state
                    _terminalize_item(
                        coordinator,
                        session,
                        now=now,
                        status=BossObservationStatus.CONTENT_UNAVAILABLE,
                    )
                    usage = _usage(
                        state,
                        started_ns=started_ns,
                        output_tokens=output_tokens,
                        attempts=attempts,
                        completed=False,
                        failed=True,
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
                    recorder.record(
                        state,
                        RunPhase.SUCCESS,
                        run_duration_ms=max(
                            0, (perf_counter_ns() - started_ns) // 1_000_000
                        ),
                    )
                    return BossSemanticItemOutcome(
                        state=state,
                        claimed_item_ordinal=claimed_ordinal,
                        semantic_result=None,
                        attempts=tuple(attempts),
                        usage=usage,
                        stop_code=stop_code,
                        handoff=handoff,
                    )
                state, grounding = boundary.state, boundary.grounding
                if not boundary.result.ok:
                    raise BossSemanticItemRuntimeError(
                        "BOSS_SEMANTIC_OBSERVATION_TOOL_FAILED"
                    )
                current_source = next_source
                current_result = boundary.result
                continue

            parsed = _strict_object(provider_text)
            semantic: BossSemanticResult | None = None
            try:
                semantic = parse_boss_semantic_result(parsed)
            except BossSemanticContractError:
                assessment = _parse_assessment(provider_text)
                if assessment.content_digest != current_digest:
                    raise BossSemanticItemRuntimeError(
                        "BOSS_SEMANTIC_ASSESSMENT_MISMATCH"
                    )
                attempt = BossObservationAttempt(
                    source=current_source,
                    status=assessment.status,
                    content_digest=current_digest,
                    incomplete_reason=assessment.incomplete_reason,
                )
                decision = decide_next_boss_observation((*attempts, attempt))
                if decision.state is not BossObservationDecisionState.HANDOFF:
                    raise BossSemanticItemRuntimeError(
                        "BOSS_SEMANTIC_TERMINAL_INVALID"
                    )
                attempts.append(attempt)
                _terminalize_item(
                    coordinator,
                    session,
                    now=now,
                    status=assessment.status,
                )
                usage = _usage(
                    state,
                    started_ns=started_ns,
                    output_tokens=output_tokens,
                    attempts=attempts,
                    completed=False,
                    failed=True,
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
                recorder.record(
                    state,
                    RunPhase.SUCCESS,
                    run_duration_ms=max(
                        0, (perf_counter_ns() - started_ns) // 1_000_000
                    ),
                )
                return BossSemanticItemOutcome(
                    state=state,
                    claimed_item_ordinal=claimed_ordinal,
                    semantic_result=None,
                    attempts=tuple(attempts),
                    usage=usage,
                    stop_code=stop_code,
                    handoff=handoff,
                )

            if (
                semantic.item_key != claimed_key
                or semantic.source is not current_source
                or semantic.source_digest != current_digest
                or semantic.classification_policy_digest
                != boss_initial_classification_policy_digest()
                or semantic.classification
                is not BossSemanticClassification.INSUFFICIENT_EVIDENCE
                or semantic.classification_reasons
                != (BossSemanticReason.INSUFFICIENT_EVIDENCE,)
            ):
                raise BossSemanticItemRuntimeError(
                    "BOSS_SEMANTIC_RESULT_MISMATCH"
                )
            sufficient = BossObservationAttempt(
                source=current_source,
                status=BossObservationStatus.SUFFICIENT,
                content_digest=current_digest,
            )
            decision = decide_next_boss_observation((*attempts, sufficient))
            if decision.state is not BossObservationDecisionState.EXTRACT:
                raise BossSemanticItemRuntimeError(
                    "BOSS_SEMANTIC_RESULT_SEQUENCE_INVALID"
                )
            attempts.append(sufficient)
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
                content_digest=semantic.content_digest,
            )
            if (
                extracted.status is not ItemStatus.EXTRACTED
                or committed.status is not ItemStatus.COMMITTED
                or committed.content_digest != semantic.content_digest
            ):
                raise BossSemanticItemRuntimeError(
                    "BOSS_SEMANTIC_COMMIT_EVIDENCE_INVALID"
                )
            usage = _usage(
                state,
                started_ns=started_ns,
                output_tokens=output_tokens,
                attempts=attempts,
                completed=True,
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
            recorder.record(
                state,
                RunPhase.SUCCESS,
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
            return BossSemanticItemOutcome(
                state=state,
                claimed_item_ordinal=claimed_ordinal,
                semantic_result=semantic,
                attempts=tuple(attempts),
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
    except RunFailure as exc:
        state = exc.state
        if recorder_started:
            recorder.record(
                state,
                (
                    RunPhase.UNKNOWN_OUTCOME
                    if exc.code == "UNKNOWN_OUTCOME"
                    else RunPhase.FAILED
                ),
                failure_code=exc.code,
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
        raise BossSemanticItemRuntimeError(exc.code) from exc
    except BossSemanticItemRuntimeError as exc:
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
                failure_code="BOSS_SEMANTIC_UNCERTAIN",
                run_duration_ms=max(
                    0, (perf_counter_ns() - started_ns) // 1_000_000
                ),
            )
        raise BossSemanticItemRuntimeError("BOSS_SEMANTIC_UNCERTAIN") from exc
    finally:
        try:
            await runner.ports.desktop.close()
        finally:
            prepared.close()


__all__ = [
    "BOSS_SEMANTIC_INITIAL_CALL_ID",
    "BOSS_SEMANTIC_INITIAL_TURN_ID",
    "BOSS_SEMANTIC_ITEM_TASK",
    "BossSemanticItemOutcome",
    "BossSemanticItemRuntimeError",
    "boss_tool_result_content_digest",
    "execute_claimed_boss_semantics_through_handoff",
]
