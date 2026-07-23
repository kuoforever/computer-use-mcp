"""Start one bounded BOSS read-only batch from durable discovery state.

This module is the first worker-side connection after identity discovery.  It
does not call a provider or desktop port, accept an item selector, navigate the
application, or advance an item beyond ``CLAIMED``.  It validates the complete
current BOSS discovery contract, opens one fixed-policy batch through the
existing :class:`BatchCoordinator`, and claims only the coordinator-selected
first item under a bounded lease.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from .batch_coordinator import BatchCoordinator, BatchCoordinatorError, BatchSession
from .batching import BatchPlan, BatchPolicy, BatchUsage
from .boss_campaign_discovery import (
    BOSS_CAMPAIGN_KIND,
    BossCampaignDiscoveryError,
    inspect_boss_discovery_campaign,
)
from .campaign import (
    CampaignHeartbeat,
    CampaignStatus,
    CampaignStoreError,
    ItemStatus,
    campaign_dir,
)
from .config import READ_ONLY_MODE
from .runner import AgentRunner
from .trace import RunRecorder


BOSS_BATCH_TASK = "Start one fixed BOSS read-only batch from durable discovery"
BOSS_BATCH_POLICY = BatchPolicy(max_items=20, max_tool_calls=1)
BOSS_BATCH_LEASE_SECONDS = 5 * 60
MIN_BOSS_BATCH_DISCOVERY_PASSES = 2


class BossCampaignBatchRuntimeError(RuntimeError):
    """Fixed failure from the bounded BOSS batch-start boundary."""


@dataclass(frozen=True)
class BossCampaignBatchStartOutcome:
    """Durable first-batch ownership without application execution."""

    campaign_id: str
    run_id: str
    batch_id: str
    discovered_count: int
    discovery_pass_count: int
    planned_item_count: int
    claimed_item_ordinal: int
    lease_expires_at: str


def _require_now(now: datetime) -> datetime:
    if (
        not isinstance(now, datetime)
        or now.tzinfo is None
        or now.utcoffset() is None
        or now.microsecond != 0
    ):
        raise BossCampaignBatchRuntimeError("BOSS_BATCH_TIME_INVALID")
    return now


def _batch_id(run_id: str) -> str:
    suffix = sha256(run_id.encode("utf-8", "strict")).hexdigest()[:16]
    return f"boss_batch_{suffix}"


def start_boss_read_only_batch(
    runner: AgentRunner,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> BossCampaignBatchStartOutcome:
    """Open and claim only the first coordinator-selected BOSS batch item."""

    if (
        not isinstance(runner, AgentRunner)
        or runner.ports is not None
        or not isinstance(campaign_id, str)
        or not campaign_id
        or not isinstance(run_id, str)
        or not run_id
    ):
        raise BossCampaignBatchRuntimeError("BOSS_BATCH_INPUT_INVALID")
    timestamp = _require_now(now)
    if runner.config.policy.mode != READ_ONLY_MODE:
        raise BossCampaignBatchRuntimeError("BOSS_BATCH_READ_ONLY_REQUIRED")

    try:
        prepared = runner.prepare(BOSS_BATCH_TASK, run_id=run_id)
    except (OSError, ValueError) as exc:
        raise BossCampaignBatchRuntimeError("BOSS_BATCH_PREPARE_FAILED") from exc
    recorder = RunRecorder(runner.config.state_dir, prepared.state.run_id)
    try:
        if recorder.checkpoint_path.exists() or recorder.trace_path.exists():
            raise BossCampaignBatchRuntimeError("BOSS_BATCH_RUN_EXISTS")
        store = prepared.campaign_store(runner.config.state_dir)
        inspected = inspect_boss_discovery_campaign(
            store,
            campaign_id=campaign_id,
            observed_at=timestamp.isoformat(timespec="seconds"),
        )
        manifest = store.read_manifest(campaign_id)
        projection = store.read_ledger(campaign_id)
        passes = store.read_discovery_passes(campaign_id)
        batches = store.read_batches(campaign_id)
        heartbeat = store.read_heartbeat(campaign_id)
        directory = campaign_dir(store.state_dir, campaign_id)
        ordered = sorted(projection.items.values(), key=lambda item: item.ordinal)
        if (
            manifest.kind != BOSS_CAMPAIGN_KIND
            or manifest.status is not CampaignStatus.RUNNING
            or inspected.pass_count < MIN_BOSS_BATCH_DISCOVERY_PASSES
            or inspected.discovered_count == 0
            or passes.total_new_count != inspected.discovered_count
            or [item.ordinal for item in ordered]
            != list(range(1, inspected.discovered_count + 1))
            or any(
                item.status is not ItemStatus.DISCOVERED
                or not item.item_key.startswith("boss:job:")
                for item in ordered
            )
            or batches.transitions
            or heartbeat is not None
            or (directory / "handoff.json").exists()
        ):
            raise BossCampaignBatchRuntimeError("BOSS_BATCH_STATE_INVALID")

        heartbeat_record = CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=run_id,
            started_at=timestamp.isoformat(timespec="seconds"),
            heartbeat_at=timestamp.isoformat(timespec="seconds"),
            fresh_until=(
                timestamp + timedelta(seconds=BOSS_BATCH_LEASE_SECONDS)
            ).isoformat(timespec="seconds"),
        )
        store.write_heartbeat(campaign_id, heartbeat_record)
        coordinator = BatchCoordinator(store)
        batch_id = _batch_id(run_id)
        opened = coordinator.open_batch(
            campaign_id=campaign_id,
            batch_id=batch_id,
            run_id=run_id,
            policy=BOSS_BATCH_POLICY,
        )
        if not isinstance(opened, BatchSession):
            if isinstance(opened, BatchPlan):
                if opened.stop_reason is None:
                    raise BossCampaignBatchRuntimeError("BOSS_BATCH_OPEN_INVALID")
                raise BossCampaignBatchRuntimeError(
                    f"BOSS_BATCH_OPEN_BLOCKED_{opened.stop_reason.value}"
                )
            raise BossCampaignBatchRuntimeError("BOSS_BATCH_OPEN_INVALID")
        claimed = coordinator.claim_next_item(
            opened,
            usage=BatchUsage(),
            now=timestamp,
            lease_seconds=BOSS_BATCH_LEASE_SECONDS,
        )
        if (
            claimed.status is not ItemStatus.CLAIMED
            or claimed.run_id != run_id
            or claimed.item_key != opened.plan.item_keys[0]
            or claimed.ordinal != 1
            or claimed.lease_expires_at is None
        ):
            raise BossCampaignBatchRuntimeError("BOSS_BATCH_CLAIM_INVALID")
        return BossCampaignBatchStartOutcome(
            campaign_id=campaign_id,
            run_id=run_id,
            batch_id=batch_id,
            discovered_count=inspected.discovered_count,
            discovery_pass_count=inspected.pass_count,
            planned_item_count=len(opened.plan.item_keys),
            claimed_item_ordinal=claimed.ordinal,
            lease_expires_at=claimed.lease_expires_at,
        )
    except BossCampaignBatchRuntimeError:
        raise
    except (BatchCoordinatorError, BossCampaignDiscoveryError, CampaignStoreError) as exc:
        raise BossCampaignBatchRuntimeError("BOSS_BATCH_STATE_INVALID") from exc
    finally:
        prepared.close()


__all__ = [
    "BOSS_BATCH_LEASE_SECONDS",
    "BOSS_BATCH_POLICY",
    "BOSS_BATCH_TASK",
    "MIN_BOSS_BATCH_DISCOVERY_PASSES",
    "BossCampaignBatchRuntimeError",
    "BossCampaignBatchStartOutcome",
    "start_boss_read_only_batch",
]
