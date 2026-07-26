from __future__ import annotations

import asyncio
import base64
import json
from collections import deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from computer_use_agent.boss_campaign_batch_runtime import (
    BOSS_SEMANTIC_BATCH_POLICY,
    BossCampaignBatchRuntimeError,
    start_boss_semantic_batch,
)
from computer_use_agent.boss_campaign_discovery import (
    create_boss_discovery_campaign,
    record_boss_snapshot_discoveries,
)
from computer_use_agent.boss_campaign_restart_runtime import (
    BossCampaignRestartRuntimeError,
    resume_finished_boss_semantic_batch_after_restart,
)
from computer_use_agent.boss_semantic_extraction import (
    BOSS_SEMANTIC_SCHEMA_VERSION,
    BossObservationSource,
    BossObservationStatus,
    boss_initial_classification_policy_digest,
)
from computer_use_agent.boss_semantic_item_runtime import (
    BOSS_SEMANTIC_INITIAL_CALL_ID,
    BOSS_SEMANTIC_INITIAL_TURN_ID,
    BossSemanticItemRuntimeError,
    boss_tool_result_content_digest,
    execute_claimed_boss_semantics_through_handoff,
)
from computer_use_agent.campaign import CampaignStore, ItemStatus, campaign_dir
from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
)
from computer_use_agent.fakes import (
    FakeApprovalPort,
    FakeDesktopMCP,
    FakeModelProvider,
)
from computer_use_agent.run_lock import RunLock
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ModelTurn,
    ModelUsage,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


NOW = datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc)
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AgentConfig:
    local = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    return AgentConfig(
        state_dir=(local / "computer-use-agent" / "boss-semantic").resolve(),
        policy_version="readonly-v1",
        provider=ProviderConfig("openai", "test-semantic-model"),
        mcp=MCPLaunchConfig(
            tmp_path / "computer-use-mcp.exe",
            (),
            tmp_path,
            {"CUMCP_ALLOWLIST": "chrome.exe"},
        ),
        policy=PolicyConfig(
            max_model_turns=5,
            max_tool_calls=5,
            max_side_effects=0,
        ),
    )


def _snapshot(*public_ids: str, marker: str) -> str:
    return "\n".join(
        (
            f'ref_{index} | hyperlink "Bounded role" | '
            f"({10 * index},{20 * index},300,80) | enabled "
            f'| value="https://www.zhipin.com/job_detail/{public_id}.html'
            f'?ka=personal_interest_brand_{marker}&securityId=discard-me"'
        )
        for index, public_id in enumerate(public_ids, start=1)
    )


def _prepare_discovery(config: AgentConfig) -> None:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    try:
        store = CampaignStore(config.state_dir, lock)
        create_boss_discovery_campaign(
            store,
            campaign_id="campaign_1",
            created_at=NOW.isoformat(timespec="seconds"),
        )
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_snapshot(
                "publicjob001",
                "publicjob002",
                marker="abc123",
            ),
            observed_at=NOW.isoformat(timespec="seconds"),
        )
        record_boss_snapshot_discoveries(
            store,
            campaign_id="campaign_1",
            snapshot_text=_snapshot(
                "publicjob003",
                "publicjob004",
                marker="def456",
            ),
            observed_at=NOW.replace(minute=1).isoformat(timespec="seconds"),
        )
    finally:
        lock.release()


def _prepare(config: AgentConfig) -> None:
    _prepare_discovery(config)
    start_boss_semantic_batch(
        AgentRunner(config),
        campaign_id="campaign_1",
        run_id="semantic_run_1",
        now=NOW.replace(minute=2),
    )


def _initial_result(text: str) -> ToolResult:
    return ToolResult(
        identity=CallIdentity(
            "semantic_run_1",
            BOSS_SEMANTIC_INITIAL_TURN_ID,
            BOSS_SEMANTIC_INITIAL_CALL_ID,
        ),
        tool_name="ui_snapshot",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text=text,
    )


def _tool_result(
    *,
    turn: int,
    call_id: str,
    tool_name: str,
    text: str,
    image: bool = False,
) -> ToolResult:
    return ToolResult(
        identity=CallIdentity(
            "semantic_run_1",
            f"boss_semantic_turn_{turn}",
            call_id,
        ),
        tool_name=tool_name,
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
        sanitized_text=text,
        images=(
            (ImageContent("image/png", _PNG, 1, 1),)
            if image
            else ()
        ),
    )


def _semantic_payload(source: BossObservationSource, digest: str) -> dict[str, object]:
    return {
        "schema_version": BOSS_SEMANTIC_SCHEMA_VERSION,
        "item_key": "boss:job:publicjob001",
        "company": "Example Company",
        "role": "AI Engineer",
        "location": "Shanghai",
        "compensation": None,
        "experience": "3-5 years",
        "classification": "INSUFFICIENT_EVIDENCE",
        "classification_reasons": ["INSUFFICIENT_EVIDENCE"],
        "classification_policy_digest": boss_initial_classification_policy_digest(),
        "source": source.value,
        "source_digest": digest,
    }


def _final_turn(turn: int, payload: dict[str, object]) -> ModelTurn:
    return ModelTurn(
        run_id="semantic_run_1",
        turn_id=f"boss_semantic_turn_{turn}",
        provider_response_id=f"response_{turn}",
        text=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        usage=ModelUsage(input_tokens=100, output_tokens=50),
    )


def _incomplete_turn(
    turn: int,
    *,
    prior_digest: str,
    reason: str,
    tool_name: str,
    arguments: dict[str, object],
) -> ModelTurn:
    return ModelTurn(
        run_id="semantic_run_1",
        turn_id=f"boss_semantic_turn_{turn}",
        provider_response_id=f"response_{turn}",
        text=json.dumps(
            {
                "status": "INCOMPLETE",
                "content_digest": prior_digest,
                "incomplete_reason": reason,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        tool_calls=(
            ToolCall(
                CallIdentity(
                    "semantic_run_1",
                    f"boss_semantic_turn_{turn}",
                    f"call_{turn}",
                ),
                tool_name,
                arguments,
            ),
        ),
        usage=ModelUsage(input_tokens=100, output_tokens=20),
    )


def _read_store(config: AgentConfig) -> tuple[CampaignStore, RunLock]:
    lock = RunLock(config.application_state_dir)
    lock.acquire()
    return CampaignStore(config.state_dir, lock), lock


def test_semantic_batch_uses_a_separate_one_item_five_call_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)

    assert BOSS_SEMANTIC_BATCH_POLICY.max_items == 1
    assert BOSS_SEMANTIC_BATCH_POLICY.max_provider_turns == 5
    assert BOSS_SEMANTIC_BATCH_POLICY.max_tool_calls == 5

    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        claimed = projection.items["boss:job:publicjob001"]
        assert claimed.status is ItemStatus.CLAIMED
        assert claimed.run_id == "semantic_run_1"
    finally:
        lock.release()


def test_semantic_batch_rejects_action_budget_before_claiming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare_discovery(config)
    unsafe_config = replace(
        config,
        policy=replace(config.policy, max_side_effects=1),
    )

    with pytest.raises(
        BossCampaignBatchRuntimeError,
        match="^BOSS_BATCH_SEMANTIC_POLICY_INVALID$",
    ):
        start_boss_semantic_batch(
            AgentRunner(unsafe_config),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=2),
        )

    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        assert all(
            item.status is ItemStatus.DISCOVERED for item in projection.items.values()
        )
        assert store.read_batches("campaign_1").active is None
        assert store.read_heartbeat("campaign_1") is None
    finally:
        lock.release()


def test_uia_semantics_commit_with_one_runner_call_and_one_provider_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    digest = boss_tool_result_content_digest(initial)
    provider = FakeModelProvider(
        turns=deque([_final_turn(1, _semantic_payload(BossObservationSource.UIA, digest))])
    )
    desktop = FakeDesktopMCP(results=deque([initial]))

    outcome = asyncio.run(
        execute_claimed_boss_semantics_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, FakeApprovalPort()),
            ),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=3),
        )
    )

    assert outcome.semantic_result is not None
    assert outcome.semantic_result.role == "AI Engineer"
    assert outcome.claimed_item_ordinal == 1
    assert outcome.stop_code == "ITEM_LIMIT"
    assert outcome.usage.items_completed == 1
    assert outcome.usage.tool_calls == 1
    assert outcome.usage.provider_turns == 1
    assert outcome.usage.input_tokens == 100
    assert outcome.usage.output_tokens == 50
    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].status is BossObservationStatus.SUFFICIENT
    assert [tool.name for tool in provider.calls[0]["tools"]] == [
        "document_text"
    ]
    assert desktop.close_calls == 1

    store, lock = _read_store(config)
    try:
        item = store.read_ledger("campaign_1").items["boss:job:publicjob001"]
        assert item.status is ItemStatus.COMMITTED
        assert item.content_digest == outcome.semantic_result.content_digest
        assert store.read_handoff("campaign_1")["next_item_ordinal"] == 2
    finally:
        lock.release()
    trace = (config.trace_dir / "semantic_run_1.jsonl").read_text(encoding="utf-8")
    assert "Example Company" not in trace
    assert "AI Engineer" not in trace
    assert "publicjob001" not in trace
    assert read_run_record(config.state_dir, "semantic_run_1")["state"]["phase"] == "SUCCESS"


def test_explicit_incomplete_escalates_to_document_text_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    document = _tool_result(
        turn=1,
        call_id="call_1",
        tool_name="document_text",
        text='{"blocks":[{"text":"Example Company AI Engineer Shanghai"}]}',
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                _incomplete_turn(
                    1,
                    prior_digest=boss_tool_result_content_digest(initial),
                    reason="STATIC_TEXT_ABSENT",
                    tool_name="document_text",
                    arguments={"scope": "foreground"},
                ),
                _final_turn(
                    2,
                    _semantic_payload(
                        BossObservationSource.DOCUMENT_TEXT,
                        boss_tool_result_content_digest(document),
                    ),
                ),
            ]
        )
    )
    desktop = FakeDesktopMCP(results=deque([initial, document]))

    outcome = asyncio.run(
        execute_claimed_boss_semantics_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(provider, desktop, FakeApprovalPort()),
            ),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=3),
        )
    )

    assert [attempt.source for attempt in outcome.attempts] == [
        BossObservationSource.UIA,
        BossObservationSource.DOCUMENT_TEXT,
    ]
    assert outcome.usage.tool_calls == 2
    assert outcome.usage.provider_turns == 2
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "document_text",
    ]
    assert [tool.name for tool in provider.calls[1]["tools"]] == ["ocr"]


def test_provider_cannot_skip_the_disclosed_next_ladder_rung(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                _incomplete_turn(
                    1,
                    prior_digest=boss_tool_result_content_digest(initial),
                    reason="STATIC_TEXT_ABSENT",
                    tool_name="ocr",
                    arguments={"x": 10, "y": 20, "w": 300, "h": 80},
                )
            ]
        )
    )
    desktop = FakeDesktopMCP(results=deque([initial]))

    with pytest.raises(
        BossSemanticItemRuntimeError,
        match="^BOSS_SEMANTIC_TOOL_SEQUENCE_INVALID$",
    ):
        asyncio.run(
            execute_claimed_boss_semantics_through_handoff(
                AgentRunner(
                    config,
                    RunnerPorts(provider, desktop, FakeApprovalPort()),
                ),
                campaign_id="campaign_1",
                run_id="semantic_run_1",
                now=NOW.replace(minute=3),
            )
        )

    assert [call.name for call in desktop.tool_calls] == ["ui_snapshot"]
    store, lock = _read_store(config)
    try:
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].status is ItemStatus.OBSERVED
        assert store.read_batches("campaign_1").active is not None
        assert not (campaign_dir(config.state_dir, "campaign_1") / "handoff.json").exists()
    finally:
        lock.release()


def test_challenge_terminalizes_item_and_writes_failure_limit_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                ModelTurn(
                    run_id="semantic_run_1",
                    turn_id="boss_semantic_turn_1",
                    provider_response_id="response_1",
                    text=json.dumps(
                        {
                            "status": "CHALLENGE_REQUIRED",
                            "content_digest": boss_tool_result_content_digest(initial),
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    usage=ModelUsage(input_tokens=50, output_tokens=10),
                )
            ]
        )
    )

    outcome = asyncio.run(
        execute_claimed_boss_semantics_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(
                    provider,
                    FakeDesktopMCP(results=deque([initial])),
                    FakeApprovalPort(),
                ),
            ),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=3),
        )
    )

    assert outcome.semantic_result is None
    assert outcome.stop_code == "CONSECUTIVE_FAILURE_LIMIT"
    assert outcome.usage.consecutive_failures == 1
    assert outcome.handoff["next_item_ordinal"] == 1
    store, lock = _read_store(config)
    try:
        item = store.read_ledger("campaign_1").items["boss:job:publicjob001"]
        assert item.status is ItemStatus.CHALLENGE
        assert item.code == "CHALLENGE_REQUIRED"
    finally:
        lock.release()


def test_ocr_baseline_denial_handoffs_without_ocr_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    document = _tool_result(
        turn=1,
        call_id="call_1",
        tool_name="document_text",
        text="document incomplete",
    )
    sources = [
        (initial, "STATIC_TEXT_ABSENT", "document_text", {"scope": "foreground"}),
        (
            document,
            "SEMANTIC_CHANNEL_UNAVAILABLE",
            "ocr",
            {"x": 10, "y": 20, "w": 300, "h": 80},
        ),
    ]
    turns = [
        _incomplete_turn(
            index,
            prior_digest=boss_tool_result_content_digest(result),
            reason=reason,
            tool_name=tool,
            arguments=arguments,
        )
        for index, (result, reason, tool, arguments) in enumerate(sources, start=1)
    ]
    desktop = FakeDesktopMCP(results=deque([initial, document]))

    outcome = asyncio.run(
        execute_claimed_boss_semantics_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(
                    FakeModelProvider(turns=deque(turns)),
                    desktop,
                    FakeApprovalPort(),
                ),
            ),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=3),
        )
    )

    assert outcome.semantic_result is None
    assert outcome.stop_code == "CONSECUTIVE_FAILURE_LIMIT"
    assert outcome.usage.tool_calls == 3
    assert outcome.usage.provider_turns == 2
    assert outcome.usage.screenshots == 0
    assert outcome.usage.ocr_regions == 0
    assert [attempt.source for attempt in outcome.attempts] == list(
        BossObservationSource
    )[:2]
    assert [call.name for call in desktop.tool_calls] == [
        "ui_snapshot",
        "document_text",
    ]
    assert outcome.handoff["next_item_ordinal"] == 1
    store, lock = _read_store(config)
    try:
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].status is ItemStatus.RETRYABLE
        assert store.read_ledger("campaign_1").items[
            "boss:job:publicjob001"
        ].code == "CONTENT_UNAVAILABLE"
    finally:
        lock.release()


def test_semantic_result_must_bind_claim_source_policy_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    payload = _semantic_payload(
        BossObservationSource.UIA,
        boss_tool_result_content_digest(initial),
    )
    payload["classification_policy_digest"] = "f" * 64
    provider = FakeModelProvider(turns=deque([_final_turn(1, payload)]))

    with pytest.raises(
        BossSemanticItemRuntimeError,
        match="^BOSS_SEMANTIC_RESULT_MISMATCH$",
    ):
        asyncio.run(
            execute_claimed_boss_semantics_through_handoff(
                AgentRunner(
                    config,
                    RunnerPorts(
                        provider,
                        FakeDesktopMCP(results=deque([initial])),
                        FakeApprovalPort(),
                    ),
                ),
                campaign_id="campaign_1",
                run_id="semantic_run_1",
                now=NOW.replace(minute=3),
            )
        )


def test_committed_semantic_batch_transfers_and_claims_exact_next_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    provider = FakeModelProvider(
        turns=deque(
            [
                _final_turn(
                    1,
                    _semantic_payload(
                        BossObservationSource.UIA,
                        boss_tool_result_content_digest(initial),
                    ),
                )
            ]
        )
    )
    asyncio.run(
        execute_claimed_boss_semantics_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(
                    provider,
                    FakeDesktopMCP(results=deque([initial])),
                    FakeApprovalPort(),
                ),
            ),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=3),
        )
    )

    resumed = resume_finished_boss_semantic_batch_after_restart(
        AgentRunner(config),
        campaign_id="campaign_1",
        replacement_run_id="semantic_run_2",
        now=NOW.replace(minute=10),
    )

    assert resumed.prior_run_id == "semantic_run_1"
    assert resumed.replacement_run_id == "semantic_run_2"
    assert resumed.claimed_item_ordinal == 2
    assert resumed.planned_item_count == 1
    assert resumed.resume.item_keys == ("boss:job:publicjob002",)
    assert resumed.heartbeat.run_id == "semantic_run_2"
    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        assert projection.items["boss:job:publicjob001"].status is ItemStatus.COMMITTED
        assert projection.items["boss:job:publicjob002"].status is ItemStatus.CLAIMED
        assert projection.items["boss:job:publicjob002"].run_id == "semantic_run_2"
    finally:
        lock.release()
    assert not (config.trace_dir / "semantic_run_2.jsonl").exists()


def test_semantic_restart_rejects_action_budget_before_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path, monkeypatch)
    _prepare(config)
    initial = _initial_result(
        _snapshot("publicjob001", "publicjob002", marker="fedcba")
    )
    asyncio.run(
        execute_claimed_boss_semantics_through_handoff(
            AgentRunner(
                config,
                RunnerPorts(
                    FakeModelProvider(
                        turns=deque(
                            [
                                _final_turn(
                                    1,
                                    _semantic_payload(
                                        BossObservationSource.UIA,
                                        boss_tool_result_content_digest(initial),
                                    ),
                                )
                            ]
                        )
                    ),
                    FakeDesktopMCP(results=deque([initial])),
                    FakeApprovalPort(),
                ),
            ),
            campaign_id="campaign_1",
            run_id="semantic_run_1",
            now=NOW.replace(minute=3),
        )
    )
    unsafe_config = replace(
        config,
        policy=replace(config.policy, max_side_effects=1),
    )

    with pytest.raises(
        BossCampaignRestartRuntimeError,
        match="^BOSS_RESTART_SEMANTIC_POLICY_INVALID$",
    ):
        resume_finished_boss_semantic_batch_after_restart(
            AgentRunner(unsafe_config),
            campaign_id="campaign_1",
            replacement_run_id="semantic_run_2",
            now=NOW.replace(minute=10),
        )

    store, lock = _read_store(config)
    try:
        projection = store.read_ledger("campaign_1")
        assert projection.items["boss:job:publicjob001"].status is ItemStatus.COMMITTED
        assert projection.items["boss:job:publicjob002"].status is ItemStatus.DISCOVERED
        assert store.read_heartbeat("campaign_1").run_id == "semantic_run_1"  # type: ignore[union-attr]
        assert store.read_batches("campaign_1").active is None
    finally:
        lock.release()
