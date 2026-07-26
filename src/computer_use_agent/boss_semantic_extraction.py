"""Bounded BOSS semantic-result and observation-ladder contracts.

This module is deliberately pure and offline.  It validates one compact result,
chooses the next reviewed observation source only after an explicit incomplete
result, and produces canonical digests without retaining raw page text or image
bytes.  It does not dispatch MCP, invoke a provider, navigate, or mutate a
campaign.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Mapping, Sequence


BOSS_SEMANTIC_SCHEMA_VERSION = "boss_job_semantics_v1"
MAX_BOSS_SEMANTIC_TEXT_CHARS = 160
_ITEM_KEY = re.compile(r"boss:job:[A-Za-z0-9_-]{8,128}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class BossSemanticContractError(ValueError):
    """Raised when untrusted semantic or observation data violates the contract."""


class BossSemanticClassification(str, Enum):
    PREFERRED = "PREFERRED"
    POSSIBLE = "POSSIBLE"
    NOT_PREFERRED = "NOT_PREFERRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class BossSemanticReason(str, Enum):
    ROLE = "ROLE"
    COMPANY = "COMPANY"
    LOCATION = "LOCATION"
    COMPENSATION = "COMPENSATION"
    EXPERIENCE = "EXPERIENCE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class BossObservationSource(str, Enum):
    UIA = "uia"
    DOCUMENT_TEXT = "document_text"
    OCR = "ocr"
    CROPPED_IMAGE = "cropped_image"
    SCREENSHOT = "screenshot"


BOSS_OBSERVATION_LADDER = (
    BossObservationSource.UIA,
    BossObservationSource.DOCUMENT_TEXT,
    BossObservationSource.OCR,
    BossObservationSource.CROPPED_IMAGE,
    BossObservationSource.SCREENSHOT,
)


class BossObservationStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INCOMPLETE = "INCOMPLETE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CHALLENGE_REQUIRED = "CHALLENGE_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SITE_BLOCKED = "SITE_BLOCKED"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"


class BossIncompleteReason(str, Enum):
    STATIC_TEXT_ABSENT = "STATIC_TEXT_ABSENT"
    SEMANTIC_CHANNEL_UNAVAILABLE = "SEMANTIC_CHANNEL_UNAVAILABLE"
    TRUNCATED = "TRUNCATED"
    REQUIRED_FIELDS_MISSING = "REQUIRED_FIELDS_MISSING"
    OCR_QUALITY_INSUFFICIENT = "OCR_QUALITY_INSUFFICIENT"
    LAYOUT_CONTEXT_REQUIRED = "LAYOUT_CONTEXT_REQUIRED"


class BossObservationDecisionState(str, Enum):
    OBSERVE = "OBSERVE"
    EXTRACT = "EXTRACT"
    HANDOFF = "HANDOFF"


_TERMINAL_OBSERVATION_STATUSES = frozenset(
    {
        BossObservationStatus.AUTH_REQUIRED,
        BossObservationStatus.CHALLENGE_REQUIRED,
        BossObservationStatus.RATE_LIMITED,
        BossObservationStatus.SITE_BLOCKED,
        BossObservationStatus.CONTENT_UNAVAILABLE,
    }
)


def _bounded_text(value: object, name: str, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise BossSemanticContractError(f"BOSS_SEMANTIC_{name}_INVALID")
    if (
        not value
        or value != value.strip()
        or len(value) > MAX_BOSS_SEMANTIC_TEXT_CHARS
        or _CONTROL.search(value) is not None
    ):
        raise BossSemanticContractError(f"BOSS_SEMANTIC_{name}_INVALID")
    return value


@dataclass(frozen=True)
class BossSemanticResult:
    """One compact result; raw job descriptions and arbitrary prose are excluded."""

    item_key: str
    company: str
    role: str
    location: str
    compensation: str | None
    experience: str | None
    classification: BossSemanticClassification
    classification_reasons: tuple[BossSemanticReason, ...]
    classification_policy_digest: str
    source: BossObservationSource
    source_digest: str
    schema_version: str = BOSS_SEMANTIC_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != BOSS_SEMANTIC_SCHEMA_VERSION:
            raise BossSemanticContractError("BOSS_SEMANTIC_SCHEMA_VERSION_INVALID")
        if not isinstance(self.item_key, str) or _ITEM_KEY.fullmatch(self.item_key) is None:
            raise BossSemanticContractError("BOSS_SEMANTIC_ITEM_KEY_INVALID")
        for name, required in (
            ("company", True),
            ("role", True),
            ("location", True),
            ("compensation", False),
            ("experience", False),
        ):
            _bounded_text(getattr(self, name), name.upper(), required=required)
        if not isinstance(self.classification, BossSemanticClassification):
            raise BossSemanticContractError("BOSS_SEMANTIC_CLASSIFICATION_INVALID")
        if (
            not isinstance(self.classification_reasons, tuple)
            or not self.classification_reasons
            or len(self.classification_reasons) > 5
            or not all(
                isinstance(reason, BossSemanticReason)
                for reason in self.classification_reasons
            )
            or len(set(self.classification_reasons)) != len(self.classification_reasons)
        ):
            raise BossSemanticContractError("BOSS_SEMANTIC_REASONS_INVALID")
        insufficient = BossSemanticReason.INSUFFICIENT_EVIDENCE
        if self.classification is BossSemanticClassification.INSUFFICIENT_EVIDENCE:
            reasons_valid = self.classification_reasons == (insufficient,)
        else:
            reasons_valid = insufficient not in self.classification_reasons
        if not reasons_valid:
            raise BossSemanticContractError("BOSS_SEMANTIC_REASONS_INVALID")
        if (
            not isinstance(self.classification_policy_digest, str)
            or _DIGEST.fullmatch(self.classification_policy_digest) is None
        ):
            raise BossSemanticContractError(
                "BOSS_SEMANTIC_CLASSIFICATION_POLICY_DIGEST_INVALID"
            )
        if not isinstance(self.source, BossObservationSource):
            raise BossSemanticContractError("BOSS_SEMANTIC_SOURCE_INVALID")
        if (
            not isinstance(self.source_digest, str)
            or _DIGEST.fullmatch(self.source_digest) is None
        ):
            raise BossSemanticContractError("BOSS_SEMANTIC_SOURCE_DIGEST_INVALID")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "classification": self.classification.value,
            "classification_reasons": [
                reason.value for reason in self.classification_reasons
            ],
            "classification_policy_digest": self.classification_policy_digest,
            "company": self.company,
            "compensation": self.compensation,
            "experience": self.experience,
            "item_key": self.item_key,
            "location": self.location,
            "role": self.role,
            "schema_version": self.schema_version,
            "source": self.source.value,
            "source_digest": self.source_digest,
        }

    @property
    def content_digest(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return sha256(encoded).hexdigest()


_RESULT_FIELDS = frozenset(
    {
        "schema_version",
        "item_key",
        "company",
        "role",
        "location",
        "compensation",
        "experience",
        "classification",
        "classification_policy_digest",
        "classification_reasons",
        "source",
        "source_digest",
    }
)


def parse_boss_semantic_result(value: Mapping[str, object]) -> BossSemanticResult:
    """Validate an untrusted exact-shape mapping into the reviewed result type."""

    if not isinstance(value, Mapping) or frozenset(value) != _RESULT_FIELDS:
        raise BossSemanticContractError("BOSS_SEMANTIC_RESULT_SHAPE_INVALID")
    reasons = value["classification_reasons"]
    if not isinstance(reasons, list):
        raise BossSemanticContractError("BOSS_SEMANTIC_REASONS_INVALID")
    try:
        classification = BossSemanticClassification(value["classification"])
        parsed_reasons = tuple(BossSemanticReason(reason) for reason in reasons)
        source = BossObservationSource(value["source"])
    except (TypeError, ValueError) as exc:
        raise BossSemanticContractError("BOSS_SEMANTIC_ENUM_INVALID") from exc
    return BossSemanticResult(
        schema_version=value["schema_version"],  # type: ignore[arg-type]
        item_key=value["item_key"],  # type: ignore[arg-type]
        company=value["company"],  # type: ignore[arg-type]
        role=value["role"],  # type: ignore[arg-type]
        location=value["location"],  # type: ignore[arg-type]
        compensation=value["compensation"],  # type: ignore[arg-type]
        experience=value["experience"],  # type: ignore[arg-type]
        classification=classification,
        classification_reasons=parsed_reasons,
        classification_policy_digest=value["classification_policy_digest"],  # type: ignore[arg-type]
        source=source,
        source_digest=value["source_digest"],  # type: ignore[arg-type]
    )


def boss_semantic_result_schema() -> dict[str, object]:
    """Return a fresh strict JSON schema intended for a future extractor."""

    bounded_required = {"type": "string", "minLength": 1, "maxLength": 160}
    bounded_optional = {
        "anyOf": [
            {"type": "string", "minLength": 1, "maxLength": 160},
            {"type": "null"},
        ]
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_RESULT_FIELDS),
        "properties": {
            "schema_version": {"const": BOSS_SEMANTIC_SCHEMA_VERSION},
            "item_key": {
                "type": "string",
                "pattern": r"^boss:job:[A-Za-z0-9_-]{8,128}$",
            },
            "company": bounded_required,
            "role": bounded_required,
            "location": bounded_required,
            "compensation": bounded_optional,
            "experience": bounded_optional,
            "classification": {
                "type": "string",
                "enum": [item.value for item in BossSemanticClassification],
            },
            "classification_policy_digest": {
                "type": "string",
                "pattern": r"^[0-9a-f]{64}$",
            },
            "classification_reasons": {
                "type": "array",
                "minItems": 1,
                "maxItems": 5,
                "uniqueItems": True,
                "items": {
                    "type": "string",
                    "enum": [item.value for item in BossSemanticReason],
                },
            },
            "source": {
                "type": "string",
                "enum": [item.value for item in BossObservationSource],
            },
            "source_digest": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
        },
    }
    return schema


def boss_semantic_schema_digest() -> str:
    encoded = json.dumps(
        boss_semantic_result_schema(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True)
class BossObservationAttempt:
    source: BossObservationSource
    status: BossObservationStatus
    content_digest: str
    incomplete_reason: BossIncompleteReason | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, BossObservationSource):
            raise BossSemanticContractError("BOSS_OBSERVATION_SOURCE_INVALID")
        if not isinstance(self.status, BossObservationStatus):
            raise BossSemanticContractError("BOSS_OBSERVATION_STATUS_INVALID")
        if (
            not isinstance(self.content_digest, str)
            or _DIGEST.fullmatch(self.content_digest) is None
        ):
            raise BossSemanticContractError("BOSS_OBSERVATION_DIGEST_INVALID")
        if (self.status is BossObservationStatus.INCOMPLETE) != isinstance(
            self.incomplete_reason, BossIncompleteReason
        ):
            raise BossSemanticContractError("BOSS_OBSERVATION_REASON_INVALID")


@dataclass(frozen=True)
class BossObservationDecision:
    state: BossObservationDecisionState
    next_source: BossObservationSource | None
    stop_code: str | None


def decide_next_boss_observation(
    attempts: Sequence[BossObservationAttempt],
) -> BossObservationDecision:
    """Choose one reviewed rung without retries, skips, or implicit widening."""

    if not isinstance(attempts, Sequence) or isinstance(attempts, (str, bytes)):
        raise BossSemanticContractError("BOSS_OBSERVATION_ATTEMPTS_INVALID")
    if len(attempts) > len(BOSS_OBSERVATION_LADDER):
        raise BossSemanticContractError("BOSS_OBSERVATION_ATTEMPTS_INVALID")
    for index, attempt in enumerate(attempts):
        if (
            not isinstance(attempt, BossObservationAttempt)
            or attempt.source is not BOSS_OBSERVATION_LADDER[index]
        ):
            raise BossSemanticContractError("BOSS_OBSERVATION_SEQUENCE_INVALID")
        if index < len(attempts) - 1 and attempt.status is not BossObservationStatus.INCOMPLETE:
            raise BossSemanticContractError("BOSS_OBSERVATION_AFTER_TERMINAL")
    if not attempts:
        return BossObservationDecision(
            BossObservationDecisionState.OBSERVE,
            BOSS_OBSERVATION_LADDER[0],
            None,
        )
    last = attempts[-1]
    if last.status is BossObservationStatus.SUFFICIENT:
        return BossObservationDecision(
            BossObservationDecisionState.EXTRACT,
            None,
            None,
        )
    if last.status in _TERMINAL_OBSERVATION_STATUSES:
        return BossObservationDecision(
            BossObservationDecisionState.HANDOFF,
            None,
            f"BOSS_{last.status.value}",
        )
    if len(attempts) == len(BOSS_OBSERVATION_LADDER):
        return BossObservationDecision(
            BossObservationDecisionState.HANDOFF,
            None,
            "BOSS_OBSERVATION_LADDER_EXHAUSTED",
        )
    return BossObservationDecision(
        BossObservationDecisionState.OBSERVE,
        BOSS_OBSERVATION_LADDER[len(attempts)],
        None,
    )


__all__ = [
    "BOSS_OBSERVATION_LADDER",
    "BOSS_SEMANTIC_SCHEMA_VERSION",
    "MAX_BOSS_SEMANTIC_TEXT_CHARS",
    "BossIncompleteReason",
    "BossObservationAttempt",
    "BossObservationDecision",
    "BossObservationDecisionState",
    "BossObservationSource",
    "BossObservationStatus",
    "BossSemanticClassification",
    "BossSemanticContractError",
    "BossSemanticReason",
    "BossSemanticResult",
    "boss_semantic_result_schema",
    "boss_semantic_schema_digest",
    "decide_next_boss_observation",
    "parse_boss_semantic_result",
]
