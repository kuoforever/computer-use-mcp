from __future__ import annotations

import asyncio
import json
from collections import deque

import pytest

from computer_use_agent.fakes import FakePlanner
from computer_use_agent.planner import (
    MAX_PLANNER_REQUEST_BYTES,
    PlannerError,
    PlannerPort,
    PlannerRequest,
    PlannerTool,
    build_planner_request,
    request_task_plan,
)
from computer_use_agent.planning import PlanStepAction
from computer_use_agent.tool_registry import get_tool_spec, reviewed_registry_digest
from computer_use_agent.types import ToolEffect, to_json_value


TASK = "Inspect the active window"


def _candidate(*steps: dict[str, object]) -> str:
    return json.dumps({"version": 1, "steps": list(steps)})


def _request(*, allowed_tools: tuple[str, ...] = ("ui_snapshot",)) -> PlannerRequest:
    return build_planner_request(
        run_id="run_1",
        plan_id="plan_1",
        task=TASK,
        allowed_tools=allowed_tools,
    )


def test_request_discloses_only_bounded_declarative_host_scope() -> None:
    request = _request(allowed_tools=("ui_snapshot", "click"))

    assert request.size_bytes <= MAX_PLANNER_REQUEST_BYTES
    assert len(request.digest) == 64
    assert TASK not in repr(request)
    assert [tool.name for tool in request.tools] == ["ui_snapshot", "click"]
    assert request.tools[1].description == get_tool_spec("click").description
    assert not hasattr(request.tools[1], "requires_approval")
    assert not hasattr(request.tools[1], "effect")
    assert not hasattr(request, "ledger")
    assert not hasattr(request, "memories")
    with pytest.raises(TypeError):
        request.tools[0].input_schema["type"] = "string"  # type: ignore[index]


def test_fake_implements_one_shot_planner_port_and_compiles_untrusted_json() -> None:
    planner = FakePlanner(
        candidates=deque(
            [
                _candidate(
                    {"action": "tool", "tool": "click", "arguments": {"ref": "ref_1"}},
                    {"action": "final_response"},
                )
            ]
        )
    )
    request = _request(allowed_tools=("click",))

    plan = asyncio.run(request_task_plan(planner, request))

    assert isinstance(planner, PlannerPort)
    assert planner.calls == [request]
    assert plan.run_id == request.run_id
    assert plan.plan_id == request.plan_id
    assert plan.registry_digest == reviewed_registry_digest()
    assert plan.steps[0].action is PlanStepAction.TOOL
    assert plan.steps[0].effect is ToolEffect.SIDE_EFFECT
    assert plan.steps[0].requires_approval is True
    assert not hasattr(plan.steps[0], "identity")
    assert not hasattr(plan.steps[0], "authorized")


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(
            {"action": "tool", "tool": "find", "arguments": {"query": "Save"}},
            {"action": "final_response"},
        ),
        json.dumps(
            {
                "version": 1,
                "steps": [
                    {
                        "action": "tool",
                        "tool": "ui_snapshot",
                        "arguments": {},
                        "authorized": True,
                    },
                    {"action": "final_response"},
                ],
            }
        ),
        "x" * (64 * 1024 + 1),
        "\ud800",
    ],
    ids=("out-of-scope", "authority-injection", "oversized", "non-utf8"),
)
def test_out_of_scope_authority_injection_and_oversize_fail_after_one_call(
    candidate: str,
) -> None:
    planner = FakePlanner(candidates=deque([candidate, _candidate({"action": "final_response"})]))

    with pytest.raises(PlannerError, match="PLANNER_CANDIDATE_INVALID"):
        asyncio.run(request_task_plan(planner, _request()))

    assert len(planner.calls) == 1
    assert len(planner.candidates) == 1


def test_planner_failure_is_fixed_and_never_retried_or_echoed() -> None:
    secret = "provider echoed private task content"
    planner = FakePlanner(
        candidates=deque([RuntimeError(secret), _candidate({"action": "final_response"})])
    )

    with pytest.raises(PlannerError, match="PLANNER_REQUEST_FAILED") as captured:
        asyncio.run(request_task_plan(planner, _request()))

    assert secret not in str(captured.value)
    assert len(planner.calls) == 1
    assert len(planner.candidates) == 1


def test_sensitive_unreviewed_duplicate_or_spoofed_tool_scope_fails_before_call() -> None:
    for tools in (("type",), ("shell",), ("ui_snapshot", "ui_snapshot")):
        with pytest.raises(PlannerError):
            _request(allowed_tools=tools)

    reviewed = get_tool_spec("ui_snapshot")
    with pytest.raises(PlannerError, match="CONTRACT_MISMATCH"):
        PlannerTool(
            name=reviewed.name,
            description="spoofed description",
            input_schema=reviewed.input_schema,
        )
    with pytest.raises(PlannerError, match="SENSITIVE"):
        PlannerTool(
            name="type",
            description=get_tool_spec("type").description,
            input_schema=get_tool_spec("type").input_schema,
        )


def test_request_version_and_total_bytes_are_strict_before_external_io() -> None:
    with pytest.raises(PlannerError, match="VERSION_UNSUPPORTED"):
        PlannerRequest(
            run_id="run_1",
            plan_id="plan_1",
            task=TASK,
            request_version=1.0,  # type: ignore[arg-type]
        )
    with pytest.raises(PlannerError, match="TOO_LARGE"):
        build_planner_request(
            run_id="run_1",
            plan_id="plan_1",
            task="x" * MAX_PLANNER_REQUEST_BYTES,
            allowed_tools=(),
        )


def test_planner_tool_schema_is_an_independent_immutable_copy() -> None:
    mutable = to_json_value(get_tool_spec("find").input_schema)
    assert isinstance(mutable, dict)
    tool = PlannerTool(
        name="find",
        description=get_tool_spec("find").description,
        input_schema=mutable,
    )
    properties = mutable["properties"]
    assert isinstance(properties, dict)
    properties["query"] = {"type": "integer"}

    assert to_json_value(tool.input_schema) == to_json_value(get_tool_spec("find").input_schema)
