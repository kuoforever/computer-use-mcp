"""Private, non-executable persistence for read-only campaign control state.

Campaign state is deliberately separate from Agent checkpoints.  This module
does not import provider, runner, policy, approval, MCP, or desktop code.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from .atomic_file import publish_atomically, read_shared_bytes
from .run_lock import RunLock


CAMPAIGN_VERSION = 2
MAX_CAMPAIGN_MANIFEST_BYTES = 16 * 1024
MAX_CAMPAIGN_HANDOFF_BYTES = 16 * 1024
MAX_CAMPAIGN_HEARTBEAT_BYTES = 4 * 1024
MAX_CAMPAIGN_LEDGER_BYTES = 1024 * 1024
MAX_CAMPAIGN_BATCH_LEDGER_BYTES = 1024 * 1024
MAX_CAMPAIGN_DISCOVERY_LEDGER_BYTES = 256 * 1024
MAX_CAMPAIGN_ITEMS = 10_000
MAX_CAMPAIGN_DISCOVERY_PASSES = 100
MAX_HEARTBEAT_FRESHNESS_SECONDS = 5 * 60
MAX_ITEM_LEASE_SECONDS = 60 * 60
CAMPAIGN_CONTROL_SNAPSHOT_ATTEMPTS = 3

#: Bounded retry for the atomic rename. A real-time file scanner can hold a
#: freshly written destination for a few milliseconds; five attempts with
#: exponential backoff span under 0.2s total, short enough that a genuine
#: permission fault still surfaces promptly.
_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_BASE_SECONDS = 0.01
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_ITEM_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


class CampaignStoreError(RuntimeError):
    """Fixed campaign persistence failure without application content."""


class CampaignStatus(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CHALLENGE = "CHALLENGE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


_HANDOFF_DIRECTIVES = {
    CampaignStatus.RUNNING: (
        "resume_batch",
        "verify_current_page_and_account_state",
    ),
    CampaignStatus.PAUSED: (
        "wait_for_resume",
        "none_until_resumed",
    ),
    CampaignStatus.CHALLENGE: (
        "wait_for_challenge_resolution",
        "resolve_challenge_then_reobserve",
    ),
    CampaignStatus.COMPLETED: (
        "none_completed",
        "none",
    ),
    CampaignStatus.FAILED: (
        "human_review_failed",
        "review_failure_before_any_resume",
    ),
}
_HANDOFF_FIELDS = {
    "campaign_id",
    "campaign_version",
    "next_item_ordinal",
    "completed_count",
    "retryable_count",
    "uncertain_count",
    "last_run_id",
    "next_action",
    "required_observation",
    "updated_at",
}


class ItemStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    CLAIMED = "CLAIMED"
    OBSERVED = "OBSERVED"
    EXTRACTED = "EXTRACTED"
    COMMITTED = "COMMITTED"
    RETRYABLE = "RETRYABLE"
    SKIPPED = "SKIPPED"
    CHALLENGE = "CHALLENGE"
    UNCERTAIN = "UNCERTAIN"


class BatchStatus(str, Enum):
    STARTED = "STARTED"
    FINISHED = "FINISHED"


_ALLOWED_TRANSITIONS = {
    ItemStatus.DISCOVERED: frozenset({ItemStatus.CLAIMED}),
    ItemStatus.CLAIMED: frozenset({ItemStatus.OBSERVED, ItemStatus.RETRYABLE}),
    ItemStatus.OBSERVED: frozenset(
        {
            ItemStatus.EXTRACTED,
            ItemStatus.RETRYABLE,
            ItemStatus.CHALLENGE,
            ItemStatus.UNCERTAIN,
        }
    ),
    ItemStatus.EXTRACTED: frozenset(
        {
            ItemStatus.COMMITTED,
            ItemStatus.SKIPPED,
            ItemStatus.RETRYABLE,
            ItemStatus.CHALLENGE,
            ItemStatus.UNCERTAIN,
        }
    ),
    ItemStatus.RETRYABLE: frozenset({ItemStatus.CLAIMED}),
    ItemStatus.COMMITTED: frozenset(),
    ItemStatus.SKIPPED: frozenset(),
    ItemStatus.CHALLENGE: frozenset(),
    ItemStatus.UNCERTAIN: frozenset(),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(value: Mapping[str, object]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_INVALID") from exc


def _digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise CampaignStoreError("CAMPAIGN_INVALID")
    return value


def _require_item_key(value: object) -> str:
    if not isinstance(value, str) or _ITEM_KEY.fullmatch(value) is None:
        raise CampaignStoreError("CAMPAIGN_INVALID")
    return value


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CampaignStoreError("CAMPAIGN_INVALID")
    return value


def _require_nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CampaignStoreError("CAMPAIGN_INVALID")
    return value


def _require_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise CampaignStoreError("CAMPAIGN_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CampaignStoreError("CAMPAIGN_INVALID") from exc
    if parsed.tzinfo is None:
        raise CampaignStoreError("CAMPAIGN_INVALID")
    return value


def _is_unsafe_path(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(reparse and attributes & reparse)


def campaign_dir(state_dir: Path, campaign_id: str) -> Path:
    """Return one campaign directory after strict path-shape validation."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    return state_dir / "campaigns" / _require_identifier(campaign_id)


def campaign_path_is_unsafe(path: Path) -> bool:
    """Expose the campaign store's symlink/reparse-point refusal to readers."""

    if not isinstance(path, Path):
        raise ValueError("path must be a Path")
    return _is_unsafe_path(path)


@dataclass(frozen=True)
class CampaignManifest:
    campaign_id: str
    kind: str
    policy_digest: str
    schema_digest: str
    created_at: str
    updated_at: str
    status: CampaignStatus = CampaignStatus.RUNNING

    def __post_init__(self) -> None:
        _require_identifier(self.campaign_id)
        if not isinstance(self.kind, str) or _KIND.fullmatch(self.kind) is None:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        _require_digest(self.policy_digest)
        _require_digest(self.schema_digest)
        _require_timestamp(self.created_at)
        _require_timestamp(self.updated_at)
        if not isinstance(self.status, CampaignStatus):
            raise CampaignStoreError("CAMPAIGN_INVALID")

    @classmethod
    def create(
        cls,
        *,
        campaign_id: str,
        kind: str,
        policy_digest: str,
        schema_digest: str,
    ) -> "CampaignManifest":
        now = _utc_now()
        return cls(
            campaign_id=campaign_id,
            kind=kind,
            policy_digest=policy_digest,
            schema_digest=schema_digest,
            created_at=now,
            updated_at=now,
        )

    def as_json(self) -> dict[str, object]:
        return {
            "campaign_version": CAMPAIGN_VERSION,
            "campaign_id": self.campaign_id,
            "kind": self.kind,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status.value,
            "policy_digest": self.policy_digest,
            "schema_digest": self.schema_digest,
        }


@dataclass(frozen=True)
class CampaignHeartbeat:
    """Bounded liveness control state for one future campaign worker."""

    campaign_id: str
    run_id: str
    started_at: str
    heartbeat_at: str
    fresh_until: str

    def __post_init__(self) -> None:
        _require_identifier(self.campaign_id)
        _require_identifier(self.run_id)
        _require_timestamp(self.started_at)
        _require_timestamp(self.heartbeat_at)
        _require_timestamp(self.fresh_until)
        started = datetime.fromisoformat(self.started_at)
        heartbeat = datetime.fromisoformat(self.heartbeat_at)
        fresh_until = datetime.fromisoformat(self.fresh_until)
        freshness = (fresh_until - heartbeat).total_seconds()
        if (
            heartbeat < started
            or freshness <= 0
            or freshness > MAX_HEARTBEAT_FRESHNESS_SECONDS
        ):
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_INVALID")

    def as_json(self) -> dict[str, object]:
        return {
            "campaign_version": CAMPAIGN_VERSION,
            "campaign_id": self.campaign_id,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "heartbeat_at": self.heartbeat_at,
            "fresh_until": self.fresh_until,
        }


@dataclass(frozen=True)
class ItemTransition:
    sequence: int
    ordinal: int
    item_key: str
    status: ItemStatus
    attempt: int
    at: str
    run_id: str | None = None
    lease_expires_at: str | None = None
    boundary: str | None = None
    code: str | None = None
    content_digest: str | None = None

    def __post_init__(self) -> None:
        if self.sequence <= 0 or self.ordinal <= 0:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        _require_item_key(self.item_key)
        if not isinstance(self.status, ItemStatus):
            raise CampaignStoreError("CAMPAIGN_INVALID")
        _require_nonnegative_int(self.attempt)
        _require_timestamp(self.at)
        if self.run_id is not None:
            _require_identifier(self.run_id)
        if self.lease_expires_at is not None:
            _require_timestamp(self.lease_expires_at)
        if self.boundary is not None and (
            not isinstance(self.boundary, str) or _IDENTIFIER.fullmatch(self.boundary) is None
        ):
            raise CampaignStoreError("CAMPAIGN_INVALID")
        if self.code is not None and (
            not isinstance(self.code, str) or _CODE.fullmatch(self.code) is None
        ):
            raise CampaignStoreError("CAMPAIGN_INVALID")
        if self.content_digest is not None:
            _require_digest(self.content_digest)
        if self.status is ItemStatus.DISCOVERED:
            if any(
                value is not None
                for value in (
                    self.run_id,
                    self.lease_expires_at,
                    self.boundary,
                    self.code,
                    self.content_digest,
                )
            ) or self.attempt != 0:
                raise CampaignStoreError("CAMPAIGN_INVALID")
        elif self.run_id is None or self.boundary is None:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        if self.status is ItemStatus.CLAIMED:
            if self.lease_expires_at is None:
                raise CampaignStoreError("CAMPAIGN_INVALID")
            lease_duration = datetime.fromisoformat(self.lease_expires_at) - datetime.fromisoformat(self.at)
            if lease_duration.total_seconds() <= 0 or lease_duration.total_seconds() > MAX_ITEM_LEASE_SECONDS:
                raise CampaignStoreError("CAMPAIGN_INVALID")
        elif self.lease_expires_at is not None:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        if self.status is ItemStatus.COMMITTED:
            if self.content_digest is None or self.code is None:
                raise CampaignStoreError("CAMPAIGN_INVALID")
        elif self.content_digest is not None:
            raise CampaignStoreError("CAMPAIGN_INVALID")

    def as_json(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "ordinal": self.ordinal,
            "item_key": self.item_key,
            "status": self.status.value,
            "attempt": self.attempt,
            "at": self.at,
            "run_id": self.run_id,
            "lease_expires_at": self.lease_expires_at,
            "boundary": self.boundary,
            "code": self.code,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True)
class BatchTransition:
    """One fixed-schema lifecycle event for a provider-context batch."""

    sequence: int
    batch_id: str
    run_id: str
    status: BatchStatus
    at: str
    stop_code: str | None = None
    items_completed: int = 0
    elapsed_seconds: int = 0
    provider_turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    screenshots: int = 0
    ocr_regions: int = 0
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        _require_identifier(self.batch_id)
        _require_identifier(self.run_id)
        if not isinstance(self.status, BatchStatus):
            raise CampaignStoreError("CAMPAIGN_INVALID")
        _require_timestamp(self.at)
        if self.stop_code is not None and (
            not isinstance(self.stop_code, str) or _CODE.fullmatch(self.stop_code) is None
        ):
            raise CampaignStoreError("CAMPAIGN_INVALID")
        counters = (
            self.items_completed, self.elapsed_seconds, self.provider_turns,
            self.tool_calls, self.input_tokens, self.output_tokens,
            self.screenshots, self.ocr_regions, self.consecutive_failures,
        )
        for counter in counters:
            _require_nonnegative_int(counter)
        if self.status is BatchStatus.STARTED:
            if self.stop_code is not None or any(counters):
                raise CampaignStoreError("CAMPAIGN_INVALID")
        elif self.stop_code is None:
            raise CampaignStoreError("CAMPAIGN_INVALID")

    def as_json(self) -> dict[str, object]:
        return {
            "sequence": self.sequence, "batch_id": self.batch_id, "run_id": self.run_id,
            "status": self.status.value, "at": self.at, "stop_code": self.stop_code,
            "items_completed": self.items_completed, "elapsed_seconds": self.elapsed_seconds,
            "provider_turns": self.provider_turns, "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "screenshots": self.screenshots, "ocr_regions": self.ocr_regions,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass(frozen=True)
class DiscoveryPass:
    """One recorded observation of a discovery source that added item keys.

    The record keeps only counts and a digest of the bounded source text. It
    never stores observed content, a URL, a page number, or a selector.
    """

    sequence: int
    at: str
    source_digest: str
    observed_count: int
    new_count: int
    run_id: str | None = None

    def __post_init__(self) -> None:
        if self.sequence <= 0:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        _require_timestamp(self.at)
        _require_digest(self.source_digest)
        _require_nonnegative_int(self.observed_count)
        _require_nonnegative_int(self.new_count)
        if self.observed_count == 0 or self.new_count > self.observed_count:
            raise CampaignStoreError("CAMPAIGN_INVALID")
        if self.run_id is not None:
            _require_identifier(self.run_id)

    def as_json(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "at": self.at,
            "source_digest": self.source_digest,
            "observed_count": self.observed_count,
            "new_count": self.new_count,
            "run_id": self.run_id,
        }


@dataclass(frozen=True)
class CampaignProjection:
    transitions: tuple[ItemTransition, ...]
    items: Mapping[str, ItemTransition]

    @property
    def discovered_count(self) -> int:
        return len(self.items)

    @property
    def completed_count(self) -> int:
        return sum(item.status is ItemStatus.COMMITTED for item in self.items.values())

    @property
    def retryable_count(self) -> int:
        return sum(item.status is ItemStatus.RETRYABLE for item in self.items.values())

    @property
    def uncertain_count(self) -> int:
        return sum(item.status is ItemStatus.UNCERTAIN for item in self.items.values())

    @property
    def next_ordinal(self) -> int:
        incomplete = [
            item.ordinal
            for item in self.items.values()
            if item.status is not ItemStatus.COMMITTED
        ]
        return min(incomplete) if incomplete else self.discovered_count + 1


@dataclass(frozen=True)
class BatchProjection:
    transitions: tuple[BatchTransition, ...]
    active: BatchTransition | None
    finished_count: int


@dataclass(frozen=True)
class DiscoveryPassProjection:
    """Durable progression facts for a discovery-only campaign."""

    passes: tuple[DiscoveryPass, ...]

    @property
    def pass_count(self) -> int:
        return len(self.passes)

    @property
    def last_source_digest(self) -> str | None:
        return self.passes[-1].source_digest if self.passes else None

    @property
    def last_at(self) -> str | None:
        return self.passes[-1].at if self.passes else None

    @property
    def total_new_count(self) -> int:
        return sum(entry.new_count for entry in self.passes)

    @property
    def last_pass_added_nothing(self) -> bool:
        """Report only the recorded fact, never an inferred end of a source."""

        return bool(self.passes) and self.passes[-1].new_count == 0


def reduce_item_ledger(transitions: Sequence[ItemTransition]) -> CampaignProjection:
    """Validate an append-only ledger and project its latest item states."""

    items: dict[str, ItemTransition] = {}
    ordinals: set[int] = set()
    for expected_sequence, transition in enumerate(transitions, start=1):
        if transition.sequence != expected_sequence:
            raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
        previous = items.get(transition.item_key)
        if previous is None:
            if transition.status is not ItemStatus.DISCOVERED or transition.ordinal in ordinals:
                raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
            ordinals.add(transition.ordinal)
        else:
            if transition.ordinal != previous.ordinal:
                raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
            if transition.status not in _ALLOWED_TRANSITIONS[previous.status]:
                raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
            if previous.status is ItemStatus.CLAIMED and transition.status is ItemStatus.RETRYABLE:
                if (
                    transition.code != "LEASE_EXPIRED"
                    or transition.boundary != "lease_expired"
                    or previous.lease_expires_at is None
                    or datetime.fromisoformat(transition.at)
                    < datetime.fromisoformat(previous.lease_expires_at)
                ):
                    raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
            expected_attempt = previous.attempt + (
                1 if transition.status is ItemStatus.CLAIMED else 0
            )
            if transition.attempt != expected_attempt:
                raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
        items[transition.item_key] = transition
    if len(items) > MAX_CAMPAIGN_ITEMS:
        raise CampaignStoreError("CAMPAIGN_LEDGER_TOO_LARGE")
    return CampaignProjection(
        transitions=tuple(transitions), items=MappingProxyType(dict(items))
    )


def reduce_batch_ledger(transitions: Sequence[BatchTransition]) -> BatchProjection:
    """Validate a sequential batch lifecycle ledger without executing it."""

    active: BatchTransition | None = None
    finished_count = 0
    batch_ids: set[str] = set()
    for expected_sequence, transition in enumerate(transitions, start=1):
        if transition.sequence != expected_sequence:
            raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID")
        if transition.status is BatchStatus.STARTED:
            if active is not None or transition.batch_id in batch_ids:
                raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID")
            batch_ids.add(transition.batch_id)
            active = transition
        elif active is None or (
            transition.batch_id != active.batch_id or transition.run_id != active.run_id
        ):
            raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID")
        else:
            active = None
            finished_count += 1
    return BatchProjection(tuple(transitions), active, finished_count)


def reduce_discovery_passes(passes: Sequence[DiscoveryPass]) -> DiscoveryPassProjection:
    """Validate an append-only discovery-pass ledger without executing it."""

    previous: DiscoveryPass | None = None
    for expected_sequence, entry in enumerate(passes, start=1):
        if entry.sequence != expected_sequence:
            raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID")
        if previous is not None:
            if entry.source_digest == previous.source_digest:
                raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID")
            if datetime.fromisoformat(entry.at) < datetime.fromisoformat(previous.at):
                raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID")
        previous = entry
    if len(passes) > MAX_CAMPAIGN_DISCOVERY_PASSES:
        raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_TOO_LARGE")
    return DiscoveryPassProjection(tuple(passes))


def _decode_discovery_pass(value: object) -> DiscoveryPass:
    fields = {"sequence", "at", "source_digest", "observed_count", "new_count", "run_id"}
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID")
    try:
        return DiscoveryPass(
            sequence=value.get("sequence"),
            at=value.get("at"),
            source_digest=value.get("source_digest"),
            observed_count=value.get("observed_count"),
            new_count=value.get("new_count"),
            run_id=value.get("run_id"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID") from exc


def _decode_manifest(value: object, *, campaign_id: str) -> CampaignManifest:
    fields = {
        "campaign_version",
        "campaign_id",
        "kind",
        "created_at",
        "updated_at",
        "status",
        "policy_digest",
        "schema_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CampaignStoreError("CAMPAIGN_MANIFEST_INVALID")
    if value.get("campaign_version") != CAMPAIGN_VERSION or value.get("campaign_id") != campaign_id:
        raise CampaignStoreError("CAMPAIGN_MANIFEST_INVALID")
    try:
        return CampaignManifest(
            campaign_id=campaign_id,
            kind=value.get("kind"),
            policy_digest=value.get("policy_digest"),
            schema_digest=value.get("schema_digest"),
            created_at=value.get("created_at"),
            updated_at=value.get("updated_at"),
            status=CampaignStatus(value.get("status")),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_MANIFEST_INVALID") from exc


def _decode_heartbeat(value: object, *, campaign_id: str) -> CampaignHeartbeat:
    fields = {
        "campaign_version",
        "campaign_id",
        "run_id",
        "started_at",
        "heartbeat_at",
        "fresh_until",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CampaignStoreError("CAMPAIGN_HEARTBEAT_INVALID")
    if value.get("campaign_version") != CAMPAIGN_VERSION or value.get("campaign_id") != campaign_id:
        raise CampaignStoreError("CAMPAIGN_HEARTBEAT_INVALID")
    try:
        return CampaignHeartbeat(
            campaign_id=campaign_id,
            run_id=value.get("run_id"),
            started_at=value.get("started_at"),
            heartbeat_at=value.get("heartbeat_at"),
            fresh_until=value.get("fresh_until"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_HEARTBEAT_INVALID") from exc


def _decode_transition(value: object) -> ItemTransition:
    fields = {
        "sequence",
        "ordinal",
        "item_key",
        "status",
        "attempt",
        "at",
        "run_id",
        "lease_expires_at",
        "boundary",
        "code",
        "content_digest",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
    try:
        return ItemTransition(
            sequence=value.get("sequence"),
            ordinal=value.get("ordinal"),
            item_key=value.get("item_key"),
            status=ItemStatus(value.get("status")),
            attempt=value.get("attempt"),
            at=value.get("at"),
            run_id=value.get("run_id"),
            lease_expires_at=value.get("lease_expires_at"),
            boundary=value.get("boundary"),
            code=value.get("code"),
            content_digest=value.get("content_digest"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID") from exc


def _decode_batch_transition(value: object) -> BatchTransition:
    fields = {
        "sequence", "batch_id", "run_id", "status", "at", "stop_code",
        "items_completed", "elapsed_seconds", "provider_turns", "tool_calls",
        "input_tokens", "output_tokens", "screenshots", "ocr_regions",
        "consecutive_failures",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID")
    try:
        return BatchTransition(
            sequence=value.get("sequence"), batch_id=value.get("batch_id"),
            run_id=value.get("run_id"), status=BatchStatus(value.get("status")),
            at=value.get("at"), stop_code=value.get("stop_code"),
            items_completed=value.get("items_completed"),
            elapsed_seconds=value.get("elapsed_seconds"),
            provider_turns=value.get("provider_turns"), tool_calls=value.get("tool_calls"),
            input_tokens=value.get("input_tokens"), output_tokens=value.get("output_tokens"),
            screenshots=value.get("screenshots"), ocr_regions=value.get("ocr_regions"),
            consecutive_failures=value.get("consecutive_failures"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID") from exc


def _decode_handoff(
    value: object,
    *,
    campaign_id: str,
    manifest: CampaignManifest,
    projection: CampaignProjection,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _HANDOFF_FIELDS:
        raise CampaignStoreError("CAMPAIGN_HANDOFF_INVALID")
    try:
        next_ordinal = _require_nonnegative_int(value.get("next_item_ordinal"))
        completed_count = _require_nonnegative_int(value.get("completed_count"))
        retryable_count = _require_nonnegative_int(value.get("retryable_count"))
        uncertain_count = _require_nonnegative_int(value.get("uncertain_count"))
        last_run_id = _require_identifier(value.get("last_run_id"))
        updated_at = _require_timestamp(value.get("updated_at"))
        next_action, required_observation = _HANDOFF_DIRECTIVES[manifest.status]
    except (CampaignStoreError, KeyError) as exc:
        raise CampaignStoreError("CAMPAIGN_HANDOFF_INVALID") from exc
    if (
        value.get("campaign_id") != campaign_id
        or value.get("campaign_version") != CAMPAIGN_VERSION
        or next_ordinal <= 0
        or next_ordinal != projection.next_ordinal
        or completed_count != projection.completed_count
        or retryable_count != projection.retryable_count
        or uncertain_count != projection.uncertain_count
        or value.get("next_action") != next_action
        or value.get("required_observation") != required_observation
        or datetime.fromisoformat(updated_at) < datetime.fromisoformat(manifest.updated_at)
    ):
        raise CampaignStoreError("CAMPAIGN_HANDOFF_INVALID")
    return {
        "campaign_id": campaign_id,
        "campaign_version": CAMPAIGN_VERSION,
        "next_item_ordinal": next_ordinal,
        "completed_count": completed_count,
        "retryable_count": retryable_count,
        "uncertain_count": uncertain_count,
        "last_run_id": last_run_id,
        "next_action": next_action,
        "required_observation": required_observation,
        "updated_at": updated_at,
    }


@dataclass(frozen=True)
class CampaignControlSnapshot:
    """One stable, fully decoded read-only campaign control snapshot."""

    manifest: CampaignManifest
    items: CampaignProjection
    batches: BatchProjection
    heartbeat: CampaignHeartbeat | None
    handoff: Mapping[str, object] | None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest, CampaignManifest)
            or not isinstance(self.items, CampaignProjection)
            or not isinstance(self.batches, BatchProjection)
            or (
                self.heartbeat is not None
                and not isinstance(self.heartbeat, CampaignHeartbeat)
            )
            or (self.handoff is not None and not isinstance(self.handoff, Mapping))
        ):
            raise CampaignStoreError("CAMPAIGN_SNAPSHOT_INVALID")
        if self.handoff is not None:
            object.__setattr__(self, "handoff", MappingProxyType(dict(self.handoff)))


def _read_optional_control_file(path: Path, maximum: int) -> bytes | None:
    try:
        raw = read_shared_bytes(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise CampaignStoreError("CAMPAIGN_SNAPSHOT_READ_FAILED") from exc
    if len(raw) > maximum:
        raise CampaignStoreError("CAMPAIGN_SNAPSHOT_READ_FAILED")
    return raw


def _read_control_files(directory: Path) -> tuple[bytes | None, ...]:
    return (
        _read_optional_control_file(directory / "manifest.json", MAX_CAMPAIGN_MANIFEST_BYTES),
        _read_optional_control_file(directory / "items.jsonl", MAX_CAMPAIGN_LEDGER_BYTES),
        _read_optional_control_file(
            directory / "batches.jsonl", MAX_CAMPAIGN_BATCH_LEDGER_BYTES
        ),
        _read_optional_control_file(
            directory / "heartbeat.json", MAX_CAMPAIGN_HEARTBEAT_BYTES
        ),
        _read_optional_control_file(directory / "handoff.json", MAX_CAMPAIGN_HANDOFF_BYTES),
    )


def _json_value(raw: bytes, code: str) -> object:
    try:
        return json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignStoreError(code) from exc


def _decode_ledger_bytes(raw: bytes | None) -> CampaignProjection:
    if raw is None:
        return CampaignProjection(transitions=(), items=MappingProxyType({}))
    try:
        lines = raw.decode("utf-8").splitlines()
        transitions = tuple(_decode_transition(json.loads(line)) for line in lines if line)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID") from exc
    return reduce_item_ledger(transitions)


def _decode_batch_bytes(raw: bytes | None) -> BatchProjection:
    if raw is None:
        return BatchProjection((), None, 0)
    try:
        lines = raw.decode("utf-8").splitlines()
        transitions = tuple(_decode_batch_transition(json.loads(line)) for line in lines if line)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID") from exc
    return reduce_batch_ledger(transitions)


def read_campaign_control_snapshot(
    state_dir: Path, campaign_id: str
) -> CampaignControlSnapshot:
    """Read one lock-free campaign snapshot without blocking atomic publishers.

    Every control file is read twice through the shared-reader path. The view is
    accepted only when the entire raw tuple is byte-identical, preventing a
    passive observer from combining records across a concurrent transition.
    """

    directory = campaign_dir(state_dir, campaign_id)
    if any(
        _is_unsafe_path(path)
        for path in (state_dir, state_dir / "campaigns", directory)
    ) or not directory.is_dir():
        raise CampaignStoreError("CAMPAIGN_UNSAFE_PATH")

    previous = _read_control_files(directory)
    stable: tuple[bytes | None, ...] | None = None
    for _ in range(CAMPAIGN_CONTROL_SNAPSHOT_ATTEMPTS):
        current = _read_control_files(directory)
        if current == previous:
            stable = current
            break
        previous = current
    if stable is None:
        raise CampaignStoreError("CAMPAIGN_SNAPSHOT_UNSTABLE")

    manifest_raw, items_raw, batches_raw, heartbeat_raw, handoff_raw = stable
    if manifest_raw is None or not manifest_raw:
        raise CampaignStoreError("CAMPAIGN_MANIFEST_READ_FAILED")
    manifest = _decode_manifest(
        _json_value(manifest_raw, "CAMPAIGN_MANIFEST_INVALID"),
        campaign_id=campaign_id,
    )
    items = _decode_ledger_bytes(items_raw)
    batches = _decode_batch_bytes(batches_raw)
    heartbeat = (
        None
        if heartbeat_raw is None
        else _decode_heartbeat(
            _json_value(heartbeat_raw, "CAMPAIGN_HEARTBEAT_INVALID"),
            campaign_id=campaign_id,
        )
    )
    handoff = (
        None
        if handoff_raw is None
        else _decode_handoff(
            _json_value(handoff_raw, "CAMPAIGN_HANDOFF_INVALID"),
            campaign_id=campaign_id,
            manifest=manifest,
            projection=items,
        )
    )
    return CampaignControlSnapshot(manifest, items, batches, heartbeat, handoff)


class CampaignStore:
    """Run-lock-bound, append-only campaign manifest and item ledger storage."""

    def __init__(self, state_dir: Path, lock: RunLock) -> None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        if not isinstance(lock, RunLock):
            raise ValueError("lock must be a RunLock")
        self.state_dir = state_dir
        self.lock = lock

    def _require_lock(self) -> None:
        if not self.lock.acquired:
            raise CampaignStoreError("CAMPAIGN_LOCK_REQUIRED")

    def _directory(self, campaign_id: str) -> Path:
        directory = campaign_dir(self.state_dir, campaign_id)
        if any(
            _is_unsafe_path(path)
            for path in (self.state_dir, self.state_dir / "campaigns", directory)
        ):
            raise CampaignStoreError("CAMPAIGN_UNSAFE_PATH")
        return directory

    def _path(self, campaign_id: str, name: str) -> Path:
        return self._directory(campaign_id) / name

    @staticmethod
    def _replace_with_retry(temporary: Path, path: Path) -> None:
        """Rename ``temporary`` onto ``path``, retrying a transient hold.

        On Windows a real-time file scanner can hold the destination open for a
        few milliseconds, and ``os.replace`` then fails with
        ERROR_ACCESS_DENIED. Retrying is safe: the rename either happened or it
        did not, so a lost race never leaves a partial record. Only that exact
        error is retried, and only for a bounded time -- a genuine permission
        problem must still fail rather than stall.
        """

        delay = _REPLACE_RETRY_BASE_SECONDS
        for _ in range(_REPLACE_RETRY_ATTEMPTS - 1):
            try:
                publish_atomically(temporary, path)
                return
            except PermissionError:
                time.sleep(delay)
                delay *= 2
        publish_atomically(temporary, path)

    @staticmethod
    def _atomic_write(path: Path, data: bytes, *, create: bool, maximum: int) -> None:
        if not data or len(data) > maximum:
            raise CampaignStoreError("CAMPAIGN_TOO_LARGE")
        if create and path.exists():
            raise CampaignStoreError("CAMPAIGN_ALREADY_EXISTS")
        path.parent.mkdir(parents=True, exist_ok=True)
        if _is_unsafe_path(path.parent) or _is_unsafe_path(path):
            raise CampaignStoreError("CAMPAIGN_UNSAFE_PATH")
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(prefix=".campaign-", suffix=".tmp", dir=path.parent)
            temporary = Path(raw_path)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "wb") as file:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
            if create and path.exists():
                raise CampaignStoreError("CAMPAIGN_ALREADY_EXISTS")
            CampaignStore._replace_with_retry(temporary, path)
            temporary = None
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except CampaignStoreError:
            raise
        except FileNotFoundError as exc:
            # A directory this method just created cannot be missing, so this
            # is the path itself being unusable -- on Windows almost always a
            # MAX_PATH overflow. Reporting it as a write failure sends the
            # reader looking for a storage fault that is not there.
            raise CampaignStoreError("CAMPAIGN_PATH_UNAVAILABLE") from exc
        except OSError as exc:
            raise CampaignStoreError("CAMPAIGN_WRITE_FAILED") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def create(self, manifest: CampaignManifest) -> CampaignManifest:
        self._require_lock()
        if not isinstance(manifest, CampaignManifest):
            raise CampaignStoreError("CAMPAIGN_MANIFEST_INVALID")
        directory = self._directory(manifest.campaign_id)
        manifest_path = directory / "manifest.json"
        encoded = _canonical(manifest.as_json()) + b"\n"
        self._atomic_write(
            manifest_path,
            encoded,
            create=True,
            maximum=MAX_CAMPAIGN_MANIFEST_BYTES,
        )
        return manifest

    def read_manifest(self, campaign_id: str) -> CampaignManifest:
        self._require_lock()
        path = self._path(campaign_id, "manifest.json")
        try:
            raw = read_shared_bytes(path)
            value = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_MANIFEST_READ_FAILED") from exc
        if not raw or len(raw) > MAX_CAMPAIGN_MANIFEST_BYTES:
            raise CampaignStoreError("CAMPAIGN_MANIFEST_READ_FAILED")
        return _decode_manifest(value, campaign_id=campaign_id)

    def transition_pause_state(
        self,
        campaign_id: str,
        *,
        status: CampaignStatus,
        at: str,
    ) -> CampaignManifest:
        """Atomically pause or resume control state without starting work."""

        self._require_lock()
        if not isinstance(status, CampaignStatus) or status not in {
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSED,
        }:
            raise CampaignStoreError("CAMPAIGN_PAUSE_INVALID")
        try:
            _require_timestamp(at)
        except CampaignStoreError as exc:
            raise CampaignStoreError("CAMPAIGN_PAUSE_INVALID") from exc
        current = self.read_manifest(campaign_id)
        if datetime.fromisoformat(at) < datetime.fromisoformat(current.updated_at):
            raise CampaignStoreError("CAMPAIGN_PAUSE_INVALID")
        if current.status is status:
            return current
        if (current.status, status) not in {
            (CampaignStatus.RUNNING, CampaignStatus.PAUSED),
            (CampaignStatus.PAUSED, CampaignStatus.RUNNING),
        }:
            raise CampaignStoreError("CAMPAIGN_PAUSE_INVALID")
        updated = CampaignManifest(
            campaign_id=current.campaign_id,
            kind=current.kind,
            policy_digest=current.policy_digest,
            schema_digest=current.schema_digest,
            created_at=current.created_at,
            updated_at=at,
            status=status,
        )
        self._atomic_write(
            self._path(campaign_id, "manifest.json"),
            _canonical(updated.as_json()) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_MANIFEST_BYTES,
        )
        return updated

    def complete_campaign(self, campaign_id: str, *, at: str) -> CampaignManifest:
        """Atomically mark one running campaign complete without starting work."""

        self._require_lock()
        try:
            _require_timestamp(at)
        except CampaignStoreError as exc:
            raise CampaignStoreError("CAMPAIGN_COMPLETION_INVALID") from exc
        current = self.read_manifest(campaign_id)
        if (
            current.status is not CampaignStatus.RUNNING
            or datetime.fromisoformat(at) < datetime.fromisoformat(current.updated_at)
        ):
            raise CampaignStoreError("CAMPAIGN_COMPLETION_INVALID")
        updated = CampaignManifest(
            campaign_id=current.campaign_id,
            kind=current.kind,
            policy_digest=current.policy_digest,
            schema_digest=current.schema_digest,
            created_at=current.created_at,
            updated_at=at,
            status=CampaignStatus.COMPLETED,
        )
        self._atomic_write(
            self._path(campaign_id, "manifest.json"),
            _canonical(updated.as_json()) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_MANIFEST_BYTES,
        )
        return updated

    def read_heartbeat(self, campaign_id: str) -> CampaignHeartbeat | None:
        """Read fixed liveness state without inferring that a worker is alive."""

        self._require_lock()
        self.read_manifest(campaign_id)
        path = self._path(campaign_id, "heartbeat.json")
        try:
            raw = read_shared_bytes(path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_READ_FAILED") from exc
        if not raw or len(raw) > MAX_CAMPAIGN_HEARTBEAT_BYTES:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_READ_FAILED")
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_INVALID") from exc
        return _decode_heartbeat(value, campaign_id=campaign_id)

    def write_heartbeat(
        self, campaign_id: str, heartbeat: CampaignHeartbeat
    ) -> CampaignHeartbeat:
        """Atomically create or advance one run's bounded heartbeat record."""

        self._require_lock()
        if not isinstance(heartbeat, CampaignHeartbeat) or heartbeat.campaign_id != campaign_id:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_INVALID")
        current = self.read_heartbeat(campaign_id)
        if current is not None:
            if (
                heartbeat.run_id != current.run_id
                or heartbeat.started_at != current.started_at
                or datetime.fromisoformat(heartbeat.heartbeat_at)
                < datetime.fromisoformat(current.heartbeat_at)
                or (
                    heartbeat.heartbeat_at == current.heartbeat_at
                    and heartbeat != current
                )
            ):
                raise CampaignStoreError("CAMPAIGN_HEARTBEAT_CONFLICT")
        self._atomic_write(
            self._path(campaign_id, "heartbeat.json"),
            _canonical(heartbeat.as_json()) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_HEARTBEAT_BYTES,
        )
        return heartbeat

    def recover_stale_heartbeat(
        self,
        campaign_id: str,
        *,
        stale_run_id: str,
        replacement: CampaignHeartbeat,
        now: datetime,
    ) -> CampaignHeartbeat:
        """Replace one proven-stale owner after every claimed item is released."""

        self._require_lock()
        try:
            _require_identifier(stale_run_id)
        except CampaignStoreError as exc:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RECOVERY_INVALID") from exc
        if (
            not isinstance(replacement, CampaignHeartbeat)
            or replacement.campaign_id != campaign_id
            or replacement.run_id == stale_run_id
        ):
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RECOVERY_INVALID")

        from .stale_run_inspection import (
            StaleRunInspectionError,
            StaleRunState,
            inspect_stale_run,
        )

        try:
            inspection = inspect_stale_run(self, campaign_id=campaign_id, now=now)
        except StaleRunInspectionError as exc:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RECOVERY_INVALID") from exc
        current = self.read_heartbeat(campaign_id)
        if (
            inspection.state is not StaleRunState.STALE
            or inspection.leases.stale
            or current is None
            or current.run_id != stale_run_id
        ):
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RECOVERY_BLOCKED")

        replacement_started = datetime.fromisoformat(replacement.started_at)
        replacement_heartbeat = datetime.fromisoformat(replacement.heartbeat_at)
        if replacement_started != now or replacement_heartbeat != now:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RECOVERY_INVALID")
        self._atomic_write(
            self._path(campaign_id, "heartbeat.json"),
            _canonical(replacement.as_json()) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_HEARTBEAT_BYTES,
        )
        return replacement

    def replace_heartbeat_owner(
        self,
        campaign_id: str,
        *,
        current_run_id: str,
        replacement: CampaignHeartbeat,
        now: datetime,
    ) -> CampaignHeartbeat:
        """Atomically replace one exact heartbeat owner at a validated boundary."""

        self._require_lock()
        try:
            _require_identifier(current_run_id)
        except CampaignStoreError as exc:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_TRANSFER_INVALID") from exc
        if (
            not isinstance(replacement, CampaignHeartbeat)
            or replacement.campaign_id != campaign_id
            or replacement.run_id == current_run_id
            or not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_TRANSFER_INVALID")

        current = self.read_heartbeat(campaign_id)
        if current is None or current.run_id != current_run_id:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_TRANSFER_CONFLICT")
        replacement_started = datetime.fromisoformat(replacement.started_at)
        replacement_heartbeat = datetime.fromisoformat(replacement.heartbeat_at)
        if replacement_started != now or replacement_heartbeat != now:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_TRANSFER_INVALID")
        self._atomic_write(
            self._path(campaign_id, "heartbeat.json"),
            _canonical(replacement.as_json()) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_HEARTBEAT_BYTES,
        )
        return replacement

    def remove_completed_heartbeat(
        self,
        campaign_id: str,
        *,
        run_id: str,
    ) -> CampaignHeartbeat | None:
        """Remove only an exact terminal heartbeat; repeat removal is a no-op."""

        self._require_lock()
        try:
            _require_identifier(run_id)
            manifest = self.read_manifest(campaign_id)
            projection = self.read_ledger(campaign_id)
            handoff = self.read_handoff(campaign_id)
            heartbeat = self.read_heartbeat(campaign_id)
        except CampaignStoreError as exc:
            raise CampaignStoreError(
                "CAMPAIGN_HEARTBEAT_RETIREMENT_INVALID"
            ) from exc
        if (
            manifest.status is not CampaignStatus.COMPLETED
            or not projection.items
            or any(
                item.status is not ItemStatus.COMMITTED
                for item in projection.items.values()
            )
            or handoff.get("last_run_id") != run_id
            or handoff.get("next_action") != "none_completed"
            or handoff.get("required_observation") != "none"
        ):
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RETIREMENT_BLOCKED")
        if heartbeat is None:
            return None
        if heartbeat.run_id != run_id:
            raise CampaignStoreError("CAMPAIGN_HEARTBEAT_RETIREMENT_CONFLICT")
        path = self._path(campaign_id, "heartbeat.json")
        try:
            path.unlink()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CampaignStoreError(
                "CAMPAIGN_HEARTBEAT_RETIREMENT_FAILED"
            ) from exc
        return heartbeat

    def read_ledger(self, campaign_id: str) -> CampaignProjection:
        self._require_lock()
        path = self._path(campaign_id, "items.jsonl")
        try:
            raw = read_shared_bytes(path)
        except FileNotFoundError:
            return CampaignProjection(transitions=(), items=MappingProxyType({}))
        except OSError as exc:
            raise CampaignStoreError("CAMPAIGN_LEDGER_READ_FAILED") from exc
        if len(raw) > MAX_CAMPAIGN_LEDGER_BYTES:
            raise CampaignStoreError("CAMPAIGN_LEDGER_TOO_LARGE")
        try:
            lines = raw.decode("utf-8").splitlines()
            transitions = tuple(_decode_transition(json.loads(line)) for line in lines if line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID") from exc
        return reduce_item_ledger(transitions)

    def append(self, campaign_id: str, transition: ItemTransition) -> CampaignProjection:
        self._require_lock()
        if not isinstance(transition, ItemTransition):
            raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID")
        self.read_manifest(campaign_id)
        projection = self.read_ledger(campaign_id)
        next_transition = ItemTransition(
            sequence=len(projection.transitions) + 1,
            ordinal=transition.ordinal,
            item_key=transition.item_key,
            status=transition.status,
            attempt=transition.attempt,
            at=transition.at,
            run_id=transition.run_id,
            lease_expires_at=transition.lease_expires_at,
            boundary=transition.boundary,
            code=transition.code,
            content_digest=transition.content_digest,
        )
        updated = reduce_item_ledger((*projection.transitions, next_transition))
        encoded = b"".join(_canonical(entry.as_json()) + b"\n" for entry in updated.transitions)
        self._atomic_write(
            self._path(campaign_id, "items.jsonl"),
            encoded,
            create=False,
            maximum=MAX_CAMPAIGN_LEDGER_BYTES,
        )
        return updated

    def read_batches(self, campaign_id: str) -> BatchProjection:
        self._require_lock()
        path = self._path(campaign_id, "batches.jsonl")
        try:
            raw = read_shared_bytes(path)
        except FileNotFoundError:
            return BatchProjection((), None, 0)
        except OSError as exc:
            raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_READ_FAILED") from exc
        if len(raw) > MAX_CAMPAIGN_BATCH_LEDGER_BYTES:
            raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_TOO_LARGE")
        try:
            lines = raw.decode("utf-8").splitlines()
            transitions = tuple(_decode_batch_transition(json.loads(line)) for line in lines if line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID") from exc
        return reduce_batch_ledger(transitions)

    def append_batch(self, campaign_id: str, transition: BatchTransition) -> BatchProjection:
        self._require_lock()
        if not isinstance(transition, BatchTransition):
            raise CampaignStoreError("CAMPAIGN_BATCH_LEDGER_INVALID")
        self.read_manifest(campaign_id)
        projection = self.read_batches(campaign_id)
        next_transition = BatchTransition(
            sequence=len(projection.transitions) + 1,
            batch_id=transition.batch_id, run_id=transition.run_id,
            status=transition.status, at=transition.at, stop_code=transition.stop_code,
            items_completed=transition.items_completed, elapsed_seconds=transition.elapsed_seconds,
            provider_turns=transition.provider_turns, tool_calls=transition.tool_calls,
            input_tokens=transition.input_tokens, output_tokens=transition.output_tokens,
            screenshots=transition.screenshots, ocr_regions=transition.ocr_regions,
            consecutive_failures=transition.consecutive_failures,
        )
        updated = reduce_batch_ledger((*projection.transitions, next_transition))
        encoded = b"".join(_canonical(entry.as_json()) + b"\n" for entry in updated.transitions)
        self._atomic_write(
            self._path(campaign_id, "batches.jsonl"), encoded, create=False,
            maximum=MAX_CAMPAIGN_BATCH_LEDGER_BYTES,
        )
        return updated

    def read_discovery_passes(self, campaign_id: str) -> DiscoveryPassProjection:
        self._require_lock()
        path = self._path(campaign_id, "discovery.jsonl")
        try:
            raw = read_shared_bytes(path)
        except FileNotFoundError:
            return DiscoveryPassProjection(())
        except OSError as exc:
            raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_READ_FAILED") from exc
        if len(raw) > MAX_CAMPAIGN_DISCOVERY_LEDGER_BYTES:
            raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_TOO_LARGE")
        try:
            lines = raw.decode("utf-8").splitlines()
            passes = tuple(_decode_discovery_pass(json.loads(line)) for line in lines if line)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID") from exc
        return reduce_discovery_passes(passes)

    def append_discovery_pass(
        self, campaign_id: str, entry: DiscoveryPass
    ) -> DiscoveryPassProjection:
        self._require_lock()
        if not isinstance(entry, DiscoveryPass):
            raise CampaignStoreError("CAMPAIGN_DISCOVERY_LEDGER_INVALID")
        self.read_manifest(campaign_id)
        projection = self.read_discovery_passes(campaign_id)
        next_entry = DiscoveryPass(
            sequence=projection.pass_count + 1,
            at=entry.at,
            source_digest=entry.source_digest,
            observed_count=entry.observed_count,
            new_count=entry.new_count,
            run_id=entry.run_id,
        )
        updated = reduce_discovery_passes((*projection.passes, next_entry))
        encoded = b"".join(_canonical(item.as_json()) + b"\n" for item in updated.passes)
        self._atomic_write(
            self._path(campaign_id, "discovery.jsonl"),
            encoded,
            create=False,
            maximum=MAX_CAMPAIGN_DISCOVERY_LEDGER_BYTES,
        )
        return updated

    def write_handoff(self, campaign_id: str, *, last_run_id: str) -> dict[str, object]:
        """Atomically replace a status-aware handoff derived from durable state."""

        self._require_lock()
        manifest = self.read_manifest(campaign_id)
        projection = self.read_ledger(campaign_id)
        _require_identifier(last_run_id)
        try:
            next_action, required_observation = _HANDOFF_DIRECTIVES[manifest.status]
        except KeyError as exc:
            raise CampaignStoreError("CAMPAIGN_HANDOFF_INVALID") from exc
        payload: dict[str, object] = {
            "campaign_id": manifest.campaign_id,
            "campaign_version": CAMPAIGN_VERSION,
            "next_item_ordinal": projection.next_ordinal,
            "completed_count": projection.completed_count,
            "retryable_count": projection.retryable_count,
            "uncertain_count": projection.uncertain_count,
            "last_run_id": last_run_id,
            "next_action": next_action,
            "required_observation": required_observation,
            "updated_at": _utc_now(),
        }
        self._atomic_write(
            self._path(campaign_id, "handoff.json"),
            _canonical(payload) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_HANDOFF_BYTES,
        )
        return payload

    def read_handoff(self, campaign_id: str) -> dict[str, object]:
        """Read and revalidate a handoff against current durable control state."""

        self._require_lock()
        manifest = self.read_manifest(campaign_id)
        projection = self.read_ledger(campaign_id)
        path = self._path(campaign_id, "handoff.json")
        try:
            raw = read_shared_bytes(path)
        except OSError as exc:
            raise CampaignStoreError("CAMPAIGN_HANDOFF_READ_FAILED") from exc
        if not raw or len(raw) > MAX_CAMPAIGN_HANDOFF_BYTES:
            raise CampaignStoreError("CAMPAIGN_HANDOFF_READ_FAILED")
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_HANDOFF_INVALID") from exc
        return _decode_handoff(
            value,
            campaign_id=campaign_id,
            manifest=manifest,
            projection=projection,
        )


__all__ = [
    "CAMPAIGN_VERSION",
    "CAMPAIGN_CONTROL_SNAPSHOT_ATTEMPTS",
    "MAX_CAMPAIGN_BATCH_LEDGER_BYTES",
    "MAX_CAMPAIGN_DISCOVERY_LEDGER_BYTES",
    "MAX_CAMPAIGN_DISCOVERY_PASSES",
    "MAX_CAMPAIGN_HANDOFF_BYTES",
    "MAX_CAMPAIGN_HEARTBEAT_BYTES",
    "MAX_CAMPAIGN_ITEMS",
    "MAX_HEARTBEAT_FRESHNESS_SECONDS",
    "MAX_ITEM_LEASE_SECONDS",
    "BatchProjection",
    "BatchStatus",
    "BatchTransition",
    "CampaignManifest",
    "CampaignHeartbeat",
    "CampaignControlSnapshot",
    "CampaignProjection",
    "CampaignStatus",
    "CampaignStore",
    "CampaignStoreError",
    "DiscoveryPass",
    "DiscoveryPassProjection",
    "ItemStatus",
    "ItemTransition",
    "campaign_dir",
    "campaign_path_is_unsafe",
    "reduce_batch_ledger",
    "reduce_discovery_passes",
    "reduce_item_ledger",
    "read_campaign_control_snapshot",
]
