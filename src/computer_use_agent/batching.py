"""Pure bounded batch selection for durable campaigns.

This module deliberately plans only.  It has no clock, persistence, provider,
MCP, desktop, or runner dependency; a future worker must supply measured usage
and decide when to write a durable item transition.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .campaign import CampaignProjection, ItemStatus


class BatchPlanningError(ValueError):
    """Raised when a batch policy or measured usage is not bounded."""


class BatchStopReason(str, Enum):
    NO_ELIGIBLE_ITEMS = "NO_ELIGIBLE_ITEMS"
    ITEM_LIMIT = "ITEM_LIMIT"
    WALL_TIME_LIMIT = "WALL_TIME_LIMIT"
    PROVIDER_TURN_LIMIT = "PROVIDER_TURN_LIMIT"
    TOOL_CALL_LIMIT = "TOOL_CALL_LIMIT"
    INPUT_TOKEN_LIMIT = "INPUT_TOKEN_LIMIT"
    OUTPUT_TOKEN_LIMIT = "OUTPUT_TOKEN_LIMIT"
    SCREENSHOT_LIMIT = "SCREENSHOT_LIMIT"
    OCR_REGION_LIMIT = "OCR_REGION_LIMIT"
    CONSECUTIVE_FAILURE_LIMIT = "CONSECUTIVE_FAILURE_LIMIT"


def _positive(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BatchPlanningError(f"{name} must be a positive integer")
    return value


def _nonnegative(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BatchPlanningError(f"{name} must be a nonnegative integer")
    return value


@dataclass(frozen=True)
class BatchPolicy:
    """All hard limits for one provider-context batch."""

    max_items: int = 20
    max_elapsed_seconds: int = 20 * 60
    max_provider_turns: int = 12
    max_tool_calls: int = 32
    max_input_tokens: int = 100_000
    max_output_tokens: int = 25_000
    max_screenshots: int = 40
    max_ocr_regions: int = 40
    max_consecutive_failures: int = 3

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            _positive(name, value)


@dataclass(frozen=True)
class BatchUsage:
    """Counters measured by a future worker; never inferred from conversation."""

    items_completed: int = 0
    elapsed_seconds: int = 0
    provider_turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    screenshots: int = 0
    ocr_regions: int = 0
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        for name, value in vars(self).items():
            _nonnegative(name, value)


@dataclass(frozen=True)
class BatchPlan:
    """A deterministic read-only selection; it does not claim or mutate items."""

    item_keys: tuple[str, ...]
    stop_reason: BatchStopReason | None


def batch_stop_reason(policy: BatchPolicy, usage: BatchUsage) -> BatchStopReason | None:
    """Return the first reached hard limit in a fixed, auditable order."""

    checks = (
        (usage.items_completed, policy.max_items, BatchStopReason.ITEM_LIMIT),
        (usage.elapsed_seconds, policy.max_elapsed_seconds, BatchStopReason.WALL_TIME_LIMIT),
        (usage.provider_turns, policy.max_provider_turns, BatchStopReason.PROVIDER_TURN_LIMIT),
        (usage.tool_calls, policy.max_tool_calls, BatchStopReason.TOOL_CALL_LIMIT),
        (usage.input_tokens, policy.max_input_tokens, BatchStopReason.INPUT_TOKEN_LIMIT),
        (usage.output_tokens, policy.max_output_tokens, BatchStopReason.OUTPUT_TOKEN_LIMIT),
        (usage.screenshots, policy.max_screenshots, BatchStopReason.SCREENSHOT_LIMIT),
        (usage.ocr_regions, policy.max_ocr_regions, BatchStopReason.OCR_REGION_LIMIT),
        (
            usage.consecutive_failures,
            policy.max_consecutive_failures,
            BatchStopReason.CONSECUTIVE_FAILURE_LIMIT,
        ),
    )
    for used, maximum, reason in checks:
        if used >= maximum:
            return reason
    return None


def plan_batch(projection: CampaignProjection, policy: BatchPolicy, usage: BatchUsage) -> BatchPlan:
    """Choose unclaimed discovered/retryable items by stable ordinal only."""

    reason = batch_stop_reason(policy, usage)
    if reason is not None:
        return BatchPlan(item_keys=(), stop_reason=reason)
    eligible = sorted(
        (
            item
            for item in projection.items.values()
            if item.status in {ItemStatus.DISCOVERED, ItemStatus.RETRYABLE}
        ),
        key=lambda item: (item.ordinal, item.item_key),
    )
    item_keys = tuple(item.item_key for item in eligible[: policy.max_items])
    return BatchPlan(
        item_keys=item_keys,
        stop_reason=None if item_keys else BatchStopReason.NO_ELIGIBLE_ITEMS,
    )
