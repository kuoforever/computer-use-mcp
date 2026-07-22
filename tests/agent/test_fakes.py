from __future__ import annotations

import asyncio
from collections import deque

from computer_use_agent.fakes import FakeApprovalPort, FakeDesktopMCP, FakeModelProvider
from computer_use_agent.tool_registry import REVIEWED_TOOLS
from computer_use_agent.types import (
    ApprovalPort,
    ApprovalRequest,
    CallIdentity,
    DesktopMCPPort,
    DispatchCertainty,
    ModelProviderPort,
    ModelTurn,
    PolicyDecision,
    PolicyDecisionKind,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


def test_fakes_implement_ports_and_record_deterministic_calls() -> None:
    identity = CallIdentity(run_id="run_1", turn_id="turn_1", call_id="call_1")
    turn = ModelTurn(
        run_id="run_1",
        turn_id="turn_1",
        provider_response_id="response_1",
        text="done",
    )
    provider = FakeModelProvider(turns=deque([turn]))
    returned_turn = asyncio.run(
        provider.create_turn(
            run_id="run_1",
            turn_id="turn_1",
            task="inspect",
            ledger=(),
            tools=REVIEWED_TOOLS,
        )
    )
    assert isinstance(provider, ModelProviderPort)
    assert returned_turn is turn
    assert len(provider.calls) == 1

    call = ToolCall(identity=identity, name="list_windows", arguments={})
    result = ToolResult(
        identity=identity,
        tool_name="list_windows",
        status=ToolResultStatus.SUCCESS,
        dispatch=DispatchCertainty.DISPATCHED,
    )
    desktop = FakeDesktopMCP(results=deque([result]))
    assert isinstance(desktop, DesktopMCPPort)
    assert len(asyncio.run(desktop.discover_tools())) == 10
    assert asyncio.run(desktop.call_tool(call)) is result
    asyncio.run(desktop.close())
    assert desktop.tool_calls == [call]
    assert desktop.close_calls == 1

    request = ApprovalRequest.from_tool_call(
        request_id="approval_1",
        call=ToolCall(identity=identity, name="click", arguments={"ref": "ref_1"}),
        reason="action",
        sensitive_arguments=(),
    )
    decision = PolicyDecision(
        request_id="approval_1",
        identity=identity,
        call_digest=request.call_digest,
        kind=PolicyDecisionKind.DENY,
        reason="denied",
    )
    approvals = FakeApprovalPort(decisions=deque([decision]))
    assert isinstance(approvals, ApprovalPort)
    assert asyncio.run(approvals.request_approval(request)) is decision
    assert approvals.requests == [request]
