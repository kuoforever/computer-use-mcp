import asyncio
import base64
import copy
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROBE = runpy.run_path(str(ROOT / "scripts/probe_gui_inert_model.py"))
READ = runpy.run_path(str(Path(__file__).with_name("test_gui_readonly_probe.py")))
RAW = '<tool_call>{"name":"computer_use","arguments":{"action":"left_click","coordinate":[500,500]}}</tool_call>'


def fake_api(*, action="click_ref", reject=False):
    def project(task, results, image, facts):
        assert len(facts["control_states"]) == 1 and results["screenshot"]["tool"] == "screenshot"
        assert image.startswith(b"\x89PNG")
        return dict(status="projected", execution_authorized=False, context=task)

    def compile(issued, captured, reply):
        assert issued == captured and issued is not captured
        assert reply["request_id"] == issued["request_id"]
        if reject:
            raise ValueError("raw private failure")
        return SimpleNamespace(to_dict=lambda: dict(action=action, execution_authorized=False))
    return SimpleNamespace(project=project, digest=lambda _: "a" * 64, compile=compile)


def response(request):
    return dict(version=1, status="OK", request_id=request["request_id"],
                context_digest=request["context_digest"], raw_output=RAW, model_requests=1,
                model_id=PROBE["MODEL"], revision=PROBE["REVISION"], adapter_sha256=PROBE["ADAPTER"],
                image_sha256=hashlib.sha256(base64.b64decode(request["image_base64"])).hexdigest(),
                input_tokens=100, output_tokens=30, generation_seconds=2.5, peak_allocated_bytes=1000)


def run_probe(tmp_path, monkeypatch, *, fault="", api=None, worker=None, ticks=(7, 7)):
    runner, desktop = READ["setup_probe"](tmp_path, monkeypatch, fault=fault)
    calls = []

    def invoke(api, request):
        assert set(request) == {"version", "request_id", "context_digest", "image_base64"}
        assert desktop._session is None  # MCP already closed: proposal cannot dispatch.
        calls.append(copy.deepcopy(request))
        return response(request) if worker is None else worker(api, request)
    clock = iter(ticks)
    receipt = asyncio.run(PROBE["probe"](
        "314", api or fake_api(), tick=lambda: next(clock), runner=runner, worker=invoke,
    ))
    assert not runner.ports.provider.calls and not runner.ports.approvals.requests
    assert receipt["host_model_turns"] == receipt["side_effects"] == 0
    assert RAW not in json.dumps(receipt) and "private" not in json.dumps(receipt)
    return receipt, calls


def test_one_inert_request_no_desktop_action(tmp_path, monkeypatch):
    receipt, calls = run_probe(tmp_path, monkeypatch)
    assert receipt["outcome"] == "PASS" and receipt["code"] == "CLICK_REF_ACCEPTED"
    assert len(calls) == receipt["worker_invocations"] == receipt["model_requests"] == 1
    assert receipt["tool_calls"] == receipt["observation_epoch"] == 3
    assert receipt["post_inference_desktop_revalidated"] is False


@pytest.mark.parametrize("action,reject,code", [
    ("stop", False, "MODEL_STOPPED"), ("click_ref", True, "PROPOSAL_REJECTED"),
])
def test_valid_negative_is_not_retried(tmp_path, monkeypatch, action, reject, code):
    receipt, calls = run_probe(tmp_path, monkeypatch, api=fake_api(action=action, reject=reject))
    assert receipt["outcome"] == "FAIL" and receipt["code"] == code and len(calls) == 1
    assert receipt["model_requests"] == 1


def test_observation_failure_never_calls_model(tmp_path, monkeypatch):
    receipt, calls = run_probe(tmp_path, monkeypatch, fault="metadata_error")
    assert not calls and receipt["model_requests"] == 0
    assert receipt["code"] == "OBSERVATION_REJECTED" and receipt["phase"] == "FAILED"


def test_input_change_invalidates_positive_result(tmp_path, monkeypatch):
    receipt, _ = run_probe(tmp_path, monkeypatch, ticks=(7, 8))
    assert receipt["outcome"] == "INVALID" and receipt["code"] == "INPUT_CHANGED"


def test_timeout_counts_unknown_generation_without_retry(tmp_path, monkeypatch):
    def timeout(api, request):
        raise subprocess.TimeoutExpired("private", 180)
    receipt, calls = run_probe(tmp_path, monkeypatch, worker=timeout)
    assert len(calls) == 1 and receipt["model_requests"] is None
    assert receipt["code"] == "WORKER_REJECTED" and receipt["outcome"] == "FAIL"


@pytest.mark.parametrize("count", [0, 1])
def test_worker_error_retains_only_validated_count(tmp_path, monkeypatch, count):
    receipt, _ = run_probe(tmp_path, monkeypatch, worker=lambda *_: dict(
        version=1, status="ERROR", code="MODEL_WORKER_FAILED", model_requests=count,
    ))
    assert receipt["model_requests"] == count and receipt["outcome"] == "FAIL"


@pytest.mark.parametrize("key,value", [
    ("version", True), ("request_id", "other"), ("context_digest", "b" * 64),
    ("image_sha256", "b" * 64), ("adapter_sha256", "b" * 64), ("revision", "other"),
    ("model_requests", True), ("model_requests", 2), ("output_tokens", 193),
    ("generation_seconds", float("nan")), ("peak_allocated_bytes", 15_000_000_001),
    ("raw_output", "x" * 4097), ("extra", "private"),
])
def test_untrusted_worker_metadata_rejects(tmp_path, monkeypatch, key, value):
    receipt, calls = run_probe(tmp_path, monkeypatch, worker=lambda api, req: response(req) | {key: value})
    assert receipt["outcome"] == "FAIL" and receipt["metrics"] == {} and len(calls) == 1


def test_duplicate_output_fields_reject():
    with pytest.raises(ValueError, match="DUPLICATE"):
        PROBE["strict_json"](b'{"version":1,"version":1}')


def test_cli_requires_opt_in():
    with pytest.raises(SystemExit) as exc:
        PROBE["main"]([])
    assert exc.value.code == 2


def test_invalid_scope_precedes_os_read():
    with pytest.raises(Exception):
        asyncio.run(PROBE["probe"]("foreground", fake_api(), tick=lambda: pytest.fail("OS read")))


def test_worker_uses_offline_bounded_isolated_process(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "private")
    monkeypatch.setenv("PYTHONPATH", "private")
    def run(args, **kwargs):
        assert args[1:3] == ["-I", "-B"] and args[-1] == "--one-inert-proposal"
        assert kwargs["timeout"] == 180 and kwargs["stderr"] == subprocess.DEVNULL
        assert "OPENAI_API_KEY" not in kwargs["env"] and "PYTHONPATH" not in kwargs["env"]
        assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
        return SimpleNamespace(returncode=1, stdout=b'{"status":"ERROR"}')
    monkeypatch.setattr(subprocess, "run", run)
    assert PROBE["local_worker"](SimpleNamespace(python="python", worker=tmp_path / "worker.py"), {}) == {"status": "ERROR"}
