# Guarded Desktop Agent naming migration

> **Status: reference.** Current canonical names plus the compatibility aliases
> retained for older configurations.

## Canonical names

- Product and repository: `Guarded Desktop Agent` / `guarded-desktop-agent`
- Python distribution: `guarded-desktop-agent`
- MCP server and console command: `guarded-desktop-mcp`
- Agent console command: `guarded-desktop-agent`

These names distinguish the project-local MCP server and Agent Host from
platform-provided Computer Use plugins.

## Compatibility boundary

The rename does not change durable state or protocol behavior. Existing
integrations may continue to use:

- Python packages `computer_use_mcp` and `computer_use_agent`;
- console aliases `computer-use-mcp` and `computer-use-agent`;
- environment variables prefixed with `CUMCP_`;
- the user-local `computer-use-agent` state directory;
- retained evidence files and historical text that identify the old name.

New installations and MCP client configurations should use the canonical
commands. The compatibility aliases must not be removed without a separately
versioned migration and explicit state/configuration upgrade guidance.
