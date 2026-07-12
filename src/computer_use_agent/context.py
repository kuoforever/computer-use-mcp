"""Budgeted reduction of the canonical in-memory event ledger."""
from __future__ import annotations

from typing import Sequence

from .types import LedgerEvent, LedgerEventKind


class ContextBudgetError(RuntimeError):
    """Raised when mandatory safety/context events cannot fit the hard budget."""


def _identity_closure(events: Sequence[LedgerEvent], indexes: set[int]) -> set[int]:
    identities = {events[index].identity for index in indexes if events[index].identity is not None}
    if not identities:
        return indexes
    return indexes | {
        index for index, event in enumerate(events) if event.identity in identities
    }


def reduce_ledger(
    events: Sequence[LedgerEvent],
    *,
    max_events: int,
    run_id: str,
) -> tuple[LedgerEvent, ...]:
    """Reduce context without splitting correlated calls or dropping safety state."""

    if isinstance(max_events, bool) or not isinstance(max_events, int) or max_events <= 0:
        raise ValueError("max_events must be a positive integer")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id must be a non-empty string")
    ledger = tuple(events)
    if not all(isinstance(event, LedgerEvent) for event in ledger):
        raise ValueError("events must contain only LedgerEvent values")
    if len(ledger) <= max_events:
        return ledger
    if not ledger or ledger[0].kind is not LedgerEventKind.USER_TASK:
        raise ContextBudgetError("CONTEXT_MISSING_USER_TASK")

    required: set[int] = {0}
    model_indexes = [
        index for index, event in enumerate(ledger) if event.kind is LedgerEventKind.MODEL_TURN
    ]
    if model_indexes:
        required.update(range(model_indexes[-1], len(ledger)))
    required.update(
        index
        for index, event in enumerate(ledger)
        if event.kind is LedgerEventKind.POLICY_DECISION
    )
    observation_indexes = [
        index for index, event in enumerate(ledger) if event.kind is LedgerEventKind.OBSERVATION
    ]
    if observation_indexes:
        required.add(observation_indexes[-1])
    required = _identity_closure(ledger, required)
    if len(required) + 1 > max_events:
        raise ContextBudgetError("CONTEXT_REQUIRED_EVENTS_EXCEED_BUDGET")

    selected = set(required)
    for index in range(len(ledger) - 1, 0, -1):
        if index in selected:
            continue
        candidate = _identity_closure(ledger, selected | {index})
        if len(candidate) + 1 <= max_events:
            selected = candidate

    retained = [ledger[index] for index in sorted(selected) if index != 0]
    dropped = len(ledger) - len(selected)
    marker = LedgerEvent(
        event_id=f"{run_id}:context:truncated:{dropped}",
        kind=LedgerEventKind.RECOVERY,
        payload={"status": "context_truncated", "dropped_event_count": dropped},
    )
    return (ledger[0], marker, *retained)


__all__ = ["ContextBudgetError", "reduce_ledger"]
