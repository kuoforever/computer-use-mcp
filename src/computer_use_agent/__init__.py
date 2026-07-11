"""Provider-neutral safety contract for the planned local Agent Host.

The canonical types and registry deliberately have no dependency on the MCP
server implementation, provider SDKs, or Windows automation libraries. Runtime
adapters remain separate modules so importing this package stays side-effect
free.
"""

from .tool_registry import REVIEWED_TOOLS
from .types import AGENT_CONTRACT_VERSION

__all__ = ["AGENT_CONTRACT_VERSION", "REVIEWED_TOOLS"]
