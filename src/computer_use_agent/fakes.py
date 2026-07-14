"""Deterministic Phase-2 fakes for provider, MCP, and approval ports."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .tool_registry import ToolSpec, reviewed_mcp_descriptors
from .types import (
    ApprovalRequest,
    LedgerEvent,
    MCPToolDescriptor,
    MemoryContextItem,
    ModelTurn,
    PolicyDecision,
    ProviderContinuationStrategy,
    ToolCall,
    ToolResult,
    JSONValue,
    to_json_value,
)


class UnexpectedFakeCall(RuntimeError):
    """Raised when a test invokes an unconfigured fake boundary."""


def _initial_input(task: str, memories: Sequence[MemoryContextItem]) -> str:
    if not memories:
        return task
    payload = [
        {
            "kind": item.kind,
            "content": item.content,
            "source": item.source,
            "scope": item.scope,
        }
        for item in memories
    ]
    return task + "\n\nOptional memory context (JSON data):\n" + json.dumps(
        payload, separators=(",", ":"), sort_keys=True
    )


@dataclass
class FakeModelProvider:
    name: str = "fake"
    continuation_strategy: ProviderContinuationStrategy = (
        ProviderContinuationStrategy.REMOTE_RESPONSE_ID
    )
    turns: deque[ModelTurn] = field(default_factory=deque)
    calls: list[dict[str, object]] = field(default_factory=list)
    continuation_state: dict[str, Mapping[str, JSONValue]] = field(default_factory=dict)

    async def create_turn(
        self,
        *,
        run_id: str,
        turn_id: str,
        task: str,
        ledger: Sequence[LedgerEvent],
        tools: Sequence[ToolSpec],
        memories: Sequence[MemoryContextItem] = (),
    ) -> ModelTurn:
        self.calls.append(
            {
                "run_id": run_id,
                "turn_id": turn_id,
                "task": task,
                "ledger": tuple(ledger),
                "tools": tuple(tools),
                "memories": tuple(memories),
            }
        )
        if not self.turns:
            raise UnexpectedFakeCall("no fake model turn was configured")
        turn = self.turns.popleft()
        previous = self.continuation_state.get(run_id, {})
        raw_batches = previous.get("output_batches", [])
        output_batches = list(raw_batches) if isinstance(raw_batches, list) else []
        output_batches.append(
            {"response_id": turn.provider_response_id, "items": []}
        )
        self.continuation_state[run_id] = {
            "response_id": turn.provider_response_id,
            "prior_context_tokens": (
                (turn.usage.input_tokens or 0) + (turn.usage.output_tokens or 0)
            ),
            "request_contract_digest": "0" * 64,
            "memory_context_used": previous.get(
                "memory_context_used", bool(memories)
            ),
            "initial_input": previous.get(
                "initial_input", _initial_input(task, memories)
            ),
            "output_batches": output_batches,
        }
        return turn

    def export_continuation(self, run_id: str) -> Mapping[str, JSONValue]:
        return to_json_value(
            self.continuation_state.get(
                run_id,
                {
                    "response_id": None,
                    "prior_context_tokens": 0,
                    "request_contract_digest": None,
                    "memory_context_used": False,
                    "initial_input": None,
                    "output_batches": [],
                },
            )
        )  # type: ignore[return-value]

    def restore_continuation(
        self, run_id: str, state: Mapping[str, JSONValue]
    ) -> None:
        self.continuation_state[run_id] = to_json_value(state)  # type: ignore[assignment]


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
