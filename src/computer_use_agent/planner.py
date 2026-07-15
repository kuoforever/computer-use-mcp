"""One-shot, provider-neutral Planner boundary for non-executable plans.

The Planner receives only a bounded task and host-selected declarative tool
schemas. Its response is untrusted JSON text and must pass the existing plan
compiler. This module has no policy, approval, MCP, persistence, or Executor
integration and cannot create or dispatch a ToolCall.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence, runtime_checkable

from .planning import (
    PLAN_CONTRACT_VERSION,
    PlanValidationError,
    TaskPlan,
    compile_task_plan,
)
from .tool_registry import ToolValidationError, get_tool_spec, reviewed_registry_digest
from .types import JSONValue, _frozen_json_object, to_json_value


PLANNER_REQUEST_VERSION = 1
MAX_PLANNER_REQUEST_BYTES = 128 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


class PlannerError(RuntimeError):
    """Fixed Planner boundary failure that never embeds task or candidate text."""


@dataclass(frozen=True)
class PlannerTool:
    """Exact declarative schema disclosed to a Planner, without authority metadata."""

    name: str
    description: str
    input_schema: Mapping[str, JSONValue]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise PlannerError("PLANNER_TOOL_INVALID")
        if not isinstance(self.description, str) or not self.description:
            raise PlannerError("PLANNER_TOOL_INVALID")
        if not isinstance(self.input_schema, Mapping):
            raise PlannerError("PLANNER_TOOL_INVALID")
        try:
            reviewed = get_tool_spec(self.name)
        except ToolValidationError:
            raise PlannerError("PLANNER_TOOL_UNREVIEWED") from None
        if reviewed.sensitive_arguments:
            raise PlannerError("PLANNER_TOOL_SENSITIVE")
        if (
            self.description != reviewed.description
            or to_json_value(self.input_schema) != to_json_value(reviewed.input_schema)
        ):
            raise PlannerError("PLANNER_TOOL_CONTRACT_MISMATCH")
        object.__setattr__(
            self,
            "input_schema",
            _frozen_json_object(self.input_schema, "planner input_schema"),
        )


@dataclass(frozen=True)
class PlannerRequest:
    """Immutable, digest-bound input for exactly one Planner call."""

    run_id: str
    plan_id: str
    task: str = field(repr=False)
    tools: tuple[PlannerTool, ...] = ()
    request_version: int = PLANNER_REQUEST_VERSION

    def __post_init__(self) -> None:
        for value in (self.run_id, self.plan_id):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise PlannerError("PLANNER_REQUEST_IDENTITY_INVALID")
        if not isinstance(self.task, str) or not self.task:
            raise PlannerError("PLANNER_REQUEST_TASK_INVALID")
        if (
            not isinstance(self.request_version, int)
            or isinstance(self.request_version, bool)
            or self.request_version != PLANNER_REQUEST_VERSION
        ):
            raise PlannerError("PLANNER_REQUEST_VERSION_UNSUPPORTED")
        if not isinstance(self.tools, tuple) or not all(
            isinstance(tool, PlannerTool) for tool in self.tools
        ):
            raise PlannerError("PLANNER_REQUEST_TOOLS_INVALID")
        names = tuple(tool.name for tool in self.tools)
        if len(names) != len(set(names)):
            raise PlannerError("PLANNER_REQUEST_TOOLS_INVALID")
        if len(names) > 8:
            raise PlannerError("PLANNER_REQUEST_TOOLS_INVALID")
        if len(self._encoded()) > MAX_PLANNER_REQUEST_BYTES:
            raise PlannerError("PLANNER_REQUEST_TOO_LARGE")

    def _payload(self) -> dict[str, object]:
        return {
            "request_version": self.request_version,
            "plan_contract_version": PLAN_CONTRACT_VERSION,
            "run_id": self.run_id,
            "plan_id": self.plan_id,
            "task": self.task,
            "registry_digest": reviewed_registry_digest(),
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": to_json_value(tool.input_schema),
                }
                for tool in self.tools
            ],
        }

    def _encoded(self) -> bytes:
        try:
            return json.dumps(
                self._payload(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise PlannerError("PLANNER_REQUEST_INVALID") from None

    @property
    def digest(self) -> str:
        return hashlib.sha256(self._encoded()).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self._encoded())


@runtime_checkable
class PlannerPort(Protocol):
    """One-shot untrusted plan-candidate boundary; it has no execution methods."""

    name: str

    async def create_candidate(self, request: PlannerRequest) -> str: ...


def build_planner_request(
    *,
    run_id: str,
    plan_id: str,
    task: str,
    allowed_tools: Sequence[str],
) -> PlannerRequest:
    """Build one request from an explicit, reviewed, non-sensitive tool scope."""

    if isinstance(allowed_tools, (str, bytes)) or not isinstance(allowed_tools, Sequence):
        raise PlannerError("PLANNER_TOOL_SCOPE_INVALID")
    names = tuple(allowed_tools)
    if not all(isinstance(name, str) and name for name in names):
        raise PlannerError("PLANNER_TOOL_SCOPE_INVALID")
    if len(names) != len(set(names)):
        raise PlannerError("PLANNER_TOOL_SCOPE_INVALID")
    tools: list[PlannerTool] = []
    for name in names:
        try:
            spec = get_tool_spec(name)
        except ToolValidationError:
            raise PlannerError("PLANNER_TOOL_UNREVIEWED") from None
        if spec.sensitive_arguments:
            raise PlannerError("PLANNER_TOOL_SENSITIVE")
        tools.append(
            PlannerTool(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
            )
        )
    return PlannerRequest(run_id=run_id, plan_id=plan_id, task=task, tools=tuple(tools))


async def request_task_plan(planner: PlannerPort, request: PlannerRequest) -> TaskPlan:
    """Call one Planner once and compile its untrusted candidate without retries."""

    if not isinstance(planner, PlannerPort) or not isinstance(planner.name, str) or not planner.name:
        raise PlannerError("PLANNER_PORT_INVALID")
    if not isinstance(request, PlannerRequest):
        raise PlannerError("PLANNER_REQUEST_INVALID")
    try:
        candidate = await planner.create_candidate(request)
    except Exception:
        raise PlannerError("PLANNER_REQUEST_FAILED") from None
    try:
        return compile_task_plan(
            candidate,
            plan_id=request.plan_id,
            run_id=request.run_id,
            task=request.task,
            allowed_tools=tuple(tool.name for tool in request.tools),
        )
    except PlanValidationError:
        raise PlannerError("PLANNER_CANDIDATE_INVALID") from None


__all__ = [
    "MAX_PLANNER_REQUEST_BYTES",
    "PLANNER_REQUEST_VERSION",
    "PlannerError",
    "PlannerPort",
    "PlannerRequest",
    "PlannerTool",
    "build_planner_request",
    "request_task_plan",
]
