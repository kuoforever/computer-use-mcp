"""Pure, redaction-safe Decision Card compilation and choice validation.

The module has no provider, approval, desktop, or dispatch port. It accepts
only Host-classified enums, safe identifiers, digests, and bounded timestamps.
A valid choice is advisory state for a future authority boundary; it is never a
``PolicyDecision`` and cannot execute work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from hashlib import sha256
from json import dumps

from .types import ApprovalBinding, JSONValue

MAX_CARD_LIFETIME = timedelta(hours=24)
MAX_EVIDENCE_REFS = 8
MAX_UNKNOWN_FACTS = 8

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class DecisionCardError(ValueError):
    """A fixed Decision Card schema failure without source content."""


class DecisionClass(str, Enum):
    RECOVERY = "recovery"
    EXTERNAL_EFFECT = "external_effect"
    OBJECT_DRIFT = "object_drift"
    HIGH_RISK_TRANSITION = "high_risk_transition"


class ApplicationClass(str, Enum):
    DESKTOP = "desktop"
    BROWSER = "browser"
    DOCUMENT = "document"
    MESSAGING = "messaging"


class IntendedEffect(str, Enum):
    RECOVER_WITHOUT_EXTERNAL_EFFECT = "recover_without_external_effect"
    APPROVE_ONE_EXACT_EFFECT = "approve_one_exact_effect"
    PRESERVE_FOR_HANDOFF = "preserve_for_handoff"
    CANCEL_EFFECT = "cancel_effect"


class RecipientScope(str, Enum):
    NONE = "none"
    INTERNAL = "internal"
    EXTERNAL = "external"


class EvidenceKind(str, Enum):
    CHECKPOINT = "checkpoint"
    OBSERVATION = "observation"
    POLICY = "policy"
    OBJECT_VERSION = "object_version"


class UnknownFact(str, Enum):
    ACTIVE_TARGET = "active_target"
    OBJECT_VERSION = "object_version"
    RECIPIENT_IDENTITY = "recipient_identity"
    COMPLETION_OUTCOME = "completion_outcome"


class DecisionOptionKind(str, Enum):
    REOBSERVE = "reobserve"
    RESUME = "resume"
    APPROVE_EXACT_EFFECT = "approve_exact_effect"
    DEFER = "defer"
    DENY = "deny"
    HUMAN_TAKEOVER = "human_takeover"


class RequiredAuthority(str, Enum):
    READ_ONLY_RECOVERY = "read_only_recovery"
    SEPARATE_EXACT_APPROVAL = "separate_exact_approval"
    OPERATOR = "operator"
    NONE = "none"


class FallbackKind(str, Enum):
    DEFER = "defer"
    DENY = "deny"
    HANDOFF_TO_OPERATOR = "handoff_to_operator"


class EstimateKind(str, Enum):
    UNKNOWN = "unknown"
    CONFIGURED_RANGE = "configured_range"
    MEASURED_RANGE = "measured_range"


class ConfidenceKind(str, Enum):
    UNKNOWN = "unknown"
    UNCALIBRATED = "uncalibrated"


class ConfidenceLabel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SelectionStatus(str, Enum):
    SELECTED = "selected"
    DENIED = "denied"
    DEFERRED = "deferred"
    HANDOFF = "handoff"
    NO_SELECTION = "no_selection"
    INVALID = "invalid"
    EXPIRED = "expired"
    STALE = "stale"


def _safe_id(value: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise DecisionCardError("DECISION_CARD_ID_INVALID")


def _digest(value: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise DecisionCardError("DECISION_CARD_DIGEST_INVALID")


def _aware(value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise DecisionCardError("DECISION_CARD_TIME_INVALID")


DecisionBinding = ApprovalBinding


@dataclass(frozen=True)
class EvidenceReference:
    kind: EvidenceKind
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EvidenceKind):
            raise DecisionCardError("DECISION_CARD_EVIDENCE_INVALID")
        _digest(self.digest)


@dataclass(frozen=True)
class RangeEstimate:
    """A provenance-bearing time or token estimate without false precision."""

    kind: EstimateKind
    minimum: int | None = None
    maximum: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, EstimateKind):
            raise DecisionCardError("DECISION_CARD_ESTIMATE_INVALID")
        values = (self.minimum, self.maximum)
        if self.kind is EstimateKind.UNKNOWN:
            if values != (None, None):
                raise DecisionCardError("DECISION_CARD_ESTIMATE_INVALID")
            return
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise DecisionCardError("DECISION_CARD_ESTIMATE_INVALID")
        assert self.minimum is not None and self.maximum is not None
        if not 0 <= self.minimum <= self.maximum <= 1_000_000:
            raise DecisionCardError("DECISION_CARD_ESTIMATE_INVALID")

    def as_display_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind.value,
            "minimum": self.minimum,
            "maximum": self.maximum,
        }


@dataclass(frozen=True)
class ConfidenceEstimate:
    kind: ConfidenceKind
    label: ConfidenceLabel | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ConfidenceKind):
            raise DecisionCardError("DECISION_CARD_CONFIDENCE_INVALID")
        if self.kind is ConfidenceKind.UNKNOWN and self.label is not None:
            raise DecisionCardError("DECISION_CARD_CONFIDENCE_INVALID")
        if self.kind is ConfidenceKind.UNCALIBRATED and not isinstance(
            self.label, ConfidenceLabel
        ):
            raise DecisionCardError("DECISION_CARD_CONFIDENCE_INVALID")

    def as_display_dict(self) -> dict[str, JSONValue]:
        return {
            "kind": self.kind.value,
            "label": None if self.label is None else self.label.value,
        }


@dataclass(frozen=True)
class DecisionOption:
    option_id: str
    kind: DecisionOptionKind
    title: str
    effect: str
    benefits: tuple[str, ...]
    costs: tuple[str, ...]
    risks: tuple[str, ...]
    reversible: bool
    expected_time_seconds: RangeEstimate
    expected_tokens: RangeEstimate
    confidence: ConfidenceEstimate
    required_authority: RequiredAuthority
    fallback: FallbackKind

    def __post_init__(self) -> None:
        _safe_id(self.option_id)
        if not isinstance(self.kind, DecisionOptionKind):
            raise DecisionCardError("DECISION_CARD_OPTION_INVALID")
        expected = _OPTION_PRESENTATION.get(self.kind)
        actual = (
            self.title,
            self.effect,
            self.benefits,
            self.costs,
            self.risks,
            self.reversible,
            self.expected_time_seconds,
            self.expected_tokens,
            self.confidence,
            self.required_authority,
            self.fallback,
        )
        if self.option_id != f"option_{self.kind.value}" or actual != expected:
            raise DecisionCardError("DECISION_CARD_OPTION_INVALID")

    def as_display_dict(self) -> dict[str, JSONValue]:
        return {
            "option_id": self.option_id,
            "kind": self.kind.value,
            "title": self.title,
            "effect": self.effect,
            "benefits": list(self.benefits),
            "costs": list(self.costs),
            "risks": list(self.risks),
            "reversible": self.reversible,
            "expected_time_seconds": self.expected_time_seconds.as_display_dict(),
            "expected_tokens": self.expected_tokens.as_display_dict(),
            "confidence": self.confidence.as_display_dict(),
            "required_authority": self.required_authority.value,
            "fallback": self.fallback.value,
        }


@dataclass(frozen=True)
class DecisionCardRequest:
    decision_id: str
    binding: DecisionBinding
    expires_at: datetime
    decision_class: DecisionClass
    application: ApplicationClass
    intended_effect: IntendedEffect
    recipient_scope: RecipientScope
    evidence: tuple[EvidenceReference, ...]
    unknown_facts: tuple[UnknownFact, ...]
    option_kinds: tuple[DecisionOptionKind, ...]
    recommended: DecisionOptionKind | None = None

    def __post_init__(self) -> None:
        _safe_id(self.decision_id)
        _aware(self.expires_at)
        if not isinstance(self.binding, DecisionBinding):
            raise DecisionCardError("DECISION_CARD_BINDING_INVALID")
        _safe_id(self.binding.run_id)
        if not all(
            isinstance(value, expected)
            for value, expected in (
                (self.decision_class, DecisionClass),
                (self.application, ApplicationClass),
                (self.intended_effect, IntendedEffect),
                (self.recipient_scope, RecipientScope),
            )
        ):
            raise DecisionCardError("DECISION_CARD_CLASSIFICATION_INVALID")
        if not 1 <= len(self.evidence) <= MAX_EVIDENCE_REFS or not all(
            isinstance(item, EvidenceReference) for item in self.evidence
        ):
            raise DecisionCardError("DECISION_CARD_EVIDENCE_INVALID")
        if len(set(self.evidence)) != len(self.evidence):
            raise DecisionCardError("DECISION_CARD_EVIDENCE_INVALID")
        if not 0 <= len(self.unknown_facts) <= MAX_UNKNOWN_FACTS or not all(
            isinstance(item, UnknownFact) for item in self.unknown_facts
        ):
            raise DecisionCardError("DECISION_CARD_UNKNOWN_FACT_INVALID")
        if len(set(self.unknown_facts)) != len(self.unknown_facts):
            raise DecisionCardError("DECISION_CARD_UNKNOWN_FACT_INVALID")
        if not 2 <= len(self.option_kinds) <= 4 or not all(
            isinstance(item, DecisionOptionKind) for item in self.option_kinds
        ):
            raise DecisionCardError("DECISION_CARD_OPTIONS_INVALID")
        if len(set(self.option_kinds)) != len(self.option_kinds):
            raise DecisionCardError("DECISION_CARD_OPTIONS_INVALID")
        if not set(self.option_kinds) & {
            DecisionOptionKind.DEFER,
            DecisionOptionKind.DENY,
            DecisionOptionKind.HUMAN_TAKEOVER,
        }:
            raise DecisionCardError("DECISION_CARD_SAFE_EXIT_REQUIRED")
        if self.recommended is not None and self.recommended not in self.option_kinds:
            raise DecisionCardError("DECISION_CARD_RECOMMENDATION_INVALID")


@dataclass(frozen=True)
class DecisionCard:
    decision_id: str
    card_digest: str
    binding: DecisionBinding
    expires_at: datetime
    decision_class: DecisionClass
    application: ApplicationClass
    intended_effect: IntendedEffect
    recipient_scope: RecipientScope
    evidence: tuple[EvidenceReference, ...]
    unknown_facts: tuple[UnknownFact, ...]
    options: tuple[DecisionOption, ...]
    recommended_option_id: str | None
    advisory_only: bool = True

    def __post_init__(self) -> None:
        _safe_id(self.decision_id)
        _digest(self.card_digest)
        _aware(self.expires_at)
        if not isinstance(self.binding, DecisionBinding) or not self.advisory_only:
            raise DecisionCardError("DECISION_CARD_INVALID")
        _safe_id(self.binding.run_id)
        if not all(
            isinstance(value, expected)
            for value, expected in (
                (self.decision_class, DecisionClass),
                (self.application, ApplicationClass),
                (self.intended_effect, IntendedEffect),
                (self.recipient_scope, RecipientScope),
            )
        ):
            raise DecisionCardError("DECISION_CARD_CLASSIFICATION_INVALID")
        if not 1 <= len(self.evidence) <= MAX_EVIDENCE_REFS or not all(
            isinstance(item, EvidenceReference) for item in self.evidence
        ):
            raise DecisionCardError("DECISION_CARD_EVIDENCE_INVALID")
        if len(set(self.evidence)) != len(self.evidence):
            raise DecisionCardError("DECISION_CARD_EVIDENCE_INVALID")
        if not 0 <= len(self.unknown_facts) <= MAX_UNKNOWN_FACTS or not all(
            isinstance(item, UnknownFact) for item in self.unknown_facts
        ):
            raise DecisionCardError("DECISION_CARD_UNKNOWN_FACT_INVALID")
        if len(set(self.unknown_facts)) != len(self.unknown_facts):
            raise DecisionCardError("DECISION_CARD_UNKNOWN_FACT_INVALID")
        if not 2 <= len(self.options) <= 4 or not all(
            isinstance(option, DecisionOption) for option in self.options
        ):
            raise DecisionCardError("DECISION_CARD_OPTIONS_INVALID")
        option_ids = tuple(option.option_id for option in self.options)
        option_kinds = tuple(option.kind for option in self.options)
        if len(set(option_ids)) != len(option_ids) or len(set(option_kinds)) != len(
            option_kinds
        ):
            raise DecisionCardError("DECISION_CARD_OPTIONS_INVALID")
        if not set(option_kinds) & {
            DecisionOptionKind.DEFER,
            DecisionOptionKind.DENY,
            DecisionOptionKind.HUMAN_TAKEOVER,
        }:
            raise DecisionCardError("DECISION_CARD_SAFE_EXIT_REQUIRED")
        if self.recommended_option_id is not None and (
            self.recommended_option_id not in option_ids
        ):
            raise DecisionCardError("DECISION_CARD_RECOMMENDATION_INVALID")

    def as_display_dict(self) -> dict[str, JSONValue]:
        return {
            "decision_id": self.decision_id,
            "card_digest": self.card_digest,
            "run_id": self.binding.run_id,
            "state_digest": self.binding.state_digest,
            "object_digest": self.binding.object_digest,
            "expires_at": self.expires_at.isoformat(),
            "decision_class": self.decision_class.value,
            "application": self.application.value,
            "intended_effect": self.intended_effect.value,
            "recipient_scope": self.recipient_scope.value,
            "evidence": [
                {"kind": item.kind.value, "digest": item.digest}
                for item in self.evidence
            ],
            "unknown_facts": [item.value for item in self.unknown_facts],
            "options": [option.as_display_dict() for option in self.options],
            "recommended_option_id": self.recommended_option_id,
            "advisory_only": self.advisory_only,
        }


@dataclass(frozen=True)
class DecisionSelection:
    decision_id: str
    card_digest: str
    option_id: str

    def __post_init__(self) -> None:
        _safe_id(self.decision_id)
        _digest(self.card_digest)
        _safe_id(self.option_id)


@dataclass(frozen=True)
class DecisionSelectionResult:
    status: SelectionStatus
    option_kind: DecisionOptionKind | None = None
    requires_separate_approval: bool = False
    releases_desktop_authority: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.status, SelectionStatus)
            or (
                self.option_kind is not None
                and not isinstance(self.option_kind, DecisionOptionKind)
            )
            or not isinstance(self.requires_separate_approval, bool)
            or not isinstance(self.releases_desktop_authority, bool)
        ):
            raise DecisionCardError("DECISION_CARD_SELECTION_RESULT_INVALID")
        if self.status in {
            SelectionStatus.NO_SELECTION,
            SelectionStatus.INVALID,
            SelectionStatus.EXPIRED,
            SelectionStatus.STALE,
        } and (
            self.option_kind is not None
            or self.requires_separate_approval
            or self.releases_desktop_authority
        ):
            raise DecisionCardError("DECISION_CARD_SELECTION_RESULT_INVALID")
        if self.requires_separate_approval != (
            self.status is SelectionStatus.SELECTED
            and self.option_kind is DecisionOptionKind.APPROVE_EXACT_EFFECT
        ):
            raise DecisionCardError("DECISION_CARD_SELECTION_RESULT_INVALID")
        if self.releases_desktop_authority != (
            self.status is SelectionStatus.HANDOFF
            and self.option_kind is DecisionOptionKind.HUMAN_TAKEOVER
        ):
            raise DecisionCardError("DECISION_CARD_SELECTION_RESULT_INVALID")
        allowed = {
            SelectionStatus.SELECTED: {
                DecisionOptionKind.REOBSERVE,
                DecisionOptionKind.RESUME,
                DecisionOptionKind.APPROVE_EXACT_EFFECT,
            },
            SelectionStatus.DENIED: {DecisionOptionKind.DENY},
            SelectionStatus.DEFERRED: {DecisionOptionKind.DEFER},
            SelectionStatus.HANDOFF: {DecisionOptionKind.HUMAN_TAKEOVER},
        }
        if self.status in allowed and self.option_kind not in allowed[self.status]:
            raise DecisionCardError("DECISION_CARD_SELECTION_RESULT_INVALID")


_OPTION_PRESENTATION: dict[
    DecisionOptionKind,
    tuple[
        str,
        str,
        tuple[str, ...],
        tuple[str, ...],
        tuple[str, ...],
        bool,
        RangeEstimate,
        RangeEstimate,
        ConfidenceEstimate,
        RequiredAuthority,
        FallbackKind,
    ],
] = {
    DecisionOptionKind.RESUME: (
        "Resume with fresh observation",
        "No external effect occurs until the Agent observes and asks again",
        ("returns control to the bounded Agent", "invalidates stale evidence"),
        ("uses additional observation and model capacity",),
        ("the requested action may still need a new approval",),
        True,
        RangeEstimate(EstimateKind.CONFIGURED_RANGE, 5, 30),
        RangeEstimate(EstimateKind.UNKNOWN),
        ConfidenceEstimate(ConfidenceKind.UNCALIBRATED, ConfidenceLabel.MEDIUM),
        RequiredAuthority.OPERATOR,
        FallbackKind.HANDOFF_TO_OPERATOR,
    ),
    DecisionOptionKind.REOBSERVE: (
        "Re-observe before continuing",
        "No external effect occurs during the fresh observation",
        ("refreshes Host evidence", "preserves the bounded workflow"),
        ("uses additional observation and model capacity",),
        ("the application may drift again",),
        True,
        RangeEstimate(EstimateKind.CONFIGURED_RANGE, 15, 45),
        RangeEstimate(EstimateKind.UNKNOWN),
        ConfidenceEstimate(ConfidenceKind.UNCALIBRATED, ConfidenceLabel.MEDIUM),
        RequiredAuthority.READ_ONLY_RECOVERY,
        FallbackKind.HANDOFF_TO_OPERATOR,
    ),
    DecisionOptionKind.APPROVE_EXACT_EFFECT: (
        "Request approval for one exact effect",
        "The exact effect remains blocked until a separate approval succeeds",
        ("may complete the intended bounded effect",),
        ("requires a separate local approval",),
        ("the effect may be externally visible or irreversible",),
        False,
        RangeEstimate(EstimateKind.UNKNOWN),
        RangeEstimate(EstimateKind.UNKNOWN),
        ConfidenceEstimate(ConfidenceKind.UNKNOWN),
        RequiredAuthority.SEPARATE_EXACT_APPROVAL,
        FallbackKind.DENY,
    ),
    DecisionOptionKind.DEFER: (
        "Defer and preserve handoff",
        "No effect occurs and the decision remains for later inspection",
        ("avoids acting on incomplete evidence",),
        ("delays completion",),
        ("the underlying application may continue to change",),
        True,
        RangeEstimate(EstimateKind.UNKNOWN),
        RangeEstimate(EstimateKind.UNKNOWN),
        ConfidenceEstimate(ConfidenceKind.UNKNOWN),
        RequiredAuthority.NONE,
        FallbackKind.HANDOFF_TO_OPERATOR,
    ),
    DecisionOptionKind.DENY: (
        "Deny or cancel the proposed effect",
        "The proposed effect is not authorized",
        ("prevents the proposed external effect",),
        ("the requested task may remain incomplete",),
        ("manual cleanup may still be required",),
        True,
        RangeEstimate(EstimateKind.CONFIGURED_RANGE, 0, 0),
        RangeEstimate(EstimateKind.CONFIGURED_RANGE, 0, 0),
        ConfidenceEstimate(ConfidenceKind.UNKNOWN),
        RequiredAuthority.NONE,
        FallbackKind.DENY,
    ),
    DecisionOptionKind.HUMAN_TAKEOVER: (
        "Hand control to the operator",
        "Agent desktop authority is released before manual work",
        ("keeps the operator in direct control",),
        ("requires manual completion",),
        ("automatic progress stops",),
        True,
        RangeEstimate(EstimateKind.UNKNOWN),
        RangeEstimate(EstimateKind.CONFIGURED_RANGE, 0, 0),
        ConfidenceEstimate(ConfidenceKind.UNKNOWN),
        RequiredAuthority.OPERATOR,
        FallbackKind.HANDOFF_TO_OPERATOR,
    ),
}


def _option(kind: DecisionOptionKind) -> DecisionOption:
    values = _OPTION_PRESENTATION[kind]
    return DecisionOption(f"option_{kind.value}", kind, *values)


def compile_decision_card(request: DecisionCardRequest, *, now: datetime) -> DecisionCard:
    """Compile one immutable card entirely from fixed Host classifications."""

    if not isinstance(request, DecisionCardRequest):
        raise DecisionCardError("DECISION_CARD_REQUEST_INVALID")
    _aware(now)
    lifetime = request.expires_at - now
    if lifetime <= timedelta(0) or lifetime > MAX_CARD_LIFETIME:
        raise DecisionCardError("DECISION_CARD_EXPIRY_INVALID")
    options = tuple(_option(kind) for kind in request.option_kinds)
    recommended_id = (
        None if request.recommended is None else f"option_{request.recommended.value}"
    )
    digest_payload = {
        "decision_id": request.decision_id,
        "binding": request.binding.__dict__,
        "expires_at": request.expires_at.isoformat(),
        "decision_class": request.decision_class.value,
        "application": request.application.value,
        "intended_effect": request.intended_effect.value,
        "recipient_scope": request.recipient_scope.value,
        "evidence": [(item.kind.value, item.digest) for item in request.evidence],
        "unknown_facts": [item.value for item in request.unknown_facts],
        "option_kinds": [item.value for item in request.option_kinds],
        "recommended": None if request.recommended is None else request.recommended.value,
    }
    card_digest = sha256(
        dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DecisionCard(
        decision_id=request.decision_id,
        card_digest=card_digest,
        binding=request.binding,
        expires_at=request.expires_at,
        decision_class=request.decision_class,
        application=request.application,
        intended_effect=request.intended_effect,
        recipient_scope=request.recipient_scope,
        evidence=request.evidence,
        unknown_facts=request.unknown_facts,
        options=options,
        recommended_option_id=recommended_id,
    )


def validate_decision_selection(
    card: DecisionCard,
    selection: DecisionSelection | None,
    *,
    current_binding: DecisionBinding,
    now: datetime,
) -> DecisionSelectionResult:
    """Validate one choice without creating approval or execution authority."""

    if not isinstance(card, DecisionCard) or not isinstance(
        current_binding, DecisionBinding
    ):
        raise DecisionCardError("DECISION_CARD_SELECTION_INPUT_INVALID")
    _aware(now)
    if selection is None:
        return DecisionSelectionResult(SelectionStatus.NO_SELECTION)
    if not isinstance(selection, DecisionSelection):
        return DecisionSelectionResult(SelectionStatus.INVALID)
    if selection.decision_id != card.decision_id or selection.card_digest != card.card_digest:
        return DecisionSelectionResult(SelectionStatus.INVALID)
    if now >= card.expires_at:
        return DecisionSelectionResult(SelectionStatus.EXPIRED)
    if current_binding != card.binding:
        return DecisionSelectionResult(SelectionStatus.STALE)
    option = next(
        (item for item in card.options if item.option_id == selection.option_id), None
    )
    if option is None:
        return DecisionSelectionResult(SelectionStatus.INVALID)
    if option.kind is DecisionOptionKind.DENY:
        return DecisionSelectionResult(SelectionStatus.DENIED, option.kind)
    if option.kind is DecisionOptionKind.DEFER:
        return DecisionSelectionResult(SelectionStatus.DEFERRED, option.kind)
    if option.kind is DecisionOptionKind.HUMAN_TAKEOVER:
        return DecisionSelectionResult(
            SelectionStatus.HANDOFF,
            option.kind,
            releases_desktop_authority=True,
        )
    return DecisionSelectionResult(
        SelectionStatus.SELECTED,
        option.kind,
        requires_separate_approval=(
            option.kind is DecisionOptionKind.APPROVE_EXACT_EFFECT
        ),
    )


__all__ = [
    "ApplicationClass",
    "ConfidenceEstimate",
    "ConfidenceKind",
    "ConfidenceLabel",
    "DecisionBinding",
    "DecisionCard",
    "DecisionCardError",
    "DecisionCardRequest",
    "DecisionClass",
    "DecisionOption",
    "DecisionOptionKind",
    "DecisionSelection",
    "DecisionSelectionResult",
    "EstimateKind",
    "EvidenceKind",
    "EvidenceReference",
    "FallbackKind",
    "IntendedEffect",
    "RangeEstimate",
    "RecipientScope",
    "RequiredAuthority",
    "SelectionStatus",
    "UnknownFact",
    "compile_decision_card",
    "validate_decision_selection",
]
