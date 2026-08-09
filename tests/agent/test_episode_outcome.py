from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from computer_use_agent.campaign import (
    CampaignManifest,
    CampaignStore,
    ItemStatus,
    ItemTransition,
)
from computer_use_agent.episode_outcome import (
    EPISODE_DATA_CLASS,
    EPISODE_OUTCOME_VERSION,
    EPISODE_USE,
    EpisodeCostVector,
    EpisodeOutcomeError,
    EpisodeOutcomeLabel,
    ExternalEffectEvidence,
    MetricCoverage,
    build_episode_outcome,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.trace import RunPhase, RunRecorder
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    LedgerEvent,
    LedgerEventKind,
    RecoveryStatus,
    RunBudget,
    RunState,
    SafeArgumentSummary,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


TASK_SECRET = "PRIVATE TASK THAT MUST NOT ENTER L0"
TYPED_SECRET = "PRIVATE TYPED VALUE"
NOW = datetime(2026, 8, 9, tzinfo=timezone.utc)


def _record_run(
    tmp_path: Path,
    *,
    run_id: str = "run_1",
    phase: RunPhase = RunPhase.SUCCESS,
    model_usage: tuple[tuple[int | None, int | None, int | None], ...] = (),
    tool_name: str | None = None,
    tool_status: ToolResultStatus = ToolResultStatus.SUCCESS,
    tool_latency_ms: int | None = None,
    run_duration_ms: int | None = 25,
) -> Path:
    events: list[LedgerEvent] = [
        LedgerEvent(
            "event_task",
            LedgerEventKind.USER_TASK,
            payload={"task_length": len(TASK_SECRET)},
        )
    ]
    input_tokens_used = 0
    for index, (input_tokens, output_tokens, latency_ms) in enumerate(
        model_usage, start=1
    ):
        if input_tokens is not None:
            input_tokens_used += input_tokens
        payload: dict[str, object] = {
            "text_length": 10,
            "tool_call_count": int(tool_name is not None and index == len(model_usage)),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        if latency_ms is not None:
            payload["latency_ms"] = latency_ms
        events.append(
            LedgerEvent(
                f"event_model_{index}",
                LedgerEventKind.MODEL_TURN,
                payload=payload,
            )
        )

    side_effects = 0
    if tool_name is not None:
        identity = CallIdentity(run_id, "turn_tool", "call_1")
        arguments = {"text": TYPED_SECRET} if tool_name == "type" else {}
        call = ToolCall(identity=identity, name=tool_name, arguments=arguments)
        summary = SafeArgumentSummary.from_tool_call(
            call,
            sensitive_arguments=("text",) if tool_name == "type" else (),
        )
        dispatch = (
            DispatchCertainty.UNKNOWN
            if tool_status is ToolResultStatus.UNKNOWN_OUTCOME
            else DispatchCertainty.DISPATCHED
        )
        result = ToolResult(
            identity=identity,
            tool_name=tool_name,
            status=tool_status,
            dispatch=dispatch,
            sanitized_text="safe result" if tool_name != "type" else "",
        )
        events.append(
            LedgerEvent(
                "event_tool_call",
                LedgerEventKind.TOOL_CALL,
                identity=identity,
                safe_argument_summary=summary,
            )
        )
        result_payload = {} if tool_latency_ms is None else {"latency_ms": tool_latency_ms}
        events.append(
            LedgerEvent(
                "event_tool_result",
                LedgerEventKind.TOOL_RESULT,
                payload=result_payload,
                identity=identity,
                tool_result=result,
            )
        )
        events.append(
            LedgerEvent(
                "event_observation",
                LedgerEventKind.OBSERVATION,
                payload={"tool_name": tool_name, "observation_epoch": 1},
            )
        )
        side_effects = int(tool_name == "type")

    state = RunState(
        run_id=run_id,
        task=TASK_SECRET,
        policy_version="policy-v1",
        observation_epoch=1,
        verified_observation_epoch=1 if phase is RunPhase.SUCCESS else None,
        budgets=RunBudget(
            max_model_turns=max(1, len(model_usage)),
            max_tool_calls=int(tool_name is not None),
            max_side_effects=side_effects,
            model_turns_used=len(model_usage),
            tool_calls_used=int(tool_name is not None),
            side_effects_used=side_effects,
            input_tokens_used=input_tokens_used,
        ),
        event_log=tuple(events),
        recovery_status=(
            RecoveryStatus.UNKNOWN_OUTCOME
            if tool_status is ToolResultStatus.UNKNOWN_OUTCOME
            else RecoveryStatus.READY
        ),
    )
    state_dir = (tmp_path / "state").resolve()
    recorder = RunRecorder(state_dir, run_id)
    recorder.start(state)
    if phase is RunPhase.SUCCESS:
        recorder.record(state, RunPhase.OBSERVING)
        recorder.record(state, RunPhase.PLANNING)
        recorder.record(state, phase, run_duration_ms=run_duration_ms)
    elif phase is RunPhase.UNKNOWN_OUTCOME:
        recorder.record(state, RunPhase.OBSERVING)
        recorder.record(
            state,
            phase,
            failure_code="UNKNOWN_OUTCOME",
            run_duration_ms=run_duration_ms,
        )
    else:
        recorder.record(
            state,
            phase,
            failure_code=(
                "CANCELLED" if phase is RunPhase.CANCELLED else "VERIFIED_FAILURE"
            ),
            run_duration_ms=run_duration_ms,
        )
    return state_dir


def _campaign_store(state_dir: Path) -> tuple[CampaignStore, RunLock]:
    lock = RunLock((state_dir.parent / "application").resolve())
    lock.acquire()
    store = CampaignStore(state_dir, lock)
    store.create(
        CampaignManifest.create(
            campaign_id="campaign_1",
            kind="saved_job_review",
            policy_digest="a" * 64,
            schema_digest="b" * 64,
        )
    )
    return store, lock


def _append_campaign_item(
    store: CampaignStore,
    *,
    status: ItemStatus,
    run_id: str = "run_1",
) -> None:
    common = {
        "sequence": 1,
        "ordinal": 1,
        "item_key": "private:item:key",
        "at": NOW.isoformat(timespec="seconds"),
    }
    store.append(
        "campaign_1",
        ItemTransition(status=ItemStatus.DISCOVERED, attempt=0, **common),
    )
    store.append(
        "campaign_1",
        ItemTransition(
            status=ItemStatus.CLAIMED,
            attempt=1,
            run_id=run_id,
            lease_expires_at=(NOW + timedelta(minutes=10)).isoformat(timespec="seconds"),
            boundary="claim",
            **common,
        ),
    )
    store.append(
        "campaign_1",
        ItemTransition(
            status=ItemStatus.OBSERVED,
            attempt=1,
            run_id=run_id,
            boundary="identity_verified",
            **common,
        ),
    )
    if status in {ItemStatus.COMMITTED, ItemStatus.SKIPPED}:
        store.append(
            "campaign_1",
            ItemTransition(
                status=ItemStatus.EXTRACTED,
                attempt=1,
                run_id=run_id,
                boundary="read_only_extract",
                **common,
            ),
        )
    store.append(
        "campaign_1",
        ItemTransition(
            status=status,
            attempt=1,
            run_id=run_id,
            boundary="episode_boundary",
            code="OK" if status is ItemStatus.COMMITTED else f"KNOWN_{status.value}",
            content_digest="c" * 64 if status is ItemStatus.COMMITTED else None,
            **common,
        ),
    )


def _snapshot_files(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_complete_run_cost_vector_is_exact_redacted_and_read_only(
    tmp_path: Path,
) -> None:
    state_dir = _record_run(
        tmp_path,
        model_usage=((3, 2, 7),),
        tool_name="ui_snapshot",
        tool_latency_ms=5,
    )
    before = _snapshot_files(state_dir)

    episode = build_episode_outcome(state_dir, "run_1")
    repeated = build_episode_outcome(state_dir, "run_1")
    payload = episode.to_payload()

    assert repeated == episode
    assert episode.outcome is EpisodeOutcomeLabel.VERIFIED_SUCCESS
    assert episode.external_effect is ExternalEffectEvidence.NONE
    assert payload["episode_outcome_version"] == EPISODE_OUTCOME_VERSION
    assert payload["data_class"] == EPISODE_DATA_CLASS
    assert payload["use"] == EPISODE_USE
    assert payload["outcome_scope"] == "run"
    assert payload["cost_scope"] == "run"
    assert payload["costs"]["model_calls"] == {
        "value": 1,
        "observed": 1,
        "coverage": "complete",
    }
    assert payload["costs"]["input_tokens"]["value"] == 3
    assert payload["costs"]["output_tokens"]["value"] == 2
    assert payload["costs"]["provider_latency_ms"]["value"] == 7
    assert payload["costs"]["tool_latency_ms"]["value"] == 5
    assert payload["costs"]["run_duration_ms"]["value"] == 25
    assert payload["missing_metrics"] == [
        "human_takeover_ms",
        "human_corrections",
        "e_stop_activations",
    ]
    serialized = json.dumps(payload, sort_keys=True)
    assert TASK_SECRET not in serialized
    assert TYPED_SECRET not in serialized
    assert payload["privacy"] == {
        "contains_raw_task": False,
        "contains_model_text": False,
        "contains_tool_result_text": False,
        "contains_images": False,
        "contains_memory": False,
        "contains_continuation": False,
        "contains_campaign_item_key": False,
        "contains_campaign_content_digest": False,
    }
    assert not any(payload["authority"].values())
    assert _snapshot_files(state_dir) == before


def test_missing_and_partial_provider_metrics_are_never_zero_filled(
    tmp_path: Path,
) -> None:
    missing_dir = _record_run(
        tmp_path / "missing",
        model_usage=((None, None, None),),
        run_duration_ms=None,
    )
    missing = build_episode_outcome(missing_dir, "run_1")
    for name in ("input_tokens", "output_tokens", "provider_latency_ms"):
        metric = getattr(missing.costs, name)
        assert metric.value is None
        assert metric.observed == 0
        assert metric.coverage is MetricCoverage.MISSING
    assert missing.costs.run_duration_ms.value is None

    partial_dir = _record_run(
        tmp_path / "partial",
        model_usage=((3, 2, 7), (None, None, None)),
    )
    partial = build_episode_outcome(partial_dir, "run_1")
    assert partial.costs.input_tokens.value is None
    assert partial.costs.input_tokens.observed == 3
    assert partial.costs.input_tokens.coverage is MetricCoverage.PARTIAL
    assert partial.costs.provider_latency_ms.value is None
    assert partial.costs.provider_latency_ms.observed == 7
    assert partial.costs.provider_latency_ms.coverage is MetricCoverage.PARTIAL


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        (RunPhase.SUCCESS, EpisodeOutcomeLabel.VERIFIED_SUCCESS),
        (RunPhase.FAILED, EpisodeOutcomeLabel.VERIFIED_FAILURE),
        (RunPhase.UNKNOWN_OUTCOME, EpisodeOutcomeLabel.UNCERTAIN),
        (RunPhase.CANCELLED, EpisodeOutcomeLabel.CANCELLED),
    ],
)
def test_run_outcomes_come_only_from_terminal_durable_phase(
    tmp_path: Path, phase: RunPhase, expected: EpisodeOutcomeLabel
) -> None:
    state_dir = _record_run(tmp_path, phase=phase)
    assert build_episode_outcome(state_dir, "run_1").outcome is expected


def test_nonterminal_run_is_not_an_episode(tmp_path: Path) -> None:
    state_dir = _record_run(tmp_path)
    checkpoint_path = state_dir / "runs" / "run_1" / "state.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["phase"] = "PLANNING"
    checkpoint.pop("final_text_length", None)
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    with pytest.raises(EpisodeOutcomeError, match="EPISODE_RUN_INCOMPLETE"):
        build_episode_outcome(state_dir, "run_1")


def test_successful_side_effect_and_uncertain_dispatch_remain_distinct(
    tmp_path: Path,
) -> None:
    success_dir = _record_run(
        tmp_path / "success",
        model_usage=((1, 1, 1),),
        tool_name="type",
        tool_latency_ms=1,
    )
    success = build_episode_outcome(success_dir, "run_1")
    assert success.external_effect is ExternalEffectEvidence.VERIFIED_COMMITTED

    uncertain_dir = _record_run(
        tmp_path / "uncertain",
        phase=RunPhase.UNKNOWN_OUTCOME,
        model_usage=((1, 1, 1),),
        tool_name="type",
        tool_status=ToolResultStatus.UNKNOWN_OUTCOME,
        tool_latency_ms=1,
    )
    uncertain = build_episode_outcome(uncertain_dir, "run_1")
    assert uncertain.outcome is EpisodeOutcomeLabel.UNCERTAIN
    assert uncertain.external_effect is ExternalEffectEvidence.UNKNOWN


def test_cost_vector_has_a_fixed_complete_dimension_set(tmp_path: Path) -> None:
    state_dir = _record_run(tmp_path)
    payload = build_episode_outcome(state_dir, "run_1").costs.to_payload()
    assert set(payload) == {field.name for field in EpisodeCostVector.__dataclass_fields__.values()}
    assert all(set(metric) == {"value", "observed", "coverage"} for metric in payload.values())


def test_tampered_metric_reconciliation_fails_closed(tmp_path: Path) -> None:
    state_dir = _record_run(tmp_path, model_usage=((3, 2, 7),))
    checkpoint_path = state_dir / "runs" / "run_1" / "state.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["metrics"]["model_calls"] = 2
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    with pytest.raises(
        EpisodeOutcomeError, match="EPISODE_COST_RECONCILIATION_FAILED"
    ):
        build_episode_outcome(state_dir, "run_1")

    checkpoint["metrics"]["model_calls"] = 1
    checkpoint["budgets"]["input_tokens_used"] = 4
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    with pytest.raises(
        EpisodeOutcomeError, match="EPISODE_COST_RECONCILIATION_FAILED"
    ):
        build_episode_outcome(state_dir, "run_1")


@pytest.mark.parametrize(
    ("item_status", "run_phase", "expected"),
    [
        (ItemStatus.COMMITTED, RunPhase.SUCCESS, EpisodeOutcomeLabel.VERIFIED_SUCCESS),
        (ItemStatus.CHALLENGE, RunPhase.SUCCESS, EpisodeOutcomeLabel.CHALLENGED),
        (ItemStatus.RETRYABLE, RunPhase.SUCCESS, EpisodeOutcomeLabel.VERIFIED_FAILURE),
        (ItemStatus.UNCERTAIN, RunPhase.SUCCESS, EpisodeOutcomeLabel.CONFLICTED),
        (ItemStatus.COMMITTED, RunPhase.FAILED, EpisodeOutcomeLabel.CONFLICTED),
    ],
)
def test_campaign_item_evidence_reconciles_without_item_content(
    tmp_path: Path,
    item_status: ItemStatus,
    run_phase: RunPhase,
    expected: EpisodeOutcomeLabel,
) -> None:
    state_dir = _record_run(tmp_path, phase=run_phase)
    store, lock = _campaign_store(state_dir)
    try:
        _append_campaign_item(store, status=item_status)
        before = _snapshot_files(state_dir)
        episode = build_episode_outcome(
            state_dir,
            "run_1",
            campaign_store=store,
            campaign_id="campaign_1",
            item_ordinal=1,
        )

        assert episode.outcome is expected
        assert episode.campaign is not None
        payload = episode.to_payload()
        assert payload["outcome_scope"] == "campaign_item"
        assert payload["cost_scope"] == "run"
        serialized = json.dumps(payload, sort_keys=True)
        assert "private:item:key" not in serialized
        assert "c" * 64 not in payload["campaign"].values()
        assert _snapshot_files(state_dir) == before
    finally:
        lock.release()


def test_campaign_source_mismatch_incomplete_item_and_partial_input_fail_closed(
    tmp_path: Path,
) -> None:
    state_dir = _record_run(tmp_path)
    store, lock = _campaign_store(state_dir)
    try:
        _append_campaign_item(store, status=ItemStatus.COMMITTED, run_id="run_other")
        with pytest.raises(EpisodeOutcomeError, match="EPISODE_CAMPAIGN_RUN_MISMATCH"):
            build_episode_outcome(
                state_dir,
                "run_1",
                campaign_store=store,
                campaign_id="campaign_1",
                item_ordinal=1,
            )
        with pytest.raises(EpisodeOutcomeError, match="EPISODE_CAMPAIGN_INPUT_INVALID"):
            build_episode_outcome(state_dir, "run_1", campaign_store=store)
    finally:
        lock.release()

    other_dir = (tmp_path / "other_state").resolve()
    other_store, other_lock = _campaign_store(other_dir)
    try:
        with pytest.raises(
            EpisodeOutcomeError, match="EPISODE_CAMPAIGN_SOURCE_MISMATCH"
        ):
            build_episode_outcome(
                state_dir,
                "run_1",
                campaign_store=other_store,
                campaign_id="campaign_1",
                item_ordinal=1,
            )
    finally:
        other_lock.release()

    incomplete_dir = _record_run(tmp_path / "incomplete")
    incomplete_store, incomplete_lock = _campaign_store(incomplete_dir)
    try:
        incomplete_store.append(
            "campaign_1",
            ItemTransition(
                sequence=1,
                ordinal=1,
                item_key="private:item:key",
                status=ItemStatus.DISCOVERED,
                attempt=0,
                at=NOW.isoformat(timespec="seconds"),
            ),
        )
        with pytest.raises(EpisodeOutcomeError, match="EPISODE_CAMPAIGN_INCOMPLETE"):
            build_episode_outcome(
                incomplete_dir,
                "run_1",
                campaign_store=incomplete_store,
                campaign_id="campaign_1",
                item_ordinal=1,
            )
        with pytest.raises(
            EpisodeOutcomeError, match="EPISODE_CAMPAIGN_INPUT_INVALID"
        ):
            build_episode_outcome(
                incomplete_dir,
                "run_1",
                campaign_store=incomplete_store,
                campaign_id="campaign_1",
                item_ordinal=True,  # type: ignore[arg-type]
            )
    finally:
        incomplete_lock.release()
