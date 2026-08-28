"""Host-owned no-key compiler for one reviewed Formal Demo Scope.

This module is deliberately smaller than an intent-provider adapter.  It maps
one already reviewed local disclosure to the single built-in Formal Demo
scenario, consumes the issuing process-local ``COMPILE`` permit once, and
returns a digest-bound Scope Sheet.  Free-form task text binds identity only;
it cannot select roles, outputs, constraints, budgets, adapters, or authority.

There is no provider, configuration, credential, environment, network,
filesystem, persistence, Runner, MCP, Driver, desktop, application, ``START``,
retry, replay, or fallback port here.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Never, SupportsIndex

from .formal_demo_contract import (
    FORMAL_DEMO_V1_ROLE_PROFILES,
    FORMAL_DEMO_V1_SCENARIO,
    ApplicationRoleProfile,
    DemoBudgets,
    DemoScenarioSpec,
    FormalDemoContractError,
    GenericScopeSheet,
    ProfileBindingState,
    TaskIntent,
    compile_generic_scope_sheet,
    decode_generic_scope_sheet,
    resolve_reviewed_formal_demo_profile,
    resolve_reviewed_formal_demo_scenario,
    validate_task_intent_for_reviewed_scenario,
)
from .formal_demo_intent_gate import (
    FormalDemoIntentDisclosure,
    FormalDemoIntentGateError,
    IntentCompileConsumption,
    IntentCompileGate,
    IntentCompilePermit,
)


LOCAL_SCOPE_COMPILER_VERSION = 1
LOCAL_SCOPE_COMPILER_ID = "formal_demo_host_fixed_scope_v1"
LOCAL_SCOPE_OUTCOME_ID = "verified_analysis_report_and_draft"

# These are intended-run ceilings shown for review, not resources opened by
# compilation.  The local slice cannot call a provider and grants no retry.
LOCAL_SCOPE_BUDGETS = DemoBudgets(
    provider_calls=0,
    tool_calls=FORMAL_DEMO_V1_SCENARIO.budget_ceilings.tool_calls,
    side_effects=FORMAL_DEMO_V1_SCENARIO.budget_ceilings.side_effects,
    retries=0,
    artifacts=FORMAL_DEMO_V1_SCENARIO.budget_ceilings.artifacts,
)


class FormalDemoLocalScopeError(ValueError):
    """Fixed, content-free failure at the local Scope compiler boundary."""


def _reviewed_contract_snapshots() -> tuple[
    DemoScenarioSpec,
    tuple[ApplicationRoleProfile, ...],
]:
    """Resolve exact current registry pins without a latest-version fallback."""

    scenario = resolve_reviewed_formal_demo_scenario(
        FORMAL_DEMO_V1_SCENARIO.scenario_id,
        version=FORMAL_DEMO_V1_SCENARIO.version,
        digest=FORMAL_DEMO_V1_SCENARIO.content_digest,
    )
    profiles = tuple(
        resolve_reviewed_formal_demo_profile(
            profile.profile_id,
            version=profile.version,
            digest=profile.content_digest,
        )
        for profile in FORMAL_DEMO_V1_ROLE_PROFILES
    )
    if (
        tuple(profile.role for profile in profiles) != scenario.required_roles
        or any(
            profile.binding_state is not ProfileBindingState.SELECTED
            for profile in profiles
        )
        or tuple(scenario.outcomes) != (LOCAL_SCOPE_OUTCOME_ID,)
    ):
        raise FormalDemoLocalScopeError(
            "FORMAL_DEMO_LOCAL_SCOPE_REGISTRY_INVALID"
        )
    return scenario, profiles


def _local_intent(
    *,
    source_task_digest: str,
    scenario: DemoScenarioSpec,
) -> TaskIntent:
    """Build the one fixed intent envelope; source text cannot widen it."""

    return TaskIntent(
        source_task_digest=source_task_digest,
        scenario_id=scenario.scenario_id,
        outcome_id=LOCAL_SCOPE_OUTCOME_ID,
        requested_roles=scenario.required_roles,
        requested_outputs=scenario.required_outputs,
        constraint_ids=scenario.required_constraints,
        risk_ceiling=scenario.risk_ceiling,
        budgets=LOCAL_SCOPE_BUDGETS,
    )


def _verified_consumption_snapshot(
    consumption: object,
) -> IntentCompileConsumption:
    """Rebuild one content-free receipt before binding or displaying it."""

    if type(consumption) is not IntentCompileConsumption:
        raise FormalDemoLocalScopeError(
            "FORMAL_DEMO_LOCAL_SCOPE_RESULT_INVALID"
        )
    try:
        return IntentCompileConsumption(
            permit_digest=consumption.permit_digest,
            disclosure_digest=consumption.disclosure_digest,
            resume_identity=consumption.resume_identity,
            source_task_digest=consumption.source_task_digest,
            route_digest=consumption.route_digest,
            profile_digest=consumption.profile_digest,
            state=consumption.state,
            provider_request_started=consumption.provider_request_started,
            grants_execution_authority=consumption.grants_execution_authority,
            grants_retry_or_replay=consumption.grants_retry_or_replay,
        )
    except FormalDemoIntentGateError:
        raise FormalDemoLocalScopeError(
            "FORMAL_DEMO_LOCAL_SCOPE_RESULT_INVALID"
        ) from None


def _consumption_digest(consumption: object) -> str:
    """Bind the local receipt without retaining task or provider prose."""

    snapshot = _verified_consumption_snapshot(consumption)
    payload = {
        "disclosure_digest": snapshot.disclosure_digest,
        "grants_execution_authority": snapshot.grants_execution_authority,
        "grants_retry_or_replay": snapshot.grants_retry_or_replay,
        "permit_digest": snapshot.permit_digest,
        "profile_digest": snapshot.profile_digest,
        "provider_request_started": snapshot.provider_request_started,
        "resume_identity": snapshot.resume_identity,
        "route_digest": snapshot.route_digest,
        "source_task_digest": snapshot.source_task_digest,
        "state": snapshot.state.value,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(
        b"formal-demo-local-scope-consumption-v1\x00" + canonical
    ).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True, repr=False)
class LocalScopeCompilation:
    """Content-free local receipt plus a non-authoritative reviewed Scope."""

    intent: TaskIntent
    scope: GenericScopeSheet
    consumption: IntentCompileConsumption
    consumption_digest: str
    compiler_id: str = LOCAL_SCOPE_COMPILER_ID
    external_work_started: bool = False
    provider_request_started: bool = False
    start_available: bool = False
    grants_execution_authority: bool = False
    grants_retry_or_replay: bool = False
    version: int = LOCAL_SCOPE_COMPILER_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.version) is not int
            or self.version != LOCAL_SCOPE_COMPILER_VERSION
            or self.compiler_id != LOCAL_SCOPE_COMPILER_ID
            or type(self.intent) is not TaskIntent
            or type(self.scope) is not GenericScopeSheet
            or type(self.consumption) is not IntentCompileConsumption
            or not _is_digest(self.consumption_digest)
            or self.consumption_digest
            != _consumption_digest(self.consumption)
            or self.external_work_started is not False
            or self.provider_request_started is not False
            or self.start_available is not False
            or self.grants_execution_authority is not False
            or self.grants_retry_or_replay is not False
            or self.intent.source_task_digest
            != self.consumption.source_task_digest
            or self.scope.resume_identity != self.consumption.resume_identity
            or self.scope.task_intent_digest != self.intent.content_digest
            or self.scope.scenario_id != self.intent.scenario_id
            or self.scope.reviewed_registry_pins_verified is not True
            or self.intent.budgets.provider_calls != 0
            or self.intent.budgets.retries != 0
        ):
            raise FormalDemoLocalScopeError(
                "FORMAL_DEMO_LOCAL_SCOPE_RESULT_INVALID"
            )

    def __repr__(self) -> str:
        return "<LocalScopeCompilation reviewed-no-authority>"

    def __copy__(self) -> Never:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_OPAQUE")

    def __deepcopy__(self, _memo: object) -> Never:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_OPAQUE")

    def __reduce__(self) -> Never:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_OPAQUE")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> Never:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_OPAQUE")


def compile_local_scope_once(
    *,
    gate: IntentCompileGate,
    permit: IntentCompilePermit,
    current_disclosure: FormalDemoIntentDisclosure,
) -> LocalScopeCompilation:
    """Consume one exact permit and compile only the built-in reviewed Scope.

    The product path accepts no scenario, profile, budget, output, constraint,
    or adapter arguments.  There is therefore no caller-controlled registry
    fallback and no way for free-form task text to expand the reviewed scope.
    """

    if type(gate) is not IntentCompileGate:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_GATE_INVALID")
    result: LocalScopeCompilation | None = None
    try:
        scenario, profiles = _reviewed_contract_snapshots()
        consumption = gate.consume(
            permit,
            current_disclosure=current_disclosure,
        )
        intent = _local_intent(
            source_task_digest=consumption.source_task_digest,
            scenario=scenario,
        )
        scope = compile_generic_scope_sheet(
            intent,
            scenario,
            profiles,
            resume_identity=consumption.resume_identity,
        )
        result = LocalScopeCompilation(
            intent=intent,
            scope=scope,
            consumption=consumption,
            consumption_digest=_consumption_digest(consumption),
        )
    except (FormalDemoContractError, FormalDemoIntentGateError, FormalDemoLocalScopeError):
        raise
    except Exception:
        pass
    if result is None:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_FAILED")
    return result


def _verified_result_snapshot(result: object) -> LocalScopeCompilation:
    """Rebuild every public field so frozen-object tamper fails before display."""

    if type(result) is not LocalScopeCompilation:
        raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_RESULT_INVALID")
    try:
        scenario, profiles = _reviewed_contract_snapshots()
        consumption_snapshot = _verified_consumption_snapshot(
            result.consumption
        )
        intent = validate_task_intent_for_reviewed_scenario(
            result.intent,
            scenario,
        )
        expected_intent = _local_intent(
            source_task_digest=consumption_snapshot.source_task_digest,
            scenario=scenario,
        )
        if intent.canonical_payload() != expected_intent.canonical_payload():
            raise FormalDemoLocalScopeError(
                "FORMAL_DEMO_LOCAL_SCOPE_RESULT_INVALID"
            )
        scope = decode_generic_scope_sheet(
            result.scope.canonical_json(),
            intent=intent,
            scenario=scenario,
            profiles=profiles,
            resume_identity=consumption_snapshot.resume_identity,
            expected_binding_digest=result.scope.binding_digest,
        )
        return LocalScopeCompilation(
            intent=intent,
            scope=scope,
            consumption=consumption_snapshot,
            consumption_digest=result.consumption_digest,
            compiler_id=result.compiler_id,
            external_work_started=result.external_work_started,
            provider_request_started=result.provider_request_started,
            start_available=result.start_available,
            grants_execution_authority=result.grants_execution_authority,
            grants_retry_or_replay=result.grants_retry_or_replay,
            version=result.version,
        )
    except (FormalDemoContractError, FormalDemoIntentGateError, FormalDemoLocalScopeError):
        raise
    except Exception:
        pass
    raise FormalDemoLocalScopeError("FORMAL_DEMO_LOCAL_SCOPE_RESULT_INVALID")


def render_local_scope_review(result: LocalScopeCompilation) -> str:
    """Render one bounded human review without raw task text or authority."""

    snapshot = _verified_result_snapshot(result)
    scope = snapshot.scope
    applications = "\n".join(
        (
            f"- {item.role.value}: {item.application_label} "
            f"[profile={item.profile_id}; adapter design={item.adapter_id}]"
        )
        for item in scope.applications
    )
    reads = "\n".join(f"- {item}" for item in scope.reads)
    changes = "\n".join(f"- {item}" for item in scope.changes)
    outputs = "\n".join(
        f"- {output_id}: {description}"
        for output_id, description in scope.outputs.items()
    )
    constraints = "\n".join(
        f"- {constraint_id}: {description}"
        for constraint_id, description in scope.constraints.items()
    )
    approvals = "\n".join(f"- {item}" for item in scope.approvals)
    stops = "\n".join(
        f"- {stop_id}: {description}"
        for stop_id, description in scope.stop_conditions.items()
    )
    residue = "\n".join(f"- {item}" for item in scope.possible_residue)
    forbidden = "\n".join(f"- {item}" for item in scope.forbidden_effects)
    budgets = scope.budgets.canonical_payload()
    return "\n".join(
        (
            "Formal Demo Scope Sheet - Host compiled locally",
            f"Compiler: {snapshot.compiler_id}",
            "Free-form interpretation: no; exact task text binds identity only.",
            "Reviewed registry pins: verified.",
            "External work started: no.",
            "Provider request started: no.",
            "Execution authority granted: no.",
            f"Draft identity: {scope.resume_identity}",
            f"Scenario: {scope.scenario_id}",
            f"Goal: {scope.goal}",
            "",
            "Applications (design bindings only; readiness unchecked):",
            applications,
            "",
            "Reads:",
            reads,
            "",
            "Changes:",
            changes,
            "",
            "Outputs:",
            outputs,
            "",
            "Constraints:",
            constraints,
            "",
            f"Risk ceiling: {scope.risk_ceiling.value}",
            (
                "Budgets: provider_calls={provider_calls}, tool_calls={tool_calls}, "
                "side_effects={side_effects}, retries={retries}, artifacts={artifacts}"
            ).format(**budgets),
            "",
            "Approvals:",
            approvals,
            "",
            "Stop conditions:",
            stops,
            "",
            "Possible residue:",
            residue,
            "",
            "Forbidden effects:",
            forbidden,
            "",
            f"TaskIntent digest: {scope.task_intent_digest}",
            f"Scenario digest: {scope.scenario_digest}",
            f"Binding digest: {scope.binding_digest}",
            f"Consumption digest: {snapshot.consumption_digest}",
            "START: unavailable in this slice; the native button remains disabled.",
            "No Runner, MCP, Driver, desktop, application, or durable run has started.",
        )
    ) + "\n"


__all__ = [
    "LOCAL_SCOPE_BUDGETS",
    "LOCAL_SCOPE_COMPILER_ID",
    "LOCAL_SCOPE_COMPILER_VERSION",
    "FormalDemoLocalScopeError",
    "LocalScopeCompilation",
    "compile_local_scope_once",
    "render_local_scope_review",
]
