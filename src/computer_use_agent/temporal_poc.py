"""Temporal proof of concept: scheduling is Temporal's, safety is ours.

The question this exists to answer is narrow and specific:

    Temporal will re-run an activity whose result it never received. For an
    HTTP call with an idempotency key that is correct. For a GUI side effect it
    is exactly what ADR-001 forbids. So what stops it?

The answer implemented here: **the activity asks the project's own durable
state before doing anything**, and Temporal's retry only decides *when* the
activity runs again, never whether the side effect may happen again.

Division of responsibility, matching ADR-003:

===========================  ==========================================
Temporal owns                This project keeps owning
===========================  ==========================================
when an activity runs        whether the effect may happen at all
retry policy and backoff     the uncertain/committed/not-dispatched call
worker lifecycle             the ledger, the lease, the exact receipt
workflow history             desktop authority and evidence
===========================  ==========================================

This is a proof of concept, not a deployment. It drives the deterministic demo
campaign and its fake side-effect sink, so it touches no desktop and needs no
credentials. ``temporalio`` is an optional extra and nothing in the domain
imports this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .campaign import CampaignStore, ItemStatus
from .demo_campaign import (
    DEMO_ITEM_LEASE_SECONDS,
    DurableFakeSideEffectSink,
    SideEffectOutcome,
    idempotency_key,
    prepare_demo_campaign,
    reconcile_after_restart,
    synthetic_demo_plan,
)
from .run_lock import RunLock

__all__ = [
    "FIRST_OWNER",
    "RESUME_OWNER",
    "TASK_QUEUE",
    "ItemDecision",
    "ItemOutcome",
    "PocConfig",
    "classify_item",
    "prepare_campaign",
    "require_temporalio",
]

TASK_QUEUE = "computer-use-agent-poc"
#: Owner id of the first worker, and of the campaign it prepares.
FIRST_OWNER = "temporal-poc-1"
#: Owner id a resuming worker takes after the first is provably gone.
RESUME_OWNER = "temporal-poc-2"
#: A takeover is only legal once the previous owner's lease and heartbeat have
#: provably expired. Reconciliation and the resuming worker share one clock
#: offset so their timestamps stay monotonic across activity boundaries.
RECONCILE_OFFSET = timedelta(seconds=DEMO_ITEM_LEASE_SECONDS + 60)
RESUME_OFFSET = timedelta(seconds=DEMO_ITEM_LEASE_SECONDS + 120)


def require_temporalio() -> None:
    """Raise a fixed, actionable error when the optional extra is absent."""

    try:
        import temporalio  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised by absence
        raise RuntimeError(
            "temporalio is not installed; "
            'install the optional extra: pip install "guarded-desktop-agent[temporal]"'
        ) from exc


class ItemDecision(str, Enum):
    """What the project's durable state permits for one item, right now."""

    #: Nothing was dispatched. Safe for Temporal to run, or re-run.
    DISPATCH = "dispatch"
    #: Already committed. Doing it again would duplicate; report and move on.
    ALREADY_COMMITTED = "already_committed"
    #: An intent exists with no correlated result. **Never** auto-retried.
    ATTENTION = "attention"


@dataclass(frozen=True)
class ItemOutcome:
    """Bounded, non-sensitive activity result. No page or business content."""

    item_key: str
    decision: str
    side_effect_performed: bool


@dataclass(frozen=True)
class PocConfig:
    """Where durable state lives for one proof-of-concept campaign."""

    state_dir: Path
    campaign_id: str

    def open(self) -> tuple[CampaignStore, DurableFakeSideEffectSink, RunLock]:
        """Open durable state exactly the way a fresh worker process would."""

        lock = RunLock(self.state_dir / "lock")
        lock.acquire(recover_stale=True)
        store = CampaignStore((self.state_dir / "campaign").resolve(), lock)
        sink = DurableFakeSideEffectSink(
            (self.state_dir / "sink" / "side-effects.jsonl").resolve()
        )
        return store, sink, lock


def classify_item(
    store: CampaignStore,
    sink: DurableFakeSideEffectSink,
    *,
    campaign_id: str,
    item_key: str,
) -> ItemDecision:
    """Decide what may happen to one item, from durable evidence only.

    This is the whole safety argument in one function. It is deliberately
    independent of Temporal: the answer must not change because a workflow task
    was rescheduled, a worker restarted, or a retry policy fired.
    """

    projection = store.read_ledger(campaign_id)
    item = projection.items.get(item_key)
    if item is None:
        raise RuntimeError("POC_ITEM_UNKNOWN")
    if item.status is ItemStatus.COMMITTED:
        return ItemDecision.ALREADY_COMMITTED
    if item.status is ItemStatus.UNCERTAIN:
        return ItemDecision.ATTENTION

    outcome = sink.outcome_for(idempotency_key(campaign_id, item_key))
    if outcome is SideEffectOutcome.PENDING:
        # An intent with no correlated result. The effect may have happened.
        # Temporal would happily run this activity again; the project says no.
        return ItemDecision.ATTENTION
    if outcome is SideEffectOutcome.ACCEPTED:
        return ItemDecision.ALREADY_COMMITTED
    return ItemDecision.DISPATCH


def prepare_campaign(config: PocConfig, *, item_count: int, now: datetime | None = None) -> None:
    """Create the manifest and discover every item before the workflow starts."""

    moment = now or datetime.now(timezone.utc).replace(microsecond=0)
    store, _sink, lock = config.open()
    try:
        prepare_demo_campaign(
            store,
            campaign_id=config.campaign_id,
            # Must match the first worker's owner id: the coordinator refuses
            # to open a batch for an owner that does not hold the heartbeat.
            run_id=FIRST_OWNER,
            plan=synthetic_demo_plan(item_count),
            now=moment,
            policy_digest="0" * 64,
        )
    finally:
        lock.release()


def reconcile(config: PocConfig, *, now: datetime | None = None) -> tuple[str, ...]:
    """Run the project's own restart reconciliation. Returns parked item keys."""

    moment = now or datetime.now(timezone.utc).replace(microsecond=0)
    store, sink, lock = config.open()
    try:
        outcome = reconcile_after_restart(
            store,
            sink,
            campaign_id=config.campaign_id,
            run_id=RESUME_OWNER,
            now=moment + RECONCILE_OFFSET,
        )
        return outcome.parked_uncertain
    finally:
        lock.release()


def build_workflow_and_activities(config: PocConfig) -> tuple[Any, list[Any]]:
    """Construct the workflow class and activities bound to ``config``.

    Imported lazily so this module stays importable without ``temporalio`` and
    so nothing in the domain gains a dependency on it.

    The activities are deliberately thin. They call the *existing* campaign
    functions; no item lifecycle, lease rule, or reconciliation logic is
    reimplemented here. A Temporal PoC that grew its own state machine would be
    demonstrating the wrong thing.
    """

    require_temporalio()
    from temporalio import activity

    @activity.defn(name="advance_campaign")
    async def advance_campaign(request: dict[str, Any]) -> dict[str, Any]:
        """Make progress on the campaign, resuming from durable state.

        Temporal may invoke this again after any failure. Every invocation
        resumes from the ledger, so a retry continues rather than restarts.
        """

        from .demo_campaign import (
            DemoFaultPoint,
            InjectedDemoFault,
            NoFaultInjector,
            ScriptedFaultInjector,
            run_demo_campaign,
        )

        store, sink, lock = config.open()
        try:
            fault = request.get("fault")
            run_id = str(request.get("run_id") or FIRST_OWNER)
            resuming = bool(request.get("resume"))
            injector: Any = NoFaultInjector()
            if fault:
                # The payload crosses Temporal as JSON, so it arrives untyped.
                # Narrow it here rather than trusting the wire.
                injector = ScriptedFaultInjector(
                    DemoFaultPoint(str(fault["point"])), int(str(fault["ordinal"]))  # type: ignore[index]
                )
            resumed = _campaign_has_progress(store, config.campaign_id)
            try:
                run_demo_campaign(
                    store,
                    sink,
                    campaign_id=config.campaign_id,
                    # A resuming worker takes a new owner id. Reusing the dead
                    # owner's id would skip takeover and leave its batch open.
                    run_id=run_id,
                    now=datetime.now(timezone.utc).replace(microsecond=0)
                    + (RESUME_OFFSET if resuming else timedelta(0)),
                    injector=injector,
                    resumed=resumed,
                )
            except InjectedDemoFault as injected:
                # A simulated hard crash. Surfaced to Temporal as a failure so
                # its retry policy is genuinely exercised.
                return {"crashed_at": injected.point.value, "ordinal": injected.ordinal}
            return {"crashed_at": None, "ordinal": 0}
        finally:
            lock.release()

    @activity.defn(name="classify_campaign")
    async def classify_campaign(item_keys: list[str]) -> dict[str, list[str]]:
        """Ask the project's durable state what each item now permits."""

        store, sink, lock = config.open()
        try:
            buckets: dict[str, list[str]] = {
                decision.value: [] for decision in ItemDecision
            }
            for item_key in item_keys:
                decision = classify_item(
                    store, sink, campaign_id=config.campaign_id, item_key=item_key
                )
                buckets[decision.value].append(item_key)
            return buckets
        finally:
            lock.release()

    @activity.defn(name="reconcile_campaign")
    async def reconcile_campaign() -> list[str]:
        """Run the project's restart reconciliation; return parked item keys."""

        return list(reconcile(config))

    from .temporal_poc_workflow import CampaignWorkflow

    return CampaignWorkflow, [advance_campaign, reconcile_campaign, classify_campaign]


def _campaign_has_progress(store: CampaignStore, campaign_id: str) -> bool:
    """True once any item has moved past DISCOVERED."""

    projection = store.read_ledger(campaign_id)
    return any(
        item.status is not ItemStatus.DISCOVERED for item in projection.items.values()
    )
