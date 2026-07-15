from __future__ import annotations

import pytest

from computer_use_agent.batching import (
    BatchPlanningError,
    BatchPolicy,
    BatchStopReason,
    BatchUsage,
    batch_stop_reason,
    plan_batch,
)
from computer_use_agent.campaign import ItemStatus, ItemTransition, reduce_item_ledger


def _transition(
    sequence: int, ordinal: int, item_key: str, status: ItemStatus, *, attempt: int = 0
) -> ItemTransition:
    kwargs: dict[str, object] = {}
    if status is not ItemStatus.DISCOVERED:
        kwargs = {"run_id": "run_1", "boundary": "observed", "code": "RETRY"}
    return ItemTransition(
        sequence=sequence,
        ordinal=ordinal,
        item_key=item_key,
        status=status,
        attempt=attempt,
        at="2026-07-15T00:00:00+00:00",
        **kwargs,  # type: ignore[arg-type]
    )


def test_plan_batch_is_deterministic_read_only_and_excludes_noneligible_states() -> None:
    projection = reduce_item_ledger(
        (
            _transition(1, 3, "item_3", ItemStatus.DISCOVERED),
            _transition(2, 1, "item_1", ItemStatus.DISCOVERED),
            _transition(3, 2, "item_2", ItemStatus.DISCOVERED),
            _transition(4, 2, "item_2", ItemStatus.CLAIMED, attempt=1),
            _transition(5, 3, "item_3", ItemStatus.CLAIMED, attempt=1),
            _transition(6, 3, "item_3", ItemStatus.OBSERVED, attempt=1),
            _transition(7, 3, "item_3", ItemStatus.RETRYABLE, attempt=1),
        )
    )

    plan = plan_batch(projection, BatchPolicy(max_items=2), BatchUsage())

    assert plan.item_keys == ("item_1", "item_3")
    assert plan.stop_reason is None
    assert projection.items["item_1"].status is ItemStatus.DISCOVERED
    assert projection.items["item_3"].status is ItemStatus.RETRYABLE


@pytest.mark.parametrize(
    ("usage", "reason"),
    [
        (BatchUsage(items_completed=1), BatchStopReason.ITEM_LIMIT),
        (BatchUsage(elapsed_seconds=1), BatchStopReason.WALL_TIME_LIMIT),
        (BatchUsage(provider_turns=1), BatchStopReason.PROVIDER_TURN_LIMIT),
        (BatchUsage(tool_calls=1), BatchStopReason.TOOL_CALL_LIMIT),
        (BatchUsage(input_tokens=1), BatchStopReason.INPUT_TOKEN_LIMIT),
        (BatchUsage(output_tokens=1), BatchStopReason.OUTPUT_TOKEN_LIMIT),
        (BatchUsage(screenshots=1), BatchStopReason.SCREENSHOT_LIMIT),
        (BatchUsage(ocr_regions=1), BatchStopReason.OCR_REGION_LIMIT),
        (BatchUsage(consecutive_failures=1), BatchStopReason.CONSECUTIVE_FAILURE_LIMIT),
    ],
)
def test_every_batch_limit_stops_before_item_selection(
    usage: BatchUsage, reason: BatchStopReason
) -> None:
    policy = BatchPolicy(
        max_items=1,
        max_elapsed_seconds=1,
        max_provider_turns=1,
        max_tool_calls=1,
        max_input_tokens=1,
        max_output_tokens=1,
        max_screenshots=1,
        max_ocr_regions=1,
        max_consecutive_failures=1,
    )
    assert batch_stop_reason(policy, usage) is reason


def test_empty_or_only_claimed_projection_has_a_fixed_stop_reason() -> None:
    empty = reduce_item_ledger(())
    claimed = reduce_item_ledger(
        (
            _transition(1, 1, "item_1", ItemStatus.DISCOVERED),
            _transition(2, 1, "item_1", ItemStatus.CLAIMED, attempt=1),
        )
    )

    assert plan_batch(empty, BatchPolicy(), BatchUsage()).stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS
    assert plan_batch(claimed, BatchPolicy(), BatchUsage()).stop_reason is BatchStopReason.NO_ELIGIBLE_ITEMS


@pytest.mark.parametrize("invalid", [0, -1, True, "1"])
def test_policy_rejects_unbounded_or_invalid_limits(invalid: object) -> None:
    with pytest.raises(BatchPlanningError):
        BatchPolicy(max_items=invalid)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid", [-1, True, "1"])
def test_usage_rejects_invalid_counters(invalid: object) -> None:
    with pytest.raises(BatchPlanningError):
        BatchUsage(tool_calls=invalid)  # type: ignore[arg-type]
