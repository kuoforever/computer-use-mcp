from __future__ import annotations

import json

import pytest

from computer_use_agent.application_worker_catalog import (
    APPLICATION_WORKERS_BY_SCENARIO,
)
from computer_use_agent.application_worker_contract import (
    ApplicationWorkerContractError,
    compile_application_worker_task,
    parse_application_worker_result,
)


SPEC = APPLICATION_WORKERS_BY_SCENARIO["A1"]
ITEM_KEY = "boss:job:publicjob001"


def _result(**overrides: object) -> str:
    value: dict[str, object] = {
        "version": 1,
        "scenario_id": "A1",
        "item_key": ITEM_KEY,
        "outcome": "EXTRACTED",
        "identity": {
            "account": "dedicated-test-account",
            "public_job_id": "publicjob001",
        },
        "result": {
            "company": "Example",
            "role": "Engineer",
            "location": "Shanghai",
            "compensation": "fixture-band",
            "experience": "fixture-level",
            "classification": "review",
        },
        "evidence": {
            "observation_tools": ["ui_snapshot", "document_text"],
            "application_state_verified": True,
            "item_identity_verified": True,
        },
        "stop_code": None,
    }
    value.update(overrides)
    return json.dumps(value)


def test_task_is_exact_bounded_and_contains_no_authority_extension() -> None:
    task = compile_application_worker_task(
        SPEC,
        item_key=ITEM_KEY,
        item_ordinal=7,
    )

    assert '"scenario_id":"A1"' in task
    assert '"item_ordinal":7' in task
    assert '"item_key":"boss:job:publicjob001"' in task
    assert '"maximum_risk":"read_only"' in task
    assert "never infer approval" in task


def test_exact_extracted_result_is_digest_bound() -> None:
    parsed = parse_application_worker_result(
        SPEC,
        item_key=ITEM_KEY,
        text=_result(),
    )

    assert parsed.outcome == "EXTRACTED"
    assert parsed.item_identity_verified
    assert parsed.application_state_verified
    assert parsed.observation_tools == ("ui_snapshot", "document_text")
    assert len(parsed.content_digest) == 64
    assert parsed.result["role"] == "Engineer"


def test_blocked_result_requires_reviewed_stop_state_and_empty_result() -> None:
    blocked = parse_application_worker_result(
        SPEC,
        item_key=ITEM_KEY,
        text=_result(
            outcome="BLOCKED",
            identity={},
            result={},
            evidence={
                "observation_tools": ["ui_snapshot"],
                "application_state_verified": False,
                "item_identity_verified": False,
            },
            stop_code="CHALLENGE",
        ),
    )
    assert blocked.outcome == "BLOCKED"
    assert blocked.stop_code == "CHALLENGE"

    with pytest.raises(
        ApplicationWorkerContractError,
        match="APPLICATION_WORKER_RESULT_INVALID",
    ):
        parse_application_worker_result(
            SPEC,
            item_key=ITEM_KEY,
            text=_result(
                outcome="BLOCKED",
                result={},
                stop_code="MODEL_DECIDED_TO_SKIP",
            ),
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_key": "boss:job:substituted"},
        {"scenario_id": "A2"},
        {"result": {"company": "missing-other-fields"}},
        {
            "evidence": {
                "observation_tools": ["screenshot"],
                "application_state_verified": True,
                "item_identity_verified": True,
            }
        },
        {"stop_code": "CHALLENGE"},
    ],
)
def test_result_substitution_schema_drift_and_unreviewed_evidence_fail(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(
        ApplicationWorkerContractError,
        match="APPLICATION_WORKER_RESULT_INVALID",
    ):
        parse_application_worker_result(
            SPEC,
            item_key=ITEM_KEY,
            text=_result(**overrides),
        )


def test_oversized_nested_value_is_rejected() -> None:
    with pytest.raises(
        ApplicationWorkerContractError,
        match="APPLICATION_WORKER_RESULT_TOO_LARGE",
    ):
        parse_application_worker_result(
            SPEC,
            item_key=ITEM_KEY,
            text=_result(
                result={
                    "company": "x" * 5000,
                    "role": "Engineer",
                    "location": "Shanghai",
                    "compensation": "fixture-band",
                    "experience": "fixture-level",
                    "classification": "review",
                }
            ),
        )
