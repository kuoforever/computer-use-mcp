from __future__ import annotations

import inspect
import hashlib
import json
import os
import sqlite3
import stat
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import computer_use_agent.learning_quarantine as quarantine_module
from computer_use_agent.episode_outcome import (
    CostMetric,
    EpisodeCostVector,
    EpisodeOutcome,
    EpisodeOutcomeLabel,
    ExternalEffectEvidence,
    MetricCoverage,
)
from computer_use_agent.learning_quarantine import (
    CANDIDATE_FACT_DATA_CLASS,
    CANDIDATE_FACT_USE,
    MAX_CANDIDATE_LIFETIME_DAYS,
    CandidateFactAction,
    CandidateFactError,
    CandidateFactQuarantine,
    CandidateFactRecord,
    CandidateFactStatus,
    extract_candidate_fact,
)
from computer_use_agent.trace import RunPhase
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ToolResult,
    ToolResultStatus,
)
from computer_use_agent.world_state import (
    FactKnowledge,
    FactScope,
    FactType,
    ObservationEvidence,
    WindowIdentity,
    WorldFact,
    WorldStateContext,
    WorldStateSnapshot,
)


NOW = datetime(2030, 1, 1, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1_000)
EXPIRY = NOW + timedelta(days=30)
RAW_SECRET = "PRIVATE PAGE TEXT password: never retain this"


def _costs() -> EpisodeCostVector:
    metric = CostMetric(value=0, observed=0, coverage=MetricCoverage.COMPLETE)
    return EpisodeCostVector(
        **{item.name: metric for item in fields(EpisodeCostVector)}
    )


def _episode(
    *,
    run_id: str = "run_1",
    outcome: EpisodeOutcomeLabel = EpisodeOutcomeLabel.VERIFIED_SUCCESS,
    epoch: int | None = 3,
    external_effect: ExternalEffectEvidence = ExternalEffectEvidence.NONE,
) -> EpisodeOutcome:
    return EpisodeOutcome(
        episode_id="a" * 64,
        run_id=run_id,
        source_record_digest="b" * 64,
        manifest_digest="sha256:" + "c" * 64,
        checkpoint_sequence=9,
        outcome=outcome,
        run_phase=(
            RunPhase.SUCCESS
            if outcome is EpisodeOutcomeLabel.VERIFIED_SUCCESS
            else RunPhase.UNKNOWN_OUTCOME
            if outcome is EpisodeOutcomeLabel.UNCERTAIN
            else RunPhase.FAILED
        ),
        failure_code=(None if outcome is EpisodeOutcomeLabel.VERIFIED_SUCCESS else "FAILED"),
        verified_observation_epoch=epoch,
        external_effect=external_effect,
        costs=_costs(),
    )


def _window(*, process_id: int = 101) -> WindowIdentity:
    return WindowIdentity("window_1", process_id, "safe-app.exe")


def _fact(
    *,
    fact_id: str = "dialog_present",
    fact_type: FactType = FactType.BOOLEAN,
    value: bool | int | str = True,
    knowledge: FactKnowledge = FactKnowledge.OBSERVED,
    epoch: int = 3,
    generation: int = 7,
    captured_at_ms: int = NOW_MS - 100,
    window: WindowIdentity | None = None,
) -> WorldFact:
    bound_window = _window() if window is None else window
    result = ToolResult(
        CallIdentity("run_1", "turn_1", "call_1"),
        "ui_snapshot",
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text=RAW_SECRET,
    )
    evidence = ObservationEvidence.from_tool_result(
        result,
        observation_epoch=epoch,
        mcp_generation=generation,
        captured_at_ms=captured_at_ms,
        window=bound_window,
    )
    return WorldFact(
        fact_id=fact_id,
        fact_type=fact_type,
        knowledge=knowledge,
        value=None if knowledge is FactKnowledge.UNKNOWN else value,
        evidence=evidence,
        scope=FactScope.WINDOW,
        max_age_ms=500,
    )


def _snapshot(fact: WorldFact | None = None) -> WorldStateSnapshot:
    return WorldStateSnapshot("run_1", (_fact() if fact is None else fact,))


def _context(
    *,
    run_id: str = "run_1",
    epoch: int = 3,
    generation: int = 7,
    now_ms: int = NOW_MS,
    window: WindowIdentity | None = None,
) -> WorldStateContext:
    return WorldStateContext(
        run_id,
        epoch,
        generation,
        now_ms,
        _window() if window is None else window,
    )


def _store(tmp_path: Path) -> CandidateFactQuarantine:
    return CandidateFactQuarantine((tmp_path / "learning-quarantine.sqlite3").resolve())


def _extract(
    tmp_path: Path,
    *,
    episode: EpisodeOutcome | None = None,
    fact: WorldFact | None = None,
    context: WorldStateContext | None = None,
    fact_id: str = "dialog_present",
    expiry: datetime = EXPIRY,
) -> tuple[CandidateFactQuarantine, CandidateFactRecord]:
    store = _store(tmp_path)
    record = extract_candidate_fact(
        store,
        episode=_episode() if episode is None else episode,
        snapshot=_snapshot(fact),
        fact_id=fact_id,
        context=_context() if context is None else context,
        now=NOW,
        expires_at=expiry,
    )
    return store, record


@pytest.mark.parametrize(
    ("fact_type", "value"),
    [(FactType.BOOLEAN, True), (FactType.BOOLEAN, False), (FactType.INTEGER, 17)],
)
def test_extracts_only_fresh_typed_fact_into_private_quarantine(
    tmp_path: Path,
    fact_type: FactType,
    value: bool | int,
) -> None:
    store, raw_record = _extract(
        tmp_path,
        fact=_fact(fact_type=fact_type, value=value),
    )
    record = raw_record
    assert record.status is CandidateFactStatus.SUGGESTED
    assert record.revision == 0
    assert record.fact_type is fact_type
    assert record.value == value
    assert record.source.episode_id == "a" * 64
    assert record.source.observation_epoch == 3
    assert record.source.window_identity_digest == _window().digest
    assert store.list(now=NOW) == (record,)
    assert [event.action for event in store.events(record.candidate_id)] == [
        CandidateFactAction.EXTRACTED
    ]
    payload = record.to_payload()
    assert payload["data_class"] == CANDIDATE_FACT_DATA_CLASS
    assert payload["use"] == CANDIDATE_FACT_USE
    assert payload["capabilities"] == {
        "inject_memory": False,
        "disclose_to_provider": False,
        "select_strategy": False,
        "promote": False,
        "authorize": False,
        "dispatch": False,
    }
    assert RAW_SECRET not in json.dumps(payload)
    assert RAW_SECRET.encode() not in store.path.read_bytes()
    assert not (tmp_path / "memory.sqlite3").exists()
    if os.name != "nt":
        assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("fact_type", "value"),
    [(FactType.TEXT, "safe looking text"), (FactType.IDENTIFIER, "safe_id")],
)
def test_text_and_identifier_facts_are_forbidden_before_store_creation(
    tmp_path: Path,
    fact_type: FactType,
    value: str,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(
        CandidateFactError, match="^CANDIDATE_FACT_CONTENT_REJECTED$"
    ):
        extract_candidate_fact(
            store,
            episode=_episode(),
            snapshot=_snapshot(_fact(fact_type=fact_type, value=value)),
            fact_id="dialog_present",
            context=_context(),
            now=NOW,
            expires_at=EXPIRY,
        )
    assert not store.path.exists()


@pytest.mark.parametrize(
    ("episode", "context", "fact", "code"),
    [
        (
            _episode(outcome=EpisodeOutcomeLabel.UNCERTAIN),
            _context(),
            _fact(),
            "CANDIDATE_FACT_EPISODE_INELIGIBLE",
        ),
        (
            _episode(external_effect=ExternalEffectEvidence.UNKNOWN),
            _context(),
            _fact(),
            "CANDIDATE_FACT_EPISODE_INELIGIBLE",
        ),
        (
            _episode(epoch=None),
            _context(),
            _fact(),
            "CANDIDATE_FACT_EPISODE_INELIGIBLE",
        ),
        (
            _episode(),
            _context(epoch=4),
            _fact(),
            "CANDIDATE_FACT_EPISODE_INELIGIBLE",
        ),
        (
            _episode(),
            _context(generation=8),
            _fact(),
            "CANDIDATE_FACT_UNAVAILABLE",
        ),
        (
            _episode(),
            _context(window=_window(process_id=102)),
            _fact(),
            "CANDIDATE_FACT_UNAVAILABLE",
        ),
        (
            _episode(),
            _context(),
            _fact(knowledge=FactKnowledge.UNKNOWN),
            "CANDIDATE_FACT_UNAVAILABLE",
        ),
        (
            _episode(),
            _context(),
            _fact(captured_at_ms=NOW_MS - 501),
            "CANDIDATE_FACT_UNAVAILABLE",
        ),
    ],
)
def test_ineligible_episode_or_unavailable_fact_fails_before_store(
    tmp_path: Path,
    episode: EpisodeOutcome,
    context: WorldStateContext,
    fact: WorldFact,
    code: str,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(CandidateFactError, match=f"^{code}$"):
        extract_candidate_fact(
            store,
            episode=episode,
            snapshot=_snapshot(fact),
            fact_id=fact.fact_id,
            context=context,
            now=NOW,
            expires_at=EXPIRY,
        )
    assert not store.path.exists()


def test_time_expiry_and_forbidden_fact_id_fail_before_store(tmp_path: Path) -> None:
    store = _store(tmp_path)
    cases = (
        ("dialog_present", NOW + timedelta(days=MAX_CANDIDATE_LIFETIME_DAYS + 1)),
        ("api_key_secret", EXPIRY),
    )
    for fact_id, expiry in cases:
        with pytest.raises(CandidateFactError):
            extract_candidate_fact(
                store,
                episode=_episode(),
                snapshot=_snapshot(_fact(fact_id=fact_id)),
                fact_id=fact_id,
                context=_context(),
                now=NOW,
                expires_at=expiry,
            )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_TIME_MISMATCH$"):
        extract_candidate_fact(
            store,
            episode=_episode(),
            snapshot=_snapshot(),
            fact_id="dialog_present",
            context=_context(now_ms=NOW_MS + 1),
            now=NOW,
            expires_at=EXPIRY,
        )
    assert not store.path.exists()


def test_confirmation_requires_explicit_flag_and_exact_revision_without_injection(
    tmp_path: Path,
) -> None:
    store, raw_record = _extract(tmp_path)
    record = raw_record
    with pytest.raises(
        CandidateFactError, match="^CANDIDATE_FACT_CONFIRMATION_REQUIRED$"
    ):
        store.confirm(
            record.candidate_id,
            expected_revision=0,
            confirmed=False,
            now=NOW + timedelta(seconds=1),
        )
    confirmed = store.confirm(
        record.candidate_id,
        expected_revision=0,
        confirmed=True,
        now=NOW + timedelta(seconds=1),
    )
    assert confirmed.status is CandidateFactStatus.CONFIRMED
    assert confirmed.revision == 1
    assert not (tmp_path / "memory.sqlite3").exists()
    with pytest.raises(
        CandidateFactError, match="^CANDIDATE_FACT_REVISION_CONFLICT$"
    ):
        store.edit(
            record.candidate_id,
            expected_revision=0,
            value=False,
            now=NOW + timedelta(seconds=2),
        )


def test_edit_resets_confirmation_and_revalidates_type_and_expiry(
    tmp_path: Path,
) -> None:
    store, raw_record = _extract(tmp_path)
    record = raw_record
    confirmed = store.confirm(
        record.candidate_id,
        expected_revision=0,
        confirmed=True,
        now=NOW + timedelta(seconds=1),
    )
    edited = store.edit(
        confirmed.candidate_id,
        expected_revision=1,
        value=False,
        expires_at=NOW + timedelta(days=60),
        now=NOW + timedelta(seconds=2),
    )
    assert edited.status is CandidateFactStatus.SUGGESTED
    assert edited.revision == 2
    assert edited.value is False
    assert edited.operator_edited
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_VALUE_INVALID$"):
        store.edit(
            edited.candidate_id,
            expected_revision=2,
            value=1,
            now=NOW + timedelta(seconds=3),
        )
    assert store.get(edited.candidate_id) == edited


def test_record_lifetime_and_mutation_time_are_bounded(tmp_path: Path) -> None:
    store, record = _extract(tmp_path)
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_TIME_INVALID$"):
        replace(
            record,
            expires_at=(
                NOW + timedelta(days=MAX_CANDIDATE_LIFETIME_DAYS, seconds=1)
            ).isoformat().replace("+00:00", "Z"),
        )
    confirmed = store.confirm(
        record.candidate_id,
        expected_revision=0,
        confirmed=True,
        now=NOW + timedelta(seconds=10),
    )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_TIME_INVALID$"):
        store.edit(
            confirmed.candidate_id,
            expected_revision=1,
            value=False,
            now=NOW + timedelta(seconds=5),
        )
    assert store.get(record.candidate_id) == confirmed


def test_expire_filter_delete_and_digest_only_tombstone(tmp_path: Path) -> None:
    store, raw_record = _extract(tmp_path)
    record = raw_record
    expired = store.expire(
        record.candidate_id,
        expected_revision=0,
        now=NOW + timedelta(seconds=1),
    )
    assert expired.status is CandidateFactStatus.EXPIRED
    assert store.list(now=NOW + timedelta(seconds=1)) == ()
    assert store.list(
        include_expired=True, now=NOW + timedelta(seconds=1)
    ) == (expired,)
    assert store.delete(
        expired.candidate_id,
        expected_revision=1,
        now=NOW + timedelta(seconds=2),
    )
    assert store.get(expired.candidate_id) is None
    events = store.events(expired.candidate_id)
    assert [event.action for event in events] == [
        CandidateFactAction.EXTRACTED,
        CandidateFactAction.EXPIRED,
        CandidateFactAction.DELETED,
    ]
    assert events[-1].record_digest is None
    assert events[-1].prior_digest == expired.digest
    assert RAW_SECRET.encode() not in store.path.read_bytes()


def test_natural_expiry_is_inactive_without_mutating_audit_history(
    tmp_path: Path,
) -> None:
    store, raw_record = _extract(tmp_path, expiry=NOW + timedelta(seconds=2))
    record = raw_record
    later = NOW + timedelta(seconds=3)
    assert record.status_at(later) is CandidateFactStatus.EXPIRED
    assert store.list(now=later) == ()
    assert store.list(include_expired=True, now=later) == (record,)
    assert len(store.events(record.candidate_id)) == 1
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_EXPIRED$"):
        store.confirm(
            record.candidate_id,
            expected_revision=0,
            confirmed=True,
            now=later,
        )


def test_duplicate_or_deleted_source_cannot_be_silently_reextracted(
    tmp_path: Path,
) -> None:
    store, raw_record = _extract(tmp_path)
    record = raw_record
    for delete_first in (False, True):
        if delete_first:
            assert store.delete(
                record.candidate_id,
                expected_revision=0,
                now=NOW + timedelta(seconds=1),
            )
        with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_EXISTS$"):
            extract_candidate_fact(
                store,
                episode=_episode(),
                snapshot=_snapshot(),
                fact_id="dialog_present",
                context=_context(),
                now=NOW,
                expires_at=EXPIRY,
            )
        if delete_first:
            break


def test_history_limit_counts_tombstones(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quarantine_module, "MAX_CANDIDATE_FACTS", 1)
    store, record = _extract(tmp_path)
    assert store.delete(
        record.candidate_id,
        expected_revision=0,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_LIMIT_EXCEEDED$"):
        _extract(tmp_path, fact=_fact(value=False))


def test_event_limit_reserves_the_final_slot_for_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quarantine_module, "MAX_CANDIDATE_EVENTS", 3)
    store, record = _extract(tmp_path)
    confirmed = store.confirm(
        record.candidate_id,
        expected_revision=0,
        confirmed=True,
        now=NOW + timedelta(seconds=1),
    )
    with pytest.raises(
        CandidateFactError, match="^CANDIDATE_FACT_EVENT_LIMIT_EXCEEDED$"
    ):
        store.edit(
            confirmed.candidate_id,
            expected_revision=1,
            value=False,
            now=NOW + timedelta(seconds=2),
        )
    assert store.delete(
        confirmed.candidate_id,
        expected_revision=1,
        now=NOW + timedelta(seconds=2),
    )
    assert len(store.events(confirmed.candidate_id)) == 3


def test_event_insert_failure_rolls_back_candidate_update(tmp_path: Path) -> None:
    store, raw_record = _extract(tmp_path)
    record = raw_record
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_event BEFORE INSERT ON candidate_fact_event "
            "WHEN NEW.sequence = 2 BEGIN SELECT RAISE(ABORT, 'injected'); END"
        )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_DATABASE_ERROR$"):
        store.confirm(
            record.candidate_id,
            expected_revision=0,
            confirmed=True,
            now=NOW + timedelta(seconds=1),
        )
    assert store.get(record.candidate_id) == record
    assert len(store.events(record.candidate_id)) == 1


@pytest.mark.parametrize("field", ["record_json", "record_digest", "revision"])
def test_tampered_candidate_row_fails_closed(tmp_path: Path, field: str) -> None:
    store, raw_record = _extract(tmp_path)
    record = raw_record
    replacement_value: object = {
        "record_json": b"{}",
        "record_digest": "f" * 64,
        "revision": 99,
    }[field]
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            f"UPDATE candidate_fact SET {field} = ? WHERE candidate_id = ?",
            (replacement_value, record.candidate_id),
        )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_STORE_INVALID$"):
        store.get(record.candidate_id)


def test_tampered_event_chain_fails_closed(tmp_path: Path) -> None:
    store, record = _extract(tmp_path)
    store.confirm(
        record.candidate_id,
        expected_revision=0,
        confirmed=True,
        now=NOW + timedelta(seconds=1),
    )
    with sqlite3.connect(store.path) as connection:
        raw = connection.execute(
            "SELECT event_json FROM candidate_fact_event "
            "WHERE candidate_id = ? AND sequence = 2",
            (record.candidate_id,),
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["prior_digest"] = "0" * 64
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        connection.execute(
            "UPDATE candidate_fact_event SET event_json = ?, event_digest = ? "
            "WHERE candidate_id = ? AND sequence = 2",
            (
                encoded,
                hashlib.sha256(encoded).hexdigest(),
                record.candidate_id,
            ),
        )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_STORE_INVALID$"):
        store.events(record.candidate_id)


def test_semantically_tampered_event_fails_closed(tmp_path: Path) -> None:
    store, record = _extract(tmp_path)
    store.confirm(
        record.candidate_id,
        expected_revision=0,
        confirmed=True,
        now=NOW + timedelta(seconds=1),
    )
    with sqlite3.connect(store.path) as connection:
        raw = connection.execute(
            "SELECT event_json FROM candidate_fact_event "
            "WHERE candidate_id = ? AND sequence = 2",
            (record.candidate_id,),
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["action"] = "edited"
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        connection.execute(
            "UPDATE candidate_fact_event SET event_json = ?, event_digest = ? "
            "WHERE candidate_id = ? AND sequence = 2",
            (
                encoded,
                hashlib.sha256(encoded).hexdigest(),
                record.candidate_id,
            ),
        )
    with pytest.raises(CandidateFactError, match="^CANDIDATE_FACT_STORE_INVALID$"):
        store.events(record.candidate_id)


def test_database_path_is_absolute_and_symlink_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="absolute"):
        CandidateFactQuarantine(Path("relative.sqlite3"))
    if os.name != "nt":
        target = tmp_path / "target.sqlite3"
        target.write_bytes(b"")
        link = tmp_path / "link.sqlite3"
        link.symlink_to(target)
        store = CandidateFactQuarantine(link.absolute())
        if store.path.is_symlink():
            with pytest.raises(
                CandidateFactError, match="^CANDIDATE_FACT_PATH_UNSAFE$"
            ):
                store.list()


def test_quarantine_has_no_execution_or_memory_context_port() -> None:
    source = inspect.getsource(quarantine_module)
    assert not hasattr(quarantine_module, "AgentRunner")
    assert not hasattr(quarantine_module, "ToolCall")
    assert not hasattr(quarantine_module, "MemoryStore")
    assert "build_memory_context" not in source
    assert "provider" not in CandidateFactQuarantine.__dict__
    assert "dispatch" not in CandidateFactQuarantine.__dict__
