"""Transfer one finished BOSS batch to a fresh run and claim the next item.

This is a control-only restart boundary.  It reconstructs the exact finished
session from durable campaign records, transfers heartbeat ownership, opens
the coordinator-selected resumed batch, and claims only its first item.  It
does not create a desktop or provider boundary and accepts no item selector.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Mapping

from .batch_coordinator import (
    BatchCoordinator,
    BatchCoordinatorError,
    BatchSession,
    BatchTransferredResumePreflight,
    BatchTransferredResumeState,
)
from .batching import BatchPlan, BatchPolicy, BatchUsage, batch_stop_reason
from .boss_campaign_batch_runtime import (
    BOSS_BATCH_LEASE_SECONDS,
    BOSS_BATCH_POLICY,
    BOSS_SEMANTIC_BATCH_POLICY,
)
from .boss_campaign_discovery import (
    BOSS_CAMPAIGN_KIND,
    boss_discovery_policy_digest,
    boss_discovery_schema_digest,
)
from .campaign import (
    BatchStatus,
    BatchTransition,
    CampaignHeartbeat,
    CampaignStatus,
    CampaignStoreError,
    ItemStatus,
)
from .config import READ_ONLY_MODE
from .runner import AgentRunner
from .stale_run_inspection import StaleRunState, inspect_stale_run


BOSS_RESTART_TASK = "Resume one finished BOSS read-only batch from durable state"
BOSS_SEMANTIC_RESTART_TASK = (
    "Resume one finished BOSS semantic read-only batch from durable state"
)


class BossCampaignRestartRuntimeError(RuntimeError):
    """Fixed failure from the BOSS restart-transfer boundary."""


@dataclass(frozen=True)
class BossCampaignRestartOutcome:
    """Fresh batch ownership and the next coordinator-selected claim."""

    campaign_id: str
    replacement_run_id: str
    prior_run_id: str
    batch_id: str
    claimed_item_ordinal: int
    planned_item_count: int
    lease_expires_at: str
    heartbeat: CampaignHeartbeat
    resume: BatchTransferredResumePreflight
    prior_handoff: Mapping[str, object]


def _resumed_batch_id(run_id: str) -> str:
    suffix = sha256(run_id.encode("utf-8", "strict")).hexdigest()[:16]
    return f"boss_resume_{suffix}"


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


def _finished_boss_session(
    coordinator: BatchCoordinator,
    *,
    campaign_id: str,
    policy: BatchPolicy,
    semantic: bool,
) -> tuple[BatchSession, BatchUsage, Mapping[str, object], int]:
    store = coordinator.store
    manifest = store.read_manifest(campaign_id)
    projection = store.read_ledger(campaign_id)
    batches = store.read_batches(campaign_id)
    try:
        handoff = store.read_handoff(campaign_id)
    except CampaignStoreError as exc:
        raise BossCampaignRestartRuntimeError(
            "BOSS_RESTART_STATE_INVALID"
        ) from exc
    heartbeat = store.read_heartbeat(campaign_id)
    transitions = batches.transitions
    started = transitions[-2] if len(transitions) >= 2 else None
    finished = transitions[-1] if transitions else None
    committed = (
        []
        if finished is None
        else sorted(
            (
                item
                for item in projection.items.values()
                if item.status is ItemStatus.COMMITTED
                and item.run_id == finished.run_id
            ),
            key=lambda item: (item.ordinal, item.item_key),
        )
    )
    selected = committed[0] if len(committed) == 1 else None
    tail = (
        []
        if selected is None
        else sorted(
            (
                item
                for item in projection.items.values()
                if item.ordinal >= selected.ordinal
                and (
                    item == selected
                    or item.status
                    in {ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
                )
            ),
            key=lambda item: (item.ordinal, item.item_key),
        )[: policy.max_items]
    )
    usage = None if finished is None else _usage_from_finished(finished)
    measured_stop = (
        None if usage is None else batch_stop_reason(policy, usage)
    )
    if (
        manifest.kind != BOSS_CAMPAIGN_KIND
        or manifest.status is not CampaignStatus.RUNNING
        or manifest.policy_digest != boss_discovery_policy_digest()
        or manifest.schema_digest != boss_discovery_schema_digest()
        or batches.active is not None
        or started is None
        or finished is None
        or started.status is not BatchStatus.STARTED
        or finished.status is not BatchStatus.FINISHED
        or (started.batch_id, started.run_id)
        != (finished.batch_id, finished.run_id)
        or usage is None
        or measured_stop is None
        or finished.stop_code != measured_stop.value
        or finished.items_completed != 1
        or (
            not semantic
            and (finished.tool_calls != 1 or finished.provider_turns != 0)
        )
        or (
            semantic
            and (
                not 1 <= finished.tool_calls <= policy.max_tool_calls
                or not 1 <= finished.provider_turns <= policy.max_provider_turns
                or finished.screenshots > policy.max_screenshots
                or finished.ocr_regions > policy.max_ocr_regions
            )
        )
        or selected is None
        or not tail
        or tail[0] != selected
        or handoff.get("last_run_id") != finished.run_id
        or handoff.get("completed_count") != projection.completed_count
        or handoff.get("next_item_ordinal") != projection.next_ordinal
        or handoff.get("next_action") != "resume_batch"
        or handoff.get("required_observation")
        != "verify_current_page_and_account_state"
        or heartbeat is None
        or heartbeat.run_id != finished.run_id
    ):
        raise BossCampaignRestartRuntimeError("BOSS_RESTART_STATE_INVALID")
    return (
        BatchSession(
            campaign_id=campaign_id,
            batch_id=finished.batch_id,
            run_id=finished.run_id,
            policy=policy,
            plan=BatchPlan(
                item_keys=tuple(item.item_key for item in tail),
                stop_reason=None,
            ),
        ),
        usage,
        handoff,
        projection.next_ordinal,
    )


def _resume_finished_boss_batch_after_restart(
    runner: AgentRunner,
    *,
    campaign_id: str,
    replacement_run_id: str,
    now: datetime,
    task: str,
    policy: BatchPolicy,
    semantic: bool,
) -> BossCampaignRestartOutcome:
    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is not None
        or runner.config.policy.mode != READ_ONLY_MODE
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(replacement_run_id, str)
        or not replacement_run_id
        or not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise BossCampaignRestartRuntimeError("BOSS_RESTART_INPUT_INVALID")
    try:
        prepared = runner.prepare(task, run_id=replacement_run_id)
    except (OSError, ValueError) as exc:
        raise BossCampaignRestartRuntimeError("BOSS_RESTART_PREPARE_FAILED") from exc
    try:
        coordinator = BatchCoordinator(
            prepared.campaign_store(runner.config.state_dir)
        )
        session, usage, handoff, expected_ordinal = _finished_boss_session(
            coordinator,
            campaign_id=campaign_id,
            policy=policy,
            semantic=semantic,
        )
        replacement = CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=replacement_run_id,
            started_at=now.isoformat(timespec="seconds"),
            heartbeat_at=now.isoformat(timespec="seconds"),
            fresh_until=(
                now + timedelta(seconds=BOSS_BATCH_LEASE_SECONDS)
            ).isoformat(timespec="seconds"),
        )
        stale = inspect_stale_run(
            coordinator.store,
            campaign_id=campaign_id,
            now=now,
        )
        if stale.state is StaleRunState.STALE:
            heartbeat = coordinator.store.recover_stale_heartbeat(
                campaign_id,
                stale_run_id=session.run_id,
                replacement=replacement,
                now=now,
            )
        elif stale.state is StaleRunState.FRESH_HEARTBEAT:
            heartbeat = coordinator.replace_finished_run_heartbeat_owner(
                session,
                usage=usage,
                now=now,
                replacement=replacement,
            )
        else:
            raise BossCampaignRestartRuntimeError(
                "BOSS_RESTART_HEARTBEAT_STATE_INVALID"
            )
        resume = coordinator.inspect_transferred_run_resume(
            session,
            replacement_run_id=replacement_run_id,
            now=now,
            policy=policy,
        )
        if (
            heartbeat != replacement
            or resume.state is not BatchTransferredResumeState.READY
            or not resume.ready
            or not resume.item_keys
            or resume.next_item_ordinal != expected_ordinal
        ):
            raise BossCampaignRestartRuntimeError(
                "BOSS_RESTART_RESUME_EVIDENCE_INVALID"
            )
        batch_id = _resumed_batch_id(replacement_run_id)
        opened = coordinator.open_transferred_resumed_batch(
            session,
            batch_id=batch_id,
            replacement_run_id=replacement_run_id,
            now=now,
            policy=policy,
        )
        claimed = coordinator.claim_next_item(
            opened,
            usage=BatchUsage(),
            now=now,
            lease_seconds=BOSS_BATCH_LEASE_SECONDS,
        )
        if (
            claimed.status is not ItemStatus.CLAIMED
            or claimed.run_id != replacement_run_id
            or claimed.item_key != resume.item_keys[0]
            or claimed.ordinal != expected_ordinal
            or claimed.lease_expires_at is None
        ):
            raise BossCampaignRestartRuntimeError("BOSS_RESTART_CLAIM_INVALID")
        return BossCampaignRestartOutcome(
            campaign_id=campaign_id,
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
    except BossCampaignRestartRuntimeError:
        raise
    except (BatchCoordinatorError, CampaignStoreError) as exc:
        raise BossCampaignRestartRuntimeError(
            "BOSS_RESTART_RESUME_BLOCKED"
        ) from exc
    except Exception as exc:
        raise BossCampaignRestartRuntimeError("BOSS_RESTART_FAILED") from exc
    finally:
        prepared.close()


def resume_finished_boss_batch_after_restart(
    runner: AgentRunner,
    *,
    campaign_id: str,
    replacement_run_id: str,
    now: datetime,
) -> BossCampaignRestartOutcome:
    """Transfer the retained one-call identity batch to a fresh run."""

    return _resume_finished_boss_batch_after_restart(
        runner,
        campaign_id=campaign_id,
        replacement_run_id=replacement_run_id,
        now=now,
        task=BOSS_RESTART_TASK,
        policy=BOSS_BATCH_POLICY,
        semantic=False,
    )


def resume_finished_boss_semantic_batch_after_restart(
    runner: AgentRunner,
    *,
    campaign_id: str,
    replacement_run_id: str,
    now: datetime,
) -> BossCampaignRestartOutcome:
    """Transfer one successfully committed semantic batch to a fresh run."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.config.policy.max_side_effects != 0
        or runner.config.policy.max_model_turns
        < BOSS_SEMANTIC_BATCH_POLICY.max_provider_turns
        or runner.config.policy.max_tool_calls
        < BOSS_SEMANTIC_BATCH_POLICY.max_tool_calls
    ):
        raise BossCampaignRestartRuntimeError(
            "BOSS_RESTART_SEMANTIC_POLICY_INVALID"
        )
    return _resume_finished_boss_batch_after_restart(
        runner,
        campaign_id=campaign_id,
        replacement_run_id=replacement_run_id,
        now=now,
        task=BOSS_SEMANTIC_RESTART_TASK,
        policy=BOSS_SEMANTIC_BATCH_POLICY,
        semantic=True,
    )


__all__ = [
    "BOSS_RESTART_TASK",
    "BOSS_SEMANTIC_RESTART_TASK",
    "BossCampaignRestartOutcome",
    "BossCampaignRestartRuntimeError",
    "resume_finished_boss_batch_after_restart",
    "resume_finished_boss_semantic_batch_after_restart",
]
