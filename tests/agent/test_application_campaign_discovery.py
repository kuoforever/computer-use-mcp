from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from computer_use_agent.application_campaign_discovery import (
    ApplicationDiscoveryError,
    create_application_discovery_campaign,
    inspect_application_discovery_campaign,
    record_application_snapshot_discoveries,
)
from computer_use_agent.application_campaign_runtime import start_application_campaign_batch
from computer_use_agent.application_worker_catalog import (
    application_worker_policy_digest,
    application_worker_schema_digest,
    get_application_worker,
)
from computer_use_agent.batch_coordinator import BatchCoordinator
from computer_use_agent.batching import BatchPolicy
from computer_use_agent.campaign import (
    CampaignStore,
    DiscoveryPass,
    ItemStatus,
    campaign_dir,
)
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.discovery_adapters import (
    MAX_DISCOVERY_CAMPAIGN_ITEMS,
    MAX_DISCOVERY_PASSES,
    discovery_adapter_for_kind,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner


AT = datetime(2026, 7, 26, 3, 0, tzinfo=timezone.utc)
ADAPTER = discovery_adapter_for_kind("enterprise_incident")
LINK_ADAPTER = discovery_adapter_for_kind("boss_saved_job_review")


def _at(offset_seconds: int = 0) -> str:
    return (AT + timedelta(seconds=offset_seconds)).isoformat(timespec="seconds")


def _queue(*public_ids: str, marker: str = "Incident queue - open") -> str:
    header = f'ref_1 | text "{marker}" | (0,0,10,10) | enabled'
    rows = [
        f'ref_{index} | listitem "{public_id} bounded row" | (0,0,10,10) | enabled'
        for index, public_id in enumerate(public_ids, start=2)
    ]
    return "\n".join([header, *rows])


def _store(tmp_path: Path) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(tmp_path / "application")
    lock.acquire()
    store = CampaignStore((tmp_path / "state").resolve(), lock)
    create_application_discovery_campaign(
        store,
        adapter=ADAPTER,
        campaign_id="campaign_1",
        created_at=_at(),
    )
    return store, lock


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=(local / "computer-use-agent" / "discovery").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "test-discovery"),
        mcp=MCPLaunchConfig(tmp_path / "mcp.exe", (), tmp_path, {}),
        policy=PolicyConfig(
            mode="read_only",
            max_model_turns=4,
            max_tool_calls=4,
            max_side_effects=0,
        ),
    )


def test_created_campaign_carries_the_reviewed_worker_digests(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        spec = get_application_worker(ADAPTER.campaign_kind)
        manifest = store.read_manifest("campaign_1")

        assert manifest.kind == spec.kind
        assert manifest.policy_digest == application_worker_policy_digest(spec)
        assert manifest.schema_digest == application_worker_schema_digest(spec)
    finally:
        lock.release()


def test_recording_persists_only_prefixed_public_identities(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        outcome = record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821", "INC-004822"),
            observed_at=_at(),
        )

        assert outcome.new_item_keys == (
            "incident:ticket:INC-004821",
            "incident:ticket:INC-004822",
        )
        assert outcome.adapter_id == ADAPTER.adapter_id
        assert outcome.campaign_kind == ADAPTER.campaign_kind
        assert outcome.discovered_count == 2
        assert outcome.pass_sequence == 1
        assert outcome.duplicate_count == 0
        assert outcome.added_nothing is False
        projection = store.read_ledger("campaign_1")
        assert [item.ordinal for item in projection.items.values()] == [1, 2]
        assert all(
            item.status is ItemStatus.DISCOVERED for item in projection.items.values()
        )
        assert not any("bounded row" in key for key in projection.items)
    finally:
        lock.release()


def test_repeated_passes_accumulate_and_report_duplicates(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821"),
            observed_at=_at(),
        )
        second = record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821", "INC-004822"),
            observed_at=_at(60),
        )

        assert second.new_item_keys == ("incident:ticket:INC-004822",)
        assert second.duplicate_count == 1
        assert second.discovered_count == 2
        assert second.pass_sequence == 2
        assert store.read_ledger("campaign_1").items[
            "incident:ticket:INC-004822"
        ].ordinal == 2
    finally:
        lock.release()


def test_pass_that_adds_nothing_is_recorded_without_inference(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821"),
            observed_at=_at(),
        )
        repeated = record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821", marker="Incident queue - open today"),
            observed_at=_at(60),
        )

        assert repeated.new_item_keys == ()
        assert repeated.added_nothing is True
        assert repeated.discovered_count == 1
    finally:
        lock.release()


def test_unchanged_source_is_refused(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        snapshot = _queue("INC-004821")
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=snapshot,
            observed_at=_at(),
        )

        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_SOURCE_UNCHANGED$"
        ):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=snapshot,
                observed_at=_at(60),
            )
    finally:
        lock.release()


def test_pass_limit_bounds_one_campaign(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        for index in range(MAX_DISCOVERY_PASSES):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=_queue(f"INC-{index:06d}"),
                observed_at=_at(index),
            )

        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_PASS_LIMIT$"
        ):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=_queue("INC-999999"),
                observed_at=_at(MAX_DISCOVERY_PASSES),
            )
    finally:
        lock.release()


def test_campaign_item_limit_fails_closed(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        for index in range(MAX_DISCOVERY_CAMPAIGN_ITEMS // 50):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=_queue(
                    *(f"INC-{index * 50 + offset:06d}" for offset in range(50))
                ),
                observed_at=_at(index),
            )

        assert store.read_ledger("campaign_1").discovered_count == (
            MAX_DISCOVERY_CAMPAIGN_ITEMS
        )
        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_CAMPAIGN_LIMIT$"
        ):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=_queue("INC-999999"),
                observed_at=_at(MAX_DISCOVERY_CAMPAIGN_ITEMS),
            )
    finally:
        lock.release()


def test_pass_ledger_claiming_unpersisted_items_fails_closed(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        store.append_discovery_pass(
            "campaign_1",
            DiscoveryPass(
                sequence=1,
                at=_at(),
                source_digest="a" * 64,
                observed_count=4,
                new_count=4,
            ),
        )

        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_LEDGER_TORN$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                observed_at=_at(60),
            )
    finally:
        lock.release()


def test_discovery_is_refused_after_a_batch_opens(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821"),
            observed_at=_at(),
        )
        BatchCoordinator(store).open_batch(
            campaign_id="campaign_1",
            batch_id="batch_1",
            run_id="run_1",
            policy=BatchPolicy(max_items=1),
        )

        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_STATE_INVALID$"
        ):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=_queue("INC-004822"),
                observed_at=_at(60),
            )
    finally:
        lock.release()


def test_discovery_is_refused_once_a_handoff_exists(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821"),
            observed_at=_at(),
        )
        (campaign_dir(store.state_dir, "campaign_1") / "handoff.json").write_text(
            "{}", encoding="utf-8"
        )

        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_STATE_INVALID$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                observed_at=_at(60),
            )
    finally:
        lock.release()


def test_observation_before_the_last_recorded_pass_is_refused(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821"),
            observed_at=_at(60),
        )

        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_STATE_INVALID$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                observed_at=_at(),
            )
    finally:
        lock.release()


def test_adapter_bound_to_another_kind_is_refused(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_STATE_INVALID$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter=LINK_ADAPTER,
                campaign_id="campaign_1",
                observed_at=_at(),
            )
    finally:
        lock.release()


def test_every_boundary_requires_the_run_lock(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    lock.release()
    try:
        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_LOCK_REQUIRED$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                observed_at=_at(),
            )
        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_LOCK_REQUIRED$"
        ):
            record_application_snapshot_discoveries(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                snapshot_text=_queue("INC-004821"),
                observed_at=_at(),
            )
    finally:
        if lock.acquired:
            lock.release()


def test_invalid_adapter_and_timestamp_fail_closed(tmp_path: Path) -> None:
    store, lock = _store(tmp_path)
    try:
        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_ADAPTER_INVALID$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter="enterprise_incident",  # type: ignore[arg-type]
                campaign_id="campaign_1",
                observed_at=_at(),
            )
        with pytest.raises(
            ApplicationDiscoveryError, match="^APPLICATION_DISCOVERY_TIME_INVALID$"
        ):
            inspect_application_discovery_campaign(
                store,
                adapter=ADAPTER,
                campaign_id="campaign_1",
                observed_at="2026-07-26T03:00:00",
            )
    finally:
        lock.release()


def test_a_fresh_run_reconstructs_progression_from_durable_records(
    tmp_path: Path,
) -> None:
    store, lock = _store(tmp_path)
    try:
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004821"),
            observed_at=_at(),
        )
        second = record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_1",
            snapshot_text=_queue("INC-004822"),
            observed_at=_at(60),
        )
    finally:
        lock.release()

    fresh_lock = RunLock(tmp_path / "application")
    fresh_lock.acquire()
    try:
        preflight = inspect_application_discovery_campaign(
            CampaignStore((tmp_path / "state").resolve(), fresh_lock),
            adapter=ADAPTER,
            campaign_id="campaign_1",
            observed_at=_at(120),
        )

        assert preflight.pass_count == 2
        assert preflight.discovered_count == 2
        assert preflight.last_source_digest == second.source_digest
        assert preflight.last_pass_added_nothing is False
    finally:
        fresh_lock.release()


def test_a_discovered_campaign_starts_through_the_generic_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        store = CampaignStore(config.state_dir, lock)
        create_application_discovery_campaign(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_start",
            created_at=_at(),
        )
        record_application_snapshot_discoveries(
            store,
            adapter=ADAPTER,
            campaign_id="campaign_start",
            snapshot_text=_queue("INC-004821", "INC-004822"),
            observed_at=_at(),
        )
    finally:
        lock.release()

    started = start_application_campaign_batch(
        AgentRunner(config),
        spec=get_application_worker(ADAPTER.campaign_kind),
        campaign_id="campaign_start",
        run_id="worker_run_1",
        now=AT,
    )

    assert started.campaign_kind == ADAPTER.campaign_kind
    assert started.planned_item_count == 1
    assert started.claimed_item_ordinal == 1

    verify_lock = RunLock(config.application_state_dir)
    verify_lock.acquire()
    try:
        projection = CampaignStore(config.state_dir, verify_lock).read_ledger(
            "campaign_start"
        )
        assert (
            projection.items["incident:ticket:INC-004821"].status is ItemStatus.CLAIMED
        )
        assert (
            projection.items["incident:ticket:INC-004822"].status
            is ItemStatus.DISCOVERED
        )
    finally:
        verify_lock.release()
