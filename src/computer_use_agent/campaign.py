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
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Sequence

from .run_lock import RunLock


CAMPAIGN_VERSION = 1
MAX_CAMPAIGN_MANIFEST_BYTES = 16 * 1024
MAX_CAMPAIGN_LEDGER_BYTES = 1024 * 1024
MAX_CAMPAIGN_ITEMS = 10_000
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


_ALLOWED_TRANSITIONS = {
    ItemStatus.DISCOVERED: frozenset({ItemStatus.CLAIMED}),
    ItemStatus.CLAIMED: frozenset({ItemStatus.OBSERVED}),
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
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise CampaignStoreError("CAMPAIGN_INVALID") from exc
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
class ItemTransition:
    sequence: int
    ordinal: int
    item_key: str
    status: ItemStatus
    attempt: int
    at: str
    run_id: str | None = None
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
                for value in (self.run_id, self.boundary, self.code, self.content_digest)
            ) or self.attempt != 0:
                raise CampaignStoreError("CAMPAIGN_INVALID")
        elif self.run_id is None or self.boundary is None:
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
            "boundary": self.boundary,
            "code": self.code,
            "content_digest": self.content_digest,
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


def _decode_transition(value: object) -> ItemTransition:
    fields = {
        "sequence",
        "ordinal",
        "item_key",
        "status",
        "attempt",
        "at",
        "run_id",
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
            boundary=value.get("boundary"),
            code=value.get("code"),
            content_digest=value.get("content_digest"),
        )
    except (TypeError, ValueError) as exc:
        raise CampaignStoreError("CAMPAIGN_LEDGER_INVALID") from exc


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
            os.replace(temporary, path)
            temporary = None
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except CampaignStoreError:
            raise
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
            raw = path.read_bytes()
            value = json.loads(raw)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CampaignStoreError("CAMPAIGN_MANIFEST_READ_FAILED") from exc
        if not raw or len(raw) > MAX_CAMPAIGN_MANIFEST_BYTES:
            raise CampaignStoreError("CAMPAIGN_MANIFEST_READ_FAILED")
        return _decode_manifest(value, campaign_id=campaign_id)

    def read_ledger(self, campaign_id: str) -> CampaignProjection:
        self._require_lock()
        path = self._path(campaign_id, "items.jsonl")
        try:
            raw = path.read_bytes()
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

    def write_handoff(self, campaign_id: str, *, last_run_id: str) -> dict[str, object]:
        """Atomically replace a fixed-schema handoff derived from the ledger."""

        self._require_lock()
        manifest = self.read_manifest(campaign_id)
        projection = self.read_ledger(campaign_id)
        _require_identifier(last_run_id)
        payload: dict[str, object] = {
            "campaign_id": manifest.campaign_id,
            "campaign_version": CAMPAIGN_VERSION,
            "next_item_ordinal": projection.next_ordinal,
            "completed_count": projection.completed_count,
            "retryable_count": projection.retryable_count,
            "uncertain_count": projection.uncertain_count,
            "last_run_id": last_run_id,
            "next_action": "resume_batch",
            "required_observation": "verify_current_page_and_account_state",
            "updated_at": _utc_now(),
        }
        self._atomic_write(
            self._path(campaign_id, "handoff.json"),
            _canonical(payload) + b"\n",
            create=False,
            maximum=MAX_CAMPAIGN_MANIFEST_BYTES,
        )
        return payload


__all__ = [
    "CAMPAIGN_VERSION",
    "MAX_CAMPAIGN_ITEMS",
    "CampaignManifest",
    "CampaignProjection",
    "CampaignStatus",
    "CampaignStore",
    "CampaignStoreError",
    "ItemStatus",
    "ItemTransition",
    "campaign_dir",
    "reduce_item_ledger",
]
