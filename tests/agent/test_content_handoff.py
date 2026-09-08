"""Content proposal boundaries using synthetic sources and documents only."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from computer_use_agent.content_handoff import (
    CHECKS, ContentHandoffError, ContentProfile, HostContentContext,
    bind_content_task, candidate_digest, safe_content_receipt, text_digest,
    verify_content_results,
)

FIXTURE = Path(__file__).parents[1] / "fixtures" / "content_handoff_v1.json"


def setup_case(index=0):
    case = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"][index]
    raw = json.dumps(case["candidate"]).encode()
    host = HostContentContext(case["candidate"]["task_id"], case["candidate"]["target"]["target_id"],
                              {s["source_id"]: text_digest(s["text"]) for s in case["host_sources"]},
                              case["initial_text"], candidate_digest(raw))
    return case, raw, host, ContentProfile(**case["profile"])


@pytest.mark.parametrize("index", [0, 1])
def test_profiles_reuse_contract_without_web_or_model_dependencies(index):
    case, raw, host, profile = setup_case(index)
    task = bind_content_task(raw, host=host, profile=profile)
    final = case["initial_text"] + case["candidate"]["content"]["text"]
    verify_content_results(task, target_id=host.target_id, observations=dict.fromkeys(CHECKS, final))
    receipt = safe_content_receipt(task)
    assert receipt["execution_authorized"] is False
    assert case["candidate"]["content"]["text"] not in json.dumps(receipt)
    assert host.target_id not in json.dumps(receipt)
    assert task.content not in repr(task)


def test_model_cannot_self_approve_or_add_a_tool():
    case, _, host, profile = setup_case()
    for key, value in [("approved", True), ("tool", "type"), ("host", {"reviewed": True})]:
        raw = json.dumps(case["candidate"] | {key: value}).encode()
        with pytest.raises(ContentHandoffError, match="FIELDS"):
            bind_content_task(raw, host=host, profile=profile)


def test_mutation_after_review_rejected_even_with_recomputed_content_hashes():
    case, _, host, profile = setup_case()
    candidate = case["candidate"]
    candidate["content"]["text"] += " Altered claim."
    candidate["content"]["sha256"] = text_digest(candidate["content"]["text"])
    candidate["acceptance"]["expected_text_sha256"] = text_digest(host.initial_text + candidate["content"]["text"])
    with pytest.raises(ContentHandoffError, match="REVIEW_BINDING"):
        bind_content_task(json.dumps(candidate).encode(), host=host, profile=profile)


@pytest.mark.parametrize("changed", ["task", "target", "source", "initial", "review"])
def test_host_identity_changes_reject_stale_handoff(changed):
    _, raw, host, profile = setup_case()
    host = {
        "task": replace(host, task_id="different"),
        "target": replace(host, target_id="different"),
        "source": replace(host, sources={"different": "0" * 64}),
        "initial": replace(host, initial_text="Edited document"),
        "review": replace(host, reviewed_task_sha256="0" * 64),
    }[changed]
    with pytest.raises(ContentHandoffError):
        bind_content_task(raw, host=host, profile=profile)


@pytest.mark.parametrize("change", [
    "bool_version", "operation", "empty_sources", "duplicate_source", "source_digest",
    "content_digest", "expected_digest", "missing_check", "extra_check", "nested_extra",
    "target_path", "control_text", "surrogate", "profile", "large_content",
])
def test_invalid_candidates_rejected_even_if_external_review_digest_matches(change):
    case, _, host, profile = setup_case()
    c = case["candidate"]
    if change == "bool_version":
        c["version"] = True
    elif change == "operation":
        c["operation"] = "execute_script"
    elif change == "empty_sources":
        c["sources"] = []
    elif change == "duplicate_source":
        c["sources"] *= 2
    elif change == "source_digest":
        c["sources"][0]["content_sha256"] = "0" * 64
    elif change == "content_digest":
        c["content"]["sha256"] = "0" * 64
    elif change == "expected_digest":
        c["acceptance"]["expected_text_sha256"] = "0" * 64
    elif change == "missing_check":
        c["acceptance"]["checks"].pop()
    elif change == "extra_check":
        c["acceptance"]["checks"].append("publish")
    elif change == "nested_extra":
        c["target"]["approved"] = True
    elif change == "target_path":
        c["target"]["target_id"] = "../other.docx"
    elif change == "control_text":
        c["content"]["text"] = "private\x00text"
    elif change == "surrogate":
        c["content"]["text"] = "\ud800"
    elif change == "profile":
        c["profile_id"] = "other-profile"
    else:
        c["content"]["text"] = "x" * 32769
    raw = json.dumps(c).encode()
    host = replace(host, reviewed_task_sha256=candidate_digest(raw))
    with pytest.raises(ContentHandoffError):
        bind_content_task(raw, host=host, profile=profile)


@pytest.mark.parametrize("raw", [b"[]", b"{}", b"\xff", b'x' * 65537,
                                  b'{"a":1,"a":2}', b'{"a":NaN}', b"[" * 2000,
                                  b'{"n":' + b'9' * 5000 + b'}'],
                         ids=["array", "empty", "encoding", "oversize", "duplicate", "nan", "deep", "integer"])
def test_malformed_json_has_fixed_error_without_prose(raw):
    _, _, host, profile = setup_case()
    with pytest.raises(ContentHandoffError) as exc:
        bind_content_task(raw, host=host, profile=profile)
    assert str(exc.value) in {"FIELDS", "JSON", "SIZE", "DUPLICATE_FIELD", "NONFINITE"}


@pytest.mark.parametrize("profile", [ContentProfile("chrome-word-summary-v1", True, 2000),
                                    ContentProfile("chrome-word-summary-v1", 1, 2000),
                                    ContentProfile("chrome-word-summary-v1", 900, 1)])
def test_host_profile_limits_are_enforced(profile):
    _, raw, host, _ = setup_case()
    with pytest.raises(ContentHandoffError):
        bind_content_task(raw, host=host, profile=profile)


@pytest.mark.parametrize("phase", CHECKS)
def test_each_result_requires_exact_complete_text_not_token_overlap(phase):
    case, raw, host, profile = setup_case()
    task = bind_content_task(raw, host=host, profile=profile)
    final = host.initial_text + case["candidate"]["content"]["text"]
    for wrong in (final[:-1], final + task.content, final.replace("\n", " "), "wrong"):
        observations = dict.fromkeys(CHECKS, final)
        observations[phase] = wrong
        with pytest.raises(ContentHandoffError, match="RESULT_MISMATCH"):
            verify_content_results(task, target_id=host.target_id, observations=observations)


def test_missing_phase_wrong_target_and_caller_mutation_do_not_pass():
    _, raw, host, profile = setup_case()
    task = bind_content_task(raw, host=host, profile=profile)
    with pytest.raises(ContentHandoffError, match="RESULT_BINDING"):
        verify_content_results(task, target_id=host.target_id, observations={})
    with pytest.raises(ContentHandoffError, match="RESULT_BINDING"):
        verify_content_results(task, target_id="other", observations=dict.fromkeys(CHECKS, "text"))
    old_pins = task.source_pins
    assert isinstance(host.sources, dict)
    host.sources.clear()
    assert task.source_pins == old_pins


def test_digest_is_canonical_but_does_not_establish_factual_truth():
    case, raw, host, profile = setup_case()
    assert candidate_digest(raw) == candidate_digest(json.dumps(case["candidate"], indent=2).encode())
    c = case["candidate"]
    # Semantics are the external reviewer's job. A matching digest is not entailment.
    c["content"]["text"] = "An unsupported claim with a matching external review."
    c["content"]["sha256"] = text_digest(c["content"]["text"])
    c["acceptance"]["expected_text_sha256"] = text_digest(host.initial_text + c["content"]["text"])
    raw = json.dumps(c).encode()
    bind_content_task(raw, host=replace(host, reviewed_task_sha256=candidate_digest(raw)), profile=profile)
