"""Private, read-only Approval Inbox projection and attention lifecycle.

The inbox is a bounded local product surface, never an approval or execution
surface.  Pending records retain only Host identity, digest, classification,
and expiry facts needed to correlate the already-bound Decision Card.  Raw
arguments, task text, model prose, UI content, typed values, credentials, and
tool results never enter this lane.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from math import ceil
from pathlib import Path
from typing import Protocol

from .atomic_file import read_shared_bytes
from .decision_cards import DecisionCard
from .types import ApprovalRequest, JSONValue


APPROVAL_INBOX_VERSION = 1
APPROVAL_NOTICE_VERSION = 1
DEFAULT_APPROVAL_INBOX_LIMIT = 20
MAX_APPROVAL_INBOX_LIMIT = 100
MAX_APPROVAL_INBOX_RECORDS = 1_000
MAX_APPROVAL_INBOX_BYTES = 16 * 1024

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset(
    {
        "approval_inbox_version",
        "request_id",
        "run_id",
        "turn_id",
        "call_id",
        "tool_name",
        "action_label",
        "call_digest",
        "card_digest",
        "opened_at",
        "expires_at",
    }
)
_ACTION_LABELS = {
    "activate_window": "Activate window",
    "click": "Click",
    "scroll": "Scroll",
    "drag": "Drag",
    "type": "Type text",
    "key": "Keyboard shortcut",
}

_NOTICE_TITLE = "Guarded Desktop Agent"
_NOTICE_BODY = "Approval needed. Review the bound local approval surface."


class ApprovalInboxError(RuntimeError):
    """Fixed failure from Approval Inbox persistence or projection."""


class ApprovalInboxStatus(str, Enum):
    PENDING = "pending_at_last_record"
    EXPIRED = "expired"


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
    return parsed.astimezone(UTC)


def _aware_utc(value: datetime, *, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ApprovalInboxError(code)
    return value.astimezone(UTC)


def _safe_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
    return value


@dataclass(frozen=True)
class ApprovalInboxRecord:
    request_id: str
    run_id: str
    turn_id: str
    call_id: str
    tool_name: str
    action_label: str
    call_digest: str
    card_digest: str
    opened_at: str
    expires_at: str

    def __post_init__(self) -> None:
        for value in (self.request_id, self.run_id, self.turn_id, self.call_id):
            _safe_id(value)
        if self.tool_name not in _ACTION_LABELS:
            raise ApprovalInboxError("APPROVAL_INBOX_ACTION_UNSUPPORTED")
        if self.action_label != _ACTION_LABELS[self.tool_name]:
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
        _digest(self.call_digest)
        _digest(self.card_digest)
        if _timestamp(self.expires_at) <= _timestamp(self.opened_at):
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "approval_inbox_version": APPROVAL_INBOX_VERSION,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "turn_id": self.turn_id,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "action_label": self.action_label,
            "call_digest": self.call_digest,
            "card_digest": self.card_digest,
            "opened_at": self.opened_at,
            "expires_at": self.expires_at,
        }


@dataclass(frozen=True)
class ApprovalNotice:
    """Fixed-content notification; ``notice_id`` is routing metadata only."""

    notice_id: str

    def __post_init__(self) -> None:
        _safe_id(self.notice_id)

    @property
    def title(self) -> str:
        return _NOTICE_TITLE

    @property
    def body(self) -> str:
        return _NOTICE_BODY

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "approval_notice_version": APPROVAL_NOTICE_VERSION,
            "category": "approval_required",
            "title": self.title,
            "body": self.body,
            "interactive": False,
            "capabilities": {
                "approve": False,
                "deny": False,
                "dispatch": False,
            },
        }


class ApprovalNotificationPort(Protocol):
    """Presentation-only notification delivery with no approval callback."""

    def show(self, notice: ApprovalNotice) -> None: ...

    def withdraw(self, notice_id: str) -> None: ...


@dataclass(frozen=True)
class ApprovalInboxItem:
    record: ApprovalInboxRecord
    status: ApprovalInboxStatus
    remaining_seconds: int

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "request_id": self.record.request_id,
            "identity": {
                "run_id": self.record.run_id,
                "turn_id": self.record.turn_id,
                "call_id": self.record.call_id,
            },
            "tool_name": self.record.tool_name,
            "action_label": self.record.action_label,
            "call_digest": self.record.call_digest,
            "card_digest": self.record.card_digest,
            "opened_at": self.record.opened_at,
            "expires_at": self.record.expires_at,
            "status": self.status.value,
            "remaining_seconds": self.remaining_seconds,
            "liveness_claimed": False,
        }


@dataclass(frozen=True)
class ApprovalInboxProjection:
    items: tuple[ApprovalInboxItem, ...]
    total_records: int
    unavailable_records: int

    def as_json(self) -> dict[str, JSONValue]:
        return {
            "approval_inbox_version": APPROVAL_INBOX_VERSION,
            "source": "validated_local_pending_records",
            "read_only": True,
            "liveness_claimed": False,
            "capabilities": {
                "approve": False,
                "deny": False,
                "defer": False,
                "takeover": False,
                "dispatch": False,
            },
            "total_records": self.total_records,
            "displayed_records": len(self.items),
            "unavailable_records": self.unavailable_records,
            "items": [item.as_json() for item in self.items],
        }


class LocalApprovalInbox:
    """Strict private pending-record persistence without task-state authority."""

    def __init__(self, state_dir: Path) -> None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        self.state_dir = state_dir

    @property
    def directory(self) -> Path:
        return self.state_dir / "approval-inbox"

    def _path(self, request_id: str) -> Path:
        return self.directory / f"{_safe_id(request_id)}.json"

    def _reject_unsafe_path(self, path: Path) -> None:
        current = path
        while True:
            if current.exists() and current.is_symlink():
                raise ApprovalInboxError("APPROVAL_INBOX_PATH_UNSAFE")
            if current == self.state_dir:
                return
            if current.parent == current:
                raise ApprovalInboxError("APPROVAL_INBOX_PATH_UNSAFE")
            current = current.parent

    @staticmethod
    def _decode(payload: object) -> ApprovalInboxRecord:
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
        if payload.get("approval_inbox_version") != APPROVAL_INBOX_VERSION:
            raise ApprovalInboxError("APPROVAL_INBOX_VERSION_UNSUPPORTED")
        return ApprovalInboxRecord(
            request_id=payload["request_id"],  # type: ignore[arg-type]
            run_id=payload["run_id"],  # type: ignore[arg-type]
            turn_id=payload["turn_id"],  # type: ignore[arg-type]
            call_id=payload["call_id"],  # type: ignore[arg-type]
            tool_name=payload["tool_name"],  # type: ignore[arg-type]
            action_label=payload["action_label"],  # type: ignore[arg-type]
            call_digest=payload["call_digest"],  # type: ignore[arg-type]
            card_digest=payload["card_digest"],  # type: ignore[arg-type]
            opened_at=payload["opened_at"],  # type: ignore[arg-type]
            expires_at=payload["expires_at"],  # type: ignore[arg-type]
        )

    def open(
        self,
        request: ApprovalRequest,
        card: DecisionCard,
        *,
        opened_at: datetime,
    ) -> ApprovalInboxRecord:
        if not isinstance(request, ApprovalRequest) or not isinstance(card, DecisionCard):
            raise ApprovalInboxError("APPROVAL_INBOX_INPUT_INVALID")
        opened = _aware_utc(opened_at, code="APPROVAL_INBOX_TIME_INVALID")
        expires = _aware_utc(card.expires_at, code="APPROVAL_INBOX_TIME_INVALID")
        if (
            request.binding is None
            or request.binding != card.binding
            or request.request_id != card.decision_id
            or request.identity.run_id != card.binding.run_id
        ):
            raise ApprovalInboxError("APPROVAL_INBOX_BINDING_MISMATCH")
        if request.tool_name not in _ACTION_LABELS:
            raise ApprovalInboxError("APPROVAL_INBOX_ACTION_UNSUPPORTED")
        if expires <= opened:
            raise ApprovalInboxError("APPROVAL_INBOX_EXPIRED")
        record = ApprovalInboxRecord(
            request_id=request.request_id,
            run_id=request.identity.run_id,
            turn_id=request.identity.turn_id,
            call_id=request.identity.call_id,
            tool_name=request.tool_name,
            action_label=_ACTION_LABELS[request.tool_name],
            call_digest=request.call_digest,
            card_digest=card.card_digest,
            opened_at=opened.isoformat(),
            expires_at=expires.isoformat(),
        )
        path = self._path(record.request_id)
        self._reject_unsafe_path(path)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ApprovalInboxError("APPROVAL_INBOX_DIRECTORY_FAILED") from exc
        self._reject_unsafe_path(path)
        encoded = (
            json.dumps(record.as_json(), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_APPROVAL_INBOX_BYTES:
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_TOO_LARGE")
        try:
            with path.open("xb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
        except FileExistsError as exc:
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_EXISTS") from exc
        except OSError as exc:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise ApprovalInboxError("APPROVAL_INBOX_WRITE_FAILED") from exc
        return record

    def read(self, request_id: str) -> ApprovalInboxRecord:
        path = self._path(request_id)
        self._reject_unsafe_path(path)
        try:
            encoded = read_shared_bytes(path)
        except OSError as exc:
            raise ApprovalInboxError("APPROVAL_INBOX_READ_FAILED") from exc
        if not encoded or len(encoded) > MAX_APPROVAL_INBOX_BYTES:
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID")
        try:
            payload = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ApprovalInboxError("APPROVAL_INBOX_RECORD_INVALID") from exc
        record = self._decode(payload)
        if record.request_id != request_id:
            raise ApprovalInboxError("APPROVAL_INBOX_IDENTITY_MISMATCH")
        return record

    def close(self, request_id: str) -> None:
        path = self._path(request_id)
        self._reject_unsafe_path(path)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ApprovalInboxError("APPROVAL_INBOX_CLOSE_FAILED") from exc


class ApprovalAttentionLifecycle:
    """Publish/withdraw supplemental attention without affecting approval."""

    def __init__(
        self,
        store: LocalApprovalInbox,
        *,
        notifications: ApprovalNotificationPort | None = None,
    ) -> None:
        if not isinstance(store, LocalApprovalInbox):
            raise ValueError("store must be a LocalApprovalInbox")
        self.store = store
        self.notifications = notifications

    def open(
        self,
        request: ApprovalRequest,
        card: DecisionCard,
        *,
        opened_at: datetime,
    ) -> ApprovalInboxRecord:
        record = self.store.open(request, card, opened_at=opened_at)
        if self.notifications is not None:
            try:
                self.notifications.show(ApprovalNotice(record.request_id))
            except Exception:
                pass
        return record

    def close(self, request_id: str) -> None:
        if self.notifications is not None:
            try:
                self.notifications.withdraw(request_id)
            except Exception:
                pass
        self.store.close(request_id)


def build_approval_inbox(
    state_dir: Path,
    *,
    limit: int = DEFAULT_APPROVAL_INBOX_LIMIT,
    now: datetime | None = None,
) -> ApprovalInboxProjection:
    """Read strict pending records without creating state or claiming liveness."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("APPROVAL_INBOX_LIMIT_INVALID")
    observed = datetime.now(UTC) if now is None else _aware_utc(
        now, code="APPROVAL_INBOX_TIME_INVALID"
    )
    store = LocalApprovalInbox(state_dir)
    directory = store.directory
    if not directory.exists():
        return ApprovalInboxProjection((), 0, 0)
    store._reject_unsafe_path(directory)
    if not directory.is_dir():
        raise ApprovalInboxError("APPROVAL_INBOX_PATH_UNSAFE")
    entries = sorted(directory.iterdir(), key=lambda path: path.name)
    if len(entries) > MAX_APPROVAL_INBOX_RECORDS:
        raise ApprovalInboxError("APPROVAL_INBOX_RECORD_LIMIT_EXCEEDED")
    items: list[ApprovalInboxItem] = []
    unavailable = 0
    for path in entries:
        if path.suffix.lower() != ".json" or _SAFE_ID.fullmatch(path.stem) is None:
            unavailable += 1
            continue
        try:
            record = store.read(path.stem)
            expires = _timestamp(record.expires_at)
        except ApprovalInboxError:
            unavailable += 1
            continue
        remaining = max(0, ceil((expires - observed).total_seconds()))
        status = (
            ApprovalInboxStatus.PENDING if remaining > 0 else ApprovalInboxStatus.EXPIRED
        )
        items.append(ApprovalInboxItem(record, status, remaining))
    items.sort(
        key=lambda item: (
            0 if item.status is ApprovalInboxStatus.PENDING else 1,
            _timestamp(item.record.expires_at),
            item.record.request_id,
        )
    )
    return ApprovalInboxProjection(tuple(items[:limit]), len(items), unavailable)


def render_approval_inbox(projection: ApprovalInboxProjection) -> str:
    """Render a human-first local Inbox without approval affordances."""

    if not isinstance(projection, ApprovalInboxProjection):
        raise ApprovalInboxError("APPROVAL_INBOX_PROJECTION_INVALID")
    lines = [
        "Guarded Desktop Agent Approval Inbox",
        "Read-only: cannot approve, deny, defer, take over, or dispatch work.",
        "Pending state is the last validated local record; process liveness is not claimed.",
    ]
    if not projection.items:
        lines.append("No validated local approval requests found.")
    for item in projection.items:
        lines.append("")
        if item.status is ApprovalInboxStatus.PENDING:
            lines.append(f"Pending ({item.remaining_seconds}s remaining at last read)")
            next_action = "Return to the bound local Decision Card."
        else:
            lines.append("Expired")
            next_action = "Inspect Task Center; never reuse or approve this request."
        record = item.record
        lines.extend(
            [
                f"- {record.action_label} [{record.tool_name}]",
                f"  Run: {record.run_id}",
                f"  Request: {record.request_id}",
                f"  Expires: {record.expires_at}",
                f"  Call digest: {record.call_digest}",
                f"  Card digest: {record.card_digest}",
                f"  Next: {next_action}",
            ]
        )
    if len(projection.items) < projection.total_records:
        lines.append("")
        lines.append(
            f"Showing {len(projection.items)} of {projection.total_records} validated records."
        )
    if projection.unavailable_records:
        lines.append("")
        lines.append(
            f"Unavailable local records: {projection.unavailable_records}. They were excluded rather than trusted."
        )
    return "\n".join(lines) + "\n"


__all__ = [
    "APPROVAL_INBOX_VERSION",
    "APPROVAL_NOTICE_VERSION",
    "ApprovalAttentionLifecycle",
    "ApprovalInboxError",
    "ApprovalInboxItem",
    "ApprovalInboxProjection",
    "ApprovalInboxRecord",
    "ApprovalInboxStatus",
    "ApprovalNotice",
    "ApprovalNotificationPort",
    "LocalApprovalInbox",
    "build_approval_inbox",
    "render_approval_inbox",
]
