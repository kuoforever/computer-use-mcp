"""Opt-in staged diagnostic: real read-only capture, one local inert proposal."""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
from dataclasses import replace
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import runpy
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

from computer_use_agent.desktop_mcp import StdioDesktopMCP
from computer_use_agent.fakes import FakeApprovalPort, FakeModelProvider
from computer_use_agent.gui_host_source import collect_host_gui_observation
from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record

ROOT = Path(__file__).resolve().parents[1]
READ = runpy.run_path(str(ROOT / "scripts/probe_gui_readonly.py"))
PINS = runpy.run_path(str(ROOT / "scripts/validate_gui_observation_handoff.py"))["CONSUMER_FILES"]
MODEL = "mPLUG/GUI-Owl-1.5-4B-Instruct"
REVISION = "3f061c2c562cc860c42bf32542a70e07a7ff4840"
ADAPTER = "3654fc21a2cea688754b800f9b10a49ae5e931f6ceb7eec080bfd83931fd0445"


def load_consumer(root):
    root = root.resolve(strict=True)
    for name, expected in PINS.items():
        source = root / "src/fullcycle_bridge" / name
        if hashlib.sha256(source.read_text(encoding="utf-8").encode()).hexdigest() != expected:
            raise ValueError("CONSUMER_SOURCE_MISMATCH")
    python = root / "work/gui-owl-lora-env/Scripts/python.exe"
    worker = root / "scripts/probe_gui_owl_single.py"
    if not python.is_file() or not worker.is_file():
        raise ValueError("WORKER_UNAVAILABLE")
    sys.path.insert(0, str(root / "src"))
    projection = importlib.import_module("fullcycle_bridge.gui_observation_projection")
    native = importlib.import_module("fullcycle_bridge.native_gui_proposal")
    for module in (projection, native):
        if Path(module.__file__).resolve().parent != root / "src/fullcycle_bridge":
            raise ValueError("CONSUMER_IMPORT_MISMATCH")
    return SimpleNamespace(project=projection.project_observation, digest=native.context_digest,
                           compile=native.compile_native_response, python=python, worker=worker)


def local_worker(api, request):
    # Bootstrap-only environment; never forward credentials or Python injection paths.
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA"}
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    env.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1")
    completed = subprocess.run(
        [str(api.python), "-I", "-B", str(api.worker), "--one-inert-proposal"],
        input=json.dumps(request).encode(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        cwd=api.worker.parent.parent, env=env, timeout=180, check=False,
    )
    if len(completed.stdout) > 16_384:
        raise ValueError("WORKER_OUTPUT_SIZE")
    response = strict_json(completed.stdout)
    if completed.returncode and response.get("status") != "ERROR":
        raise ValueError("WORKER_EXIT")
    return response


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("DUPLICATE_FIELD")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique)


def validate_response(response, request, image_sha):
    fields = {"version", "status", "request_id", "context_digest", "raw_output", "model_requests",
              "model_id", "revision", "adapter_sha256", "image_sha256", "input_tokens",
              "output_tokens", "generation_seconds", "peak_allocated_bytes"}
    if type(response) is not dict or set(response) != fields:
        raise ValueError("WORKER_FIELDS")
    for key, value in dict(version=1, status="OK", request_id=request["request_id"],
                           context_digest=request["context_digest"], image_sha256=image_sha,
                           model_requests=1, model_id=MODEL, revision=REVISION,
                           adapter_sha256=ADAPTER).items():
        if type(response[key]) is not type(value) or response[key] != value:
            raise ValueError("WORKER_BINDING")
    for key, limit in [("input_tokens", 4096), ("output_tokens", 192),
                       ("peak_allocated_bytes", 15_000_000_000)]:
        if type(response[key]) is not int or not 0 < response[key] <= limit:
            raise ValueError("WORKER_RESOURCE")
    seconds = response["generation_seconds"]
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 60:
        raise ValueError("WORKER_RESOURCE")
    if type(response["raw_output"]) is not str or len(response["raw_output"].encode()) > 4096:
        raise ValueError("WORKER_OUTPUT_SIZE")


async def probe(scope, api, *, tick=READ["input_tick"], runner=None, worker=local_worker):
    task = READ["task_for"](scope)
    run_id = "gui-inert-" + uuid4().hex
    task["request_id"] = run_id
    if runner is None:
        config = READ["config_for"]()
        config = replace(config, state_dir=config.state_dir.parent / "gui-inert-probe")
        runner = AgentRunner(config, RunnerPorts(
            FakeModelProvider(), StdioDesktopMCP(config.mcp), FakeApprovalPort(),
        ))
    before = tick()
    outcome, code, calls, requests, metrics = "FAIL", "OBSERVATION_REJECTED", 0, 0, {}
    try:
        collected = await collect_host_gui_observation(runner, task, run_id=run_id, max_seconds=5)
        payload, image = collected.bundle.to_dict(), collected.bundle.image
        if (len(payload["host_facts"]["control_states"]) != 1 or
            not any(line.startswith("* " + scope + " | ") and
                    line.endswith(' | "' + READ["TITLE"] + '"')
                    for line in payload["results"]["windows"]["text"].splitlines()) or
            f'button "{READ["TARGET"]}"' not in payload["results"]["snapshot"]["text"] or
            payload["execution_authorized"] is not False):
            code = "FIXTURE_MISMATCH"
        else:
            code = "PROJECTION_REJECTED"
            projected = api.project(payload["task"], payload["results"], image, payload["host_facts"])
            if projected["status"] != "projected" or projected["execution_authorized"] is not False:
                raise ValueError("PROJECTION_INCOMPLETE")
            context = projected["context"]
            # This copy is the captured snapshot, NOT a fresh post-inference desktop read.
            captured = copy.deepcopy(context)
            image_sha = hashlib.sha256(image).hexdigest()
            request = dict(version=1, request_id=task["request_id"],
                           context_digest=api.digest(context), image_base64=base64.b64encode(image).decode())
            if len(image) > 8 * 1024 * 1024:
                raise ValueError("IMAGE_SIZE")
            code, calls, requests = "WORKER_REJECTED", 1, None
            response = worker(api, request)  # Exactly one invocation, no retry path.
            if (type(response) is dict and set(response) == {"version", "status", "code", "model_requests"}
                and type(response["version"]) is int and response["version"] == 1
                and response["status"] == "ERROR" and response["code"] == "MODEL_WORKER_FAILED"
                and type(response["model_requests"]) is int and response["model_requests"] in (0, 1)):
                requests = response["model_requests"]
                raise ValueError("MODEL_WORKER_FAILED")
            validate_response(response, request, image_sha)
            requests = 1
            metrics = {k: response[k] for k in ("input_tokens", "output_tokens", "generation_seconds",
                       "peak_allocated_bytes", "image_sha256", "adapter_sha256", "model_id", "revision")}
            metrics["raw_output_sha256"] = hashlib.sha256(response["raw_output"].encode()).hexdigest()
            code = "PROPOSAL_REJECTED"
            proposal = api.compile(context, captured, {k: response[k] for k in
                                   ("request_id", "context_digest", "raw_output")}).to_dict()
            if proposal["execution_authorized"] is not False:
                raise ValueError("EXECUTION_AUTHORITY")
            if proposal["action"] == "click_ref":
                outcome, code = "PASS", "CLICK_REF_ACCEPTED"
            elif proposal["action"] == "stop":
                code = "MODEL_STOPPED"
    except Exception:
        pass  # Fixed-stage errors only; never persist raw model/UI/exception text.
    after = tick()
    if before != after:
        outcome, code = "INVALID", "INPUT_CHANGED"
    record = read_run_record(runner.config.state_dir, run_id)["state"]
    budgets = record["budgets"]
    return dict(version=1, run_id=run_id, outcome=outcome, code=code,
                input_unchanged=before == after, phase=record["phase"],
                observation_epoch=record["observation_epoch"], tool_calls=budgets["tool_calls_used"],
                host_model_turns=budgets["model_turns_used"], side_effects=budgets["side_effects_used"],
                worker_invocations=calls, model_requests=requests, metrics=metrics,
                execution_authorized=False, raw_observations_exported=False,
                post_inference_desktop_revalidated=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-inert-proposal", action="store_true", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--consumer-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        READ["task_for"](args.scope)
        if sys.platform != "win32":
            raise ValueError("WINDOWS_REQUIRED")
        api = load_consumer(args.consumer_root)
        receipt = asyncio.run(probe(args.scope, api))
    except Exception:
        receipt = dict(version=1, outcome="ERROR", code="PROBE_UNAVAILABLE")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
