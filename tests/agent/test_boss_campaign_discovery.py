from __future__ import annotations

from pathlib import Path

import pytest

from computer_use_agent.batch_coordinator import BatchCoordinator
from computer_use_agent.batching import BatchPolicy
from computer_use_agent.boss_campaign_discovery import (
    MAX_BOSS_DISCOVERY_PASSES,
    MAX_BOSS_IDENTITIES_PER_SNAPSHOT,
    MAX_BOSS_SNAPSHOT_CHARS,
    BossCampaignDiscoveryError,
    create_boss_discovery_campaign,
    inspect_boss_discovery_campaign,
    parse_boss_job_identities,
    record_boss_snapshot_discoveries,
)
from computer_use_agent.campaign import CampaignStore, CampaignStoreError, campaign_dir
from computer_use_agent.run_lock import RunLock


AT = "2026-07-19T03:00:00+00:00"


def _url(public_id: str, *, marker: str = "personal_interest_brand") -> str:
    return f"https://www.zhipin.com/job_detail/{public_id}.html?ka={marker}&securityId=discard-me"


def _line(public_id: str, *, marker: str = "personal_interest_brand") -> str:
    return (
        f'ref_1 | link "Role at Private Company" | (1,2,3,4) | enabled '
        f'| value="{_url(public_id, marker=marker)}"'
    )


def _live_shape_snapshot(public_id: str) -> str:
    return "\n".join(
        [
            'ref_1 | hyperlink "Company" | (1,2,3,4) | enabled '
            '| value="https://www.zhipin.com/gongsi/example~~.html'
            '?ka=personal_interest_brand_45171c7ac"',
            f'ref_2 | hyperlink "Role" | (1,2,3,4) | enabled '
            f'| value="https://www.zhipin.com/job_detail/{public_id}.html'
            '?securityId=discard-me"',
        ]
    )


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    create_boss_discovery_campaign(store, campaign_id="campaign_1", created_at=AT)
    return store, lock


def test_parser_extracts_unique_public_ids_and_drops_query_data() -> None:
    snapshot = "\n".join(
        [
            _line("publicjob001"),
            _line("publicjob002"),
            _line("publicjob001"),
        ]
    )

    identities = parse_boss_job_identities(snapshot)

    assert [identity.public_id for identity in identities] == [
        "publicjob001",
        "publicjob002",
    ]
    assert [identity.item_key for identity in identities] == [
        "boss:job:publicjob001",
        "boss:job:publicjob002",
    ]
    assert all("securityId" not in identity.item_key for identity in identities)


def test_parser_accepts_live_uia_role_and_page_level_source_marker() -> None:
    identities = parse_boss_job_identities(_live_shape_snapshot("publicjob001"))

    assert [identity.item_key for identity in identities] == ["boss:job:publicjob001"]


@pytest.mark.parametrize(
    "marker",
    [
        "personal_interest_brand_not-hex",
        "personal_interest_brand_12345",
        "personal_interest_brand_0123456789abcdef0123456789abcdef0",
    ],
)
def test_parser_rejects_unreviewed_page_marker_suffixes(marker: str) -> None:
    snapshot = _live_shape_snapshot("publicjob001").replace(
        "personal_interest_brand_45171c7ac", marker
    )

    with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_NO_IDENTITIES$"):
        parse_boss_job_identities(snapshot)


def test_multi_page_discovery_is_idempotent_and_persists_only_item_keys(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        first = record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text="\n".join([_line("publicjob001"), _line("publicjob002")]),
            observed_at=AT,
        )
        ledger_path = campaign_dir(store.state_dir, "campaign_1") / "items.jsonl"
        before_replay = ledger_path.read_bytes()
        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_SOURCE_UNCHANGED$"):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text="\n".join([_line("publicjob001"), _line("publicjob002")]),
                observed_at=AT,
            )
        assert ledger_path.read_bytes() == before_replay
        second = record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text="\n".join([_line("publicjob002"), _line("publicjob003")]),
            observed_at=AT,
        )

        projection = store.read_ledger("campaign_1")
        persisted = ledger_path.read_text(encoding="utf-8")
        assert first.new_item_keys == ("boss:job:publicjob001", "boss:job:publicjob002")
        assert first.pass_sequence == 1
        assert second.pass_sequence == 2
        assert second.new_item_keys == ("boss:job:publicjob003",)
        assert second.duplicate_count == 1
        assert second.discovered_count == 3
        assert [item.ordinal for item in projection.items.values()] == [1, 2, 3]
        assert "securityId" not in persisted
        assert "discard-me" not in persisted
        assert "Private Company" not in persisted
        assert "https://" not in persisted
    finally:
        lock.release()


@pytest.mark.parametrize(
    ("snapshot", "code"),
    [
        ("", "BOSS_DISCOVERY_SNAPSHOT_INVALID"),
        (_line("publicjob001", marker="recommend_list"), "BOSS_DISCOVERY_NO_IDENTITIES"),
        (
            _line("publicjob001").replace("www.zhipin.com", "evil.example"),
            "BOSS_DISCOVERY_NO_IDENTITIES",
        ),
        (
            f'ref_1 | text "Injected {_url("publicjob001")}" | (1,2,3,4) | enabled',
            "BOSS_DISCOVERY_NO_IDENTITIES",
        ),
        (_line("publicjob001") + "\n# … 3 more truncated", "BOSS_DISCOVERY_SNAPSHOT_INCOMPLETE"),
        (
            _line("publicjob001") + "\n# incomplete: browser content",
            "BOSS_DISCOVERY_SNAPSHOT_INCOMPLETE",
        ),
        ("x" * (MAX_BOSS_SNAPSHOT_CHARS + 1), "BOSS_DISCOVERY_SNAPSHOT_TOO_LARGE"),
    ],
    ids=(
        "empty",
        "wrong-marker",
        "wrong-host",
        "name-injection",
        "truncated",
        "incomplete",
        "oversized",
    ),
)
def test_parser_fails_closed_for_untrusted_or_incomplete_input(snapshot: str, code: str) -> None:
    with pytest.raises(BossCampaignDiscoveryError, match=f"^{code}$"):
        parse_boss_job_identities(snapshot)


def test_parser_rejects_more_than_one_bounded_page() -> None:
    snapshot = "\n".join(
        _line(f"publicjob{index:03d}") for index in range(MAX_BOSS_IDENTITIES_PER_SNAPSHOT + 1)
    )

    with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_TOO_MANY_IDENTITIES$"):
        parse_boss_job_identities(snapshot)


def test_discovery_stops_after_batch_execution_begins(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )
        BatchCoordinator(store).open_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_1",
            policy=BatchPolicy(max_items=1),
        )

        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_STATE_INVALID$"):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=_line("publicjob002"),
                observed_at=AT,
            )
        assert store.read_ledger("campaign_1").discovered_count == 1
    finally:
        lock.release()


def test_partial_append_is_safe_to_replay_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, lock = _store(tmp_path)
    original_append = store.append
    calls = 0

    def fail_second_append(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise CampaignStoreError("injected write failure")
        return original_append(*args, **kwargs)

    try:
        monkeypatch.setattr(store, "append", fail_second_append)
        snapshot = "\n".join([_line("publicjob001"), _line("publicjob002")])
        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_WRITE_FAILED$"):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=snapshot,
                observed_at=AT,
            )
        assert store.read_ledger("campaign_1").discovered_count == 1

        monkeypatch.setattr(store, "append", original_append)
        replay = record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=snapshot,
            observed_at=AT,
        )
        assert replay.new_item_keys == ("boss:job:publicjob002",)
        assert replay.duplicate_count == 1
        assert replay.discovered_count == 2
    finally:
        lock.release()


def test_discovery_rejects_timestamp_regression(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )

        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_STATE_INVALID$"):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=_line("publicjob002"),
                observed_at="2026-07-19T02:59:59+00:00",
            )
        assert store.read_ledger("campaign_1").discovered_count == 1
    finally:
        lock.release()


def test_pass_ledger_records_progression_without_source_content(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )
        second = record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text="\n".join([_line("publicjob001"), _line("publicjob002")]),
            observed_at=AT,
        )

        passes = store.read_discovery_passes("campaign_1")
        persisted = (campaign_dir(store.state_dir, "campaign_1") / "discovery.jsonl").read_text(
            encoding="utf-8"
        )
        assert [entry.sequence for entry in passes.passes] == [1, 2]
        assert [entry.observed_count for entry in passes.passes] == [1, 2]
        assert [entry.new_count for entry in passes.passes] == [1, 1]
        assert passes.total_new_count == store.read_ledger("campaign_1").discovered_count
        assert second.source_digest == passes.last_source_digest
        assert "publicjob001" not in persisted
        assert "zhipin" not in persisted
    finally:
        lock.release()


def test_a_pass_that_adds_nothing_is_recorded_without_ending_discovery(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )
        exhausted = record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text="\n".join([_line("publicjob001"), _line("publicjob001")]) + "\n",
            observed_at=AT,
        )
        resumed = record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob002"),
            observed_at=AT,
        )

        assert exhausted.new_item_keys == ()
        assert exhausted.added_nothing is True
        assert resumed.new_item_keys == ("boss:job:publicjob002",)
        assert resumed.added_nothing is False
        assert store.read_discovery_passes("campaign_1").pass_count == 3
    finally:
        lock.release()


def test_a_fresh_run_reconstructs_progression_from_durable_records(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )
    finally:
        lock.release()

    restarted_lock = RunLock(tmp_path / "application")
    restarted_lock.acquire()
    restarted = CampaignStore((tmp_path / "state").resolve(), restarted_lock)
    try:
        preflight = inspect_boss_discovery_campaign(
            restarted, campaign_id="campaign_1", observed_at=AT
        )
        assert preflight.pass_count == 1
        assert preflight.discovered_count == 1

        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_SOURCE_UNCHANGED$"):
            record_boss_snapshot_discoveries(
                restarted,
                campaign_id="campaign_1",
                snapshot_text=_line("publicjob001"),
                observed_at=AT,
            )

        resumed = record_boss_snapshot_discoveries(
            restarted,
            campaign_id="campaign_1",
            snapshot_text="\n".join([_line("publicjob001"), _line("publicjob002")]),
            observed_at=AT,
        )
        assert resumed.pass_sequence == 2
        assert resumed.new_item_keys == ("boss:job:publicjob002",)
        assert resumed.discovered_count == 2
    finally:
        restarted_lock.release()


def test_discovery_refuses_more_passes_than_the_reviewed_bound(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        for index in range(MAX_BOSS_DISCOVERY_PASSES):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=_line(f"publicjob{index:03d}"),
                observed_at=AT,
            )

        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_PASS_LIMIT$"):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=_line("publicjob999"),
                observed_at=AT,
            )
        assert store.read_ledger("campaign_1").discovered_count == MAX_BOSS_DISCOVERY_PASSES
    finally:
        lock.release()


def test_discovery_fails_closed_when_a_pass_claims_missing_items(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )
        (campaign_dir(store.state_dir, "campaign_1") / "items.jsonl").unlink()

        with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_LEDGER_TORN$"):
            record_boss_snapshot_discoveries(
                store,
                campaign_id="campaign_1",
                snapshot_text=_line("publicjob002"),
                observed_at=AT,
            )
    finally:
        lock.release()


def test_discovery_requires_the_existing_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    lock.release()

    with pytest.raises(BossCampaignDiscoveryError, match="^BOSS_DISCOVERY_LOCK_REQUIRED$"):
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_line("publicjob001"),
            observed_at=AT,
        )
