import asyncio
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest

from computer_use_agent.runner import AgentRunner, RunnerPorts
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import ToolResult, ToolResultStatus, DispatchCertainty
from computer_use_mcp.contract import Node, TreeResult, Window, Rect, ProcRef

ROOT = Path(__file__).resolve().parents[2]
PROBE = runpy.run_path(str(ROOT / "scripts/probe_gui_single_action.py"))
HOST = runpy.run_path(str(Path(__file__).with_name("test_gui_host_source.py")))


def setup(tmp_path, monkeypatch, *, fault="", action="click_ref"):
    runner, desktop, driver, sessions = HOST["setup"](tmp_path, monkeypatch)
    driver.control = replace(driver.control, role="button", name=PROBE["FIXTURE"]["TARGET"])
    driver.metadata = replace(driver.metadata, controls=(driver.control,))
    driver.list_windows = lambda: [Window("314", PROBE["FIXTURE"]["TITLE"], Rect(0, 0, 1, 1),
                                         ProcRef(42, "fixture.exe"), [], True)]

    def tree(opts):
        c = driver.metadata.controls[0]
        return TreeResult([Node(c.native_id, "Button", c.name, None, Rect(0, 0, 1, 1),
                               ["enabled", "focused"] if c.enabled else ["disabled", "focused"], [])], 0)
    driver.get_tree = tree
    config = replace(PROBE["config_for"](), state_dir=runner.config.state_dir, mcp=runner.config.mcp)
    if fault == "budget":
        config = replace(config, policy=replace(config.policy, max_side_effects=0))
    if fault == "verification_capacity":
        config = replace(config, policy=replace(config.policy, max_model_turns=0))
    if fault == "policy":
        config = replace(config, policy=replace(config.policy, mode="read_only"))
    permit = PROBE["FixturePermit"]()
    approve = permit.request_approval
    async def approval(request):
        if fault == "approval_replay":
            await approve(request)
        elif fault == "approval_binding":
            request = replace(request, call_digest="0" * 64)
        elif fault == "approval_input":
            ticks[0] = 8
        return await approve(request)
    permit.request_approval = approval
    runner = AgentRunner(config, RunnerPorts(runner.ports.provider, desktop, permit))
    original_call = desktop.call_tool
    clicks = []
    async def call(call):
        if call.name != "click":
            return await original_call(call)
        record = read_run_record(config.state_dir, call.identity.run_id)["state"]
        assert record["phase"] == "EXECUTING" and record["budgets"]["side_effects_used"] == 1
        assert permit.used and permit.requests == 1 and set(call.arguments) == {"ref"}
        clicks.append(call)
        if fault == "unknown":
            return ToolResult(call.identity, "click", ToolResultStatus.UNKNOWN_OUTCOME,
                              DispatchCertainty.UNKNOWN, code="UNKNOWN_OUTCOME")
        if fault != "no_effect":
            driver.metadata = replace(driver.metadata, controls=(replace(driver.control,
                name=PROBE["FIXTURE"]["COMPLETED"], enabled=False),))
        return ToolResult(call.identity, "click", ToolResultStatus.SUCCESS, DispatchCertainty.DISPATCHED)
    desktop.call_tool = call
    def project(task, results, image, facts):
        return {"context": dict(task, observation=dict(epoch=task["current_epoch"],
                image=hashlib.sha256(image).hexdigest(), facts=facts["control_states"]))}
    def compile(issued, current, response):
        return SimpleNamespace(to_dict=lambda: dict(action=action, arguments={"ref": "ref_1"},
                                                    execution_authorized=False))
    api = SimpleNamespace(project=project, compile=compile, digest=lambda _: "a" * 64)
    ticks = [7]
    calls = []
    def worker(api, request):
        calls.append(request)
        assert desktop._session is not None
        if fault == "input":
            ticks[0] = 8
        if fault == "native":
            driver.control = replace(driver.control, native_id="changed")
            driver.metadata = replace(driver.metadata, controls=(driver.control,))
        if fault == "worker":
            raise ValueError("private model failure")
        return dict(version=1, status="OK", request_id=request["request_id"],
                    context_digest=request["context_digest"], raw_output="synthetic private response",
                    model_requests=1, model_id=PROBE["INERT"]["MODEL"], revision=PROBE["INERT"]["REVISION"],
                    adapter_sha256=PROBE["INERT"]["ADAPTER"],
                    image_sha256=hashlib.sha256(base64.b64decode(request["image_base64"])).hexdigest(),
                    input_tokens=100, output_tokens=20, generation_seconds=2.0, peak_allocated_bytes=1000)
    return runner, desktop, api, worker, ticks, calls, clicks, sessions


def execute(tmp_path, monkeypatch, **kwargs):
    runner, desktop, api, worker, ticks, calls, clicks, sessions = setup(tmp_path, monkeypatch, **kwargs)
    receipt = asyncio.run(PROBE["probe"]("314", api, runner=runner, worker=worker, tick=lambda: ticks[0]))
    assert desktop.closed and len(sessions) == 1 and not runner.ports.provider.calls
    assert "private" not in json.dumps(receipt)
    with runner.prepare("lock released", run_id="after-probe"):
        pass
    return receipt, calls, clicks


def test_real_host_boundary_records_single_action_and_readback(tmp_path, monkeypatch):
    receipt, calls, clicks = execute(tmp_path, monkeypatch)
    assert receipt["outcome"] == "PASS" and receipt["postcondition_verified"]
    assert len(calls) == len(clicks) == receipt["approval_requests"] == 1
    assert receipt["tool_calls"] == 10 and receipt["observation_epoch"] == 9
    assert receipt["side_effects"] == 1 and receipt["host_model_turns"] == 0


@pytest.mark.parametrize("fault", ["native", "input", "worker", "policy", "budget", "verification_capacity",
                                   "approval_replay", "approval_binding", "approval_input"])
def test_pre_dispatch_failures_never_click(tmp_path, monkeypatch, fault):
    receipt, calls, clicks = execute(tmp_path, monkeypatch, fault=fault)
    assert len(calls) == 1 and not clicks and receipt["outcome"] != "PASS"
    assert receipt["side_effects"] == 0
    if fault == "input":
        assert receipt["outcome"] == "INVALID"


def test_stop_proposal_never_clicks(tmp_path, monkeypatch):
    receipt, _, clicks = execute(tmp_path, monkeypatch, action="stop")
    assert not clicks and receipt["code"] == "PROPOSAL_REJECTED"


def test_successful_dispatch_without_state_change_fails(tmp_path, monkeypatch):
    receipt, _, clicks = execute(tmp_path, monkeypatch, fault="no_effect")
    assert len(clicks) == 1 and receipt["action_dispatched"]
    assert receipt["outcome"] == "FAIL" and not receipt["postcondition_verified"]


def test_unknown_action_outcome_never_replays(tmp_path, monkeypatch):
    receipt, calls, clicks = execute(tmp_path, monkeypatch, fault="unknown")
    assert len(calls) == len(clicks) == 1
    assert receipt["outcome"] == receipt["phase"] == "UNKNOWN_OUTCOME"
    assert receipt["action_dispatched"] is None and receipt["side_effects"] == 1


@pytest.mark.parametrize("change", ["image", "native_ref", "generation", "epoch"])
def test_revalidation_is_exact_except_three_new_observations(change):
    issued = dict(current_epoch=3, runtime_generation=1, observation=dict(epoch=3, image="a", ref="ref_1"))
    fresh = dict(current_epoch=6, runtime_generation=1, observation=dict(epoch=6, image="a", ref="ref_1"))
    PROBE["stable_context"](issued, fresh)
    if change == "image":
        fresh["observation"]["image"] = "b"
    elif change == "native_ref":
        fresh["observation"]["ref"] = "ref_2"
    elif change == "generation":
        fresh["runtime_generation"] = 2
    else:
        fresh["current_epoch"] = fresh["observation"]["epoch"] = 7
    with pytest.raises(ValueError):
        PROBE["stable_context"](issued, fresh)


def test_explicit_action_and_fixture_optins_required():
    for entry in (PROBE["main"], PROBE["FIXTURE"]["main"]):
        with pytest.raises(SystemExit) as exc:
            entry([])
        assert exc.value.code == 2
    config = PROBE["config_for"]()
    assert config.policy.max_side_effects == 1 and config.policy.require_approval_for_actions
    assert config.mcp.environment["CUMCP_MODE"] == "safe_local"
    assert config.mcp.environment["CUMCP_UIA_ACTIONS"] == "1"
