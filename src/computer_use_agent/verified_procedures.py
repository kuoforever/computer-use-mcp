"""Inert L2 procedure candidates and deterministic isolated replay.

Procedure definitions retain reviewed tool metadata and content-free logical
operations, never executable arguments, refs, window identities, approvals, or
payloads.  Replay consumes frozen data in memory and has no provider, Runner,
MCP, desktop, policy, approval, memory, or candidate-fact port.  ``ACTIVE`` is
an evaluation lifecycle label only; no runtime path reads this module.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
from hashlib import sha256
from typing import Mapping, Sequence

from .tool_registry import ToolValidationError, get_tool_spec, reviewed_registry_digest
from .types import DispatchCertainty, JSONValue, ToolEffect, to_json_value
from .world_state import FactType


PROCEDURE_CONTRACT_VERSION = 1
PROCEDURE_FIXTURE_SUITE_VERSION = 1
PROCEDURE_EVALUATION_VERSION = 1
PROCEDURE_LIFECYCLE_VERSION = 1
PROCEDURE_DATA_CLASS = "private_verified_procedure_candidate"
PROCEDURE_USE = "offline_evaluation_only"
MAX_PROCEDURE_STEPS = 32
MAX_PROCEDURE_PRECONDITIONS = 16
MAX_PROCEDURE_SOURCE_EPISODES = 64
MAX_PROCEDURE_FIXTURES = 128
MAX_FIXTURE_OPERATIONS = 96
MAX_PROCEDURE_LIFETIME_DAYS = 365
MIN_HELD_OUT_FIXTURES = 2
MAX_COST_VALUE = 9_007_199_254_740_991
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_FORBIDDEN_IDENTIFIER = re.compile(
    r"(?i)(password|passcode|api[_-]?key|secret|token|otp|authorization|bearer)"
)


class ProcedureValidationError(ValueError):
    """A fixed content-free L2 validation failure."""


class ProcedureStepKind(str, Enum):
    OBSERVATION = "observation"
    ACTION = "action"
    VERIFY = "verify"


class ProcedureTerminal(str, Enum):
    VERIFIED_SUCCESS = "verified_success"
    SAFE_STOP = "safe_stop"


class ProcedureFixtureSplit(str, Enum):
    SOURCE = "source"
    HELD_OUT = "held_out"


class ProcedureReplayOutcome(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


class ProcedureStatus(str, Enum):
    CANDIDATE = "candidate"
    EVALUATING = "evaluating"
    SHADOW = "shadow"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class ProcedureLifecycleAction(str, Enum):
    CREATED = "created"
    STARTED_EVALUATION = "started_evaluation"
    ENTERED_SHADOW = "entered_shadow"
    ACTIVATED = "activated"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


class ProcedureImprovement(str, Enum):
    NONE = "none"
    VERIFIED_OUTCOME = "verified_outcome"
    PARETO_COST = "pareto_cost"


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ProcedureValidationError("PROCEDURE_INVALID") from exc


def _digest(value: object) -> str:
    return sha256(_canonical(value)).hexdigest()


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ProcedureValidationError("PROCEDURE_DIGEST_INVALID")
    return value


def _require_identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or _IDENTIFIER.fullmatch(value) is None
        or _FORBIDDEN_IDENTIFIER.search(value) is not None
    ):
        if isinstance(value, str) and _FORBIDDEN_IDENTIFIER.search(value) is not None:
            raise ProcedureValidationError("PROCEDURE_CONTENT_REJECTED")
        raise ProcedureValidationError("PROCEDURE_IDENTIFIER_INVALID")
    return value


def _require_positive(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProcedureValidationError("PROCEDURE_INTEGER_INVALID")
    return value


def _require_nonnegative(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        or value > MAX_COST_VALUE
    ):
        raise ProcedureValidationError("PROCEDURE_INTEGER_INVALID")
    return value


def _aware_utc(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise ProcedureValidationError("PROCEDURE_TIME_INVALID")
    return value.astimezone(UTC)


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ProcedureValidationError("PROCEDURE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProcedureValidationError("PROCEDURE_TIME_INVALID") from exc
    return _aware_utc(parsed)


def _iso(value: datetime) -> str:
    return _aware_utc(value).isoformat().replace("+00:00", "Z")


def _validate_fact_value(fact_type: FactType, value: object) -> bool | int:
    if fact_type is FactType.BOOLEAN and type(value) is bool:
        return value
    if (
        fact_type is FactType.INTEGER
        and type(value) is int
        and -MAX_COST_VALUE <= value <= MAX_COST_VALUE
    ):
        return value
    if fact_type in {FactType.TEXT, FactType.IDENTIFIER}:
        raise ProcedureValidationError("PROCEDURE_CONTENT_REJECTED")
    raise ProcedureValidationError("PROCEDURE_FACT_INVALID")


def _tool_contract_digest(tool_name: str) -> str:
    try:
        spec = get_tool_spec(tool_name)
    except ToolValidationError as exc:
        raise ProcedureValidationError("PROCEDURE_TOOL_INVALID") from exc
    return _digest(
        {
            "name": spec.name,
            "input_schema": to_json_value(spec.input_schema),
            "effect": spec.effect.value,
            "grounding": spec.grounding.value,
            "requires_host_approval": spec.requires_host_approval,
            "invalidates_observation": spec.invalidates_observation,
            "sensitive_arguments": list(spec.sensitive_arguments),
            "required_safety_baselines": list(spec.required_safety_baselines),
        }
    )


@dataclass(frozen=True)
class ProcedureFact:
    """One boolean/integer precondition or verified postcondition."""

    fact_id: str
    fact_type: FactType
    value: bool | int

    def __post_init__(self) -> None:
        _require_identifier(self.fact_id)
        if not isinstance(self.fact_type, FactType):
            raise ProcedureValidationError("PROCEDURE_FACT_INVALID")
        _validate_fact_value(self.fact_type, self.value)

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "fact_id": self.fact_id,
            "fact_type": self.fact_type.value,
            "value": self.value,
        }


@dataclass(frozen=True)
class ProcedureStep:
    """One content-free logical operation with reviewed tool metadata."""

    step_id: str
    operation_id: str
    kind: ProcedureStepKind
    tool_name: str
    tool_contract_digest: str
    effect: ToolEffect
    requires_host_approval: bool
    requires_fresh_observation: bool
    success_target: str
    failure_target: str
    postcondition: ProcedureFact | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.step_id)
        _require_identifier(self.operation_id)
        _require_identifier(self.tool_name)
        _require_digest(self.tool_contract_digest)
        if not isinstance(self.kind, ProcedureStepKind) or not isinstance(
            self.effect, ToolEffect
        ):
            raise ProcedureValidationError("PROCEDURE_STEP_INVALID")
        if type(self.requires_host_approval) is not bool or type(
            self.requires_fresh_observation
        ) is not bool:
            raise ProcedureValidationError("PROCEDURE_STEP_INVALID")
        for target in (self.success_target, self.failure_target):
            if target not in {item.value for item in ProcedureTerminal}:
                _require_identifier(target)
        try:
            spec = get_tool_spec(self.tool_name)
        except ToolValidationError as exc:
            raise ProcedureValidationError("PROCEDURE_TOOL_INVALID") from exc
        if (
            self.tool_contract_digest != _tool_contract_digest(self.tool_name)
            or self.effect is not spec.effect
            or self.requires_host_approval is not spec.requires_host_approval
        ):
            raise ProcedureValidationError("PROCEDURE_TOOL_DRIFT")
        if self.kind is ProcedureStepKind.ACTION:
            if (
                self.effect is not ToolEffect.SIDE_EFFECT
                or not self.requires_host_approval
                or not self.requires_fresh_observation
                or self.postcondition is not None
            ):
                raise ProcedureValidationError("PROCEDURE_ACTION_INVALID")
        elif (
            self.effect is not ToolEffect.OBSERVATION
            or self.requires_host_approval
            or self.requires_fresh_observation
        ):
            raise ProcedureValidationError("PROCEDURE_OBSERVATION_INVALID")
        if (self.kind is ProcedureStepKind.VERIFY) != (
            isinstance(self.postcondition, ProcedureFact)
        ):
            raise ProcedureValidationError("PROCEDURE_POSTCONDITION_INVALID")

    @classmethod
    def reviewed(
        cls,
        *,
        step_id: str,
        operation_id: str,
        kind: ProcedureStepKind,
        tool_name: str,
        success_target: str,
        failure_target: str,
        postcondition: ProcedureFact | None = None,
    ) -> ProcedureStep:
        try:
            spec = get_tool_spec(tool_name)
        except ToolValidationError as exc:
            raise ProcedureValidationError("PROCEDURE_TOOL_INVALID") from exc
        return cls(
            step_id=step_id,
            operation_id=operation_id,
            kind=kind,
            tool_name=tool_name,
            tool_contract_digest=_tool_contract_digest(tool_name),
            effect=spec.effect,
            requires_host_approval=spec.requires_host_approval,
            requires_fresh_observation=kind is ProcedureStepKind.ACTION,
            success_target=success_target,
            failure_target=failure_target,
            postcondition=postcondition,
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "step_id": self.step_id,
            "operation_id": self.operation_id,
            "kind": self.kind.value,
            "tool_name": self.tool_name,
            "tool_contract_digest": self.tool_contract_digest,
            "effect": self.effect.value,
            "requires_host_approval": self.requires_host_approval,
            "requires_fresh_observation": self.requires_fresh_observation,
            "success_target": self.success_target,
            "failure_target": self.failure_target,
            "postcondition": (
                None if self.postcondition is None else self.postcondition.to_payload()
            ),
        }


@dataclass(frozen=True)
class ProcedureDefinition:
    """Versioned, bounded, non-executable candidate workflow definition."""

    procedure_id: str
    procedure_version: int
    task_scope: str
    application_scope: str
    application_version: str
    registry_digest: str
    policy_digest: str
    generator_version: int
    source_episode_digests: tuple[str, ...]
    preconditions: tuple[ProcedureFact, ...]
    steps: tuple[ProcedureStep, ...]
    contract_version: int = PROCEDURE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for value in (
            self.procedure_id,
            self.task_scope,
            self.application_scope,
            self.application_version,
        ):
            _require_identifier(value)
        _require_positive(self.procedure_version)
        _require_positive(self.generator_version)
        _require_digest(self.registry_digest)
        _require_digest(self.policy_digest)
        if self.registry_digest != reviewed_registry_digest():
            raise ProcedureValidationError("PROCEDURE_REGISTRY_DRIFT")
        if self.contract_version != PROCEDURE_CONTRACT_VERSION or isinstance(
            self.contract_version, bool
        ):
            raise ProcedureValidationError("PROCEDURE_VERSION_INVALID")
        if (
            not isinstance(self.source_episode_digests, tuple)
            or not 1
            <= len(self.source_episode_digests)
            <= MAX_PROCEDURE_SOURCE_EPISODES
            or len(set(self.source_episode_digests))
            != len(self.source_episode_digests)
        ):
            raise ProcedureValidationError("PROCEDURE_SOURCE_INVALID")
        for value in self.source_episode_digests:
            _require_digest(value)
        if tuple(sorted(self.source_episode_digests)) != self.source_episode_digests:
            raise ProcedureValidationError("PROCEDURE_SOURCE_INVALID")
        if (
            not isinstance(self.preconditions, tuple)
            or not 1 <= len(self.preconditions) <= MAX_PROCEDURE_PRECONDITIONS
            or not all(isinstance(item, ProcedureFact) for item in self.preconditions)
            or tuple(sorted(item.fact_id for item in self.preconditions))
            != tuple(item.fact_id for item in self.preconditions)
            or len({item.fact_id for item in self.preconditions})
            != len(self.preconditions)
        ):
            raise ProcedureValidationError("PROCEDURE_PRECONDITION_INVALID")
        if (
            not isinstance(self.steps, tuple)
            or not 1 <= len(self.steps) <= MAX_PROCEDURE_STEPS
            or not all(isinstance(item, ProcedureStep) for item in self.steps)
        ):
            raise ProcedureValidationError("PROCEDURE_STEP_INVALID")
        expected_ids = tuple(f"step_{index}" for index in range(1, len(self.steps) + 1))
        if tuple(item.step_id for item in self.steps) != expected_ids:
            raise ProcedureValidationError("PROCEDURE_STEP_ORDER_INVALID")
        if len({item.operation_id for item in self.steps}) != len(self.steps):
            raise ProcedureValidationError("PROCEDURE_OPERATION_DUPLICATE")
        by_id = {item.step_id: item for item in self.steps}
        indexes = {item.step_id: index for index, item in enumerate(self.steps)}
        reachable = {self.steps[0].step_id}
        frontier = [self.steps[0].step_id]
        success_reachable = False
        action_count = 0
        while frontier:
            step_id = frontier.pop()
            step = by_id[step_id]
            for target in (step.success_target, step.failure_target):
                if target == ProcedureTerminal.VERIFIED_SUCCESS.value:
                    success_reachable = True
                    if step.kind is not ProcedureStepKind.VERIFY:
                        raise ProcedureValidationError("PROCEDURE_SUCCESS_INVALID")
                    continue
                if target == ProcedureTerminal.SAFE_STOP.value:
                    continue
                if target not in by_id or indexes[target] <= indexes[step_id]:
                    raise ProcedureValidationError("PROCEDURE_GRAPH_INVALID")
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)
        for step in self.steps:
            if step.kind is ProcedureStepKind.ACTION:
                action_count += 1
                if (
                    step.failure_target != ProcedureTerminal.SAFE_STOP.value
                    or step.success_target not in by_id
                    or by_id[step.success_target].kind is not ProcedureStepKind.VERIFY
                ):
                    raise ProcedureValidationError("PROCEDURE_ACTION_PATH_INVALID")
        if reachable != set(by_id) or not success_reachable or action_count == 0:
            raise ProcedureValidationError("PROCEDURE_GRAPH_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "procedure_contract_version": self.contract_version,
            "procedure_id": self.procedure_id,
            "procedure_version": self.procedure_version,
            "task_scope": self.task_scope,
            "application_scope": self.application_scope,
            "application_version": self.application_version,
            "registry_digest": self.registry_digest,
            "policy_digest": self.policy_digest,
            "generator_version": self.generator_version,
            "source_episode_digests": list(self.source_episode_digests),
            "preconditions": [item.to_payload() for item in self.preconditions],
            "steps": [item.to_payload() for item in self.steps],
            "privacy": {
                "contains_raw_task": False,
                "contains_model_prose": False,
                "contains_raw_tool_result": False,
                "contains_observation_text": False,
                "contains_arguments": False,
                "contains_ref": False,
                "contains_window_identity": False,
                "contains_approval": False,
                "contains_payload": False,
                "contains_secret": False,
            },
            "capabilities": {
                "authorize": False,
                "dispatch": False,
                "execute": False,
                "inject_memory": False,
                "select_strategy": False,
                "promote_runtime": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class ProcedurePin:
    procedure_id: str
    procedure_version: int
    definition_digest: str

    def __post_init__(self) -> None:
        _require_identifier(self.procedure_id)
        _require_positive(self.procedure_version)
        _require_digest(self.definition_digest)

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "procedure_id": self.procedure_id,
            "procedure_version": self.procedure_version,
            "definition_digest": self.definition_digest,
        }


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


@dataclass(frozen=True)
class ProcedureReplayCost:
    model_turns: int = 0
    tool_calls: int = 0
    side_effects: int = 0
    observation_calls: int = 0
    input_tokens: int = 0
    result_bytes: int = 0
    duration_ms: int = 0
    human_approvals: int = 0
    retries: int = 0

    def __post_init__(self) -> None:
        for field_name in _COST_FIELDS:
            _require_nonnegative(getattr(self, field_name))

    def __add__(self, other: ProcedureReplayCost) -> ProcedureReplayCost:
        if not isinstance(other, ProcedureReplayCost):
            return NotImplemented
        return ProcedureReplayCost(
            **{
                field_name: getattr(self, field_name) + getattr(other, field_name)
                for field_name in _COST_FIELDS
            }
        )

    def to_payload(self) -> dict[str, JSONValue]:
        return {field_name: getattr(self, field_name) for field_name in _COST_FIELDS}

    def vector(self) -> tuple[int, ...]:
        return tuple(getattr(self, field_name) for field_name in _COST_FIELDS)


@dataclass(frozen=True)
class FixtureOperationResult:
    operation_id: str
    tool_name: str
    outcome: ProcedureReplayOutcome
    dispatch_certainty: DispatchCertainty
    approval_granted: bool
    fresh_observation: bool
    verified_value: bool | int | None
    cost: ProcedureReplayCost

    def __post_init__(self) -> None:
        _require_identifier(self.operation_id)
        _require_identifier(self.tool_name)
        try:
            get_tool_spec(self.tool_name)
        except ToolValidationError as exc:
            raise ProcedureValidationError("PROCEDURE_FIXTURE_TOOL_INVALID") from exc
        if not isinstance(self.outcome, ProcedureReplayOutcome) or not isinstance(
            self.dispatch_certainty, DispatchCertainty
        ):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_RESULT_INVALID")
        if type(self.approval_granted) is not bool or type(
            self.fresh_observation
        ) is not bool:
            raise ProcedureValidationError("PROCEDURE_FIXTURE_RESULT_INVALID")
        if self.verified_value is not None and type(self.verified_value) not in {
            bool,
            int,
        }:
            raise ProcedureValidationError("PROCEDURE_FIXTURE_CONTENT_REJECTED")
        if not isinstance(self.cost, ProcedureReplayCost):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_COST_INVALID")
        attempted = self.dispatch_certainty is not DispatchCertainty.NOT_DISPATCHED
        if self.cost.tool_calls != int(attempted):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_COST_INVALID")
        if (
            self.outcome is ProcedureReplayOutcome.UNKNOWN
            and self.dispatch_certainty is DispatchCertainty.NOT_DISPATCHED
        ) or (
            self.dispatch_certainty is DispatchCertainty.UNKNOWN
            and self.outcome is not ProcedureReplayOutcome.UNKNOWN
        ):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_CERTAINTY_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "operation_id": self.operation_id,
            "tool_name": self.tool_name,
            "outcome": self.outcome.value,
            "dispatch_certainty": self.dispatch_certainty.value,
            "approval_granted": self.approval_granted,
            "fresh_observation": self.fresh_observation,
            "verified_value": self.verified_value,
            "cost": self.cost.to_payload(),
        }


@dataclass(frozen=True)
class ProcedureReplayFixture:
    fixture_id: str
    split: ProcedureFixtureSplit
    source_episode_digest: str
    task_scope: str
    application_scope: str
    application_version: str
    registry_digest: str
    policy_digest: str
    facts: tuple[ProcedureFact, ...]
    operations: tuple[FixtureOperationResult, ...]

    def __post_init__(self) -> None:
        for value in (
            self.fixture_id,
            self.task_scope,
            self.application_scope,
            self.application_version,
        ):
            _require_identifier(value)
        if not isinstance(self.split, ProcedureFixtureSplit):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_SPLIT_INVALID")
        for value in (
            self.source_episode_digest,
            self.registry_digest,
            self.policy_digest,
        ):
            _require_digest(value)
        if (
            not isinstance(self.facts, tuple)
            or not 1 <= len(self.facts) <= MAX_PROCEDURE_PRECONDITIONS
            or not all(isinstance(item, ProcedureFact) for item in self.facts)
            or tuple(item.fact_id for item in self.facts)
            != tuple(sorted(item.fact_id for item in self.facts))
            or len({item.fact_id for item in self.facts}) != len(self.facts)
        ):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_FACT_INVALID")
        if (
            not isinstance(self.operations, tuple)
            or not 1 <= len(self.operations) <= MAX_FIXTURE_OPERATIONS
            or not all(isinstance(item, FixtureOperationResult) for item in self.operations)
        ):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_OPERATION_INVALID")
        keys = tuple((item.operation_id, item.tool_name) for item in self.operations)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_OPERATION_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "fixture_id": self.fixture_id,
            "split": self.split.value,
            "source_episode_digest": self.source_episode_digest,
            "task_scope": self.task_scope,
            "application_scope": self.application_scope,
            "application_version": self.application_version,
            "registry_digest": self.registry_digest,
            "policy_digest": self.policy_digest,
            "facts": [item.to_payload() for item in self.facts],
            "operations": [item.to_payload() for item in self.operations],
            "privacy": {
                "contains_raw_task": False,
                "contains_model_prose": False,
                "contains_raw_tool_result": False,
                "contains_observation_text": False,
                "contains_arguments": False,
                "contains_image": False,
                "contains_secret": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def _strict_mapping(
    value: object,
    fields: frozenset[str],
    *,
    code: str = "PROCEDURE_FIXTURE_INVALID",
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or frozenset(value) != fields:
        raise ProcedureValidationError(code)
    return value


def _decode_fact(value: object) -> ProcedureFact:
    item = _strict_mapping(value, frozenset({"fact_id", "fact_type", "value"}))
    try:
        return ProcedureFact(
            fact_id=item["fact_id"],  # type: ignore[arg-type]
            fact_type=FactType(item["fact_type"]),
            value=item["value"],  # type: ignore[arg-type]
        )
    except (TypeError, ValueError, ProcedureValidationError) as exc:
        raise ProcedureValidationError("PROCEDURE_FIXTURE_INVALID") from exc


def _decode_cost(value: object) -> ProcedureReplayCost:
    item = _strict_mapping(value, frozenset(_COST_FIELDS))
    try:
        return ProcedureReplayCost(
            **{field_name: item[field_name] for field_name in _COST_FIELDS}  # type: ignore[arg-type]
        )
    except (TypeError, ProcedureValidationError) as exc:
        raise ProcedureValidationError("PROCEDURE_FIXTURE_INVALID") from exc


def _decode_operation(value: object) -> FixtureOperationResult:
    item = _strict_mapping(
        value,
        frozenset(
            {
                "operation_id",
                "tool_name",
                "outcome",
                "dispatch_certainty",
                "approval_granted",
                "fresh_observation",
                "verified_value",
                "cost",
            }
        ),
    )
    try:
        return FixtureOperationResult(
            operation_id=item["operation_id"],  # type: ignore[arg-type]
            tool_name=item["tool_name"],  # type: ignore[arg-type]
            outcome=ProcedureReplayOutcome(item["outcome"]),
            dispatch_certainty=DispatchCertainty(item["dispatch_certainty"]),
            approval_granted=item["approval_granted"],  # type: ignore[arg-type]
            fresh_observation=item["fresh_observation"],  # type: ignore[arg-type]
            verified_value=item["verified_value"],  # type: ignore[arg-type]
            cost=_decode_cost(item["cost"]),
        )
    except (TypeError, ValueError, ProcedureValidationError) as exc:
        raise ProcedureValidationError("PROCEDURE_FIXTURE_INVALID") from exc


def decode_procedure_fixture_suite(value: object) -> tuple[ProcedureReplayFixture, ...]:
    """Strictly decode one bounded frozen fixture suite without file I/O."""

    root = _strict_mapping(
        value,
        frozenset({"procedure_fixture_suite_version", "fixtures"}),
    )
    if root["procedure_fixture_suite_version"] != PROCEDURE_FIXTURE_SUITE_VERSION:
        raise ProcedureValidationError("PROCEDURE_FIXTURE_VERSION_INVALID")
    raw_fixtures = root["fixtures"]
    if (
        not isinstance(raw_fixtures, list)
        or not 1 <= len(raw_fixtures) <= MAX_PROCEDURE_FIXTURES
    ):
        raise ProcedureValidationError("PROCEDURE_FIXTURE_INVALID")
    fixture_fields = frozenset(
        {
            "fixture_id",
            "split",
            "source_episode_digest",
            "task_scope",
            "application_scope",
            "application_version",
            "registry_digest",
            "policy_digest",
            "facts",
            "operations",
            "privacy",
        }
    )
    expected_privacy = {
        "contains_raw_task": False,
        "contains_model_prose": False,
        "contains_raw_tool_result": False,
        "contains_observation_text": False,
        "contains_arguments": False,
        "contains_image": False,
        "contains_secret": False,
    }
    fixtures: list[ProcedureReplayFixture] = []
    for raw_fixture in raw_fixtures:
        item = _strict_mapping(raw_fixture, fixture_fields)
        if item["privacy"] != expected_privacy:
            raise ProcedureValidationError("PROCEDURE_FIXTURE_PRIVACY_INVALID")
        raw_facts = item["facts"]
        raw_operations = item["operations"]
        if (
            not isinstance(raw_facts, list)
            or not 1 <= len(raw_facts) <= MAX_PROCEDURE_PRECONDITIONS
            or not isinstance(raw_operations, list)
            or not 1 <= len(raw_operations) <= MAX_FIXTURE_OPERATIONS
        ):
            raise ProcedureValidationError("PROCEDURE_FIXTURE_INVALID")
        try:
            fixtures.append(
                ProcedureReplayFixture(
                    fixture_id=item["fixture_id"],  # type: ignore[arg-type]
                    split=ProcedureFixtureSplit(item["split"]),
                    source_episode_digest=item["source_episode_digest"],  # type: ignore[arg-type]
                    task_scope=item["task_scope"],  # type: ignore[arg-type]
                    application_scope=item["application_scope"],  # type: ignore[arg-type]
                    application_version=item["application_version"],  # type: ignore[arg-type]
                    registry_digest=item["registry_digest"],  # type: ignore[arg-type]
                    policy_digest=item["policy_digest"],  # type: ignore[arg-type]
                    facts=tuple(_decode_fact(fact) for fact in raw_facts),
                    operations=tuple(
                        _decode_operation(operation) for operation in raw_operations
                    ),
                )
            )
        except (TypeError, ValueError, ProcedureValidationError) as exc:
            raise ProcedureValidationError("PROCEDURE_FIXTURE_INVALID") from exc
    if tuple(item.fixture_id for item in fixtures) != tuple(
        sorted(item.fixture_id for item in fixtures)
    ) or len({item.fixture_id for item in fixtures}) != len(fixtures):
        raise ProcedureValidationError("PROCEDURE_FIXTURE_ORDER_INVALID")
    return tuple(fixtures)


@dataclass(frozen=True)
class ProcedureReplayResult:
    definition_digest: str
    fixture_id: str
    fixture_digest: str
    terminal: ProcedureTerminal
    visited_operations: tuple[str, ...]
    verified_success: bool
    safety_escapes: int
    authority_regressions: int
    complete: bool
    failure_code: str | None
    cost: ProcedureReplayCost

    def __post_init__(self) -> None:
        _require_digest(self.definition_digest)
        _require_identifier(self.fixture_id)
        _require_digest(self.fixture_digest)
        if not isinstance(self.terminal, ProcedureTerminal):
            raise ProcedureValidationError("PROCEDURE_REPLAY_INVALID")
        if not isinstance(self.visited_operations, tuple) or not all(
            isinstance(item, str) and _IDENTIFIER.fullmatch(item)
            for item in self.visited_operations
        ):
            raise ProcedureValidationError("PROCEDURE_REPLAY_INVALID")
        if type(self.verified_success) is not bool or type(self.complete) is not bool:
            raise ProcedureValidationError("PROCEDURE_REPLAY_INVALID")
        _require_nonnegative(self.safety_escapes)
        _require_nonnegative(self.authority_regressions)
        if self.failure_code is not None:
            _require_identifier(self.failure_code)
        if not isinstance(self.cost, ProcedureReplayCost):
            raise ProcedureValidationError("PROCEDURE_REPLAY_INVALID")
        if self.verified_success != (
            self.terminal is ProcedureTerminal.VERIFIED_SUCCESS
            and self.complete
            and self.safety_escapes == 0
            and self.authority_regressions == 0
        ):
            raise ProcedureValidationError("PROCEDURE_REPLAY_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "definition_digest": self.definition_digest,
            "fixture_id": self.fixture_id,
            "fixture_digest": self.fixture_digest,
            "terminal": self.terminal.value,
            "visited_operations": list(self.visited_operations),
            "verified_success": self.verified_success,
            "safety_escapes": self.safety_escapes,
            "authority_regressions": self.authority_regressions,
            "complete": self.complete,
            "failure_code": self.failure_code,
            "cost": self.cost.to_payload(),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def _replay_result(
    definition: ProcedureDefinition,
    fixture: ProcedureReplayFixture,
    *,
    terminal: ProcedureTerminal = ProcedureTerminal.SAFE_STOP,
    visited: Sequence[str] = (),
    safety_escapes: int = 0,
    authority_regressions: int = 0,
    complete: bool = True,
    failure_code: str | None = None,
    cost: ProcedureReplayCost | None = None,
) -> ProcedureReplayResult:
    verified = (
        terminal is ProcedureTerminal.VERIFIED_SUCCESS
        and complete
        and safety_escapes == 0
        and authority_regressions == 0
    )
    return ProcedureReplayResult(
        definition_digest=definition.digest,
        fixture_id=fixture.fixture_id,
        fixture_digest=fixture.digest,
        terminal=terminal,
        visited_operations=tuple(visited),
        verified_success=verified,
        safety_escapes=safety_escapes,
        authority_regressions=authority_regressions,
        complete=complete,
        failure_code=failure_code,
        cost=ProcedureReplayCost() if cost is None else cost,
    )


def replay_procedure(
    definition: ProcedureDefinition,
    fixture: ProcedureReplayFixture,
) -> ProcedureReplayResult:
    """Purely replay one definition against one frozen content-free fixture."""

    if not isinstance(definition, ProcedureDefinition) or not isinstance(
        fixture, ProcedureReplayFixture
    ):
        raise ProcedureValidationError("PROCEDURE_REPLAY_INPUT_INVALID")
    if (
        fixture.task_scope != definition.task_scope
        or fixture.application_scope != definition.application_scope
        or fixture.application_version != definition.application_version
        or fixture.registry_digest != definition.registry_digest
        or fixture.policy_digest != definition.policy_digest
    ):
        return _replay_result(
            definition,
            fixture,
            complete=False,
            failure_code="FIXTURE_SCOPE_MISMATCH",
        )
    if (
        fixture.split is ProcedureFixtureSplit.HELD_OUT
        and fixture.source_episode_digest in definition.source_episode_digests
    ):
        return _replay_result(
            definition,
            fixture,
            complete=False,
            failure_code="HELD_OUT_SOURCE_LEAKAGE",
        )
    fixture_facts = {item.fact_id: item for item in fixture.facts}
    if any(fixture_facts.get(item.fact_id) != item for item in definition.preconditions):
        return _replay_result(
            definition,
            fixture,
            failure_code="PRECONDITION_UNSATISFIED",
        )
    responses = {
        (item.operation_id, item.tool_name): item for item in fixture.operations
    }
    steps = {item.step_id: item for item in definition.steps}
    current = definition.steps[0].step_id
    visited: list[str] = []
    total_cost = ProcedureReplayCost()
    for _ in range(len(definition.steps)):
        step = steps[current]
        response = responses.get((step.operation_id, step.tool_name))
        if response is None:
            return _replay_result(
                definition,
                fixture,
                visited=visited,
                complete=False,
                failure_code="FIXTURE_OPERATION_MISSING",
                cost=total_cost,
            )
        attempted = response.dispatch_certainty is not DispatchCertainty.NOT_DISPATCHED
        expected_side_effects = int(
            step.kind is ProcedureStepKind.ACTION and attempted
        )
        expected_observations = int(
            step.kind is not ProcedureStepKind.ACTION and attempted
        )
        expected_approvals = int(
            step.kind is ProcedureStepKind.ACTION and response.approval_granted
        )
        if (
            response.cost.side_effects != expected_side_effects
            or response.cost.observation_calls != expected_observations
            or response.cost.human_approvals != expected_approvals
            or (
                step.kind is not ProcedureStepKind.ACTION
                and response.approval_granted
            )
            or (
                response.outcome is ProcedureReplayOutcome.SUCCESS
                and not attempted
            )
        ):
            return _replay_result(
                definition,
                fixture,
                visited=visited,
                complete=False,
                failure_code="FIXTURE_OPERATION_INVALID",
                cost=total_cost,
            )
        visited.append(step.operation_id)
        total_cost = total_cost + response.cost
        if step.kind is ProcedureStepKind.ACTION and attempted and (
            not response.approval_granted or not response.fresh_observation
        ):
            return _replay_result(
                definition,
                fixture,
                visited=visited,
                safety_escapes=1,
                authority_regressions=1,
                failure_code="AUTHORITY_ESCAPE",
                cost=total_cost,
            )
        if response.outcome is ProcedureReplayOutcome.UNKNOWN:
            return _replay_result(
                definition,
                fixture,
                visited=visited,
                failure_code="UNKNOWN_OUTCOME",
                cost=total_cost,
            )
        succeeded = response.outcome is ProcedureReplayOutcome.SUCCESS
        if step.kind is ProcedureStepKind.VERIFY:
            assert step.postcondition is not None
            succeeded = succeeded and (
                type(response.verified_value) is type(step.postcondition.value)
                and response.verified_value == step.postcondition.value
            )
        target = step.success_target if succeeded else step.failure_target
        if target == ProcedureTerminal.VERIFIED_SUCCESS.value:
            return _replay_result(
                definition,
                fixture,
                terminal=ProcedureTerminal.VERIFIED_SUCCESS,
                visited=visited,
                cost=total_cost,
            )
        if target == ProcedureTerminal.SAFE_STOP.value:
            return _replay_result(
                definition,
                fixture,
                visited=visited,
                failure_code=(
                    "OPERATION_FAILED" if not succeeded else "SAFE_STOP"
                ),
                cost=total_cost,
            )
        current = target
    return _replay_result(
        definition,
        fixture,
        visited=visited,
        complete=False,
        failure_code="REPLAY_BOUND_EXCEEDED",
        cost=total_cost,
    )


@dataclass(frozen=True)
class ProcedureEvaluation:
    definition_digest: str
    results: tuple[ProcedureReplayResult, ...]
    total_cost: ProcedureReplayCost
    evaluation_version: int = PROCEDURE_EVALUATION_VERSION

    def __post_init__(self) -> None:
        _require_digest(self.definition_digest)
        if (
            self.evaluation_version != PROCEDURE_EVALUATION_VERSION
            or isinstance(self.evaluation_version, bool)
            or not MIN_HELD_OUT_FIXTURES
            <= len(self.results)
            <= MAX_PROCEDURE_FIXTURES
            or not all(isinstance(item, ProcedureReplayResult) for item in self.results)
            or tuple(item.fixture_id for item in self.results)
            != tuple(sorted(item.fixture_id for item in self.results))
            or len({item.fixture_id for item in self.results}) != len(self.results)
            or any(item.definition_digest != self.definition_digest for item in self.results)
        ):
            raise ProcedureValidationError("PROCEDURE_EVALUATION_INVALID")
        expected = ProcedureReplayCost()
        for result in self.results:
            expected = expected + result.cost
        if self.total_cost != expected:
            raise ProcedureValidationError("PROCEDURE_EVALUATION_INVALID")

    @property
    def fixture_suite_digest(self) -> str:
        return _digest(
            {
                "procedure_fixture_suite_version": PROCEDURE_FIXTURE_SUITE_VERSION,
                "fixture_digests": [item.fixture_digest for item in self.results],
            }
        )

    @property
    def verified_successes(self) -> int:
        return sum(item.verified_success for item in self.results)

    @property
    def safety_escapes(self) -> int:
        return sum(item.safety_escapes for item in self.results)

    @property
    def authority_regressions(self) -> int:
        return sum(item.authority_regressions for item in self.results)

    @property
    def complete(self) -> bool:
        return all(item.complete for item in self.results)

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "procedure_evaluation_version": self.evaluation_version,
            "definition_digest": self.definition_digest,
            "fixture_suite_digest": self.fixture_suite_digest,
            "fixture_count": len(self.results),
            "verified_successes": self.verified_successes,
            "safety_escapes": self.safety_escapes,
            "authority_regressions": self.authority_regressions,
            "complete": self.complete,
            "total_cost": self.total_cost.to_payload(),
            "result_digests": [item.digest for item in self.results],
            "data_class": PROCEDURE_DATA_CLASS,
            "use": PROCEDURE_USE,
            "capabilities": {
                "authorize": False,
                "dispatch": False,
                "execute": False,
                "select_strategy": False,
                "promote_runtime": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def evaluate_procedure(
    definition: ProcedureDefinition,
    fixtures: Sequence[ProcedureReplayFixture],
) -> ProcedureEvaluation:
    """Evaluate one definition only on an ordered held-out suite."""

    if not isinstance(definition, ProcedureDefinition) or isinstance(
        fixtures, (str, bytes)
    ) or not isinstance(fixtures, Sequence):
        raise ProcedureValidationError("PROCEDURE_EVALUATION_INPUT_INVALID")
    frozen = tuple(fixtures)
    if (
        not MIN_HELD_OUT_FIXTURES <= len(frozen) <= MAX_PROCEDURE_FIXTURES
        or not all(isinstance(item, ProcedureReplayFixture) for item in frozen)
        or any(item.split is not ProcedureFixtureSplit.HELD_OUT for item in frozen)
        or tuple(item.fixture_id for item in frozen)
        != tuple(sorted(item.fixture_id for item in frozen))
        or len({item.fixture_id for item in frozen}) != len(frozen)
    ):
        raise ProcedureValidationError("PROCEDURE_EVALUATION_FIXTURES_INVALID")
    results = tuple(replay_procedure(definition, fixture) for fixture in frozen)
    total_cost = ProcedureReplayCost()
    for result in results:
        total_cost = total_cost + result.cost
    return ProcedureEvaluation(
        definition_digest=definition.digest,
        results=results,
        total_cost=total_cost,
    )


@dataclass(frozen=True)
class ProcedureActivationGate:
    candidate_definition_digest: str
    baseline_definition_digest: str
    candidate_evaluation_digest: str
    baseline_evaluation_digest: str
    fixture_suite_digest: str
    improvement: ProcedureImprovement
    passes: bool
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.candidate_definition_digest,
            self.baseline_definition_digest,
            self.candidate_evaluation_digest,
            self.baseline_evaluation_digest,
            self.fixture_suite_digest,
        ):
            _require_digest(value)
        if not isinstance(self.improvement, ProcedureImprovement) or type(
            self.passes
        ) is not bool:
            raise ProcedureValidationError("PROCEDURE_GATE_INVALID")
        if not isinstance(self.reasons, tuple) or not all(
            isinstance(item, str) and _IDENTIFIER.fullmatch(item)
            for item in self.reasons
        ):
            raise ProcedureValidationError("PROCEDURE_GATE_INVALID")
        if self.passes != (not self.reasons and self.improvement is not ProcedureImprovement.NONE):
            raise ProcedureValidationError("PROCEDURE_GATE_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "candidate_definition_digest": self.candidate_definition_digest,
            "baseline_definition_digest": self.baseline_definition_digest,
            "candidate_evaluation_digest": self.candidate_evaluation_digest,
            "baseline_evaluation_digest": self.baseline_evaluation_digest,
            "fixture_suite_digest": self.fixture_suite_digest,
            "improvement": self.improvement.value,
            "passes": self.passes,
            "reasons": list(self.reasons),
            "runtime_activation": False,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


def build_activation_gate(
    candidate: ProcedureEvaluation,
    baseline: ProcedureEvaluation,
) -> ProcedureActivationGate:
    """Compare two evaluations on one exact held-out suite."""

    if not isinstance(candidate, ProcedureEvaluation) or not isinstance(
        baseline, ProcedureEvaluation
    ):
        raise ProcedureValidationError("PROCEDURE_GATE_INPUT_INVALID")
    reasons: list[str] = []
    if candidate.definition_digest == baseline.definition_digest:
        reasons.append("BASELINE_EQUALS_CANDIDATE")
    if candidate.fixture_suite_digest != baseline.fixture_suite_digest:
        reasons.append("FIXTURE_SUITE_MISMATCH")
    if not candidate.complete or not baseline.complete:
        reasons.append("EVALUATION_INCOMPLETE")
    if candidate.safety_escapes or baseline.safety_escapes:
        reasons.append("SAFETY_ESCAPE")
    if candidate.authority_regressions or baseline.authority_regressions:
        reasons.append("AUTHORITY_REGRESSION")
    if candidate.verified_successes != len(candidate.results):
        reasons.append("CANDIDATE_NOT_FULLY_VERIFIED")
    improvement = ProcedureImprovement.NONE
    if candidate.verified_successes > baseline.verified_successes:
        improvement = ProcedureImprovement.VERIFIED_OUTCOME
    elif candidate.verified_successes == baseline.verified_successes:
        candidate_cost = candidate.total_cost.vector()
        baseline_cost = baseline.total_cost.vector()
        if all(left <= right for left, right in zip(candidate_cost, baseline_cost)) and any(
            left < right for left, right in zip(candidate_cost, baseline_cost)
        ):
            improvement = ProcedureImprovement.PARETO_COST
    if improvement is ProcedureImprovement.NONE:
        reasons.append("NO_HELD_OUT_IMPROVEMENT")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return ProcedureActivationGate(
        candidate_definition_digest=candidate.definition_digest,
        baseline_definition_digest=baseline.definition_digest,
        candidate_evaluation_digest=candidate.digest,
        baseline_evaluation_digest=baseline.digest,
        fixture_suite_digest=candidate.fixture_suite_digest,
        improvement=improvement,
        passes=not unique_reasons,
        reasons=unique_reasons,
    )


@dataclass(frozen=True)
class ProcedureCandidateRecord:
    definition: ProcedureDefinition
    status: ProcedureStatus
    revision: int
    created_at: str
    updated_at: str
    expires_at: str
    rollback_target: ProcedurePin
    activation_gate_digest: str | None = None
    lifecycle_version: int = PROCEDURE_LIFECYCLE_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ProcedureDefinition) or not isinstance(
            self.status, ProcedureStatus
        ):
            raise ProcedureValidationError("PROCEDURE_LIFECYCLE_INVALID")
        _require_nonnegative(self.revision)
        created = _parse_time(self.created_at)
        updated = _parse_time(self.updated_at)
        expires = _parse_time(self.expires_at)
        if (
            updated < created
            or expires <= created
            or expires > created + timedelta(days=MAX_PROCEDURE_LIFETIME_DAYS)
        ):
            raise ProcedureValidationError("PROCEDURE_TIME_INVALID")
        if not isinstance(self.rollback_target, ProcedurePin) or (
            self.rollback_target.procedure_id == self.definition.procedure_id
            and self.rollback_target.procedure_version
            == self.definition.procedure_version
        ):
            raise ProcedureValidationError("PROCEDURE_ROLLBACK_TARGET_INVALID")
        if self.activation_gate_digest is not None:
            _require_digest(self.activation_gate_digest)
        if self.status in {ProcedureStatus.SHADOW, ProcedureStatus.ACTIVE} and (
            self.activation_gate_digest is None
        ):
            raise ProcedureValidationError("PROCEDURE_GATE_REQUIRED")
        if self.lifecycle_version != PROCEDURE_LIFECYCLE_VERSION or isinstance(
            self.lifecycle_version, bool
        ):
            raise ProcedureValidationError("PROCEDURE_LIFECYCLE_INVALID")

    @property
    def candidate_id(self) -> str:
        return self.definition.digest

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "procedure_lifecycle_version": self.lifecycle_version,
            "candidate_id": self.candidate_id,
            "definition": self.definition.to_payload(),
            "status": self.status.value,
            "revision": self.revision,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "rollback_target": self.rollback_target.to_payload(),
            "activation_gate_digest": self.activation_gate_digest,
            "data_class": PROCEDURE_DATA_CLASS,
            "use": PROCEDURE_USE,
            "capabilities": {
                "authorize": False,
                "dispatch": False,
                "execute": False,
                "inject_memory": False,
                "select_strategy": False,
                "promote_runtime": False,
            },
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class ProcedureLifecycleEvent:
    candidate_id: str
    sequence: int
    action: ProcedureLifecycleAction
    occurred_at: str
    from_status: ProcedureStatus | None
    to_status: ProcedureStatus
    from_revision: int | None
    to_revision: int
    prior_digest: str | None
    record_digest: str
    reviewed: bool
    activation_gate_digest: str | None = None
    rollback_target: ProcedurePin | None = None

    def __post_init__(self) -> None:
        _require_digest(self.candidate_id)
        _require_positive(self.sequence)
        _parse_time(self.occurred_at)
        if not isinstance(self.action, ProcedureLifecycleAction) or not isinstance(
            self.to_status, ProcedureStatus
        ):
            raise ProcedureValidationError("PROCEDURE_EVENT_INVALID")
        if self.from_status is not None and not isinstance(
            self.from_status, ProcedureStatus
        ):
            raise ProcedureValidationError("PROCEDURE_EVENT_INVALID")
        if self.from_revision is not None:
            _require_nonnegative(self.from_revision)
        _require_nonnegative(self.to_revision)
        if self.prior_digest is not None:
            _require_digest(self.prior_digest)
        _require_digest(self.record_digest)
        if type(self.reviewed) is not bool:
            raise ProcedureValidationError("PROCEDURE_EVENT_INVALID")
        if self.activation_gate_digest is not None:
            _require_digest(self.activation_gate_digest)
        if self.rollback_target is not None and not isinstance(
            self.rollback_target, ProcedurePin
        ):
            raise ProcedureValidationError("PROCEDURE_EVENT_INVALID")
        expected: dict[ProcedureLifecycleAction, tuple[set[ProcedureStatus | None], ProcedureStatus]] = {
            ProcedureLifecycleAction.CREATED: ({None}, ProcedureStatus.CANDIDATE),
            ProcedureLifecycleAction.STARTED_EVALUATION: (
                {ProcedureStatus.CANDIDATE},
                ProcedureStatus.EVALUATING,
            ),
            ProcedureLifecycleAction.ENTERED_SHADOW: (
                {ProcedureStatus.EVALUATING},
                ProcedureStatus.SHADOW,
            ),
            ProcedureLifecycleAction.ACTIVATED: (
                {ProcedureStatus.SHADOW},
                ProcedureStatus.ACTIVE,
            ),
            ProcedureLifecycleAction.DEPRECATED: (
                {ProcedureStatus.ACTIVE},
                ProcedureStatus.DEPRECATED,
            ),
            ProcedureLifecycleAction.RETIRED: (
                {ProcedureStatus.DEPRECATED},
                ProcedureStatus.RETIRED,
            ),
            ProcedureLifecycleAction.REJECTED: (
                {
                    ProcedureStatus.CANDIDATE,
                    ProcedureStatus.EVALUATING,
                    ProcedureStatus.SHADOW,
                },
                ProcedureStatus.REJECTED,
            ),
            ProcedureLifecycleAction.ROLLED_BACK: (
                {ProcedureStatus.ACTIVE, ProcedureStatus.DEPRECATED},
                ProcedureStatus.ROLLED_BACK,
            ),
        }
        allowed_from, expected_to = expected[self.action]
        if self.from_status not in allowed_from or self.to_status is not expected_to:
            raise ProcedureValidationError("PROCEDURE_EVENT_TRANSITION_INVALID")
        if self.action is ProcedureLifecycleAction.CREATED:
            valid = (
                self.sequence == 1
                and self.from_revision is None
                and self.to_revision == 0
                and self.prior_digest is None
                and not self.reviewed
            )
        else:
            valid = (
                self.from_revision is not None
                and self.to_revision == self.from_revision + 1
                and self.prior_digest is not None
            )
        gate_action = self.action in {
            ProcedureLifecycleAction.ENTERED_SHADOW,
            ProcedureLifecycleAction.ACTIVATED,
        }
        rollback_action = self.action is ProcedureLifecycleAction.ROLLED_BACK
        if (
            not valid
            or gate_action != (self.activation_gate_digest is not None)
            or rollback_action != (self.rollback_target is not None)
            or (gate_action or rollback_action) != self.reviewed
        ):
            raise ProcedureValidationError("PROCEDURE_EVENT_INVALID")

    def to_payload(self) -> dict[str, JSONValue]:
        return {
            "candidate_id": self.candidate_id,
            "sequence": self.sequence,
            "action": self.action.value,
            "occurred_at": self.occurred_at,
            "from_status": (
                None if self.from_status is None else self.from_status.value
            ),
            "to_status": self.to_status.value,
            "from_revision": self.from_revision,
            "to_revision": self.to_revision,
            "prior_digest": self.prior_digest,
            "record_digest": self.record_digest,
            "reviewed": self.reviewed,
            "activation_gate_digest": self.activation_gate_digest,
            "rollback_target": (
                None if self.rollback_target is None else self.rollback_target.to_payload()
            ),
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_payload())


@dataclass(frozen=True)
class ProcedureLifecycle:
    record: ProcedureCandidateRecord
    events: tuple[ProcedureLifecycleEvent, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.record, ProcedureCandidateRecord) or not isinstance(
            self.events, tuple
        ) or not self.events:
            raise ProcedureValidationError("PROCEDURE_LIFECYCLE_INVALID")
        for expected_sequence, event in enumerate(self.events, start=1):
            if not isinstance(event, ProcedureLifecycleEvent) or (
                event.sequence != expected_sequence
                or event.candidate_id != self.record.candidate_id
            ):
                raise ProcedureValidationError("PROCEDURE_LIFECYCLE_INVALID")
            if expected_sequence > 1:
                prior = self.events[expected_sequence - 2]
                if (
                    event.from_status is not prior.to_status
                    or event.from_revision != prior.to_revision
                    or event.prior_digest != prior.record_digest
                    or _parse_time(event.occurred_at) < _parse_time(prior.occurred_at)
                ):
                    raise ProcedureValidationError("PROCEDURE_LIFECYCLE_INVALID")
        first = self.events[0]
        tail = self.events[-1]
        if (
            first.action is not ProcedureLifecycleAction.CREATED
            or first.occurred_at != self.record.created_at
            or tail.to_status is not self.record.status
            or tail.to_revision != self.record.revision
            or tail.record_digest != self.record.digest
            or tail.occurred_at != self.record.updated_at
        ):
            raise ProcedureValidationError("PROCEDURE_LIFECYCLE_INVALID")


def create_procedure_candidate(
    definition: ProcedureDefinition,
    *,
    now: datetime,
    expires_at: datetime,
    rollback_target: ProcedurePin,
) -> ProcedureLifecycle:
    """Create one inert candidate and its first content-free audit event."""

    if not isinstance(definition, ProcedureDefinition) or not isinstance(
        rollback_target, ProcedurePin
    ):
        raise ProcedureValidationError("PROCEDURE_CREATE_INVALID")
    current = _aware_utc(now)
    expiry = _aware_utc(expires_at)
    if expiry <= current or expiry > current + timedelta(days=MAX_PROCEDURE_LIFETIME_DAYS):
        raise ProcedureValidationError("PROCEDURE_EXPIRY_INVALID")
    timestamp = _iso(current)
    record = ProcedureCandidateRecord(
        definition=definition,
        status=ProcedureStatus.CANDIDATE,
        revision=0,
        created_at=timestamp,
        updated_at=timestamp,
        expires_at=_iso(expiry),
        rollback_target=rollback_target,
    )
    event = ProcedureLifecycleEvent(
        candidate_id=record.candidate_id,
        sequence=1,
        action=ProcedureLifecycleAction.CREATED,
        occurred_at=timestamp,
        from_status=None,
        to_status=ProcedureStatus.CANDIDATE,
        from_revision=None,
        to_revision=0,
        prior_digest=None,
        record_digest=record.digest,
        reviewed=False,
    )
    return ProcedureLifecycle(record, (event,))


_TARGET_ACTION = {
    ProcedureStatus.EVALUATING: ProcedureLifecycleAction.STARTED_EVALUATION,
    ProcedureStatus.SHADOW: ProcedureLifecycleAction.ENTERED_SHADOW,
    ProcedureStatus.ACTIVE: ProcedureLifecycleAction.ACTIVATED,
    ProcedureStatus.DEPRECATED: ProcedureLifecycleAction.DEPRECATED,
    ProcedureStatus.RETIRED: ProcedureLifecycleAction.RETIRED,
    ProcedureStatus.REJECTED: ProcedureLifecycleAction.REJECTED,
    ProcedureStatus.ROLLED_BACK: ProcedureLifecycleAction.ROLLED_BACK,
}


def transition_procedure_candidate(
    lifecycle: ProcedureLifecycle,
    target: ProcedureStatus,
    *,
    expected_revision: int,
    now: datetime,
    reviewed: bool = False,
    candidate_evaluation: ProcedureEvaluation | None = None,
    baseline_evaluation: ProcedureEvaluation | None = None,
    rollback_target: ProcedurePin | None = None,
) -> ProcedureLifecycle:
    """Apply one exact-revision lifecycle transition without runtime activation."""

    if not isinstance(lifecycle, ProcedureLifecycle) or not isinstance(
        target, ProcedureStatus
    ):
        raise ProcedureValidationError("PROCEDURE_TRANSITION_INVALID")
    _require_nonnegative(expected_revision)
    if type(reviewed) is not bool:
        raise ProcedureValidationError("PROCEDURE_TRANSITION_INVALID")
    record = lifecycle.record
    current = _aware_utc(now)
    timestamp = _iso(current)
    if record.revision != expected_revision:
        raise ProcedureValidationError("PROCEDURE_REVISION_CONFLICT")
    if current < _parse_time(record.updated_at):
        raise ProcedureValidationError("PROCEDURE_TIME_INVALID")
    action = _TARGET_ACTION.get(target)
    if action is None:
        raise ProcedureValidationError("PROCEDURE_TRANSITION_INVALID")
    gate: ProcedureActivationGate | None = None
    if target in {ProcedureStatus.SHADOW, ProcedureStatus.ACTIVE}:
        if (
            not reviewed
            or candidate_evaluation is None
            or baseline_evaluation is None
        ):
            raise ProcedureValidationError("PROCEDURE_REVIEW_REQUIRED")
        gate = build_activation_gate(candidate_evaluation, baseline_evaluation)
        if (
            not gate.passes
            or gate.candidate_definition_digest != record.definition.digest
            or current >= _parse_time(record.expires_at)
        ):
            raise ProcedureValidationError("PROCEDURE_ACTIVATION_GATE_FAILED")
    elif candidate_evaluation is not None or baseline_evaluation is not None:
        raise ProcedureValidationError("PROCEDURE_EVALUATION_UNEXPECTED")
    if target is ProcedureStatus.ROLLED_BACK:
        if (
            not reviewed
            or rollback_target is None
            or rollback_target != record.rollback_target
        ):
            raise ProcedureValidationError("PROCEDURE_ROLLBACK_TARGET_INVALID")
    elif rollback_target is not None:
        raise ProcedureValidationError("PROCEDURE_ROLLBACK_TARGET_UNEXPECTED")
    if target in {ProcedureStatus.EVALUATING, ProcedureStatus.SHADOW} and current >= _parse_time(
        record.expires_at
    ):
        raise ProcedureValidationError("PROCEDURE_EXPIRED")
    next_record = replace(
        record,
        status=target,
        revision=record.revision + 1,
        updated_at=timestamp,
        activation_gate_digest=(
            record.activation_gate_digest if gate is None else gate.digest
        ),
    )
    event = ProcedureLifecycleEvent(
        candidate_id=record.candidate_id,
        sequence=len(lifecycle.events) + 1,
        action=action,
        occurred_at=timestamp,
        from_status=record.status,
        to_status=target,
        from_revision=record.revision,
        to_revision=next_record.revision,
        prior_digest=record.digest,
        record_digest=next_record.digest,
        reviewed=reviewed,
        activation_gate_digest=None if gate is None else gate.digest,
        rollback_target=(rollback_target if target is ProcedureStatus.ROLLED_BACK else None),
    )
    return ProcedureLifecycle(next_record, (*lifecycle.events, event))


__all__ = [
    "MAX_FIXTURE_OPERATIONS",
    "MAX_PROCEDURE_FIXTURES",
    "MAX_PROCEDURE_LIFETIME_DAYS",
    "MAX_PROCEDURE_PRECONDITIONS",
    "MAX_PROCEDURE_SOURCE_EPISODES",
    "MAX_PROCEDURE_STEPS",
    "MIN_HELD_OUT_FIXTURES",
    "PROCEDURE_CONTRACT_VERSION",
    "PROCEDURE_DATA_CLASS",
    "PROCEDURE_EVALUATION_VERSION",
    "PROCEDURE_FIXTURE_SUITE_VERSION",
    "PROCEDURE_LIFECYCLE_VERSION",
    "PROCEDURE_USE",
    "FixtureOperationResult",
    "ProcedureActivationGate",
    "ProcedureCandidateRecord",
    "ProcedureDefinition",
    "ProcedureEvaluation",
    "ProcedureFact",
    "ProcedureFixtureSplit",
    "ProcedureImprovement",
    "ProcedureLifecycle",
    "ProcedureLifecycleAction",
    "ProcedureLifecycleEvent",
    "ProcedurePin",
    "ProcedureReplayCost",
    "ProcedureReplayFixture",
    "ProcedureReplayOutcome",
    "ProcedureReplayResult",
    "ProcedureStatus",
    "ProcedureStep",
    "ProcedureStepKind",
    "ProcedureTerminal",
    "ProcedureValidationError",
    "build_activation_gate",
    "create_procedure_candidate",
    "decode_procedure_fixture_suite",
    "evaluate_procedure",
    "replay_procedure",
    "transition_procedure_candidate",
]
