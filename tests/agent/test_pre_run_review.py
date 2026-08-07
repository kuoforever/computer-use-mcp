from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from computer_use_agent.config import AgentConfig, load_agent_config
from computer_use_agent.config_init import initialize_public_web_word_config
from computer_use_agent.pre_run_review import (
    PreRunReviewError,
    compile_public_web_word_review,
    render_pre_run_review,
)
from computer_use_agent.public_web_word import (
    PUBLIC_WEB_WORD_SOURCE_TITLE,
    PUBLIC_WEB_WORD_SOURCE_URL,
    public_web_word_contract_error,
)


FORBIDDEN = "MODEL_PLAN_SECRET_MUST_NOT_APPEAR"


def _config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> AgentConfig:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    mcp_executable = tmp_path / "guarded-desktop-mcp.exe"
    mcp_executable.write_bytes(b"")
    config_path = tmp_path / "workflow.toml"
    initialize_public_web_word_config(
        provider="openai",
        model="reviewed-model",
        output=config_path,
        mcp_executable=mcp_executable,
    )
    return load_agent_config(config_path)


def test_public_web_word_review_is_host_fixed_complete_and_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    output = (tmp_path / "brief.docx").resolve()
    review = compile_public_web_word_review(config, output)
    payload = review.as_json()
    encoded = json.dumps(payload)

    assert payload["pre_run_review_version"] == 1
    assert payload["source"] == "host_fixed_contract"
    assert payload["contains_model_prose"] is False
    assert payload["external_work_started"] is False
    assert payload["workflow"] == "public-web-word"
    assert [item["name"] for item in payload["applications"]] == [
        "Google Chrome",
        "Microsoft Word",
    ]
    assert payload["output"] == {
        "path": str(output),
        "policy": "CREATE_NEW_ONLY_NEVER_OVERWRITE",
    }
    assert payload["maximum_approvals"] == 7
    assert payload["acknowledgement"] == {
        "interactive_token": "START",
        "noninteractive_flag": "--acknowledge-scope",
        "starts_ordinary_workflow_only": True,
        "grants_action_approval": False,
        "grants_retry_or_replay": False,
    }
    assert {item["code"] for item in payload["stop_conditions"]} == {
        "PRECONDITION_FAILED",
        "OPERATOR_NOT_APPROVED",
        "DESKTOP_AUTHORITY_LOST",
        "BOUND_EXHAUSTED",
        "VERIFICATION_FAILED",
        "UNKNOWN_OUTCOME",
    }
    assert PUBLIC_WEB_WORD_SOURCE_TITLE in encoded
    assert PUBLIC_WEB_WORD_SOURCE_URL in encoded
    assert FORBIDDEN not in encoded
    assert not output.exists()


def test_human_scope_sheet_explains_effects_stops_and_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = compile_public_web_word_review(
        _config(tmp_path, monkeypatch),
        (tmp_path / "brief.docx").resolve(),
    )
    rendered = render_pre_run_review(review)

    for expected in (
        "Pre-run Review - nothing has started",
        "Applications",
        "Reads",
        "Changes",
        "Maximum action approvals: 7",
        "Stops when",
        "do not retry automatically",
        "Possible unfinished state",
        "does not pre-approve any desktop action",
    ):
        assert expected in rendered
    assert FORBIDDEN not in rendered


def test_review_fails_closed_for_contract_drift_before_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    under_budget = replace(
        config,
        policy=replace(config.policy, max_side_effects=6),
    )

    with pytest.raises(PreRunReviewError, match="PUBLIC_WEB_WORD_BUDGET_TOO_SMALL"):
        compile_public_web_word_review(
            under_budget,
            (tmp_path / "brief.docx").resolve(),
        )

    assert not (tmp_path / "brief.docx").exists()


@pytest.mark.parametrize(
    ("drift", "expected"),
    [
        ("policy", "PUBLIC_WEB_WORD_APPROVED_ACTIONS_REQUIRED"),
        ("continuation", "PUBLIC_WEB_WORD_CONTINUATION_MUST_BE_DISABLED"),
        ("allowlist", "PUBLIC_WEB_WORD_ALLOWLIST_MUST_BE_FIXED"),
        ("human_idle", "PUBLIC_WEB_WORD_HUMAN_IDLE_PROFILE_REQUIRED"),
        ("budget", "PUBLIC_WEB_WORD_BUDGET_TOO_SMALL"),
    ],
)
def test_shared_product_contract_validator_returns_exact_first_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
    expected: str,
) -> None:
    config = _config(tmp_path, monkeypatch)
    if drift == "policy":
        config = replace(
            config,
            policy=replace(config.policy, mode="read_only"),
        )
    elif drift == "continuation":
        config = replace(
            config,
            continuation=replace(config.continuation, enabled=True),
        )
    elif drift == "allowlist":
        environment = dict(config.mcp.environment)
        environment["CUMCP_ALLOWLIST"] = "notepad.exe"
        config = replace(config, mcp=replace(config.mcp, environment=environment))
    elif drift == "human_idle":
        environment = dict(config.mcp.environment)
        environment["CUMCP_HUMAN_STABLE_SAMPLES"] = "2"
        config = replace(config, mcp=replace(config.mcp, environment=environment))
    else:
        config = replace(
            config,
            policy=replace(config.policy, max_side_effects=6),
        )

    assert public_web_word_contract_error(config) == expected
    with pytest.raises(PreRunReviewError, match=f"^{expected}$"):
        compile_public_web_word_review(
            config,
            (tmp_path / "brief.docx").resolve(),
        )


def test_review_refuses_existing_output_or_missing_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    existing = (tmp_path / "existing.docx").resolve()
    existing.write_bytes(b"user-owned")

    with pytest.raises(PreRunReviewError, match="PUBLIC_WEB_WORD_OUTPUT_EXISTS"):
        compile_public_web_word_review(config, existing)
    assert existing.read_bytes() == b"user-owned"

    missing = (tmp_path / "missing" / "brief.docx").resolve()
    with pytest.raises(
        PreRunReviewError,
        match="PUBLIC_WEB_WORD_OUTPUT_PARENT_NOT_FOUND",
    ):
        compile_public_web_word_review(config, missing)
    assert not missing.parent.exists()


def test_review_discloses_exact_explicit_application_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, monkeypatch)
    chrome = (tmp_path / "chrome.exe").resolve()
    word = (tmp_path / "winword.exe").resolve()
    review = compile_public_web_word_review(
        config,
        (tmp_path / "brief.docx").resolve(),
        chrome_executable=chrome,
        word_executable=word,
    )

    assert [item.executable_override for item in review.applications] == [
        str(chrome),
        str(word),
    ]
