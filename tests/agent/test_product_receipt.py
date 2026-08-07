from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from computer_use_agent.disposable_process import DisposableCleanup
from computer_use_agent.product_receipt import (
    ProductReceiptError,
    product_receipt_path,
    read_product_receipt,
    write_public_web_word_receipt,
)


DIGEST = "a" * 64
FORBIDDEN = "PRODUCT_RECEIPT_TASK_SECRET"


def _cleanup(application: str) -> DisposableCleanup:
    return DisposableCleanup(
        application=application,
        pid=123,
        disposition="graceful",
        exit_code=0,
        close_requests=1,
        window_cleanup_verified=True,
        process_running=False,
    )


def _result(tmp_path: Path, run_id: str = "run_1") -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        artifact=(tmp_path / "verified.docx").resolve(),
        artifact_sha256=DIGEST,
        post_save_verified=True,
        reopen_verified=True,
        fixture_cleanup=(_cleanup("chrome"), _cleanup("word")),
        verifier_cleanup=(_cleanup("word"),),
    )


def test_receipt_round_trip_is_versioned_bounded_and_content_free(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    product_receipt_path(state_dir, "run_1").parent.mkdir(parents=True)

    written = write_public_web_word_receipt(
        state_dir,
        _result(tmp_path),
        verified_at=datetime(2026, 8, 7, 8, 0, tzinfo=timezone.utc),
    )
    read = read_product_receipt(state_dir, "run_1")

    assert read == written
    assert read.artifact_sha256 == DIGEST
    assert read.verified_at == "2026-08-07T08:00:00+00:00"
    raw = product_receipt_path(state_dir, "run_1").read_text(encoding="utf-8")
    assert FORBIDDEN not in raw
    assert set(json.loads(raw)) == {
        "product_receipt_version",
        "run_id",
        "workflow",
        "status",
        "artifact",
        "cleanup",
        "verified_at",
    }


def test_receipt_requires_every_workflow_verification_before_write(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    path = product_receipt_path(state_dir, "run_1")
    path.parent.mkdir(parents=True)
    result = _result(tmp_path)
    result.reopen_verified = False

    with pytest.raises(ProductReceiptError, match="PRODUCT_RECEIPT_NOT_VERIFIED"):
        write_public_web_word_receipt(state_dir, result)

    assert not path.exists()


def test_receipt_is_immutable_and_rejects_schema_tampering(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    path = product_receipt_path(state_dir, "run_1")
    path.parent.mkdir(parents=True)
    write_public_web_word_receipt(state_dir, _result(tmp_path))

    with pytest.raises(ProductReceiptError, match="PRODUCT_RECEIPT_EXISTS"):
        write_public_web_word_receipt(state_dir, _result(tmp_path))

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["task_text"] = FORBIDDEN
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ProductReceiptError, match="PRODUCT_RECEIPT_INVALID"):
        read_product_receipt(state_dir, "run_1")


def test_receipt_rejects_non_utc_verification_timestamp(tmp_path: Path) -> None:
    state_dir = (tmp_path / "state").resolve()
    path = product_receipt_path(state_dir, "run_1")
    path.parent.mkdir(parents=True)
    write_public_web_word_receipt(state_dir, _result(tmp_path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["verified_at"] = "2026-08-07T16:00:00+08:00"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ProductReceiptError, match="PRODUCT_RECEIPT_INVALID"):
        read_product_receipt(state_dir, "run_1")


@pytest.mark.parametrize("run_id", ["../escape", "", "a" * 129])
def test_receipt_rejects_unsafe_run_identity(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(ProductReceiptError, match="PRODUCT_RECEIPT_RUN_ID_INVALID"):
        product_receipt_path(tmp_path.resolve(), run_id)
