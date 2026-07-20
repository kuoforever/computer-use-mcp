"""Temporal PoC, run against a real Temporal test server.

The claim under test is not "Temporal works". It is:

    Temporal decides *when* an activity runs again. The project decides whether
    the side effect may happen again. An eager retry policy must not be able to
    turn a crash into a duplicate.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest

pytest.importorskip("temporalio", reason="temporal extra not installed")

from temporalio.client import Client  # noqa: E402
from temporalio.testing import WorkflowEnvironment  # noqa: E402
from temporalio.worker import Worker  # noqa: E402

from computer_use_agent.demo_campaign import (  # noqa: E402
    DurableFakeSideEffectSink,
    SideEffectOutcome,
    idempotency_key,
)
from computer_use_agent.temporal_poc import (  # noqa: E402
    TASK_QUEUE,
    ItemDecision,
    PocConfig,
    build_workflow_and_activities,
    prepare_campaign,
)

ITEMS = 4


def _run(coro):
    """Run one coroutine. Avoids depending on an async pytest plugin."""

    return asyncio.run(coro)


def _config(tmp_path: Path) -> PocConfig:
    return PocConfig(state_dir=tmp_path.resolve(), campaign_id="poc-campaign")


def _item_keys() -> list[str]:
    return [f"demo-item-{index:04d}" for index in range(1, ITEMS + 1)]


def _sink(config: PocConfig) -> DurableFakeSideEffectSink:
    return DurableFakeSideEffectSink(
        (config.state_dir / "sink" / "side-effects.jsonl").resolve()
    )


def _duplicate_attempts(config: PocConfig) -> int:
    return len(_sink(config).duplicate_attempts())


async def _scenario(config: PocConfig, fault: dict | None) -> dict:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        return await _execute(env.client, config, fault)


async def _execute(client: Client, config: PocConfig, fault: dict | None) -> dict:
    workflow_cls, activities = build_workflow_and_activities(config)
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[workflow_cls],
        activities=activities,
    ):
        return await client.execute_workflow(
            "CampaignWorkflow",
            args=[_item_keys(), fault],
            id=f"poc-{uuid.uuid4().hex}",
            task_queue=TASK_QUEUE,
        )


def test_worker_crash_after_commit_continues_without_duplicates(tmp_path: Path) -> None:
    """Case 1: safe redispatch. The ledger proves what is already done."""
    config = _config(tmp_path)
    prepare_campaign(config, item_count=ITEMS)

    result = _run(_scenario(config, {"point": "after_item_commit", "ordinal": 2}))

    assert sorted(result["committed"]) == sorted(_item_keys())
    assert result["attention"] == []
    assert result["pending"] == []
    assert _duplicate_attempts(config) == 0


def test_uncertain_dispatch_stops_for_attention_and_is_never_replayed(tmp_path: Path) -> None:
    """Case 2: the one that matters.

    The worker dies between the durable intent and the result. Temporal is
    configured to retry. The item must end in attention with exactly one
    side-effect attempt recorded.
    """
    config = _config(tmp_path)
    prepare_campaign(config, item_count=ITEMS)

    result = _run(_scenario(config, {"point": "after_dispatch_intent", "ordinal": 2}))

    assert len(result["attention"]) == 1
    parked = result["attention"][0]
    assert parked not in result["committed"]
    assert _duplicate_attempts(config) == 0

    # The sink must still hold exactly one record for that key: an intent with
    # no result. A replay would have produced a second attempt.
    sink = _sink(config)
    key = idempotency_key(config.campaign_id, parked)
    assert sink.outcome_for(key) is SideEffectOutcome.PENDING
    assert sink.receipt_for(key) is None


def test_the_workflow_reports_attention_through_a_query(tmp_path: Path) -> None:
    """An operator must be able to see what stopped without reading files."""
    config = _config(tmp_path)
    prepare_campaign(config, item_count=ITEMS)

    async def scenario():
        workflow_cls, activities = build_workflow_and_activities(config)
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=TASK_QUEUE,
                workflows=[workflow_cls],
                activities=activities,
            ):
                handle = await env.client.start_workflow(
                    "CampaignWorkflow",
                    args=[_item_keys(), {"point": "after_dispatch_intent", "ordinal": 1}],
                    id=f"poc-{uuid.uuid4().hex}",
                    task_queue=TASK_QUEUE,
                )
                return await handle.result(), await handle.query("attention_items")

    result, queried = _run(scenario())

    assert queried == result["attention"]
    assert len(queried) == 1


def test_clean_run_commits_everything(tmp_path: Path) -> None:
    config = _config(tmp_path)
    prepare_campaign(config, item_count=ITEMS)

    result = _run(_scenario(config, None))

    assert sorted(result["committed"]) == sorted(_item_keys())
    assert result["attention"] == []
    assert _duplicate_attempts(config) == 0


def test_decisions_are_derived_from_durable_state_only() -> None:
    """The safety decision must not have a Temporal-shaped input."""
    import inspect

    from computer_use_agent import temporal_poc

    source = inspect.getsource(temporal_poc.classify_item)
    # Compare executable code only. The docstring and comments explain the
    # relationship to Temporal on purpose; the implementation must not depend
    # on it.
    body = source.split('"""')[2] if source.count('"""') >= 2 else source
    code = " ".join(line.split("#", 1)[0] for line in body.splitlines())
    for temporal_term in ("temporal", "workflow", "activity", "retry"):
        assert temporal_term not in code.lower()
    assert set(ItemDecision) == {
        ItemDecision.DISPATCH,
        ItemDecision.ALREADY_COMMITTED,
        ItemDecision.ATTENTION,
    }
