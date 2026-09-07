from dataclasses import replace
import asyncio
from pathlib import Path
import runpy

import pytest

from computer_use_agent.config import PolicyConfig
from computer_use_agent.runner import AgentRunner
from computer_use_mcp.contract import ProcRef, Rect, Window
from computer_use_mcp.gui_metadata import GuiMetadataError

ROOT = Path(__file__).resolve().parents[2]
PROBE = runpy.run_path(str(ROOT / "scripts/probe_gui_readonly.py"))
HOST = runpy.run_path(str(Path(__file__).with_name("test_gui_host_source.py")))


def setup_probe(tmp_path, monkeypatch, *, fault=""):
    monkeypatch.setitem(HOST["setup"].__globals__, "NAME", PROBE["TARGET"])
    runner, desktop, driver, _ = HOST["setup"](tmp_path, monkeypatch, fault=fault)
    driver.control = replace(driver.control, role="button")
    driver.metadata = replace(driver.metadata, controls=(driver.control,))
    get_tree = driver.get_tree

    def button_tree(options):
        tree = get_tree(options)
        for node in tree.nodes:
            node.role = "Button"
        return tree

    driver.get_tree = button_tree
    driver.list_windows = lambda: [Window(
        "314", PROBE["TITLE"], Rect(0, 0, 1, 1), ProcRef(42, "fixture.exe"), [], True,
    )]
    config = replace(runner.config, policy=PolicyConfig(
        max_model_turns=0, max_tool_calls=3, max_side_effects=0,
    ))
    return AgentRunner(config, runner.ports), desktop


def test_probe_uses_real_collector_and_exports_only_safe_counts(tmp_path, monkeypatch):
    runner, _ = setup_probe(tmp_path, monkeypatch)
    receipt = asyncio.run(PROBE["probe"]("314", tick=lambda: 7, runner=runner))
    assert receipt["outcome"] == "PASS"
    assert receipt["tool_calls"] == receipt["observation_epoch"] == 3
    assert receipt["model_turns"] == receipt["side_effects"] == 0
    assert receipt["control_count"] == 1
    assert receipt["raw_observations_exported"] is False
    assert PROBE["TARGET"] not in str(receipt) and PROBE["TITLE"] not in str(receipt)
    assert not runner.ports.provider.calls and not runner.ports.approvals.requests


def test_input_change_invalidates_even_successful_collection(tmp_path, monkeypatch):
    runner, _ = setup_probe(tmp_path, monkeypatch)
    ticks = iter([7, 8])
    receipt = asyncio.run(PROBE["probe"]("314", tick=lambda: next(ticks), runner=runner))
    assert receipt["outcome"] == "INVALID" and receipt["code"] == "INPUT_CHANGED"
    assert receipt["control_count"] == 0 and receipt["phase"] == "SUCCESS"


def test_metadata_failure_is_not_promoted_or_disclosed(tmp_path, monkeypatch):
    runner, _ = setup_probe(tmp_path, monkeypatch, fault="metadata_error")
    receipt = asyncio.run(PROBE["probe"]("314", tick=lambda: 7, runner=runner))
    assert receipt["outcome"] == "FAIL" and receipt["tool_calls"] == 0
    assert receipt["code"] == "OBSERVATION_REJECTED" and receipt["phase"] == "FAILED"
    assert PROBE["TARGET"] not in str(receipt)


def test_wrong_fixture_does_not_pass(tmp_path, monkeypatch):
    runner, desktop = setup_probe(tmp_path, monkeypatch)
    monkeypatch.setitem(PROBE["probe"].__globals__, "TITLE", "Different fixture")
    receipt = asyncio.run(PROBE["probe"]("314", tick=lambda: 7, runner=runner))
    assert receipt["outcome"] == "FAIL" and receipt["code"] == "FIXTURE_MISMATCH"
    assert desktop._session is None


@pytest.mark.parametrize("scope", [None, "foreground", "0", "-1", "314/../../x"])
def test_bad_scope_rejects_before_tick_or_connection(scope):
    with pytest.raises(GuiMetadataError):
        asyncio.run(PROBE["probe"](scope, tick=lambda: pytest.fail("OS read")))


def test_explicit_opt_in_is_required():
    with pytest.raises(SystemExit) as exc:
        PROBE["main"]([])
    assert exc.value.code == 2
    config = PROBE["config_for"]()
    assert config.policy.mode == "read_only"
    assert config.policy.max_model_turns == config.policy.max_side_effects == 0
    assert config.policy.max_tool_calls == 3
    assert "OPENAI_API_KEY" not in config.mcp.child_environment()


def test_fixture_requires_opt_in_before_native_imports():
    fixture = runpy.run_path(str(ROOT / "scripts/gui_readonly_fixture.py"))
    with pytest.raises(SystemExit) as exc:
        fixture["main"]([])
    assert exc.value.code == 2
