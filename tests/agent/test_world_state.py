from __future__ import annotations

import base64
import inspect
from dataclasses import replace

import pytest

from computer_use_agent import world_state as world_state_module
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ToolResult,
    ToolResultStatus,
)
from computer_use_agent.world_state import (
    MAX_EVIDENCE_TEXT_CHARS,
    MAX_FACT_AGE_MS,
    MAX_WORLD_FACTS,
    ConditionEvaluation,
    ConditionOutcome,
    FactAvailability,
    FactCondition,
    FactExtractionMethod,
    FactInspection,
    FactKnowledge,
    FactScope,
    FactType,
    ObservationEvidence,
    WindowIdentity,
    WorldFact,
    WorldStateContext,
    WorldStateError,
    WorldStateSnapshot,
    evaluate_fact_condition,
    inspect_world_fact,
)


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _window(
    *, window_id: str = "window_1", process_id: int = 101, process_name: str = "app.exe"
) -> WindowIdentity:
    return WindowIdentity(window_id, process_id, process_name)


def _result(
    tool_name: str = "ui_snapshot",
    *,
    text: str = 'ref_1 | button "Private label"',
    call_id: str = "call_1",
    ok: bool = True,
) -> ToolResult:
    images = (
        (ImageContent("image/png", _PNG, 1, 1),)
        if tool_name in {"screenshot", "capture_region"} and ok
        else ()
    )
    return ToolResult(
        CallIdentity("run_1", "turn_1", call_id),
        tool_name,
        ToolResultStatus.SUCCESS if ok else ToolResultStatus.TRANSPORT_ERROR,
        (
            DispatchCertainty.DISPATCHED
            if ok
            else DispatchCertainty.NOT_DISPATCHED
        ),
        sanitized_text=text if ok else "",
        code=None if ok else "MCP_TIMEOUT_BEFORE_DISPATCH",
        images=images,
    )


def _evidence(
    *,
    tool_name: str = "ui_snapshot",
    epoch: int = 3,
    generation: int = 7,
    captured_at_ms: int = 1_000,
    window: WindowIdentity | None = None,
    text: str = 'ref_1 | button "Private label"',
) -> ObservationEvidence:
    return ObservationEvidence.from_tool_result(
        _result(tool_name, text=text),
        observation_epoch=epoch,
        mcp_generation=generation,
        captured_at_ms=captured_at_ms,
        window=window,
    )


def _fact(
    *,
    fact_id: str = "target_present",
    fact_type: FactType = FactType.BOOLEAN,
    knowledge: FactKnowledge = FactKnowledge.OBSERVED,
    value: bool | int | str | None = True,
    window_bound: bool = True,
    max_age_ms: int = 500,
) -> WorldFact:
    window = _window() if window_bound else None
    return WorldFact(
        fact_id=fact_id,
        fact_type=fact_type,
        knowledge=knowledge,
        value=value,
        evidence=_evidence(window=window),
        scope=FactScope.WINDOW if window_bound else FactScope.RUN,
        max_age_ms=max_age_ms,
    )


def _snapshot(fact: WorldFact | None = None) -> WorldStateSnapshot:
    return WorldStateSnapshot("run_1", (_fact() if fact is None else fact,))


def _context(
    *,
    run_id: str = "run_1",
    epoch: int = 3,
    generation: int = 7,
    now_ms: int = 1_500,
    window: WindowIdentity | None = None,
) -> WorldStateContext:
    return WorldStateContext(
        run_id=run_id,
        observation_epoch=epoch,
        mcp_generation=generation,
        now_ms=now_ms,
        window=_window() if window is None else window,
    )


@pytest.mark.parametrize(
    ("tool_name", "method"),
    [
        ("ui_snapshot", FactExtractionMethod.UI_AUTOMATION),
        ("find", FactExtractionMethod.UI_AUTOMATION),
        ("list_windows", FactExtractionMethod.WINDOW_ENUMERATION),
        ("document_text", FactExtractionMethod.DOCUMENT_TEXT),
        ("ocr", FactExtractionMethod.OCR),
        ("screenshot", FactExtractionMethod.PIXEL_MEASUREMENT),
        ("capture_region", FactExtractionMethod.PIXEL_MEASUREMENT),
    ],
)
def test_reviewed_observation_sources_have_fixed_extraction_methods(
    tool_name: str, method: FactExtractionMethod
) -> None:
    evidence = _evidence(tool_name=tool_name)

    assert evidence.source_tool == tool_name
    assert evidence.extraction_method is method
    assert len(evidence.evidence_digest) == 64


def test_evidence_hashes_source_content_without_retaining_text_or_image_bytes() -> None:
    private_text = "private account name and document content"
    text_evidence = _evidence(text=private_text)
    image_evidence = _evidence(tool_name="screenshot", text="")

    assert private_text not in repr(text_evidence)
    assert private_text not in str(text_evidence.to_payload())
    assert text_evidence.source_text_length == len(private_text)
    assert text_evidence.source_text_digest != "0" * 64
    assert image_evidence.source_images[0].digest != "0" * 64
    assert not hasattr(image_evidence, "sanitized_text")
    assert not hasattr(image_evidence.source_images[0], "data")


def test_evidence_digest_binds_result_epoch_generation_time_and_window() -> None:
    base = _evidence(window=_window())
    variants = (
        _evidence(window=_window(), text="different source"),
        _evidence(window=_window(), epoch=4),
        _evidence(window=_window(), generation=8),
        _evidence(window=_window(), captured_at_ms=1_001),
        _evidence(window=_window(process_id=102)),
    )

    assert len({base.evidence_digest, *(item.evidence_digest for item in variants)}) == 6


def test_direct_evidence_metadata_is_bounded_to_the_reviewed_result_shape() -> None:
    text = _evidence()
    screenshot = _evidence(tool_name="screenshot", text="")

    with pytest.raises(WorldStateError, match="EVIDENCE_INVALID"):
        replace(text, source_text_length=MAX_EVIDENCE_TEXT_CHARS + 1)
    with pytest.raises(WorldStateError, match="EVIDENCE_INVALID"):
        replace(text, source_images=screenshot.source_images)
    with pytest.raises(WorldStateError, match="EVIDENCE_INVALID"):
        replace(screenshot, source_images=())


@pytest.mark.parametrize(
    "result",
    [
        _result(ok=False),
        ToolResult(
            CallIdentity("run_1", "turn_1", "call_click"),
            "click",
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
        ),
    ],
)
def test_failed_or_side_effect_results_cannot_become_fact_evidence(
    result: ToolResult,
) -> None:
    with pytest.raises(WorldStateError):
        ObservationEvidence.from_tool_result(
            result,
            observation_epoch=1,
            mcp_generation=1,
            captured_at_ms=1,
        )


@pytest.mark.parametrize(
    ("fact_type", "value"),
    [
        (FactType.BOOLEAN, False),
        (FactType.INTEGER, 42),
        (FactType.TEXT, "bounded text"),
        (FactType.IDENTIFIER, "control.ready"),
    ],
)
def test_fact_values_are_exactly_typed_and_digest_bound(
    fact_type: FactType, value: bool | int | str
) -> None:
    fact = _fact(
        fact_id=f"fact_{fact_type.value}",
        fact_type=fact_type,
        value=value,
        window_bound=False,
    )

    assert fact.value == value
    assert len(fact.digest) == 64
    assert repr(value) not in repr(fact)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _fact(fact_type=FactType.BOOLEAN, value=1),
        lambda: _fact(fact_type=FactType.INTEGER, value=True),
        lambda: _fact(fact_type=FactType.TEXT, value=""),
        lambda: _fact(fact_type=FactType.IDENTIFIER, value="unsafe value"),
        lambda: _fact(knowledge=FactKnowledge.UNKNOWN, value=False),
        lambda: _fact(window_bound=True, max_age_ms=0),
        lambda: _fact(window_bound=True, max_age_ms=MAX_FACT_AGE_MS + 1),
        lambda: replace(_fact(window_bound=True), scope=FactScope.RUN),
        lambda: replace(_fact(window_bound=False), scope=FactScope.WINDOW),
    ],
)
def test_malformed_type_knowledge_scope_and_freshness_fail_closed(factory) -> None:
    with pytest.raises(WorldStateError):
        factory()


def test_explicit_unknown_fact_has_no_value_and_is_unavailable() -> None:
    fact = _fact(knowledge=FactKnowledge.UNKNOWN, value=None)
    inspection = inspect_world_fact(
        _snapshot(fact),
        fact.fact_id,
        _context(),
        required_type=FactType.BOOLEAN,
    )

    assert inspection.availability is FactAvailability.UNKNOWN
    assert not inspection.available
    assert inspection.value is None
    assert inspection.fact_digest is None
    assert inspection.evidence_digest is None


@pytest.mark.parametrize(
    ("context", "required_type", "expected"),
    [
        (_context(run_id="run_2"), FactType.BOOLEAN, FactAvailability.RUN_CHANGED),
        (_context(epoch=4), FactType.BOOLEAN, FactAvailability.EPOCH_CHANGED),
        (
            _context(generation=8),
            FactType.BOOLEAN,
            FactAvailability.GENERATION_CHANGED,
        ),
        (
            _context(window=_window(window_id="window_2")),
            FactType.BOOLEAN,
            FactAvailability.WINDOW_CHANGED,
        ),
        (
            _context(window=_window(process_id=102)),
            FactType.BOOLEAN,
            FactAvailability.WINDOW_CHANGED,
        ),
        (
            _context(window=_window(process_name="replacement.exe")),
            FactType.BOOLEAN,
            FactAvailability.WINDOW_CHANGED,
        ),
        (_context(now_ms=999), FactType.BOOLEAN, FactAvailability.CLOCK_INVALID),
        (_context(now_ms=1_501), FactType.BOOLEAN, FactAvailability.EXPIRED),
        (_context(), FactType.TEXT, FactAvailability.TYPE_MISMATCH),
    ],
)
def test_epoch_generation_window_time_and_type_drift_never_expose_a_value(
    context: WorldStateContext,
    required_type: FactType,
    expected: FactAvailability,
) -> None:
    inspection = inspect_world_fact(
        _snapshot(),
        "target_present",
        context,
        required_type=required_type,
    )

    assert inspection.availability is expected
    assert not inspection.available
    assert inspection.value is None
    assert inspection.fact_digest is None
    assert inspection.evidence_digest is None


def test_missing_or_absent_window_context_fails_closed() -> None:
    missing = inspect_world_fact(
        WorldStateSnapshot("run_1", ()),
        "missing_fact",
        _context(),
        required_type=FactType.BOOLEAN,
    )
    no_window = WorldStateContext("run_1", 3, 7, 1_500, None)
    changed = inspect_world_fact(
        _snapshot(),
        "target_present",
        no_window,
        required_type=FactType.BOOLEAN,
    )

    assert missing.availability is FactAvailability.MISSING
    assert changed.availability is FactAvailability.WINDOW_CHANGED


def test_exact_freshness_boundary_and_window_identity_are_available() -> None:
    inspection = inspect_world_fact(
        _snapshot(),
        "target_present",
        _context(now_ms=1_500),
        required_type=FactType.BOOLEAN,
    )

    assert inspection.available
    assert inspection.availability is FactAvailability.FRESH
    assert inspection.value is True
    assert inspection.fact_type is FactType.BOOLEAN
    assert inspection.fact_digest == _fact().digest
    assert inspection.evidence_digest == _fact().evidence.evidence_digest


def test_run_scoped_fact_does_not_gain_or_require_window_authority() -> None:
    fact = _fact(window_bound=False)
    context = replace(_context(), window=_window(process_id=999))
    inspection = inspect_world_fact(
        _snapshot(fact),
        fact.fact_id,
        context,
        required_type=FactType.BOOLEAN,
    )

    assert inspection.available


def test_fresh_known_condition_distinguishes_true_from_false() -> None:
    true_condition = FactCondition(
        "condition_present",
        "target_present",
        FactType.BOOLEAN,
        True,
    )
    false_condition = replace(true_condition, expected_value=False)

    true_result = evaluate_fact_condition(_snapshot(), true_condition, _context())
    false_result = evaluate_fact_condition(_snapshot(), false_condition, _context())

    assert true_result.outcome is ConditionOutcome.TRUE
    assert false_result.outcome is ConditionOutcome.FALSE
    assert true_result.availability is false_result.availability is FactAvailability.FRESH
    assert true_result.fact_digest == false_result.fact_digest == _fact().digest


@pytest.mark.parametrize(
    ("snapshot", "context", "availability"),
    [
        (_snapshot(_fact(knowledge=FactKnowledge.UNKNOWN, value=None)), _context(), FactAvailability.UNKNOWN),
        (_snapshot(), _context(epoch=4), FactAvailability.EPOCH_CHANGED),
        (
            _snapshot(),
            _context(window=_window(process_id=202)),
            FactAvailability.WINDOW_CHANGED,
        ),
        (_snapshot(), _context(now_ms=1_501), FactAvailability.EXPIRED),
    ],
)
def test_invalidated_condition_is_unavailable_never_false(
    snapshot: WorldStateSnapshot,
    context: WorldStateContext,
    availability: FactAvailability,
) -> None:
    condition = FactCondition(
        "condition_present",
        "target_present",
        FactType.BOOLEAN,
        True,
    )

    result = evaluate_fact_condition(snapshot, condition, context)

    assert result.outcome is ConditionOutcome.UNAVAILABLE
    assert result.availability is availability
    assert result.fact_digest is None
    assert result.evidence_digest is None


def test_condition_digest_binds_expected_value_without_repr_disclosure() -> None:
    secret_expected = "private expected label"
    condition = FactCondition(
        "condition_label",
        "target_label",
        FactType.TEXT,
        secret_expected,
    )

    assert secret_expected not in repr(condition)
    assert condition.digest != replace(condition, expected_value="other").digest


def test_snapshot_order_is_canonical_and_duplicate_or_cross_run_facts_fail() -> None:
    first = _fact(fact_id="fact_a", window_bound=False)
    second = _fact(
        fact_id="fact_b",
        fact_type=FactType.INTEGER,
        value=2,
        window_bound=False,
    )
    forward = WorldStateSnapshot("run_1", (first, second))
    reverse = WorldStateSnapshot("run_1", (second, first))

    assert forward.facts == reverse.facts
    assert forward.digest == reverse.digest
    with pytest.raises(WorldStateError, match="DUPLICATE"):
        WorldStateSnapshot("run_1", (first, first))
    with pytest.raises(WorldStateError, match="RUN_MISMATCH"):
        WorldStateSnapshot(
            "run_1",
            (replace(first, evidence=replace(first.evidence, identity=CallIdentity("run_2", "turn_1", "call_1"))),),
        )


def test_snapshot_fact_bound_and_structural_result_invariants_fail_closed() -> None:
    facts = tuple(
        _fact(fact_id=f"fact_{index}", window_bound=False)
        for index in range(MAX_WORLD_FACTS + 1)
    )
    with pytest.raises(WorldStateError, match="FACTS_INVALID"):
        WorldStateSnapshot("run_1", facts)
    with pytest.raises(WorldStateError, match="INSPECTION_INVALID"):
        FactInspection("fact_1", FactAvailability.EXPIRED, value=True)
    with pytest.raises(WorldStateError, match="CONDITION_INVALID"):
        ConditionEvaluation(
            "condition_1",
            ConditionOutcome.FALSE,
            FactAvailability.EXPIRED,
            "a" * 64,
            fact_digest="b" * 64,
        )


def test_world_state_module_has_no_external_or_tree_transition_port() -> None:
    source = inspect.getsource(world_state_module)

    assert "call_tool(" not in source
    assert "_execute_requested_call_boundary(" not in source
    assert "transition_tree_leaf(" not in source
    assert not hasattr(WorldStateSnapshot, "dispatch")
    assert not hasattr(ConditionEvaluation, "transition")
