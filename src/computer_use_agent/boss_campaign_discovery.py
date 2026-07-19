"""Bounded BOSS saved-job identity discovery for a future read-only campaign.

The module accepts only bounded UIA text already returned by the reviewed
desktop MCP path.  It extracts public BOSS job-detail identifiers, discards URL
query data, and persists only stable item keys in the existing campaign ledger.
It does not navigate, call MCP, start a worker, or grant action authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

from .campaign import (
    CampaignManifest,
    CampaignStatus,
    CampaignStore,
    CampaignStoreError,
    ItemStatus,
    ItemTransition,
)


BOSS_CAMPAIGN_KIND = "boss_saved_job_read_only"
BOSS_SOURCE_MARKER = "personal_interest_brand"
MAX_BOSS_SNAPSHOT_CHARS = 64 * 1024
MAX_BOSS_SNAPSHOT_LINES = 256
MAX_BOSS_IDENTITIES_PER_SNAPSHOT = 50
MAX_BOSS_CAMPAIGN_ITEMS = 200
_BOSS_HOST = "www.zhipin.com"
_VALUE_URL = re.compile(r'\| value="(https://[^"<>]+)"\Z')
_JOB_PATH = re.compile(r"/job_detail/([A-Za-z0-9_-]{8,128})\.html\Z")


class BossCampaignDiscoveryError(RuntimeError):
    """Fixed failure from the bounded BOSS discovery boundary."""


@dataclass(frozen=True)
class BossJobIdentity:
    public_id: str
    item_key: str


@dataclass(frozen=True)
class BossDiscoveryOutcome:
    campaign_id: str
    new_item_keys: tuple[str, ...]
    duplicate_count: int
    discovered_count: int


def _contract_digest(label: str, material: dict[str, object]) -> str:
    encoded = json.dumps(
        {"label": label, **material},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def boss_discovery_policy_digest() -> str:
    return _contract_digest(
        "boss-discovery-policy-v1",
        {
            "effect": "observation_only",
            "host": _BOSS_HOST,
            "source_marker": BOSS_SOURCE_MARKER,
            "max_snapshot_chars": MAX_BOSS_SNAPSHOT_CHARS,
            "max_snapshot_lines": MAX_BOSS_SNAPSHOT_LINES,
            "max_identities_per_snapshot": MAX_BOSS_IDENTITIES_PER_SNAPSHOT,
            "max_campaign_items": MAX_BOSS_CAMPAIGN_ITEMS,
        },
    )


def boss_discovery_schema_digest() -> str:
    return _contract_digest(
        "boss-discovery-schema-v1",
        {
            "persisted_item_key": "boss:job:<public_id>",
            "discarded_url_fields": ["scheme", "host", "query", "fragment"],
        },
    )


def _require_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_TIME_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_TIME_INVALID")
    return value


def parse_boss_job_identities(snapshot_text: str) -> tuple[BossJobIdentity, ...]:
    """Extract unique stable public identities from one bounded BOSS snapshot."""

    if not isinstance(snapshot_text, str) or not snapshot_text:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_SNAPSHOT_INVALID")
    if len(snapshot_text) > MAX_BOSS_SNAPSHOT_CHARS:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_SNAPSHOT_TOO_LARGE")
    lines = snapshot_text.splitlines()
    if len(lines) > MAX_BOSS_SNAPSHOT_LINES:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_SNAPSHOT_TOO_LARGE")
    if any(line.startswith("# …") or line.startswith("# incomplete:") for line in lines):
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_SNAPSHOT_INCOMPLETE")

    identities: list[BossJobIdentity] = []
    seen: set[str] = set()
    for line in lines:
        if not line.startswith("ref_") or ' | link "' not in line:
            continue
        value_match = _VALUE_URL.search(line)
        if value_match is None:
            continue
        candidate = value_match.group(1)
        try:
            parsed = urlsplit(candidate)
            marker = parse_qs(parsed.query, keep_blank_values=True).get("ka", [])
            port = parsed.port
            hostname = parsed.hostname
            username = parsed.username
            password = parsed.password
        except ValueError:
            continue
        match = _JOB_PATH.fullmatch(parsed.path)
        if (
            parsed.scheme != "https"
            or hostname != _BOSS_HOST
            or port not in {None, 443}
            or username is not None
            or password is not None
            or match is None
            or BOSS_SOURCE_MARKER not in marker
        ):
            continue
        public_id = match.group(1)
        if public_id in seen:
            continue
        seen.add(public_id)
        identities.append(BossJobIdentity(public_id, f"boss:job:{public_id}"))
        if len(identities) > MAX_BOSS_IDENTITIES_PER_SNAPSHOT:
            raise BossCampaignDiscoveryError("BOSS_DISCOVERY_TOO_MANY_IDENTITIES")
    if not identities:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_NO_IDENTITIES")
    return tuple(identities)


def create_boss_discovery_campaign(
    store: CampaignStore, *, campaign_id: str, created_at: str
) -> CampaignManifest:
    """Create only the fixed read-only BOSS discovery manifest."""

    if not isinstance(store, CampaignStore) or not store.lock.acquired:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_LOCK_REQUIRED")
    timestamp = _require_timestamp(created_at)
    try:
        return store.create(
            CampaignManifest(
                campaign_id=campaign_id,
                kind=BOSS_CAMPAIGN_KIND,
                policy_digest=boss_discovery_policy_digest(),
                schema_digest=boss_discovery_schema_digest(),
                created_at=timestamp,
                updated_at=timestamp,
            )
        )
    except CampaignStoreError as exc:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_CREATE_FAILED") from exc


def record_boss_snapshot_discoveries(
    store: CampaignStore,
    *,
    campaign_id: str,
    snapshot_text: str,
    observed_at: str,
) -> BossDiscoveryOutcome:
    """Idempotently append new identities while the campaign is discovery-only."""

    if not isinstance(store, CampaignStore) or not store.lock.acquired:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_LOCK_REQUIRED")
    timestamp = _require_timestamp(observed_at)
    identities = parse_boss_job_identities(snapshot_text)
    try:
        manifest = store.read_manifest(campaign_id)
        projection = store.read_ledger(campaign_id)
        batches = store.read_batches(campaign_id)
    except CampaignStoreError as exc:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_STATE_INVALID") from exc
    if (
        manifest.kind != BOSS_CAMPAIGN_KIND
        or manifest.status is not CampaignStatus.RUNNING
        or manifest.policy_digest != boss_discovery_policy_digest()
        or manifest.schema_digest != boss_discovery_schema_digest()
        or batches.transitions
        or any(item.status is not ItemStatus.DISCOVERED for item in projection.items.values())
        or datetime.fromisoformat(timestamp) < datetime.fromisoformat(manifest.updated_at)
        or any(
            datetime.fromisoformat(timestamp) < datetime.fromisoformat(item.at)
            for item in projection.items.values()
        )
    ):
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_STATE_INVALID")

    new_identities = tuple(
        identity for identity in identities if identity.item_key not in projection.items
    )
    if projection.discovered_count + len(new_identities) > MAX_BOSS_CAMPAIGN_ITEMS:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_CAMPAIGN_LIMIT")
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
    except CampaignStoreError as exc:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_WRITE_FAILED") from exc
    return BossDiscoveryOutcome(
        campaign_id=campaign_id,
        new_item_keys=tuple(identity.item_key for identity in new_identities),
        duplicate_count=len(identities) - len(new_identities),
        discovered_count=projection.discovered_count,
    )


__all__ = [
    "BOSS_CAMPAIGN_KIND",
    "BOSS_SOURCE_MARKER",
    "MAX_BOSS_CAMPAIGN_ITEMS",
    "MAX_BOSS_IDENTITIES_PER_SNAPSHOT",
    "MAX_BOSS_SNAPSHOT_CHARS",
    "MAX_BOSS_SNAPSHOT_LINES",
    "BossCampaignDiscoveryError",
    "BossDiscoveryOutcome",
    "BossJobIdentity",
    "boss_discovery_policy_digest",
    "boss_discovery_schema_digest",
    "create_boss_discovery_campaign",
    "parse_boss_job_identities",
    "record_boss_snapshot_discoveries",
]
