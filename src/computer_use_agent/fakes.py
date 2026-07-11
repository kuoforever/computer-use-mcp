"""Deterministic Phase-2 fakes for provider, MCP, and approval ports."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Sequence

from .tool_registry import ToolSpec, reviewed_mcp_descriptors
from .types import (
    ApprovalRequest,
    LedgerEvent,
    MCPToolDescriptor,
    ModelTurn,
    PolicyDecision,
    ToolCall,
    ToolResult,
)


class UnexpectedFakeCall(RuntimeError):
    """Raised when a test invokes an unconfigured fake boundary."""


@dataclass
class FakeModelProvider:
    name: str = "fake"
    turns: deque[ModelTurn] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence[ToolSpec],
    ) -> ModelTurn:
        self.calls.append(
            {
                "run_id": run_id,
                "turn_id": turn_id,
                "task": task,
                "ledger": tuple(ledger),
                "tools": tuple(tools),
            }
        )
        if not self.turns:
            raise UnexpectedFakeCall("no fake model turn was configured")
        return self.turns.popleft()


@dataclass
class FakeDesktopMCP:
    generation: int = 1
    descriptors: tuple[MCPToolDescriptor, ...] = field(default_factory=reviewed_mcp_descriptors)
    results: deque[ToolResult] = field(default_factory=deque)
    discovery_calls: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    close_calls: int = 0

    async def discover_tools(self) -> tuple[MCPToolDescriptor, ...]:
        self.discovery_calls += 1
        return self.descriptors

    async def call_tool(self, call: ToolCall) -> ToolResult:
        self.tool_calls.append(call)
        if not self.results:
            raise UnexpectedFakeCall("no fake tool result was configured")
        return self.results.popleft()

    async def close(self) -> None:
        self.close_calls += 1


@dataclass
class FakeApprovalPort:
    decisions: deque[PolicyDecision] = field(default_factory=deque)
    requests: list[ApprovalRequest] = field(default_factory=list)

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        self.requests.append(request)
        if not self.decisions:
            raise UnexpectedFakeCall("no fake approval decision was configured")
        return self.decisions.popleft()
