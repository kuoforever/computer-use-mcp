from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CAMPAIGN_VERSION,
    CampaignManifest,
    CampaignStore,
    CampaignStoreError,
    DiscoveryPass,
    ItemStatus,
    ItemTransition,
    campaign_dir,
    reduce_discovery_passes,
    reduce_item_ledger,
)
from computer_use_agent.run_lock import RunLock


DIGEST = "a" * 64
CONTENT_DIGEST = "b" * 64


def _manifest() -> CampaignManifest:
    return CampaignManifest.create(
        campaign_id="campaign_1",
        kind="saved_job_review",
        policy_digest=DIGEST,
        schema_digest=DIGEST,
    )


def _transition(
    status: ItemStatus,
    *,
    ordinal: int = 1,
    item_key: str = "boss:job_1",
    attempt: int = 0,
    run_id: str | None = None,
    lease_expires_at: str | None = None,
    use_default_lease: bool = True,
    boundary: str | None = None,
    code: str | None = None,
    content_digest: str | None = None,
) -> ItemTransition:
    if status is ItemStatus.CLAIMED and lease_expires_at is None and use_default_lease:
        lease_expires_at = "2026-07-15T00:10:00+00:00"
    return ItemTransition(
        sequence=999,
        ordinal=ordinal,
        item_key=item_key,
        status=status,
        attempt=attempt,
        at="2026-07-15T00:00:00+00:00",
        run_id=run_id,
        lease_expires_at=lease_expires_at,
        boundary=boundary,
        code=code,
        content_digest=content_digest,
    )


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    return CampaignStore((tmp_path / "state").resolve(), lock), lock


def test_campaign_manifest_and_ledger_are_private_bounded_and_append_only(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        discovered = store.append(manifest.campaign_id, _transition(ItemStatus.DISCOVERED))
        claimed = store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.CLAIMED,
                attempt=1,
                run_id="run_1",
                boundary="claim",
            ),
        )
        observed = store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.OBSERVED,
                attempt=1,
                run_id="run_1",
                boundary="identity_verified",
            ),
        )
        extracted = store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.EXTRACTED,
                attempt=1,
                run_id="run_1",
                boundary="read_only_extract",
            ),
        )
        committed = store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.COMMITTED,
                attempt=1,
                run_id="run_1",
                boundary="result_verified",
                code="OK",
                content_digest=CONTENT_DIGEST,
            ),
        )

        path = campaign_dir((tmp_path / "state").resolve(), manifest.campaign_id) / "items.jsonl"
        assert [entry.sequence for entry in committed.transitions] == [1, 2, 3, 4, 5]
        assert discovered.discovered_count == 1
        assert claimed.items["boss:job_1"].status is ItemStatus.CLAIMED
        assert observed.items["boss:job_1"].status is ItemStatus.OBSERVED
        assert extracted.items["boss:job_1"].status is ItemStatus.EXTRACTED
        assert committed.completed_count == 1
        assert committed.next_ordinal == 2
        assert "job title" not in path.read_text(encoding="utf-8")
        assert store.read_ledger(manifest.campaign_id) == committed
    finally:
        lock.release()


def test_campaign_reducer_rejects_duplicate_discovery_illegal_transition_and_attempt_drift() -> None:
    discovered = _transition(ItemStatus.DISCOVERED)
    duplicate = _transition(ItemStatus.DISCOVERED)
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LEDGER_INVALID"):
        reduce_item_ledger((discovered, duplicate))

    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LEDGER_INVALID"):
        reduce_item_ledger(
            (
                discovered,
                _transition(
                    ItemStatus.COMMITTED,
                    attempt=1,
                    run_id="run_1",
                    boundary="result_verified",
                    code="OK",
                    content_digest=CONTENT_DIGEST,
                ),
            )
        )
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LEDGER_INVALID"):
        reduce_item_ledger(
            (
                discovered,
                _transition(
                    ItemStatus.CLAIMED,
                    attempt=2,
                    run_id="run_1",
                    boundary="claim",
                ),
            )
        )


@pytest.mark.parametrize(
    "lease_expires_at",
    [None, "2026-07-15T00:00:00+00:00", "2026-07-15T02:00:00+00:00"],
)
def test_claim_requires_a_bounded_future_lease(lease_expires_at: str | None) -> None:
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_INVALID"):
        _transition(
            ItemStatus.CLAIMED,
            attempt=1,
            run_id="run_1",
            boundary="claim",
            lease_expires_at=lease_expires_at,
            use_default_lease=False,
        )


def test_campaign_store_requires_lock_and_never_replaces_manifest(tmp_path: Path) -> None:
    lock = RunLock(tmp_path / "application")
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_LOCK_REQUIRED"):
        store.create(_manifest())

    lock.acquire()
    try:
        store.create(_manifest())
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_ALREADY_EXISTS"):
            store.create(_manifest())
    finally:
        lock.release()


def test_campaign_reader_rejects_tampered_manifest_and_corrupt_ledger(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        directory = campaign_dir((tmp_path / "state").resolve(), manifest.campaign_id)
        manifest_path = directory / "manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["unexpected"] = True
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_MANIFEST_INVALID"):
            store.read_manifest(manifest.campaign_id)

        manifest_path.write_text(json.dumps(manifest.as_json()), encoding="utf-8")
        ledger_path = directory / "items.jsonl"
        ledger_path.write_text("not-json\n", encoding="utf-8")
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_LEDGER_INVALID"):
            store.read_ledger(manifest.campaign_id)
    finally:
        lock.release()


def test_failed_atomic_ledger_append_preserves_prior_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        store.append(manifest.campaign_id, _transition(ItemStatus.DISCOVERED))
        path = campaign_dir((tmp_path / "state").resolve(), manifest.campaign_id) / "items.jsonl"
        before = path.read_bytes()

        def fail_replace(_source: object, _target: object) -> None:
            raise OSError("synthetic replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_WRITE_FAILED"):
            store.append(
                manifest.campaign_id,
                _transition(
                    ItemStatus.CLAIMED,
                    attempt=1,
                    run_id="run_1",
                    boundary="claim",
                ),
            )
        assert path.read_bytes() == before
    finally:
        lock.release()


def test_handoff_is_fixed_schema_and_derived_only_from_durable_ledger(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        store.append(manifest.campaign_id, _transition(ItemStatus.DISCOVERED, ordinal=1))
        store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.CLAIMED,
                attempt=1,
                run_id="run_1",
                boundary="claim",
            ),
        )
        store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.OBSERVED,
                attempt=1,
                run_id="run_1",
                boundary="identity_verified",
            ),
        )
        store.append(
            manifest.campaign_id,
            _transition(
                ItemStatus.RETRYABLE,
                attempt=1,
                run_id="run_1",
                boundary="provider_failed_before_dispatch",
                code="PROVIDER_FAILURE",
            ),
        )

        handoff = store.write_handoff(manifest.campaign_id, last_run_id="run_1")
        path = campaign_dir((tmp_path / "state").resolve(), manifest.campaign_id) / "handoff.json"
        persisted = json.loads(path.read_text(encoding="utf-8"))
        assert handoff == persisted
        assert persisted["campaign_version"] == CAMPAIGN_VERSION
        assert persisted["next_item_ordinal"] == 1
        assert persisted["retryable_count"] == 1
        assert persisted["next_action"] == "resume_batch"
        assert set(persisted) == {
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
    finally:
        lock.release()


def _pass(sequence: int, *, digest: str, at: str = "2026-07-19T03:00:00+00:00") -> DiscoveryPass:
    return DiscoveryPass(
        sequence=sequence,
        at=at,
        source_digest=digest,
        observed_count=2,
        new_count=1,
    )


def test_discovery_pass_ledger_is_append_only_and_resequenced(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        assert store.read_discovery_passes(manifest.campaign_id).pass_count == 0

        store.append_discovery_pass(manifest.campaign_id, _pass(99, digest="c" * 64))
        projection = store.append_discovery_pass(
            manifest.campaign_id, _pass(1, digest="d" * 64)
        )

        path = campaign_dir((tmp_path / "state").resolve(), manifest.campaign_id) / "discovery.jsonl"
        persisted = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [entry.sequence for entry in projection.passes] == [1, 2]
        assert [entry["sequence"] for entry in persisted] == [1, 2]
        assert projection.last_source_digest == "d" * 64
        assert projection.total_new_count == 2
        assert projection.last_pass_added_nothing is False
    finally:
        lock.release()


def test_discovery_pass_ledger_rejects_a_repeated_source_and_time_regression() -> None:
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_DISCOVERY_LEDGER_INVALID"):
        reduce_discovery_passes((_pass(1, digest="c" * 64), _pass(2, digest="c" * 64)))

    with pytest.raises(CampaignStoreError, match="CAMPAIGN_DISCOVERY_LEDGER_INVALID"):
        reduce_discovery_passes(
            (
                _pass(1, digest="c" * 64),
                _pass(2, digest="d" * 64, at="2026-07-19T02:59:59+00:00"),
            )
        )


def test_discovery_pass_rejects_counts_that_cannot_describe_an_observation() -> None:
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_INVALID"):
        DiscoveryPass(
            sequence=1,
            at="2026-07-19T03:00:00+00:00",
            source_digest="c" * 64,
            observed_count=1,
            new_count=2,
        )
    with pytest.raises(CampaignStoreError, match="CAMPAIGN_INVALID"):
        DiscoveryPass(
            sequence=1,
            at="2026-07-19T03:00:00+00:00",
            source_digest="c" * 64,
            observed_count=0,
            new_count=0,
        )


def test_atomic_write_retries_a_transient_replace_hold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scanner holding the destination briefly must not fail the write."""

    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(source: object, target: object) -> None:
            calls["n"] += 1
            if calls["n"] <= 2:
                raise PermissionError(5, "denied")
            real_replace(source, target)

        monkeypatch.setattr(os, "replace", flaky_replace)
        store.append(manifest.campaign_id, _transition(ItemStatus.DISCOVERED))

        assert calls["n"] == 3
        projection = store.read_ledger(manifest.campaign_id)
        assert len(projection.items) == 1
    finally:
        lock.release()


def test_atomic_write_gives_up_on_a_persistent_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry is bounded: a real permission fault still fails, and fails loudly."""

    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())
        path = campaign_dir((tmp_path / "state").resolve(), manifest.campaign_id) / "items.jsonl"
        before = path.read_bytes() if path.exists() else b""
        calls = {"n": 0}

        def always_denied(_source: object, _target: object) -> None:
            calls["n"] += 1
            raise PermissionError(5, "denied")

        monkeypatch.setattr(os, "replace", always_denied)
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_WRITE_FAILED"):
            store.append(manifest.campaign_id, _transition(ItemStatus.DISCOVERED))

        assert calls["n"] == 5
        assert (path.read_bytes() if path.exists() else b"") == before
    finally:
        lock.release()


def test_atomic_write_reports_an_unusable_path_distinctly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing path is not a write fault; MAX_PATH overflow looks like this."""

    store, lock = _store(tmp_path)
    try:
        manifest = store.create(_manifest())

        def missing(*_args: object, **_kwargs: object) -> None:
            raise FileNotFoundError(2, "No such file or directory")

        monkeypatch.setattr(tempfile, "mkstemp", missing)
        with pytest.raises(CampaignStoreError, match="CAMPAIGN_PATH_UNAVAILABLE"):
            store.append(manifest.campaign_id, _transition(ItemStatus.DISCOVERED))
    finally:
        lock.release()
