"""Pure offline contracts for the first Formal Demo v1 implementation slice.

The four public structures in this module are inert, versioned data.  They do
not import or expose a provider, Runner, MCP bridge, desktop driver, approval
port, persistence layer, or application adapter.  Untrusted ``TaskIntent``
JSON may select only Host-authored semantic identifiers; it cannot name tools,
applications, adapters, arguments, permissions, actions, or recipients.

The built-in product records are design bindings, not implementation or
application evidence.  In particular, the email handoff adapter remains
unselected, so compiling the full product scenario fails closed until a later
explicit slice reviews one exact adapter.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping, Sequence


TASK_INTENT_VERSION = 1
DEMO_SCENARIO_SPEC_VERSION = 1
APPLICATION_ROLE_PROFILE_VERSION = 1
GENERIC_SCOPE_SHEET_VERSION = 1
FORMAL_DEMO_BINDING_VERSION = 1

MAX_TASK_INTENT_JSON_BYTES = 16 * 1024
MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES = 64 * 1024
MAX_SOURCE_TASK_BYTES = 8 * 1024
MAX_IDENTIFIER_CHARS = 80
MAX_LABEL_CHARS = 160
MAX_DESCRIPTION_CHARS = 512
MAX_CONTRACT_ITEMS = 16
MAX_BUDGET_VALUE = 10_000

_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,79}\Z")
_RESUME_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_BUDGET_FIELDS = (
    "provider_calls",
    "tool_calls",
    "side_effects",
    "retries",
    "artifacts",
)


class FormalDemoContractError(ValueError):
    """Fixed, content-free failure from an offline Formal Demo contract."""


class SemanticRole(str, Enum):
    SOURCE = "source"
    EVIDENCE = "evidence"
    ANALYSIS = "analysis"
    REPORT = "report"
    HANDOFF = "handoff"


_ROLE_ORDER = {role: index for index, role in enumerate(SemanticRole)}


class DemoRiskCeiling(str, Enum):
    READ_ONLY = "read_only"
    DRAFT = "draft"
    REVERSIBLE = "reversible"
    EXTERNAL = "external"
    CRITICAL = "critical"


_RISK_ORDER = {risk: index for index, risk in enumerate(DemoRiskCeiling)}


class ProfileBindingState(str, Enum):
    SELECTED = "selected"
    UNSELECTED = "unselected"


def _canonical_json_bytes(payload: object) -> bytes:
    """Return the private, domain-local canonical JSON representation."""

    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise FormalDemoContractError("FORMAL_DEMO_CANONICAL_JSON_INVALID") from None


def _content_digest(domain: str, payload: object) -> str:
    return sha256(
        _canonical_json_bytes({"domain": domain, "payload": payload})
    ).hexdigest()


def _require_canonical_size(payload: object, *, max_bytes: int) -> None:
    if len(_canonical_json_bytes(payload)) > max_bytes:
        raise FormalDemoContractError("FORMAL_DEMO_CANONICAL_JSON_TOO_LARGE")


def _duplicate_safe_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise FormalDemoContractError("FORMAL_DEMO_JSON_DUPLICATE_KEY")
        value[key] = item
    return value


def _reject_json_number(_value: str) -> object:
    raise FormalDemoContractError("FORMAL_DEMO_JSON_NUMBER_INVALID")


def _parse_json_integer(value: str) -> int:
    if len(value) > 6:
        raise FormalDemoContractError("FORMAL_DEMO_JSON_NUMBER_INVALID")
    try:
        return int(value)
    except ValueError:
        raise FormalDemoContractError("FORMAL_DEMO_JSON_NUMBER_INVALID") from None


def _parse_json_object(text: str, *, max_bytes: int) -> dict[str, object]:
    if not isinstance(text, str) or not text:
        raise FormalDemoContractError("FORMAL_DEMO_JSON_INVALID")
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        raise FormalDemoContractError("FORMAL_DEMO_JSON_INVALID") from None
    if len(encoded) > max_bytes:
        raise FormalDemoContractError("FORMAL_DEMO_JSON_TOO_LARGE")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_duplicate_safe_object,
            parse_int=_parse_json_integer,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except FormalDemoContractError:
        raise
    except (json.JSONDecodeError, RecursionError, UnicodeError):
        raise FormalDemoContractError("FORMAL_DEMO_JSON_INVALID") from None
    if not isinstance(value, dict):
        raise FormalDemoContractError("FORMAL_DEMO_JSON_INVALID")
    return value


def _strict_mapping(
    value: object,
    fields: set[str] | frozenset[str],
    *,
    code: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise FormalDemoContractError(code)
    return value


def _require_version(value: object, expected: int) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value != expected
    ):
        raise FormalDemoContractError("FORMAL_DEMO_VERSION_UNSUPPORTED")
    return value


def _require_identifier(value: object, *, code: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise FormalDemoContractError(code)
    return value


def _require_resume_identity(value: object) -> str:
    if not isinstance(value, str) or _RESUME_IDENTITY.fullmatch(value) is None:
        raise FormalDemoContractError("FORMAL_DEMO_RESUME_IDENTITY_INVALID")
    return value


def _require_digest(value: object, *, code: str) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise FormalDemoContractError(code)
    return value


def _require_text(value: object, *, limit: int, code: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > limit
        or _CONTROL.search(value) is not None
    ):
        raise FormalDemoContractError(code)
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise FormalDemoContractError(code) from None
    return value


def _require_source_task_digest(source_task: str) -> str:
    if not isinstance(source_task, str) or not source_task.strip() or "\x00" in source_task:
        raise FormalDemoContractError("FORMAL_DEMO_SOURCE_TASK_INVALID")
    try:
        encoded = source_task.encode("utf-8")
    except UnicodeError:
        raise FormalDemoContractError("FORMAL_DEMO_SOURCE_TASK_INVALID") from None
    if len(encoded) > MAX_SOURCE_TASK_BYTES:
        raise FormalDemoContractError("FORMAL_DEMO_SOURCE_TASK_TOO_LARGE")
    return sha256(encoded).hexdigest()


def _normalize_identifier_tuple(
    values: tuple[str, ...],
    *,
    minimum: int,
    maximum: int = MAX_CONTRACT_ITEMS,
    code: str,
) -> tuple[str, ...]:
    if (
        not isinstance(values, tuple)
        or not minimum <= len(values) <= maximum
        or any(not isinstance(item, str) or _IDENTIFIER.fullmatch(item) is None for item in values)
        or len(set(values)) != len(values)
    ):
        raise FormalDemoContractError(code)
    return tuple(sorted(values))


def _normalize_text_tuple(
    values: tuple[str, ...],
    *,
    minimum: int,
    maximum: int = MAX_CONTRACT_ITEMS,
    code: str,
) -> tuple[str, ...]:
    if not isinstance(values, tuple) or not minimum <= len(values) <= maximum:
        raise FormalDemoContractError(code)
    normalized = tuple(
        _require_text(item, limit=MAX_DESCRIPTION_CHARS, code=code) for item in values
    )
    if len(set(normalized)) != len(normalized):
        raise FormalDemoContractError(code)
    return tuple(sorted(normalized))


def _normalize_roles(
    values: tuple[SemanticRole, ...],
    *,
    minimum: int,
    code: str,
) -> tuple[SemanticRole, ...]:
    if (
        not isinstance(values, tuple)
        or not minimum <= len(values) <= len(SemanticRole)
        or any(not isinstance(item, SemanticRole) for item in values)
        or len(set(values)) != len(values)
    ):
        raise FormalDemoContractError(code)
    return tuple(sorted(values, key=_ROLE_ORDER.__getitem__))


def _freeze_text_map(
    value: Mapping[str, str],
    *,
    minimum: int,
    code: str,
) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not minimum <= len(value) <= MAX_CONTRACT_ITEMS:
        raise FormalDemoContractError(code)
    copied: dict[str, str] = {}
    for key, description in value.items():
        selected_key = _require_identifier(key, code=code)
        copied[selected_key] = _require_text(
            description,
            limit=MAX_DESCRIPTION_CHARS,
            code=code,
        )
    if len(copied) != len(value):
        raise FormalDemoContractError(code)
    return MappingProxyType(dict(sorted(copied.items())))


def _roles_from_json(value: object, *, code: str) -> tuple[SemanticRole, ...]:
    if not isinstance(value, list):
        raise FormalDemoContractError(code)
    try:
        roles = tuple(SemanticRole(item) for item in value)
    except (TypeError, ValueError):
        raise FormalDemoContractError(code) from None
    return _normalize_roles(roles, minimum=1, code=code)


def _identifiers_from_json(
    value: object,
    *,
    minimum: int,
    code: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FormalDemoContractError(code)
    return _normalize_identifier_tuple(tuple(value), minimum=minimum, code=code)  # type: ignore[arg-type]


def _texts_from_json(value: object, *, minimum: int, code: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise FormalDemoContractError(code)
    return _normalize_text_tuple(tuple(value), minimum=minimum, code=code)  # type: ignore[arg-type]


def _text_map_from_json(value: object, *, minimum: int, code: str) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise FormalDemoContractError(code)
    if any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise FormalDemoContractError(code)
    return _freeze_text_map(value, minimum=minimum, code=code)  # type: ignore[arg-type]


@dataclass(frozen=True)
class DemoBudgets:
    """Typed intended-run ceilings; constructing this object starts no work."""

    provider_calls: int
    tool_calls: int
    side_effects: int
    retries: int
    artifacts: int

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= MAX_BUDGET_VALUE
            for value in (
                self.provider_calls,
                self.tool_calls,
                self.side_effects,
                self.retries,
                self.artifacts,
            )
        ):
            raise FormalDemoContractError("FORMAL_DEMO_BUDGET_INVALID")

    def canonical_payload(self) -> dict[str, int]:
        return {field: getattr(self, field) for field in _BUDGET_FIELDS}

    def within(self, ceilings: DemoBudgets) -> bool:
        if not isinstance(ceilings, DemoBudgets):
            raise FormalDemoContractError("FORMAL_DEMO_BUDGET_INVALID")
        return all(
            getattr(self, field) <= getattr(ceilings, field)
            for field in _BUDGET_FIELDS
        )


def _budgets_from_json(value: object) -> DemoBudgets:
    mapping = _strict_mapping(
        value,
        frozenset(_BUDGET_FIELDS),
        code="FORMAL_DEMO_BUDGET_INVALID",
    )
    return DemoBudgets(**mapping)  # type: ignore[arg-type]


@dataclass(frozen=True)
class TaskIntent:
    """Host-normalized, untrusted intent data with no execution authority."""

    source_task_digest: str
    scenario_id: str
    outcome_id: str
    requested_roles: tuple[SemanticRole, ...]
    requested_outputs: tuple[str, ...]
    constraint_ids: tuple[str, ...]
    risk_ceiling: DemoRiskCeiling
    budgets: DemoBudgets
    version: int = TASK_INTENT_VERSION

    def __post_init__(self) -> None:
        _require_version(self.version, TASK_INTENT_VERSION)
        _require_digest(
            self.source_task_digest,
            code="FORMAL_DEMO_SOURCE_TASK_DIGEST_INVALID",
        )
        _require_identifier(self.scenario_id, code="FORMAL_DEMO_INTENT_INVALID")
        _require_identifier(self.outcome_id, code="FORMAL_DEMO_INTENT_INVALID")
        object.__setattr__(
            self,
            "requested_roles",
            _normalize_roles(
                self.requested_roles,
                minimum=1,
                code="FORMAL_DEMO_INTENT_ROLES_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "requested_outputs",
            _normalize_identifier_tuple(
                self.requested_outputs,
                minimum=1,
                code="FORMAL_DEMO_INTENT_OUTPUTS_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "constraint_ids",
            _normalize_identifier_tuple(
                self.constraint_ids,
                minimum=1,
                code="FORMAL_DEMO_INTENT_CONSTRAINTS_INVALID",
            ),
        )
        if not isinstance(self.risk_ceiling, DemoRiskCeiling):
            raise FormalDemoContractError("FORMAL_DEMO_INTENT_RISK_INVALID")
        if not isinstance(self.budgets, DemoBudgets):
            raise FormalDemoContractError("FORMAL_DEMO_BUDGET_INVALID")
        _require_canonical_size(
            self.canonical_payload(),
            max_bytes=MAX_TASK_INTENT_JSON_BYTES,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source_task_digest": self.source_task_digest,
            "scenario_id": self.scenario_id,
            "outcome_id": self.outcome_id,
            "requested_roles": [role.value for role in self.requested_roles],
            "requested_outputs": list(self.requested_outputs),
            "constraint_ids": list(self.constraint_ids),
            "risk_ceiling": self.risk_ceiling.value,
            "budgets": self.budgets.canonical_payload(),
        }

    @property
    def content_digest(self) -> str:
        return _content_digest("formal-demo-task-intent-v1", self.canonical_payload())

    def canonical_json(self) -> str:
        return _canonical_json_bytes(self.canonical_payload()).decode("utf-8")


@dataclass(frozen=True)
class DemoScenarioSpec:
    """Host-authored semantic allowlist without tools, calls, or application code."""

    scenario_id: str
    outcomes: Mapping[str, str]
    allowed_roles: tuple[SemanticRole, ...]
    required_roles: tuple[SemanticRole, ...]
    outputs: Mapping[str, str]
    required_outputs: tuple[str, ...]
    constraints: Mapping[str, str]
    required_constraints: tuple[str, ...]
    budget_ceilings: DemoBudgets
    fixtures: Mapping[str, str]
    risk_ceiling: DemoRiskCeiling
    forbidden_effects: tuple[str, ...]
    version: int = DEMO_SCENARIO_SPEC_VERSION

    def __post_init__(self) -> None:
        _require_version(self.version, DEMO_SCENARIO_SPEC_VERSION)
        _require_identifier(self.scenario_id, code="FORMAL_DEMO_SCENARIO_INVALID")
        object.__setattr__(
            self,
            "outcomes",
            _freeze_text_map(
                self.outcomes,
                minimum=1,
                code="FORMAL_DEMO_SCENARIO_OUTCOMES_INVALID",
            ),
        )
        allowed_roles = _normalize_roles(
            self.allowed_roles,
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_ROLES_INVALID",
        )
        required_roles = _normalize_roles(
            self.required_roles,
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_ROLES_INVALID",
        )
        if not set(required_roles) <= set(allowed_roles):
            raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_ROLES_INVALID")
        object.__setattr__(self, "allowed_roles", allowed_roles)
        object.__setattr__(self, "required_roles", required_roles)
        outputs = _freeze_text_map(
            self.outputs,
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_OUTPUTS_INVALID",
        )
        required_outputs = _normalize_identifier_tuple(
            self.required_outputs,
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_OUTPUTS_INVALID",
        )
        if not set(required_outputs) <= set(outputs):
            raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_OUTPUTS_INVALID")
        object.__setattr__(self, "outputs", outputs)
        object.__setattr__(self, "required_outputs", required_outputs)
        constraints = _freeze_text_map(
            self.constraints,
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_CONSTRAINTS_INVALID",
        )
        required_constraints = _normalize_identifier_tuple(
            self.required_constraints,
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_CONSTRAINTS_INVALID",
        )
        if not set(required_constraints) <= set(constraints):
            raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_CONSTRAINTS_INVALID")
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(self, "required_constraints", required_constraints)
        if not isinstance(self.budget_ceilings, DemoBudgets):
            raise FormalDemoContractError("FORMAL_DEMO_BUDGET_INVALID")
        object.__setattr__(
            self,
            "fixtures",
            _freeze_text_map(
                self.fixtures,
                minimum=1,
                code="FORMAL_DEMO_SCENARIO_FIXTURES_INVALID",
            ),
        )
        if not isinstance(self.risk_ceiling, DemoRiskCeiling):
            raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_RISK_INVALID")
        object.__setattr__(
            self,
            "forbidden_effects",
            _normalize_identifier_tuple(
                self.forbidden_effects,
                minimum=1,
                code="FORMAL_DEMO_SCENARIO_EFFECTS_INVALID",
            ),
        )
        _require_canonical_size(
            self.canonical_payload(),
            max_bytes=MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "scenario_id": self.scenario_id,
            "outcomes": dict(self.outcomes),
            "allowed_roles": [role.value for role in self.allowed_roles],
            "required_roles": [role.value for role in self.required_roles],
            "outputs": dict(self.outputs),
            "required_outputs": list(self.required_outputs),
            "constraints": dict(self.constraints),
            "required_constraints": list(self.required_constraints),
            "budget_ceilings": self.budget_ceilings.canonical_payload(),
            "fixtures": dict(self.fixtures),
            "risk_ceiling": self.risk_ceiling.value,
            "forbidden_effects": list(self.forbidden_effects),
        }

    @property
    def content_digest(self) -> str:
        return _content_digest("formal-demo-scenario-v1", self.canonical_payload())

    def canonical_json(self) -> str:
        return _canonical_json_bytes(self.canonical_payload()).decode("utf-8")


@dataclass(frozen=True)
class ApplicationRoleProfile:
    """Inert semantic role data; only an exact registry pin establishes review."""

    profile_id: str
    role: SemanticRole
    application_label: str
    adapter_id: str | None
    binding_state: ProfileBindingState
    test_data_boundary: str
    reads: tuple[str, ...]
    changes: tuple[str, ...]
    output_ids: tuple[str, ...]
    fixture_ids: tuple[str, ...]
    risk_ceiling: DemoRiskCeiling
    forbidden_effects: tuple[str, ...]
    version: int = APPLICATION_ROLE_PROFILE_VERSION

    def __post_init__(self) -> None:
        _require_version(self.version, APPLICATION_ROLE_PROFILE_VERSION)
        _require_identifier(self.profile_id, code="FORMAL_DEMO_PROFILE_INVALID")
        if not isinstance(self.role, SemanticRole):
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_ROLE_INVALID")
        _require_text(
            self.application_label,
            limit=MAX_LABEL_CHARS,
            code="FORMAL_DEMO_PROFILE_INVALID",
        )
        if not isinstance(self.binding_state, ProfileBindingState):
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_BINDING_INVALID")
        if self.binding_state is ProfileBindingState.SELECTED:
            _require_identifier(self.adapter_id, code="FORMAL_DEMO_PROFILE_BINDING_INVALID")
        elif self.adapter_id is not None:
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_BINDING_INVALID")
        _require_text(
            self.test_data_boundary,
            limit=MAX_DESCRIPTION_CHARS,
            code="FORMAL_DEMO_PROFILE_INVALID",
        )
        object.__setattr__(
            self,
            "reads",
            _normalize_text_tuple(
                self.reads,
                minimum=1,
                code="FORMAL_DEMO_PROFILE_READS_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "changes",
            _normalize_text_tuple(
                self.changes,
                minimum=0,
                code="FORMAL_DEMO_PROFILE_CHANGES_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "output_ids",
            _normalize_identifier_tuple(
                self.output_ids,
                minimum=0,
                code="FORMAL_DEMO_PROFILE_OUTPUTS_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "fixture_ids",
            _normalize_identifier_tuple(
                self.fixture_ids,
                minimum=1,
                code="FORMAL_DEMO_PROFILE_FIXTURES_INVALID",
            ),
        )
        if not isinstance(self.risk_ceiling, DemoRiskCeiling):
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_RISK_INVALID")
        if self.changes and self.risk_ceiling is DemoRiskCeiling.READ_ONLY:
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_RISK_INVALID")
        object.__setattr__(
            self,
            "forbidden_effects",
            _normalize_identifier_tuple(
                self.forbidden_effects,
                minimum=0,
                code="FORMAL_DEMO_PROFILE_EFFECTS_INVALID",
            ),
        )
        _require_canonical_size(
            self.canonical_payload(),
            max_bytes=MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "profile_id": self.profile_id,
            "role": self.role.value,
            "application_label": self.application_label,
            "adapter_id": self.adapter_id,
            "binding_state": self.binding_state.value,
            "test_data_boundary": self.test_data_boundary,
            "reads": list(self.reads),
            "changes": list(self.changes),
            "output_ids": list(self.output_ids),
            "fixture_ids": list(self.fixture_ids),
            "risk_ceiling": self.risk_ceiling.value,
            "forbidden_effects": list(self.forbidden_effects),
        }

    @property
    def content_digest(self) -> str:
        return _content_digest("formal-demo-role-profile-v1", self.canonical_payload())

    def canonical_json(self) -> str:
        return _canonical_json_bytes(self.canonical_payload()).decode("utf-8")


@dataclass(frozen=True)
class ScopeApplication:
    """One exact bound application-role projection in a Scope Sheet."""

    role: SemanticRole
    profile_id: str
    profile_digest: str
    application_label: str
    adapter_id: str
    test_data_boundary: str
    reads: tuple[str, ...]
    changes: tuple[str, ...]
    output_ids: tuple[str, ...]
    fixture_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.role, SemanticRole):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        _require_identifier(self.profile_id, code="FORMAL_DEMO_SCOPE_INVALID")
        _require_digest(self.profile_digest, code="FORMAL_DEMO_SCOPE_INVALID")
        _require_text(
            self.application_label,
            limit=MAX_LABEL_CHARS,
            code="FORMAL_DEMO_SCOPE_INVALID",
        )
        _require_identifier(self.adapter_id, code="FORMAL_DEMO_SCOPE_INVALID")
        _require_text(
            self.test_data_boundary,
            limit=MAX_DESCRIPTION_CHARS,
            code="FORMAL_DEMO_SCOPE_INVALID",
        )
        object.__setattr__(
            self,
            "reads",
            _normalize_text_tuple(
                self.reads,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "changes",
            _normalize_text_tuple(
                self.changes,
                minimum=0,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "output_ids",
            _normalize_identifier_tuple(
                self.output_ids,
                minimum=0,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "fixture_ids",
            _normalize_identifier_tuple(
                self.fixture_ids,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "profile_id": self.profile_id,
            "profile_digest": self.profile_digest,
            "application_label": self.application_label,
            "adapter_id": self.adapter_id,
            "test_data_boundary": self.test_data_boundary,
            "reads": list(self.reads),
            "changes": list(self.changes),
            "output_ids": list(self.output_ids),
            "fixture_ids": list(self.fixture_ids),
        }


_SCOPE_APPROVALS = (
    "START enters only this bound scope and grants no individual action approval.",
    "Every later action remains subject to ordinary Host policy, approval, grounding, and observation.",
)
_SCOPE_STOPS: Mapping[str, str] = MappingProxyType(
    {
        "authority_lost": "Desktop authority, grounding, or fresh observation is unavailable.",
        "budget_exceeded": "One reviewed intended-run budget would be exceeded.",
        "human_handoff_required": "A challenge, ambiguity, or product decision requires the operator.",
        "policy_denied": "Host policy or an exact action approval denies work.",
        "profile_unavailable": "A required reviewed application-role binding is unavailable.",
        "unknown_outcome": "A side effect may have happened; never replay it automatically.",
        "unsupported_scope": "The requested outcome, role, output, constraint, or risk is outside the scenario.",
        "verification_failed": "A required output or cleanup postcondition is not verified.",
    }
)
_SCOPE_RESIDUE = (
    "Compiling this Scope Sheet starts no provider, durable workflow, MCP, desktop, or application work.",
    "A future disposable artifact or test-account draft must be reported if cleanup cannot be verified.",
)


@dataclass(frozen=True)
class GenericScopeSheet:
    """Host-compiled, digest-bound review data without action authority."""

    resume_identity: str
    scenario_id: str
    goal: str
    applications: tuple[ScopeApplication, ...]
    reads: tuple[str, ...]
    changes: tuple[str, ...]
    outputs: Mapping[str, str]
    constraints: Mapping[str, str]
    risk_ceiling: DemoRiskCeiling
    budgets: DemoBudgets
    approvals: tuple[str, ...]
    stop_conditions: Mapping[str, str]
    possible_residue: tuple[str, ...]
    forbidden_effects: tuple[str, ...]
    task_intent_digest: str
    scenario_digest: str
    profile_digests: Mapping[str, str]
    binding_digest: str
    reviewed_registry_pins_verified: bool
    version: int = GENERIC_SCOPE_SHEET_VERSION

    def __post_init__(self) -> None:
        _require_version(self.version, GENERIC_SCOPE_SHEET_VERSION)
        _require_resume_identity(self.resume_identity)
        _require_identifier(self.scenario_id, code="FORMAL_DEMO_SCOPE_INVALID")
        _require_text(
            self.goal,
            limit=MAX_DESCRIPTION_CHARS,
            code="FORMAL_DEMO_SCOPE_INVALID",
        )
        if (
            not isinstance(self.applications, tuple)
            or not 1 <= len(self.applications) <= len(SemanticRole)
            or any(not isinstance(item, ScopeApplication) for item in self.applications)
            or len({item.role for item in self.applications}) != len(self.applications)
            or tuple(item.role for item in self.applications)
            != tuple(sorted((item.role for item in self.applications), key=_ROLE_ORDER.__getitem__))
        ):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        object.__setattr__(
            self,
            "reads",
            _normalize_text_tuple(
                self.reads,
                minimum=1,
                maximum=MAX_CONTRACT_ITEMS * 2,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "changes",
            _normalize_text_tuple(
                self.changes,
                minimum=0,
                maximum=MAX_CONTRACT_ITEMS * 2,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "outputs",
            _freeze_text_map(
                self.outputs,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "constraints",
            _freeze_text_map(
                self.constraints,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        if not isinstance(self.risk_ceiling, DemoRiskCeiling):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        if not isinstance(self.budgets, DemoBudgets):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        object.__setattr__(
            self,
            "approvals",
            _normalize_text_tuple(
                self.approvals,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "stop_conditions",
            _freeze_text_map(
                self.stop_conditions,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "possible_residue",
            _normalize_text_tuple(
                self.possible_residue,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        object.__setattr__(
            self,
            "forbidden_effects",
            _normalize_identifier_tuple(
                self.forbidden_effects,
                minimum=1,
                code="FORMAL_DEMO_SCOPE_INVALID",
            ),
        )
        _require_digest(self.task_intent_digest, code="FORMAL_DEMO_SCOPE_INVALID")
        _require_digest(self.scenario_digest, code="FORMAL_DEMO_SCOPE_INVALID")
        if (
            not isinstance(self.profile_digests, Mapping)
            or set(self.profile_digests) != {item.role.value for item in self.applications}
        ):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        frozen_profile_digests: dict[str, str] = {}
        for role, digest in self.profile_digests.items():
            _require_identifier(role, code="FORMAL_DEMO_SCOPE_INVALID")
            frozen_profile_digests[role] = _require_digest(
                digest,
                code="FORMAL_DEMO_SCOPE_INVALID",
            )
        object.__setattr__(
            self,
            "profile_digests",
            MappingProxyType(dict(sorted(frozen_profile_digests.items()))),
        )
        if any(
            frozen_profile_digests[application.role.value]
            != application.profile_digest
            for application in self.applications
        ):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        _require_digest(self.binding_digest, code="FORMAL_DEMO_SCOPE_INVALID")
        if not isinstance(self.reviewed_registry_pins_verified, bool):
            raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
        _require_canonical_size(
            self.canonical_payload(),
            max_bytes=MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES,
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "source": "host_compiled_from_validated_task_intent",
            "contains_model_prose": False,
            "compilation_starts_external_work": False,
            "grants_execution_authority": False,
            "reviewed_registry_pins_verified": self.reviewed_registry_pins_verified,
            "resume_identity": self.resume_identity,
            "scenario_id": self.scenario_id,
            "goal": self.goal,
            "applications": [item.canonical_payload() for item in self.applications],
            "reads": list(self.reads),
            "changes": list(self.changes),
            "outputs": dict(self.outputs),
            "constraints": dict(self.constraints),
            "risk_ceiling": self.risk_ceiling.value,
            "budgets": self.budgets.canonical_payload(),
            "approvals": list(self.approvals),
            "stop_conditions": dict(self.stop_conditions),
            "possible_residue": list(self.possible_residue),
            "forbidden_effects": list(self.forbidden_effects),
            "digests": {
                "task_intent": self.task_intent_digest,
                "scenario": self.scenario_digest,
                "profiles": dict(self.profile_digests),
                "binding": self.binding_digest,
            },
            "acknowledgement": {
                "interactive_token": "START",
                "starts_bound_scope_only": True,
                "grants_action_approval": False,
                "grants_retry_or_replay": False,
            },
        }

    def canonical_json(self) -> str:
        return _canonical_json_bytes(self.canonical_payload()).decode("utf-8")


def decode_task_intent(candidate: str, *, source_task: str) -> TaskIntent:
    """Decode one bounded provider/local candidate into non-authoritative data."""

    value = _parse_json_object(candidate, max_bytes=MAX_TASK_INTENT_JSON_BYTES)
    value = _strict_mapping(
        value,
        {
            "version",
            "scenario_id",
            "outcome_id",
            "requested_roles",
            "requested_outputs",
            "constraint_ids",
            "risk_ceiling",
            "budgets",
        },
        code="FORMAL_DEMO_INTENT_SHAPE_INVALID",
    )
    _require_version(value["version"], TASK_INTENT_VERSION)
    try:
        risk = DemoRiskCeiling(value["risk_ceiling"])
    except (TypeError, ValueError):
        raise FormalDemoContractError("FORMAL_DEMO_INTENT_RISK_INVALID") from None
    return TaskIntent(
        source_task_digest=_require_source_task_digest(source_task),
        scenario_id=_require_identifier(
            value["scenario_id"],
            code="FORMAL_DEMO_INTENT_INVALID",
        ),
        outcome_id=_require_identifier(
            value["outcome_id"],
            code="FORMAL_DEMO_INTENT_INVALID",
        ),
        requested_roles=_roles_from_json(
            value["requested_roles"],
            code="FORMAL_DEMO_INTENT_ROLES_INVALID",
        ),
        requested_outputs=_identifiers_from_json(
            value["requested_outputs"],
            minimum=1,
            code="FORMAL_DEMO_INTENT_OUTPUTS_INVALID",
        ),
        constraint_ids=_identifiers_from_json(
            value["constraint_ids"],
            minimum=1,
            code="FORMAL_DEMO_INTENT_CONSTRAINTS_INVALID",
        ),
        risk_ceiling=risk,
        budgets=_budgets_from_json(value["budgets"]),
    )


def decode_task_intent_artifact(
    text: str,
    *,
    source_task: str,
    expected_intent_digest: str,
) -> TaskIntent:
    """Reload canonical Host-normalized intent data and verify its source binding."""

    value = _parse_json_object(text, max_bytes=MAX_TASK_INTENT_JSON_BYTES)
    value = _strict_mapping(
        value,
        {
            "version",
            "source_task_digest",
            "scenario_id",
            "outcome_id",
            "requested_roles",
            "requested_outputs",
            "constraint_ids",
            "risk_ceiling",
            "budgets",
        },
        code="FORMAL_DEMO_INTENT_SHAPE_INVALID",
    )
    _require_version(value["version"], TASK_INTENT_VERSION)
    expected_source_digest = _require_source_task_digest(source_task)
    if value["source_task_digest"] != expected_source_digest:
        raise FormalDemoContractError("FORMAL_DEMO_SOURCE_TASK_DIGEST_MISMATCH")
    try:
        risk = DemoRiskCeiling(value["risk_ceiling"])
    except (TypeError, ValueError):
        raise FormalDemoContractError("FORMAL_DEMO_INTENT_RISK_INVALID") from None
    intent = TaskIntent(
        source_task_digest=expected_source_digest,
        scenario_id=_require_identifier(
            value["scenario_id"],
            code="FORMAL_DEMO_INTENT_INVALID",
        ),
        outcome_id=_require_identifier(
            value["outcome_id"],
            code="FORMAL_DEMO_INTENT_INVALID",
        ),
        requested_roles=_roles_from_json(
            value["requested_roles"],
            code="FORMAL_DEMO_INTENT_ROLES_INVALID",
        ),
        requested_outputs=_identifiers_from_json(
            value["requested_outputs"],
            minimum=1,
            code="FORMAL_DEMO_INTENT_OUTPUTS_INVALID",
        ),
        constraint_ids=_identifiers_from_json(
            value["constraint_ids"],
            minimum=1,
            code="FORMAL_DEMO_INTENT_CONSTRAINTS_INVALID",
        ),
        risk_ceiling=risk,
        budgets=_budgets_from_json(value["budgets"]),
    )
    selected_digest = _require_digest(
        expected_intent_digest,
        code="FORMAL_DEMO_INTENT_DIGEST_MISMATCH",
    )
    if intent.content_digest != selected_digest:
        raise FormalDemoContractError("FORMAL_DEMO_INTENT_DIGEST_MISMATCH")
    return intent


def decode_demo_scenario_spec(text: str) -> DemoScenarioSpec:
    """Load one exact versioned Host scenario from bounded JSON text."""

    value = _parse_json_object(text, max_bytes=MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES)
    value = _strict_mapping(
        value,
        {
            "version",
            "scenario_id",
            "outcomes",
            "allowed_roles",
            "required_roles",
            "outputs",
            "required_outputs",
            "constraints",
            "required_constraints",
            "budget_ceilings",
            "fixtures",
            "risk_ceiling",
            "forbidden_effects",
        },
        code="FORMAL_DEMO_SCENARIO_SHAPE_INVALID",
    )
    _require_version(value["version"], DEMO_SCENARIO_SPEC_VERSION)
    try:
        risk = DemoRiskCeiling(value["risk_ceiling"])
    except (TypeError, ValueError):
        raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_RISK_INVALID") from None
    return DemoScenarioSpec(
        scenario_id=_require_identifier(
            value["scenario_id"],
            code="FORMAL_DEMO_SCENARIO_INVALID",
        ),
        outcomes=_text_map_from_json(
            value["outcomes"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_OUTCOMES_INVALID",
        ),
        allowed_roles=_roles_from_json(
            value["allowed_roles"],
            code="FORMAL_DEMO_SCENARIO_ROLES_INVALID",
        ),
        required_roles=_roles_from_json(
            value["required_roles"],
            code="FORMAL_DEMO_SCENARIO_ROLES_INVALID",
        ),
        outputs=_text_map_from_json(
            value["outputs"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_OUTPUTS_INVALID",
        ),
        required_outputs=_identifiers_from_json(
            value["required_outputs"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_OUTPUTS_INVALID",
        ),
        constraints=_text_map_from_json(
            value["constraints"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_CONSTRAINTS_INVALID",
        ),
        required_constraints=_identifiers_from_json(
            value["required_constraints"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_CONSTRAINTS_INVALID",
        ),
        budget_ceilings=_budgets_from_json(value["budget_ceilings"]),
        fixtures=_text_map_from_json(
            value["fixtures"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_FIXTURES_INVALID",
        ),
        risk_ceiling=risk,
        forbidden_effects=_identifiers_from_json(
            value["forbidden_effects"],
            minimum=1,
            code="FORMAL_DEMO_SCENARIO_EFFECTS_INVALID",
        ),
    )


def decode_application_role_profile(text: str) -> ApplicationRoleProfile:
    """Structurally load inert role data; validation does not make it reviewed.

    A future product path must resolve exact Host-reviewed profile pins.  This
    decoder exists for bounded offline contract round-trips and cannot register
    an adapter, grant authority, or establish application availability.
    """

    value = _parse_json_object(text, max_bytes=MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES)
    value = _strict_mapping(
        value,
        {
            "version",
            "profile_id",
            "role",
            "application_label",
            "adapter_id",
            "binding_state",
            "test_data_boundary",
            "reads",
            "changes",
            "output_ids",
            "fixture_ids",
            "risk_ceiling",
            "forbidden_effects",
        },
        code="FORMAL_DEMO_PROFILE_SHAPE_INVALID",
    )
    _require_version(value["version"], APPLICATION_ROLE_PROFILE_VERSION)
    try:
        role = SemanticRole(value["role"])
        binding_state = ProfileBindingState(value["binding_state"])
        risk = DemoRiskCeiling(value["risk_ceiling"])
    except (TypeError, ValueError):
        raise FormalDemoContractError("FORMAL_DEMO_PROFILE_ENUM_INVALID") from None
    adapter_id = value["adapter_id"]
    if adapter_id is not None and not isinstance(adapter_id, str):
        raise FormalDemoContractError("FORMAL_DEMO_PROFILE_BINDING_INVALID")
    return ApplicationRoleProfile(
        profile_id=_require_identifier(
            value["profile_id"],
            code="FORMAL_DEMO_PROFILE_INVALID",
        ),
        role=role,
        application_label=_require_text(
            value["application_label"],
            limit=MAX_LABEL_CHARS,
            code="FORMAL_DEMO_PROFILE_INVALID",
        ),
        adapter_id=adapter_id,
        binding_state=binding_state,
        test_data_boundary=_require_text(
            value["test_data_boundary"],
            limit=MAX_DESCRIPTION_CHARS,
            code="FORMAL_DEMO_PROFILE_INVALID",
        ),
        reads=_texts_from_json(
            value["reads"],
            minimum=1,
            code="FORMAL_DEMO_PROFILE_READS_INVALID",
        ),
        changes=_texts_from_json(
            value["changes"],
            minimum=0,
            code="FORMAL_DEMO_PROFILE_CHANGES_INVALID",
        ),
        output_ids=_identifiers_from_json(
            value["output_ids"],
            minimum=0,
            code="FORMAL_DEMO_PROFILE_OUTPUTS_INVALID",
        ),
        fixture_ids=_identifiers_from_json(
            value["fixture_ids"],
            minimum=1,
            code="FORMAL_DEMO_PROFILE_FIXTURES_INVALID",
        ),
        risk_ceiling=risk,
        forbidden_effects=_identifiers_from_json(
            value["forbidden_effects"],
            minimum=0,
            code="FORMAL_DEMO_PROFILE_EFFECTS_INVALID",
        ),
    )


def _validate_intent_against_scenario(
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
) -> None:
    if intent.scenario_id != scenario.scenario_id:
        raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_MISMATCH")
    if intent.outcome_id not in scenario.outcomes:
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_EXPANSION")
    if (
        not set(scenario.required_roles) <= set(intent.requested_roles)
        or not set(intent.requested_roles) <= set(scenario.allowed_roles)
        or not set(scenario.required_outputs) <= set(intent.requested_outputs)
        or not set(intent.requested_outputs) <= set(scenario.outputs)
        or not set(scenario.required_constraints) <= set(intent.constraint_ids)
        or not set(intent.constraint_ids) <= set(scenario.constraints)
        or _RISK_ORDER[intent.risk_ceiling] > _RISK_ORDER[scenario.risk_ceiling]
    ):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_EXPANSION")
    if not intent.budgets.within(scenario.budget_ceilings):
        raise FormalDemoContractError("FORMAL_DEMO_BUDGET_EXCEEDED")
    if intent.budgets.artifacts < len(intent.requested_outputs):
        raise FormalDemoContractError("FORMAL_DEMO_BUDGET_EXCEEDED")


def _ordered_profiles(
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
    profiles: Sequence[ApplicationRoleProfile],
) -> tuple[ApplicationRoleProfile, ...]:
    if (
        isinstance(profiles, (str, bytes))
        or not isinstance(profiles, Sequence)
        or not 1 <= len(profiles) <= MAX_CONTRACT_ITEMS
        or any(not isinstance(profile, ApplicationRoleProfile) for profile in profiles)
    ):
        raise FormalDemoContractError("FORMAL_DEMO_PROFILES_INVALID")
    selected = tuple(profiles)
    if (
        len({profile.profile_id for profile in selected}) != len(selected)
        or len({profile.role for profile in selected}) != len(selected)
        or {profile.role for profile in selected} != set(intent.requested_roles)
    ):
        raise FormalDemoContractError("FORMAL_DEMO_PROFILES_INVALID")
    by_role = {profile.role: profile for profile in selected}
    ordered = tuple(by_role[role] for role in intent.requested_roles)
    output_owners: dict[str, int] = {output: 0 for output in intent.requested_outputs}
    for profile in ordered:
        if profile.binding_state is not ProfileBindingState.SELECTED:
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_UNAVAILABLE")
        if (
            _RISK_ORDER[profile.risk_ceiling] > _RISK_ORDER[intent.risk_ceiling]
            or not set(profile.fixture_ids) <= set(scenario.fixtures)
            or not set(profile.output_ids) <= set(intent.requested_outputs)
        ):
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_SCOPE_INVALID")
        for output in profile.output_ids:
            output_owners[output] += 1
    if any(count != 1 for count in output_owners.values()):
        raise FormalDemoContractError("FORMAL_DEMO_OUTPUT_AMBIGUOUS")
    return ordered


def _binding_digest(
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
    profiles: tuple[ApplicationRoleProfile, ...],
    resume_identity: str,
) -> str:
    material = {
        "binding_version": FORMAL_DEMO_BINDING_VERSION,
        "scope_sheet_version": GENERIC_SCOPE_SHEET_VERSION,
        "resume_identity": resume_identity,
        "task_intent": intent.canonical_payload(),
        "scenario": scenario.canonical_payload(),
        "profiles": [profile.canonical_payload() for profile in profiles],
    }
    return _content_digest("formal-demo-binding-v1", material)


def _compile_generic_scope_sheet(
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
    profiles: Sequence[ApplicationRoleProfile],
    *,
    resume_identity: str,
    expected_binding_digest: str | None = None,
    reviewed_registry_pins_verified: bool,
) -> GenericScopeSheet:
    """Compile an inert Scope Sheet after structural cross-contract validation."""

    if not isinstance(intent, TaskIntent) or not isinstance(scenario, DemoScenarioSpec):
        raise FormalDemoContractError("FORMAL_DEMO_COMPILATION_INVALID")
    selected_resume = _require_resume_identity(resume_identity)
    _validate_intent_against_scenario(intent, scenario)
    ordered = _ordered_profiles(intent, scenario, profiles)
    binding_digest = _binding_digest(intent, scenario, ordered, selected_resume)
    if expected_binding_digest is not None:
        _require_digest(
            expected_binding_digest,
            code="FORMAL_DEMO_BINDING_DIGEST_MISMATCH",
        )
        if expected_binding_digest != binding_digest:
            raise FormalDemoContractError("FORMAL_DEMO_BINDING_DIGEST_MISMATCH")

    applications = tuple(
        ScopeApplication(
            role=profile.role,
            profile_id=profile.profile_id,
            profile_digest=profile.content_digest,
            application_label=profile.application_label,
            adapter_id=profile.adapter_id,  # type: ignore[arg-type]
            test_data_boundary=profile.test_data_boundary,
            reads=profile.reads,
            changes=profile.changes,
            output_ids=profile.output_ids,
            fixture_ids=profile.fixture_ids,
        )
        for profile in ordered
    )
    reads = tuple(
        f"{application.role.value}: {item}"
        for application in applications
        for item in application.reads
    )
    changes = tuple(
        f"{application.role.value}: {item}"
        for application in applications
        for item in application.changes
    )
    forbidden_effects = tuple(
        sorted(
            set(scenario.forbidden_effects).union(
                *(set(profile.forbidden_effects) for profile in ordered)
            )
        )
    )
    return GenericScopeSheet(
        resume_identity=selected_resume,
        scenario_id=scenario.scenario_id,
        goal=scenario.outcomes[intent.outcome_id],
        applications=applications,
        reads=reads,
        changes=changes,
        outputs={output: scenario.outputs[output] for output in intent.requested_outputs},
        constraints={
            constraint: scenario.constraints[constraint]
            for constraint in intent.constraint_ids
        },
        risk_ceiling=intent.risk_ceiling,
        budgets=intent.budgets,
        approvals=_SCOPE_APPROVALS,
        stop_conditions=_SCOPE_STOPS,
        possible_residue=_SCOPE_RESIDUE,
        forbidden_effects=forbidden_effects,
        task_intent_digest=intent.content_digest,
        scenario_digest=scenario.content_digest,
        profile_digests={
            profile.role.value: profile.content_digest for profile in ordered
        },
        binding_digest=binding_digest,
        reviewed_registry_pins_verified=reviewed_registry_pins_verified,
    )


def _resolve_reviewed_formal_demo_contracts(
    scenario: DemoScenarioSpec,
    profiles: Sequence[ApplicationRoleProfile],
) -> tuple[DemoScenarioSpec, tuple[ApplicationRoleProfile, ...]]:
    if not isinstance(scenario, DemoScenarioSpec):
        raise FormalDemoContractError("FORMAL_DEMO_COMPILATION_INVALID")
    if (
        not isinstance(profiles, (tuple, list))
        or not 1 <= len(profiles) <= MAX_CONTRACT_ITEMS
        or any(not isinstance(profile, ApplicationRoleProfile) for profile in profiles)
    ):
        raise FormalDemoContractError("FORMAL_DEMO_PROFILES_INVALID")
    resolved_scenario = resolve_reviewed_formal_demo_scenario(
        scenario.scenario_id,
        version=scenario.version,
        digest=scenario.content_digest,
    )
    if resolved_scenario is not scenario and resolved_scenario != scenario:
        raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_PIN_MISMATCH")
    resolved_profiles: list[ApplicationRoleProfile] = []
    for profile in profiles:
        resolved_profile = resolve_reviewed_formal_demo_profile(
            profile.profile_id,
            version=profile.version,
            digest=profile.content_digest,
        )
        if resolved_profile is not profile and resolved_profile != profile:
            raise FormalDemoContractError("FORMAL_DEMO_PROFILE_PIN_MISMATCH")
        resolved_profiles.append(resolved_profile)
    return resolved_scenario, tuple(resolved_profiles)


def compile_generic_scope_sheet(
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
    profiles: Sequence[ApplicationRoleProfile],
    *,
    resume_identity: str,
    expected_binding_digest: str | None = None,
) -> GenericScopeSheet:
    """Compile only exact Host-reviewed scenario/profile registry pins.

    Structurally valid decoded records are not reviewed records.  The private
    structural compiler is exercised only by offline contract tests; product
    callers cannot bypass these exact registry pins through this public API.
    """

    reviewed_scenario, reviewed_profiles = _resolve_reviewed_formal_demo_contracts(
        scenario,
        profiles,
    )
    return _compile_generic_scope_sheet(
        intent,
        reviewed_scenario,
        reviewed_profiles,
        resume_identity=resume_identity,
        expected_binding_digest=expected_binding_digest,
        reviewed_registry_pins_verified=True,
    )


def _scope_application_from_json(value: object) -> ScopeApplication:
    mapping = _strict_mapping(
        value,
        {
            "role",
            "profile_id",
            "profile_digest",
            "application_label",
            "adapter_id",
            "test_data_boundary",
            "reads",
            "changes",
            "output_ids",
            "fixture_ids",
        },
        code="FORMAL_DEMO_SCOPE_INVALID",
    )
    try:
        role = SemanticRole(mapping["role"])
    except (TypeError, ValueError):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID") from None
    return ScopeApplication(
        role=role,
        profile_id=_require_identifier(
            mapping["profile_id"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        profile_digest=_require_digest(
            mapping["profile_digest"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        application_label=_require_text(
            mapping["application_label"],
            limit=MAX_LABEL_CHARS,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        adapter_id=_require_identifier(
            mapping["adapter_id"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        test_data_boundary=_require_text(
            mapping["test_data_boundary"],
            limit=MAX_DESCRIPTION_CHARS,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        reads=_texts_from_json(
            mapping["reads"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        changes=_texts_from_json(
            mapping["changes"],
            minimum=0,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        output_ids=_identifiers_from_json(
            mapping["output_ids"],
            minimum=0,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        fixture_ids=_identifiers_from_json(
            mapping["fixture_ids"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
    )


def _decode_generic_scope_sheet(
    text: str,
    *,
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
    profiles: Sequence[ApplicationRoleProfile],
    resume_identity: str,
    expected_binding_digest: str,
    reviewed_registry_pins_verified: bool,
) -> GenericScopeSheet:
    """Reload bounded Scope data against a previously retained binding pin."""

    retained_binding_digest = _require_digest(
        expected_binding_digest,
        code="FORMAL_DEMO_BINDING_DIGEST_MISMATCH",
    )
    value = _parse_json_object(text, max_bytes=MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES)
    value = _strict_mapping(
        value,
        {
            "version",
            "source",
            "contains_model_prose",
            "compilation_starts_external_work",
            "grants_execution_authority",
            "reviewed_registry_pins_verified",
            "resume_identity",
            "scenario_id",
            "goal",
            "applications",
            "reads",
            "changes",
            "outputs",
            "constraints",
            "risk_ceiling",
            "budgets",
            "approvals",
            "stop_conditions",
            "possible_residue",
            "forbidden_effects",
            "digests",
            "acknowledgement",
        },
        code="FORMAL_DEMO_SCOPE_SHAPE_INVALID",
    )
    _require_version(value["version"], GENERIC_SCOPE_SHEET_VERSION)
    if (
        value["source"] != "host_compiled_from_validated_task_intent"
        or value["contains_model_prose"] is not False
        or value["compilation_starts_external_work"] is not False
        or value["grants_execution_authority"] is not False
        or value["reviewed_registry_pins_verified"]
        is not reviewed_registry_pins_verified
    ):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_AUTHORITY_INVALID")
    acknowledgement = _strict_mapping(
        value["acknowledgement"],
        {
            "interactive_token",
            "starts_bound_scope_only",
            "grants_action_approval",
            "grants_retry_or_replay",
        },
        code="FORMAL_DEMO_SCOPE_AUTHORITY_INVALID",
    )
    if (
        acknowledgement["interactive_token"] != "START"
        or not isinstance(acknowledgement["interactive_token"], str)
        or acknowledgement["starts_bound_scope_only"] is not True
        or acknowledgement["grants_action_approval"] is not False
        or acknowledgement["grants_retry_or_replay"] is not False
    ):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_AUTHORITY_INVALID")
    applications_value = value["applications"]
    if not isinstance(applications_value, list):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
    digests = _strict_mapping(
        value["digests"],
        {"task_intent", "scenario", "profiles", "binding"},
        code="FORMAL_DEMO_SCOPE_INVALID",
    )
    profile_digests = digests["profiles"]
    if not isinstance(profile_digests, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in profile_digests.items()
    ):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID")
    try:
        risk = DemoRiskCeiling(value["risk_ceiling"])
    except (TypeError, ValueError):
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_INVALID") from None
    parsed = GenericScopeSheet(
        resume_identity=_require_resume_identity(value["resume_identity"]),
        scenario_id=_require_identifier(
            value["scenario_id"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        goal=_require_text(
            value["goal"],
            limit=MAX_DESCRIPTION_CHARS,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        applications=tuple(
            _scope_application_from_json(item) for item in applications_value
        ),
        reads=_texts_from_json(
            value["reads"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        changes=_texts_from_json(
            value["changes"],
            minimum=0,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        outputs=_text_map_from_json(
            value["outputs"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        constraints=_text_map_from_json(
            value["constraints"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        risk_ceiling=risk,
        budgets=_budgets_from_json(value["budgets"]),
        approvals=_texts_from_json(
            value["approvals"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        stop_conditions=_text_map_from_json(
            value["stop_conditions"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        possible_residue=_texts_from_json(
            value["possible_residue"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        forbidden_effects=_identifiers_from_json(
            value["forbidden_effects"],
            minimum=1,
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        task_intent_digest=_require_digest(
            digests["task_intent"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        scenario_digest=_require_digest(
            digests["scenario"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        profile_digests=profile_digests,  # type: ignore[arg-type]
        binding_digest=_require_digest(
            digests["binding"],
            code="FORMAL_DEMO_SCOPE_INVALID",
        ),
        reviewed_registry_pins_verified=reviewed_registry_pins_verified,
    )
    expected = _compile_generic_scope_sheet(
        intent,
        scenario,
        profiles,
        resume_identity=resume_identity,
        expected_binding_digest=retained_binding_digest,
        reviewed_registry_pins_verified=reviewed_registry_pins_verified,
    )
    if parsed.canonical_payload() != expected.canonical_payload():
        raise FormalDemoContractError("FORMAL_DEMO_SCOPE_TAMPERED")
    return parsed


def decode_generic_scope_sheet(
    text: str,
    *,
    intent: TaskIntent,
    scenario: DemoScenarioSpec,
    profiles: Sequence[ApplicationRoleProfile],
    resume_identity: str,
    expected_binding_digest: str,
) -> GenericScopeSheet:
    """Reload Scope data against exact reviewed pins and one retained binding."""

    reviewed_scenario, reviewed_profiles = _resolve_reviewed_formal_demo_contracts(
        scenario,
        profiles,
    )
    return _decode_generic_scope_sheet(
        text,
        intent=intent,
        scenario=reviewed_scenario,
        profiles=reviewed_profiles,
        resume_identity=resume_identity,
        expected_binding_digest=expected_binding_digest,
        reviewed_registry_pins_verified=True,
    )


def resolve_reviewed_formal_demo_profile(
    profile_id: str,
    *,
    version: int,
    digest: str,
) -> ApplicationRoleProfile:
    """Resolve one exact built-in profile pin with no latest-version fallback."""

    selected_id = _require_identifier(
        profile_id,
        code="FORMAL_DEMO_PROFILE_PIN_MISMATCH",
    )
    _require_version(version, APPLICATION_ROLE_PROFILE_VERSION)
    selected_digest = _require_digest(
        digest,
        code="FORMAL_DEMO_PROFILE_PIN_MISMATCH",
    )
    profile = FORMAL_DEMO_V1_ROLE_PROFILES_BY_ID.get(selected_id)
    if (
        profile is None
        or profile.version != version
        or profile.content_digest != selected_digest
    ):
        raise FormalDemoContractError("FORMAL_DEMO_PROFILE_PIN_MISMATCH")
    return profile


def resolve_reviewed_formal_demo_scenario(
    scenario_id: str,
    *,
    version: int,
    digest: str,
) -> DemoScenarioSpec:
    """Resolve the exact built-in scenario pin with no version fallback."""

    selected_id = _require_identifier(
        scenario_id,
        code="FORMAL_DEMO_SCENARIO_PIN_MISMATCH",
    )
    _require_version(version, DEMO_SCENARIO_SPEC_VERSION)
    selected_digest = _require_digest(
        digest,
        code="FORMAL_DEMO_SCENARIO_PIN_MISMATCH",
    )
    scenario = FORMAL_DEMO_V1_SCENARIOS_BY_ID.get(selected_id)
    if (
        scenario is None
        or scenario.version != version
        or scenario.content_digest != selected_digest
    ):
        raise FormalDemoContractError("FORMAL_DEMO_SCENARIO_PIN_MISMATCH")
    return scenario


FORMAL_DEMO_V1_SCENARIO = DemoScenarioSpec(
    scenario_id="formal_demo_v1",
    outcomes={
        "verified_analysis_report_and_draft": (
            "Review dedicated issue and PDF fixtures, create verified disposable "
            "analysis and report artifacts, and prepare a verified unsent test-account draft."
        )
    },
    allowed_roles=tuple(SemanticRole),
    required_roles=tuple(SemanticRole),
    outputs={
        "email_draft": "One verified unsent draft in a dedicated test account.",
        "excel_analysis": "One disposable workbook saved, reopened, and verified.",
        "word_report": "One disposable document saved, reopened, and read back.",
    },
    required_outputs=("excel_analysis", "word_report", "email_draft"),
    constraints={
        "cleanup_required": "Cleanup is verified or any residue is reported.",
        "create_new_only": "Disposable outputs are created without overwriting existing data.",
        "email_draft_only": "Email remains an unsent test-account draft.",
        "fixture_only": "Reads and changes remain inside dedicated non-sensitive fixtures.",
        "verify_reopen": "Every output is reopened and verified before success.",
    },
    required_constraints=(
        "cleanup_required",
        "create_new_only",
        "email_draft_only",
        "fixture_only",
        "verify_reopen",
    ),
    budget_ceilings=DemoBudgets(
        provider_calls=12,
        tool_calls=128,
        side_effects=24,
        retries=8,
        artifacts=3,
    ),
    fixtures={
        "excel_disposable_v1": "A new disposable workbook boundary; no user workbook.",
        "github_issues_fixture_v1": "Dedicated stable public issue identities and bounded fields.",
        "pdf_evidence_fixture_v1": "Versioned non-sensitive PDF evidence fixture.",
        "test_email_boundary_v1": "Dedicated test account and fixed recipient boundary.",
        "word_disposable_v1": "A new disposable document boundary; no user document.",
    },
    risk_ceiling=DemoRiskCeiling.DRAFT,
    forbidden_effects=(
        "arbitrary_file_access",
        "email_forward",
        "email_schedule",
        "email_send",
        "external_delivery",
        "github_close",
        "github_comment",
        "github_write",
        "overwrite_existing",
    ),
)


FORMAL_DEMO_V1_ROLE_PROFILES = (
    ApplicationRoleProfile(
        profile_id="formal_source_github_v1",
        role=SemanticRole.SOURCE,
        application_label="Dedicated GitHub Issues fixture",
        adapter_id="github_issues_fixture",
        binding_state=ProfileBindingState.SELECTED,
        test_data_boundary="Stable fixture issue identities, labels, and bounded public fields only.",
        reads=("Read bounded stable issue identities, labels, titles, and descriptions.",),
        changes=(),
        output_ids=(),
        fixture_ids=("github_issues_fixture_v1",),
        risk_ceiling=DemoRiskCeiling.READ_ONLY,
        forbidden_effects=("github_close", "github_comment", "github_write"),
    ),
    ApplicationRoleProfile(
        profile_id="formal_evidence_pdf_v1",
        role=SemanticRole.EVIDENCE,
        application_label="Versioned non-sensitive PDF fixture",
        adapter_id="pdf_fixture",
        binding_state=ProfileBindingState.SELECTED,
        test_data_boundary="One exact versioned PDF fixture and its verified citation locations only.",
        reads=("Read bounded document text and separately allowed OCR evidence.",),
        changes=(),
        output_ids=(),
        fixture_ids=("pdf_evidence_fixture_v1",),
        risk_ceiling=DemoRiskCeiling.READ_ONLY,
        forbidden_effects=("arbitrary_file_access",),
    ),
    ApplicationRoleProfile(
        profile_id="formal_analysis_excel_v1",
        role=SemanticRole.ANALYSIS,
        application_label="Disposable Excel workbook",
        adapter_id="excel_disposable",
        binding_state=ProfileBindingState.SELECTED,
        test_data_boundary="One new workbook with exact reviewed sheet and range identities.",
        reads=("Read only verified source and evidence values admitted by the scenario.",),
        changes=("Create, save, reopen, and verify one disposable workbook.",),
        output_ids=("excel_analysis",),
        fixture_ids=("excel_disposable_v1",),
        risk_ceiling=DemoRiskCeiling.DRAFT,
        forbidden_effects=("overwrite_existing",),
    ),
    ApplicationRoleProfile(
        profile_id="formal_report_word_v1",
        role=SemanticRole.REPORT,
        application_label="Disposable Word document",
        adapter_id="word_disposable",
        binding_state=ProfileBindingState.SELECTED,
        test_data_boundary="One new document at a future exact reviewed output identity.",
        reads=("Read only the verified analysis and source citations admitted by the scenario.",),
        changes=("Create, save, reopen, and read back one disposable report.",),
        output_ids=("word_report",),
        fixture_ids=("word_disposable_v1",),
        risk_ceiling=DemoRiskCeiling.DRAFT,
        forbidden_effects=("overwrite_existing",),
    ),
    ApplicationRoleProfile(
        profile_id="formal_handoff_email_v1",
        role=SemanticRole.HANDOFF,
        application_label="Dedicated test-account email draft",
        adapter_id=None,
        binding_state=ProfileBindingState.UNSELECTED,
        test_data_boundary=(
            "A future exact email adapter, test account, fixed recipient, and attachment boundary."
        ),
        reads=("Read only the verified report and attachment identity admitted by the scenario.",),
        changes=("Prepare, reopen, verify, and clean up one unsent test-account draft.",),
        output_ids=("email_draft",),
        fixture_ids=("test_email_boundary_v1",),
        risk_ceiling=DemoRiskCeiling.DRAFT,
        forbidden_effects=(
            "email_forward",
            "email_schedule",
            "email_send",
            "external_delivery",
        ),
    ),
)

FORMAL_DEMO_V1_ROLE_PROFILES_BY_ID: Mapping[str, ApplicationRoleProfile] = (
    MappingProxyType(
        {profile.profile_id: profile for profile in FORMAL_DEMO_V1_ROLE_PROFILES}
    )
)

FORMAL_DEMO_V1_SCENARIOS_BY_ID: Mapping[str, DemoScenarioSpec] = MappingProxyType(
    {FORMAL_DEMO_V1_SCENARIO.scenario_id: FORMAL_DEMO_V1_SCENARIO}
)


__all__ = [
    "APPLICATION_ROLE_PROFILE_VERSION",
    "DEMO_SCENARIO_SPEC_VERSION",
    "FORMAL_DEMO_V1_ROLE_PROFILES",
    "FORMAL_DEMO_V1_ROLE_PROFILES_BY_ID",
    "FORMAL_DEMO_V1_SCENARIO",
    "FORMAL_DEMO_V1_SCENARIOS_BY_ID",
    "GENERIC_SCOPE_SHEET_VERSION",
    "MAX_FORMAL_DEMO_CONTRACT_JSON_BYTES",
    "MAX_SOURCE_TASK_BYTES",
    "MAX_TASK_INTENT_JSON_BYTES",
    "TASK_INTENT_VERSION",
    "ApplicationRoleProfile",
    "DemoBudgets",
    "DemoRiskCeiling",
    "DemoScenarioSpec",
    "FormalDemoContractError",
    "GenericScopeSheet",
    "ProfileBindingState",
    "ScopeApplication",
    "SemanticRole",
    "TaskIntent",
    "compile_generic_scope_sheet",
    "decode_application_role_profile",
    "decode_demo_scenario_spec",
    "decode_generic_scope_sheet",
    "decode_task_intent",
    "decode_task_intent_artifact",
    "resolve_reviewed_formal_demo_profile",
    "resolve_reviewed_formal_demo_scenario",
]
