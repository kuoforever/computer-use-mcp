"""Bounded BOSS saved-job identity discovery for a future read-only campaign.

The module accepts only bounded UIA text already returned by the reviewed
desktop MCP path. It requires a same-page BOSS interested-jobs source marker,
extracts public BOSS job-detail identifiers, discards URL query data, and
persists only stable item keys in the existing campaign ledger. It does not
navigate, call MCP, start a worker, or grant action authority.

Repeated observations accumulate through a durable discovery-pass ledger. Page
progression is driven entirely by the operator moving the observed foreground;
this module records that a distinct source was observed, refuses an unchanged
source, bounds the number of passes, and fails closed when the pass ledger and
the item ledger disagree.
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
    DiscoveryPass,
    ItemStatus,
    ItemTransition,
)


BOSS_CAMPAIGN_KIND = "boss_saved_job_read_only"
BOSS_SOURCE_MARKER = "personal_interest_brand"
MAX_BOSS_SNAPSHOT_CHARS = 64 * 1024
MAX_BOSS_SNAPSHOT_LINES = 256
MAX_BOSS_IDENTITIES_PER_SNAPSHOT = 50
MAX_BOSS_CAMPAIGN_ITEMS = 200
MAX_BOSS_DISCOVERY_PASSES = 20
_BOSS_HOST = "www.zhipin.com"
_VALUE_URL = re.compile(r'\| value="(https://[^"<>]+)"\Z')
_JOB_PATH = re.compile(r"/job_detail/([A-Za-z0-9_-]{8,128})\.html\Z")
_SOURCE_MARKER = re.compile(rf"{BOSS_SOURCE_MARKER}(?:_[A-Fa-f0-9]{{6,32}})?\Z")
_LINK_ROLES = ("link", "hyperlink")


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
    pass_sequence: int
    source_digest: str
    added_nothing: bool


@dataclass(frozen=True)
class BossDiscoveryPreflight:
    campaign_id: str
    discovered_count: int
    pass_count: int
    last_source_digest: str | None
    last_pass_added_nothing: bool


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
        "boss-discovery-policy-v3",
        {
            "effect": "observation_only",
            "progression": "operator_moved_source_only",
            "max_discovery_passes": MAX_BOSS_DISCOVERY_PASSES,
            "host": _BOSS_HOST,
            "source_marker": BOSS_SOURCE_MARKER,
            "source_marker_scope": "same_snapshot_boss_link",
            "link_roles": list(_LINK_ROLES),
            "max_snapshot_chars": MAX_BOSS_SNAPSHOT_CHARS,
            "max_snapshot_lines": MAX_BOSS_SNAPSHOT_LINES,
            "max_identities_per_snapshot": MAX_BOSS_IDENTITIES_PER_SNAPSHOT,
            "max_campaign_items": MAX_BOSS_CAMPAIGN_ITEMS,
        },
    )


def boss_discovery_schema_digest() -> str:
    return _contract_digest(
        "boss-discovery-schema-v2",
        {
            "persisted_item_key": "boss:job:<public_id>",
            "discarded_url_fields": ["scheme", "host", "query", "fragment"],
            "discovery_pass_fields": [
                "sequence",
                "at",
                "source_digest",
                "observed_count",
                "new_count",
                "run_id",
            ],
        },
    )


def boss_snapshot_source_digest(snapshot_text: str) -> str:
    """Digest one bounded snapshot so passes are distinguishable without content."""

    if not isinstance(snapshot_text, str) or not snapshot_text:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_SNAPSHOT_INVALID")
    return hashlib.sha256(snapshot_text.encode("utf-8", "surrogatepass")).hexdigest()


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

    boss_links = []
    for line in lines:
        if not line.startswith("ref_") or not any(f' | {role} "' in line for role in _LINK_ROLES):
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
        if (
            parsed.scheme != "https"
            or hostname != _BOSS_HOST
            or port not in {None, 443}
            or username is not None
            or password is not None
        ):
            continue
        boss_links.append((parsed, marker))

    if not any(
        _SOURCE_MARKER.fullmatch(value) for _parsed, markers in boss_links for value in markers
    ):
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_NO_IDENTITIES")

    identities: list[BossJobIdentity] = []
    seen: set[str] = set()
    for parsed, _marker in boss_links:
        match = _JOB_PATH.fullmatch(parsed.path)
        if match is None:
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


def inspect_boss_discovery_campaign(
    store: CampaignStore, *, campaign_id: str, observed_at: str
) -> BossDiscoveryPreflight:
    """Validate discovery-only durable state without dispatching or writing."""

    if not isinstance(store, CampaignStore) or not store.lock.acquired:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_LOCK_REQUIRED")
    timestamp = _require_timestamp(observed_at)
    try:
        manifest = store.read_manifest(campaign_id)
        projection = store.read_ledger(campaign_id)
        batches = store.read_batches(campaign_id)
        passes = store.read_discovery_passes(campaign_id)
    except CampaignStoreError as exc:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_STATE_INVALID") from exc
    # Items are appended before the pass that records them, so a persisted item
    # count above the recorded total is an interrupted pass and stays repairable
    # by replay. The reverse claims items that were never persisted.
    if projection.discovered_count < passes.total_new_count:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_LEDGER_TORN")
    if passes.last_at is not None and datetime.fromisoformat(timestamp) < datetime.fromisoformat(
        passes.last_at
    ):
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_STATE_INVALID")
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
    return BossDiscoveryPreflight(
        campaign_id=campaign_id,
        discovered_count=projection.discovered_count,
        pass_count=passes.pass_count,
        last_source_digest=passes.last_source_digest,
        last_pass_added_nothing=passes.last_pass_added_nothing,
    )


def record_boss_snapshot_discoveries(
    store: CampaignStore,
    *,
    campaign_id: str,
    snapshot_text: str,
    observed_at: str,
) -> BossDiscoveryOutcome:
    """Idempotently append new identities while the campaign is discovery-only.

    One call records exactly one discovery pass. The caller cannot select a
    page: progression happens only because the operator moved the observed
    source, which this boundary verifies through a changed source digest.
    """

    if not isinstance(store, CampaignStore) or not store.lock.acquired:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_LOCK_REQUIRED")
    timestamp = _require_timestamp(observed_at)
    identities = parse_boss_job_identities(snapshot_text)
    source_digest = boss_snapshot_source_digest(snapshot_text)
    preflight = inspect_boss_discovery_campaign(
        store, campaign_id=campaign_id, observed_at=timestamp
    )
    if source_digest == preflight.last_source_digest:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_SOURCE_UNCHANGED")
    if preflight.pass_count >= MAX_BOSS_DISCOVERY_PASSES:
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_PASS_LIMIT")
    projection = store.read_ledger(campaign_id)

    new_identities = tuple(
        identity for identity in identities if identity.item_key not in projection.items
    )
    if preflight.discovered_count + len(new_identities) > MAX_BOSS_CAMPAIGN_ITEMS:
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
        raise BossCampaignDiscoveryError("BOSS_DISCOVERY_WRITE_FAILED") from exc
    return BossDiscoveryOutcome(
        campaign_id=campaign_id,
        new_item_keys=tuple(identity.item_key for identity in new_identities),
        duplicate_count=len(identities) - len(new_identities),
        discovered_count=projection.discovered_count,
        pass_sequence=passes.pass_count,
        source_digest=source_digest,
        added_nothing=passes.last_pass_added_nothing,
    )


__all__ = [
    "BOSS_CAMPAIGN_KIND",
    "BOSS_SOURCE_MARKER",
    "MAX_BOSS_CAMPAIGN_ITEMS",
    "MAX_BOSS_DISCOVERY_PASSES",
    "MAX_BOSS_IDENTITIES_PER_SNAPSHOT",
    "MAX_BOSS_SNAPSHOT_CHARS",
    "MAX_BOSS_SNAPSHOT_LINES",
    "BossCampaignDiscoveryError",
    "BossDiscoveryOutcome",
    "BossDiscoveryPreflight",
    "BossJobIdentity",
    "boss_discovery_policy_digest",
    "boss_discovery_schema_digest",
    "boss_snapshot_source_digest",
    "create_boss_discovery_campaign",
    "inspect_boss_discovery_campaign",
    "parse_boss_job_identities",
    "record_boss_snapshot_discoveries",
]
