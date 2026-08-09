"""Typed, non-authorizing H5 world-state facts and freshness inspection."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import TypeAlias

from .tool_registry import ToolValidationError, get_tool_spec
from .types import CallIdentity, ToolEffect, ToolResult


WORLD_STATE_VERSION = 1
MAX_WORLD_FACTS = 128
MAX_FACT_AGE_MS = 300_000
MAX_FACT_TEXT_CHARS = 4096
MAX_EVIDENCE_TEXT_CHARS = 1_000_000
MAX_UTC_TIMESTAMP_MS = 253_402_300_799_999
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_DIGEST = re.compile(r"[0-9a-f]{64}")


class WorldStateError(RuntimeError):
    """Fixed H5 contract failure without raw fact or observation content."""


class FactType(str, Enum):
    BOOLEAN = "boolean"
    INTEGER = "integer"
    TEXT = "text"
    IDENTIFIER = "identifier"


class FactKnowledge(str, Enum):
    OBSERVED = "observed"
    UNKNOWN = "unknown"


class FactScope(str, Enum):
    RUN = "run"
    WINDOW = "window"


class FactExtractionMethod(str, Enum):
    UI_AUTOMATION = "ui_automation"
    WINDOW_ENUMERATION = "window_enumeration"
    DOCUMENT_TEXT = "document_text"
    OCR = "ocr"
    PIXEL_MEASUREMENT = "pixel_measurement"


class FactAvailability(str, Enum):
    FRESH = "fresh"
    MISSING = "missing"
    UNKNOWN = "unknown"
    TYPE_MISMATCH = "type_mismatch"
    RUN_CHANGED = "run_changed"
    EPOCH_CHANGED = "epoch_changed"
    GENERATION_CHANGED = "generation_changed"
    WINDOW_CHANGED = "window_changed"
    CLOCK_INVALID = "clock_invalid"
    EXPIRED = "expired"


class ConditionOutcome(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNAVAILABLE = "unavailable"


FactValue: TypeAlias = bool | int | str | None


_SOURCE_METHOD = {
    "ui_snapshot": FactExtractionMethod.UI_AUTOMATION,
    "find": FactExtractionMethod.UI_AUTOMATION,
    "list_windows": FactExtractionMethod.WINDOW_ENUMERATION,
    "document_text": FactExtractionMethod.DOCUMENT_TEXT,
    "ocr": FactExtractionMethod.OCR,
    "screenshot": FactExtractionMethod.PIXEL_MEASUREMENT,
    "capture_region": FactExtractionMethod.PIXEL_MEASUREMENT,
}


def _canonical(payload: object) -> bytes:
    try:
        return json.dumps(
            payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise WorldStateError("WORLD_STATE_INVALID") from exc


def _digest(payload: object) -> str:
    return sha256(_canonical(payload)).hexdigest()


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise WorldStateError("WORLD_STATE_IDENTIFIER_INVALID")
    return value


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise WorldStateError("WORLD_STATE_DIGEST_INVALID")
    return value


def _require_nonnegative(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise WorldStateError(code)
    return value


def _require_epoch(value: object) -> int:
    epoch = _require_nonnegative(value, "WORLD_STATE_EPOCH_INVALID")
    if epoch == 0:
        raise WorldStateError("WORLD_STATE_EPOCH_INVALID")
    return epoch


def _require_timestamp(value: object) -> int:
    timestamp = _require_nonnegative(value, "WORLD_STATE_TIME_INVALID")
    if timestamp > MAX_UTC_TIMESTAMP_MS:
        raise WorldStateError("WORLD_STATE_TIME_INVALID")
    return timestamp


def _validate_value(fact_type: FactType, value: FactValue) -> None:
    if fact_type is FactType.BOOLEAN:
        if type(value) is not bool:
            raise WorldStateError("WORLD_STATE_VALUE_INVALID")
        return
    if fact_type is FactType.INTEGER:
        if type(value) is not int or not -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER:
            raise WorldStateError("WORLD_STATE_VALUE_INVALID")
        return
    if fact_type is FactType.TEXT:
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= MAX_FACT_TEXT_CHARS
            or "\x00" in value
        ):
            raise WorldStateError("WORLD_STATE_VALUE_INVALID")
        return
    if fact_type is FactType.IDENTIFIER:
        _require_identifier(value)
        return
    raise WorldStateError("WORLD_STATE_TYPE_INVALID")


@dataclass(frozen=True, repr=False)
class WindowIdentity:
    """Exact window/process identity; no title or UI content is retained."""

    window_id: str
    process_id: int
    process_name: str

    def __post_init__(self) -> None:
        _require_identifier(self.window_id)
        if (
            isinstance(self.process_id, bool)
            or not isinstance(self.process_id, int)
            or self.process_id <= 0
        ):
            raise WorldStateError("WORLD_STATE_WINDOW_INVALID")
        if (
            not isinstance(self.process_name, str)
            or not 1 <= len(self.process_name) <= 260
            or any(character in self.process_name for character in "\x00\r\n")
        ):
            raise WorldStateError("WORLD_STATE_WINDOW_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "window_id": self.window_id,
            "process_id": self.process_id,
            "process_name": self.process_name,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())

    def __repr__(self) -> str:
        return f"WindowIdentity(digest={self.digest!r})"


@dataclass(frozen=True)
class ImageEvidence:
    """Content-free binding for one source image."""

    digest: str
    width: int
    height: int

    def __post_init__(self) -> None:
        _require_digest(self.digest)
        for value in (self.width, self.height):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise WorldStateError("WORLD_STATE_IMAGE_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {"digest": self.digest, "width": self.width, "height": self.height}


@dataclass(frozen=True, repr=False)
class ObservationEvidence:
    """Content-free binding to one successful reviewed observation result."""

    identity: CallIdentity
    source_tool: str
    extraction_method: FactExtractionMethod
    observation_epoch: int
    mcp_generation: int
    captured_at_ms: int
    source_text_digest: str
    source_text_length: int
    source_images: tuple[ImageEvidence, ...] = ()
    window: WindowIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CallIdentity):
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID")
        if not isinstance(self.extraction_method, FactExtractionMethod):
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID")
        expected_method = _SOURCE_METHOD.get(self.source_tool)
        try:
            spec = get_tool_spec(self.source_tool)
        except ToolValidationError as exc:
            raise WorldStateError("WORLD_STATE_SOURCE_INVALID") from exc
        if (
            spec.effect is not ToolEffect.OBSERVATION
            or expected_method is not self.extraction_method
        ):
            raise WorldStateError("WORLD_STATE_SOURCE_INVALID")
        _require_epoch(self.observation_epoch)
        _require_nonnegative(self.mcp_generation, "WORLD_STATE_GENERATION_INVALID")
        _require_timestamp(self.captured_at_ms)
        _require_digest(self.source_text_digest)
        if (
            isinstance(self.source_text_length, bool)
            or not isinstance(self.source_text_length, int)
            or not 0 <= self.source_text_length <= MAX_EVIDENCE_TEXT_CHARS
        ):
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID")
        if not isinstance(self.source_images, tuple) or not all(
            isinstance(item, ImageEvidence) for item in self.source_images
        ):
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID")
        if (
            (self.source_tool == "screenshot" and len(self.source_images) != 1)
            or (self.source_tool == "capture_region" and len(self.source_images) > 1)
            or (
                self.source_tool not in {"screenshot", "capture_region"}
                and self.source_images
            )
        ):
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID")
        if self.window is not None and not isinstance(self.window, WindowIdentity):
            raise WorldStateError("WORLD_STATE_WINDOW_INVALID")

    @classmethod
    def from_tool_result(
        cls,
        result: ToolResult,
        *,
        observation_epoch: int,
        mcp_generation: int,
        captured_at_ms: int,
        window: WindowIdentity | None = None,
    ) -> "ObservationEvidence":
        """Hash one validated result without retaining its text or image bytes."""

        if not isinstance(result, ToolResult) or not result.ok:
            raise WorldStateError("WORLD_STATE_OBSERVATION_REQUIRED")
        method = _SOURCE_METHOD.get(result.tool_name)
        if method is None:
            raise WorldStateError("WORLD_STATE_SOURCE_INVALID")
        try:
            text_digest = sha256(result.sanitized_text.encode("utf-8")).hexdigest()
        except UnicodeError as exc:
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID") from exc
        images = tuple(
            ImageEvidence(
                digest=sha256(image.data).hexdigest(),
                width=image.width,
                height=image.height,
            )
            for image in result.images
        )
        return cls(
            identity=result.identity,
            source_tool=result.tool_name,
            extraction_method=method,
            observation_epoch=observation_epoch,
            mcp_generation=mcp_generation,
            captured_at_ms=captured_at_ms,
            source_text_digest=text_digest,
            source_text_length=len(result.sanitized_text),
            source_images=images,
            window=window,
        )

    def _material(self) -> dict[str, object]:
        return {
            "run_id": self.identity.run_id,
            "turn_id": self.identity.turn_id,
            "call_id": self.identity.call_id,
            "source_tool": self.source_tool,
            "extraction_method": self.extraction_method.value,
            "observation_epoch": self.observation_epoch,
            "mcp_generation": self.mcp_generation,
            "captured_at_ms": self.captured_at_ms,
            "source_text_digest": self.source_text_digest,
            "source_text_length": self.source_text_length,
            "source_images": [item.to_payload() for item in self.source_images],
            "window": None if self.window is None else self.window.to_payload(),
        }

    @property
    def evidence_digest(self) -> str:
        return _digest(self._material())

    def to_payload(self) -> dict[str, object]:
        return {**self._material(), "evidence_digest": self.evidence_digest}

    def __repr__(self) -> str:
        return (
            "ObservationEvidence("
            f"source_tool={self.source_tool!r}, evidence_digest={self.evidence_digest!r})"
        )


@dataclass(frozen=True, repr=False)
class WorldFact:
    """One typed fact; content is data and never execution authority."""

    fact_id: str
    fact_type: FactType
    knowledge: FactKnowledge
    value: FactValue
    evidence: ObservationEvidence
    scope: FactScope
    max_age_ms: int

    def __post_init__(self) -> None:
        _require_identifier(self.fact_id)
        if not isinstance(self.fact_type, FactType):
            raise WorldStateError("WORLD_STATE_TYPE_INVALID")
        if not isinstance(self.knowledge, FactKnowledge):
            raise WorldStateError("WORLD_STATE_KNOWLEDGE_INVALID")
        if not isinstance(self.evidence, ObservationEvidence):
            raise WorldStateError("WORLD_STATE_EVIDENCE_INVALID")
        if not isinstance(self.scope, FactScope):
            raise WorldStateError("WORLD_STATE_SCOPE_INVALID")
        if (
            isinstance(self.max_age_ms, bool)
            or not isinstance(self.max_age_ms, int)
            or not 1 <= self.max_age_ms <= MAX_FACT_AGE_MS
        ):
            raise WorldStateError("WORLD_STATE_FRESHNESS_INVALID")
        if self.scope is FactScope.WINDOW and self.evidence.window is None:
            raise WorldStateError("WORLD_STATE_WINDOW_REQUIRED")
        if self.scope is FactScope.RUN and self.evidence.window is not None:
            raise WorldStateError("WORLD_STATE_WINDOW_UNEXPECTED")
        if self.knowledge is FactKnowledge.UNKNOWN:
            if self.value is not None:
                raise WorldStateError("WORLD_STATE_VALUE_INVALID")
        else:
            _validate_value(self.fact_type, self.value)

    def _material(self) -> dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "fact_type": self.fact_type.value,
            "knowledge": self.knowledge.value,
            "value": self.value,
            "evidence": self.evidence.to_payload(),
            "scope": self.scope.value,
            "max_age_ms": self.max_age_ms,
        }

    @property
    def digest(self) -> str:
        return _digest(self._material())

    def __repr__(self) -> str:
        return (
            "WorldFact("
            f"fact_id={self.fact_id!r}, fact_type={self.fact_type.value!r}, "
            f"knowledge={self.knowledge.value!r}, digest={self.digest!r})"
        )


@dataclass(frozen=True)
class WorldStateContext:
    """Current Host facts against which one fact may be consumed."""

    run_id: str
    observation_epoch: int
    mcp_generation: int
    now_ms: int
    window: WindowIdentity | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.run_id)
        _require_epoch(self.observation_epoch)
        _require_nonnegative(self.mcp_generation, "WORLD_STATE_GENERATION_INVALID")
        _require_timestamp(self.now_ms)
        if self.window is not None and not isinstance(self.window, WindowIdentity):
            raise WorldStateError("WORLD_STATE_WINDOW_INVALID")


@dataclass(frozen=True, repr=False)
class WorldStateSnapshot:
    """Canonical bounded collection of private H5 facts."""

    run_id: str
    facts: tuple[WorldFact, ...]
    version: int = WORLD_STATE_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.run_id)
        if self.version != WORLD_STATE_VERSION or isinstance(self.version, bool):
            raise WorldStateError("WORLD_STATE_VERSION_UNSUPPORTED")
        if (
            not isinstance(self.facts, tuple)
            or len(self.facts) > MAX_WORLD_FACTS
            or not all(isinstance(fact, WorldFact) for fact in self.facts)
        ):
            raise WorldStateError("WORLD_STATE_FACTS_INVALID")
        ordered = tuple(sorted(self.facts, key=lambda fact: fact.fact_id))
        if len({fact.fact_id for fact in ordered}) != len(ordered):
            raise WorldStateError("WORLD_STATE_DUPLICATE_FACT")
        if any(fact.evidence.identity.run_id != self.run_id for fact in ordered):
            raise WorldStateError("WORLD_STATE_RUN_MISMATCH")
        object.__setattr__(self, "facts", ordered)

    def _material(self) -> dict[str, object]:
        return {
            "world_state_version": self.version,
            "run_id": self.run_id,
            "facts": [fact._material() for fact in self.facts],
        }

    @property
    def digest(self) -> str:
        return _digest(self._material())

    def __repr__(self) -> str:
        return (
            "WorldStateSnapshot("
            f"run_id={self.run_id!r}, fact_count={len(self.facts)}, "
            f"digest={self.digest!r})"
        )


@dataclass(frozen=True, repr=False)
class FactInspection:
    """A fail-closed fact read; unavailable reads never expose a value."""

    fact_id: str
    availability: FactAvailability
    fact_type: FactType | None = None
    value: FactValue = None
    fact_digest: str | None = None
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.fact_id)
        if not isinstance(self.availability, FactAvailability):
            raise WorldStateError("WORLD_STATE_INSPECTION_INVALID")
        if self.availability is FactAvailability.FRESH:
            if (
                not isinstance(self.fact_type, FactType)
                or self.value is None
                or self.fact_digest is None
                or self.evidence_digest is None
            ):
                raise WorldStateError("WORLD_STATE_INSPECTION_INVALID")
            _validate_value(self.fact_type, self.value)
            _require_digest(self.fact_digest)
            _require_digest(self.evidence_digest)
        elif any(
            item is not None
            for item in (
                self.fact_type,
                self.value,
                self.fact_digest,
                self.evidence_digest,
            )
        ):
            raise WorldStateError("WORLD_STATE_INSPECTION_INVALID")

    @property
    def available(self) -> bool:
        return self.availability is FactAvailability.FRESH

    def __repr__(self) -> str:
        return (
            "FactInspection("
            f"fact_id={self.fact_id!r}, availability={self.availability.value!r}, "
            f"fact_digest={self.fact_digest!r})"
        )


def inspect_world_fact(
    snapshot: WorldStateSnapshot,
    fact_id: str,
    context: WorldStateContext,
    *,
    required_type: FactType,
) -> FactInspection:
    """Return a value only when every run, epoch, generation, window, and age pin holds."""

    if (
        not isinstance(snapshot, WorldStateSnapshot)
        or not isinstance(context, WorldStateContext)
        or not isinstance(required_type, FactType)
    ):
        raise WorldStateError("WORLD_STATE_INPUT_INVALID")
    _require_identifier(fact_id)
    fact = next((item for item in snapshot.facts if item.fact_id == fact_id), None)
    if fact is None:
        return FactInspection(fact_id, FactAvailability.MISSING)
    if snapshot.run_id != context.run_id:
        return FactInspection(fact_id, FactAvailability.RUN_CHANGED)
    if fact.knowledge is FactKnowledge.UNKNOWN:
        return FactInspection(fact_id, FactAvailability.UNKNOWN)
    if fact.fact_type is not required_type:
        return FactInspection(fact_id, FactAvailability.TYPE_MISMATCH)
    evidence = fact.evidence
    if evidence.observation_epoch != context.observation_epoch:
        return FactInspection(fact_id, FactAvailability.EPOCH_CHANGED)
    if evidence.mcp_generation != context.mcp_generation:
        return FactInspection(fact_id, FactAvailability.GENERATION_CHANGED)
    if fact.scope is FactScope.WINDOW and (
        context.window is None
        or evidence.window is None
        or context.window.digest != evidence.window.digest
    ):
        return FactInspection(fact_id, FactAvailability.WINDOW_CHANGED)
    if context.now_ms < evidence.captured_at_ms:
        return FactInspection(fact_id, FactAvailability.CLOCK_INVALID)
    if context.now_ms - evidence.captured_at_ms > fact.max_age_ms:
        return FactInspection(fact_id, FactAvailability.EXPIRED)
    return FactInspection(
        fact_id=fact.fact_id,
        availability=FactAvailability.FRESH,
        fact_type=fact.fact_type,
        value=fact.value,
        fact_digest=fact.digest,
        evidence_digest=evidence.evidence_digest,
    )


@dataclass(frozen=True, repr=False)
class FactCondition:
    """One typed equality condition; it cannot transition or dispatch a tree."""

    condition_id: str
    fact_id: str
    fact_type: FactType
    expected_value: bool | int | str

    def __post_init__(self) -> None:
        _require_identifier(self.condition_id)
        _require_identifier(self.fact_id)
        if not isinstance(self.fact_type, FactType):
            raise WorldStateError("WORLD_STATE_TYPE_INVALID")
        _validate_value(self.fact_type, self.expected_value)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "condition_id": self.condition_id,
                "fact_id": self.fact_id,
                "fact_type": self.fact_type.value,
                "expected_value": self.expected_value,
            }
        )

    def __repr__(self) -> str:
        return (
            "FactCondition("
            f"condition_id={self.condition_id!r}, fact_id={self.fact_id!r}, "
            f"digest={self.digest!r})"
        )


@dataclass(frozen=True)
class ConditionEvaluation:
    """Three-valued H5 result; unavailable is never treated as false."""

    condition_id: str
    outcome: ConditionOutcome
    availability: FactAvailability
    condition_digest: str
    fact_digest: str | None = None
    evidence_digest: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.condition_id)
        if (
            not isinstance(self.outcome, ConditionOutcome)
            or not isinstance(self.availability, FactAvailability)
        ):
            raise WorldStateError("WORLD_STATE_CONDITION_INVALID")
        _require_digest(self.condition_digest)
        available = self.availability is FactAvailability.FRESH
        if available is (self.outcome is ConditionOutcome.UNAVAILABLE):
            raise WorldStateError("WORLD_STATE_CONDITION_INVALID")
        if available:
            _require_digest(self.fact_digest)
            _require_digest(self.evidence_digest)
        elif self.fact_digest is not None or self.evidence_digest is not None:
            raise WorldStateError("WORLD_STATE_CONDITION_INVALID")


def evaluate_fact_condition(
    snapshot: WorldStateSnapshot,
    condition: FactCondition,
    context: WorldStateContext,
) -> ConditionEvaluation:
    """Evaluate fresh known equality; every invalidation remains unavailable."""

    if not isinstance(condition, FactCondition):
        raise WorldStateError("WORLD_STATE_INPUT_INVALID")
    inspection = inspect_world_fact(
        snapshot,
        condition.fact_id,
        context,
        required_type=condition.fact_type,
    )
    if not inspection.available:
        return ConditionEvaluation(
            condition_id=condition.condition_id,
            outcome=ConditionOutcome.UNAVAILABLE,
            availability=inspection.availability,
            condition_digest=condition.digest,
        )
    return ConditionEvaluation(
        condition_id=condition.condition_id,
        outcome=(
            ConditionOutcome.TRUE
            if inspection.value == condition.expected_value
            else ConditionOutcome.FALSE
        ),
        availability=FactAvailability.FRESH,
        condition_digest=condition.digest,
        fact_digest=inspection.fact_digest,
        evidence_digest=inspection.evidence_digest,
    )


__all__ = [
    "MAX_FACT_AGE_MS",
    "MAX_FACT_TEXT_CHARS",
    "MAX_EVIDENCE_TEXT_CHARS",
    "MAX_WORLD_FACTS",
    "WORLD_STATE_VERSION",
    "ConditionEvaluation",
    "ConditionOutcome",
    "FactAvailability",
    "FactCondition",
    "FactExtractionMethod",
    "FactInspection",
    "FactKnowledge",
    "FactScope",
    "FactType",
    "ImageEvidence",
    "ObservationEvidence",
    "WindowIdentity",
    "WorldFact",
    "WorldStateContext",
    "WorldStateError",
    "WorldStateSnapshot",
    "evaluate_fact_condition",
    "inspect_world_fact",
]
