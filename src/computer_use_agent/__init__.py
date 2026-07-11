"""Provider-neutral safety contract for the planned local Agent Host.

This package deliberately has no dependency on the MCP server implementation,
provider SDKs, or Windows automation libraries.  Phase 0 establishes only the
reviewable host contract; it does not make an Agent Host runnable yet.
"""

from .tool_registry import REVIEWED_TOOLS
from .types import AGENT_CONTRACT_VERSION

__all__ = ["AGENT_CONTRACT_VERSION", "REVIEWED_TOOLS"]
