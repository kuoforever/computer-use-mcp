"""Durable coordination around one bounded campaign batch.

This is intentionally not a worker: it never invokes a provider, MCP tool, or
desktop action.  A future worker supplies durable item transitions and measured
usage between ``open_batch`` and ``finish_batch``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .batching import (
    BatchPlan,
    BatchPolicy,
    BatchStopReason,
    BatchUsage,
    batch_stop_reason,
    plan_batch,
)
from .campaign import (
    MAX_ITEM_LEASE_SECONDS,
    BatchStatus,
    BatchTransition,
    CampaignProjection,
    CampaignStatus,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from .campaign_resume_planning import CampaignResumePlan, plan_campaign_resume
from .heartbeat_inspection import (
    HeartbeatFreshness,
    HeartbeatInspectionError,
    inspect_heartbeat,
)


class BatchCoordinatorError(RuntimeError):
    """Fixed control-state error without application content."""


class BatchCompletionReason(str, Enum):
    PLAN_COMPLETE = "PLAN_COMPLETE"


class BatchContinuationState(str, Enum):
    READY = "READY"
    CAMPAIGN_NOT_RUNNING = "CAMPAIGN_NOT_RUNNING"
    BATCH_NOT_ACTIVE = "BATCH_NOT_ACTIVE"
    BATCH_OWNER_MISMATCH = "BATCH_OWNER_MISMATCH"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_OWNER_MISMATCH = "HEARTBEAT_OWNER_MISMATCH"
    ITEMS_IN_FLIGHT = "ITEMS_IN_FLIGHT"
    PLAN_DRIFT = "PLAN_DRIFT"
    USAGE_MISMATCH = "USAGE_MISMATCH"
    COMMITTED_PREFIX_REQUIRED = "COMMITTED_PREFIX_REQUIRED"
    LIMIT_REACHED = "LIMIT_REACHED"
    PLAN_COMPLETE = "PLAN_COMPLETE"


class BatchHandoffState(str, Enum):
    READY = "READY"
    CAMPAIGN_NOT_RUNNING = "CAMPAIGN_NOT_RUNNING"
    BATCH_STILL_ACTIVE = "BATCH_STILL_ACTIVE"
    FINISH_RECORD_MISSING = "FINISH_RECORD_MISSING"
    BATCH_OWNER_MISMATCH = "BATCH_OWNER_MISMATCH"
    HEARTBEAT_MISSING = "HEARTBEAT_MISSING"
    HEARTBEAT_STALE = "HEARTBEAT_STALE"
    HEARTBEAT_OWNER_MISMATCH = "HEARTBEAT_OWNER_MISMATCH"
    ITEMS_IN_FLIGHT = "ITEMS_IN_FLIGHT"
    PLAN_DRIFT = "PLAN_DRIFT"
    USAGE_MISMATCH = "USAGE_MISMATCH"
    FINISH_RECORD_MISMATCH = "FINISH_RECORD_MISMATCH"
    FINISH_REASON_MISMATCH = "FINISH_REASON_MISMATCH"


@dataclass(frozen=True)
class BatchSession:
    campaign_id: str
    batch_id: str
    run_id: str
    policy: BatchPolicy
    plan: BatchPlan


def _committed_plan_prefix(
    projection: CampaignProjection,
    session: BatchSession,
) -> tuple[int, set[str]]:
    completed_items = 0
    for item_key in session.plan.item_keys:
        item = projection.items.get(item_key)
        if (
            item is not None
            and item.status is ItemStatus.COMMITTED
            and item.run_id == session.run_id
        ):
            completed_items += 1
        else:
            break
    committed_by_run = {
        item.item_key
        for item in projection.items.values()
        if item.status is ItemStatus.COMMITTED and item.run_id == session.run_id
    }
    return completed_items, committed_by_run


@dataclass(frozen=True)
class BatchContinuationPreflight:
    state: BatchContinuationState
    campaign_id: str
    batch_id: str
    run_id: str
    completed_items: int
    next_item_key: str | None
    next_item_ordinal: int | None
    stop_reason: BatchStopReason | None
    required_claim: str

    @property
    def ready(self) -> bool:
        return self.state is BatchContinuationState.READY


@dataclass(frozen=True)
class BatchHandoffPreflight:
    state: BatchHandoffState
    campaign_id: str
    batch_id: str
    run_id: str
    completed_items: int
    next_item_ordinal: int
    stop_code: str | None
    required_handoff: str

    @property
    def ready(self) -> bool:
        return self.state is BatchHandoffState.READY


class BatchCoordinator:
    """Run-lock-bound opener/closer for one persisted batch lifecycle."""

    def __init__(self, store: CampaignStore) -> None:
        if not isinstance(store, CampaignStore):
            raise ValueError("store must be a CampaignStore")
        self.store = store

    def open_batch(
        self, *, campaign_id: str, batch_id: str, run_id: str, policy: BatchPolicy
    ) -> BatchSession | BatchPlan:
        """Persist STARTED only for a nonempty plan and no active prior batch."""

        if not isinstance(policy, BatchPolicy):
            raise BatchCoordinatorError("BATCH_POLICY_INVALID")
        self.store.read_manifest(campaign_id)
        batches = self.store.read_batches(campaign_id)
        if batches.active is not None:
            raise BatchCoordinatorError("BATCH_ALREADY_ACTIVE")
        plan = plan_batch(self.store.read_ledger(campaign_id), policy, BatchUsage())
        if plan.stop_reason is not None:
            return plan
        self.store.append_batch(
            campaign_id,
            BatchTransition(
                sequence=1,
                batch_id=batch_id,
                run_id=run_id,
                status=BatchStatus.STARTED,
                at=_utc_now(),
            ),
        )
        return BatchSession(campaign_id, batch_id, run_id, policy, plan)

    def open_resumed_batch(
        self,
        *,
        campaign_id: str,
        batch_id: str,
        run_id: str,
        now: datetime,
        policy: BatchPolicy,
    ) -> BatchSession | CampaignResumePlan:
        """Persist STARTED only for an exact nonempty READY resume plan."""

        if not isinstance(policy, BatchPolicy):
            raise BatchCoordinatorError("BATCH_POLICY_INVALID")
        resume = plan_campaign_resume(
            self.store,
            campaign_id=campaign_id,
            run_id=run_id,
            now=now,
            policy=policy,
        )
        if not resume.has_nonempty_plan:
            return resume
        plan = resume.batch
        if plan is None:
            raise BatchCoordinatorError("BATCH_PLAN_INVALID")
        self.store.append_batch(
            campaign_id,
            BatchTransition(
                sequence=1,
                batch_id=batch_id,
                run_id=run_id,
                status=BatchStatus.STARTED,
                at=now.isoformat(timespec="seconds"),
            ),
        )
        return BatchSession(campaign_id, batch_id, run_id, policy, plan)

    def claim_first_item(
        self,
        session: BatchSession,
        *,
        now: datetime,
        lease_seconds: int,
    ) -> ItemTransition:
        """Claim the exact first planned item without performing its operation."""

        if not isinstance(session, BatchSession):
            raise BatchCoordinatorError("BATCH_SESSION_INVALID")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise BatchCoordinatorError("BATCH_CLOCK_INVALID")
        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not 0 < lease_seconds <= MAX_ITEM_LEASE_SECONDS
        ):
            raise BatchCoordinatorError("BATCH_LEASE_INVALID")

        manifest = self.store.read_manifest(session.campaign_id)
        if manifest.status is not CampaignStatus.RUNNING:
            raise BatchCoordinatorError("BATCH_CAMPAIGN_NOT_RUNNING")
        active = self.store.read_batches(session.campaign_id).active
        if active is None or (active.batch_id, active.run_id) != (
            session.batch_id,
            session.run_id,
        ):
            raise BatchCoordinatorError("BATCH_NOT_ACTIVE")
        try:
            heartbeat = inspect_heartbeat(
                self.store.read_heartbeat(session.campaign_id), now=now
            )
        except HeartbeatInspectionError as exc:
            raise BatchCoordinatorError("BATCH_HEARTBEAT_INVALID") from exc
        if heartbeat.run_id != session.run_id:
            raise BatchCoordinatorError("BATCH_HEARTBEAT_OWNER_MISMATCH")
        if not heartbeat.is_fresh:
            raise BatchCoordinatorError("BATCH_HEARTBEAT_NOT_FRESH")

        projection = self.store.read_ledger(session.campaign_id)
        if any(item.status is ItemStatus.CLAIMED for item in projection.items.values()):
            raise BatchCoordinatorError("BATCH_ITEM_CLAIM_ACTIVE")
        current_plan = plan_batch(projection, session.policy, BatchUsage())
        if current_plan != session.plan or not current_plan.item_keys:
            raise BatchCoordinatorError("BATCH_PLAN_DRIFT")
        selected = projection.items.get(current_plan.item_keys[0])
        if selected is None or selected.status not in {
            ItemStatus.DISCOVERED,
            ItemStatus.RETRYABLE,
        }:
            raise BatchCoordinatorError("BATCH_PLAN_INVALID")
        if datetime.fromisoformat(selected.at) > now:
            raise BatchCoordinatorError("BATCH_CLOCK_INVALID")

        claimed_at = now.isoformat(timespec="seconds")
        lease_expires_at = (now + timedelta(seconds=lease_seconds)).isoformat(
            timespec="seconds"
        )
        updated = self.store.append(
            session.campaign_id,
            ItemTransition(
                sequence=1,
                ordinal=selected.ordinal,
                item_key=selected.item_key,
                status=ItemStatus.CLAIMED,
                attempt=selected.attempt + 1,
                at=claimed_at,
                run_id=session.run_id,
                lease_expires_at=lease_expires_at,
                boundary="claim",
            ),
        )
        return updated.items[selected.item_key]

    def inspect_continuation(
        self,
        session: BatchSession,
        *,
        usage: BatchUsage,
        now: datetime,
    ) -> BatchContinuationPreflight:
        """Inspect the exact next planned item after a committed prefix."""

        if not isinstance(session, BatchSession) or not isinstance(usage, BatchUsage):
            raise BatchCoordinatorError("BATCH_CONTINUATION_INVALID")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise BatchCoordinatorError("BATCH_CLOCK_INVALID")

        manifest = self.store.read_manifest(session.campaign_id)
        active = self.store.read_batches(session.campaign_id).active
        projection = self.store.read_ledger(session.campaign_id)
        try:
            heartbeat = inspect_heartbeat(
                self.store.read_heartbeat(session.campaign_id), now=now
            )
        except HeartbeatInspectionError as exc:
            raise BatchCoordinatorError("BATCH_HEARTBEAT_INVALID") from exc

        planned = session.plan.item_keys
        completed_items, committed_by_run = _committed_plan_prefix(projection, session)
        expected_committed = set(planned[:completed_items])
        in_flight = any(
            item.status in {ItemStatus.CLAIMED, ItemStatus.OBSERVED, ItemStatus.EXTRACTED}
            for item in projection.items.values()
        )
        reason = batch_stop_reason(session.policy, usage)
        next_item_key: str | None = None
        next_item_ordinal: int | None = None
        stop_reason: BatchStopReason | None = None

        if manifest.status is not CampaignStatus.RUNNING:
            state = BatchContinuationState.CAMPAIGN_NOT_RUNNING
        elif active is None:
            state = BatchContinuationState.BATCH_NOT_ACTIVE
        elif (active.batch_id, active.run_id) != (session.batch_id, session.run_id):
            state = BatchContinuationState.BATCH_OWNER_MISMATCH
        elif heartbeat.freshness is HeartbeatFreshness.MISSING:
            state = BatchContinuationState.HEARTBEAT_MISSING
        elif heartbeat.run_id != session.run_id:
            state = BatchContinuationState.HEARTBEAT_OWNER_MISMATCH
        elif heartbeat.freshness is HeartbeatFreshness.STALE:
            state = BatchContinuationState.HEARTBEAT_STALE
        elif in_flight:
            state = BatchContinuationState.ITEMS_IN_FLIGHT
        elif not planned or session.plan.stop_reason is not None:
            state = BatchContinuationState.PLAN_DRIFT
        elif committed_by_run != expected_committed:
            state = BatchContinuationState.PLAN_DRIFT
        elif usage.items_completed != completed_items:
            state = BatchContinuationState.USAGE_MISMATCH
        elif completed_items == 0:
            state = BatchContinuationState.COMMITTED_PREFIX_REQUIRED
        elif reason is not None:
            state = BatchContinuationState.LIMIT_REACHED
            stop_reason = reason
        elif completed_items == len(planned):
            remaining = plan_batch(projection, session.policy, usage)
            if remaining.stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS:
                state = BatchContinuationState.PLAN_COMPLETE
            else:
                state = BatchContinuationState.PLAN_DRIFT
        else:
            expected_key = planned[completed_items]
            selected = projection.items.get(expected_key)
            current_plan = plan_batch(projection, session.policy, usage)
            if (
                selected is None
                or selected.status not in {ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
                or not current_plan.item_keys
                or current_plan.item_keys[0] != expected_key
            ):
                state = BatchContinuationState.PLAN_DRIFT
            else:
                state = BatchContinuationState.READY
                next_item_key = selected.item_key
                next_item_ordinal = selected.ordinal
        return BatchContinuationPreflight(
            state=state,
            campaign_id=session.campaign_id,
            batch_id=session.batch_id,
            run_id=session.run_id,
            completed_items=completed_items,
            next_item_key=next_item_key,
            next_item_ordinal=next_item_ordinal,
            stop_reason=stop_reason,
            required_claim="claim_exact_next_planned_item",
        )

    def claim_next_item(
        self,
        session: BatchSession,
        *,
        usage: BatchUsage,
        now: datetime,
        lease_seconds: int,
    ) -> ItemTransition:
        """Claim only the exact next item from a READY continuation preflight."""

        if (
            isinstance(lease_seconds, bool)
            or not isinstance(lease_seconds, int)
            or not 0 < lease_seconds <= MAX_ITEM_LEASE_SECONDS
        ):
            raise BatchCoordinatorError("BATCH_LEASE_INVALID")
        preflight = self.inspect_continuation(session, usage=usage, now=now)
        if not preflight.ready:
            raise BatchCoordinatorError(
                f"BATCH_CONTINUATION_BLOCKED_{preflight.state.value}"
            )
        if preflight.next_item_key is None or preflight.next_item_ordinal is None:
            raise BatchCoordinatorError("BATCH_CONTINUATION_STATE_DRIFT")

        projection = self.store.read_ledger(session.campaign_id)
        selected = projection.items.get(preflight.next_item_key)
        if (
            selected is None
            or selected.ordinal != preflight.next_item_ordinal
            or selected.status not in {ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
        ):
            raise BatchCoordinatorError("BATCH_CONTINUATION_STATE_DRIFT")
        if datetime.fromisoformat(selected.at) > now:
            raise BatchCoordinatorError("BATCH_CLOCK_INVALID")

        claimed_at = now.isoformat(timespec="seconds")
        lease_expires_at = (now + timedelta(seconds=lease_seconds)).isoformat(
            timespec="seconds"
        )
        updated = self.store.append(
            session.campaign_id,
            ItemTransition(
                sequence=1,
                ordinal=selected.ordinal,
                item_key=selected.item_key,
                status=ItemStatus.CLAIMED,
                attempt=selected.attempt + 1,
                at=claimed_at,
                run_id=session.run_id,
                lease_expires_at=lease_expires_at,
                boundary="claim",
            ),
        )
        return updated.items[selected.item_key]

    def finish_continued_batch(
        self,
        session: BatchSession,
        *,
        usage: BatchUsage,
        now: datetime,
    ) -> str:
        """Finish only at a continuation-validated limit or completed plan."""

        preflight = self.inspect_continuation(session, usage=usage, now=now)
        if preflight.state is BatchContinuationState.LIMIT_REACHED:
            if preflight.stop_reason is None:
                raise BatchCoordinatorError("BATCH_CONTINUATION_STATE_DRIFT")
            code = preflight.stop_reason.value
        elif preflight.state is BatchContinuationState.PLAN_COMPLETE:
            if preflight.stop_reason is not None:
                raise BatchCoordinatorError("BATCH_CONTINUATION_STATE_DRIFT")
            code = BatchCompletionReason.PLAN_COMPLETE.value
        else:
            raise BatchCoordinatorError(
                f"BATCH_FINISH_BLOCKED_{preflight.state.value}"
            )

        self.store.append_batch(
            session.campaign_id,
            BatchTransition(
                sequence=1,
                batch_id=session.batch_id,
                run_id=session.run_id,
                status=BatchStatus.FINISHED,
                at=now.isoformat(timespec="seconds"),
                stop_code=code,
                items_completed=usage.items_completed,
                elapsed_seconds=usage.elapsed_seconds,
                provider_turns=usage.provider_turns,
                tool_calls=usage.tool_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                screenshots=usage.screenshots,
                ocr_regions=usage.ocr_regions,
                consecutive_failures=usage.consecutive_failures,
            ),
        )
        return code

    def inspect_finished_handoff(
        self,
        session: BatchSession,
        *,
        usage: BatchUsage,
        now: datetime,
    ) -> BatchHandoffPreflight:
        """Inspect whether one exact finished batch is ready for handoff writing."""

        if not isinstance(session, BatchSession) or not isinstance(usage, BatchUsage):
            raise BatchCoordinatorError("BATCH_HANDOFF_PREFLIGHT_INVALID")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise BatchCoordinatorError("BATCH_CLOCK_INVALID")

        manifest = self.store.read_manifest(session.campaign_id)
        batches = self.store.read_batches(session.campaign_id)
        projection = self.store.read_ledger(session.campaign_id)
        try:
            heartbeat = inspect_heartbeat(
                self.store.read_heartbeat(session.campaign_id), now=now
            )
        except HeartbeatInspectionError as exc:
            raise BatchCoordinatorError("BATCH_HANDOFF_HEARTBEAT_INVALID") from exc

        finished = batches.transitions[-1] if batches.transitions else None
        completed_items, committed_by_run = _committed_plan_prefix(projection, session)
        planned = session.plan.item_keys
        expected_committed = set(planned[:completed_items])
        in_flight = any(
            item.status in {ItemStatus.CLAIMED, ItemStatus.OBSERVED, ItemStatus.EXTRACTED}
            for item in projection.items.values()
        )
        persisted_usage = None
        if finished is not None:
            persisted_usage = (
                finished.items_completed,
                finished.elapsed_seconds,
                finished.provider_turns,
                finished.tool_calls,
                finished.input_tokens,
                finished.output_tokens,
                finished.screenshots,
                finished.ocr_regions,
                finished.consecutive_failures,
            )
        measured_usage = (
            usage.items_completed,
            usage.elapsed_seconds,
            usage.provider_turns,
            usage.tool_calls,
            usage.input_tokens,
            usage.output_tokens,
            usage.screenshots,
            usage.ocr_regions,
            usage.consecutive_failures,
        )
        reason = batch_stop_reason(session.policy, usage)
        expected_code: str | None = None
        if reason is not None:
            expected_code = reason.value
        elif completed_items == len(planned):
            remaining = plan_batch(projection, session.policy, usage)
            if remaining.stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS:
                expected_code = BatchCompletionReason.PLAN_COMPLETE.value

        if manifest.status is not CampaignStatus.RUNNING:
            state = BatchHandoffState.CAMPAIGN_NOT_RUNNING
        elif batches.active is not None:
            state = BatchHandoffState.BATCH_STILL_ACTIVE
        elif finished is None or finished.status is not BatchStatus.FINISHED:
            state = BatchHandoffState.FINISH_RECORD_MISSING
        elif (finished.batch_id, finished.run_id) != (session.batch_id, session.run_id):
            state = BatchHandoffState.BATCH_OWNER_MISMATCH
        elif heartbeat.freshness is HeartbeatFreshness.MISSING:
            state = BatchHandoffState.HEARTBEAT_MISSING
        elif heartbeat.run_id != session.run_id:
            state = BatchHandoffState.HEARTBEAT_OWNER_MISMATCH
        elif heartbeat.freshness is HeartbeatFreshness.STALE:
            state = BatchHandoffState.HEARTBEAT_STALE
        elif in_flight:
            state = BatchHandoffState.ITEMS_IN_FLIGHT
        elif not planned or session.plan.stop_reason is not None:
            state = BatchHandoffState.PLAN_DRIFT
        elif committed_by_run != expected_committed:
            state = BatchHandoffState.PLAN_DRIFT
        elif usage.items_completed != completed_items:
            state = BatchHandoffState.USAGE_MISMATCH
        elif persisted_usage != measured_usage:
            state = BatchHandoffState.FINISH_RECORD_MISMATCH
        elif expected_code is None or finished.stop_code != expected_code:
            state = BatchHandoffState.FINISH_REASON_MISMATCH
        else:
            state = BatchHandoffState.READY
        return BatchHandoffPreflight(
            state=state,
            campaign_id=session.campaign_id,
            batch_id=session.batch_id,
            run_id=session.run_id,
            completed_items=completed_items,
            next_item_ordinal=projection.next_ordinal,
            stop_code=None if finished is None else finished.stop_code,
            required_handoff="write_current_campaign_handoff",
        )

    def finish_batch(self, session: BatchSession, usage: BatchUsage) -> str:
        """Derive and persist a terminal boundary from measured bounded usage."""

        if not isinstance(session, BatchSession) or not isinstance(usage, BatchUsage):
            raise BatchCoordinatorError("BATCH_INVALID")
        active = self.store.read_batches(session.campaign_id).active
        if active is None or (active.batch_id, active.run_id) != (session.batch_id, session.run_id):
            raise BatchCoordinatorError("BATCH_NOT_ACTIVE")
        if usage.items_completed > len(session.plan.item_keys):
            raise BatchCoordinatorError("BATCH_USAGE_INVALID")
        reason = batch_stop_reason(session.policy, usage)
        if reason is None:
            if usage.items_completed != len(session.plan.item_keys):
                raise BatchCoordinatorError("BATCH_BOUNDARY_REQUIRED")
            code = BatchCompletionReason.PLAN_COMPLETE.value
        else:
            code = reason.value
        self.store.append_batch(
            session.campaign_id,
            BatchTransition(
                sequence=1,
                batch_id=session.batch_id,
                run_id=session.run_id,
                status=BatchStatus.FINISHED,
                at=_utc_now(),
                stop_code=code,
                items_completed=usage.items_completed,
                elapsed_seconds=usage.elapsed_seconds,
                provider_turns=usage.provider_turns,
                tool_calls=usage.tool_calls,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                screenshots=usage.screenshots,
                ocr_regions=usage.ocr_regions,
                consecutive_failures=usage.consecutive_failures,
            ),
        )
        return code


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


__all__ = [
    "BatchCompletionReason",
    "BatchContinuationPreflight",
    "BatchContinuationState",
    "BatchCoordinator",
    "BatchCoordinatorError",
    "BatchHandoffPreflight",
    "BatchHandoffState",
    "BatchSession",
]
