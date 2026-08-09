"""Bounded L4 canary routing over reviewed equivalent procedure evidence.

The router selects only a content-free procedure pin.  It cannot build calls,
carry arguments, authorize work, approve an action, dispatch, retry, replay, or
promote a procedure.  Concrete H7 plans remain Host-compiled and must bind back
to the selected reviewed definition before the existing Runner may open them.
"""
from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence

from .episode_outcome import EpisodeOutcomeLabel
from .hierarchical_side_effects import (
    HierarchicalSideEffectError,
    validate_bounded_side_effect_plan,
)
from .planning import PlanStepAction, TaskPlan
from .run_lock import RunLock
from .shadow_strategies import (
    ShadowRecommendationKind,
    ShadowStrategyComparison,
    ShadowStrategyEvidence,
)
from .tool_registry import reviewed_registry_digest
from .types import ActionRiskTier, JSONValue, ToolEffect
from .verified_procedures import (
    ProcedureDefinition,
    ProcedureFact,
    ProcedureLifecycleAction,
    ProcedurePin,
    ProcedureStatus,
    ProcedureStepKind,
    ProcedureTerminal,
)
from .world_state import FactType


ADAPTIVE_ROUTING_POLICY_VERSION = 1
ADAPTIVE_ROUTING_ROLLOUT_VERSION = 1
ADAPTIVE_ROUTING_DECISION_VERSION = 1
ADAPTIVE_ROUTING_OUTCOME_VERSION = 1
ADAPTIVE_ROUTING_BINDING_VERSION = 1
ADAPTIVE_ROUTING_STORE_VERSION = 1
ADAPTIVE_ROUTING_DATA_CLASS = "private_adaptive_procedure_routing"
ADAPTIVE_ROUTING_USE = "bounded_runtime_selection_only"
MIN_CANARY_INTERVAL = 10
MAX_CANARY_INTERVAL = 1_000
MAX_CANARY_RUNS = 32
MAX_BASELINE_WARMUP_SUCCESSES = 1_000
MAX_ROLLOUT_LIFETIME_DAYS = 30
MAX_ADAPTIVE_ROUTING_STORE_BYTES = 512 * 1024
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_IDENTIFIER = re.compile(
    r"(?i)(password|passcode|api[_-]?key|secret|token|otp|authorization|bearer)"
)


class AdaptiveRoutingError(ValueError):
    """A fixed content-free L4 validation or transition failure."""


class AdaptiveRoutingStoreError(RuntimeError):
    """A fixed failure from the private atomic L4 state store."""


class AdaptiveRolloutStatus(str, Enum):
    WARMUP = "warmup"
    CANARY = "canary"
    COMPLETE = "complete"
    ROLLED_BACK = "rolled_back"


class AdaptiveRouteChoice(str, Enum):
    ACTIVE_BASELINE = "active_baseline"
    CANARY_CANDIDATE = "canary_candidate"
    ROLLBACK_BASELINE = "rollback_baseline"


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise AdaptiveRoutingError("ADAPTIVE_ROUTING_INVALID") from exc


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise AdaptiveRoutingError("ADAPTIVE_DIGEST_INVALID")
    return value


def _require_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or _FORBIDDEN_IDENTIFIER.search(value) is not None
    ):
        if isinstance(value, str) and _FORBIDDEN_IDENTIFIER.search(value) is not None:
            raise AdaptiveRoutingError("ADAPTIVE_CONTENT_REJECTED")
        raise AdaptiveRoutingError("ADAPTIVE_IDENTIFIER_INVALID")
    return value


def _require_nonnegative(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AdaptiveRoutingError("ADAPTIVE_INTEGER_INVALID")
    return value


def _require_positive(value: object) -> int:
    result = _require_nonnegative(value)
    if result == 0:
        raise AdaptiveRoutingError("ADAPTIVE_INTEGER_INVALID")
    return result


def _aware_utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise AdaptiveRoutingError("ADAPTIVE_TIME_INVALID")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise AdaptiveRoutingError("ADAPTIVE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdaptiveRoutingError("ADAPTIVE_TIME_INVALID") from exc
    return _aware_utc(parsed)


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _pin_key(pin: ProcedurePin) -> tuple[str, int, str]:
    return (pin.procedure_id, pin.procedure_version, pin.definition_digest)


def _strict_mapping(
    value: object,
    fields: frozenset[str],
    *,
    code: str = "ADAPTIVE_STORE_INVALID",
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != fields:
        raise AdaptiveRoutingStoreError(code)
    return value


def adaptive_action_call_digest(
    tool_name: str,
    arguments: Mapping[str, JSONValue],
) -> str:
    """Bind one Host risk classification to exact non-retained call arguments."""

    _require_identifier(tool_name)
    if not isinstance(arguments, Mapping):
        raise AdaptiveRoutingError("ADAPTIVE_ACTION_BINDING_INVALID")
    return _digest({"tool_name": tool_name, "arguments": dict(arguments)})


def _action_count(definition: ProcedureDefinition) -> int:
    return sum(step.kind is ProcedureStepKind.ACTION for step in definition.steps)


@dataclass(frozen=True)
class AdaptiveRoutingPolicy:
    """One reviewed rollout policy with a prefix-safe canary fraction."""

    policy_id: str
    policy_version: int
    baseline_warmup_successes: int
    canary_interval: int
    max_canary_runs: int
    contract_version: int = ADAPTIVE_ROUTING_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.policy_id)
        _require_positive(self.policy_version)
        if (
            not isinstance(self.baseline_warmup_successes, int)
            or isinstance(self.baseline_warmup_successes, bool)
            or not 1
            <= self.baseline_warmup_successes
            <= MAX_BASELINE_WARMUP_SUCCESSES
            or not isinstance(self.canary_interval, int)
            or isinstance(self.canary_interval, bool)
            or not MIN_CANARY_INTERVAL
            <= self.canary_interval
            <= MAX_CANARY_INTERVAL
            or not isinstance(self.max_canary_runs, int)
            or isinstance(self.max_canary_runs, bool)
            or not 1 <= self.max_canary_runs <= MAX_CANARY_RUNS
            or self.contract_version != ADAPTIVE_ROUTING_POLICY_VERSION
            or isinstance(self.contract_version, bool)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_POLICY_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "adaptive_routing_policy_version": self.contract_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "baseline_warmup_successes": self.baseline_warmup_successes,
            "canary_interval": self.canary_interval,
            "maximum_canary_fraction": {
                "numerator": 1,
                "denominator": self.canary_interval,
            },
            "max_canary_runs": self.max_canary_runs,
            "candidate_eligibility": {
                "l2_status": ProcedureStatus.SHADOW.value,
                "l3_strict_improvement": True,
                "host_action_risk": ActionRiskTier.LOW.value,
                "exact_context": True,
                "exact_authority_profile": True,
            },
            "rollback": {
                "first_non_success": True,
                "unknown_outcome": True,
                "safety_escape": True,
                "authority_regression": True,
                "approval_gate_change": True,
                "authority_gate_change": True,
                "evidence_drift": True,
                "automatic_candidate_retry": False,
                "automatic_promotion": False,
            },
            "runtime_selection": True,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class AdaptiveRoutingContext:
    """Current Host facts that must match both equivalent definitions."""

    task_scope: str
    application_scope: str
    application_version: str
    task_digest: str
    registry_digest: str
    policy_digest: str
    preconditions: tuple[ProcedureFact, ...]
    action_risks: tuple[ActionRiskTier, ...]
    action_call_digests: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.task_scope,
            self.application_scope,
            self.application_version,
        ):
            _require_identifier(value)
        for value in (self.task_digest, self.registry_digest, self.policy_digest):
            _require_digest(value)
        if self.registry_digest != reviewed_registry_digest():
            raise AdaptiveRoutingError("ADAPTIVE_REGISTRY_DRIFT")
        if (
            not isinstance(self.preconditions, tuple)
            or not self.preconditions
            or not all(isinstance(item, ProcedureFact) for item in self.preconditions)
            or tuple(item.fact_id for item in self.preconditions)
            != tuple(sorted(item.fact_id for item in self.preconditions))
            or len({item.fact_id for item in self.preconditions})
            != len(self.preconditions)
            or not isinstance(self.action_risks, tuple)
            or not self.action_risks
            or not all(isinstance(item, ActionRiskTier) for item in self.action_risks)
            or not isinstance(self.action_call_digests, tuple)
            or len(self.action_call_digests) != len(self.action_risks)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_CONTEXT_INVALID")
        for value in self.action_call_digests:
            _require_digest(value)

    @property
    def low_risk(self) -> bool:
        return all(item is ActionRiskTier.LOW for item in self.action_risks)

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "task_scope": self.task_scope,
            "application_scope": self.application_scope,
            "application_version": self.application_version,
            "task_digest": self.task_digest,
            "registry_digest": self.registry_digest,
            "policy_digest": self.policy_digest,
            "preconditions": [item.to_payload() for item in self.preconditions],
            "action_risks": [item.value for item in self.action_risks],
            "action_call_digests": list(self.action_call_digests),
            "low_risk": self.low_risk,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class AdaptiveRouteDecision:
    """One non-authorizing, sequentially bound runtime procedure selection."""

    rollout_id: str
    decision_sequence: int
    choice: AdaptiveRouteChoice
    selected_procedure: ProcedurePin
    selected_evidence_digest: str
    active_baseline: ProcedurePin
    candidate: ProcedurePin
    context: AdaptiveRoutingContext
    issued_at: str
    reason: str
    decision_version: int = ADAPTIVE_ROUTING_DECISION_VERSION

    def __post_init__(self) -> None:
        _require_digest(self.rollout_id)
        _require_digest(self.selected_evidence_digest)
        _require_positive(self.decision_sequence)
        _parse_time(self.issued_at)
        _require_identifier(self.reason)
        if (
            not isinstance(self.choice, AdaptiveRouteChoice)
            or not isinstance(self.selected_procedure, ProcedurePin)
            or not isinstance(self.active_baseline, ProcedurePin)
            or not isinstance(self.candidate, ProcedurePin)
            or not isinstance(self.context, AdaptiveRoutingContext)
            or self.active_baseline == self.candidate
            or self.decision_version != ADAPTIVE_ROUTING_DECISION_VERSION
            or isinstance(self.decision_version, bool)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_DECISION_INVALID")
        expected = (
            self.candidate
            if self.choice is AdaptiveRouteChoice.CANARY_CANDIDATE
            else self.active_baseline
        )
        if self.selected_procedure != expected:
            raise AdaptiveRoutingError("ADAPTIVE_DECISION_INVALID")
        if self.choice is AdaptiveRouteChoice.CANARY_CANDIDATE and not self.context.low_risk:
            raise AdaptiveRoutingError("ADAPTIVE_LOW_RISK_REQUIRED")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "adaptive_routing_decision_version": self.decision_version,
            "rollout_id": self.rollout_id,
            "decision_sequence": self.decision_sequence,
            "choice": self.choice.value,
            "selected_procedure": self.selected_procedure.to_payload(),
            "selected_evidence_digest": self.selected_evidence_digest,
            "active_baseline": self.active_baseline.to_payload(),
            "candidate": self.candidate.to_payload(),
            "context": self.context.to_payload(),
            "context_digest": self.context.digest,
            "issued_at": self.issued_at,
            "reason": self.reason,
            "data_class": ADAPTIVE_ROUTING_DATA_CLASS,
            "use": ADAPTIVE_ROUTING_USE,
            "runtime_selection": True,
            "capabilities": {
                "authorize": False,
                "approve": False,
                "dispatch": False,
                "execute": False,
                "retry": False,
                "replay": False,
                "inject_memory": False,
                "promote_procedure": False,
                "train": False,
            },
            "required_runtime_gates": {
                "fresh_observation": True,
                "host_policy": True,
                "host_approval": True,
                "grounding": True,
                "write_ahead_log": True,
                "post_action_verification": True,
                "sole_runner_dispatch": True,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class AdaptiveRoutingOutcome:
    """Content-free Host evidence correlated to one route decision."""

    decision_digest: str
    selected_procedure: ProcedurePin
    context_digest: str
    source_episode_digest: str
    terminal: EpisodeOutcomeLabel
    safety_escapes: int
    authority_regressions: int
    approval_gate_unchanged: bool
    authority_gate_unchanged: bool
    known_side_effect_outcome: bool
    verified_postcondition: bool
    outcome_version: int = ADAPTIVE_ROUTING_OUTCOME_VERSION

    def __post_init__(self) -> None:
        for digest_value in (
            self.decision_digest,
            self.context_digest,
            self.source_episode_digest,
        ):
            _require_digest(digest_value)
        for count_value in (self.safety_escapes, self.authority_regressions):
            _require_nonnegative(count_value)
        if (
            not isinstance(self.selected_procedure, ProcedurePin)
            or not isinstance(self.terminal, EpisodeOutcomeLabel)
            or type(self.approval_gate_unchanged) is not bool
            or type(self.authority_gate_unchanged) is not bool
            or type(self.known_side_effect_outcome) is not bool
            or type(self.verified_postcondition) is not bool
            or self.outcome_version != ADAPTIVE_ROUTING_OUTCOME_VERSION
            or isinstance(self.outcome_version, bool)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_OUTCOME_INVALID")

    @property
    def verified_success(self) -> bool:
        return (
            self.terminal is EpisodeOutcomeLabel.VERIFIED_SUCCESS
            and self.safety_escapes == 0
            and self.authority_regressions == 0
            and self.approval_gate_unchanged
            and self.authority_gate_unchanged
            and self.known_side_effect_outcome
            and self.verified_postcondition
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "adaptive_routing_outcome_version": self.outcome_version,
            "decision_digest": self.decision_digest,
            "selected_procedure": self.selected_procedure.to_payload(),
            "context_digest": self.context_digest,
            "source_episode_digest": self.source_episode_digest,
            "terminal": self.terminal.value,
            "safety_escapes": self.safety_escapes,
            "authority_regressions": self.authority_regressions,
            "approval_gate_unchanged": self.approval_gate_unchanged,
            "authority_gate_unchanged": self.authority_gate_unchanged,
            "known_side_effect_outcome": self.known_side_effect_outcome,
            "verified_postcondition": self.verified_postcondition,
            "verified_success": self.verified_success,
            "contains_raw_task": False,
            "contains_model_prose": False,
            "contains_tool_result": False,
            "contains_arguments": False,
            "contains_approval": False,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class AdaptiveRoutingRollout:
    """Immutable CAS-friendly state for one reviewed L3 recommendation."""

    rollout_id: str
    policy: AdaptiveRoutingPolicy
    comparison_digest: str
    equivalence_digest: str
    fixture_suite_digest: str
    active_baseline: ProcedurePin
    candidate: ProcedurePin
    active_evidence_digest: str
    candidate_evidence_digest: str
    created_at: str
    expires_at: str
    status: AdaptiveRolloutStatus
    revision: int
    low_risk_decisions: int
    active_selections: int
    active_successes: int
    candidate_selections: int
    candidate_successes: int
    pending_decision: AdaptiveRouteDecision | None = None
    last_outcome_digest: str | None = None
    rollback_reason: str | None = None
    rollout_version: int = ADAPTIVE_ROUTING_ROLLOUT_VERSION

    def __post_init__(self) -> None:
        for digest_value in (
            self.rollout_id,
            self.comparison_digest,
            self.equivalence_digest,
            self.fixture_suite_digest,
            self.active_evidence_digest,
            self.candidate_evidence_digest,
        ):
            _require_digest(digest_value)
        created = _parse_time(self.created_at)
        expires = _parse_time(self.expires_at)
        for count_value in (
            self.revision,
            self.low_risk_decisions,
            self.active_selections,
            self.active_successes,
            self.candidate_selections,
            self.candidate_successes,
        ):
            _require_nonnegative(count_value)
        if self.last_outcome_digest is not None:
            _require_digest(self.last_outcome_digest)
        if self.rollback_reason is not None:
            _require_identifier(self.rollback_reason)
        total_selections = self.active_selections + self.candidate_selections
        has_pending = self.pending_decision is not None
        completed_decisions = total_selections - int(has_pending)
        if (
            not isinstance(self.policy, AdaptiveRoutingPolicy)
            or not isinstance(self.active_baseline, ProcedurePin)
            or not isinstance(self.candidate, ProcedurePin)
            or self.active_baseline == self.candidate
            or not isinstance(self.status, AdaptiveRolloutStatus)
            or expires <= created
            or expires > created + timedelta(days=MAX_ROLLOUT_LIFETIME_DAYS)
            or self.active_successes > self.active_selections
            or self.candidate_successes > self.candidate_selections
            or self.candidate_selections > self.policy.max_canary_runs
            or self.low_risk_decisions
            > total_selections
            or self.candidate_selections
            > self.low_risk_decisions // self.policy.canary_interval
            or self.revision != 2 * total_selections - int(has_pending)
            or completed_decisions < 0
            or (completed_decisions == 0) != (self.last_outcome_digest is None)
            or self.rollout_version != ADAPTIVE_ROUTING_ROLLOUT_VERSION
            or isinstance(self.rollout_version, bool)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if self.pending_decision is not None:
            if (
                not isinstance(self.pending_decision, AdaptiveRouteDecision)
                or self.pending_decision.rollout_id != self.rollout_id
                or self.pending_decision.decision_sequence
                != total_selections
            ):
                raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if (self.status is AdaptiveRolloutStatus.ROLLED_BACK) != (
            self.rollback_reason is not None
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if self.status is AdaptiveRolloutStatus.COMPLETE and (
            self.candidate_successes != self.policy.max_canary_runs
            or self.pending_decision is not None
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if (
            self.status is not AdaptiveRolloutStatus.COMPLETE
            and self.candidate_successes == self.policy.max_canary_runs
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if self.status is AdaptiveRolloutStatus.WARMUP and (
            self.active_successes >= self.policy.baseline_warmup_successes
            or self.candidate_selections != 0
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if self.status in {AdaptiveRolloutStatus.CANARY, AdaptiveRolloutStatus.COMPLETE} and (
            self.active_successes < self.policy.baseline_warmup_successes
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if (
            self.status is AdaptiveRolloutStatus.ROLLED_BACK
            and self.pending_decision is not None
            and self.pending_decision.choice is not AdaptiveRouteChoice.ROLLBACK_BASELINE
        ):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
        if self.rollout_id != _digest(self._identity_payload()):
            raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_ID_MISMATCH")

    def _identity_payload(self) -> dict[str, JSONValue]:
        return {
            "policy_digest": self.policy.digest,
            "comparison_digest": self.comparison_digest,
            "equivalence_digest": self.equivalence_digest,
            "fixture_suite_digest": self.fixture_suite_digest,
            "active_baseline": self.active_baseline.to_payload(),
            "candidate": self.candidate.to_payload(),
            "active_evidence_digest": self.active_evidence_digest,
            "candidate_evidence_digest": self.candidate_evidence_digest,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "adaptive_routing_rollout_version": self.rollout_version,
            "rollout_id": self.rollout_id,
            "policy": self.policy.to_payload(),
            "policy_digest": self.policy.digest,
            "comparison_digest": self.comparison_digest,
            "equivalence_digest": self.equivalence_digest,
            "fixture_suite_digest": self.fixture_suite_digest,
            "active_baseline": self.active_baseline.to_payload(),
            "candidate": self.candidate.to_payload(),
            "active_evidence_digest": self.active_evidence_digest,
            "candidate_evidence_digest": self.candidate_evidence_digest,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "status": self.status.value,
            "revision": self.revision,
            "low_risk_decisions": self.low_risk_decisions,
            "active_selections": self.active_selections,
            "active_successes": self.active_successes,
            "candidate_selections": self.candidate_selections,
            "candidate_successes": self.candidate_successes,
            "pending_decision": (
                None
                if self.pending_decision is None
                else self.pending_decision.to_payload()
            ),
            "last_outcome_digest": self.last_outcome_digest,
            "rollback_reason": self.rollback_reason,
            "fallback_procedure": self.active_baseline.to_payload(),
            "automatic_candidate_retry": False,
            "automatic_promotion": False,
            "data_class": ADAPTIVE_ROUTING_DATA_CLASS,
            "use": ADAPTIVE_ROUTING_USE,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class AdaptiveRoutingTransition:
    rollout: AdaptiveRoutingRollout
    decision: AdaptiveRouteDecision

    def __post_init__(self) -> None:
        if (
            not isinstance(self.rollout, AdaptiveRoutingRollout)
            or not isinstance(self.decision, AdaptiveRouteDecision)
            or self.rollout.pending_decision != self.decision
        ):
            raise AdaptiveRoutingError("ADAPTIVE_TRANSITION_INVALID")


def _require_current_evidence(
    rollout: AdaptiveRoutingRollout,
    active: ShadowStrategyEvidence,
    candidate: ShadowStrategyEvidence,
    *,
    now: datetime,
) -> str | None:
    if not isinstance(active, ShadowStrategyEvidence) or active.pin != rollout.active_baseline:
        raise AdaptiveRoutingError("ADAPTIVE_ACTIVE_EVIDENCE_DRIFT")
    if active.status is not ProcedureStatus.ACTIVE or active.digest != rollout.active_evidence_digest:
        raise AdaptiveRoutingError("ADAPTIVE_ACTIVE_EVIDENCE_DRIFT")
    active_record = active.lifecycle.record
    if now < _parse_time(active_record.updated_at) or now >= _parse_time(
        active_record.expires_at
    ):
        raise AdaptiveRoutingError("ADAPTIVE_ACTIVE_EVIDENCE_EXPIRED")
    if not isinstance(candidate, ShadowStrategyEvidence):
        return "CANDIDATE_EVIDENCE_DRIFT"
    if (
        candidate.pin != rollout.candidate
        or candidate.status is not ProcedureStatus.SHADOW
        or candidate.digest != rollout.candidate_evidence_digest
        or candidate.equivalence_digest != rollout.equivalence_digest
        or active.equivalence_digest != rollout.equivalence_digest
        or candidate.evaluation.fixture_suite_digest != rollout.fixture_suite_digest
        or active.evaluation.fixture_suite_digest != rollout.fixture_suite_digest
    ):
        return "CANDIDATE_EVIDENCE_DRIFT"
    candidate_record = candidate.lifecycle.record
    if now < _parse_time(candidate_record.updated_at) or now >= _parse_time(
        candidate_record.expires_at
    ):
        return "CANDIDATE_EVIDENCE_EXPIRED"
    if candidate_record.rollback_target != rollout.active_baseline:
        return "CANDIDATE_ROLLBACK_TARGET_DRIFT"
    return None


def _require_context(
    context: AdaptiveRoutingContext,
    active: ProcedureDefinition,
    candidate: ProcedureDefinition,
) -> None:
    if not isinstance(context, AdaptiveRoutingContext):
        raise AdaptiveRoutingError("ADAPTIVE_CONTEXT_INVALID")
    for definition in (active, candidate):
        if (
            context.task_scope != definition.task_scope
            or context.application_scope != definition.application_scope
            or context.application_version != definition.application_version
            or context.registry_digest != definition.registry_digest
            or context.policy_digest != definition.policy_digest
            or context.preconditions != definition.preconditions
            or len(context.action_risks) != _action_count(definition)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_CONTEXT_MISMATCH")


def create_adaptive_rollout(
    comparison: ShadowStrategyComparison,
    evidence: Sequence[ShadowStrategyEvidence],
    *,
    policy: AdaptiveRoutingPolicy,
    now: datetime,
    expires_at: datetime,
) -> AdaptiveRoutingRollout:
    """Create one canary rollout from an exact reviewed L3 recommendation."""

    if (
        not isinstance(comparison, ShadowStrategyComparison)
        or not isinstance(policy, AdaptiveRoutingPolicy)
        or isinstance(evidence, (str, bytes))
        or not isinstance(evidence, Sequence)
        or comparison.recommendation is not ShadowRecommendationKind.RECOMMEND_SHADOW
        or not comparison.strict_improvement
        or comparison.recommended_procedure == comparison.active_baseline
    ):
        raise AdaptiveRoutingError("ADAPTIVE_COMPARISON_INELIGIBLE")
    current = _aware_utc(now)
    expiry = _aware_utc(expires_at)
    if expiry <= current or expiry > current + timedelta(days=MAX_ROLLOUT_LIFETIME_DAYS):
        raise AdaptiveRoutingError("ADAPTIVE_EXPIRY_INVALID")
    indexed = {_pin_key(item.pin): item for item in evidence}
    if len(indexed) != len(tuple(evidence)):
        raise AdaptiveRoutingError("ADAPTIVE_EVIDENCE_DUPLICATE")
    try:
        active = indexed[_pin_key(comparison.active_baseline)]
        candidate = indexed[_pin_key(comparison.recommended_procedure)]
    except KeyError as exc:
        raise AdaptiveRoutingError("ADAPTIVE_EVIDENCE_MISSING") from exc
    scores = {_pin_key(item.procedure): item for item in comparison.scores}
    if active.status is not ProcedureStatus.ACTIVE or candidate.status is not ProcedureStatus.SHADOW:
        raise AdaptiveRoutingError("ADAPTIVE_EVIDENCE_STATUS_INVALID")
    if (
        scores[_pin_key(active.pin)].evidence_digest != active.digest
        or scores[_pin_key(candidate.pin)].evidence_digest != candidate.digest
        or candidate.lifecycle.record.rollback_target != active.pin
        or candidate.lifecycle.events[-1].action
        is not ProcedureLifecycleAction.ENTERED_SHADOW
        or not candidate.lifecycle.events[-1].reviewed
        or active.equivalence_digest != comparison.equivalence_digest
        or candidate.equivalence_digest != comparison.equivalence_digest
        or active.evaluation.fixture_suite_digest != comparison.fixture_suite_digest
        or candidate.evaluation.fixture_suite_digest != comparison.fixture_suite_digest
    ):
        raise AdaptiveRoutingError("ADAPTIVE_EVIDENCE_INVALID")
    if current < _parse_time(comparison.evaluated_at):
        raise AdaptiveRoutingError("ADAPTIVE_TIME_INVALID")
    for item in (active, candidate):
        record = item.lifecycle.record
        if (
            current < _parse_time(record.updated_at)
            or current >= _parse_time(record.expires_at)
            or expiry > _parse_time(record.expires_at)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_EVIDENCE_EXPIRED")
    created_at = _iso(current)
    expires = _iso(expiry)
    identity: dict[str, JSONValue] = {
        "policy_digest": policy.digest,
        "comparison_digest": comparison.digest,
        "equivalence_digest": comparison.equivalence_digest,
        "fixture_suite_digest": comparison.fixture_suite_digest,
        "active_baseline": active.pin.to_payload(),
        "candidate": candidate.pin.to_payload(),
        "active_evidence_digest": active.digest,
        "candidate_evidence_digest": candidate.digest,
        "created_at": created_at,
        "expires_at": expires,
    }
    return AdaptiveRoutingRollout(
        rollout_id=_digest(identity),
        policy=policy,
        comparison_digest=comparison.digest,
        equivalence_digest=comparison.equivalence_digest,
        fixture_suite_digest=comparison.fixture_suite_digest,
        active_baseline=active.pin,
        candidate=candidate.pin,
        active_evidence_digest=active.digest,
        candidate_evidence_digest=candidate.digest,
        created_at=created_at,
        expires_at=expires,
        status=AdaptiveRolloutStatus.WARMUP,
        revision=0,
        low_risk_decisions=0,
        active_selections=0,
        active_successes=0,
        candidate_selections=0,
        candidate_successes=0,
    )


def _issue_decision(
    rollout: AdaptiveRoutingRollout,
    *,
    context: AdaptiveRoutingContext,
    now: datetime,
    choice: AdaptiveRouteChoice,
    reason: str,
    status: AdaptiveRolloutStatus | None = None,
    rollback_reason: str | None = None,
) -> AdaptiveRoutingTransition:
    decision = AdaptiveRouteDecision(
        rollout_id=rollout.rollout_id,
        decision_sequence=rollout.active_selections + rollout.candidate_selections + 1,
        choice=choice,
        selected_procedure=(
            rollout.candidate
            if choice is AdaptiveRouteChoice.CANARY_CANDIDATE
            else rollout.active_baseline
        ),
        selected_evidence_digest=(
            rollout.candidate_evidence_digest
            if choice is AdaptiveRouteChoice.CANARY_CANDIDATE
            else rollout.active_evidence_digest
        ),
        active_baseline=rollout.active_baseline,
        candidate=rollout.candidate,
        context=context,
        issued_at=_iso(now),
        reason=reason,
    )
    candidate_selected = choice is AdaptiveRouteChoice.CANARY_CANDIDATE
    next_rollout = replace(
        rollout,
        status=rollout.status if status is None else status,
        revision=rollout.revision + 1,
        low_risk_decisions=rollout.low_risk_decisions + int(context.low_risk),
        active_selections=rollout.active_selections + int(not candidate_selected),
        candidate_selections=rollout.candidate_selections + int(candidate_selected),
        pending_decision=decision,
        rollback_reason=rollback_reason,
    )
    return AdaptiveRoutingTransition(next_rollout, decision)


def route_adaptive_procedure(
    rollout: AdaptiveRoutingRollout,
    *,
    active_evidence: ShadowStrategyEvidence,
    candidate_evidence: ShadowStrategyEvidence,
    context: AdaptiveRoutingContext,
    expected_revision: int,
    now: datetime,
) -> AdaptiveRoutingTransition:
    """Select one baseline or canary pin without granting execution authority."""

    if not isinstance(rollout, AdaptiveRoutingRollout):
        raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INVALID")
    if not isinstance(active_evidence, ShadowStrategyEvidence) or not isinstance(
        candidate_evidence, ShadowStrategyEvidence
    ):
        raise AdaptiveRoutingError("ADAPTIVE_EVIDENCE_INVALID")
    _require_nonnegative(expected_revision)
    current = _aware_utc(now)
    if rollout.revision != expected_revision:
        raise AdaptiveRoutingError("ADAPTIVE_REVISION_CONFLICT")
    if rollout.pending_decision is not None:
        raise AdaptiveRoutingError("ADAPTIVE_OUTCOME_REQUIRED")
    if rollout.status in {AdaptiveRolloutStatus.COMPLETE, AdaptiveRolloutStatus.ROLLED_BACK}:
        raise AdaptiveRoutingError("ADAPTIVE_ROLLOUT_INACTIVE")
    if current < _parse_time(rollout.created_at):
        raise AdaptiveRoutingError("ADAPTIVE_TIME_INVALID")
    drift = _require_current_evidence(
        rollout,
        active_evidence,
        candidate_evidence,
        now=current,
    )
    _require_context(context, active_evidence.definition, candidate_evidence.definition)
    if current >= _parse_time(rollout.expires_at):
        return _issue_decision(
            rollout,
            context=context,
            now=current,
            choice=AdaptiveRouteChoice.ROLLBACK_BASELINE,
            reason="ROLLOUT_EXPIRED",
            status=AdaptiveRolloutStatus.ROLLED_BACK,
            rollback_reason="ROLLOUT_EXPIRED",
        )
    if drift is not None:
        return _issue_decision(
            rollout,
            context=context,
            now=current,
            choice=AdaptiveRouteChoice.ROLLBACK_BASELINE,
            reason=drift,
            status=AdaptiveRolloutStatus.ROLLED_BACK,
            rollback_reason=drift,
        )
    if not context.low_risk:
        return _issue_decision(
            rollout,
            context=context,
            now=current,
            choice=AdaptiveRouteChoice.ACTIVE_BASELINE,
            reason="NON_LOW_RISK_BASELINE_ONLY",
        )
    if rollout.active_successes < rollout.policy.baseline_warmup_successes:
        return _issue_decision(
            rollout,
            context=context,
            now=current,
            choice=AdaptiveRouteChoice.ACTIVE_BASELINE,
            reason="BASELINE_WARMUP",
        )
    next_low_risk = rollout.low_risk_decisions + 1
    candidate_due = next_low_risk % rollout.policy.canary_interval == 0
    if candidate_due and rollout.candidate_selections < rollout.policy.max_canary_runs:
        return _issue_decision(
            rollout,
            context=context,
            now=current,
            choice=AdaptiveRouteChoice.CANARY_CANDIDATE,
            reason="CANARY_SLOT",
            status=AdaptiveRolloutStatus.CANARY,
        )
    return _issue_decision(
        rollout,
        context=context,
        now=current,
        choice=AdaptiveRouteChoice.ACTIVE_BASELINE,
        reason="CANARY_LIMIT_BASELINE",
        status=AdaptiveRolloutStatus.CANARY,
    )


def record_adaptive_outcome(
    rollout: AdaptiveRoutingRollout,
    outcome: AdaptiveRoutingOutcome,
    *,
    expected_revision: int,
) -> AdaptiveRoutingRollout:
    """Consume one exact outcome; any regression permanently stops the canary."""

    if not isinstance(rollout, AdaptiveRoutingRollout) or not isinstance(
        outcome, AdaptiveRoutingOutcome
    ):
        raise AdaptiveRoutingError("ADAPTIVE_OUTCOME_INVALID")
    _require_nonnegative(expected_revision)
    decision = rollout.pending_decision
    if rollout.revision != expected_revision:
        raise AdaptiveRoutingError("ADAPTIVE_REVISION_CONFLICT")
    if decision is None:
        raise AdaptiveRoutingError("ADAPTIVE_DECISION_REQUIRED")
    if (
        outcome.decision_digest != decision.digest
        or outcome.selected_procedure != decision.selected_procedure
        or outcome.context_digest != decision.context.digest
    ):
        raise AdaptiveRoutingError("ADAPTIVE_OUTCOME_MISMATCH")
    next_status = rollout.status
    rollback_reason = rollout.rollback_reason
    active_successes = rollout.active_successes
    candidate_successes = rollout.candidate_successes
    if not outcome.verified_success:
        next_status = AdaptiveRolloutStatus.ROLLED_BACK
        rollback_reason = (
            "CANDIDATE_OUTCOME_REGRESSION"
            if decision.choice is AdaptiveRouteChoice.CANARY_CANDIDATE
            else "BASELINE_OUTCOME_REGRESSION"
        )
    elif decision.choice is AdaptiveRouteChoice.CANARY_CANDIDATE:
        candidate_successes += 1
        if candidate_successes == rollout.policy.max_canary_runs:
            next_status = AdaptiveRolloutStatus.COMPLETE
    elif decision.context.low_risk:
        active_successes += 1
        if (
            next_status is AdaptiveRolloutStatus.WARMUP
            and active_successes >= rollout.policy.baseline_warmup_successes
        ):
            next_status = AdaptiveRolloutStatus.CANARY
    return replace(
        rollout,
        status=next_status,
        revision=rollout.revision + 1,
        active_successes=active_successes,
        candidate_successes=candidate_successes,
        pending_decision=None,
        last_outcome_digest=outcome.digest,
        rollback_reason=rollback_reason,
    )


@dataclass(frozen=True)
class AdaptiveRoutedPlan:
    """Exact non-secret binding from one L4 decision to one concrete H7 plan."""

    decision: AdaptiveRouteDecision
    procedure: ProcedurePin
    procedure_evidence_digest: str
    plan_digest: str
    ordered_operation_ids: tuple[str, ...]
    ordered_tool_names: tuple[str, ...]
    binding_version: int = ADAPTIVE_ROUTING_BINDING_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.decision, AdaptiveRouteDecision)
            or not isinstance(self.procedure, ProcedurePin)
            or self.procedure != self.decision.selected_procedure
            or not isinstance(self.ordered_operation_ids, tuple)
            or len(self.ordered_operation_ids) != 3
            or not all(isinstance(item, str) for item in self.ordered_operation_ids)
            or not isinstance(self.ordered_tool_names, tuple)
            or len(self.ordered_tool_names) != 3
            or not all(isinstance(item, str) for item in self.ordered_tool_names)
            or self.binding_version != ADAPTIVE_ROUTING_BINDING_VERSION
            or isinstance(self.binding_version, bool)
        ):
            raise AdaptiveRoutingError("ADAPTIVE_PLAN_BINDING_INVALID")
        for value in (self.procedure_evidence_digest, self.plan_digest):
            _require_digest(value)
        for value in (*self.ordered_operation_ids, *self.ordered_tool_names):
            _require_identifier(value)

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "adaptive_routing_binding_version": self.binding_version,
            "decision_digest": self.decision.digest,
            "procedure": self.procedure.to_payload(),
            "procedure_evidence_digest": self.procedure_evidence_digest,
            "plan_digest": self.plan_digest,
            "ordered_operation_ids": list(self.ordered_operation_ids),
            "ordered_tool_names": list(self.ordered_tool_names),
            "contains_arguments": False,
            "contains_raw_task": False,
            "authorize": False,
            "approve": False,
            "dispatch": False,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def bind_adaptive_h7_plan(
    decision: AdaptiveRouteDecision,
    evidence: ShadowStrategyEvidence,
    plan: TaskPlan,
) -> AdaptiveRoutedPlan:
    """Bind the selected logical procedure to one separately compiled H7 plan."""

    if (
        not isinstance(decision, AdaptiveRouteDecision)
        or not isinstance(evidence, ShadowStrategyEvidence)
        or not isinstance(plan, TaskPlan)
        or evidence.pin != decision.selected_procedure
        or evidence.digest != decision.selected_evidence_digest
    ):
        raise AdaptiveRoutingError("ADAPTIVE_PLAN_BINDING_INVALID")
    try:
        validate_bounded_side_effect_plan(plan)
    except HierarchicalSideEffectError as exc:
        raise AdaptiveRoutingError("ADAPTIVE_PLAN_SHAPE_INVALID") from exc
    definition = evidence.definition
    steps = definition.steps
    if (
        len(steps) != 3
        or tuple(item.kind for item in steps)
        != (
            ProcedureStepKind.OBSERVATION,
            ProcedureStepKind.ACTION,
            ProcedureStepKind.VERIFY,
        )
        or steps[0].success_target != steps[1].step_id
        or steps[0].failure_target != ProcedureTerminal.SAFE_STOP.value
        or steps[1].success_target != steps[2].step_id
        or steps[1].failure_target != ProcedureTerminal.SAFE_STOP.value
        or steps[2].success_target != ProcedureTerminal.VERIFIED_SUCCESS.value
        or steps[2].failure_target != ProcedureTerminal.SAFE_STOP.value
        or plan.task_digest != decision.context.task_digest
        or plan.registry_digest != decision.context.registry_digest
    ):
        raise AdaptiveRoutingError("ADAPTIVE_PLAN_SHAPE_INVALID")
    tool_steps = tuple(
        item for item in plan.steps if item.action is PlanStepAction.TOOL
    )
    procedure_tools = tuple(item.tool_name for item in steps)
    if tuple(item.tool_name for item in tool_steps) != procedure_tools:
        raise AdaptiveRoutingError("ADAPTIVE_PLAN_TOOL_MISMATCH")
    action_steps = tuple(
        item for item in tool_steps if item.effect is ToolEffect.SIDE_EFFECT
    )
    action_call_digests: list[str] = []
    for item in action_steps:
        if item.tool_name is None:
            raise AdaptiveRoutingError("ADAPTIVE_PLAN_ACTION_RISK_MISMATCH")
        action_call_digests.append(
            adaptive_action_call_digest(item.tool_name, item.arguments)
        )
    if tuple(action_call_digests) != decision.context.action_call_digests:
        raise AdaptiveRoutingError("ADAPTIVE_PLAN_ACTION_RISK_MISMATCH")
    return AdaptiveRoutedPlan(
        decision=decision,
        procedure=evidence.pin,
        procedure_evidence_digest=evidence.digest,
        plan_digest=plan.digest,
        ordered_operation_ids=tuple(item.operation_id for item in steps),
        ordered_tool_names=procedure_tools,
    )


def _decode_pin(value: object) -> ProcedurePin:
    item = _strict_mapping(
        value,
        frozenset({"procedure_id", "procedure_version", "definition_digest"}),
    )
    try:
        pin = ProcedurePin(
            procedure_id=item["procedure_id"],  # type: ignore[arg-type]
            procedure_version=item["procedure_version"],  # type: ignore[arg-type]
            definition_digest=item["definition_digest"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID") from exc
    if pin.to_payload() != dict(item):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    return pin


def _decode_policy(value: object) -> AdaptiveRoutingPolicy:
    item = _strict_mapping(
        value,
        frozenset(
            {
                "adaptive_routing_policy_version",
                "policy_id",
                "policy_version",
                "baseline_warmup_successes",
                "canary_interval",
                "maximum_canary_fraction",
                "max_canary_runs",
                "candidate_eligibility",
                "rollback",
                "runtime_selection",
            }
        ),
    )
    try:
        policy = AdaptiveRoutingPolicy(
            policy_id=item["policy_id"],  # type: ignore[arg-type]
            policy_version=item["policy_version"],  # type: ignore[arg-type]
            baseline_warmup_successes=item["baseline_warmup_successes"],  # type: ignore[arg-type]
            canary_interval=item["canary_interval"],  # type: ignore[arg-type]
            max_canary_runs=item["max_canary_runs"],  # type: ignore[arg-type]
            contract_version=item["adaptive_routing_policy_version"],  # type: ignore[arg-type]
        )
    except (TypeError, AdaptiveRoutingError) as exc:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID") from exc
    if policy.to_payload() != dict(item):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    return policy


def _decode_fact(value: object) -> ProcedureFact:
    item = _strict_mapping(value, frozenset({"fact_id", "fact_type", "value"}))
    try:
        fact = ProcedureFact(
            fact_id=item["fact_id"],  # type: ignore[arg-type]
            fact_type=FactType(item["fact_type"]),
            value=item["value"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError) as exc:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID") from exc
    if fact.to_payload() != dict(item):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    return fact


def _decode_context(value: object) -> AdaptiveRoutingContext:
    item = _strict_mapping(
        value,
        frozenset(
            {
                "task_scope",
                "application_scope",
                "application_version",
                "task_digest",
                "registry_digest",
                "policy_digest",
                "preconditions",
                "action_risks",
                "action_call_digests",
                "low_risk",
            }
        ),
    )
    preconditions = item["preconditions"]
    risks = item["action_risks"]
    action_call_digests = item["action_call_digests"]
    if (
        not isinstance(preconditions, list)
        or not isinstance(risks, list)
        or not isinstance(action_call_digests, list)
        or isinstance(preconditions, (str, bytes))
        or isinstance(risks, (str, bytes))
        or isinstance(action_call_digests, (str, bytes))
    ):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    try:
        context = AdaptiveRoutingContext(
            task_scope=item["task_scope"],  # type: ignore[arg-type]
            application_scope=item["application_scope"],  # type: ignore[arg-type]
            application_version=item["application_version"],  # type: ignore[arg-type]
            task_digest=item["task_digest"],  # type: ignore[arg-type]
            registry_digest=item["registry_digest"],  # type: ignore[arg-type]
            policy_digest=item["policy_digest"],  # type: ignore[arg-type]
            preconditions=tuple(_decode_fact(fact) for fact in preconditions),
            action_risks=tuple(ActionRiskTier(risk) for risk in risks),
            action_call_digests=tuple(action_call_digests),  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, AdaptiveRoutingError) as exc:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID") from exc
    if context.to_payload() != dict(item):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    return context


def _decode_decision(value: object) -> AdaptiveRouteDecision:
    item = _strict_mapping(
        value,
        frozenset(
            {
                "adaptive_routing_decision_version",
                "rollout_id",
                "decision_sequence",
                "choice",
                "selected_procedure",
                "selected_evidence_digest",
                "active_baseline",
                "candidate",
                "context",
                "context_digest",
                "issued_at",
                "reason",
                "data_class",
                "use",
                "runtime_selection",
                "capabilities",
                "required_runtime_gates",
            }
        ),
    )
    try:
        decision = AdaptiveRouteDecision(
            rollout_id=item["rollout_id"],  # type: ignore[arg-type]
            decision_sequence=item["decision_sequence"],  # type: ignore[arg-type]
            choice=AdaptiveRouteChoice(item["choice"]),
            selected_procedure=_decode_pin(item["selected_procedure"]),
            selected_evidence_digest=item["selected_evidence_digest"],  # type: ignore[arg-type]
            active_baseline=_decode_pin(item["active_baseline"]),
            candidate=_decode_pin(item["candidate"]),
            context=_decode_context(item["context"]),
            issued_at=item["issued_at"],  # type: ignore[arg-type]
            reason=item["reason"],  # type: ignore[arg-type]
            decision_version=item["adaptive_routing_decision_version"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, AdaptiveRoutingError) as exc:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID") from exc
    if decision.to_payload() != dict(item):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    return decision


def _decode_rollout(value: object) -> AdaptiveRoutingRollout:
    item = _strict_mapping(
        value,
        frozenset(
            {
                "adaptive_routing_rollout_version",
                "rollout_id",
                "policy",
                "policy_digest",
                "comparison_digest",
                "equivalence_digest",
                "fixture_suite_digest",
                "active_baseline",
                "candidate",
                "active_evidence_digest",
                "candidate_evidence_digest",
                "created_at",
                "expires_at",
                "status",
                "revision",
                "low_risk_decisions",
                "active_selections",
                "active_successes",
                "candidate_selections",
                "candidate_successes",
                "pending_decision",
                "last_outcome_digest",
                "rollback_reason",
                "fallback_procedure",
                "automatic_candidate_retry",
                "automatic_promotion",
                "data_class",
                "use",
            }
        ),
    )
    pending_value = item["pending_decision"]
    pending = None if pending_value is None else _decode_decision(pending_value)
    try:
        rollout = AdaptiveRoutingRollout(
            rollout_id=item["rollout_id"],  # type: ignore[arg-type]
            policy=_decode_policy(item["policy"]),
            comparison_digest=item["comparison_digest"],  # type: ignore[arg-type]
            equivalence_digest=item["equivalence_digest"],  # type: ignore[arg-type]
            fixture_suite_digest=item["fixture_suite_digest"],  # type: ignore[arg-type]
            active_baseline=_decode_pin(item["active_baseline"]),
            candidate=_decode_pin(item["candidate"]),
            active_evidence_digest=item["active_evidence_digest"],  # type: ignore[arg-type]
            candidate_evidence_digest=item["candidate_evidence_digest"],  # type: ignore[arg-type]
            created_at=item["created_at"],  # type: ignore[arg-type]
            expires_at=item["expires_at"],  # type: ignore[arg-type]
            status=AdaptiveRolloutStatus(item["status"]),
            revision=item["revision"],  # type: ignore[arg-type]
            low_risk_decisions=item["low_risk_decisions"],  # type: ignore[arg-type]
            active_selections=item["active_selections"],  # type: ignore[arg-type]
            active_successes=item["active_successes"],  # type: ignore[arg-type]
            candidate_selections=item["candidate_selections"],  # type: ignore[arg-type]
            candidate_successes=item["candidate_successes"],  # type: ignore[arg-type]
            pending_decision=pending,
            last_outcome_digest=item["last_outcome_digest"],  # type: ignore[arg-type]
            rollback_reason=item["rollback_reason"],  # type: ignore[arg-type]
            rollout_version=item["adaptive_routing_rollout_version"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, AdaptiveRoutingError) as exc:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID") from exc
    if (
        rollout.to_payload() != dict(item)
        or item["policy_digest"] != rollout.policy.digest
        or item["fallback_procedure"] != rollout.active_baseline.to_payload()
    ):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INVALID")
    return rollout


def _store_envelope(rollout: AdaptiveRoutingRollout) -> dict[str, JSONValue]:
    unsigned: dict[str, JSONValue] = {
        "adaptive_routing_store_version": ADAPTIVE_ROUTING_STORE_VERSION,
        "rollout": rollout.to_payload(),
        "rollout_digest": rollout.digest,
    }
    return {**unsigned, "envelope_digest": _digest(unsigned)}


def _decode_store_envelope(value: object) -> AdaptiveRoutingRollout:
    item = _strict_mapping(
        value,
        frozenset(
            {
                "adaptive_routing_store_version",
                "rollout",
                "rollout_digest",
                "envelope_digest",
            }
        ),
    )
    if item["adaptive_routing_store_version"] != ADAPTIVE_ROUTING_STORE_VERSION:
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_VERSION_UNSUPPORTED")
    rollout = _decode_rollout(item["rollout"])
    unsigned = {key: value for key, value in item.items() if key != "envelope_digest"}
    if (
        item["rollout_digest"] != rollout.digest
        or item["envelope_digest"] != _digest(unsigned)
    ):
        raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_DIGEST_MISMATCH")
    return rollout


def _is_unsafe_path(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return True


def adaptive_routing_lock(state_dir: Path, rollout_id: str) -> RunLock:
    """Return the independent OS lock that serializes one cross-run rollout."""

    if not isinstance(state_dir, Path) or not state_dir.is_absolute():
        raise ValueError("state_dir must be an absolute Path")
    _require_digest(rollout_id)
    return RunLock(state_dir / "adaptive-routing" / rollout_id)


class AdaptiveRoutingStore:
    """Private atomic rollout state with exact CAS and one pending decision."""

    filename = "rollout.json"

    def __init__(self, state_dir: Path, rollout_id: str, lock: RunLock) -> None:
        if not isinstance(state_dir, Path) or not state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        _require_digest(rollout_id)
        expected_lock_dir = state_dir / "adaptive-routing" / rollout_id
        if not isinstance(lock, RunLock) or lock.lock_dir != expected_lock_dir:
            raise ValueError("lock must be the exact adaptive routing lock")
        self.state_dir = state_dir
        self.rollout_id = rollout_id
        self.lock = lock
        self.path = expected_lock_dir / self.filename

    def _require_lock(self) -> None:
        if not self.lock.acquired:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_LOCK_REQUIRED")

    def _require_safe_path(self) -> None:
        routing_dir = self.state_dir / "adaptive-routing"
        if any(
            _is_unsafe_path(path)
            for path in (self.state_dir, routing_dir, self.path.parent, self.path)
        ):
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_UNSAFE_PATH")

    def _read(self) -> AdaptiveRoutingRollout:
        self._require_safe_path()
        try:
            encoded = self.path.read_bytes()
        except OSError as exc:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_READ_FAILED") from exc
        if not encoded or len(encoded) > MAX_ADAPTIVE_ROUTING_STORE_BYTES:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_READ_FAILED")
        try:
            value = json.loads(encoded)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_READ_FAILED") from exc
        rollout = _decode_store_envelope(value)
        if rollout.rollout_id != self.rollout_id:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_ID_MISMATCH")
        return rollout

    def _write(
        self,
        rollout: AdaptiveRoutingRollout,
        *,
        create: bool,
    ) -> AdaptiveRoutingRollout:
        if rollout.rollout_id != self.rollout_id:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_ID_MISMATCH")
        payload = _store_envelope(rollout)
        validated = _decode_store_envelope(payload)
        encoded = _canonical(payload) + b"\n"
        if len(encoded) > MAX_ADAPTIVE_ROUTING_STORE_BYTES:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_TOO_LARGE")
        if create and self.path.exists():
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_ALREADY_EXISTS")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_WRITE_FAILED") from exc
        self._require_safe_path()
        temporary: Path | None = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=".adaptive-routing-",
                suffix=".tmp",
                dir=self.path.parent,
            )
            temporary = Path(raw_path)
            os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
            with os.fdopen(descriptor, "wb") as file:
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            if create and self.path.exists():
                raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_ALREADY_EXISTS")
            os.replace(temporary, self.path)
            temporary = None
            os.chmod(self.path, stat.S_IRUSR | stat.S_IWUSR)
        except AdaptiveRoutingStoreError:
            raise
        except OSError as exc:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_WRITE_FAILED") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass
        return validated

    @staticmethod
    def _require_cas(
        current: AdaptiveRoutingRollout,
        *,
        expected_revision: int,
        expected_digest: str,
    ) -> None:
        _require_nonnegative(expected_revision)
        _require_digest(expected_digest)
        if current.revision != expected_revision or current.digest != expected_digest:
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_REVISION_CONFLICT")

    def create(self, rollout: AdaptiveRoutingRollout) -> AdaptiveRoutingRollout:
        self._require_lock()
        if (
            not isinstance(rollout, AdaptiveRoutingRollout)
            or rollout.revision != 0
            or rollout.pending_decision is not None
        ):
            raise AdaptiveRoutingStoreError("ADAPTIVE_STORE_INITIAL_STATE_INVALID")
        return self._write(rollout, create=True)

    def read(self) -> AdaptiveRoutingRollout:
        self._require_lock()
        return self._read()

    def route(
        self,
        *,
        active_evidence: ShadowStrategyEvidence,
        candidate_evidence: ShadowStrategyEvidence,
        context: AdaptiveRoutingContext,
        expected_revision: int,
        expected_digest: str,
        now: datetime,
    ) -> AdaptiveRoutingTransition:
        self._require_lock()
        current = self._read()
        self._require_cas(
            current,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
        )
        transition = route_adaptive_procedure(
            current,
            active_evidence=active_evidence,
            candidate_evidence=candidate_evidence,
            context=context,
            expected_revision=expected_revision,
            now=now,
        )
        persisted = self._write(transition.rollout, create=False)
        return AdaptiveRoutingTransition(persisted, transition.decision)

    def record_outcome(
        self,
        outcome: AdaptiveRoutingOutcome,
        *,
        expected_revision: int,
        expected_digest: str,
    ) -> AdaptiveRoutingRollout:
        self._require_lock()
        current = self._read()
        self._require_cas(
            current,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
        )
        updated = record_adaptive_outcome(
            current,
            outcome,
            expected_revision=expected_revision,
        )
        return self._write(updated, create=False)


__all__ = [
    "ADAPTIVE_ROUTING_BINDING_VERSION",
    "ADAPTIVE_ROUTING_DATA_CLASS",
    "ADAPTIVE_ROUTING_DECISION_VERSION",
    "ADAPTIVE_ROUTING_OUTCOME_VERSION",
    "ADAPTIVE_ROUTING_POLICY_VERSION",
    "ADAPTIVE_ROUTING_ROLLOUT_VERSION",
    "ADAPTIVE_ROUTING_STORE_VERSION",
    "ADAPTIVE_ROUTING_USE",
    "MAX_ADAPTIVE_ROUTING_STORE_BYTES",
    "MAX_CANARY_RUNS",
    "MIN_CANARY_INTERVAL",
    "AdaptiveRouteChoice",
    "AdaptiveRouteDecision",
    "AdaptiveRoutedPlan",
    "AdaptiveRolloutStatus",
    "AdaptiveRoutingContext",
    "AdaptiveRoutingError",
    "AdaptiveRoutingOutcome",
    "AdaptiveRoutingPolicy",
    "AdaptiveRoutingRollout",
    "AdaptiveRoutingStore",
    "AdaptiveRoutingStoreError",
    "AdaptiveRoutingTransition",
    "adaptive_action_call_digest",
    "adaptive_routing_lock",
    "bind_adaptive_h7_plan",
    "create_adaptive_rollout",
    "record_adaptive_outcome",
    "route_adaptive_procedure",
]
