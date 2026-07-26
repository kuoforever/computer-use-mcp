"""Composable stable-identity discovery adapters for application campaigns.

An adapter is declarative data, not execution authority.  It states how one
bounded observation of an already-foreground application yields stable public
item identities for a reviewed scenario.  It cannot navigate, choose a page,
open a port, widen the reviewed tool set, or reach a second dispatch site: the
caller observes through the sole Runner boundary and passes the bounded text
here.

Two reviewed extraction modes exist.  ``link_url`` reads public identifiers out
of hyperlink target values on an exact allowlisted host and discards every
other URL field.  ``control_name`` reads them out of control names for an exact
set of roles.  Both require a same-observation source marker so an unrelated
foreground window cannot silently seed a campaign, and both persist only a
prefixed public identity.

Patterns are reviewed code, never operator input.  They are bounded in length
and only ever applied to a bounded snapshot.

The fixed BOSS discovery boundary in :mod:`boss_campaign_discovery` keeps its
own module, contract, and retained digests; this generic path is additive and
does not change it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping
from urllib.parse import parse_qs, urlsplit

from .application_worker_catalog import APPLICATION_WORKERS_BY_KIND


MAX_DISCOVERY_SNAPSHOT_CHARS = 64 * 1024
MAX_DISCOVERY_SNAPSHOT_LINES = 256
MAX_DISCOVERY_IDENTITIES_PER_PASS = 50
MAX_DISCOVERY_CAMPAIGN_ITEMS = 200
MAX_DISCOVERY_PASSES = 20
MAX_DISCOVERY_PATTERN_CHARS = 256

DISCOVERY_OBSERVATION_TOOL = "ui_snapshot"
DISCOVERY_MODES = ("link_url", "control_name")

_MODES = frozenset(DISCOVERY_MODES)
_REVIEWED_ROLES = frozenset(
    {
        "link",
        "hyperlink",
        "listitem",
        "treeitem",
        "dataitem",
        "tabitem",
        "button",
        "text",
    }
)
_ADAPTER_ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_ITEM_KEY_PREFIX = re.compile(r"[a-z][a-z0-9_]{0,31}(?::[a-z][a-z0-9_]{0,31}){0,3}\Z")
_PUBLIC_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]{3,127}\Z")
_QUERY_KEY = re.compile(r"[A-Za-z0-9_]{1,32}\Z")
_HOST = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+\Z")
_SNAPSHOT_LINE = re.compile(
    r'ref_\d+ \| (?P<role>[a-z]+) "(?P<name>.*)" \| \(-?\d+,-?\d+,\d+,\d+\) \| [^|]*'
    r'(?: \| value="(?P<value>[^"]*)")?\Z'
)


class DiscoveryAdapterError(RuntimeError):
    """Fixed failure from the composable discovery-adapter boundary."""


@dataclass(frozen=True)
class DiscoveredIdentity:
    """One stable public identity and its persisted campaign item key."""

    public_id: str
    item_key: str


@lru_cache(maxsize=64)
def _compiled(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _valid_pattern(pattern: object, *, groups: int) -> re.Pattern[str] | None:
    if (
        not isinstance(pattern, str)
        or not pattern
        or len(pattern) > MAX_DISCOVERY_PATTERN_CHARS
    ):
        return None
    try:
        compiled = _compiled(pattern)
    except re.error:
        return None
    return compiled if compiled.groups == groups else None


@dataclass(frozen=True)
class DiscoveryAdapter:
    """One immutable reviewed rule for deriving stable identities."""

    adapter_id: str
    campaign_kind: str
    identity_dimension: str
    mode: str
    item_key_prefix: str
    identity_pattern: str
    source_marker_pattern: str
    roles: tuple[str, ...]
    hosts: tuple[str, ...] = ()
    marker_query_key: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.adapter_id, str)
            or _ADAPTER_ID.fullmatch(self.adapter_id) is None
            or not isinstance(self.campaign_kind, str)
            or not self.campaign_kind
            or not isinstance(self.identity_dimension, str)
            or not self.identity_dimension
            or self.mode not in _MODES
            or not isinstance(self.item_key_prefix, str)
            or _ITEM_KEY_PREFIX.fullmatch(self.item_key_prefix) is None
        ):
            raise ValueError("discovery adapter is invalid")
        if (
            _valid_pattern(self.identity_pattern, groups=1) is None
            or _valid_pattern(self.source_marker_pattern, groups=0) is None
        ):
            raise ValueError("discovery adapter pattern is invalid")
        if (
            not isinstance(self.roles, tuple)
            or not self.roles
            or len(set(self.roles)) != len(self.roles)
            or not set(self.roles) <= _REVIEWED_ROLES
        ):
            raise ValueError("discovery adapter roles are invalid")
        if not isinstance(self.hosts, tuple) or len(set(self.hosts)) != len(self.hosts):
            raise ValueError("discovery adapter hosts are invalid")
        if self.mode == "link_url":
            if (
                not self.hosts
                or any(
                    not isinstance(host, str) or _HOST.fullmatch(host) is None
                    for host in self.hosts
                )
                or not isinstance(self.marker_query_key, str)
                or _QUERY_KEY.fullmatch(self.marker_query_key) is None
            ):
                raise ValueError("link discovery adapter is invalid")
        elif self.hosts or self.marker_query_key is not None:
            raise ValueError("control-name discovery adapter cannot bind URL fields")

    def item_key(self, public_id: str) -> str:
        return f"{self.item_key_prefix}:{public_id}"


def _contract_digest(label: str, material: Mapping[str, object]) -> str:
    encoded = json.dumps(
        {"label": label, **dict(material)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def discovery_adapter_policy_digest(adapter: DiscoveryAdapter) -> str:
    """Bind every reviewed extraction and bound fact of one adapter."""

    if not isinstance(adapter, DiscoveryAdapter):
        raise DiscoveryAdapterError("DISCOVERY_ADAPTER_INVALID")
    return _contract_digest(
        "discovery-adapter-policy-v1",
        {
            "adapter_id": adapter.adapter_id,
            "campaign_kind": adapter.campaign_kind,
            "effect": "observation_only",
            "progression": "operator_moved_source_only",
            "observation_tool": DISCOVERY_OBSERVATION_TOOL,
            "mode": adapter.mode,
            "roles": list(adapter.roles),
            "hosts": list(adapter.hosts),
            "marker_query_key": adapter.marker_query_key,
            "identity_pattern": adapter.identity_pattern,
            "source_marker_pattern": adapter.source_marker_pattern,
            "max_snapshot_chars": MAX_DISCOVERY_SNAPSHOT_CHARS,
            "max_snapshot_lines": MAX_DISCOVERY_SNAPSHOT_LINES,
            "max_identities_per_pass": MAX_DISCOVERY_IDENTITIES_PER_PASS,
            "max_campaign_items": MAX_DISCOVERY_CAMPAIGN_ITEMS,
            "max_discovery_passes": MAX_DISCOVERY_PASSES,
        },
    )


def discovery_adapter_schema_digest(adapter: DiscoveryAdapter) -> str:
    """Bind only what discovery persists, never what it observed."""

    if not isinstance(adapter, DiscoveryAdapter):
        raise DiscoveryAdapterError("DISCOVERY_ADAPTER_INVALID")
    return _contract_digest(
        "discovery-adapter-schema-v1",
        {
            "identity_dimension": adapter.identity_dimension,
            "persisted_item_key": f"{adapter.item_key_prefix}:<public_id>",
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


def discovery_source_digest(snapshot_text: str) -> str:
    """Digest one bounded observation so passes are distinguishable."""

    if not isinstance(snapshot_text, str) or not snapshot_text:
        raise DiscoveryAdapterError("DISCOVERY_SNAPSHOT_INVALID")
    return hashlib.sha256(snapshot_text.encode("utf-8", "surrogatepass")).hexdigest()


def _bounded_lines(snapshot_text: str) -> tuple[str, ...]:
    if not isinstance(snapshot_text, str) or not snapshot_text:
        raise DiscoveryAdapterError("DISCOVERY_SNAPSHOT_INVALID")
    if len(snapshot_text) > MAX_DISCOVERY_SNAPSHOT_CHARS:
        raise DiscoveryAdapterError("DISCOVERY_SNAPSHOT_TOO_LARGE")
    lines = snapshot_text.splitlines()
    if len(lines) > MAX_DISCOVERY_SNAPSHOT_LINES:
        raise DiscoveryAdapterError("DISCOVERY_SNAPSHOT_TOO_LARGE")
    if any(line.startswith("# …") or line.startswith("# incomplete:") for line in lines):
        raise DiscoveryAdapterError("DISCOVERY_SNAPSHOT_INCOMPLETE")
    return tuple(lines)


def _link_candidates(
    adapter: DiscoveryAdapter, lines: tuple[str, ...]
) -> tuple[bool, tuple[str, ...]]:
    """Return whether the source marker was seen, plus candidate URL paths."""

    marker = _compiled(adapter.source_marker_pattern)
    hosts = frozenset(adapter.hosts)
    source_seen = False
    paths: list[str] = []
    for line in lines:
        parsed_line = _SNAPSHOT_LINE.fullmatch(line)
        if parsed_line is None or parsed_line.group("role") not in adapter.roles:
            continue
        value = parsed_line.group("value")
        if not value:
            continue
        try:
            parsed = urlsplit(value)
            markers = parse_qs(parsed.query, keep_blank_values=True).get(
                adapter.marker_query_key or "", []
            )
            hostname = parsed.hostname
            port = parsed.port
            username = parsed.username
            password = parsed.password
        except ValueError:
            continue
        if (
            parsed.scheme != "https"
            or hostname not in hosts
            or port not in {None, 443}
            or username is not None
            or password is not None
        ):
            continue
        if any(marker.fullmatch(candidate) for candidate in markers):
            source_seen = True
        paths.append(parsed.path)
    return source_seen, tuple(paths)


def _control_candidates(
    adapter: DiscoveryAdapter, lines: tuple[str, ...]
) -> tuple[bool, tuple[str, ...]]:
    """Return whether the source marker was seen, plus candidate control names."""

    marker = _compiled(adapter.source_marker_pattern)
    source_seen = False
    names: list[str] = []
    for line in lines:
        parsed_line = _SNAPSHOT_LINE.fullmatch(line)
        if parsed_line is None:
            continue
        name = parsed_line.group("name")
        if marker.fullmatch(name):
            source_seen = True
        if parsed_line.group("role") in adapter.roles:
            names.append(name)
    return source_seen, tuple(names)


def parse_discovery_identities(
    adapter: DiscoveryAdapter, snapshot_text: str
) -> tuple[DiscoveredIdentity, ...]:
    """Extract unique stable identities from one bounded observation."""

    if not isinstance(adapter, DiscoveryAdapter):
        raise DiscoveryAdapterError("DISCOVERY_ADAPTER_INVALID")
    lines = _bounded_lines(snapshot_text)
    if adapter.mode == "link_url":
        source_seen, candidates = _link_candidates(adapter, lines)
    else:
        source_seen, candidates = _control_candidates(adapter, lines)
    if not source_seen:
        raise DiscoveryAdapterError("DISCOVERY_SOURCE_MARKER_ABSENT")

    pattern = _compiled(adapter.identity_pattern)
    identities: list[DiscoveredIdentity] = []
    seen: set[str] = set()
    for candidate in candidates:
        match = pattern.fullmatch(candidate)
        if match is None:
            continue
        public_id = match.group(1)
        if _PUBLIC_ID.fullmatch(public_id) is None or public_id in seen:
            continue
        seen.add(public_id)
        identities.append(DiscoveredIdentity(public_id, adapter.item_key(public_id)))
        if len(identities) > MAX_DISCOVERY_IDENTITIES_PER_PASS:
            raise DiscoveryAdapterError("DISCOVERY_TOO_MANY_IDENTITIES")
    if not identities:
        raise DiscoveryAdapterError("DISCOVERY_NO_IDENTITIES")
    return tuple(identities)


class DiscoveryAdapterRegistry:
    """Immutable, duplicate-refusing registry keyed by campaign kind."""

    def __init__(self, adapters: tuple[DiscoveryAdapter, ...]) -> None:
        if not isinstance(adapters, tuple) or not adapters:
            raise ValueError("discovery adapters must be a non-empty tuple")
        resolved: dict[str, DiscoveryAdapter] = {}
        for adapter in adapters:
            if not isinstance(adapter, DiscoveryAdapter):
                raise ValueError("discovery adapter is invalid")
            if adapter.campaign_kind in resolved:
                raise ValueError("duplicate discovery adapter campaign kind")
            spec = APPLICATION_WORKERS_BY_KIND.get(adapter.campaign_kind)
            if (
                spec is None
                or adapter.identity_dimension not in spec.identity_dimensions
                or DISCOVERY_OBSERVATION_TOOL not in spec.observation_ladder
            ):
                raise ValueError("discovery adapter does not match a reviewed scenario")
            resolved[adapter.campaign_kind] = adapter
        self._adapters: Mapping[str, DiscoveryAdapter] = MappingProxyType(resolved)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def get(self, campaign_kind: str) -> DiscoveryAdapter:
        try:
            return self._adapters[campaign_kind]
        except (KeyError, TypeError) as exc:
            raise DiscoveryAdapterError("DISCOVERY_ADAPTER_UNSUPPORTED") from exc


DISCOVERY_ADAPTERS = (
    DiscoveryAdapter(
        adapter_id="boss_saved_job_links",
        campaign_kind="boss_saved_job_review",
        identity_dimension="public_job_id",
        mode="link_url",
        item_key_prefix="boss:job",
        identity_pattern=r"/job_detail/([A-Za-z0-9_-]{8,128})\.html",
        source_marker_pattern=r"personal_interest_brand(?:_[A-Fa-f0-9]{6,32})?",
        roles=("link", "hyperlink"),
        hosts=("www.zhipin.com",),
        marker_query_key="ka",
    ),
    DiscoveryAdapter(
        adapter_id="incident_queue_rows",
        campaign_kind="enterprise_incident",
        identity_dimension="ticket_id",
        mode="control_name",
        item_key_prefix="incident:ticket",
        identity_pattern=r"(?:[^\n]{0,128}?\s)?(INC-[0-9]{4,12})(?:\s[^\n]{0,128})?",
        source_marker_pattern=r"Incident queue(?:[^\n]{0,64})?",
        roles=("listitem", "dataitem"),
    ),
)

DEFAULT_DISCOVERY_ADAPTERS = DiscoveryAdapterRegistry(DISCOVERY_ADAPTERS)


def discovery_adapter_for_kind(campaign_kind: str) -> DiscoveryAdapter:
    """Bind one adapter through durable campaign kind, never operator input."""

    return DEFAULT_DISCOVERY_ADAPTERS.get(campaign_kind)


__all__ = [
    "DEFAULT_DISCOVERY_ADAPTERS",
    "DISCOVERY_ADAPTERS",
    "DISCOVERY_MODES",
    "DISCOVERY_OBSERVATION_TOOL",
    "MAX_DISCOVERY_CAMPAIGN_ITEMS",
    "MAX_DISCOVERY_IDENTITIES_PER_PASS",
    "MAX_DISCOVERY_PASSES",
    "MAX_DISCOVERY_PATTERN_CHARS",
    "MAX_DISCOVERY_SNAPSHOT_CHARS",
    "MAX_DISCOVERY_SNAPSHOT_LINES",
    "DiscoveredIdentity",
    "DiscoveryAdapter",
    "DiscoveryAdapterError",
    "DiscoveryAdapterRegistry",
    "discovery_adapter_for_kind",
    "discovery_adapter_policy_digest",
    "discovery_adapter_schema_digest",
    "discovery_source_digest",
    "parse_discovery_identities",
]
