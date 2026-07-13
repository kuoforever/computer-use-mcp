"""Pure write-ahead operation folding and conservative crash classification.

This module performs no filesystem, provider, or MCP I/O.  A resumable-looking
classification names a future reviewed continuation path; it never authorizes
that path by itself.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


class OperationError(ValueError):
    """Fixed invalid write-ahead operation sequence."""


class OperationKind(str, Enum):
    PROVIDER = "provider"
    TOOL = "tool"


class OperationStage(str, Enum):
    PREPARED = "prepared"
    DISPATCH_INTENT = "dispatch_intent"
    COMPLETED = "completed"


class OperationEffect(str, Enum):
    OBSERVATION = "observation"
    SIDE_EFFECT = "side_effect"


class OperationResult(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    UNKNOWN_OUTCOME = "unknown_outcome"


class ReconstructionAction(str, Enum):
    START_NEW_RUN = "start_new_run"
    HUMAN_REOBSERVE = "human_reobserve"
    DISPATCH_OBSERVATION = "dispatch_observation"
    CONTINUE_PROVIDER = "continue_provider"
    MANDATORY_REOBSERVE = "mandatory_reobserve"
    FAIL_CLOSED = "fail_closed"


class ReconstructionPhase(str, Enum):
    FAILED = "FAILED"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    OBSERVING = "OBSERVING"
    PLANNING = "PLANNING"
    VERIFYING = "VERIFYING"


@dataclass(frozen=True)
class OperationRecord:
    """One durable write-ahead record for an external operation."""

    operation_id: str
    kind: OperationKind
    stage: OperationStage
    effect: OperationEffect | None = None
    result: OperationResult | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id.strip():
            raise OperationError("OPERATION_ID_INVALID")
        if len(self.operation_id) > 384:
            raise OperationError("OPERATION_ID_INVALID")
        if not isinstance(self.kind, OperationKind) or not isinstance(
            self.stage, OperationStage
        ):
            raise OperationError("OPERATION_RECORD_INVALID")
        if self.kind is OperationKind.TOOL and not isinstance(
            self.effect, OperationEffect
        ):
            raise OperationError("OPERATION_EFFECT_REQUIRED")
        if self.kind is OperationKind.PROVIDER and self.effect is not None:
            raise OperationError("OPERATION_EFFECT_FORBIDDEN")
        if self.stage is OperationStage.COMPLETED:
            if not isinstance(self.result, OperationResult):
                raise OperationError("OPERATION_RESULT_REQUIRED")
        elif self.result is not None:
            raise OperationError("OPERATION_RESULT_FORBIDDEN")


@dataclass(frozen=True)
class OperationState:
    """Folded state of exactly one write-ahead operation."""

    operation_id: str
    kind: OperationKind
    stage: OperationStage
    effect: OperationEffect | None
    result: OperationResult | None = None

    def __post_init__(self) -> None:
        OperationRecord(
            operation_id=self.operation_id,
            kind=self.kind,
            stage=self.stage,
            effect=self.effect,
            result=self.result,
        )

    @classmethod
    def prepare(
        cls,
        operation_id: str,
        kind: OperationKind,
        *,
        effect: OperationEffect | None = None,
    ) -> "OperationState":
        record = OperationRecord(operation_id, kind, OperationStage.PREPARED, effect)
        return cls(
            operation_id=record.operation_id,
            kind=record.kind,
            stage=record.stage,
            effect=record.effect,
        )

    def apply(self, record: OperationRecord) -> "OperationState":
        if record.operation_id != self.operation_id:
            raise OperationError("OPERATION_IDENTITY_MISMATCH")
        if record.kind is not self.kind or record.effect is not self.effect:
            raise OperationError("OPERATION_IDENTITY_MISMATCH")
        expected = {
            OperationStage.PREPARED: OperationStage.DISPATCH_INTENT,
            OperationStage.DISPATCH_INTENT: OperationStage.COMPLETED,
        }.get(self.stage)
        if record.stage is not expected:
            raise OperationError("ILLEGAL_OPERATION_TRANSITION")
        return replace(self, stage=record.stage, result=record.result)


def fold_operation_records(records: Iterable[OperationRecord]) -> tuple[OperationState, ...]:
    """Fold an append-only record stream and reject gaps or interleaving."""

    states: list[OperationState] = []
    current: OperationState | None = None
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, OperationRecord):
            raise OperationError("OPERATION_RECORD_INVALID")
        if record.stage is OperationStage.PREPARED:
            if current is not None and current.stage is not OperationStage.COMPLETED:
                raise OperationError("OPERATION_INTERLEAVED")
            if record.operation_id in seen:
                raise OperationError("OPERATION_ID_REUSED")
            current = OperationState.prepare(
                record.operation_id, record.kind, effect=record.effect
            )
            states.append(current)
            seen.add(record.operation_id)
            continue
        if current is None:
            raise OperationError("OPERATION_PREPARE_MISSING")
        current = current.apply(record)
        states[-1] = current
    if not states:
        raise OperationError("OPERATION_LEDGER_EMPTY")
    return tuple(states)


@dataclass(frozen=True)
class ReconstructionContext:
    """Trusted validation results plus non-executable pending-work metadata."""

    integrity: str = "valid"
    identity_matches: bool = True
    sequence_matches: bool = True
    budget_available: bool = True
    pending_effect: OperationEffect | None = None

    def __post_init__(self) -> None:
        if self.integrity not in {"valid", "corrupt", "expired", "unsafe_path"}:
            raise ValueError("unsupported continuation integrity")
        for value in (
            self.identity_matches,
            self.sequence_matches,
            self.budget_available,
        ):
            if not isinstance(value, bool):
                raise ValueError("reconstruction validation flags must be boolean")
        if self.pending_effect is not None and not isinstance(
            self.pending_effect, OperationEffect
        ):
            raise ValueError("pending_effect must be an OperationEffect or None")


@dataclass(frozen=True)
class ReconstructionDecision:
    action: ReconstructionAction
    reason: str
    final_phase: ReconstructionPhase
    automatic_resume: bool = False
    new_external_calls: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.action, ReconstructionAction):
            raise ValueError("unsupported reconstruction action")
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("reconstruction reason must be non-empty")
        if not isinstance(self.final_phase, ReconstructionPhase):
            raise ValueError("unsupported reconstruction phase")
        if self.automatic_resume or self.new_external_calls:
            raise ValueError("pure reconstruction decisions cannot authorize external calls")


def _decision(
    action: ReconstructionAction, reason: str, phase: ReconstructionPhase
) -> ReconstructionDecision:
    return ReconstructionDecision(action=action, reason=reason, final_phase=phase)


def classify_crash_reconstruction(
    operations: Iterable[OperationRecord],
    *,
    context: ReconstructionContext = ReconstructionContext(),
) -> ReconstructionDecision:
    """Classify the last durable boundary without replaying external work."""

    if not isinstance(context, ReconstructionContext):
        raise ValueError("context must be a ReconstructionContext")
    if context.integrity != "valid":
        reason = {
            "corrupt": "CONTINUATION_CORRUPT",
            "expired": "CONTINUATION_EXPIRED",
            "unsafe_path": "CONTINUATION_UNSAFE_PATH",
        }[context.integrity]
        return _decision(
            ReconstructionAction.FAIL_CLOSED, reason, ReconstructionPhase.FAILED
        )
    if not context.identity_matches:
        return _decision(
            ReconstructionAction.START_NEW_RUN,
            "CHECKPOINT_MISMATCH",
            ReconstructionPhase.FAILED,
        )
    if not context.sequence_matches:
        return _decision(
            ReconstructionAction.FAIL_CLOSED,
            "STALE_CONTINUATION",
            ReconstructionPhase.FAILED,
        )
    try:
        states = fold_operation_records(operations)
    except OperationError:
        return _decision(
            ReconstructionAction.FAIL_CLOSED,
            "CONTINUATION_CORRUPT",
            ReconstructionPhase.FAILED,
        )
    return classify_operation_state(states[-1], context=context)


def classify_operation_state(
    current: OperationState,
    *,
    context: ReconstructionContext = ReconstructionContext(),
) -> ReconstructionDecision:
    """Classify an already validated durable operation snapshot."""

    if not isinstance(current, OperationState):
        raise ValueError("current must be an OperationState")
    if not isinstance(context, ReconstructionContext):
        raise ValueError("context must be a ReconstructionContext")
    if context.integrity != "valid":
        reason = {
            "corrupt": "CONTINUATION_CORRUPT",
            "expired": "CONTINUATION_EXPIRED",
            "unsafe_path": "CONTINUATION_UNSAFE_PATH",
        }[context.integrity]
        return _decision(
            ReconstructionAction.FAIL_CLOSED, reason, ReconstructionPhase.FAILED
        )
    if not context.identity_matches:
        return _decision(
            ReconstructionAction.START_NEW_RUN,
            "CHECKPOINT_MISMATCH",
            ReconstructionPhase.FAILED,
        )
    if not context.sequence_matches:
        return _decision(
            ReconstructionAction.FAIL_CLOSED,
            "STALE_CONTINUATION",
            ReconstructionPhase.FAILED,
        )
    if not context.budget_available:
        return _decision(
            ReconstructionAction.START_NEW_RUN,
            "BUDGET_EXHAUSTED",
            ReconstructionPhase.FAILED,
        )
    if current.stage is OperationStage.DISPATCH_INTENT:
        return _decision(
            ReconstructionAction.HUMAN_REOBSERVE,
            "UNKNOWN_OUTCOME",
            ReconstructionPhase.UNKNOWN_OUTCOME,
        )
    if current.stage is OperationStage.PREPARED:
        if (
            current.kind is OperationKind.TOOL
            and current.effect is OperationEffect.OBSERVATION
        ):
            return _decision(
                ReconstructionAction.DISPATCH_OBSERVATION,
                "OBSERVATION_PREPARED",
                ReconstructionPhase.OBSERVING,
            )
        reason = (
            "PROVIDER_REQUEST_PREPARED"
            if current.kind is OperationKind.PROVIDER
            else "PENDING_SIDE_EFFECT"
        )
        return _decision(
            ReconstructionAction.START_NEW_RUN, reason, ReconstructionPhase.FAILED
        )
    if current.result is OperationResult.UNKNOWN_OUTCOME:
        return _decision(
            ReconstructionAction.HUMAN_REOBSERVE,
            "UNKNOWN_OUTCOME",
            ReconstructionPhase.UNKNOWN_OUTCOME,
        )
    if current.kind is OperationKind.PROVIDER:
        if context.pending_effect is OperationEffect.OBSERVATION:
            return _decision(
                ReconstructionAction.DISPATCH_OBSERVATION,
                "PROVIDER_COMPLETED_OBSERVATION_PENDING",
                ReconstructionPhase.OBSERVING,
            )
        return _decision(
            ReconstructionAction.START_NEW_RUN,
            "PENDING_SIDE_EFFECT",
            ReconstructionPhase.FAILED,
        )
    if current.effect is OperationEffect.OBSERVATION:
        return _decision(
            ReconstructionAction.CONTINUE_PROVIDER,
            "OBSERVATION_COMPLETED",
            ReconstructionPhase.PLANNING,
        )
    return _decision(
        ReconstructionAction.MANDATORY_REOBSERVE,
        "SIDE_EFFECT_COMPLETED",
        ReconstructionPhase.VERIFYING,
    )


__all__ = [
    "OperationEffect",
    "OperationError",
    "OperationKind",
    "OperationRecord",
    "OperationResult",
    "OperationStage",
    "OperationState",
    "ReconstructionAction",
    "ReconstructionContext",
    "ReconstructionDecision",
    "ReconstructionPhase",
    "classify_crash_reconstruction",
    "classify_operation_state",
    "fold_operation_records",
]
