"""Local approval ports for explicit Agent Host authorization."""
from __future__ import annotations

from .types import ApprovalRequest, PolicyDecision


class ReadOnlyApprovalPort:
    """Fail if approval is ever requested by the read-only runtime."""

    async def request_approval(self, request: ApprovalRequest) -> PolicyDecision:
        del request
        raise RuntimeError("APPROVAL_UNAVAILABLE_IN_READ_ONLY_MODE")

