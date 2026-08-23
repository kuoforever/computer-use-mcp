from __future__ import annotations

import ast
import asyncio
import copy
import json
import pickle
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import Callable

import pytest

import computer_use_agent.formal_demo_intent_request as request_module
from computer_use_agent.formal_demo_contract import (
    FORMAL_DEMO_V1_SCENARIO,
    MAX_TASK_INTENT_JSON_BYTES,
    TASK_INTENT_VERSION,
    DemoRiskCeiling,
    DemoScenarioSpec,
    FormalDemoContractError,
    SemanticRole,
)
from computer_use_agent.formal_demo_intent_gate import (
    INTENT_COMPILE_TOKEN,
    FormalDemoIntentDisclosure,
    FormalDemoIntentGateError,
    IntentCompileGate,
    IntentCompileGateState,
    IntentCompilePermit,
    ProviderIntentRoute,
    ProviderProtocol,
    ReviewedIntentDisclosureProfile,
    compile_intent_disclosure,
    resolve_reviewed_intent_disclosure_profile,
    reviewed_intent_disclosure_profiles,
)
from computer_use_agent.formal_demo_intent_request import (
    FormalDemoIntentRequestError,
    IntentCandidateAttempt,
    IntentCandidateRequest,
    IntentCandidateResponse,
    IntentCandidateStatus,
    compile_task_intent_once,
)


SOURCE_TASK = "Create fixture-grounded analysis, a report, and an unsent draft."
DISCLOSURE_ID = "formal-demo-draft-007c"
RESUME_IDENTITY = "formal-demo-review-007c"


def _route() -> ProviderIntentRoute:
    return ProviderIntentRoute(
        provider_id="openai",
        region="global",
        model_id="gpt-reviewed",
        protocol=ProviderProtocol.OPENAI_RESPONSES,
        endpoint="https://api.openai.com/v1",
    )


def _profile() -> ReviewedIntentDisclosureProfile:
    selected = next(
        profile
        for profile in reviewed_intent_disclosure_profiles()
        if profile.provider_id == "openai"
    )
    return resolve_reviewed_intent_disclosure_profile(
        selected.profile_id,
        version=selected.version,
        expected_digest=selected.content_digest,
    )


def _disclosure(
    *,
    source_task: str = SOURCE_TASK,
    disclosure_id: str = DISCLOSURE_ID,
    resume_identity: str = RESUME_IDENTITY,
) -> FormalDemoIntentDisclosure:
    profile = _profile()
    return compile_intent_disclosure(
        disclosure_id=disclosure_id,
        resume_identity=resume_identity,
        source_task=source_task,
        route=_route(),
        profile_id=profile.profile_id,
        profile_version=profile.version,
        expected_profile_digest=profile.content_digest,
    )


def _candidate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": TASK_INTENT_VERSION,
        "scenario_id": FORMAL_DEMO_V1_SCENARIO.scenario_id,
        "outcome_id": "verified_analysis_report_and_draft",
        "requested_roles": [role.value for role in SemanticRole],
        "requested_outputs": ["excel_analysis", "word_report", "email_draft"],
        "constraint_ids": [
            "cleanup_required",
            "create_new_only",
            "email_draft_only",
            "fixture_only",
            "verify_reopen",
        ],
        "risk_ceiling": "draft",
        "budgets": {
            "provider_calls": 10,
            "tool_calls": 100,
            "side_effects": 20,
            "retries": 4,
            "artifacts": 3,
        },
    }
    payload.update(overrides)
    return payload


def _completed_candidate(**overrides: object) -> IntentCandidateResponse:
    return IntentCandidateResponse(
        status=IntentCandidateStatus.COMPLETED,
        candidate=json.dumps(_candidate_payload(**overrides)),
    )


ScriptItem = (
    IntentCandidateResponse
    | BaseException
    | object
    | Callable[[IntentCandidateRequest], object]
)


class ScriptedIntentPort:
    def __init__(self, *script: ScriptItem) -> None:
        self._script = list(script)
        self._lock = Lock()
        self.calls: list[IntentCandidateRequest] = []

    def create_candidate(self, request: IntentCandidateRequest) -> object:
        with self._lock:
            self.calls.append(request)
            if not self._script:
                raise AssertionError("unexpected extra fake call")
            item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request)
        return item


def _gate_and_permit(
    disclosure: FormalDemoIntentDisclosure | None = None,
) -> tuple[FormalDemoIntentDisclosure, IntentCompileGate, IntentCompilePermit]:
    selected = _disclosure() if disclosure is None else disclosure
    gate = IntentCompileGate(selected)
    permit = gate.acknowledge(INTENT_COMPILE_TOKEN)
    return selected, gate, permit


def _compile(
    *,
    disclosure: FormalDemoIntentDisclosure,
    gate: IntentCompileGate,
    permit: IntentCompilePermit,
    port: object,
    current_disclosure: FormalDemoIntentDisclosure | None = None,
    scenario: DemoScenarioSpec = FORMAL_DEMO_V1_SCENARIO,
) -> IntentCandidateAttempt:
    return compile_task_intent_once(
        gate=gate,
        permit=permit,
        current_disclosure=(
            disclosure if current_disclosure is None else current_disclosure
        ),
        scenario=scenario,
        port=port,  # type: ignore[arg-type]
    )


def test_gate_is_consumed_before_one_fake_call_and_result_is_non_authoritative() -> None:
    disclosure, gate, permit = _gate_and_permit()

    def observe(request: IntentCandidateRequest) -> IntentCandidateResponse:
        assert gate.state is IntentCompileGateState.CONSUMED
        assert request.source_task == SOURCE_TASK
        assert request.source_task_digest == disclosure.source_task_digest
        assert request.disclosure_digest == disclosure.content_digest
        assert request.route.content_digest == disclosure.route.content_digest
        assert request.scenario_digest == FORMAL_DEMO_V1_SCENARIO.content_digest
        assert request.request_limit == 1
        assert request.tools_allowed is False
        assert request.automatic_retry is False
        assert request.bound_payload()["contains_credential_value"] is False
        assert SOURCE_TASK not in json.dumps(request.bound_payload())
        return _completed_candidate()

    port = ScriptedIntentPort(observe)
    result = _compile(
        disclosure=disclosure,
        gate=gate,
        permit=permit,
        port=port,
    )

    assert len(port.calls) == 1
    assert result.intent.scenario_id == FORMAL_DEMO_V1_SCENARIO.scenario_id
    assert result.intent.source_task_digest == disclosure.source_task_digest
    assert result.consumption.provider_request_started is False
    assert result.port_calls == 1
    assert result.tools_allowed is False
    assert result.automatic_retry is False
    assert result.grants_execution_authority is False
    assert SOURCE_TASK not in repr(result)


def test_invalid_scenario_pin_fails_preflight_without_consuming() -> None:
    disclosure, gate, permit = _gate_and_permit()
    tampered_scenario = replace(
        FORMAL_DEMO_V1_SCENARIO,
        outcomes={
            **FORMAL_DEMO_V1_SCENARIO.outcomes,
            "attacker_outcome": "Attacker-selected outcome.",
        },
    )
    port = ScriptedIntentPort(_completed_candidate())
    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_SCENARIO_INVALID$",
    ):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
            scenario=tampered_scenario,
        )
    assert gate.state is IntentCompileGateState.PERMITTED
    assert port.calls == []


def test_invalid_port_is_checked_only_after_terminal_consumption() -> None:
    disclosure, gate, permit = _gate_and_permit()
    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_PORT_INVALID$",
    ) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=object(),
        )
    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED


def test_port_descriptor_is_not_entered_until_after_consumption() -> None:
    disclosure, gate, permit = _gate_and_permit()

    class DescriptorPort:
        def __init__(self) -> None:
            self.lookups = 0
            self.calls = 0

        @property
        def create_candidate(
            self,
        ) -> Callable[[IntentCandidateRequest], IntentCandidateResponse]:
            self.lookups += 1
            assert gate.state is IntentCompileGateState.CONSUMED

            def complete(_request: IntentCandidateRequest) -> IntentCandidateResponse:
                self.calls += 1
                return _completed_candidate()

            return complete

    port = DescriptorPort()
    result = _compile(
        disclosure=disclosure,
        gate=gate,
        permit=permit,
        port=port,
    )

    assert isinstance(result, IntentCandidateAttempt)
    assert port.lookups == 1
    assert port.calls == 1


def test_binding_drift_or_cross_gate_permit_cancels_before_fake_call() -> None:
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(_completed_candidate())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
            current_disclosure=_disclosure(source_task=SOURCE_TASK + " changed"),
        )
    assert gate.state is IntentCompileGateState.CANCELLED
    assert port.calls == []

    second_disclosure, second_gate, _second_permit = _gate_and_permit()
    third_disclosure, _third_gate, third_permit = _gate_and_permit()
    third_port = ScriptedIntentPort(_completed_candidate())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ):
        _compile(
            disclosure=second_disclosure,
            gate=second_gate,
            permit=third_permit,
            port=third_port,
            current_disclosure=second_disclosure,
        )
    assert second_gate.state is IntentCompileGateState.CANCELLED
    assert third_disclosure.content_digest == second_disclosure.content_digest
    assert third_port.calls == []


def test_tampered_disclosure_failure_has_no_raw_exception_context() -> None:
    disclosure, gate, permit = _gate_and_permit()
    object.__setattr__(
        disclosure,
        "source_task",
        "SECRET_TAMPERED_TASK_\ud800",
    )
    port = ScriptedIntentPort(_completed_candidate())

    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )

    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CANCELLED
    assert port.calls == []


def test_wrong_disclosure_type_is_rejected_without_entering_its_properties() -> None:
    disclosure, gate, permit = _gate_and_permit()

    class ExplosiveDisclosure:
        property_reads = 0

        @property
        def source_task(self) -> str:
            self.property_reads += 1
            raise RuntimeError("SECRET_DISCLOSURE_PROPERTY")

    current = ExplosiveDisclosure()
    port = ScriptedIntentPort(_completed_candidate())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_PERMIT_MISMATCH$",
    ) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
            current_disclosure=current,  # type: ignore[arg-type]
        )

    assert caught.value.__context__ is None
    assert current.property_reads == 0
    assert gate.state is IntentCompileGateState.CANCELLED
    assert port.calls == []


@pytest.mark.parametrize(
    ("terminal", "expected"),
    (
        (
            IntentCandidateResponse(status=IntentCandidateStatus.REFUSED),
            "FORMAL_DEMO_INTENT_CANDIDATE_REFUSED",
        ),
        (
            IntentCandidateResponse(status=IntentCandidateStatus.TRUNCATED),
            "FORMAL_DEMO_INTENT_CANDIDATE_TRUNCATED",
        ),
        (
            RuntimeError("SECRET_PROVIDER_FAILURE"),
            "FORMAL_DEMO_INTENT_PORT_FAILED",
        ),
    ),
)
def test_terminal_port_outcomes_are_content_free_and_never_retried(
    terminal: ScriptItem,
    expected: str,
) -> None:
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(terminal, _completed_candidate())

    try:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )
    except (FormalDemoIntentRequestError, FormalDemoIntentGateError) as exc:
        assert str(exc) == expected
        assert "SECRET_PROVIDER_FAILURE" not in "".join(traceback.format_exception(exc))
        assert exc.__context__ is None
        assert exc.__cause__ is None
    else:
        raise AssertionError("terminal fake outcome unexpectedly succeeded")

    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1
    retry_port = ScriptedIntentPort(_completed_candidate())
    with pytest.raises(
        FormalDemoIntentGateError,
        match="^FORMAL_DEMO_INTENT_GATE_TERMINAL$",
    ):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=retry_port,
        )
    assert retry_port.calls == []


INVALID_CANDIDATES = (
    ("{}", "FORMAL_DEMO_INTENT_SHAPE_INVALID"),
    ('{"version":1,"version":1}', "FORMAL_DEMO_JSON_DUPLICATE_KEY"),
    (
        json.dumps({**_candidate_payload(), "tools": []}),
        "FORMAL_DEMO_INTENT_SHAPE_INVALID",
    ),
    (json.dumps(_candidate_payload(version=2)), "FORMAL_DEMO_VERSION_UNSUPPORTED"),
    (
        json.dumps(_candidate_payload(requested_roles=["source", "attacker"])),
        "FORMAL_DEMO_INTENT_ROLES_INVALID",
    ),
    (
        json.dumps(
            _candidate_payload(
                requested_roles=[
                    "source",
                    "evidence",
                    "analysis",
                    "report",
                ]
            )
        ),
        "FORMAL_DEMO_SCOPE_EXPANSION",
    ),
    (
        json.dumps(
            _candidate_payload(
                requested_outputs=[
                    "excel_analysis",
                    "word_report",
                    "email_draft",
                    "unknown_output",
                ]
            )
        ),
        "FORMAL_DEMO_SCOPE_EXPANSION",
    ),
    (
        json.dumps(
            _candidate_payload(
                budgets={
                    **_candidate_payload()["budgets"],  # type: ignore[dict-item]
                    "tool_calls": 129,
                }
            )
        ),
        "FORMAL_DEMO_BUDGET_EXCEEDED",
    ),
    (" " * (MAX_TASK_INTENT_JSON_BYTES + 1), "FORMAL_DEMO_JSON_TOO_LARGE"),
)


@pytest.mark.parametrize(("candidate", "expected"), INVALID_CANDIDATES)
def test_untrusted_candidate_matrix_fails_after_exactly_one_call(
    candidate: str,
    expected: str,
) -> None:
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(
        IntentCandidateResponse(
            status=IntentCandidateStatus.COMPLETED,
            candidate=candidate,
        )
    )
    with pytest.raises(FormalDemoContractError, match=f"^{expected}$"):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


def test_malformed_candidate_error_has_no_raw_json_exception_context() -> None:
    raw_candidate = "SECRET_RAW_CANDIDATE:["
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(
        IntentCandidateResponse(
            status=IntentCandidateStatus.COMPLETED,
            candidate=raw_candidate,
        )
    )

    with pytest.raises(
        FormalDemoContractError,
        match="^FORMAL_DEMO_JSON_INVALID$",
    ) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )

    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert raw_candidate not in "".join(traceback.format_exception(caught.value))
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


@pytest.mark.parametrize("response_kind", ("wrong_type", "tampered_status", "contradictory"))
def test_wrong_or_tampered_response_envelope_fails_closed(response_kind: str) -> None:
    response: object
    if response_kind == "wrong_type":
        response = object()
    elif response_kind == "tampered_status":
        response = _completed_candidate()
        object.__setattr__(response, "status", "completed")
    else:
        response = IntentCandidateResponse(status=IntentCandidateStatus.REFUSED)
        object.__setattr__(response, "candidate", "SECRET_CANDIDATE")

    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(response)
    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_RESPONSE_INVALID$",
    ):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


def test_request_tamper_during_fake_call_is_terminal_and_rejected() -> None:
    disclosure, gate, permit = _gate_and_permit()

    def mutate(request: IntentCandidateRequest) -> IntentCandidateResponse:
        object.__setattr__(request, "source_task", "tampered after consumption")
        return _completed_candidate()

    port = ScriptedIntentPort(mutate)
    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_REQUEST_STALE$",
    ):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


def test_reviewed_scenario_mutation_during_call_fails_closed() -> None:
    disclosure, gate, permit = _gate_and_permit()
    original_risk = FORMAL_DEMO_V1_SCENARIO.risk_ceiling

    def mutate_scenario(
        _request: IntentCandidateRequest,
    ) -> IntentCandidateResponse:
        object.__setattr__(
            FORMAL_DEMO_V1_SCENARIO,
            "risk_ceiling",
            DemoRiskCeiling.EXTERNAL,
        )
        return _completed_candidate(risk_ceiling="external")

    port = ScriptedIntentPort(mutate_scenario)
    try:
        with pytest.raises(
            FormalDemoIntentRequestError,
            match="^FORMAL_DEMO_INTENT_SCENARIO_STALE$",
        ):
            _compile(
                disclosure=disclosure,
                gate=gate,
                permit=permit,
                port=port,
            )
    finally:
        object.__setattr__(
            FORMAL_DEMO_V1_SCENARIO,
            "risk_ceiling",
            original_risk,
        )

    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


def test_cancellation_consumes_the_attempt_and_cannot_be_replayed() -> None:
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )
    assert caught.value.args == ()
    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1

    retry_port = ScriptedIntentPort(_completed_candidate())
    with pytest.raises(FormalDemoIntentGateError):
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=retry_port,
        )
    assert retry_port.calls == []


def test_base_exception_message_is_removed_after_consumption() -> None:
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(KeyboardInterrupt("SECRET_INTERRUPT:" + SOURCE_TASK))

    with pytest.raises(KeyboardInterrupt) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )

    assert caught.value.args == ()
    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


@pytest.mark.parametrize(
    ("terminal", "expected_type", "expected_args"),
    (
        (SystemExit("SECRET_EXIT"), SystemExit, (1,)),
        (GeneratorExit("SECRET_GENERATOR"), GeneratorExit, ()),
    ),
)
def test_process_control_messages_are_sanitized_after_consumption(
    terminal: BaseException,
    expected_type: type[BaseException],
    expected_args: tuple[object, ...],
) -> None:
    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(terminal)

    with pytest.raises(expected_type) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )

    assert caught.value.args == expected_args
    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


def test_unknown_base_exception_is_normalized_after_consumption() -> None:
    class UnknownPortControl(BaseException):
        pass

    disclosure, gate, permit = _gate_and_permit()
    port = ScriptedIntentPort(UnknownPortControl("SECRET_UNKNOWN_CONTROL"))
    with pytest.raises(
        FormalDemoIntentRequestError,
        match="^FORMAL_DEMO_INTENT_PORT_FAILED$",
    ) as caught:
        _compile(
            disclosure=disclosure,
            gate=gate,
            permit=permit,
            port=port,
        )

    assert caught.value.__context__ is None
    assert gate.state is IntentCompileGateState.CONSUMED
    assert len(port.calls) == 1


def test_concurrent_attempts_make_exactly_one_fake_call() -> None:
    disclosure, gate, permit = _gate_and_permit()
    start = Barrier(8)
    entered = Event()
    release = Event()
    losers_done = Event()
    loser_lock = Lock()
    loser_count = 0

    def hold_winner(_request: IntentCandidateRequest) -> IntentCandidateResponse:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("timed out waiting to release winning fake")
        return _completed_candidate()

    port = ScriptedIntentPort(hold_winner)

    def attempt() -> object:
        nonlocal loser_count
        start.wait(timeout=5)
        try:
            return _compile(
                disclosure=disclosure,
                gate=gate,
                permit=permit,
                port=port,
            )
        except (FormalDemoIntentRequestError, FormalDemoIntentGateError) as exc:
            with loser_lock:
                loser_count += 1
                if loser_count == 7:
                    losers_done.set()
            return str(exc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt) for _index in range(8)]
        assert entered.wait(timeout=5)
        try:
            assert losers_done.wait(timeout=5)
            assert len(port.calls) == 1
        finally:
            release.set()
        results = [future.result(timeout=5) for future in futures]

    assert sum(isinstance(item, IntentCandidateAttempt) for item in results) == 1
    assert results.count("FORMAL_DEMO_INTENT_GATE_TERMINAL") == 7
    assert len(port.calls) == 1
    assert gate.state is IntentCompileGateState.CONSUMED


def test_sensitive_request_and_response_are_opaque_and_content_free() -> None:
    disclosure, gate, permit = _gate_and_permit()
    response = _completed_candidate()
    port = ScriptedIntentPort(response)
    _compile(
        disclosure=disclosure,
        gate=gate,
        permit=permit,
        port=port,
    )
    request = port.calls[0]

    assert SOURCE_TASK not in repr(request)
    assert response.candidate not in repr(response)
    assert not hasattr(request, "api_key")
    assert not hasattr(request, "credential")
    for operation in (
        lambda: copy.copy(request),
        lambda: copy.deepcopy(request),
        lambda: pickle.dumps(request),
        lambda: copy.copy(response),
        lambda: copy.deepcopy(response),
        lambda: pickle.dumps(response),
    ):
        with pytest.raises(FormalDemoIntentRequestError):
            operation()


def test_module_has_no_provider_sdk_network_credential_or_execution_wiring() -> None:
    source_path = Path(request_module.__file__ or "")
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    allowed_plain_imports = {"json", "re"}
    allowed_from_imports = {
        (0, "__future__"): {"annotations"},
        (0, "asyncio"): {"CancelledError"},
        (0, "dataclasses"): {"dataclass", "field"},
        (0, "enum"): {"Enum"},
        (0, "hashlib"): {"sha256"},
        (0, "typing"): {"Never", "Protocol", "SupportsIndex"},
        (1, "formal_demo_contract"): {
            "MAX_SOURCE_TASK_BYTES",
            "TASK_INTENT_VERSION",
            "DemoScenarioSpec",
            "FormalDemoContractError",
            "TaskIntent",
            "decode_demo_scenario_spec",
            "decode_task_intent",
            "resolve_reviewed_formal_demo_scenario",
            "validate_task_intent_for_reviewed_scenario",
        },
        (1, "formal_demo_intent_gate"): {
            "INTENT_COMPILE_OPERATION",
            "INTENT_COMPILE_REQUEST_LIMIT",
            "FormalDemoIntentDisclosure",
            "IntentCompileConsumption",
            "IntentCompileGate",
            "IntentCompilePermit",
            "ProviderIntentRoute",
        },
    }
    forbidden_attribute_calls = {
        "connect",
        "create_connection",
        "dispatch",
        "from_environment",
        "getenv",
        "import_module",
        "open",
        "open_connection",
        "request",
        "send",
        "urlopen",
        "urlretrieve",
    }
    forbidden_name_calls = forbidden_attribute_calls | {
        "__import__",
        "compile",
        "eval",
        "exec",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {item.name for item in node.names} <= allowed_plain_imports
        if isinstance(node, ast.ImportFrom):
            key = (node.level, node.module or "")
            assert key in allowed_from_imports
            assert {item.name for item in node.names} <= allowed_from_imports[key]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden_name_calls
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden_attribute_calls

    for value in (
        "create_model_provider",
        "create_planner",
        "create_final_response_adapter",
        "AgentRunner",
        "StdioDesktopMCP",
        "FastMCP",
        "WindowsDriver",
        "api_key",
        "os.environ",
    ):
        assert value not in source
