# Quick Setup and Agent Controls

> **Status: implemented as a CLI-first configuration surface.** Quick Setup
> creates one ordinary strict TOML configuration. Agent Controls projects that
> same configuration into human-readable or JSON settings. Neither surface can
> start work or grant authority.

## Human model

The first-run flow has three separate steps:

1. `config setup` creates one non-overwriting recommended configuration.
2. `config settings` explains the saved purpose, connection, safety, interface,
   and exact next command without starting anything.
3. `config doctor` performs the explicit installed-runtime readiness check.

This separation is intentional. Creation is a bounded local write, settings is
an inert projection, and doctor briefly starts the configured MCP child for
schema discovery. No command silently advances into the next step.

~~~powershell
guarded-desktop-agent config setup
guarded-desktop-agent config settings
guarded-desktop-agent config doctor --config `
  "$env:LOCALAPPDATA\computer-use-agent\agent.toml"
~~~

The default is the reviewed `desktop-ask` / `openai` profile and the current
project-validated OpenAI model ID. The bounded `--profile`, `--provider`,
`--model`, `--output`, `--allowlist`, and `--mcp-executable` overrides reuse the
existing `config init` validation; an explicit model override remains the
operator's responsibility. Existing output is never overwritten. Provider
credentials remain environment variables and are never written to TOML or
printed.

Use `config settings --config PATH` for a non-default file and add `--json` to
either command for automation. Human and JSON views come from the same strict
`AgentConfig`; settings do not maintain a second product state.

## Projection boundary

Agent Controls may show only bounded configuration and local setup facts:

- purpose, profile, provider, and model;
- policy mode, approval policy, allowlisted applications, and `Ctrl+Alt+Q`
  emergency stop;
- configured presentation preferences;
- SDK and documented credential-variable presence as booleans, never the
  credential value;
- configuration/state paths and the exact `config doctor` command.

The JSON `authority` object is deliberately explicit: approval, task control,
dispatch, retry/replay, and shortcut registration are all `false`. The surface
opens no provider, MCP, application, or desktop port and does not claim runtime
readiness or liveness.

No new global shortcut is part of this slice. The only existing emergency
shortcut remains `Ctrl+Alt+Q`. Future presentation/pause shortcuts require a
separate broker and must not introduce global approve or resume actions.
