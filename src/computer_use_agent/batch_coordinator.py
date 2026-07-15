"""Durable coordination around one bounded campaign batch.

This is intentionally not a worker: it never invokes a provider, MCP tool, or
desktop action.  A future worker supplies durable item transitions and measured
usage between ``open_batch`` and ``finish_batch``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .batching import BatchPlan, BatchPolicy, BatchUsage, batch_stop_reason, plan_batch
from .campaign import BatchStatus, BatchTransition, CampaignStore


class BatchCoordinatorError(RuntimeError):
    """Fixed control-state error without application content."""


class BatchCompletionReason(str, Enum):
    PLAN_COMPLETE = "PLAN_COMPLETE"


@dataclass(frozen=True)
class BatchSession:
    campaign_id: str
    batch_id: str
    run_id: str
    policy: BatchPolicy
    plan: BatchPlan


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
    "BatchCoordinator",
    "BatchCoordinatorError",
    "BatchSession",
]
