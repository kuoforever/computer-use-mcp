# Configuration and safety

> **Status: implemented on Windows.** This page describes the current runtime
> behavior, not a future safety model.

Desktop actions have visible side effects. Keep the allowlist narrow and use
`safe_local` unless an operator has explicitly approved local takeover.

## Control modes

### `safe_local` (default)

Before an action is executed, the server:

1. Rejects it if the emergency stop is latched.
2. Yields when recent human input is detected.
3. For `click`, `type`, and `key`, checks that the foreground window's
   process ownership chain contains an allowlisted executable.
4. For a dangerous `click(ref=...)`, asks for a native confirmation dialog.
5. Writes the action result to the JSONL audit log.

`activate_window(window_id)` intentionally skips the foreground allowlist
check, because it is used to bring a listed target forward. In safe mode it is
still human-activity guarded, e-stop guarded, and audited.

### `full_control_local`

This mode explicitly bypasses the foreground allowlist and human-activity
yielding checks. It **does not** disable the emergency stop or auditing.
Dangerous ref-click confirmation defaults to off in this mode, but can be
enabled with `CUMCP_DANGEROUS_CONFIRM=1`.

Use it only for an operator-approved local session. It does not make
same-desktop background control safe or parallel.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `CUMCP_ALLOWLIST` | `notepad.exe` | Comma-separated executable names allowed for safe-mode foreground actions. A match anywhere in the foreground process ancestry is accepted. |
| `CUMCP_MODE` | `safe_local` | Either `safe_local` or `full_control_local`. No `isolated_worker` mode is currently accepted. |
| `CUMCP_HUMAN_IDLE_SECONDS` | `2.5` | Seconds after local mouse/keyboard input during which safe-mode actions yield. |
| `CUMCP_DANGEROUS_CONFIRM` | on in safe mode; off in full-control mode | Enables confirmation for dangerous `click(ref=...)` targets. |
| `CUMCP_ESTOP` | `ctrl+alt+q` | Global hotkey that latches all actions off until the server restarts. |
| `CUMCP_AUDIT` | `audit/actions.jsonl` | JSONL audit-log path. |
| `CUMCP_REDACT_TITLES` | `1Password,Bitwarden,KeePass,Authenticator` | Comma-separated title substrings for screenshot blackouts. |
| `CUMCP_VMRUN` | unset | Optional path to VMware `vmrun.exe` for the host-side helper. |
| `CUMCP_WORKER_VMX` | unset | Existing VMware `.vmx` path for the host-side helper. |

Examples:

~~~powershell
# Default guardrails; only foreground Notepad actions are permitted.
$env:CUMCP_MODE = "safe_local"
$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\computer-use-mcp.exe

# Explicit local takeover. E-stop and audit remain enabled.
$env:CUMCP_MODE = "full_control_local"
$env:CUMCP_DANGEROUS_CONFIRM = "1"
.\.venv\Scripts\computer-use-mcp.exe
~~~

## What the safeguards do not cover

- Dangerous-action confirmation currently applies to keyword-matched
  `click(ref=...)` targets. It does not classify coordinate clicks, text
  entry, key chords, or window activation as dangerous.
- Password values are omitted from UI snapshots, but the server does not
  perform general sensitive-data detection.
- Screenshot redaction blackens visible windows only when their titles match a
  configured substring. It does not inspect the pixels or redact every secret.
- The safe-mode allowlist is a local guardrail, not an operating-system
  security boundary.
- A single desktop still has shared focus, pointer, keyboard, and screenshot
  resources.

## Audit and recovery

Each action records its tool name, a bounded argument summary, decision, result,
and control mode in the JSONL audit file. For `type`, the audit record contains
only `text_present`, `text_length`, and `ref_supplied`; it never contains typed
text, a typed-text prefix, arbitrary type arguments, or a driver result message.
Inspect it with a text editor or a JSON-aware log viewer.

Hold the configured e-stop hotkey to abort future actions. The e-stop is
latched; restart the MCP server to clear it.

Experimental write-ahead continuation persistence is disabled by default. To
collect private crash boundaries, configure `[continuation] enabled = true` and
`ttl_seconds` between 60 and 86400. The resulting `continuation.json` can contain
the exact task, assistant text, UI results, and PNG screenshots. It is written
with user-only permissions, removed on normal terminal completion, excluded from
`agent trace` and `agent report`, and never authorizes automatic replay. An
operator may execute one strictly classified read-only continuation boundary
with `agent recover ... --execute-read-only`; the command holds the run lock and
fails closed on task, policy, provider, registry, budget, digest, or sequence drift.

## VMware helper

`scripts/vmware_worker.py` is an **experimental host-side helper**. It can
check `vmrun.exe`, start an existing VMware Workstation VM, and optionally wait
for VMware Tools:

~~~powershell
$env:CUMCP_WORKER_VMX = "D:\VMs\cumcp-worker\cumcp-worker.vmx"
.\.venv\Scripts\python.exe scripts\vmware_worker.py doctor
.\.venv\Scripts\python.exe scripts\vmware_worker.py start --wait-tools
~~~

It does not create or license the guest OS, install this project in the guest,
start a guest MCP server, or connect the host agent to it. Those are future
orchestration concerns.
