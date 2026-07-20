# Security policy

## Supported versions

| Version | Status |
| --- | --- |
| `0.1.x` | Experimental. Fixes land on `main`; there is no backport branch. |

This project is experimental software that, by design, controls a real desktop.
It has not been through an external security review. Do not run it against an
account, machine, or application whose compromise would matter.

## Reporting a vulnerability

Use **GitHub → Security → Report a vulnerability** on this repository, which
opens a private advisory. Please do not open a public issue containing exploit
details, a working bypass, or captured data.

Include the version or commit, the mode (`safe_local` or
`full_control_local`), the configuration involved (with credentials and personal
paths removed), what you expected the guard to do, and what it actually did.

This is a personal, unfunded project. There is no paid bounty, and response is
best-effort rather than an SLA.

## What counts as a vulnerability here

The threat model is unusual: the whole point of the tool is to let a model act
on a desktop under stated constraints. A report is in scope when it shows a
**stated constraint failing**, not merely that the tool can act.

**In scope**

- Bypassing the `safe_local` foreground gate — causing an action to execute
  while the foreground window's process ancestry is outside the allowlist.
- Escaping the reviewed MCP child environment: getting a non-reviewed variable,
  a provider credential, or an audit/redaction override into the child process.
- Provider credentials, API keys, or tokens appearing in a trace, checkpoint,
  audit record, evidence file, or preflight report.
- Defeating screenshot or text redaction so sensitive content reaches a
  provider when the privacy boundary is enabled.
- Causing a side effect to be replayed automatically after an uncertain
  dispatch, or a `ref` action to land on an element other than the one named.
- Arbitrary command or code execution through configuration parsing, a tool
  argument, or an MCP result.
- Path traversal or write access outside the configured state directory.

**Not vulnerabilities**

- That an operator can grant desktop control at all. That is the feature.
- That `full_control_local` bypasses the foreground allowlist and
  human-activity yielding. This is documented, deliberate, and requires an
  explicit mode change.
- That a model can be prompt-injected into *requesting* a harmful action.
  Injection is expected. The mitigations are the policy gate, the approval
  boundary, and the audit record — not the model's judgment. A report is in
  scope only if injected content bypasses one of those.
- That an operator can allowlist a sensitive application, or point the state
  directory somewhere unwise.
- Missing hardening the project never claimed: it is not an OS sandbox, and the
  preflight's environment allowlist limits variable transfer rather than
  isolating the process.

## Handling of secrets

Provider credentials are read by the provider adapter from the Agent host
process environment. They are never forwarded to the MCP child: the child
receives only reviewed `CUMCP_*` controls, and a non-reviewed key is rejected
rather than passed through. Retained evidence and preflight reports are
sanitized and exclude subprocess output.

If you believe a credential reached a file that is committed to this
repository, treat it as a vulnerability report and use the private channel
above.
