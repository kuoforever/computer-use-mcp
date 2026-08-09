"""Private L1 quarantine for non-authorizing candidate facts.

The extractor accepts only a fresh H5 boolean or integer fact correlated with
one verified-success L0 episode.  The store is isolated from explicit memory,
provider context, policy, Runner, MCP, and desktop paths.  Confirmation is only
a quarantine lifecycle fact; it never promotes or injects the candidate.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import stat
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping

from .episode_outcome import (
    EpisodeOutcome,
    EpisodeOutcomeLabel,
    ExternalEffectEvidence,
)
from .memory import MemoryStoreError, validate_memory_content
from .types import JSONValue
from .world_state import (
    FactAvailability,
    FactExtractionMethod,
    FactScope,
    FactType,
    WorldStateContext,
    WorldStateError,
    WorldStateSnapshot,
    inspect_world_fact,
)


CANDIDATE_FACT_VERSION = 1
CANDIDATE_FACT_EVENT_VERSION = 1
CANDIDATE_FACT_EXTRACTOR_VERSION = 1
CANDIDATE_FACT_DATA_CLASS = "private_candidate_fact_quarantine"
CANDIDATE_FACT_USE = "operator_review_only"
MAX_CANDIDATE_FACTS = 1_000
MAX_CANDIDATE_EVENTS = 64
MAX_CANDIDATE_RECORD_BYTES = 32 * 1024
MAX_CANDIDATE_EVENT_BYTES = 8 * 1024
MAX_CANDIDATE_LIFETIME_DAYS = 365
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_IDENTIFIER = re.compile(
    r"(?i)(password|passcode|api[_-]?key|secret|token|otp|authorization|bearer)"
)


class CandidateFactError(RuntimeError):
    """Fixed content-free L1 validation or persistence failure."""


class CandidateFactStatus(str, Enum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    EXPIRED = "expired"


class CandidateFactAction(str, Enum):
    EXTRACTED = "extracted"
    CONFIRMED = "confirmed"
    EDITED = "edited"
    EXPIRED = "expired"
    DELETED = "deleted"


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CandidateFactError("CANDIDATE_FACT_INVALID") from exc


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise CandidateFactError("CANDIDATE_FACT_INVALID")
    return value


def _require_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or _FORBIDDEN_IDENTIFIER.search(value) is not None
    ):
        if isinstance(value, str) and _FORBIDDEN_IDENTIFIER.search(value) is not None:
            raise CandidateFactError("CANDIDATE_FACT_CONTENT_REJECTED")
        raise CandidateFactError("CANDIDATE_FACT_INVALID")
    try:
        validate_memory_content(value, max_chars=128)
    except MemoryStoreError as exc:
        raise CandidateFactError("CANDIDATE_FACT_CONTENT_REJECTED") from exc
    return value


def _require_nonnegative(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise CandidateFactError("CANDIDATE_FACT_INVALID")
    return value


def _aware_utc(value: object, *, code: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise CandidateFactError(code)
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID") from exc
    return _aware_utc(parsed, code="CANDIDATE_FACT_TIME_INVALID")


def _iso(value: datetime) -> str:
    return _aware_utc(value, code="CANDIDATE_FACT_TIME_INVALID").isoformat().replace(
        "+00:00", "Z"
    )


def _validate_expiry(expires_at: datetime, *, now: datetime) -> str:
    expiry = _aware_utc(expires_at, code="CANDIDATE_FACT_EXPIRY_INVALID")
    current = _aware_utc(now, code="CANDIDATE_FACT_TIME_INVALID")
    if expiry <= current or expiry > current + timedelta(days=MAX_CANDIDATE_LIFETIME_DAYS):
        raise CandidateFactError("CANDIDATE_FACT_EXPIRY_INVALID")
    return _iso(expiry)


def _validate_fact_value(fact_type: FactType, value: object) -> bool | int:
    if fact_type is FactType.BOOLEAN and type(value) is bool:
        return value
    if (
        fact_type is FactType.INTEGER
        and type(value) is int
        and -9_007_199_254_740_991 <= value <= 9_007_199_254_740_991
    ):
        return value
    if fact_type in {FactType.TEXT, FactType.IDENTIFIER}:
        raise CandidateFactError("CANDIDATE_FACT_CONTENT_REJECTED")
    raise CandidateFactError("CANDIDATE_FACT_VALUE_INVALID")


@dataclass(frozen=True)
class CandidateFactSource:
    """Content-free correlation to one L0 episode and one fresh H5 fact."""

    episode_id: str
    source_record_digest: str
    manifest_digest: str
    checkpoint_sequence: int
    snapshot_digest: str
    fact_digest: str
    evidence_digest: str
    extraction_method: FactExtractionMethod
    source_tool: str
    observation_epoch: int
    mcp_generation: int
    window_identity_digest: str | None = None
    extractor_version: int = CANDIDATE_FACT_EXTRACTOR_VERSION

    def __post_init__(self) -> None:
        for value in (
            self.episode_id,
            self.source_record_digest,
            self.snapshot_digest,
            self.fact_digest,
            self.evidence_digest,
        ):
            _require_digest(value)
        if (
            not isinstance(self.manifest_digest, str)
            or not self.manifest_digest.startswith("sha256:")
        ):
            raise CandidateFactError("CANDIDATE_FACT_SOURCE_INVALID")
        _require_digest(self.manifest_digest.removeprefix("sha256:"))
        if (
            _require_nonnegative(self.checkpoint_sequence) == 0
            or _require_nonnegative(self.observation_epoch) == 0
        ):
            raise CandidateFactError("CANDIDATE_FACT_SOURCE_INVALID")
        _require_nonnegative(self.mcp_generation)
        if not isinstance(self.extraction_method, FactExtractionMethod):
            raise CandidateFactError("CANDIDATE_FACT_SOURCE_INVALID")
        _require_identifier(self.source_tool)
        if self.window_identity_digest is not None:
            _require_digest(self.window_identity_digest)
        if (
            not isinstance(self.extractor_version, int)
            or isinstance(self.extractor_version, bool)
            or self.extractor_version != CANDIDATE_FACT_EXTRACTOR_VERSION
        ):
            raise CandidateFactError("CANDIDATE_FACT_SOURCE_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "episode_id": self.episode_id,
            "source_record_digest": self.source_record_digest,
            "manifest_digest": self.manifest_digest,
            "checkpoint_sequence": self.checkpoint_sequence,
            "snapshot_digest": self.snapshot_digest,
            "fact_digest": self.fact_digest,
            "evidence_digest": self.evidence_digest,
            "extraction_method": self.extraction_method.value,
            "source_tool": self.source_tool,
            "observation_epoch": self.observation_epoch,
            "mcp_generation": self.mcp_generation,
            "window_identity_digest": self.window_identity_digest,
            "extractor_version": self.extractor_version,
        }


@dataclass(frozen=True)
class CandidateFactRecord:
    candidate_id: str
    status: CandidateFactStatus
    revision: int
    fact_id: str
    fact_type: FactType
    value: bool | int
    scope: FactScope
    source: CandidateFactSource
    created_at: str
    updated_at: str
    expires_at: str
    operator_edited: bool = False
    version: int = CANDIDATE_FACT_VERSION

    def __post_init__(self) -> None:
        _require_digest(self.candidate_id)
        if not isinstance(self.status, CandidateFactStatus):
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        _require_nonnegative(self.revision)
        _require_identifier(self.fact_id)
        if not isinstance(self.fact_type, FactType):
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        _validate_fact_value(self.fact_type, self.value)
        if not isinstance(self.scope, FactScope):
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        if not isinstance(self.source, CandidateFactSource):
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        created = _parse_time(self.created_at)
        updated = _parse_time(self.updated_at)
        expiry = _parse_time(self.expires_at)
        if updated < created or expiry < created:
            raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID")
        if self.status is CandidateFactStatus.EXPIRED:
            if expiry != updated:
                raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID")
        elif (
            expiry <= updated
            or expiry > created + timedelta(days=MAX_CANDIDATE_LIFETIME_DAYS)
        ):
            raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID")
        if type(self.operator_edited) is not bool:
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version != CANDIDATE_FACT_VERSION
        ):
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        if (self.scope is FactScope.WINDOW) != (
            self.source.window_identity_digest is not None
        ):
            raise CandidateFactError("CANDIDATE_FACT_SOURCE_INVALID")

    def status_at(self, now: datetime) -> CandidateFactStatus:
        current = _aware_utc(now, code="CANDIDATE_FACT_TIME_INVALID")
        if self.status is CandidateFactStatus.EXPIRED or _parse_time(
            self.expires_at
        ) <= current:
            return CandidateFactStatus.EXPIRED
        return self.status

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "candidate_fact_version": self.version,
            "candidate_id": self.candidate_id,
            "status": self.status.value,
            "revision": self.revision,
            "fact_id": self.fact_id,
            "fact_type": self.fact_type.value,
            "value": self.value,
            "scope": self.scope.value,
            "source": self.source.to_payload(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "operator_edited": self.operator_edited,
            "data_class": CANDIDATE_FACT_DATA_CLASS,
            "use": CANDIDATE_FACT_USE,
            "capabilities": {
                "inject_memory": False,
                "disclose_to_provider": False,
                "select_strategy": False,
                "promote": False,
                "authorize": False,
                "dispatch": False,
            },
            "privacy": {
                "contains_raw_task": False,
                "contains_model_prose": False,
                "contains_raw_tool_result": False,
                "contains_observation_text": False,
                "contains_image": False,
                "contains_typed_text": False,
                "contains_ui_reference": False,
                "contains_window_title": False,
                "contains_secret": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class CandidateFactEvent:
    candidate_id: str
    sequence: int
    action: CandidateFactAction
    occurred_at: str
    from_status: CandidateFactStatus | None
    to_status: CandidateFactStatus | None
    from_revision: int | None
    to_revision: int | None
    prior_digest: str | None
    record_digest: str | None
    version: int = CANDIDATE_FACT_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_digest(self.candidate_id)
        if _require_nonnegative(self.sequence) == 0:
            raise CandidateFactError("CANDIDATE_FACT_EVENT_INVALID")
        if not isinstance(self.action, CandidateFactAction):
            raise CandidateFactError("CANDIDATE_FACT_EVENT_INVALID")
        _parse_time(self.occurred_at)
        for status_value in (self.from_status, self.to_status):
            if status_value is not None and not isinstance(
                status_value, CandidateFactStatus
            ):
                raise CandidateFactError("CANDIDATE_FACT_EVENT_INVALID")
        for revision in (self.from_revision, self.to_revision):
            if revision is not None:
                _require_nonnegative(revision)
        for digest_value in (self.prior_digest, self.record_digest):
            if digest_value is not None:
                _require_digest(digest_value)
        if self.action is CandidateFactAction.EXTRACTED:
            valid = (
                self.sequence == 1
                and self.from_status is None
                and self.to_status is CandidateFactStatus.SUGGESTED
                and self.from_revision is None
                and self.to_revision == 0
                and self.prior_digest is None
                and self.record_digest is not None
            )
        elif self.action is CandidateFactAction.DELETED:
            valid = (
                self.from_status is not None
                and self.to_status is None
                and self.from_revision is not None
                and self.to_revision is None
                and self.prior_digest is not None
                and self.record_digest is None
            )
        else:
            valid = (
                self.from_status is not None
                and self.to_status is not None
                and self.from_revision is not None
                and self.to_revision == self.from_revision + 1
                and self.prior_digest is not None
                and self.record_digest is not None
            )
            if self.action is CandidateFactAction.CONFIRMED:
                valid = valid and (
                    self.from_status is CandidateFactStatus.SUGGESTED
                    and self.to_status is CandidateFactStatus.CONFIRMED
                )
            elif self.action is CandidateFactAction.EDITED:
                valid = valid and (
                    self.from_status
                    in {CandidateFactStatus.SUGGESTED, CandidateFactStatus.CONFIRMED}
                    and self.to_status is CandidateFactStatus.SUGGESTED
                )
            elif self.action is CandidateFactAction.EXPIRED:
                valid = valid and (
                    self.from_status
                    in {CandidateFactStatus.SUGGESTED, CandidateFactStatus.CONFIRMED}
                    and self.to_status is CandidateFactStatus.EXPIRED
                )
        if not valid or self.version != CANDIDATE_FACT_EVENT_VERSION:
            raise CandidateFactError("CANDIDATE_FACT_EVENT_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "candidate_fact_event_version": self.version,
            "candidate_id": self.candidate_id,
            "sequence": self.sequence,
            "action": self.action.value,
            "occurred_at": self.occurred_at,
            "from_status": None if self.from_status is None else self.from_status.value,
            "to_status": None if self.to_status is None else self.to_status.value,
            "from_revision": self.from_revision,
            "to_revision": self.to_revision,
            "prior_digest": self.prior_digest,
            "record_digest": self.record_digest,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


_RECORD_FIELDS = frozenset(
    {
        "candidate_fact_version",
        "candidate_id",
        "status",
        "revision",
        "fact_id",
        "fact_type",
        "value",
        "scope",
        "source",
        "created_at",
        "updated_at",
        "expires_at",
        "operator_edited",
        "data_class",
        "use",
        "capabilities",
        "privacy",
    }
)
_SOURCE_FIELDS = frozenset(
    {
        "episode_id",
        "source_record_digest",
        "manifest_digest",
        "checkpoint_sequence",
        "snapshot_digest",
        "fact_digest",
        "evidence_digest",
        "extraction_method",
        "source_tool",
        "observation_epoch",
        "mcp_generation",
        "window_identity_digest",
        "extractor_version",
    }
)
_CAPABILITIES = {
    "inject_memory": False,
    "disclose_to_provider": False,
    "select_strategy": False,
    "promote": False,
    "authorize": False,
    "dispatch": False,
}
_PRIVACY = {
    "contains_raw_task": False,
    "contains_model_prose": False,
    "contains_raw_tool_result": False,
    "contains_observation_text": False,
    "contains_image": False,
    "contains_typed_text": False,
    "contains_ui_reference": False,
    "contains_window_title": False,
    "contains_secret": False,
}


def _strict_object(raw: bytes, *, maximum: int) -> dict[str, object]:
    if not isinstance(raw, bytes) or not raw or len(raw) > maximum:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
            value[key] = item
        return value

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except CandidateFactError:
        raise
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID") from exc
    if not isinstance(value, dict):
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
    return value


def _decode_source(value: object) -> CandidateFactSource:
    if not isinstance(value, Mapping) or frozenset(value) != _SOURCE_FIELDS:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
    try:
        return CandidateFactSource(
            episode_id=value["episode_id"],  # type: ignore[arg-type]
            source_record_digest=value["source_record_digest"],  # type: ignore[arg-type]
            manifest_digest=value["manifest_digest"],  # type: ignore[arg-type]
            checkpoint_sequence=value["checkpoint_sequence"],  # type: ignore[arg-type]
            snapshot_digest=value["snapshot_digest"],  # type: ignore[arg-type]
            fact_digest=value["fact_digest"],  # type: ignore[arg-type]
            evidence_digest=value["evidence_digest"],  # type: ignore[arg-type]
            extraction_method=FactExtractionMethod(value["extraction_method"]),
            source_tool=value["source_tool"],  # type: ignore[arg-type]
            observation_epoch=value["observation_epoch"],  # type: ignore[arg-type]
            mcp_generation=value["mcp_generation"],  # type: ignore[arg-type]
            window_identity_digest=value["window_identity_digest"],  # type: ignore[arg-type]
            extractor_version=value["extractor_version"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, CandidateFactError) as exc:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID") from exc


def _decode_record(raw: bytes) -> CandidateFactRecord:
    value = _strict_object(raw, maximum=MAX_CANDIDATE_RECORD_BYTES)
    if (
        frozenset(value) != _RECORD_FIELDS
        or value.get("data_class") != CANDIDATE_FACT_DATA_CLASS
        or value.get("use") != CANDIDATE_FACT_USE
        or value.get("capabilities") != _CAPABILITIES
        or value.get("privacy") != _PRIVACY
    ):
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
    try:
        return CandidateFactRecord(
            candidate_id=value["candidate_id"],  # type: ignore[arg-type]
            status=CandidateFactStatus(value["status"]),
            revision=value["revision"],  # type: ignore[arg-type]
            fact_id=value["fact_id"],  # type: ignore[arg-type]
            fact_type=FactType(value["fact_type"]),
            value=value["value"],  # type: ignore[arg-type]
            scope=FactScope(value["scope"]),
            source=_decode_source(value["source"]),
            created_at=value["created_at"],  # type: ignore[arg-type]
            updated_at=value["updated_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
            operator_edited=value["operator_edited"],  # type: ignore[arg-type]
            version=value["candidate_fact_version"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, CandidateFactError) as exc:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID") from exc


def _decode_event(raw: bytes) -> CandidateFactEvent:
    value = _strict_object(raw, maximum=MAX_CANDIDATE_EVENT_BYTES)
    expected = frozenset(
        {
            "candidate_fact_event_version",
            "candidate_id",
            "sequence",
            "action",
            "occurred_at",
            "from_status",
            "to_status",
            "from_revision",
            "to_revision",
            "prior_digest",
            "record_digest",
        }
    )
    if frozenset(value) != expected:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
    try:
        return CandidateFactEvent(
            candidate_id=value["candidate_id"],  # type: ignore[arg-type]
            sequence=value["sequence"],  # type: ignore[arg-type]
            action=CandidateFactAction(value["action"]),
            occurred_at=value["occurred_at"],  # type: ignore[arg-type]
            from_status=(
                None
                if value["from_status"] is None
                else CandidateFactStatus(value["from_status"])
            ),
            to_status=(
                None
                if value["to_status"] is None
                else CandidateFactStatus(value["to_status"])
            ),
            from_revision=value["from_revision"],  # type: ignore[arg-type]
            to_revision=value["to_revision"],  # type: ignore[arg-type]
            prior_digest=value["prior_digest"],  # type: ignore[arg-type]
            record_digest=value["record_digest"],  # type: ignore[arg-type]
            version=value["candidate_fact_event_version"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, CandidateFactError) as exc:
        raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID") from exc


def _candidate_identity(source: CandidateFactSource) -> str:
    if not isinstance(source, CandidateFactSource):
        raise CandidateFactError("CANDIDATE_FACT_SOURCE_INVALID")
    return _digest(
        {
            "candidate_fact_version": CANDIDATE_FACT_VERSION,
            "episode_id": source.episode_id,
            "fact_digest": source.fact_digest,
            "extractor_version": source.extractor_version,
        }
    )


class CandidateFactQuarantine:
    """Private transactional store with revision CAS and content-free events."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("quarantine path must be an absolute Path")
        self.path = path

    def _prepare_path(self) -> None:
        if self.path.exists() and self.path.is_symlink():
            raise CandidateFactError("CANDIDATE_FACT_PATH_UNSAFE")
        if self.path.parent.exists() and self.path.parent.is_symlink():
            raise CandidateFactError("CANDIDATE_FACT_PATH_UNSAFE")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(self.path.parent, stat.S_IRWXU)
        except OSError as exc:
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc

    def _connect(self, *, create: bool) -> sqlite3.Connection | None:
        if not self.path.exists() and not create:
            return None
        self._prepare_path()
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode = DELETE")
            connection.execute("PRAGMA synchronous = FULL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, CANDIDATE_FACT_VERSION}:
                raise CandidateFactError("CANDIDATE_FACT_DATABASE_INVALID")
            if version == 0:
                if not create:
                    connection.close()
                    raise CandidateFactError("CANDIDATE_FACT_DATABASE_INVALID")
                connection.executescript(
                    """
                    CREATE TABLE candidate_fact (
                        candidate_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        revision INTEGER NOT NULL,
                        expires_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        record_digest TEXT NOT NULL,
                        record_json BLOB NOT NULL
                    );
                    CREATE TABLE candidate_fact_event (
                        candidate_id TEXT NOT NULL,
                        sequence INTEGER NOT NULL,
                        event_digest TEXT NOT NULL,
                        event_json BLOB NOT NULL,
                        PRIMARY KEY(candidate_id, sequence)
                    );
                    PRAGMA user_version = 1;
                    """
                )
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
            return connection
        except CandidateFactError:
            if connection is not None:
                connection.close()
            raise
        except sqlite3.Error as exc:
            if connection is not None:
                connection.close()
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        except OSError as exc:
            if connection is not None:
                connection.close()
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc

    @staticmethod
    def _read_row(row: sqlite3.Row) -> CandidateFactRecord:
        raw = row["record_json"]
        if not isinstance(raw, bytes):
            raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
        record = _decode_record(raw)
        if (
            row["candidate_id"] != record.candidate_id
            or row["status"] != record.status.value
            or row["revision"] != record.revision
            or row["expires_at"] != record.expires_at
            or row["updated_at"] != record.updated_at
            or row["record_digest"] != record.digest
        ):
            raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
        return record

    @staticmethod
    def _event_row(event: CandidateFactEvent) -> tuple[object, ...]:
        encoded = _canonical(event.to_payload())
        if len(encoded) > MAX_CANDIDATE_EVENT_BYTES:
            raise CandidateFactError("CANDIDATE_FACT_EVENT_INVALID")
        return (event.candidate_id, event.sequence, event.digest, encoded)

    @staticmethod
    def _read_events(
        connection: sqlite3.Connection,
        candidate_id: str,
    ) -> tuple[CandidateFactEvent, ...]:
        rows = connection.execute(
            "SELECT * FROM candidate_fact_event WHERE candidate_id = ? "
            "ORDER BY sequence",
            (candidate_id,),
        ).fetchall()
        events: list[CandidateFactEvent] = []
        for row in rows:
            raw = row["event_json"]
            if not isinstance(raw, bytes):
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
            event = _decode_event(raw)
            if (
                row["candidate_id"] != event.candidate_id
                or row["sequence"] != event.sequence
                or row["event_digest"] != event.digest
            ):
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
            events.append(event)
        if len(events) > MAX_CANDIDATE_EVENTS:
            raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
        return tuple(events)

    @staticmethod
    def _validate_history(
        events: tuple[CandidateFactEvent, ...],
        record: CandidateFactRecord | None,
    ) -> None:
        if not events:
            if record is not None:
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
            return
        if (
            events[0].action is not CandidateFactAction.EXTRACTED
            or events[0].sequence != 1
        ):
            raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
        for expected_sequence, event in enumerate(events, start=1):
            if event.sequence != expected_sequence:
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
            if expected_sequence == 1:
                continue
            prior = events[expected_sequence - 2]
            if (
                prior.record_digest != event.prior_digest
                or prior.to_status is not event.from_status
                or prior.to_revision != event.from_revision
                or prior.action is CandidateFactAction.DELETED
                or _parse_time(event.occurred_at) < _parse_time(prior.occurred_at)
            ):
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
        tail = events[-1]
        if record is None:
            if tail.action is not CandidateFactAction.DELETED:
                raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")
        elif (
            tail.action is CandidateFactAction.DELETED
            or tail.record_digest != record.digest
            or tail.to_status is not record.status
            or tail.to_revision != record.revision
            or events[0].occurred_at != record.created_at
            or tail.occurred_at != record.updated_at
        ):
            raise CandidateFactError("CANDIDATE_FACT_STORE_INVALID")

    @staticmethod
    def _record_row(record: CandidateFactRecord) -> tuple[object, ...]:
        encoded = _canonical(record.to_payload())
        if len(encoded) > MAX_CANDIDATE_RECORD_BYTES:
            raise CandidateFactError("CANDIDATE_FACT_INVALID")
        return (
            record.candidate_id,
            record.status.value,
            record.revision,
            record.expires_at,
            record.updated_at,
            record.digest,
            encoded,
        )

    def _create_from_extractor(
        self, record: CandidateFactRecord
    ) -> CandidateFactRecord:
        """Persist only the record produced by ``extract_candidate_fact``."""
        if (
            not isinstance(record, CandidateFactRecord)
            or record.status is not CandidateFactStatus.SUGGESTED
            or record.revision != 0
            or record.operator_edited
            or record.candidate_id != _candidate_identity(record.source)
        ):
            raise CandidateFactError("CANDIDATE_FACT_CREATE_INVALID")
        connection = self._connect(create=True)
        assert connection is not None
        event = CandidateFactEvent(
            candidate_id=record.candidate_id,
            sequence=1,
            action=CandidateFactAction.EXTRACTED,
            occurred_at=record.created_at,
            from_status=None,
            to_status=record.status,
            from_revision=None,
            to_revision=record.revision,
            prior_digest=None,
            record_digest=record.digest,
        )
        try:
            connection.execute("BEGIN IMMEDIATE")
            history_count = connection.execute(
                "SELECT COUNT(*) FROM candidate_fact_event WHERE sequence = 1"
            ).fetchone()[0]
            prior_events = connection.execute(
                "SELECT COUNT(*) FROM candidate_fact_event WHERE candidate_id = ?",
                (record.candidate_id,),
            ).fetchone()[0]
            if history_count >= MAX_CANDIDATE_FACTS:
                raise CandidateFactError("CANDIDATE_FACT_LIMIT_EXCEEDED")
            if prior_events:
                raise CandidateFactError("CANDIDATE_FACT_EXISTS")
            connection.execute(
                "INSERT INTO candidate_fact VALUES (?, ?, ?, ?, ?, ?, ?)",
                self._record_row(record),
            )
            connection.execute(
                "INSERT INTO candidate_fact_event VALUES (?, ?, ?, ?)",
                self._event_row(event),
            )
            connection.commit()
            return record
        except CandidateFactError:
            connection.rollback()
            raise
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise CandidateFactError("CANDIDATE_FACT_EXISTS") from exc
        except sqlite3.Error as exc:
            connection.rollback()
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        finally:
            connection.close()

    def get(self, candidate_id: str) -> CandidateFactRecord | None:
        _require_digest(candidate_id)
        connection = self._connect(create=False)
        if connection is None:
            return None
        try:
            row = connection.execute(
                "SELECT * FROM candidate_fact WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            record = None if row is None else self._read_row(row)
            events = self._read_events(connection, candidate_id)
            self._validate_history(events, record)
            return record
        except sqlite3.Error as exc:
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        finally:
            connection.close()

    def list(
        self,
        *,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> tuple[CandidateFactRecord, ...]:
        if type(include_expired) is not bool:
            raise CandidateFactError("CANDIDATE_FACT_LIST_INVALID")
        current = datetime.now(UTC).replace(microsecond=0) if now is None else now
        current = _aware_utc(current, code="CANDIDATE_FACT_TIME_INVALID")
        connection = self._connect(create=False)
        if connection is None:
            return ()
        try:
            rows = connection.execute(
                "SELECT * FROM candidate_fact ORDER BY updated_at, candidate_id"
            ).fetchall()
            records = tuple(self._read_row(row) for row in rows)
            for record in records:
                self._validate_history(
                    self._read_events(connection, record.candidate_id),
                    record,
                )
            if include_expired:
                return records
            return tuple(
                record
                for record in records
                if record.status_at(current) is not CandidateFactStatus.EXPIRED
            )
        except sqlite3.Error as exc:
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        finally:
            connection.close()

    def events(self, candidate_id: str) -> tuple[CandidateFactEvent, ...]:
        _require_digest(candidate_id)
        connection = self._connect(create=False)
        if connection is None:
            return ()
        try:
            row = connection.execute(
                "SELECT * FROM candidate_fact WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            record = None if row is None else self._read_row(row)
            events = self._read_events(connection, candidate_id)
            self._validate_history(events, record)
            return events
        except sqlite3.Error as exc:
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        finally:
            connection.close()

    def _mutate(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        now: datetime,
        action: CandidateFactAction,
        update: Callable[[CandidateFactRecord, str], CandidateFactRecord],
    ) -> CandidateFactRecord:
        _require_digest(candidate_id)
        _require_nonnegative(expected_revision)
        timestamp = _iso(now)
        connection = self._connect(create=False)
        if connection is None:
            raise CandidateFactError("CANDIDATE_FACT_NOT_FOUND")
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM candidate_fact WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                raise CandidateFactError("CANDIDATE_FACT_NOT_FOUND")
            current = self._read_row(row)
            if current.revision != expected_revision:
                raise CandidateFactError("CANDIDATE_FACT_REVISION_CONFLICT")
            if _parse_time(timestamp) < _parse_time(current.updated_at):
                raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID")
            if current.status_at(now) is CandidateFactStatus.EXPIRED:
                raise CandidateFactError("CANDIDATE_FACT_EXPIRED")
            events = self._read_events(connection, candidate_id)
            self._validate_history(events, current)
            count = len(events)
            if count >= MAX_CANDIDATE_EVENTS - 1:
                raise CandidateFactError("CANDIDATE_FACT_EVENT_LIMIT_EXCEEDED")
            next_record = update(current, timestamp)
            event = CandidateFactEvent(
                candidate_id=candidate_id,
                sequence=count + 1,
                action=action,
                occurred_at=timestamp,
                from_status=current.status,
                to_status=next_record.status,
                from_revision=current.revision,
                to_revision=next_record.revision,
                prior_digest=current.digest,
                record_digest=next_record.digest,
            )
            cursor = connection.execute(
                "UPDATE candidate_fact SET status = ?, revision = ?, expires_at = ?, "
                "updated_at = ?, record_digest = ?, record_json = ? "
                "WHERE candidate_id = ? AND revision = ?",
                (
                    next_record.status.value,
                    next_record.revision,
                    next_record.expires_at,
                    next_record.updated_at,
                    next_record.digest,
                    _canonical(next_record.to_payload()),
                    candidate_id,
                    expected_revision,
                ),
            )
            if cursor.rowcount != 1:
                raise CandidateFactError("CANDIDATE_FACT_REVISION_CONFLICT")
            connection.execute(
                "INSERT INTO candidate_fact_event VALUES (?, ?, ?, ?)",
                self._event_row(event),
            )
            connection.commit()
            return next_record
        except CandidateFactError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        finally:
            connection.close()

    def confirm(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        confirmed: bool,
        now: datetime | None = None,
    ) -> CandidateFactRecord:
        if confirmed is not True:
            raise CandidateFactError("CANDIDATE_FACT_CONFIRMATION_REQUIRED")
        current = datetime.now(UTC).replace(microsecond=0) if now is None else now

        def update(record: CandidateFactRecord, timestamp: str) -> CandidateFactRecord:
            if record.status is not CandidateFactStatus.SUGGESTED:
                raise CandidateFactError("CANDIDATE_FACT_TRANSITION_INVALID")
            return replace(
                record,
                status=CandidateFactStatus.CONFIRMED,
                revision=record.revision + 1,
                updated_at=timestamp,
            )

        return self._mutate(
            candidate_id,
            expected_revision=expected_revision,
            now=current,
            action=CandidateFactAction.CONFIRMED,
            update=update,
        )

    def edit(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        value: bool | int | None = None,
        expires_at: datetime | None = None,
        now: datetime | None = None,
    ) -> CandidateFactRecord:
        if value is None and expires_at is None:
            raise CandidateFactError("CANDIDATE_FACT_EDIT_EMPTY")
        current = datetime.now(UTC).replace(microsecond=0) if now is None else now
        current = _aware_utc(current, code="CANDIDATE_FACT_TIME_INVALID")

        def update(record: CandidateFactRecord, timestamp: str) -> CandidateFactRecord:
            next_value = (
                record.value
                if value is None
                else _validate_fact_value(record.fact_type, value)
            )
            next_expiry = (
                record.expires_at
                if expires_at is None
                else _validate_expiry(expires_at, now=current)
            )
            return replace(
                record,
                status=CandidateFactStatus.SUGGESTED,
                revision=record.revision + 1,
                value=next_value,
                expires_at=next_expiry,
                updated_at=timestamp,
                operator_edited=True,
            )

        return self._mutate(
            candidate_id,
            expected_revision=expected_revision,
            now=current,
            action=CandidateFactAction.EDITED,
            update=update,
        )

    def expire(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> CandidateFactRecord:
        current = datetime.now(UTC).replace(microsecond=0) if now is None else now

        def update(record: CandidateFactRecord, timestamp: str) -> CandidateFactRecord:
            return replace(
                record,
                status=CandidateFactStatus.EXPIRED,
                revision=record.revision + 1,
                expires_at=timestamp,
                updated_at=timestamp,
            )

        return self._mutate(
            candidate_id,
            expected_revision=expected_revision,
            now=current,
            action=CandidateFactAction.EXPIRED,
            update=update,
        )

    def delete(
        self,
        candidate_id: str,
        *,
        expected_revision: int,
        now: datetime | None = None,
    ) -> bool:
        _require_digest(candidate_id)
        _require_nonnegative(expected_revision)
        current_time = (
            datetime.now(UTC).replace(microsecond=0) if now is None else now
        )
        timestamp = _iso(current_time)
        connection = self._connect(create=False)
        if connection is None:
            return False
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM candidate_fact WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                return False
            record = self._read_row(row)
            if record.revision != expected_revision:
                raise CandidateFactError("CANDIDATE_FACT_REVISION_CONFLICT")
            if _parse_time(timestamp) < _parse_time(record.updated_at):
                raise CandidateFactError("CANDIDATE_FACT_TIME_INVALID")
            events = self._read_events(connection, candidate_id)
            self._validate_history(events, record)
            count = len(events)
            if count >= MAX_CANDIDATE_EVENTS:
                raise CandidateFactError("CANDIDATE_FACT_EVENT_LIMIT_EXCEEDED")
            event = CandidateFactEvent(
                candidate_id=candidate_id,
                sequence=count + 1,
                action=CandidateFactAction.DELETED,
                occurred_at=timestamp,
                from_status=record.status,
                to_status=None,
                from_revision=record.revision,
                to_revision=None,
                prior_digest=record.digest,
                record_digest=None,
            )
            cursor = connection.execute(
                "DELETE FROM candidate_fact WHERE candidate_id = ? AND revision = ?",
                (candidate_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise CandidateFactError("CANDIDATE_FACT_REVISION_CONFLICT")
            connection.execute(
                "INSERT INTO candidate_fact_event VALUES (?, ?, ?, ?)",
                self._event_row(event),
            )
            connection.commit()
            return True
        except CandidateFactError:
            connection.rollback()
            raise
        except sqlite3.Error as exc:
            connection.rollback()
            raise CandidateFactError("CANDIDATE_FACT_DATABASE_ERROR") from exc
        finally:
            connection.close()


def extract_candidate_fact(
    quarantine: CandidateFactQuarantine,
    *,
    episode: EpisodeOutcome,
    snapshot: WorldStateSnapshot,
    fact_id: str,
    context: WorldStateContext,
    now: datetime,
    expires_at: datetime,
) -> CandidateFactRecord:
    """Validate one L0/H5 correlation, then quarantine one inert suggestion."""

    if (
        not isinstance(quarantine, CandidateFactQuarantine)
        or not isinstance(episode, EpisodeOutcome)
        or not isinstance(snapshot, WorldStateSnapshot)
        or not isinstance(context, WorldStateContext)
    ):
        raise CandidateFactError("CANDIDATE_FACT_INPUT_INVALID")
    current = _aware_utc(now, code="CANDIDATE_FACT_TIME_INVALID")
    expiry = _validate_expiry(expires_at, now=current)
    safe_fact_id = _require_identifier(fact_id)
    if int(current.timestamp() * 1_000) != context.now_ms:
        raise CandidateFactError("CANDIDATE_FACT_TIME_MISMATCH")
    if (
        episode.outcome is not EpisodeOutcomeLabel.VERIFIED_SUCCESS
        or episode.external_effect is ExternalEffectEvidence.UNKNOWN
        or episode.run_id != snapshot.run_id
        or episode.run_id != context.run_id
        or episode.verified_observation_epoch is None
        or episode.verified_observation_epoch != context.observation_epoch
    ):
        raise CandidateFactError("CANDIDATE_FACT_EPISODE_INELIGIBLE")
    fact = next((item for item in snapshot.facts if item.fact_id == safe_fact_id), None)
    if fact is None:
        raise CandidateFactError("CANDIDATE_FACT_UNAVAILABLE")
    if fact.fact_type not in {FactType.BOOLEAN, FactType.INTEGER}:
        raise CandidateFactError("CANDIDATE_FACT_CONTENT_REJECTED")
    try:
        inspection = inspect_world_fact(
            snapshot,
            safe_fact_id,
            context,
            required_type=fact.fact_type,
        )
    except WorldStateError as exc:
        raise CandidateFactError("CANDIDATE_FACT_UNAVAILABLE") from exc
    if (
        inspection.availability is not FactAvailability.FRESH
        or inspection.fact_type is None
        or inspection.value is None
        or inspection.fact_digest is None
        or inspection.evidence_digest is None
    ):
        raise CandidateFactError("CANDIDATE_FACT_UNAVAILABLE")
    value = _validate_fact_value(inspection.fact_type, inspection.value)
    evidence = fact.evidence
    source = CandidateFactSource(
        episode_id=episode.episode_id,
        source_record_digest=episode.source_record_digest,
        manifest_digest=episode.manifest_digest,
        checkpoint_sequence=episode.checkpoint_sequence,
        snapshot_digest=snapshot.digest,
        fact_digest=inspection.fact_digest,
        evidence_digest=inspection.evidence_digest,
        extraction_method=evidence.extraction_method,
        source_tool=evidence.source_tool,
        observation_epoch=evidence.observation_epoch,
        mcp_generation=evidence.mcp_generation,
        window_identity_digest=(
            None if evidence.window is None else evidence.window.digest
        ),
    )
    candidate_id = _candidate_identity(source)
    timestamp = _iso(current)
    record = CandidateFactRecord(
        candidate_id=candidate_id,
        status=CandidateFactStatus.SUGGESTED,
        revision=0,
        fact_id=safe_fact_id,
        fact_type=inspection.fact_type,
        value=value,
        scope=fact.scope,
        source=source,
        created_at=timestamp,
        updated_at=timestamp,
        expires_at=expiry,
    )
    return quarantine._create_from_extractor(record)


__all__ = [
    "CANDIDATE_FACT_DATA_CLASS",
    "CANDIDATE_FACT_EVENT_VERSION",
    "CANDIDATE_FACT_EXTRACTOR_VERSION",
    "CANDIDATE_FACT_USE",
    "CANDIDATE_FACT_VERSION",
    "MAX_CANDIDATE_EVENTS",
    "MAX_CANDIDATE_FACTS",
    "MAX_CANDIDATE_LIFETIME_DAYS",
    "CandidateFactAction",
    "CandidateFactError",
    "CandidateFactEvent",
    "CandidateFactQuarantine",
    "CandidateFactRecord",
    "CandidateFactSource",
    "CandidateFactStatus",
    "extract_candidate_fact",
]
