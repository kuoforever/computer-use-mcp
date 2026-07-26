"""Generic durable preparation and batch start for reviewed application workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from time import perf_counter_ns
from typing import Mapping

from .application_worker_catalog import (
    ApplicationWorkerSpec,
    application_worker_policy_digest,
    application_worker_schema_digest,
)
from .application_worker_contract import (
    ApplicationWorkerContractError,
    ApplicationWorkerResult,
    compile_application_worker_task,
    parse_application_worker_result,
)
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
    BatchTransition,
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
    campaign_dir,
)
from .run_lock import RunLock
from .runner import AgentRunner
from .stale_run_inspection import StaleRunState, inspect_stale_run
from .trace import RunRecorder
from .types import LedgerEventKind, RunState
from .worker_capabilities import tools_for_composition


APPLICATION_BATCH_POLICY = BatchPolicy(max_items=1)
APPLICATION_ITEM_LEASE_SECONDS = 5 * 60
MAX_APPLICATION_CAMPAIGN_ITEMS = 500


class ApplicationCampaignRuntimeError(RuntimeError):
    """Fixed failure from generic application campaign control."""


@dataclass(frozen=True)
class ApplicationCampaignPreparation:
    campaign_id: str
    campaign_kind: str
    scenario_id: str
    run_id: str
    item_count: int


@dataclass(frozen=True)
class ApplicationCampaignBatchStart:
    campaign_id: str
    campaign_kind: str
    scenario_id: str
    run_id: str
    batch_id: str
    planned_item_count: int
    claimed_item_ordinal: int
    lease_expires_at: str


@dataclass(frozen=True)
class ApplicationCampaignItemOutcome:
    campaign_id: str
    campaign_kind: str
    scenario_id: str
    run_id: str
    claimed_item_ordinal: int
    result: ApplicationWorkerResult
    stop_code: str
    usage: BatchUsage
    handoff: Mapping[str, object]


@dataclass(frozen=True)
class ApplicationCampaignResumeOutcome:
    campaign_id: str
    campaign_kind: str
    scenario_id: str
    replacement_run_id: str
    prior_run_id: str
    batch_id: str
    claimed_item_ordinal: int
    planned_item_count: int
    lease_expires_at: str
    heartbeat: CampaignHeartbeat
    resume: BatchTransferredResumePreflight
    prior_handoff: Mapping[str, object]


def _require_now(now: datetime) -> datetime:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_TIME_INVALID")
    return now


def _batch_id(spec: ApplicationWorkerSpec, run_id: str) -> str:
    suffix = sha256(f"{spec.scenario_id}:{run_id}".encode("ascii")).hexdigest()[:16]
    return f"app_batch_{suffix}"


def prepare_application_campaign(
    runner: AgentRunner,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
    run_id: str,
    item_keys: tuple[str, ...],
    now: datetime,
) -> ApplicationCampaignPreparation:
    """Create one explicit reviewed scenario campaign from stable item keys."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is not None
        or not isinstance(spec, ApplicationWorkerSpec)
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(item_keys, tuple)
        or not item_keys
        or len(item_keys) > MAX_APPLICATION_CAMPAIGN_ITEMS
        or len(set(item_keys)) != len(item_keys)
        or any(not isinstance(key, str) or not key for key in item_keys)
    ):
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_INPUT_INVALID")
    timestamp = _require_now(now).isoformat(timespec="seconds")
    try:
        prepared = runner.prepare(
            f"Prepare reviewed application campaign {spec.scenario_id}",
            run_id=run_id,
        )
    except (OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_PREPARE_FAILED") from exc
    try:
        recorder = RunRecorder(runner.config.state_dir, run_id)
        store = prepared.campaign_store(runner.config.state_dir)
        directory = campaign_dir(store.state_dir, campaign_id)
        if (
            recorder.checkpoint_path.exists()
            or recorder.trace_path.exists()
            or directory.exists()
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_EXISTS")
        store.create(
            CampaignManifest(
                campaign_id=campaign_id,
                kind=spec.kind,
                policy_digest=application_worker_policy_digest(spec),
                schema_digest=application_worker_schema_digest(spec),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
        for ordinal, item_key in enumerate(item_keys, start=1):
            store.append(
                campaign_id,
                ItemTransition(
                    sequence=ordinal,
                    ordinal=ordinal,
                    item_key=item_key,
                    status=ItemStatus.DISCOVERED,
                    attempt=0,
                    at=timestamp,
                ),
            )
        projection = store.read_ledger(campaign_id)
        if (
            projection.discovered_count != len(item_keys)
            or tuple(
                item.item_key
                for item in sorted(
                    projection.items.values(),
                    key=lambda item: item.ordinal,
                )
            )
            != item_keys
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_STATE_INVALID")
        return ApplicationCampaignPreparation(
            campaign_id=campaign_id,
            campaign_kind=spec.kind,
            scenario_id=spec.scenario_id,
            run_id=run_id,
            item_count=len(item_keys),
        )
    except ApplicationCampaignRuntimeError:
        raise
    except (CampaignStoreError, OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_PREPARE_FAILED") from exc
    finally:
        prepared.close()


def start_application_campaign_batch(
    runner: AgentRunner,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> ApplicationCampaignBatchStart:
    """Start and claim the first exact item for any reviewed scenario."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is not None
        or not isinstance(spec, ApplicationWorkerSpec)
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(run_id, str)
        or not run_id
    ):
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_INPUT_INVALID")
    timestamp = _require_now(now)
    try:
        prepared = runner.prepare(
            f"Start reviewed application campaign {spec.scenario_id}",
            run_id=run_id,
        )
    except (OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_START_FAILED") from exc
    try:
        recorder = RunRecorder(runner.config.state_dir, run_id)
        store = prepared.campaign_store(runner.config.state_dir)
        manifest = store.read_manifest(campaign_id)
        projection = store.read_ledger(campaign_id)
        batches = store.read_batches(campaign_id)
        if (
            recorder.checkpoint_path.exists()
            or recorder.trace_path.exists()
            or manifest.kind != spec.kind
            or manifest.status is not CampaignStatus.RUNNING
            or manifest.policy_digest != application_worker_policy_digest(spec)
            or manifest.schema_digest != application_worker_schema_digest(spec)
            or not projection.items
            or any(
                item.status not in {ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
                for item in projection.items.values()
            )
            or batches.transitions
            or store.read_heartbeat(campaign_id) is not None
            or (campaign_dir(store.state_dir, campaign_id) / "handoff.json").exists()
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_STATE_INVALID")
        heartbeat = CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=run_id,
            started_at=timestamp.isoformat(timespec="seconds"),
            heartbeat_at=timestamp.isoformat(timespec="seconds"),
            fresh_until=(
                timestamp + timedelta(seconds=APPLICATION_ITEM_LEASE_SECONDS)
            ).isoformat(timespec="seconds"),
        )
        store.write_heartbeat(campaign_id, heartbeat)
        coordinator = BatchCoordinator(store)
        opened = coordinator.open_batch(
            campaign_id=campaign_id,
            batch_id=_batch_id(spec, run_id),
            run_id=run_id,
            policy=APPLICATION_BATCH_POLICY,
        )
        if not isinstance(opened, BatchSession):
            if isinstance(opened, BatchPlan) and opened.stop_reason is not None:
                raise ApplicationCampaignRuntimeError(
                    f"APPLICATION_CAMPAIGN_START_BLOCKED_{opened.stop_reason.value}"
                )
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_START_INVALID")
        claimed = coordinator.claim_next_item(
            opened,
            usage=BatchUsage(),
            now=timestamp,
            lease_seconds=APPLICATION_ITEM_LEASE_SECONDS,
        )
        if (
            claimed.status is not ItemStatus.CLAIMED
            or claimed.item_key != opened.plan.item_keys[0]
            or claimed.run_id != run_id
            or claimed.lease_expires_at is None
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_CLAIM_INVALID")
        return ApplicationCampaignBatchStart(
            campaign_id=campaign_id,
            campaign_kind=spec.kind,
            scenario_id=spec.scenario_id,
            run_id=run_id,
            batch_id=opened.batch_id,
            planned_item_count=len(opened.plan.item_keys),
            claimed_item_ordinal=claimed.ordinal,
            lease_expires_at=claimed.lease_expires_at,
        )
    except ApplicationCampaignRuntimeError:
        raise
    except (BatchCoordinatorError, CampaignStoreError, OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_START_FAILED") from exc
    finally:
        prepared.close()


def _claimed_application_session(
    store,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
    run_id: str,
) -> tuple[BatchSession, int, str]:
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
    selected = claimed[0] if len(claimed) == 1 else None
    last = batches.transitions[-1] if batches.transitions else None
    if (
        manifest.kind != spec.kind
        or manifest.status is not CampaignStatus.RUNNING
        or manifest.policy_digest != application_worker_policy_digest(spec)
        or manifest.schema_digest != application_worker_schema_digest(spec)
        or active is None
        or last is None
        or last.status is not BatchStatus.STARTED
        or active.run_id != run_id
        or last.batch_id != active.batch_id
        or heartbeat is None
        or heartbeat.run_id != run_id
        or selected is None
    ):
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_CLAIM_INVALID")
    return (
        BatchSession(
            campaign_id=campaign_id,
            batch_id=active.batch_id,
            run_id=run_id,
            policy=APPLICATION_BATCH_POLICY,
            plan=BatchPlan(item_keys=(selected.item_key,), stop_reason=None),
        ),
        selected.ordinal,
        selected.item_key,
    )


def _inspect_claim(
    runner: AgentRunner,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
    run_id: str,
) -> tuple[int, str]:
    lock = RunLock(runner.config.application_state_dir)
    lock.acquire()
    try:
        session, ordinal, item_key = _claimed_application_session(
            CampaignStore(runner.config.state_dir, lock),
            spec=spec,
            campaign_id=campaign_id,
            run_id=run_id,
        )
        if session.plan.item_keys != (item_key,):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_CLAIM_INVALID")
        return ordinal, item_key
    except ApplicationCampaignRuntimeError:
        raise
    except (CampaignStoreError, OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_CLAIM_INVALID") from exc
    finally:
        lock.release()


def _measured_usage(state: RunState, *, elapsed_seconds: int) -> BatchUsage:
    output_tokens = 0
    screenshots = 0
    ocr_regions = 0
    for event in state.event_log:
        if event.kind is LedgerEventKind.MODEL_TURN:
            value = event.payload.get("output_tokens")
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                output_tokens += value
        elif (
            event.kind is LedgerEventKind.TOOL_CALL
            and event.safe_argument_summary is not None
        ):
            if event.safe_argument_summary.tool_name in {"screenshot", "capture_region"}:
                screenshots += 1
            elif event.safe_argument_summary.tool_name == "ocr":
                ocr_regions += 1
    return BatchUsage(
        items_completed=1,
        elapsed_seconds=elapsed_seconds,
        provider_turns=state.budgets.model_turns_used,
        tool_calls=state.budgets.tool_calls_used,
        input_tokens=state.budgets.input_tokens_used,
        output_tokens=output_tokens,
        screenshots=screenshots,
        ocr_regions=ocr_regions,
    )


def _usage_from_finished(finished: BatchTransition) -> BatchUsage:
    return BatchUsage(
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


async def execute_claimed_application_item(
    runner: AgentRunner,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> ApplicationCampaignItemOutcome:
    """Run one exact claimed item through Runner and digest-backed commit."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is None
        or not isinstance(spec, ApplicationWorkerSpec)
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(run_id, str)
        or not run_id
    ):
        if isinstance(runner, AgentRunner) and runner.ports is not None:
            await runner.ports.desktop.close()
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_INPUT_INVALID")
    timestamp = _require_now(now)
    claimed_ordinal, item_key = _inspect_claim(
        runner,
        spec=spec,
        campaign_id=campaign_id,
        run_id=run_id,
    )
    task = compile_application_worker_task(
        spec,
        item_key=item_key,
        item_ordinal=claimed_ordinal,
    )
    allowed_tools = tools_for_composition(
        spec.scenario_id,
        spec.capability_names,
    )
    started_ns = perf_counter_ns()
    try:
        run = await runner.run(
            task,
            run_id=run_id,
            allowed_tool_names=allowed_tools,
        )
        parsed = parse_application_worker_result(
            spec,
            item_key=item_key,
            text=run.text,
        )
    except ApplicationWorkerContractError as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_RESULT_INVALID") from exc
    if parsed.outcome != "EXTRACTED":
        raise ApplicationCampaignRuntimeError(
            f"APPLICATION_CAMPAIGN_BLOCKED_{parsed.stop_code}"
        )
    executed_tools = {
        event.safe_argument_summary.tool_name
        for event in run.state.event_log
        if event.kind is LedgerEventKind.TOOL_CALL
        and event.safe_argument_summary is not None
    }
    if not set(parsed.observation_tools) <= executed_tools:
        raise ApplicationCampaignRuntimeError(
            "APPLICATION_CAMPAIGN_EVIDENCE_INVALID"
        )
    usage = _measured_usage(
        run.state,
        elapsed_seconds=max(0, (perf_counter_ns() - started_ns) // 1_000_000_000),
    )
    lock = RunLock(runner.config.application_state_dir)
    lock.acquire()
    try:
        coordinator = BatchCoordinator(CampaignStore(runner.config.state_dir, lock))
        session, ordinal, current_key = _claimed_application_session(
            coordinator.store,
            spec=spec,
            campaign_id=campaign_id,
            run_id=run_id,
        )
        if ordinal != claimed_ordinal or current_key != item_key:
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_CLAIM_DRIFT")
        zero = BatchUsage()
        coordinator.record_next_claimed_item_observed(
            session,
            usage=zero,
            now=timestamp,
            application_state_verified=parsed.application_state_verified,
            item_identity_verified=parsed.item_identity_verified,
        )
        coordinator.record_next_observed_item_extracted(
            session,
            usage=zero,
            now=timestamp,
            read_only_extraction_completed=True,
        )
        committed = coordinator.record_next_extracted_item_committed(
            session,
            usage=zero,
            now=timestamp,
            bounded_result_verified=True,
            content_digest=parsed.content_digest,
        )
        if (
            committed.status is not ItemStatus.COMMITTED
            or committed.content_digest != parsed.content_digest
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_COMMIT_INVALID")
        stop_code = coordinator.finish_continued_batch(
            session,
            usage=usage,
            now=timestamp,
        )
        handoff = coordinator.write_finished_handoff(
            session,
            usage=usage,
            now=timestamp,
        )
        if (
            stop_code != "ITEM_LIMIT"
            or handoff.get("campaign_id") != campaign_id
            or handoff.get("last_run_id") != run_id
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_HANDOFF_INVALID")
        return ApplicationCampaignItemOutcome(
            campaign_id=campaign_id,
            campaign_kind=spec.kind,
            scenario_id=spec.scenario_id,
            run_id=run_id,
            claimed_item_ordinal=claimed_ordinal,
            result=parsed,
            stop_code=stop_code,
            usage=usage,
            handoff=handoff,
        )
    except ApplicationCampaignRuntimeError:
        raise
    except (BatchCoordinatorError, CampaignStoreError, OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_COMMIT_FAILED") from exc
    finally:
        lock.release()


def _finished_application_session(
    store: CampaignStore,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
) -> tuple[BatchSession, BatchUsage, Mapping[str, object], int]:
    manifest = store.read_manifest(campaign_id)
    projection = store.read_ledger(campaign_id)
    batches = store.read_batches(campaign_id)
    handoff = store.read_handoff(campaign_id)
    heartbeat = store.read_heartbeat(campaign_id)
    transitions = batches.transitions
    started = transitions[-2] if len(transitions) >= 2 else None
    finished = transitions[-1] if transitions else None
    committed = (
        []
        if finished is None
        else [
            item
            for item in projection.items.values()
            if item.status is ItemStatus.COMMITTED and item.run_id == finished.run_id
        ]
    )
    selected = committed[0] if len(committed) == 1 else None
    if (
        manifest.kind != spec.kind
        or manifest.status is not CampaignStatus.RUNNING
        or manifest.policy_digest != application_worker_policy_digest(spec)
        or manifest.schema_digest != application_worker_schema_digest(spec)
        or batches.active is not None
        or started is None
        or finished is None
        or started.status is not BatchStatus.STARTED
        or finished.status is not BatchStatus.FINISHED
        or (started.batch_id, started.run_id) != (finished.batch_id, finished.run_id)
        or finished.stop_code != "ITEM_LIMIT"
        or finished.items_completed != 1
        or selected is None
        or handoff.get("last_run_id") != finished.run_id
        or handoff.get("completed_count") != projection.completed_count
        or handoff.get("next_item_ordinal") != projection.next_ordinal
        or handoff.get("next_action") != "resume_batch"
        or heartbeat is None
        or heartbeat.run_id != finished.run_id
    ):
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_RESUME_STATE_INVALID")
    return (
        BatchSession(
            campaign_id=campaign_id,
            batch_id=finished.batch_id,
            run_id=finished.run_id,
            policy=APPLICATION_BATCH_POLICY,
            plan=BatchPlan(item_keys=(selected.item_key,), stop_reason=None),
        ),
        _usage_from_finished(finished),
        handoff,
        projection.next_ordinal,
    )


def resume_application_campaign_batch(
    runner: AgentRunner,
    *,
    spec: ApplicationWorkerSpec,
    campaign_id: str,
    replacement_run_id: str,
    now: datetime,
) -> ApplicationCampaignResumeOutcome:
    """Transfer a finished one-item worker context and claim the next item."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is not None
        or not isinstance(spec, ApplicationWorkerSpec)
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(replacement_run_id, str)
        or not replacement_run_id
    ):
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_INPUT_INVALID")
    timestamp = _require_now(now)
    try:
        prepared = runner.prepare(
            f"Resume reviewed application campaign {spec.scenario_id}",
            run_id=replacement_run_id,
        )
    except (OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_RESUME_FAILED") from exc
    try:
        coordinator = BatchCoordinator(
            prepared.campaign_store(runner.config.state_dir)
        )
        session, usage, handoff, expected_ordinal = _finished_application_session(
            coordinator.store,
            spec=spec,
            campaign_id=campaign_id,
        )
        replacement = CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=replacement_run_id,
            started_at=timestamp.isoformat(timespec="seconds"),
            heartbeat_at=timestamp.isoformat(timespec="seconds"),
            fresh_until=(
                timestamp + timedelta(seconds=APPLICATION_ITEM_LEASE_SECONDS)
            ).isoformat(timespec="seconds"),
        )
        stale = inspect_stale_run(
            coordinator.store,
            campaign_id=campaign_id,
            now=timestamp,
        )
        if stale.state is StaleRunState.STALE:
            heartbeat = coordinator.store.recover_stale_heartbeat(
                campaign_id,
                stale_run_id=session.run_id,
                replacement=replacement,
                now=timestamp,
            )
        elif stale.state is StaleRunState.FRESH_HEARTBEAT:
            heartbeat = coordinator.replace_finished_run_heartbeat_owner(
                session,
                usage=usage,
                now=timestamp,
                replacement=replacement,
            )
        else:
            raise ApplicationCampaignRuntimeError(
                "APPLICATION_CAMPAIGN_RESUME_HEARTBEAT_INVALID"
            )
        resume = coordinator.inspect_transferred_run_resume(
            session,
            replacement_run_id=replacement_run_id,
            now=timestamp,
            policy=APPLICATION_BATCH_POLICY,
        )
        if (
            heartbeat != replacement
            or resume.state is not BatchTransferredResumeState.READY
            or not resume.ready
            or not resume.item_keys
            or resume.next_item_ordinal != expected_ordinal
        ):
            raise ApplicationCampaignRuntimeError(
                "APPLICATION_CAMPAIGN_RESUME_EVIDENCE_INVALID"
            )
        opened = coordinator.open_transferred_resumed_batch(
            session,
            batch_id=_batch_id(spec, replacement_run_id),
            replacement_run_id=replacement_run_id,
            now=timestamp,
            policy=APPLICATION_BATCH_POLICY,
        )
        claimed = coordinator.claim_next_item(
            opened,
            usage=BatchUsage(),
            now=timestamp,
            lease_seconds=APPLICATION_ITEM_LEASE_SECONDS,
        )
        if (
            claimed.status is not ItemStatus.CLAIMED
            or claimed.run_id != replacement_run_id
            or claimed.item_key != resume.item_keys[0]
            or claimed.ordinal != expected_ordinal
            or claimed.lease_expires_at is None
        ):
            raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_CLAIM_INVALID")
        return ApplicationCampaignResumeOutcome(
            campaign_id=campaign_id,
            campaign_kind=spec.kind,
            scenario_id=spec.scenario_id,
            replacement_run_id=replacement_run_id,
            prior_run_id=session.run_id,
            batch_id=opened.batch_id,
            claimed_item_ordinal=claimed.ordinal,
            planned_item_count=len(opened.plan.item_keys),
            lease_expires_at=claimed.lease_expires_at,
            heartbeat=heartbeat,
            resume=resume,
            prior_handoff=handoff,
        )
    except ApplicationCampaignRuntimeError:
        raise
    except (BatchCoordinatorError, CampaignStoreError, OSError, ValueError) as exc:
        raise ApplicationCampaignRuntimeError("APPLICATION_CAMPAIGN_RESUME_FAILED") from exc
    finally:
        prepared.close()


__all__ = [
    "APPLICATION_BATCH_POLICY",
    "APPLICATION_ITEM_LEASE_SECONDS",
    "ApplicationCampaignBatchStart",
    "ApplicationCampaignItemOutcome",
    "ApplicationCampaignPreparation",
    "ApplicationCampaignResumeOutcome",
    "ApplicationCampaignRuntimeError",
    "execute_claimed_application_item",
    "prepare_application_campaign",
    "resume_application_campaign_batch",
    "start_application_campaign_batch",
]
