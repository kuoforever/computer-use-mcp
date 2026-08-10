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
`--model`, `--region`, Qwen-only `--workspace-id`, `--output`, `--allowlist`,
`--mcp-executable`, and `--pause-shortcut` overrides reuse the existing
`config init` validation; an explicit model override remains the operator's
responsibility. New Qwen configurations use `region + workspace_id`; its
`--base-url` option exists only for strict legacy migration and cannot be
combined with either typed field. Fixed-endpoint providers reject it.
`local_openai` requires an explicit model plus a literal loopback `/v1` URL;
its optional key remains environment-only. Existing output is never
overwritten. Provider credentials are never written to TOML or printed. See the
[provider matrix](PROVIDERS.md).

The pause chord defaults to `ctrl+alt+p`. Only exact canonical
`ctrl+alt+<a-z>` is accepted; G remains Agent Controls and Q remains emergency
stop, so both are rejected as pause keys. Windows-key combinations, function
keys including F12, uppercase aliases, and whitespace-normalized variants are
not accepted. For example:

~~~powershell
guarded-desktop-agent config setup --pause-shortcut ctrl+alt+k
~~~

Use `config settings --config PATH` for a non-default file and add `--json` to
either command for automation. Human and JSON views come from the same strict
`AgentConfig`; settings do not maintain a second product state.

## Projection boundary

Agent Controls may show only bounded configuration and local setup facts:

- purpose, profile, provider, region, and model;
- policy mode, approval policy, allowlisted applications, and `Ctrl+Alt+Q`
  emergency stop;
- configured presentation preferences and the effective pause shortcut;
- SDK plus documented credential required/presence booleans, never the value;
- configuration/state paths and the exact `config doctor` command.

The JSON `authority` object is deliberately explicit: approval, task control,
dispatch, retry/replay, and shortcut registration are all `false`. The surface
opens no provider, MCP, application, or desktop port and does not claim runtime
readiness or liveness.

Agent Controls JSON version 2 adds `provider_setup.credential_required` so an
absent optional local key is never mislabeled as a missing readiness secret.

The settings view does not itself register a shortcut and cannot infer whether
another process currently owns one. Its fixed `registered_by_this_view=false`
field and false authority flags describe this projection only, not system-wide
liveness.

## Explicit shortcut host

An operator may start the separate foreground ShortcutBroker after setup:

~~~powershell
guarded-desktop-agent shortcuts run --config `
  "$env:LOCALAPPDATA\computer-use-agent\agent.toml"
~~~

The command validates the same strict configuration, checks every currently
loaded keyboard layout for a Ctrl+Alt character mapping on G and the configured
pause key, then atomically registers both shortcuts with Win32 `RegisterHotKey`
and `MOD_NOREPEAT`. It reports `SHORTCUTS ACTIVE` only after both registrations
and its poll timer succeed. A layout or registration conflict fails visibly
before ACTIVE; partial registration is rolled back. `Ctrl+C` releases both.

- `Ctrl+Alt+G` restores and refreshes the Agent Controls console owned by this
  explicitly started host. It is presentation-only and does not enumerate or
  claim another process's Decision Card.
- The configured pause chord (default `Ctrl+Alt+P`) submits the existing
  cooperative `pause` request for the one unambiguous live controlled run.
  `PAUSE REQUESTED` is not desktop authority; local input is safe only after
  the host reports `PAUSED · DESKTOP AUTHORITY RELEASED` from exact
  `status=paused` and `authority=released` state.
- `Ctrl+Alt+Q` remains the independent MCP emergency-stop path. The broker does
  not register, replace, or weaken it.

There is no global approve or resume shortcut. The broker starts no provider,
MCP, application, or desktop-dispatch port, and only the existing Runner/MCP
path can perform desktop work. The first fixed-G/P non-input native gate is
retained in [PRODUCT-020 Windows evidence](SHORTCUT_BROKER_WINDOWS_EVIDENCE.md):
it covers only the two layouts loaded on that machine and direct Win32 message
routing. Later [PRODUCT-021 supervised physical runs](SHORTCUT_BROKER_PHYSICAL_EVIDENCE.md)
on the same loaded `zh-CN`/`en-US` layouts confirmed configured G foreground,
no-run K fail-closed behavior, direct-console Ctrl+C cleanup wording, and
release/reacquisition. A follow-up also confirmed the installed physical-Q
E-stop latch and physical K driving an active production Runner control record
to `paused` with `authority=released` before any provider call. Full-MCP
post-Q action denial, real-provider/MCP/application pause or resume, and layouts
not installed/loaded when a Host starts remain unverified.
