from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
from dataclasses import replace
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from computer_use_agent.config import (
    AgentConfig,
    MCPLaunchConfig,
    PolicyConfig,
    ProviderConfig,
    PrivacyConfig,
)
from computer_use_agent.desktop_mcp import (
    MCPBridgeError,
    StdioDesktopMCP,
    _InitializedClientSession,
)
from computer_use_agent.fakes import FakeApprovalPort, FakeModelProvider
from computer_use_agent.gui_host_source import collect_host_gui_observation
from computer_use_agent.runner import AgentRunner, RunnerPorts, RunFailure
from computer_use_agent.trace import read_run_record
from computer_use_agent.types import LedgerEventKind
from computer_use_mcp.contract import Image, Node, ProcRef, Rect, TreeResult, Window
from computer_use_mcp.gui_metadata import GuiMetadataError, VerifiedControl, VerifiedGuiState
from computer_use_mcp.gui_metadata_wire import SessionGuiMetadata, decode_metadata
from computer_use_mcp.server import build_server

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
NAME = "Synthetic private document"
TASK = dict(
    version=1,
    request_id="host-observation",
    target_scope="314",
    target=dict(name=NAME, role="edit"),
)


class DesktopDriver:
    """Only the OS-facing data is simulated; no native methods are available."""

    def __init__(self, fault=""):
        self.fault = fault
        self.reads = []
        self.inspections = 0
        self.resource_entered = asyncio.Event()
        self.templates = []
        self.control = VerifiedControl("1-2", "edit", NAME, (0, 0, 1, 1), True, True, True)
        self.metadata = VerifiedGuiState("314", "314", (0, 0, 1, 1), (0, 0, 1, 1), (self.control,))

    def inspect_gui_metadata(self, scope):
        assert scope == "314"
        self.inspections += 1
        if self.fault == "metadata_error":
            raise RuntimeError(NAME)
        if self.fault == "changed" and self.inspections == 2:
            return replace(self.metadata, controls=(replace(self.control, focused=False),))
        return self.metadata

    def list_windows(self):
        self.reads.append("list_windows")
        return [Window("314", NAME, Rect(0, 0, 1, 1), ProcRef(42, "editor.exe"), [], True)]

    def get_tree(self, opts):
        self.reads.append("ui_snapshot")
        assert opts.scope == "314"
        native = "changed-native" if self.fault == "ref" else "1-2"
        return TreeResult(
            [Node(native, "Edit", NAME, None, Rect(0, 0, 1, 1), ["enabled", "focused"], [])], 0
        )

    def capture_screen(self, region=None):
        self.reads.append("screenshot")
        return Image(PNG, 1, 1, 1.0)


def setup(tmp_path, monkeypatch, *, fault="", enabled=True, max_calls=3):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    config = AgentConfig(
        state_dir=tmp_path / "computer-use-agent" / "gui-host-test",
        policy_version="readonly-v1",
        provider=ProviderConfig(name="openai", model="never-called"),
        mcp=MCPLaunchConfig(
            executable=tmp_path / "not-launched.exe", args=(), cwd=tmp_path, environment={}
        ),
        policy=PolicyConfig(max_tool_calls=max_calls),
    )
    driver = DesktopDriver(fault)
    server = build_server(
        driver=driver,
        start_estop=False,
        redact_titles=[],
        audit_path=tmp_path / "actions.jsonl",
        gui_observation_enabled=enabled,
    )
    sessions = []

    @asynccontextmanager
    async def factory(launch, timeout):
        async with create_connected_server_and_client_session(server) as client:
            sessions.append(client)
            driver.templates = (await client.list_resource_templates()).resourceTemplates
            assert "gui_observation_metadata" not in {
                t.name for t in (await client.list_tools()).tools
            }

            class Client(_InitializedClientSession):
                async def call_tool(self, name, arguments=None, read_timeout_seconds=None):
                    if fault == "tool_wait" and name == "ui_snapshot":
                        driver.resource_entered.set()
                        await asyncio.Future()
                    return await super().call_tool(name, arguments, read_timeout_seconds)

                async def read_resource(self, uri):
                    if fault == "resource_wait":
                        driver.resource_entered.set()
                        await asyncio.Future()
                    result = await super().read_resource(uri)
                    if fault == "bad_wire":
                        result.contents[0].text = '{"version":1}'
                    return result

            yield Client(client, satisfied_safety_baselines=frozenset())

    class Desktop(StdioDesktopMCP):
        async def close(self):
            await super().close()
            if fault == "close_error":
                raise MCPBridgeError("MCP_TRANSPORT_ERROR")

        async def call_tool(self, call):
            result = await super().call_tool(call)
            if fault == "reconnect" and call.name == "ui_snapshot":
                async with self._operation_lock:
                    await self._drop_locked(suppress_errors=False)
                await self.discover_tools()
            return result

    desktop = Desktop(config.mcp, session_factory=factory)
    provider = FakeModelProvider(())
    runner = AgentRunner(config, RunnerPorts(provider, desktop, FakeApprovalPort()))
    return runner, desktop, driver, sessions


def test_real_runner_mcp_session_and_ref_tables_feed_the_producer(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch)
    result = asyncio.run(
        collect_host_gui_observation(runner, TASK, run_id="gui-host", max_seconds=5)
    )
    payload = result.bundle.to_dict()
    assert driver.reads == ["list_windows", "ui_snapshot", "screenshot"]
    assert driver.inspections == 2 and len(sessions) == 1
    assert len(driver.templates) == 1
    assert result.state.observation_epoch == payload["task"]["current_epoch"] == 3
    assert payload["task"]["runtime_generation"] == desktop.generation == 1
    assert result.state.budgets.tool_calls_used == 3
    assert result.state.budgets.model_turns_used == result.state.budgets.side_effects_used == 0
    events = result.state.event_log
    assert [
        e.payload["observation_epoch"] for e in events if e.kind is LedgerEventKind.OBSERVATION
    ] == [1, 2, 3]
    actual_calls = {e.identity.call_id for e in events if e.kind is LedgerEventKind.TOOL_CALL}
    assert actual_calls == {r["call_id"] for r in payload["results"].values()}
    assert payload["host_facts"]["control_states"] == {"ref_1": {"enabled": True, "visible": True}}
    assert not payload["execution_authorized"]
    record = read_run_record(runner.config.state_dir, "gui-host")
    assert record["state"]["phase"] == "SUCCESS"
    assert NAME not in json.dumps(record)
    assert desktop.closed
    with runner.prepare("Lock can be reacquired", run_id="after-host"):
        pass


@pytest.mark.parametrize("fault", ["metadata_error", "changed", "ref", "bad_wire"])
def test_metadata_failure_or_drift_rejects_and_releases_resources(tmp_path, monkeypatch, fault):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, fault=fault)
    with pytest.raises(GuiMetadataError):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="bad-host", max_seconds=5))
    assert desktop.closed and len(sessions) == 1
    assert driver.reads.count("ui_snapshot") <= 1
    record = read_run_record(runner.config.state_dir, "bad-host")
    assert record["state"]["phase"] == "FAILED"
    assert NAME not in json.dumps(record)
    with runner.prepare("Lock can be reacquired", run_id="after-failure"):
        pass


def test_resource_is_default_off_and_not_a_model_tool(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, enabled=False)
    with pytest.raises(GuiMetadataError, match="GUI_METADATA_READ_FAILED"):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="disabled"))
    assert not driver.reads and driver.inspections == 0 and desktop.closed
    assert not driver.templates


def test_real_runner_budget_rejects_third_call_before_dispatch(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, max_calls=2)
    with pytest.raises(RunFailure, match="TOOL_CALL_BUDGET_EXHAUSTED"):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="budget", max_seconds=5))
    assert driver.reads == ["list_windows", "ui_snapshot"]
    record = read_run_record(runner.config.state_dir, "budget")
    assert record["state"]["observation_epoch"] == 2
    assert record["state"]["phase"] == "FAILED" and desktop.closed


def test_unsupported_privacy_configuration_fails_before_connecting(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch)
    runner.config = replace(runner.config, privacy=PrivacyConfig(enabled=True))
    with pytest.raises(GuiMetadataError, match="GUI_HOST_CONFIGURATION_UNSUPPORTED"):
        asyncio.run(collect_host_gui_observation(runner, TASK))
    assert not sessions and not driver.reads


def test_wire_roundtrip_rejects_duplicate_keys_unknown_fields_and_wrong_scope():
    state = DesktopDriver().metadata
    encoded = SessionGuiMetadata(state, (("ref_1", "1-2"),)).encode()
    assert decode_metadata(encoded, "314").state == state
    for bad in [
        encoded.replace('"version":1', '"version":1,"version":1'),
        encoded.replace('"version":1', '"version":true'),
        encoded.replace('"enabled":true', '"enabled":1'),
        encoded[:-1] + ',"extra":1}',
        "x" * 65537,
    ]:
        with pytest.raises(GuiMetadataError):
            decode_metadata(bad, "314")
    with pytest.raises(GuiMetadataError):
        decode_metadata(encoded, "315")


def test_real_mcp_reconnect_invalidates_the_old_observation_group(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, fault="reconnect")
    with pytest.raises(GuiMetadataError, match="GUI_STAMP_CHANGED"):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="reconnect", max_seconds=5))
    assert desktop.generation == 2 and len(sessions) == 2 and desktop.closed
    assert driver.reads == ["list_windows", "ui_snapshot"]


def test_resource_timeout_has_no_retry_and_releases_lock(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, fault="resource_wait")
    desktop._timeout_seconds = 0.1
    with pytest.raises(GuiMetadataError, match="GUI_METADATA_READ_FAILED"):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="timeout"))
    assert len(sessions) == 1 and desktop.closed and not driver.reads
    with runner.prepare("Lock after timeout", run_id="after-timeout"):
        pass


def test_resource_cancellation_has_no_retry_and_releases_lock(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, fault="resource_wait")

    async def scenario():
        task = asyncio.create_task(collect_host_gui_observation(runner, TASK, run_id="cancelled"))
        await asyncio.wait_for(driver.resource_entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert len(sessions) == 1 and desktop.closed and not driver.reads
    assert read_run_record(runner.config.state_dir, "cancelled")["state"]["phase"] == "CANCELLED"
    with runner.prepare("Lock after cancellation", run_id="after-cancelled"):
        pass


def test_invalid_task_does_not_acquire_lock_or_connect(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch)
    with pytest.raises(GuiMetadataError, match="GUI_TASK_INVALID"):
        asyncio.run(collect_host_gui_observation(runner, None))
    assert not sessions and not runner.config.state_dir.exists()
    with runner.prepare("Lock after validation failure", run_id="after-invalid"):
        pass


def test_cleanup_failure_cannot_leave_a_success_checkpoint(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, fault="close_error")
    with pytest.raises(MCPBridgeError):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="close-error", max_seconds=5))
    assert read_run_record(runner.config.state_dir, "close-error")["state"]["phase"] == "FAILED"
    with runner.prepare("Lock after cleanup failure", run_id="after-close-error"):
        pass


def test_invalid_run_identity_cannot_leak_a_lock(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        asyncio.run(collect_host_gui_observation(runner, TASK, run_id="invalid/run"))
    assert not sessions
    with runner.prepare("Lock after invalid identity", run_id="after-bad-id"):
        pass


def test_cancelled_tool_preserves_runner_unknown_outcome_without_replay(tmp_path, monkeypatch):
    runner, desktop, driver, sessions = setup(tmp_path, monkeypatch, fault="tool_wait")

    async def scenario():
        task = asyncio.create_task(collect_host_gui_observation(runner, TASK, run_id="tool-cancel"))
        await asyncio.wait_for(driver.resource_entered.wait(), 5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    record = read_run_record(runner.config.state_dir, "tool-cancel")
    assert record["state"]["phase"] == "UNKNOWN_OUTCOME"
    assert record["state"]["observation_epoch"] == 1
    assert record["state"]["budgets"]["tool_calls_used"] == 2
    assert driver.reads == ["list_windows"] and len(sessions) == 1 and desktop.closed
    with runner.prepare("Lock after uncertain cancellation", run_id="after-tool-cancel"):
        pass
