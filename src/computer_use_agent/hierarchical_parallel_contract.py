"""Content-free H8A evidence for one bounded parallel condition batch.

These immutable values contain only Host identifiers, three-valued H5 results,
and exact digests. They carry no task text, observation value, callable,
provider, Runner, MCP, desktop, approval, retry, replay, or dispatch authority.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256

from .world_state import ConditionOutcome, FactAvailability


PARALLEL_CONDITION_BATCH_VERSION = 1
MIN_PARALLEL_CONDITIONS = 2
MAX_PARALLEL_CONDITIONS = 16
MAX_PARALLEL_WORKERS = 4
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class ParallelConditionContractError(ValueError):
    """Fixed, content-free failure for malformed H8A evidence."""


class ParallelBatchDisposition(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ParallelConditionContractError(f"{field_name} is invalid")
    return value


def _require_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ParallelConditionContractError(f"{field_name} must be a SHA-256 digest")
    return value


def _require_optional_digest(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_digest(value, field_name)


@dataclass(frozen=True)
class ParallelConditionResult:
    """One node-bound H5 result without the inspected fact value."""

    node_id: str
    condition_id: str
    outcome: ConditionOutcome
    availability: FactAvailability
    condition_digest: str
    fact_digest: str | None = None
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.node_id, "node_id")
        _require_identifier(self.condition_id, "condition_id")
        if not isinstance(self.outcome, ConditionOutcome) or not isinstance(
            self.availability, FactAvailability
        ):
            raise ParallelConditionContractError("parallel condition result is invalid")
        _require_digest(self.condition_digest, "condition_digest")
        _require_optional_digest(self.fact_digest, "fact_digest")
        _require_optional_digest(self.evidence_digest, "evidence_digest")
        available = self.availability is FactAvailability.FRESH
        if available is (self.outcome is ConditionOutcome.UNAVAILABLE):
            raise ParallelConditionContractError("parallel condition result is invalid")
        if available != (self.fact_digest is not None and self.evidence_digest is not None):
            raise ParallelConditionContractError("parallel condition result is invalid")

    def to_payload(self) -> dict[str, object]:
        return {
            "node_id": self.node_id,
            "condition_id": self.condition_id,
            "outcome": self.outcome.value,
            "availability": self.availability.value,
            "condition_digest": self.condition_digest,
            "fact_digest": self.fact_digest,
            "evidence_digest": self.evidence_digest,
        }


@dataclass(frozen=True)
class ParallelConditionBatch:
    """One complete, deterministic H8A evaluation bound to its source tree."""

    parallel_node_id: str
    source_sequence: int
    source_tree_digest: str
    snapshot_digest: str
    context_digest: str
    results: tuple[ParallelConditionResult, ...]
    disposition: ParallelBatchDisposition
    version: int = PARALLEL_CONDITION_BATCH_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.parallel_node_id, "parallel_node_id")
        if (
            isinstance(self.source_sequence, bool)
            or not isinstance(self.source_sequence, int)
            or self.source_sequence < 0
        ):
            raise ParallelConditionContractError("source_sequence is invalid")
        _require_digest(self.source_tree_digest, "source_tree_digest")
        _require_digest(self.snapshot_digest, "snapshot_digest")
        _require_digest(self.context_digest, "context_digest")
        if self.version != PARALLEL_CONDITION_BATCH_VERSION or isinstance(
            self.version, bool
        ):
            raise ParallelConditionContractError("parallel batch version is unsupported")
        if not isinstance(self.disposition, ParallelBatchDisposition):
            raise ParallelConditionContractError("parallel batch disposition is invalid")
        if (
            not isinstance(self.results, tuple)
            or not MIN_PARALLEL_CONDITIONS
            <= len(self.results)
            <= MAX_PARALLEL_CONDITIONS
            or not all(isinstance(item, ParallelConditionResult) for item in self.results)
        ):
            raise ParallelConditionContractError("parallel batch results are invalid")
        ordered = tuple(sorted(self.results, key=lambda item: item.node_id))
        if ordered != self.results:
            raise ParallelConditionContractError("parallel batch results are not canonical")
        if len({item.node_id for item in ordered}) != len(ordered) or len(
            {item.condition_id for item in ordered}
        ) != len(ordered):
            raise ParallelConditionContractError("parallel batch results contain duplicates")

        outcomes = tuple(item.outcome for item in ordered)
        expected = (
            ParallelBatchDisposition.FAILED
            if ConditionOutcome.FALSE in outcomes
            else ParallelBatchDisposition.BLOCKED
            if ConditionOutcome.UNAVAILABLE in outcomes
            else ParallelBatchDisposition.COMPLETED
        )
        if self.disposition is not expected:
            raise ParallelConditionContractError("parallel batch disposition is not canonical")

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "parallel_node_id": self.parallel_node_id,
            "source_sequence": self.source_sequence,
            "source_tree_digest": self.source_tree_digest,
            "snapshot_digest": self.snapshot_digest,
            "context_digest": self.context_digest,
            "disposition": self.disposition.value,
            "results": [item.to_payload() for item in self.results],
        }

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self.to_payload(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        return sha256(encoded).hexdigest()


__all__ = [
    "MAX_PARALLEL_CONDITIONS",
    "MAX_PARALLEL_WORKERS",
    "MIN_PARALLEL_CONDITIONS",
    "PARALLEL_CONDITION_BATCH_VERSION",
    "ParallelBatchDisposition",
    "ParallelConditionBatch",
    "ParallelConditionContractError",
    "ParallelConditionResult",
]
