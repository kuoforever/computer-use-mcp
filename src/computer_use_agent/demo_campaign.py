"""Deterministic multi-item demo campaign with explicit fault injection.

This module exists to demonstrate one property that unit tests state but never
show end to end: a campaign killed mid-flight resumes from durable state without
repeating a committed item and without replaying a side effect whose outcome is
unknown.

It deliberately adds no new state machine. Item lifecycle, lease ownership, and
the committed prefix all come from :class:`~computer_use_agent.campaign.CampaignStore`
and :class:`~computer_use_agent.batch_coordinator.BatchCoordinator`. What is new
here is only:

* explicit, named fault points instead of a random kill,
* a durable two-phase fake side-effect sink that can express "this may or may
  not have happened",
* a loop over the coordinator's existing ``*_next_*`` boundaries.

It is also not a second desktop execution path. The side effect is a fake sink;
real desktop work continues to go through the Agent Runner and the project's
stdio MCP server, unchanged.

Why the sink is two-phase
-------------------------
A sink we can always query cannot model uncertainty: after a crash we would
simply ask it what happened, and no case would ever be genuinely unknown. Real
GUI side effects are not queryable that way. So the sink records an intent
(``pending``) before performing the effect and a result (``accepted``) after,
each fsynced. A crash between the two leaves a ``pending`` record with no
``accepted`` record, which is exactly the state that must never be replayed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Callable, Protocol

from .batch_coordinator import BatchCoordinator, BatchCoordinatorError, BatchSession
from .batching import BatchPolicy, BatchUsage
from .campaign import (
    BatchStatus,
    BatchTransition,
    CampaignHeartbeat,
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from .tool_registry import reviewed_registry_digest

DEMO_CAMPAIGN_KIND = "demo_reliability"
DEMO_BATCH_ID = "demo-batch"
DEMO_ITEM_LEASE_SECONDS = 300
MAX_DEMO_ITEMS = 1000


class DemoCampaignError(RuntimeError):
    """Raised when demo input or durable state is not bounded and consistent."""


class DemoFaultPoint(str, Enum):
    """Named, repeatable places a demo process may be killed.

    A random kill proves nothing reproducible. Each of these sits on one side of
    a specific durability boundary, so the expected recovery behavior is a fixed
    claim rather than a lucky outcome.
    """

    #: Lease exists, no work done: recovery re-claims the item.
    AFTER_ITEM_CLAIM = "after_item_claim"
    #: Sink intent is durable, result is not: outcome unknown, never replayed.
    AFTER_DISPATCH_INTENT = "after_dispatch_intent"
    #: Sink result is durable, COMMITTED is not: reconcile from the exact
    #: receipt without dispatching again.
    AFTER_SIDE_EFFECT_COMPLETION = "after_side_effect_completion"
    #: COMMITTED is durable: recovery must skip the item entirely.
    AFTER_ITEM_COMMIT = "after_item_commit"
    #: Every item is durable, the report is not: the report is a projection and
    #: is simply rebuilt.
    BEFORE_FINAL_PROJECTION = "before_final_projection"


class InjectedDemoFault(BaseException):
    """Simulated hard crash.

    This intentionally derives from :class:`BaseException`. A simulated crash
    that ``except Exception`` could swallow would let the driver's own error
    handling run, which is exactly the code a real process kill skips.
    """

    def __init__(self, point: DemoFaultPoint, ordinal: int) -> None:
        super().__init__(f"INJECTED_FAULT_{point.value.upper()}_AT_ITEM_{ordinal}")
        self.point = point
        self.ordinal = ordinal


class FaultInjector(Protocol):
    """Port deciding whether to crash at a named boundary."""

    def check(self, point: DemoFaultPoint, *, ordinal: int) -> None:
        """Raise :class:`InjectedDemoFault` to simulate a crash, or return."""


class NoFaultInjector:
    """Production default. Never crashes."""

    def check(self, point: DemoFaultPoint, *, ordinal: int) -> None:
        return None


@dataclass
class ScriptedFaultInjector:
    """Crash exactly once, at one named point and one item ordinal."""

    point: DemoFaultPoint
    ordinal: int
    fired: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.point, DemoFaultPoint):
            raise DemoCampaignError("DEMO_FAULT_POINT_INVALID")
        if isinstance(self.ordinal, bool) or not isinstance(self.ordinal, int):
            raise DemoCampaignError("DEMO_FAULT_ORDINAL_INVALID")
        if not 0 < self.ordinal <= MAX_DEMO_ITEMS:
            raise DemoCampaignError("DEMO_FAULT_ORDINAL_INVALID")

    def check(self, point: DemoFaultPoint, *, ordinal: int) -> None:
        if self.fired or point is not self.point or ordinal != self.ordinal:
            return None
        self.fired = True
        raise InjectedDemoFault(point, ordinal)


def fault_injector_from_env(environ: dict[str, str] | None = None) -> FaultInjector:
    """Build an injector from ``CUA_DEMO_FAULT_POINT``/``CUA_DEMO_FAULT_ORDINAL``.

    Absent or empty configuration yields :class:`NoFaultInjector`, so the demo is
    fail-safe by default and a production run cannot inherit a fault by accident.
    """

    source = os.environ if environ is None else environ
    raw_point = (source.get("CUA_DEMO_FAULT_POINT") or "").strip()
    if not raw_point:
        return NoFaultInjector()
    try:
        point = DemoFaultPoint(raw_point)
    except ValueError as exc:
        raise DemoCampaignError("DEMO_FAULT_POINT_INVALID") from exc
    raw_ordinal = (source.get("CUA_DEMO_FAULT_ORDINAL") or "").strip()
    try:
        ordinal = int(raw_ordinal)
    except ValueError as exc:
        raise DemoCampaignError("DEMO_FAULT_ORDINAL_INVALID") from exc
    return ScriptedFaultInjector(point=point, ordinal=ordinal)


class SideEffectOutcome(str, Enum):
    """What the durable sink record says about one idempotency key."""

    NONE = "none"
    #: An intent exists with no result. The effect may or may not have happened.
    PENDING = "pending"
    ACCEPTED = "accepted"


@dataclass(frozen=True)
class SideEffectReceipt:
    """Proof that exactly one side effect was accepted for an idempotency key."""

    idempotency_key: str
    receipt_digest: str


class DurableFakeSideEffectSink:
    """Append-only two-phase fake sink that survives a process restart.

    The duplicate claim is only meaningful if the sink outlives the crash, so
    records are fsynced to a file rather than held in memory. A repeated key is
    recorded as a duplicate *attempt* and rejected; it is never silently
    accepted, because a sink that deduplicates for us would hide the very bug
    this demo exists to expose.
    """

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise DemoCampaignError("DEMO_SINK_PATH_INVALID")
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _records(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        records: list[dict[str, object]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            decoded = json.loads(line)
            if not isinstance(decoded, dict):
                raise DemoCampaignError("DEMO_SINK_RECORD_INVALID")
            records.append(decoded)
        return records

    def _append(self, record: dict[str, object]) -> None:
        line = json.dumps(record, separators=(",", ":"), sort_keys=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _keys_with(self, outcome: str) -> tuple[str, ...]:
        return tuple(
            str(record["idempotency_key"])
            for record in self._records()
            if record.get("outcome") == outcome
        )

    def accepted_keys(self) -> tuple[str, ...]:
        return self._keys_with("accepted")

    def pending_keys(self) -> tuple[str, ...]:
        accepted = set(self.accepted_keys())
        return tuple(key for key in self._keys_with("pending") if key not in accepted)

    def duplicate_attempts(self) -> tuple[str, ...]:
        return self._keys_with("duplicate")

    def outcome_for(self, idempotency_key: str) -> SideEffectOutcome:
        if idempotency_key in self.accepted_keys():
            return SideEffectOutcome.ACCEPTED
        if idempotency_key in self.pending_keys():
            return SideEffectOutcome.PENDING
        return SideEffectOutcome.NONE

    def receipt_for(self, idempotency_key: str) -> SideEffectReceipt | None:
        for record in self._records():
            if (
                record.get("outcome") == "accepted"
                and record.get("idempotency_key") == idempotency_key
            ):
                return SideEffectReceipt(
                    idempotency_key=idempotency_key,
                    receipt_digest=str(record["receipt_digest"]),
                )
        return None

    def dispatch(
        self,
        idempotency_key: str,
        *,
        after_intent: Callable[[], None] | None = None,
    ) -> SideEffectReceipt:
        """Record intent, perform the effect, record the result.

        ``after_intent`` runs between the durable intent and the effect. That is
        the only place a crash produces a genuinely unknown outcome, so it is the
        seam the fault injector uses.
        """

        if not isinstance(idempotency_key, str) or not idempotency_key:
            raise DemoCampaignError("DEMO_SINK_KEY_INVALID")
        if self.outcome_for(idempotency_key) is not SideEffectOutcome.NONE:
            self._append({"idempotency_key": idempotency_key, "outcome": "duplicate"})
            raise DemoCampaignError("DEMO_SINK_DUPLICATE_REJECTED")
        self._append({"idempotency_key": idempotency_key, "outcome": "pending"})
        if after_intent is not None:
            after_intent()
        receipt_digest = sha256(idempotency_key.encode("utf-8")).hexdigest()
        self._append(
            {
                "idempotency_key": idempotency_key,
                "outcome": "accepted",
                "receipt_digest": receipt_digest,
            }
        )
        return SideEffectReceipt(idempotency_key, receipt_digest)


@dataclass(frozen=True)
class DemoItemOutcome:
    """One item's bounded, non-sensitive result."""

    item_key: str
    ordinal: int
    content_digest: str


@dataclass(frozen=True)
class DemoRunOutcome:
    """What one demo process managed to do before it stopped."""

    campaign_id: str
    run_id: str
    committed: tuple[DemoItemOutcome, ...]
    reconciled: tuple[str, ...]
    parked_uncertain: tuple[str, ...]
    skipped_already_committed: tuple[str, ...]


@dataclass(frozen=True)
class DemoCampaignPlan:
    """Fixed synthetic item identities. No business content is stored."""

    item_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.item_keys or len(self.item_keys) > MAX_DEMO_ITEMS:
            raise DemoCampaignError("DEMO_PLAN_INVALID")
        if len(set(self.item_keys)) != len(self.item_keys):
            raise DemoCampaignError("DEMO_PLAN_DUPLICATE_ITEM")


def synthetic_demo_plan(count: int, *, prefix: str = "demo-item") -> DemoCampaignPlan:
    """Build ``count`` stable synthetic item keys."""

    if isinstance(count, bool) or not isinstance(count, int) or not 0 < count <= MAX_DEMO_ITEMS:
        raise DemoCampaignError("DEMO_PLAN_INVALID")
    return DemoCampaignPlan(tuple(f"{prefix}-{index:04d}" for index in range(1, count + 1)))


def idempotency_key(campaign_id: str, item_key: str) -> str:
    """Stable side-effect identity, independent of run, attempt, and process."""

    return sha256(f"{campaign_id}\x1f{item_key}".encode("utf-8")).hexdigest()


def prepare_demo_campaign(
    store: CampaignStore,
    *,
    campaign_id: str,
    run_id: str,
    plan: DemoCampaignPlan,
    now: datetime,
    policy_digest: str,
) -> CampaignManifest:
    """Create the manifest, discover every item, and open the heartbeat lease."""

    timestamp = now.isoformat(timespec="seconds")
    manifest = store.create(
        CampaignManifest(
            campaign_id=campaign_id,
            kind=DEMO_CAMPAIGN_KIND,
            policy_digest=policy_digest,
            schema_digest=reviewed_registry_digest(),
            created_at=timestamp,
            updated_at=timestamp,
        )
    )
    for ordinal, item_key in enumerate(plan.item_keys, start=1):
        store.append(
            campaign_id,
            ItemTransition(
                sequence=1,
                ordinal=ordinal,
                item_key=item_key,
                status=ItemStatus.DISCOVERED,
                attempt=0,
                at=timestamp,
            ),
        )
    store.write_heartbeat(
        campaign_id,
        CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=run_id,
            started_at=timestamp,
            heartbeat_at=timestamp,
            fresh_until=(now + timedelta(seconds=DEMO_ITEM_LEASE_SECONDS)).isoformat(
                timespec="seconds"
            ),
        ),
    )
    return manifest


def _items_with(store: CampaignStore, campaign_id: str, status: ItemStatus) -> tuple[str, ...]:
    projection = store.read_ledger(campaign_id)
    return tuple(
        item_key for item_key, item in projection.items.items() if item.status is status
    )


@dataclass(frozen=True)
class ReconciliationOutcome:
    """How a fresh process classified the previous process's unfinished items."""

    reconciled: tuple[str, ...]
    parked_uncertain: tuple[str, ...]
    released_for_retry: tuple[str, ...]


def reconcile_after_restart(
    store: CampaignStore,
    sink: DurableFakeSideEffectSink,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> ReconciliationOutcome:
    """Classify items a dead process left mid-flight, using sink evidence only.

    Three cases, and only three:

    * ``accepted`` receipt, item not COMMITTED — the effect provably happened.
      Local bookkeeping is behind, so it is caught up from that exact receipt.
      Nothing is dispatched.
    * ``pending`` with no result — the effect may or may not have happened. The
      item becomes UNCERTAIN, which is terminal in the ledger. This is where the
      campaign stops guessing and asks for a human.
    * no record at all — nothing was dispatched, so the item is released for a
      normal retry.
    """

    projection = store.read_ledger(campaign_id)
    timestamp = now.isoformat(timespec="seconds")
    reconciled: list[str] = []
    parked: list[str] = []
    released: list[str] = []

    for item_key, item in projection.items.items():
        if item.status not in {ItemStatus.CLAIMED, ItemStatus.OBSERVED, ItemStatus.EXTRACTED}:
            continue
        key = idempotency_key(campaign_id, item_key)
        outcome = sink.outcome_for(key)
        # Reconciled work is attributed to the run that actually performed it,
        # not to this one. Crediting the recovering run would make it look like
        # it committed an item outside its own batch plan, which the
        # coordinator correctly reads as plan drift.
        owner = item.run_id or run_id

        if outcome is SideEffectOutcome.ACCEPTED:
            receipt = sink.receipt_for(key)
            if receipt is None:  # pragma: no cover - outcome_for already proved it
                raise DemoCampaignError("DEMO_SINK_RECEIPT_MISSING")
            status = item.status
            if status is ItemStatus.CLAIMED:
                store.append(
                    campaign_id,
                    ItemTransition(
                        sequence=1,
                        ordinal=item.ordinal,
                        item_key=item_key,
                        status=ItemStatus.OBSERVED,
                        attempt=item.attempt,
                        at=timestamp,
                        run_id=owner,
                        boundary="reconcile",
                    ),
                )
                status = ItemStatus.OBSERVED
            if status is ItemStatus.OBSERVED:
                store.append(
                    campaign_id,
                    ItemTransition(
                        sequence=1,
                        ordinal=item.ordinal,
                        item_key=item_key,
                        status=ItemStatus.EXTRACTED,
                        attempt=item.attempt,
                        at=timestamp,
                        run_id=owner,
                        boundary="reconcile",
                    ),
                )
            store.append(
                campaign_id,
                ItemTransition(
                    sequence=1,
                    ordinal=item.ordinal,
                    item_key=item_key,
                    status=ItemStatus.COMMITTED,
                    attempt=item.attempt,
                    at=timestamp,
                    run_id=owner,
                    boundary="reconcile",
                    code="RECONCILED_FROM_RECEIPT",
                    content_digest=receipt.receipt_digest,
                ),
            )
            reconciled.append(item_key)
            continue

        if outcome is SideEffectOutcome.PENDING:
            store.append(
                campaign_id,
                ItemTransition(
                    sequence=1,
                    ordinal=item.ordinal,
                    item_key=item_key,
                    status=ItemStatus.UNCERTAIN,
                    attempt=item.attempt,
                    at=timestamp,
                    run_id=owner,
                    boundary="dispatch",
                    code="DISPATCH_OUTCOME_UNKNOWN",
                ),
            )
            parked.append(item_key)
            continue

        if item.status is ItemStatus.CLAIMED:
            # Nothing was dispatched, so this item is safe to redo -- but the
            # ledger only permits CLAIMED -> RETRYABLE through lease expiry.
            # That rule is not an inconvenience to route around: a claim must
            # outlive a crash, because a process we believe is dead may still
            # be running. Releasing early is exactly how two owners end up
            # working the same item.
            if item.lease_expires_at is None or now < datetime.fromisoformat(
                item.lease_expires_at
            ):
                # Still leased. Leave it claimed; a later pass, after the lease
                # expires, releases it.
                continue
            store.append(
                campaign_id,
                ItemTransition(
                    sequence=1,
                    ordinal=item.ordinal,
                    item_key=item_key,
                    status=ItemStatus.RETRYABLE,
                    attempt=item.attempt,
                    at=timestamp,
                    run_id=owner,
                    boundary="lease_expired",
                    code="LEASE_EXPIRED",
                ),
            )
            released.append(item_key)

    return ReconciliationOutcome(
        reconciled=tuple(reconciled),
        parked_uncertain=tuple(parked),
        released_for_retry=tuple(released),
    )


def _take_over_from_dead_owner(
    store: CampaignStore,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
) -> None:
    """Close the dead process's batch and take the heartbeat under lease rules.

    This runs only after :func:`reconcile_after_restart` has released every item
    lease. ``recover_stale_heartbeat`` refuses to reassign ownership while any
    claimed item is still held, which is what stops two processes from believing
    they own the same campaign.

    Note the ordering requirement: the dead batch must be closed before a new one
    opens, and the heartbeat may only be taken when it is provably stale. Neither
    step is a shortcut around the lease; both are the lease being enforced.
    """

    timestamp = now.isoformat(timespec="seconds")
    active = store.read_batches(campaign_id).active
    if active is not None and active.run_id != run_id:
        store.append_batch(
            campaign_id,
            BatchTransition(
                sequence=1,
                batch_id=active.batch_id,
                run_id=active.run_id,
                status=BatchStatus.FINISHED,
                at=timestamp,
                stop_code="OWNER_LOST",
            ),
        )

    heartbeat = store.read_heartbeat(campaign_id)
    if heartbeat is None or heartbeat.run_id == run_id:
        return
    store.recover_stale_heartbeat(
        campaign_id,
        stale_run_id=heartbeat.run_id,
        replacement=CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=run_id,
            started_at=timestamp,
            heartbeat_at=timestamp,
            fresh_until=(now + timedelta(seconds=DEMO_ITEM_LEASE_SECONDS)).isoformat(
                timespec="seconds"
            ),
        ),
        now=now,
    )


def run_demo_campaign(
    store: CampaignStore,
    sink: DurableFakeSideEffectSink,
    *,
    campaign_id: str,
    run_id: str,
    now: datetime,
    policy: BatchPolicy | None = None,
    injector: FaultInjector | None = None,
    resumed: bool = False,
) -> DemoRunOutcome:
    """Process every eligible item once, honoring durable state and fault points.

    Called on a fresh process after a crash with ``resumed=True``, this reconciles
    what the dead process left behind, skips what is already COMMITTED, and
    carries on. It never re-dispatches a side effect for a key the sink has
    already seen.
    """

    injector = injector or NoFaultInjector()
    policy = policy or BatchPolicy(max_items=MAX_DEMO_ITEMS)
    coordinator = BatchCoordinator(store)

    already_committed = _items_with(store, campaign_id, ItemStatus.COMMITTED)
    reconciliation = (
        reconcile_after_restart(
            store, sink, campaign_id=campaign_id, run_id=run_id, now=now
        )
        if resumed
        else ReconciliationOutcome((), (), ())
    )

    if resumed:
        _take_over_from_dead_owner(store, campaign_id=campaign_id, run_id=run_id, now=now)

    batch_id = f"{DEMO_BATCH_ID}-{run_id}"
    opened = coordinator.open_batch(
        campaign_id=campaign_id, batch_id=batch_id, run_id=run_id, policy=policy
    )
    committed: list[DemoItemOutcome] = []

    if isinstance(opened, BatchSession):
        committed = _process_batch(
            coordinator,
            sink,
            session=opened,
            campaign_id=campaign_id,
            now=now,
            injector=injector,
        )
        injector.check(DemoFaultPoint.BEFORE_FINAL_PROJECTION, ordinal=len(committed))

    # A non-session result means the plan is exhausted or blocked, which is a
    # legitimate terminal state, not a failure.
    return DemoRunOutcome(
        campaign_id=campaign_id,
        run_id=run_id,
        committed=tuple(committed),
        reconciled=reconciliation.reconciled,
        parked_uncertain=reconciliation.parked_uncertain,
        skipped_already_committed=already_committed,
    )


def _beat_heartbeat(store: CampaignStore, *, campaign_id: str, now: datetime) -> None:
    """Advance this run's heartbeat to ``now``.

    Only the current owner may advance its own heartbeat, and only forward, so
    this cannot be used to steal ownership or to revive a stale claim.
    """

    current = store.read_heartbeat(campaign_id)
    if current is None:
        return
    timestamp = now.isoformat(timespec="seconds")
    if datetime.fromisoformat(timestamp) <= datetime.fromisoformat(current.heartbeat_at):
        return
    store.write_heartbeat(
        campaign_id,
        CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=current.run_id,
            started_at=current.started_at,
            heartbeat_at=timestamp,
            fresh_until=(now + timedelta(seconds=DEMO_ITEM_LEASE_SECONDS)).isoformat(
                timespec="seconds"
            ),
        ),
    )


def _process_batch(
    coordinator: BatchCoordinator,
    sink: DurableFakeSideEffectSink,
    *,
    session: BatchSession,
    campaign_id: str,
    now: datetime,
    injector: FaultInjector,
) -> list[DemoItemOutcome]:
    committed: list[DemoItemOutcome] = []
    usage = BatchUsage()
    clock = now

    while usage.items_completed < len(session.plan.item_keys):
        # The coordinator deliberately separates the first item of a batch from
        # its continuation: a continuation preflight requires a committed prefix,
        # which the first item does not have yet.
        first = usage.items_completed == 0
        clock = clock + timedelta(seconds=1)
        try:
            claimed = (
                coordinator.claim_first_item(
                    session, now=clock, lease_seconds=DEMO_ITEM_LEASE_SECONDS
                )
                if first
                else coordinator.claim_next_item(
                    session, usage=usage, now=clock, lease_seconds=DEMO_ITEM_LEASE_SECONDS
                )
            )
        except BatchCoordinatorError:
            break
        injector.check(DemoFaultPoint.AFTER_ITEM_CLAIM, ordinal=claimed.ordinal)
        # Beat the heartbeat while working. A worker that only writes one
        # heartbeat at startup declares itself dead partway through any batch
        # that outlives the freshness window, and then blocks its own commits.
        _beat_heartbeat(coordinator.store, campaign_id=campaign_id, now=clock)

        clock = clock + timedelta(seconds=1)
        if first:
            coordinator.record_first_claimed_item_observed(
                session,
                now=clock,
                application_state_verified=True,
                item_identity_verified=True,
            )
        else:
            coordinator.record_next_claimed_item_observed(
                session,
                usage=usage,
                now=clock,
                application_state_verified=True,
                item_identity_verified=True,
            )

        receipt = sink.dispatch(
            idempotency_key(campaign_id, claimed.item_key),
            after_intent=lambda ordinal=claimed.ordinal: injector.check(
                DemoFaultPoint.AFTER_DISPATCH_INTENT, ordinal=ordinal
            ),
        )
        injector.check(DemoFaultPoint.AFTER_SIDE_EFFECT_COMPLETION, ordinal=claimed.ordinal)

        clock = clock + timedelta(seconds=1)
        if first:
            coordinator.record_first_observed_item_extracted(
                session, now=clock, read_only_extraction_completed=True
            )
        else:
            coordinator.record_next_observed_item_extracted(
                session, usage=usage, now=clock, read_only_extraction_completed=True
            )
        clock = clock + timedelta(seconds=1)
        if first:
            coordinator.record_first_extracted_item_committed(
                session,
                now=clock,
                bounded_result_verified=True,
                content_digest=receipt.receipt_digest,
            )
        else:
            coordinator.record_next_extracted_item_committed(
                session,
                usage=usage,
                now=clock,
                bounded_result_verified=True,
                content_digest=receipt.receipt_digest,
            )
        usage = BatchUsage(items_completed=usage.items_completed + 1)
        committed.append(
            DemoItemOutcome(
                item_key=claimed.item_key,
                ordinal=claimed.ordinal,
                content_digest=receipt.receipt_digest,
            )
        )
        injector.check(DemoFaultPoint.AFTER_ITEM_COMMIT, ordinal=claimed.ordinal)

    return committed


@dataclass(frozen=True)
class DemoReport:
    """Sanitized, machine-readable result. Identities are hashes, never content."""

    campaign_digest: str
    total_items: int
    committed_items: int
    uncertain_items: int
    duplicate_side_effects: int
    accepted_side_effects: int
    pending_side_effects: int
    fault_points_exercised: tuple[str, ...]
    resumed_runs: int

    def as_json(self) -> dict[str, object]:
        return {
            "campaign_digest": self.campaign_digest,
            "total_items": self.total_items,
            "committed_items": self.committed_items,
            "uncertain_items": self.uncertain_items,
            "duplicate_side_effects": self.duplicate_side_effects,
            "accepted_side_effects": self.accepted_side_effects,
            "pending_side_effects": self.pending_side_effects,
            "fault_points_exercised": list(self.fault_points_exercised),
            "resumed_runs": self.resumed_runs,
        }


def project_demo_report(
    store: CampaignStore,
    sink: DurableFakeSideEffectSink,
    *,
    campaign_id: str,
    fault_points: tuple[DemoFaultPoint, ...] = (),
    resumed_runs: int = 0,
) -> DemoReport:
    """Rebuild the report from durable state.

    The report is a projection, never an authority. Losing it costs nothing:
    this rebuilds it from the ledger and the sink alone.
    """

    projection = store.read_ledger(campaign_id)
    return DemoReport(
        campaign_digest=sha256(campaign_id.encode("utf-8")).hexdigest(),
        total_items=len(projection.items),
        committed_items=len(_items_with(store, campaign_id, ItemStatus.COMMITTED)),
        uncertain_items=len(_items_with(store, campaign_id, ItemStatus.UNCERTAIN)),
        duplicate_side_effects=len(sink.duplicate_attempts()),
        accepted_side_effects=len(sink.accepted_keys()),
        pending_side_effects=len(sink.pending_keys()),
        fault_points_exercised=tuple(point.value for point in fault_points),
        resumed_runs=resumed_runs,
    )


__all__ = [
    "DEMO_CAMPAIGN_KIND",
    "DemoCampaignError",
    "DemoCampaignPlan",
    "DemoFaultPoint",
    "DemoItemOutcome",
    "DemoReport",
    "DemoRunOutcome",
    "DurableFakeSideEffectSink",
    "FaultInjector",
    "InjectedDemoFault",
    "NoFaultInjector",
    "ReconciliationOutcome",
    "ScriptedFaultInjector",
    "SideEffectOutcome",
    "SideEffectReceipt",
    "fault_injector_from_env",
    "idempotency_key",
    "prepare_demo_campaign",
    "project_demo_report",
    "reconcile_after_restart",
    "run_demo_campaign",
    "synthetic_demo_plan",
]
