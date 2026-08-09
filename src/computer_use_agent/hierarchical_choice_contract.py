"""Content-free H8C ordered-choice and fallback evidence contracts."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256

from .world_state import ConditionOutcome, FactAvailability


CHOICE_EVIDENCE_VERSION = 1
MIN_CHOICE_BRANCHES = 2
MAX_CHOICE_BRANCHES = 16
MAX_CHOICE_WORKERS = 4
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ChoiceContractError(ValueError):
    """Fixed H8C contract failure without task or observation content."""


class ChoiceDisposition(str, Enum):
    SELECTED = "selected"
    FAILED = "failed"
    BLOCKED = "blocked"


class ChoiceFallbackCause(str, Enum):
    PRE_BOUNDARY_FALSE = "pre_boundary_false"
    VERIFIED_READ_ONLY_MISS = "verified_read_only_miss"


class ChoiceBoundaryOutcome(str, Enum):
    PRE_BOUNDARY_FALSE = "pre_boundary_false"
    VERIFIED_READ_ONLY_MISS = "verified_read_only_miss"
    APPROVAL_DENIED = "approval_denied"
    PERMISSION_DENIED = "permission_denied"
    AUTHORITY_LOST = "authority_lost"
    GROUNDING_CONFLICT = "grounding_conflict"
    POLICY_CONFLICT = "policy_conflict"
    BUDGET_CONFLICT = "budget_conflict"
    CANCELLED = "cancelled"
    DISPATCHED_ERROR = "dispatched_error"
    MISSING_VERIFICATION = "missing_verification"
    UNKNOWN_OUTCOME = "unknown_outcome"
    SIDE_EFFECT_FAILURE = "side_effect_failure"


def choice_boundary_allows_fallback(outcome: ChoiceBoundaryOutcome) -> bool:
    """Return true only for the two reviewed fallback evidence classes."""

    if not isinstance(outcome, ChoiceBoundaryOutcome):
        raise ChoiceContractError("CHOICE_BOUNDARY_INVALID")
    return outcome in {
        ChoiceBoundaryOutcome.PRE_BOUNDARY_FALSE,
        ChoiceBoundaryOutcome.VERIFIED_READ_ONLY_MISS,
    }


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ChoiceContractError("CHOICE_IDENTIFIER_INVALID")
    return value


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ChoiceContractError("CHOICE_DIGEST_INVALID")
    return value


def _optional_identifier(value: object) -> str | None:
    return None if value is None else _require_identifier(value)


def _optional_digest(value: object) -> str | None:
    return None if value is None else _require_digest(value)


def _digest_payload(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ChoiceGateResult:
    branch_id: str
    condition_node_id: str
    condition_id: str
    outcome: ConditionOutcome
    availability: FactAvailability
    condition_digest: str
    fact_digest: str | None = None
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.branch_id)
        _require_identifier(self.condition_node_id)
        _require_identifier(self.condition_id)
        _require_digest(self.condition_digest)
        if not isinstance(self.outcome, ConditionOutcome) or not isinstance(
            self.availability, FactAvailability
        ):
            raise ChoiceContractError("CHOICE_GATE_INVALID")
        fresh = self.availability is FactAvailability.FRESH
        if fresh is (self.outcome is ConditionOutcome.UNAVAILABLE):
            raise ChoiceContractError("CHOICE_GATE_INVALID")
        if fresh:
            _require_digest(self.fact_digest)
            _require_digest(self.evidence_digest)
        elif self.fact_digest is not None or self.evidence_digest is not None:
            raise ChoiceContractError("CHOICE_GATE_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "branch_id": self.branch_id,
            "condition_node_id": self.condition_node_id,
            "condition_id": self.condition_id,
            "outcome": self.outcome.value,
            "availability": self.availability.value,
            "condition_digest": self.condition_digest,
            "fact_digest": self.fact_digest,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class ChoiceFallbackEvidence:
    cause: ChoiceFallbackCause
    source_branch_id: str
    failure_node_id: str
    condition_id: str
    condition_digest: str
    fact_digest: str
    evidence_digest: str
    observation_node_id: str | None = None
    observation_evidence_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cause, ChoiceFallbackCause):
            raise ChoiceContractError("CHOICE_FALLBACK_INVALID")
        for value in (
            self.source_branch_id,
            self.failure_node_id,
            self.condition_id,
        ):
            _require_identifier(value)
        for value in (
            self.condition_digest,
            self.fact_digest,
            self.evidence_digest,
        ):
            _require_digest(value)
        _optional_identifier(self.observation_node_id)
        _optional_digest(self.observation_evidence_digest)
        read_only = self.cause is ChoiceFallbackCause.VERIFIED_READ_ONLY_MISS
        if read_only:
            if (
                self.observation_node_id is None
                or self.observation_evidence_digest != self.evidence_digest
            ):
                raise ChoiceContractError("CHOICE_FALLBACK_INVALID")
        elif (
            self.observation_node_id is not None
            or self.observation_evidence_digest is not None
        ):
            raise ChoiceContractError("CHOICE_FALLBACK_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "cause": self.cause.value,
            "source_branch_id": self.source_branch_id,
            "failure_node_id": self.failure_node_id,
            "condition_id": self.condition_id,
            "condition_digest": self.condition_digest,
            "fact_digest": self.fact_digest,
            "evidence_digest": self.evidence_digest,
            "observation_node_id": self.observation_node_id,
            "observation_evidence_digest": self.observation_evidence_digest,
        }


@dataclass(frozen=True)
class ChoiceEvent:
    choice_node_id: str
    source_sequence: int
    source_tree_digest: str
    snapshot_digest: str
    context_digest: str
    disposition: ChoiceDisposition
    results: tuple[ChoiceGateResult, ...]
    selected_branch_id: str | None = None
    fallback: ChoiceFallbackEvidence | None = None
    version: int = CHOICE_EVIDENCE_VERSION

    def __post_init__(self) -> None:
        if self.version != CHOICE_EVIDENCE_VERSION or isinstance(self.version, bool):
            raise ChoiceContractError("CHOICE_VERSION_UNSUPPORTED")
        _require_identifier(self.choice_node_id)
        if (
            isinstance(self.source_sequence, bool)
            or not isinstance(self.source_sequence, int)
            or self.source_sequence < 0
        ):
            raise ChoiceContractError("CHOICE_SEQUENCE_INVALID")
        for value in (
            self.source_tree_digest,
            self.snapshot_digest,
            self.context_digest,
        ):
            _require_digest(value)
        if not isinstance(self.disposition, ChoiceDisposition):
            raise ChoiceContractError("CHOICE_DISPOSITION_INVALID")
        if not isinstance(self.results, tuple) or not all(
            isinstance(result, ChoiceGateResult) for result in self.results
        ):
            raise ChoiceContractError("CHOICE_RESULTS_INVALID")
        if len({result.branch_id for result in self.results}) != len(self.results):
            raise ChoiceContractError("CHOICE_RESULTS_INVALID")
        _optional_identifier(self.selected_branch_id)
        if self.fallback is not None and not isinstance(
            self.fallback, ChoiceFallbackEvidence
        ):
            raise ChoiceContractError("CHOICE_FALLBACK_INVALID")

        first_true: ChoiceGateResult | None = None
        blocked = False
        for result in self.results:
            if result.outcome is ConditionOutcome.UNAVAILABLE:
                blocked = True
                break
            if result.outcome is ConditionOutcome.TRUE:
                first_true = result
                break
        expected = (
            ChoiceDisposition.BLOCKED
            if blocked
            else ChoiceDisposition.SELECTED
            if first_true is not None
            else ChoiceDisposition.FAILED
        )
        if self.disposition is not expected:
            raise ChoiceContractError("CHOICE_DISPOSITION_INVALID")
        expected_branch = None if first_true is None else first_true.branch_id
        if self.selected_branch_id != expected_branch:
            raise ChoiceContractError("CHOICE_SELECTION_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "choice_node_id": self.choice_node_id,
            "source_sequence": self.source_sequence,
            "source_tree_digest": self.source_tree_digest,
            "snapshot_digest": self.snapshot_digest,
            "context_digest": self.context_digest,
            "disposition": self.disposition.value,
            "selected_branch_id": self.selected_branch_id,
            "fallback": None if self.fallback is None else self.fallback.to_payload(),
            "results": [result.to_payload() for result in self.results],
        }

    @property
    def digest(self) -> str:
        return _digest_payload(self.to_payload())


__all__ = [
    "CHOICE_EVIDENCE_VERSION",
    "MAX_CHOICE_BRANCHES",
    "MAX_CHOICE_WORKERS",
    "MIN_CHOICE_BRANCHES",
    "ChoiceBoundaryOutcome",
    "ChoiceContractError",
    "ChoiceDisposition",
    "ChoiceEvent",
    "ChoiceFallbackCause",
    "ChoiceFallbackEvidence",
    "ChoiceGateResult",
    "choice_boundary_allows_fallback",
]
