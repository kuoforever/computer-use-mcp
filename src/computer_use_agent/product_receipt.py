"""Private, versioned product receipts for Host-verified workflow outcomes.

Receipts are local product state, not authority and not Full Cycle exports.
They contain no task text, UI text, model prose, provider traffic, screenshots,
typed values, or credentials.  A receipt may be written only after the owning
workflow has completed its independent artifact and cleanup verification.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Mapping

from .atomic_file import has_unsafe_ancestor, read_shared_bytes

if TYPE_CHECKING:
    from .public_web_word_runtime import PublicWebWordResult


PRODUCT_RECEIPT_VERSION = 1
MAX_PRODUCT_RECEIPT_BYTES = 16 * 1024
MAX_ARTIFACT_PATH_CHARS = 2048
PUBLIC_WEB_WORD_WORKFLOW = "public-web-word"

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ProductReceiptError(RuntimeError):
    """Fixed failure from immutable product-receipt persistence or reading."""


@dataclass(frozen=True)
class ProductReceipt:
    """Strict local evidence for one completed fixed product workflow."""

    run_id: str
    workflow: str
    status: str
    artifact_path: Path
    artifact_sha256: str
    saved_verified: bool
    reopen_verified: bool
    fixture_cleanup_verified: bool
    verifier_cleanup_verified: bool
    verified_at: str

    def as_json(self) -> dict[str, object]:
        return {
            "product_receipt_version": PRODUCT_RECEIPT_VERSION,
            "run_id": self.run_id,
            "workflow": self.workflow,
            "status": self.status,
            "artifact": {
                "path": str(self.artifact_path),
                "sha256": self.artifact_sha256,
                "saved_verified": self.saved_verified,
                "reopen_verified": self.reopen_verified,
            },
            "cleanup": {
                "fixture_windows_verified": self.fixture_cleanup_verified,
                "verifier_windows_verified": self.verifier_cleanup_verified,
            },
            "verified_at": self.verified_at,
        }


def _validate_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or _RUN_ID.fullmatch(run_id) is None:
        raise ProductReceiptError("PRODUCT_RECEIPT_RUN_ID_INVALID")
    return run_id


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    return value


def _receipt_directory(state_dir: Path, run_id: str) -> Path:
    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    safe_run_id = _validate_run_id(run_id)
    return state_dir / "workflows" / PUBLIC_WEB_WORD_WORKFLOW / safe_run_id


def product_receipt_path(state_dir: Path, run_id: str) -> Path:
    """Return the fixed receipt path without creating any directory."""

    return _receipt_directory(state_dir, run_id) / "receipt.json"


def _reject_unsafe_path(path: Path, *, state_dir: Path) -> None:
    if has_unsafe_ancestor(path, root=state_dir):
        raise ProductReceiptError("PRODUCT_RECEIPT_PATH_UNSAFE")


def _decode_receipt(payload: object, *, expected_run_id: str) -> ProductReceipt:
    if not isinstance(payload, Mapping) or set(payload) != {
        "product_receipt_version",
        "run_id",
        "workflow",
        "status",
        "artifact",
        "cleanup",
        "verified_at",
    }:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    if payload.get("product_receipt_version") != PRODUCT_RECEIPT_VERSION:
        raise ProductReceiptError("PRODUCT_RECEIPT_VERSION_UNSUPPORTED")
    run_id = _validate_run_id(payload.get("run_id"))
    if run_id != expected_run_id:
        raise ProductReceiptError("PRODUCT_RECEIPT_RUN_ID_MISMATCH")
    if (
        payload.get("workflow") != PUBLIC_WEB_WORD_WORKFLOW
        or payload.get("status") != "COMPLETED"
    ):
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")

    artifact = payload.get("artifact")
    cleanup = payload.get("cleanup")
    if not isinstance(artifact, Mapping) or set(artifact) != {
        "path",
        "sha256",
        "saved_verified",
        "reopen_verified",
    }:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    if not isinstance(cleanup, Mapping) or set(cleanup) != {
        "fixture_windows_verified",
        "verifier_windows_verified",
    }:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")

    raw_path = artifact.get("path")
    digest = artifact.get("sha256")
    if (
        not isinstance(raw_path, str)
        or not raw_path
        or len(raw_path) > MAX_ARTIFACT_PATH_CHARS
        or "\x00" in raw_path
    ):
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    artifact_path = Path(raw_path)
    if not artifact_path.is_absolute() or artifact_path.suffix.lower() != ".docx":
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    flags = (
        artifact.get("saved_verified"),
        artifact.get("reopen_verified"),
        cleanup.get("fixture_windows_verified"),
        cleanup.get("verifier_windows_verified"),
    )
    if any(value is not True for value in flags):
        raise ProductReceiptError("PRODUCT_RECEIPT_NOT_VERIFIED")

    return ProductReceipt(
        run_id=run_id,
        workflow=PUBLIC_WEB_WORD_WORKFLOW,
        status="COMPLETED",
        artifact_path=artifact_path,
        artifact_sha256=digest,
        saved_verified=True,
        reopen_verified=True,
        fixture_cleanup_verified=True,
        verifier_cleanup_verified=True,
        verified_at=_validate_timestamp(payload.get("verified_at")),
    )


def read_product_receipt(state_dir: Path, run_id: str) -> ProductReceipt:
    """Read and fully validate one bounded immutable receipt."""

    safe_run_id = _validate_run_id(run_id)
    path = product_receipt_path(state_dir, safe_run_id)
    _reject_unsafe_path(path, state_dir=state_dir)
    try:
        encoded = read_shared_bytes(path)
    except OSError as exc:
        raise ProductReceiptError("PRODUCT_RECEIPT_READ_FAILED") from exc
    if not encoded or len(encoded) > MAX_PRODUCT_RECEIPT_BYTES:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID")
    try:
        payload = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductReceiptError("PRODUCT_RECEIPT_INVALID") from exc
    return _decode_receipt(payload, expected_run_id=safe_run_id)


def write_public_web_word_receipt(
    state_dir: Path,
    result: PublicWebWordResult,
    *,
    verified_at: datetime | None = None,
) -> ProductReceipt:
    """Persist one receipt after every product verification has passed."""

    timestamp = datetime.now(UTC) if verified_at is None else verified_at
    if (
        not isinstance(timestamp, datetime)
        or timestamp.tzinfo is None
        or timestamp.utcoffset() is None
    ):
        raise ValueError("verified_at must be timezone-aware")
    run_id = _validate_run_id(result.run_id)
    cleanup_flags = (
        bool(result.fixture_cleanup)
        and all(item.window_cleanup_verified for item in result.fixture_cleanup),
        bool(result.verifier_cleanup)
        and all(item.window_cleanup_verified for item in result.verifier_cleanup),
    )
    receipt = ProductReceipt(
        run_id=run_id,
        workflow=PUBLIC_WEB_WORD_WORKFLOW,
        status="COMPLETED",
        artifact_path=result.artifact,
        artifact_sha256=result.artifact_sha256,
        saved_verified=result.post_save_verified,
        reopen_verified=result.reopen_verified,
        fixture_cleanup_verified=cleanup_flags[0],
        verifier_cleanup_verified=cleanup_flags[1],
        verified_at=timestamp.astimezone(UTC).isoformat(),
    )
    # Reuse the reader's exact schema validation before touching disk.
    validated = _decode_receipt(receipt.as_json(), expected_run_id=run_id)
    path = product_receipt_path(state_dir, run_id)
    _reject_unsafe_path(path, state_dir=state_dir)
    if not path.parent.is_dir():
        raise ProductReceiptError("PRODUCT_RECEIPT_DIRECTORY_MISSING")
    encoded = (
        json.dumps(validated.as_json(), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(encoded) > MAX_PRODUCT_RECEIPT_BYTES:
        raise ProductReceiptError("PRODUCT_RECEIPT_TOO_LARGE")
    try:
        with path.open("xb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
    except FileExistsError as exc:
        raise ProductReceiptError("PRODUCT_RECEIPT_EXISTS") from exc
    except OSError as exc:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise ProductReceiptError("PRODUCT_RECEIPT_WRITE_FAILED") from exc
    return validated


__all__ = [
    "MAX_PRODUCT_RECEIPT_BYTES",
    "PRODUCT_RECEIPT_VERSION",
    "ProductReceipt",
    "ProductReceiptError",
    "product_receipt_path",
    "read_product_receipt",
    "write_public_web_word_receipt",
]
