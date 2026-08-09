"""Explicit-only local SQLite memory with conservative content rejection."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from uuid import uuid4

from .types import MemoryContextItem


MAX_MEMORY_CONTENT_CHARS = 4096
MAX_MEMORY_SCOPE_CHARS = 128
MAX_RUN_MEMORIES = 8
MAX_RUN_MEMORY_CHARS = 8192
_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}\Z")
_FORBIDDEN_CONTENT = (
    re.compile(
        r"(?i)\b(password|passcode|api[ _-]?key|secret|access[ _-]?token|refresh[ _-]?token|otp|one[ _-]?time|authorization|bearer)\b"
    ),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(ref_\d+|window_\d+)\b"),
    re.compile(r"(?i)\b(screenshot|screen capture)\b"),
    re.compile(r"(?i)data:image/|iVBORw0KGgo"),
)


class MemoryStoreError(ValueError):
    """Fixed memory validation/storage error without candidate content."""


class MemoryKind(str, Enum):
    PREFERENCE = "preference"
    VERIFIED_PROCEDURE = "verified_procedure"


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    kind: MemoryKind
    content: str
    source: str
    scope: str
    expires_at: str
    created_at: str

    def as_json(self) -> dict[str, str]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "content": self.content,
            "source": self.source,
            "scope": self.scope,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
        }


def _timestamp(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise MemoryStoreError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MemoryStoreError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise MemoryStoreError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_memory_content(
    content: str,
    *,
    max_chars: int = MAX_MEMORY_CONTENT_CHARS,
) -> str:
    """Apply the shared no-secret/no-raw-desktop text boundary."""

    if (
        not isinstance(max_chars, int)
        or isinstance(max_chars, bool)
        or not 1 <= max_chars <= MAX_MEMORY_CONTENT_CHARS
    ):
        raise MemoryStoreError("MEMORY_CONTENT_REJECTED")
    if not isinstance(content, str) or not content.strip():
        raise MemoryStoreError("memory content must be non-empty")
    if len(content) > max_chars or any(ord(char) < 32 for char in content):
        raise MemoryStoreError("MEMORY_CONTENT_REJECTED")
    if any(pattern.search(content) for pattern in _FORBIDDEN_CONTENT):
        raise MemoryStoreError("MEMORY_CONTENT_REJECTED")
    return content.strip()


def validate_memory_candidate(
    *,
    kind: MemoryKind,
    content: str,
    source: str,
    scope: str,
    expires_at: str,
    confirmed: bool,
    now: datetime | None = None,
) -> tuple[str, str]:
    if not isinstance(kind, MemoryKind):
        raise MemoryStoreError("kind must be preference or verified_procedure")
    if confirmed is not True:
        raise MemoryStoreError("MEMORY_REQUIRES_EXPLICIT_CONFIRMATION")
    if source != "user_confirmed":
        raise MemoryStoreError("MEMORY_SOURCE_NOT_TRUSTED")
    safe_content = validate_memory_content(content)
    if not isinstance(scope, str) or _SCOPE.fullmatch(scope) is None:
        raise MemoryStoreError("memory scope must be a path-safe logical scope")
    parsed_expiry = _timestamp(expires_at, "expires_at")
    current = datetime.now(UTC) if now is None else now.astimezone(UTC)
    if parsed_expiry <= current:
        raise MemoryStoreError("memory expiry must be in the future")
    return safe_content, _iso(parsed_expiry)


class MemoryStore:
    """Small explicit memory store; it never extracts or promotes content."""

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("memory path must be an absolute Path")
        self.path = path

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            connection = sqlite3.connect(self.path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL CHECK(type IN ('preference', 'verified_procedure')),
                    content TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source = 'user_confirmed'),
                    scope TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            return connection
        except sqlite3.Error as exc:
            raise MemoryStoreError("MEMORY_DATABASE_ERROR") from exc
    def add(
        self,
        *,
        kind: MemoryKind,
        content: str,
        source: str,
        scope: str,
        expires_at: str,
        confirmed: bool,
        now: datetime | None = None,
    ) -> MemoryRecord:
        current = datetime.now(UTC) if now is None else now.astimezone(UTC)
        safe_content, safe_expiry = validate_memory_candidate(
            kind=kind,
            content=content,
            source=source,
            scope=scope,
            expires_at=expires_at,
            confirmed=confirmed,
            now=current,
        )
        record = MemoryRecord(
            id=uuid4().hex,
            kind=kind,
            content=safe_content,
            source=source,
            scope=scope,
            expires_at=safe_expiry,
            created_at=_iso(current),
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO memory(id, type, content, source, scope, expiry, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.id,
                        record.kind.value,
                        record.content,
                        record.source,
                        record.scope,
                        record.expires_at,
                        record.created_at,
                    ),
                )
        except sqlite3.Error as exc:
            raise MemoryStoreError("MEMORY_DATABASE_ERROR") from exc
        return record

    def list(
        self,
        *,
        scope: str | None = None,
        include_expired: bool = False,
        now: datetime | None = None,
    ) -> tuple[MemoryRecord, ...]:
        if scope is not None and _SCOPE.fullmatch(scope) is None:
            raise MemoryStoreError("memory scope must be a path-safe logical scope")
        current = _iso(datetime.now(UTC) if now is None else now.astimezone(UTC))
        clauses: list[str] = []
        values: list[str] = []
        if scope is not None:
            clauses.append("scope = ?")
            values.append(scope)
        if not include_expired:
            clauses.append("expiry > ?")
            values.append(current)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        try:
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT id, type, content, source, scope, expiry, created_at FROM memory"
                    + where
                    + " ORDER BY created_at, id",
                    values,
                ).fetchall()
        except sqlite3.Error as exc:
            raise MemoryStoreError("MEMORY_DATABASE_ERROR") from exc
        return tuple(
            MemoryRecord(
                id=row["id"],
                kind=MemoryKind(row["type"]),
                content=row["content"],
                source=row["source"],
                scope=row["scope"],
                expires_at=row["expiry"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    def delete(self, memory_id: str) -> bool:
        if not isinstance(memory_id, str) or re.fullmatch(r"[0-9a-f]{32}", memory_id) is None:
            raise MemoryStoreError("memory id must be a 32-character hex identifier")
        try:
            with self._connect() as connection:
                cursor = connection.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            raise MemoryStoreError("MEMORY_DATABASE_ERROR") from exc


def build_memory_context(
    records: tuple[MemoryRecord, ...], *, now: datetime | None = None
) -> tuple[MemoryContextItem, ...]:
    """Bound explicitly selected active records before provider disclosure."""

    if not isinstance(records, tuple) or not all(
        isinstance(item, MemoryRecord) for item in records
    ):
        raise MemoryStoreError("MEMORY_CONTEXT_INVALID")
    if len(records) > MAX_RUN_MEMORIES:
        raise MemoryStoreError("MEMORY_CONTEXT_LIMIT_EXCEEDED")
    current = datetime.now(UTC) if now is None else now.astimezone(UTC)
    validated: list[tuple[MemoryRecord, str]] = []
    for item in records:
        content, _ = validate_memory_candidate(
            kind=item.kind,
            content=item.content,
            source=item.source,
            scope=item.scope,
            expires_at=item.expires_at,
            confirmed=True,
            now=current,
        )
        validated.append((item, content))
    if sum(len(content) for _, content in validated) > MAX_RUN_MEMORY_CHARS:
        raise MemoryStoreError("MEMORY_CONTEXT_LIMIT_EXCEEDED")
    return tuple(
        MemoryContextItem(
            kind=item.kind.value,
            content=content,
            source=item.source,
            scope=item.scope,
        )
        for item, content in validated
    )


__all__ = [
    "MemoryStoreError",
    "MemoryKind",
    "MemoryRecord",
    "MemoryStore",
    "build_memory_context",
    "validate_memory_content",
    "validate_memory_candidate",
]
