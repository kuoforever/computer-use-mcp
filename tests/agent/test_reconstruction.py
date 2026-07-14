from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from computer_use_agent.reconstruction import (
    OperationEffect,
    OperationError,
    OperationKind,
    OperationRecord,
    OperationResult,
    OperationStage,
    OperationState,
    ReconstructionContext,
    classify_crash_reconstruction,
    fold_operation_records,
)


FIXTURE = Path(__file__).parents[2] / "evals" / "e2-crash-reconstruction.json"
MANIFEST = (
    Path(__file__).parents[2] / "evals" / "e2-crash-reconstruction-manifest.json"
)


def _record(raw: list[object]) -> OperationRecord:
    operation_id, kind, stage, effect, result = raw
    return OperationRecord(
        operation_id=str(operation_id),
        kind=OperationKind(str(kind)),
        stage=OperationStage(str(stage)),
        effect=None if effect is None else OperationEffect(str(effect)),
        result=None if result is None else OperationResult(str(result)),
    )


def _context(raw: dict[str, object]) -> ReconstructionContext:
    values = dict(raw)
    pending = values.get("pending_effect")
    if pending is not None:
        values["pending_effect"] = OperationEffect(str(pending))
    return ReconstructionContext(**values)  # type: ignore[arg-type]


def test_write_ahead_operation_state_machine_allows_only_linear_transitions() -> None:
    prepared = OperationState.prepare("run_1:turn_1:provider", OperationKind.PROVIDER)
    intent = prepared.apply(
        OperationRecord(
            "run_1:turn_1:provider",
            OperationKind.PROVIDER,
            OperationStage.DISPATCH_INTENT,
        )
    )
    completed = intent.apply(
        OperationRecord(
            "run_1:turn_1:provider",
            OperationKind.PROVIDER,
            OperationStage.COMPLETED,
            result=OperationResult.SUCCESS,
        )
    )

    assert completed.stage is OperationStage.COMPLETED
    with pytest.raises(OperationError, match="ILLEGAL_OPERATION_TRANSITION"):
        prepared.apply(
            OperationRecord(
                prepared.operation_id,
                OperationKind.PROVIDER,
                OperationStage.COMPLETED,
                result=OperationResult.SUCCESS,
            )
        )
    with pytest.raises(OperationError, match="OPERATION_IDENTITY_MISMATCH"):
        intent.apply(
            OperationRecord(
                "different",
                OperationKind.PROVIDER,
                OperationStage.COMPLETED,
                result=OperationResult.SUCCESS,
            )
        )


def test_write_ahead_ledger_rejects_interleaving_and_operation_id_reuse() -> None:
    first = OperationRecord(
        "tool_1", OperationKind.TOOL, OperationStage.PREPARED, OperationEffect.OBSERVATION
    )
    second = OperationRecord(
        "tool_2", OperationKind.TOOL, OperationStage.PREPARED, OperationEffect.OBSERVATION
    )
    with pytest.raises(OperationError, match="OPERATION_INTERLEAVED"):
        fold_operation_records([first, second])

    complete = [
        first,
        OperationRecord(
            "tool_1",
            OperationKind.TOOL,
            OperationStage.DISPATCH_INTENT,
            OperationEffect.OBSERVATION,
        ),
        OperationRecord(
            "tool_1",
            OperationKind.TOOL,
            OperationStage.COMPLETED,
            OperationEffect.OBSERVATION,
            OperationResult.SUCCESS,
        ),
        first,
    ]
    with pytest.raises(OperationError, match="OPERATION_ID_REUSED"):
        fold_operation_records(complete)


def test_e2_crash_reconstruction_fixture_is_canonical_and_frozen() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    assert set(manifest) == {"version", "sha256"}
    assert manifest["version"] == 1
    assert set(manifest["sha256"]) == {FIXTURE.name}
    assert hashlib.sha256(canonical).hexdigest() == manifest["sha256"][FIXTURE.name]


def test_e2_crash_reconstruction_matrix_is_fail_closed_and_side_effect_free() -> None:
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(document) == {"version", "level", "invariants", "cases"}
    assert document["version"] == 1
    assert document["level"] == "E2"
    assert document["invariants"] == {
        "automatic_resume": False,
        "new_external_calls": [],
        "safety_escapes": 0,
    }
    cases = document["cases"]
    assert isinstance(cases, list) and len(cases) == 14
    assert len({case["id"] for case in cases}) == 14
    assert {
        case["id"]: case["runtime_calls"]
        for case in cases
        if case["runtime_calls"]
    } == {
        "e2_resume_provider_completed_observation_pending": ["tool:list_windows"],
        "e2_resume_observation_completed": ["provider:turn_2"],
    }

    for case in cases:
        records = [_record(raw) for raw in case["records"]]
        decision = classify_crash_reconstruction(
            records, context=_context(case["context"])
        )
        expected_action, expected_reason, expected_phase = case["expected"]
        assert decision.action.value == expected_action, case["id"]
        assert decision.reason == expected_reason, case["id"]
        assert decision.final_phase.value == expected_phase, case["id"]
        assert decision.automatic_resume is False, case["id"]
        assert decision.new_external_calls == (), case["id"]
        assert document["invariants"]["safety_escapes"] == 0, case["id"]


@pytest.mark.parametrize(
    "context",
    [
        ReconstructionContext(integrity="corrupt"),
        ReconstructionContext(identity_matches=False),
        ReconstructionContext(sequence_matches=False),
    ],
)
def test_invalid_reconstruction_context_is_classified_before_ledger_fold(
    context: ReconstructionContext,
) -> None:
    decision = classify_crash_reconstruction([], context=context)

    assert decision.automatic_resume is False
    assert decision.new_external_calls == ()
