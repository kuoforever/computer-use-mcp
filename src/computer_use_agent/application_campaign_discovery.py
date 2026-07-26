"""Durable stable-identity discovery for reviewed application campaigns.

This is the generic counterpart of the fixed BOSS discovery boundary.  It
accepts only bounded text already returned by the reviewed desktop MCP path,
routes it through the adapter bound to the durable campaign kind, and persists
only prefixed public item keys plus an append-only discovery-pass ledger of
counts and source digests.

The campaign it creates is an ordinary reviewed application campaign: its
manifest carries the same policy and schema digests that
:mod:`application_campaign_runtime` validates, so a discovered campaign enters
``campaign start`` without a second manifest shape or a second dispatch path.

Progression is operator-driven.  No function here accepts a page, URL, scope,
selector, or campaign kind from the caller once the manifest exists: the kind
selects the adapter, an unchanged source is refused, passes are bounded, and a
pass ledger that claims unpersisted items fails closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .application_worker_catalog import (
    ApplicationWorkerSpec,
    application_worker_policy_digest,
    application_worker_schema_digest,
    get_application_worker,
)
from .campaign import (
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    DiscoveryPass,
    ItemStatus,
    ItemTransition,
    campaign_dir,
)
from .discovery_adapters import (
    MAX_DISCOVERY_CAMPAIGN_ITEMS,
    MAX_DISCOVERY_PASSES,
    DiscoveryAdapter,
    DiscoveryAdapterError,
    discovery_source_digest,
    parse_discovery_identities,
)


class ApplicationDiscoveryError(RuntimeError):
    """Fixed failure from the generic application discovery boundary."""


@dataclass(frozen=True)
class ApplicationDiscoveryPreflight:
    campaign_id: str
    campaign_kind: str
    adapter_id: str
    discovered_count: int
    pass_count: int
    last_source_digest: str | None
    last_pass_added_nothing: bool


@dataclass(frozen=True)
class ApplicationDiscoveryOutcome:
    campaign_id: str
    campaign_kind: str
    adapter_id: str
    new_item_keys: tuple[str, ...]
    duplicate_count: int
    discovered_count: int
    pass_sequence: int
    source_digest: str
    added_nothing: bool


def _require_adapter(adapter: DiscoveryAdapter) -> ApplicationWorkerSpec:
    if not isinstance(adapter, DiscoveryAdapter):
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_ADAPTER_INVALID")
    try:
        return get_application_worker(adapter.campaign_kind)
    except KeyError as exc:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_ADAPTER_INVALID") from exc


def _require_store(store: CampaignStore) -> CampaignStore:
    if not isinstance(store, CampaignStore) or not store.lock.acquired:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_LOCK_REQUIRED")
    return store


def _require_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_TIME_INVALID")
    return value


def create_application_discovery_campaign(
    store: CampaignStore,
    *,
    adapter: DiscoveryAdapter,
    campaign_id: str,
    created_at: str,
) -> CampaignManifest:
    """Create one empty reviewed scenario campaign for adapter discovery."""

    spec = _require_adapter(adapter)
    _require_store(store)
    timestamp = _require_timestamp(created_at)
    try:
        return store.create(
            CampaignManifest(
                campaign_id=campaign_id,
                kind=spec.kind,
                policy_digest=application_worker_policy_digest(spec),
                schema_digest=application_worker_schema_digest(spec),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    except (CampaignStoreError, ValueError) as exc:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_CREATE_FAILED") from exc


def inspect_application_discovery_campaign(
    store: CampaignStore,
    *,
    adapter: DiscoveryAdapter,
    campaign_id: str,
    observed_at: str,
) -> ApplicationDiscoveryPreflight:
    """Validate discovery-only durable state without dispatching or writing."""

    spec = _require_adapter(adapter)
    _require_store(store)
    timestamp = _require_timestamp(observed_at)
    try:
        manifest = store.read_manifest(campaign_id)
        projection = store.read_ledger(campaign_id)
        batches = store.read_batches(campaign_id)
        passes = store.read_discovery_passes(campaign_id)
        heartbeat = store.read_heartbeat(campaign_id)
    except CampaignStoreError as exc:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_STATE_INVALID") from exc
    # Items are appended before the pass that records them, so a persisted item
    # count above the recorded total is an interrupted pass and stays repairable
    # by replay. The reverse claims items that were never persisted.
    if projection.discovered_count < passes.total_new_count:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_LEDGER_TORN")
    if passes.last_at is not None and datetime.fromisoformat(timestamp) < datetime.fromisoformat(
        passes.last_at
    ):
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_STATE_INVALID")
    if (
        manifest.kind != spec.kind
        or manifest.status is not CampaignStatus.RUNNING
        or manifest.policy_digest != application_worker_policy_digest(spec)
        or manifest.schema_digest != application_worker_schema_digest(spec)
        or batches.transitions
        or heartbeat is not None
        or (campaign_dir(store.state_dir, campaign_id) / "handoff.json").exists()
        or any(item.status is not ItemStatus.DISCOVERED for item in projection.items.values())
        or datetime.fromisoformat(timestamp) < datetime.fromisoformat(manifest.updated_at)
        or any(
            datetime.fromisoformat(timestamp) < datetime.fromisoformat(item.at)
            for item in projection.items.values()
        )
    ):
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_STATE_INVALID")
    return ApplicationDiscoveryPreflight(
        campaign_id=campaign_id,
        campaign_kind=spec.kind,
        adapter_id=adapter.adapter_id,
        discovered_count=projection.discovered_count,
        pass_count=passes.pass_count,
        last_source_digest=passes.last_source_digest,
        last_pass_added_nothing=passes.last_pass_added_nothing,
    )


def record_application_snapshot_discoveries(
    store: CampaignStore,
    *,
    adapter: DiscoveryAdapter,
    campaign_id: str,
    snapshot_text: str,
    observed_at: str,
) -> ApplicationDiscoveryOutcome:
    """Idempotently append new identities while the campaign is discovery-only.

    One call records exactly one discovery pass. The caller cannot select a
    source: progression happens only because the operator moved the observed
    foreground, which this boundary verifies through a changed source digest.
    """

    spec = _require_adapter(adapter)
    _require_store(store)
    timestamp = _require_timestamp(observed_at)
    try:
        identities = parse_discovery_identities(adapter, snapshot_text)
        source_digest = discovery_source_digest(snapshot_text)
    except DiscoveryAdapterError as exc:
        raise ApplicationDiscoveryError(str(exc)) from exc
    preflight = inspect_application_discovery_campaign(
        store,
        adapter=adapter,
        campaign_id=campaign_id,
        observed_at=timestamp,
    )
    if source_digest == preflight.last_source_digest:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_SOURCE_UNCHANGED")
    if preflight.pass_count >= MAX_DISCOVERY_PASSES:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_PASS_LIMIT")
    projection = store.read_ledger(campaign_id)

    new_identities = tuple(
        identity for identity in identities if identity.item_key not in projection.items
    )
    if preflight.discovered_count + len(new_identities) > MAX_DISCOVERY_CAMPAIGN_ITEMS:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_CAMPAIGN_LIMIT")
    next_ordinal = 1 + max(
        (item.ordinal for item in projection.items.values()),
        default=0,
    )
    try:
        for offset, identity in enumerate(new_identities):
            projection = store.append(
                campaign_id,
                ItemTransition(
                    sequence=len(projection.transitions) + 1,
                    ordinal=next_ordinal + offset,
                    item_key=identity.item_key,
                    status=ItemStatus.DISCOVERED,
                    attempt=0,
                    at=timestamp,
                ),
            )
        passes = store.append_discovery_pass(
            campaign_id,
            DiscoveryPass(
                sequence=preflight.pass_count + 1,
                at=timestamp,
                source_digest=source_digest,
                observed_count=len(identities),
                new_count=len(new_identities),
            ),
        )
    except CampaignStoreError as exc:
        raise ApplicationDiscoveryError("APPLICATION_DISCOVERY_WRITE_FAILED") from exc
    return ApplicationDiscoveryOutcome(
        campaign_id=campaign_id,
        campaign_kind=spec.kind,
        adapter_id=adapter.adapter_id,
        new_item_keys=tuple(identity.item_key for identity in new_identities),
        duplicate_count=len(identities) - len(new_identities),
        discovered_count=projection.discovered_count,
        pass_sequence=passes.pass_count,
        source_digest=source_digest,
        added_nothing=passes.last_pass_added_nothing,
    )


__all__ = [
    "ApplicationDiscoveryError",
    "ApplicationDiscoveryOutcome",
    "ApplicationDiscoveryPreflight",
    "create_application_discovery_campaign",
    "inspect_application_discovery_campaign",
    "record_application_snapshot_discoveries",
]
