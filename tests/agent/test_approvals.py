from __future__ import annotations

import asyncio

from computer_use_agent.approvals import ConsoleApprovalPort
from computer_use_agent.types import (
    ApprovalRequest,
    CallIdentity,
    PolicyDecisionKind,
    ToolCall,
)


def _request(call: ToolCall) -> ApprovalRequest:
    return ApprovalRequest.from_tool_call(
        request_id="approval_1",
        call=call,
        reason="action",
        sensitive_arguments=("text",) if call.name == "type" else (),
    )


def test_console_approval_is_bound_to_request_and_accepts_only_explicit_yes() -> None:
    outputs: list[str] = []
    call = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"),
        "click",
        {"ref": "ref_1"},
    )
    request = _request(call)
    port = ConsoleApprovalPort(input_fn=lambda _prompt: "yes", output_fn=outputs.append)

    decision = asyncio.run(port.request_approval(request))

    assert request.matches(decision)
    assert decision.kind is PolicyDecisionKind.ALLOW
    assert "ref_1" in outputs[0]
    assert request.call_digest in outputs[0]


def test_console_approval_denies_default_and_never_prints_typed_value() -> None:
    outputs: list[str] = []
    typed_value = "DO_NOT_PRINT_TYPED_VALUE"
    call = ToolCall(
        CallIdentity("run_1", "turn_1", "call_1"),
        "type",
        {"text": typed_value},
    )
    request = _request(call)
    port = ConsoleApprovalPort(input_fn=lambda _prompt: "", output_fn=outputs.append)

    decision = asyncio.run(port.request_approval(request))

    assert decision.kind is PolicyDecisionKind.DENY
    assert typed_value not in "".join(outputs)
    assert "text_length" in outputs[0]
