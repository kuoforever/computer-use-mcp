"""The Temporal workflow definition, kept out of :mod:`temporal_poc`.

Temporal rejects a workflow class defined inside a function, so this cannot be
built by a factory. Keeping it in its own module preserves the optional
dependency instead: ``temporal_poc`` imports this lazily, and nothing imports
it unless the ``temporal`` extra is installed.

The workflow holds no desktop authority. It sequences activities and reports
what stopped; every safety decision is made by
:func:`computer_use_agent.temporal_poc.classify_item` from durable state.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from temporalio import workflow

from .temporal_poc import FIRST_OWNER, RESUME_OWNER, ItemDecision

__all__ = ["CampaignWorkflow"]


@workflow.defn(name="CampaignWorkflow")
class CampaignWorkflow:
    """Schedules work. It holds no desktop authority of its own."""

    def __init__(self) -> None:
        self._attention: list[str] = []

    @workflow.run
    async def run(
        self, item_keys: list[str], fault: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from temporalio.common import RetryPolicy

        # A generous retry policy on purpose. The safety property must not
        # depend on Temporal being configured cautiously; it must hold even
        # when Temporal is eager to run things again.
        policy = RetryPolicy(maximum_attempts=3)

        first = await workflow.execute_activity(
            "advance_campaign",
            {"fault": fault, "run_id": FIRST_OWNER},
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=policy,
        )
        if first["crashed_at"] is not None:
            # Reconciliation is the project's, not Temporal's. Only after it
            # runs does the workflow learn what is safe to continue. The resume
            # takes a fresh owner id, because reusing the dead owner's id would
            # skip takeover and leave its batch open.
            await workflow.execute_activity(
                "reconcile_campaign",
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=policy,
            )
            await workflow.execute_activity(
                "advance_campaign",
                {"fault": None, "run_id": RESUME_OWNER, "resume": True},
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=policy,
            )
        buckets = await workflow.execute_activity(
            "classify_campaign",
            item_keys,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=policy,
        )
        self._attention = list(buckets[ItemDecision.ATTENTION.value])
        return {
            "committed": buckets[ItemDecision.ALREADY_COMMITTED.value],
            "attention": self._attention,
            "pending": buckets[ItemDecision.DISPATCH.value],
        }

    @workflow.query(name="attention_items")
    def attention_items(self) -> list[str]:
        return list(self._attention)
