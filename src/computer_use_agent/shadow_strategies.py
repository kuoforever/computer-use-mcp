"""Inert L3 shadow comparison for reviewed L2 procedure evidence.

This module compares one data-only ``ACTIVE`` L2 procedure with one or more
data-only ``SHADOW`` procedures.  It has no provider, Runner, MCP, desktop,
policy, approval, persistence, memory, or runtime-selection port.  A result is
only a reproducible recommendation over frozen evaluation evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from hashlib import sha256
from typing import Mapping, Sequence

from .types import JSONValue
from .verified_procedures import (
    ProcedureDefinition,
    ProcedureEvaluation,
    ProcedureLifecycle,
    ProcedurePin,
    ProcedureReplayCost,
    ProcedureStatus,
    ProcedureStepKind,
    ProcedureTerminal,
)


SHADOW_STRATEGY_POLICY_VERSION = 1
SHADOW_STRATEGY_COMPARISON_VERSION = 1
SHADOW_STRATEGY_DATA_CLASS = "private_shadow_strategy_evaluation"
SHADOW_STRATEGY_USE = "offline_recommendation_only"
MAX_SHADOW_CANDIDATES = 16
MAX_REWARD_WEIGHT = 1_000_000
MAX_REWARD_VALUE = 9_007_199_254_740_991
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_IDENTIFIER = re.compile(
    r"(?i)(password|passcode|api[_-]?key|secret|token|otp|authorization|bearer)"
)
_COST_FIELDS = (
    "model_turns",
    "tool_calls",
    "side_effects",
    "observation_calls",
    "input_tokens",
    "result_bytes",
    "duration_ms",
    "human_approvals",
    "retries",
)


class ShadowStrategyError(ValueError):
    """A fixed content-free L3 validation failure."""


class ShadowRecommendationKind(str, Enum):
    RETAIN_ACTIVE = "retain_active"
    RECOMMEND_SHADOW = "recommend_shadow"


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ShadowStrategyError("SHADOW_STRATEGY_INVALID") from exc


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ShadowStrategyError("SHADOW_DIGEST_INVALID")
    return value


def _require_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or _FORBIDDEN_IDENTIFIER.search(value) is not None
    ):
        if isinstance(value, str) and _FORBIDDEN_IDENTIFIER.search(value) is not None:
            raise ShadowStrategyError("SHADOW_CONTENT_REJECTED")
        raise ShadowStrategyError("SHADOW_IDENTIFIER_INVALID")
    return value


def _require_nonnegative(value: object, *, maximum: int = MAX_REWARD_VALUE) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > maximum
    ):
        raise ShadowStrategyError("SHADOW_INTEGER_INVALID")
    return value


def _require_positive(value: object, *, maximum: int = MAX_REWARD_VALUE) -> int:
    result = _require_nonnegative(value, maximum=maximum)
    if result == 0:
        raise ShadowStrategyError("SHADOW_INTEGER_INVALID")
    return result


def _aware_utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise ShadowStrategyError("SHADOW_TIME_INVALID")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ShadowStrategyError("SHADOW_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowStrategyError("SHADOW_TIME_INVALID") from exc
    return _aware_utc(parsed)


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _strict_mapping(
    value: object,
    fields: frozenset[str],
    *,
    code: str = "SHADOW_POLICY_INVALID",
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != fields:
        raise ShadowStrategyError(code)
    return value


def _pin_key(pin: ProcedurePin) -> tuple[str, int, str]:
    return (pin.procedure_id, pin.procedure_version, pin.definition_digest)


@dataclass(frozen=True)
class ShadowRewardWeights:
    """Visible non-negative weights for every L2 replay cost dimension."""

    model_turns: int
    tool_calls: int
    side_effects: int
    observation_calls: int
    input_tokens: int
    result_bytes: int
    duration_ms: int
    human_approvals: int
    retries: int

    def __post_init__(self) -> None:
        for field_name in _COST_FIELDS:
            _require_nonnegative(
                getattr(self, field_name),
                maximum=MAX_REWARD_WEIGHT,
            )
        if not any(getattr(self, field_name) for field_name in _COST_FIELDS):
            raise ShadowStrategyError("SHADOW_WEIGHTS_EMPTY")

    def to_payload(self) -> dict[str, JSONValue]:
        return {field_name: getattr(self, field_name) for field_name in _COST_FIELDS}

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class ShadowStrategyPolicy:
    """One versioned offline-only scoring policy."""

    policy_id: str
    policy_version: int
    max_candidates: int
    weights: ShadowRewardWeights
    contract_version: int = SHADOW_STRATEGY_POLICY_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.policy_id)
        _require_positive(self.policy_version)
        if (
            not isinstance(self.max_candidates, int)
            or isinstance(self.max_candidates, bool)
            or not 2 <= self.max_candidates <= MAX_SHADOW_CANDIDATES
            or not isinstance(self.weights, ShadowRewardWeights)
            or self.contract_version != SHADOW_STRATEGY_POLICY_VERSION
            or isinstance(self.contract_version, bool)
        ):
            raise ShadowStrategyError("SHADOW_POLICY_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "shadow_strategy_policy_version": self.contract_version,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "max_candidates": self.max_candidates,
            "weights": self.weights.to_payload(),
            "hard_gates": {
                "complete_evaluation": True,
                "full_verified_success": True,
                "zero_safety_escapes": True,
                "zero_authority_regressions": True,
                "equivalent_authority_profile": True,
                "exact_fixture_suite": True,
            },
            "tie_behavior": ShadowRecommendationKind.RETAIN_ACTIVE.value,
            "runtime_selection": False,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def decode_shadow_strategy_policy(value: object) -> ShadowStrategyPolicy:
    """Strictly decode one bounded content-free shadow policy."""

    item = _strict_mapping(
        value,
        frozenset(
            {
                "shadow_strategy_policy_version",
                "policy_id",
                "policy_version",
                "max_candidates",
                "weights",
            }
        ),
    )
    if item["shadow_strategy_policy_version"] != SHADOW_STRATEGY_POLICY_VERSION:
        raise ShadowStrategyError("SHADOW_POLICY_VERSION_INVALID")
    weights = _strict_mapping(item["weights"], frozenset(_COST_FIELDS))
    try:
        return ShadowStrategyPolicy(
            policy_id=item["policy_id"],  # type: ignore[arg-type]
            policy_version=item["policy_version"],  # type: ignore[arg-type]
            max_candidates=item["max_candidates"],  # type: ignore[arg-type]
            weights=ShadowRewardWeights(
                **{field_name: weights[field_name] for field_name in _COST_FIELDS}  # type: ignore[arg-type]
            ),
        )
    except (TypeError, ShadowStrategyError) as exc:
        raise ShadowStrategyError("SHADOW_POLICY_INVALID") from exc


@dataclass(frozen=True)
class ShadowRewardVector:
    """Visible hard outcomes plus the complete L2 replay cost vector."""

    fixture_count: int
    verified_successes: int
    incomplete_results: int
    safety_escapes: int
    authority_regressions: int
    cost: ProcedureReplayCost

    def __post_init__(self) -> None:
        _require_positive(self.fixture_count)
        for value in (
            self.verified_successes,
            self.incomplete_results,
            self.safety_escapes,
            self.authority_regressions,
        ):
            _require_nonnegative(value)
        if (
            self.verified_successes > self.fixture_count
            or self.incomplete_results > self.fixture_count
            or not isinstance(self.cost, ProcedureReplayCost)
        ):
            raise ShadowStrategyError("SHADOW_REWARD_INVALID")

    @classmethod
    def from_evaluation(cls, evaluation: ProcedureEvaluation) -> ShadowRewardVector:
        if not isinstance(evaluation, ProcedureEvaluation):
            raise ShadowStrategyError("SHADOW_EVIDENCE_INVALID")
        return cls(
            fixture_count=len(evaluation.results),
            verified_successes=evaluation.verified_successes,
            incomplete_results=sum(not item.complete for item in evaluation.results),
            safety_escapes=evaluation.safety_escapes,
            authority_regressions=evaluation.authority_regressions,
            cost=evaluation.total_cost,
        )

    @property
    def hard_gates_pass(self) -> bool:
        return (
            self.verified_successes == self.fixture_count
            and self.incomplete_results == 0
            and self.safety_escapes == 0
            and self.authority_regressions == 0
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "fixture_count": self.fixture_count,
            "verified_successes": self.verified_successes,
            "incomplete_results": self.incomplete_results,
            "safety_escapes": self.safety_escapes,
            "authority_regressions": self.authority_regressions,
            "cost": self.cost.to_payload(),
        }


def _equivalence_payload(definition: ProcedureDefinition) -> dict[str, JSONValue]:
    actions: list[JSONValue] = []
    verified_postconditions: list[JSONValue] = []
    for step in definition.steps:
        if step.kind is ProcedureStepKind.ACTION:
            actions.append(
                {
                    "tool_name": step.tool_name,
                    "tool_contract_digest": step.tool_contract_digest,
                    "effect": step.effect.value,
                    "requires_host_approval": step.requires_host_approval,
                    "requires_fresh_observation": step.requires_fresh_observation,
                }
            )
        if (
            step.kind is ProcedureStepKind.VERIFY
            and step.success_target == ProcedureTerminal.VERIFIED_SUCCESS.value
        ):
            assert step.postcondition is not None
            verified_postconditions.append(step.postcondition.to_payload())
    verified_postconditions.sort(key=_canonical)
    return {
        "task_scope": definition.task_scope,
        "application_scope": definition.application_scope,
        "application_version": definition.application_version,
        "registry_digest": definition.registry_digest,
        "policy_digest": definition.policy_digest,
        "preconditions": [item.to_payload() for item in definition.preconditions],
        "ordered_action_authority": actions,
        "verified_postconditions": verified_postconditions,
    }


@dataclass(frozen=True)
class ShadowStrategyEvidence:
    """One audited L2 lifecycle plus one current frozen evaluation."""

    lifecycle: ProcedureLifecycle
    evaluation: ProcedureEvaluation

    def __post_init__(self) -> None:
        if not isinstance(self.lifecycle, ProcedureLifecycle) or not isinstance(
            self.evaluation, ProcedureEvaluation
        ):
            raise ShadowStrategyError("SHADOW_EVIDENCE_INVALID")
        record = self.lifecycle.record
        if (
            record.status not in {ProcedureStatus.ACTIVE, ProcedureStatus.SHADOW}
            or record.activation_gate_digest is None
            or self.evaluation.definition_digest != record.definition.digest
        ):
            raise ShadowStrategyError("SHADOW_EVIDENCE_INVALID")

    @property
    def definition(self) -> ProcedureDefinition:
        return self.lifecycle.record.definition

    @property
    def pin(self) -> ProcedurePin:
        return ProcedurePin(
            procedure_id=self.definition.procedure_id,
            procedure_version=self.definition.procedure_version,
            definition_digest=self.definition.digest,
        )

    @property
    def status(self) -> ProcedureStatus:
        return self.lifecycle.record.status

    @property
    def reward(self) -> ShadowRewardVector:
        return ShadowRewardVector.from_evaluation(self.evaluation)

    @property
    def equivalence_digest(self) -> str:
        return _digest(_equivalence_payload(self.definition))

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "procedure": self.pin.to_payload(),
            "status": self.status.value,
            "record_digest": self.lifecycle.record.digest,
            "lifecycle_tail_digest": self.lifecycle.events[-1].digest,
            "activation_gate_digest": self.lifecycle.record.activation_gate_digest,
            "evaluation_digest": self.evaluation.digest,
            "fixture_suite_digest": self.evaluation.fixture_suite_digest,
            "equivalence_digest": self.equivalence_digest,
            "reward": self.reward.to_payload(),
            "data_class": SHADOW_STRATEGY_DATA_CLASS,
            "use": SHADOW_STRATEGY_USE,
            "capabilities": {
                "authorize": False,
                "dispatch": False,
                "execute": False,
                "route_runtime": False,
                "inject_memory": False,
                "promote_procedure": False,
                "train": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class ShadowStrategyScore:
    """One candidate's visible vector, weighted contributions, and penalty."""

    procedure: ProcedurePin
    status: ProcedureStatus
    evidence_digest: str
    reward: ShadowRewardVector
    weighted_costs: tuple[tuple[str, int], ...]
    weighted_penalty: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.procedure, ProcedurePin)
            or self.status not in {ProcedureStatus.ACTIVE, ProcedureStatus.SHADOW}
            or not isinstance(self.reward, ShadowRewardVector)
        ):
            raise ShadowStrategyError("SHADOW_SCORE_INVALID")
        _require_digest(self.evidence_digest)
        if (
            not isinstance(self.weighted_costs, tuple)
            or tuple(item[0] for item in self.weighted_costs) != _COST_FIELDS
            or not all(
                isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], str)
                and isinstance(item[1], int)
                and not isinstance(item[1], bool)
                and item[1] >= 0
                for item in self.weighted_costs
            )
            or self.weighted_penalty != sum(item[1] for item in self.weighted_costs)
        ):
            raise ShadowStrategyError("SHADOW_SCORE_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "procedure": self.procedure.to_payload(),
            "status": self.status.value,
            "evidence_digest": self.evidence_digest,
            "reward": self.reward.to_payload(),
            "weighted_costs": {
                field_name: value for field_name, value in self.weighted_costs
            },
            "weighted_penalty": self.weighted_penalty,
        }


@dataclass(frozen=True)
class ShadowStrategyComparison:
    """A deterministic offline recommendation with no execution capability."""

    policy: ShadowStrategyPolicy
    evaluated_at: str
    equivalence_digest: str
    fixture_suite_digest: str
    active_baseline: ProcedurePin
    recommendation: ShadowRecommendationKind
    recommended_procedure: ProcedurePin
    strict_improvement: bool
    reason: str
    scores: tuple[ShadowStrategyScore, ...]
    comparison_version: int = SHADOW_STRATEGY_COMPARISON_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.policy, ShadowStrategyPolicy):
            raise ShadowStrategyError("SHADOW_COMPARISON_INVALID")
        _parse_time(self.evaluated_at)
        _require_digest(self.equivalence_digest)
        _require_digest(self.fixture_suite_digest)
        _require_identifier(self.reason)
        if (
            not isinstance(self.active_baseline, ProcedurePin)
            or not isinstance(self.recommended_procedure, ProcedurePin)
            or not isinstance(self.recommendation, ShadowRecommendationKind)
            or type(self.strict_improvement) is not bool
            or not isinstance(self.scores, tuple)
            or not 2 <= len(self.scores) <= self.policy.max_candidates
            or not all(isinstance(item, ShadowStrategyScore) for item in self.scores)
            or tuple(_pin_key(item.procedure) for item in self.scores)
            != tuple(sorted(_pin_key(item.procedure) for item in self.scores))
            or len({_pin_key(item.procedure) for item in self.scores})
            != len(self.scores)
            or self.comparison_version != SHADOW_STRATEGY_COMPARISON_VERSION
            or isinstance(self.comparison_version, bool)
        ):
            raise ShadowStrategyError("SHADOW_COMPARISON_INVALID")
        active = [item for item in self.scores if item.status is ProcedureStatus.ACTIVE]
        pins = {item.procedure for item in self.scores}
        for score in self.scores:
            expected_costs = tuple(
                (
                    field_name,
                    getattr(score.reward.cost, field_name)
                    * getattr(self.policy.weights, field_name),
                )
                for field_name in _COST_FIELDS
            )
            if score.weighted_costs != expected_costs:
                raise ShadowStrategyError("SHADOW_COMPARISON_INVALID")
        if (
            len(active) != 1
            or active[0].procedure != self.active_baseline
            or self.recommended_procedure not in pins
            or any(not item.reward.hard_gates_pass for item in self.scores)
        ):
            raise ShadowStrategyError("SHADOW_COMPARISON_INVALID")
        best_shadow = min(
            (item for item in self.scores if item.status is ProcedureStatus.SHADOW),
            key=lambda item: (item.weighted_penalty, _pin_key(item.procedure)),
        )
        if self.recommendation is ShadowRecommendationKind.RETAIN_ACTIVE:
            valid = (
                not self.strict_improvement
                and self.recommended_procedure == self.active_baseline
                and self.reason == "NO_STRICT_WEIGHTED_IMPROVEMENT"
                and best_shadow.weighted_penalty >= active[0].weighted_penalty
            )
        else:
            valid = (
                self.strict_improvement
                and self.recommended_procedure == best_shadow.procedure
                and self.reason == "LOWER_WEIGHTED_COST"
                and best_shadow.weighted_penalty < active[0].weighted_penalty
            )
        if not valid:
            raise ShadowStrategyError("SHADOW_COMPARISON_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "shadow_strategy_comparison_version": self.comparison_version,
            "policy": self.policy.to_payload(),
            "policy_digest": self.policy.digest,
            "evaluated_at": self.evaluated_at,
            "equivalence_digest": self.equivalence_digest,
            "fixture_suite_digest": self.fixture_suite_digest,
            "active_baseline": self.active_baseline.to_payload(),
            "recommendation": self.recommendation.value,
            "recommended_procedure": self.recommended_procedure.to_payload(),
            "strict_improvement": self.strict_improvement,
            "reason": self.reason,
            "scores": [item.to_payload() for item in self.scores],
            "data_class": SHADOW_STRATEGY_DATA_CLASS,
            "use": SHADOW_STRATEGY_USE,
            "runtime_selection": False,
            "capabilities": {
                "authorize": False,
                "dispatch": False,
                "execute": False,
                "route_runtime": False,
                "inject_memory": False,
                "promote_procedure": False,
                "train": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def _score_evidence(
    evidence: ShadowStrategyEvidence,
    weights: ShadowRewardWeights,
) -> ShadowStrategyScore:
    reward = evidence.reward
    weighted_costs = tuple(
        (
            field_name,
            getattr(reward.cost, field_name) * getattr(weights, field_name),
        )
        for field_name in _COST_FIELDS
    )
    return ShadowStrategyScore(
        procedure=evidence.pin,
        status=evidence.status,
        evidence_digest=evidence.digest,
        reward=reward,
        weighted_costs=weighted_costs,
        weighted_penalty=sum(item[1] for item in weighted_costs),
    )


def compare_shadow_strategies(
    evidence: Sequence[ShadowStrategyEvidence],
    *,
    policy: ShadowStrategyPolicy,
    evaluated_at: datetime,
) -> ShadowStrategyComparison:
    """Compare reviewed L2 evidence and emit one non-executing recommendation."""

    if (
        not isinstance(policy, ShadowStrategyPolicy)
        or isinstance(evidence, (str, bytes))
        or not isinstance(evidence, Sequence)
    ):
        raise ShadowStrategyError("SHADOW_COMPARISON_INPUT_INVALID")
    current = _aware_utc(evaluated_at)
    frozen = tuple(evidence)
    if (
        not 2 <= len(frozen) <= policy.max_candidates
        or not all(isinstance(item, ShadowStrategyEvidence) for item in frozen)
    ):
        raise ShadowStrategyError("SHADOW_COMPARISON_INPUT_INVALID")
    ordered = tuple(sorted(frozen, key=lambda item: _pin_key(item.pin)))
    if len({_pin_key(item.pin) for item in ordered}) != len(ordered):
        raise ShadowStrategyError("SHADOW_PROCEDURE_DUPLICATE")
    active = [item for item in ordered if item.status is ProcedureStatus.ACTIVE]
    if len(active) != 1 or any(
        item.status is not ProcedureStatus.SHADOW
        for item in ordered
        if item is not active[0]
    ):
        raise ShadowStrategyError("SHADOW_BASELINE_INVALID")
    for item in ordered:
        record = item.lifecycle.record
        if (
            current < _parse_time(record.updated_at)
            or current >= _parse_time(record.expires_at)
        ):
            raise ShadowStrategyError("SHADOW_EVIDENCE_EXPIRED")
    equivalence_digests = {item.equivalence_digest for item in ordered}
    fixture_suite_digests = {
        item.evaluation.fixture_suite_digest for item in ordered
    }
    fixture_sequences = {
        tuple(result.fixture_digest for result in item.evaluation.results)
        for item in ordered
    }
    if len(equivalence_digests) != 1:
        raise ShadowStrategyError("SHADOW_AUTHORITY_PROFILE_MISMATCH")
    if len(fixture_suite_digests) != 1 or len(fixture_sequences) != 1:
        raise ShadowStrategyError("SHADOW_FIXTURE_SUITE_MISMATCH")
    if any(not item.reward.hard_gates_pass for item in ordered):
        raise ShadowStrategyError("SHADOW_HARD_GATE_FAILED")
    scores = tuple(_score_evidence(item, policy.weights) for item in ordered)
    active_score = next(
        item for item in scores if item.status is ProcedureStatus.ACTIVE
    )
    shadow_scores = tuple(
        item for item in scores if item.status is ProcedureStatus.SHADOW
    )
    best_shadow = min(
        shadow_scores,
        key=lambda item: (item.weighted_penalty, _pin_key(item.procedure)),
    )
    if best_shadow.weighted_penalty < active_score.weighted_penalty:
        recommendation = ShadowRecommendationKind.RECOMMEND_SHADOW
        recommended = best_shadow.procedure
        strict_improvement = True
        reason = "LOWER_WEIGHTED_COST"
    else:
        recommendation = ShadowRecommendationKind.RETAIN_ACTIVE
        recommended = active_score.procedure
        strict_improvement = False
        reason = "NO_STRICT_WEIGHTED_IMPROVEMENT"
    return ShadowStrategyComparison(
        policy=policy,
        evaluated_at=_iso(current),
        equivalence_digest=next(iter(equivalence_digests)),
        fixture_suite_digest=next(iter(fixture_suite_digests)),
        active_baseline=active_score.procedure,
        recommendation=recommendation,
        recommended_procedure=recommended,
        strict_improvement=strict_improvement,
        reason=reason,
        scores=scores,
    )


__all__ = [
    "MAX_REWARD_WEIGHT",
    "MAX_SHADOW_CANDIDATES",
    "SHADOW_STRATEGY_COMPARISON_VERSION",
    "SHADOW_STRATEGY_DATA_CLASS",
    "SHADOW_STRATEGY_POLICY_VERSION",
    "SHADOW_STRATEGY_USE",
    "ShadowRecommendationKind",
    "ShadowRewardVector",
    "ShadowRewardWeights",
    "ShadowStrategyComparison",
    "ShadowStrategyError",
    "ShadowStrategyEvidence",
    "ShadowStrategyPolicy",
    "ShadowStrategyScore",
    "compare_shadow_strategies",
    "decode_shadow_strategy_policy",
]
