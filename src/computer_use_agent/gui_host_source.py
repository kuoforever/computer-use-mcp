"""Explicit internal observation-only Host run; no provider or CLI integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Mapping
from uuid import uuid4

from computer_use_mcp.gui_metadata import GuiMetadataError, VerifiedGuiState
from computer_use_mcp.gui_metadata_wire import SessionGuiMetadata

from .desktop_mcp import MCPBridgeError, StdioDesktopMCP
from .grounding import GroundingState
from .gui_observation import (
    ObservationBundle,
    StampedObservation,
    collect_gui_observation,
    validate_gui_task,
)
from .runner import AgentRunner, RunFailure
from .tool_registry import (
    ToolRegistryMismatchError,
    configured_optional_tool_names,
    verify_discovered_tools,
)
from .trace import RunPhase, RunRecorder
from .types import CallIdentity, RunState, ToolCall


@dataclass(frozen=True)
class HostGuiObservation:
    bundle: ObservationBundle
    state: RunState


class _RunnerSource:
    def __init__(
        self,
        runner: AgentRunner,
        desktop: StdioDesktopMCP,
        state: RunState,
        recorder: RunRecorder,
        scope: str,
    ) -> None:
        self.runner, self.desktop, self.run_state = runner, desktop, state
        self.recorder, self.scope = recorder, scope
        self.grounding = GroundingState()
        self.metadata: SessionGuiMetadata | None = None

    def state(self) -> tuple[int, int]:
        return self.desktop.generation, self.run_state.observation_epoch

    async def inspect(self, scope: str) -> VerifiedGuiState:
        if scope != self.scope:
            raise GuiMetadataError("GUI_SCOPE_INVALID")
        self.metadata = await self.desktop.inspect_gui_metadata(scope)
        return self.metadata.state

    async def resolve_ref(self, ref: str) -> str:
        if self.metadata is None:
            raise GuiMetadataError("GUI_REF_MISMATCH")
        return dict(self.metadata.refs).get(ref, "")

    async def read(self, tool: str, arguments: Mapping[str, str]) -> StampedObservation:
        expected = {"list_windows": {}, "ui_snapshot": {"scope": self.scope}, "screenshot": {}}
        if tool not in expected or dict(arguments) != expected[tool]:
            raise GuiMetadataError("GUI_CALL_UNSUPPORTED")
        call = ToolCall(
            CallIdentity(self.run_state.run_id, "gui_observation", uuid4().hex), tool, arguments
        )
        try:
            outcome = await self.runner._execute_requested_call_boundary(
                self.run_state,
                call,
                grounding=self.grounding,
                recorder=self.recorder,
                continuation=None,
            )
        except RunFailure as exc:
            self.run_state = exc.state
            raise
        self.run_state, self.grounding = outcome.state, outcome.grounding
        if outcome.abandon_remaining_calls:
            raise GuiMetadataError("GUI_CALL_INTERRUPTED")
        return StampedObservation(call, outcome.result, *self.state())


async def collect_host_gui_observation(
    runner: AgentRunner, task: dict, *, run_id: str | None = None, max_seconds: float = 2.0
) -> HostGuiObservation:
    """Own lock/recorder/discovery/cleanup and reuse the ordinary Runner boundary."""
    task = validate_gui_task(task)
    if type(max_seconds) not in {int, float} or not 0 < max_seconds <= 5:
        raise GuiMetadataError("GUI_BUDGET_INVALID")
    ports = runner.ports
    if (
        ports is None
        or not isinstance(ports.desktop, StdioDesktopMCP)
        or runner.config.continuation.enabled
        or runner.config.privacy.enabled
        or any(p is not None for p in (ports.control, ports.presence, ports.progress))
    ):
        raise GuiMetadataError("GUI_HOST_CONFIGURATION_UNSUPPORTED")
    # This narrow internal run is not a general Runner substitute. Unsupported
    # lifecycle/privacy configurations reject before any connection or OS read.
    desktop = ports.desktop
    resolved_run_id = run_id or uuid4().hex
    recorder = RunRecorder(runner.config.state_dir, resolved_run_id)
    prepared = runner.prepare("Collect one bounded GUI observation", run_id=resolved_run_id)
    source = _RunnerSource(runner, desktop, prepared.state, recorder, task.get("target_scope", ""))
    started = False
    closed = False
    try:
        recorder.start(source.run_state)
        started = True
        recorder.record(source.run_state, RunPhase.OBSERVING)
        discovered = await desktop.discover_tools()
        verify_discovered_tools(
            discovered, configured_optional_tool_names(runner.config.mcp.environment)
        )
        recorder.record(source.run_state, RunPhase.PLANNING)
        bundle = await collect_gui_observation(task, source, max_seconds=max_seconds)
        await desktop.close()
        closed = True
        recorder.record(source.run_state, RunPhase.SUCCESS)
        return HostGuiObservation(bundle, source.run_state)
    except (GuiMetadataError, RunFailure, MCPBridgeError, ToolRegistryMismatchError) as exc:
        if started and recorder.phase not in {
            RunPhase.UNKNOWN_OUTCOME,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        }:
            recorder.record(
                source.run_state,
                RunPhase.FAILED,
                failure_code=(exc.code if isinstance(exc, RunFailure) else "MCP_PROTOCOL_ERROR"),
            )
        raise
    except asyncio.CancelledError:
        if started and recorder.phase not in {
            RunPhase.UNKNOWN_OUTCOME,
            RunPhase.FAILED,
            RunPhase.CANCELLED,
        }:
            recorder.record(source.run_state, RunPhase.CANCELLED)
        raise
    finally:
        try:
            if not closed:
                await desktop.close()
        finally:
            prepared.close()
