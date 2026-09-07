"""Opt-in one-use fixture action through the existing Host and safe-local MCP."""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import runpy
import sys
import time
from uuid import uuid4

from computer_use_agent.config import PolicyConfig
from computer_use_agent.desktop_mcp import StdioDesktopMCP
from computer_use_agent.fakes import FakeModelProvider
from computer_use_agent.gui_host_source import _RunnerSource
from computer_use_agent.gui_observation import collect_gui_observation
from computer_use_agent.runner import AgentRunner, RunnerPorts, RunFailure
from computer_use_agent.tool_registry import verify_discovered_tools
from computer_use_agent.trace import RunPhase, RunRecorder, read_run_record
from computer_use_agent.types import CallIdentity, ToolCall, PolicyDecision, PolicyDecisionKind

ROOT = Path(__file__).resolve().parents[1]
INERT = runpy.run_path(str(ROOT / "scripts/probe_gui_inert_model.py"))
READ = INERT["READ"]
FIXTURE = runpy.run_path(str(ROOT / "scripts/gui_action_fixture.py"))


def config_for():
    base = READ["config_for"]()
    return replace(base, state_dir=base.state_dir.parent / "gui-single-action",
                   policy_version="gui-single-action-v1",
                   policy=PolicyConfig(mode="approved_actions", max_model_turns=1,
                                       max_tool_calls=10, max_side_effects=1),
                   mcp=replace(base.mcp, environment={
                       "CUMCP_ALLOWLIST": "pythonw.exe", "CUMCP_MODE": "safe_local",
                       "CUMCP_UIA_ACTIONS": "1", "CUMCP_DANGEROUS_CONFIRM": "1",
                   }))


def fixture(bundle, scope, *, completed=False):
    payload = bundle.to_dict()
    if not any(line.startswith("* " + scope + " | ") and
               line.endswith(' | "' + FIXTURE["TITLE"] + '"')
               for line in payload["results"]["windows"]["text"].splitlines()):
        raise ValueError("FIXTURE_MISMATCH")
    expected = FIXTURE["COMPLETED"] if completed else FIXTURE["TARGET"]
    states = payload["host_facts"]["control_states"]
    if (len(states) != 1 or next(iter(states.values())) != dict(enabled=not completed, visible=True)
        or f'button "{expected}"' not in payload["results"]["snapshot"]["text"]
        or payload["execution_authorized"] is not False):
        raise ValueError("FIXTURE_STATE")
    return payload


def stable_context(issued, fresh):
    # Only observation epochs may advance; every semantic field, ref and pixel stays identical.
    old, new = copy.deepcopy(issued), copy.deepcopy(fresh)
    if (type(old["current_epoch"]) is not int or type(new["current_epoch"]) is not int
        or new["current_epoch"] != old["current_epoch"] + 3
        or old["observation"]["epoch"] != old["current_epoch"]
        or new["observation"]["epoch"] != new["current_epoch"]):
        raise ValueError("EPOCH_MISMATCH")
    for context in (old, new):
        context.pop("current_epoch")
        context["observation"].pop("epoch")
    if old != new:
        raise ValueError("CONTEXT_CHANGED")


class FixturePermit:
    """Host-owned one-use preauthorization from the explicit fixture-only CLI opt-in."""
    def __init__(self):
        self.armed = None
        self.used = False
        self.requests = 0

    async def request_approval(self, request):
        self.requests += 1
        allowed = False
        if self.armed is not None and not self.used:
            self.used = True  # Consume even on a mismatch or failed fresh check.
            call, source, metadata, tick, before, deadline = self.armed
            if (request.tool_name == "click" and request.identity == call.identity
                and request.call_digest == call.digest and request.binding is not None
                and tick() == before and time.monotonic() <= deadline):
                current = await asyncio.wait_for(source.inspect(source.scope), timeout=2)
                allowed = current == metadata and tick() == before and time.monotonic() <= deadline
        return PolicyDecision(request.request_id, request.identity, request.call_digest,
                              PolicyDecisionKind.ALLOW if allowed else PolicyDecisionKind.DENY,
                              "explicit_single_fixture_opt_in" if allowed else "fixture_permit_rejected")


async def probe(scope, api, *, tick=READ["input_tick"], runner=None, worker=INERT["local_worker"]):
    task = READ["task_for"](scope)
    run_id = "gui-action-" + uuid4().hex
    task["request_id"] = run_id
    if runner is None:
        config = config_for()
        runner = AgentRunner(config, RunnerPorts(FakeModelProvider(), StdioDesktopMCP(config.mcp), FixturePermit()))
    if (not isinstance(runner.ports.desktop, StdioDesktopMCP)
        or not isinstance(runner.ports.approvals, FixturePermit)
        or runner.config.continuation.enabled or runner.config.privacy.enabled
        or any(p is not None for p in (runner.ports.control, runner.ports.presence, runner.ports.progress))):
        raise ValueError("UNSUPPORTED_CONFIGURATION")
    permit = runner.ports.approvals
    desktop = runner.ports.desktop
    before = tick()
    prepared = runner.prepare("One explicitly authorized synthetic fixture click", run_id=run_id)
    recorder = RunRecorder(runner.config.state_dir, run_id)
    source = _RunnerSource(runner, desktop, prepared.state, recorder, scope)
    outcome, code, calls, requests, metrics = "FAIL", "OBSERVATION_REJECTED", 0, 0, {}
    verified, dispatched, closed = False, False, False
    try:
        recorder.start(source.run_state)
        recorder.record(source.run_state, RunPhase.OBSERVING)
        verify_discovered_tools(await desktop.discover_tools())
        recorder.record(source.run_state, RunPhase.PLANNING)
        first = await collect_gui_observation(task, source, max_seconds=5)
        payload = fixture(first, scope)
        first_metadata = source.metadata.state
        issued = api.project(payload["task"], payload["results"], first.image, payload["host_facts"])["context"]
        image_sha = hashlib.sha256(first.image).hexdigest()
        request = dict(version=1, request_id=task["request_id"], context_digest=api.digest(issued),
                       image_base64=base64.b64encode(first.image).decode())
        if len(first.image) > 8 * 1024 * 1024 or tick() != before:
            raise ValueError("INPUT_OR_IMAGE_REJECTED")
        code, calls, requests = "WORKER_REJECTED", 1, None
        response = await asyncio.to_thread(worker, api, request)
        INERT["validate_response"](response, request, image_sha)
        requests = 1
        metrics = {k: response[k] for k in ("model_id", "revision", "adapter_sha256", "image_sha256",
                   "input_tokens", "output_tokens", "generation_seconds", "peak_allocated_bytes")}
        metrics["raw_output_sha256"] = hashlib.sha256(response["raw_output"].encode()).hexdigest()
        code = "PROPOSAL_REJECTED"
        proposal = api.compile(issued, copy.deepcopy(issued), {k: response[k] for k in
                               ("request_id", "context_digest", "raw_output")}).to_dict()
        if proposal["action"] != "click_ref" or proposal["execution_authorized"] is not False:
            raise ValueError("NO_CLICK_PROPOSAL")
        if tick() != before:
            raise ValueError("INPUT_CHANGED")
        code = "REVALIDATION_REJECTED"
        fresh = await collect_gui_observation(task, source, max_seconds=5)
        payload = fixture(fresh, scope)
        current = api.project(payload["task"], payload["results"], fresh.image, payload["host_facts"])["context"]
        stable_context(issued, current)
        if source.metadata.state != first_metadata or tick() != before:
            raise ValueError("NATIVE_OR_INPUT_CHANGED")
        # Original reply stays bound to issued; stable fresh facts permit the same ref.
        call = ToolCall(CallIdentity(run_id, "fixture_action", uuid4().hex), "click", proposal["arguments"])
        if set(call.arguments) != {"ref"}:
            raise ValueError("REF_REQUIRED")
        permit.armed = (call, source, source.metadata.state, tick, before, time.monotonic() + 2)
        code = "ACTION_REJECTED"
        result = await runner._execute_requested_call_boundary(
            source.run_state, call, grounding=source.grounding, recorder=recorder, continuation=None,
        )
        source.run_state, source.grounding = result.state, result.grounding
        dispatched = result.result.dispatch.value != "not_dispatched"
        if not result.result.ok or result.abandon_remaining_calls:
            raise ValueError("ACTION_NOT_SUCCESSFUL")
        code = "POSTCONDITION_REJECTED"
        after = await collect_gui_observation(task, source, max_seconds=5)
        fixture(after, scope, completed=True)
        post = source.metadata.state
        if (len(post.controls) != 1 or post.controls[0].native_id != first_metadata.controls[0].native_id
            or post.controls[0].name != FIXTURE["COMPLETED"] or post.controls[0].enabled):
            raise ValueError("POSTCONDITION_MISMATCH")
        if tick() != before:
            raise ValueError("INPUT_CHANGED")
        verified = True
        await desktop.close()
        closed = True
        outcome, code = "PASS", "SINGLE_ACTION_VERIFIED"
    except RunFailure as exc:
        source.run_state = exc.state
        if exc.code == "UNKNOWN_OUTCOME":
            outcome, code = "UNKNOWN_OUTCOME", "UNKNOWN_OUTCOME"
            dispatched = None
    except asyncio.CancelledError:
        outcome, code = "INVALID", "CANCELLED"
        raise
    except Exception:
        pass  # Raw UI/model/error text never enters the safe receipt.
    finally:
        try:
            if not closed:
                try:
                    await desktop.close()
                except Exception:
                    outcome, code = "FAIL", "CLEANUP_FAILED"
            if tick() != before:
                outcome, code = "INVALID", "INPUT_CHANGED"
            phase = (RunPhase.SUCCESS if outcome == "PASS" else RunPhase.UNKNOWN_OUTCOME
                     if outcome == "UNKNOWN_OUTCOME" else RunPhase.FAILED)
            # The sole boundary already persists a cancelled dispatch as UNKNOWN;
            # never overwrite that newer ledger with the caller's pre-call state.
            if recorder.phase is not RunPhase.UNKNOWN_OUTCOME:
                recorder.record(source.run_state, phase)
        finally:
            prepared.close()
    record = read_run_record(runner.config.state_dir, run_id)["state"]
    budgets = record["budgets"]
    return dict(version=1, run_id=run_id, outcome=outcome, code=code, phase=record["phase"],
                tool_calls=budgets["tool_calls_used"], host_model_turns=budgets["model_turns_used"],
                side_effects=budgets["side_effects_used"], observation_epoch=record["observation_epoch"],
                worker_invocations=calls, model_requests=requests, approval_requests=permit.requests,
                action_dispatched=dispatched, postcondition_verified=verified, input_unchanged=tick() == before,
                backend="uia", metrics=metrics, raw_observations_exported=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-one-fixture-click", action="store_true", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--consumer-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        READ["task_for"](args.scope)
        if sys.platform != "win32":
            raise ValueError("WINDOWS_REQUIRED")
        receipt = asyncio.run(probe(args.scope, INERT["load_consumer"](args.consumer_root)))
    except Exception:
        receipt = dict(version=1, outcome="ERROR", code="PROBE_UNAVAILABLE")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["outcome"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
