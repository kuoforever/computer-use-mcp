"""Local approval ports for explicit Agent Host authorization."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

from .types import ApprovalRequest, PolicyDecision, PolicyDecisionKind, to_json_value


class ReadOnlyApprovalPort:
    """Fail if approval is ever requested by the read-only runtime."""

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        del request
        raise RuntimeError("APPROVAL_UNAVAILABLE_IN_READ_ONLY_MODE")


class ConsoleApprovalPort:
    """Ask the local operator for one digest-bound action approval."""

    def __init__(
        self,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
    ) -> None:
        self._input = input_fn
        self._output = output_fn

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        summary = json.dumps(
            to_json_value(request.safe_argument_summary.values),
            sort_keys=True,
            separators=(",", ":"),
        )
        self._output(
            f"Approval required: tool={request.tool_name} arguments={summary} "
            f"digest={request.call_digest}"
        )
        try:
            answer = await asyncio.to_thread(self._input, "Approve this one action? [y/N]: ")
        except (EOFError, KeyboardInterrupt):
            answer = ""
        kind = (
            PolicyDecisionKind.ALLOW
            if answer.strip().lower() in {"y", "yes"}
            else PolicyDecisionKind.DENY
        )
        return PolicyDecision(
            request_id=request.request_id,
            identity=request.identity,
            call_digest=request.call_digest,
            kind=kind,
            reason="local_operator_response",
        )


__all__ = ["ConsoleApprovalPort", "ReadOnlyApprovalPort"]

