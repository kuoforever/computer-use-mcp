"""Deterministic Phase-2 fakes for provider, MCP, and approval ports."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from .planner import PlannerRequest
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


@dataclass
class FakePlanner:
    """One-shot candidate fake with no provider continuation or execution port."""

    name: str = "fake-planner"
    candidates: deque[str | Exception] = field(default_factory=deque)
    calls: list[PlannerRequest] = field(default_factory=list)

    async def create_candidate(self, request: PlannerRequest) -> str:
        self.calls.append(request)
        if not self.candidates:
            raise UnexpectedFakeCall("no fake plan candidate was configured")
        candidate = self.candidates.popleft()
        if isinstance(candidate, Exception):
            raise candidate
        return candidate


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
    satisfied_safety_baselines: frozenset[str] = frozenset()
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


# Any focus/activation entry point a real Win32 window could offer. The passive
# progress window must never reach for one, so the fake refuses them loudly
# rather than silently recording a call that would steal the operator's focus.
_FORBIDDEN_WINDOW_CALLS = frozenset(
    {"activate", "set_focus", "set_foreground", "bring_to_top", "show", "focus"}
)


class FakeProgressWindowApi:
    """A recording ``ProgressWindowApi`` for the passive progress window.

    Its foreground never changes, because nothing on the real interface can move
    it; a stable value here mirrors the real contract and lets a test assert the
    operator's foreground survived a full open/refresh/move/topmost/close cycle.
    """

    def __init__(self, foreground: int = 4242) -> None:
        self.calls: list[tuple] = []
        self.lines: dict[int, tuple[str, ...]] = {}
        self.workflow_lines: dict[int, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        self.toggle_handlers: dict[int, Callable[[bool], None]] = {}
        self.alive: set[int] = set()
        self._foreground = foreground
        self._next_hwnd = 1000

    def create(self, *, ex_style: int, style: int, title: str) -> int:
        self._next_hwnd += 1
        hwnd = self._next_hwnd
        self.alive.add(hwnd)
        self.calls.append(("create", ex_style, style, title, hwnd))
        return hwnd

    def set_lines(self, hwnd: int, lines: Sequence[str]) -> None:
        self.workflow_lines.pop(hwnd, None)
        self.toggle_handlers.pop(hwnd, None)
        self.lines[hwnd] = tuple(lines)
        self.calls.append(("set_lines", hwnd, tuple(lines)))

    def set_workflow_lines(
        self,
        hwnd: int,
        *,
        compact_lines: Sequence[str],
        expanded_lines: Sequence[str],
        expanded: bool,
        accent_rgb: int,
        on_toggle: Callable[[bool], None],
    ) -> None:
        variants = (tuple(compact_lines), tuple(expanded_lines))
        self.workflow_lines[hwnd] = variants
        self.toggle_handlers[hwnd] = on_toggle
        self.lines[hwnd] = variants[1] if expanded else variants[0]
        self.calls.append(("set_workflow_lines", hwnd, expanded, accent_rgb))

    def show_noactivate(self, hwnd: int) -> None:
        self.calls.append(("show_noactivate", hwnd))

    def reposition_noactivate(self, hwnd: int, *, x: int, y: int, topmost: bool) -> None:
        self.calls.append(("reposition_noactivate", hwnd, x, y, topmost))

    def foreground(self) -> int:
        return self._foreground

    def destroy(self, hwnd: int) -> None:
        self.alive.discard(hwnd)
        self.workflow_lines.pop(hwnd, None)
        self.toggle_handlers.pop(hwnd, None)
        self.calls.append(("destroy", hwnd))

    def click_workflow_toggle(self, hwnd: int) -> None:
        """Simulate the operator's non-activating SHOW/HIDE STEPS affordance."""

        variants = self.workflow_lines[hwnd]
        next_expanded = self.lines[hwnd] != variants[1]
        self.lines[hwnd] = variants[1] if next_expanded else variants[0]
        self.toggle_handlers[hwnd](next_expanded)

    def __getattr__(self, name: str):  # pragma: no cover - only hit on misuse
        if name in _FORBIDDEN_WINDOW_CALLS:
            raise UnexpectedFakeCall(f"passive window must never call {name!r}")
        raise AttributeError(name)

    def kinds(self) -> list[str]:
        """The call sequence by kind, for order assertions."""

        return [call[0] for call in self.calls]
