# Agent release and operator checklist

> **Status: implemented release gate documentation; release not yet approved.**
> Automated CI covers offline E0-E2 and wheel installation. Live provider and
> isolated desktop evidence remain explicit human gates.

## Automated pull-request gates

`.github/workflows/ci.yml` runs on Windows for Python 3.11, 3.12, and 3.13 with
read-only repository permissions. It performs:

1. editable development installation;
2. Ruff over `src`, `tests`, and `scripts`;
3. the full pytest suite, with credentialed E3 tests skipped by default;
4. deterministic `agent eval` with a retained JSON report;
5. wheel build; and
6. clean wheel installation, CLI help, and E1/E2 smoke.

No CI job receives provider credentials, launches the real MCP executable, or
controls a desktop. E3 and E4 must never be silently added to the default job.

## Human release gates

Before tagging a release, record evidence for every item:

- CI is green on all supported Python versions.
- The wheel artifact installs in a clean Windows environment.
- OpenAI and Claude E3 pass with reviewed model IDs and the harmless fake MCP.
- All four cells in the [E4 isolated desktop smoke runbook](E4_SMOKE.md) pass
  only in disposable Notepad or a VM with a narrow allowlist.
- Read-only and one locally approved low-risk action complete with post-action
  observation for both providers.
- Trace samples contain no task/UI/typed/image/provider-error content.
- Unknown outcome, denial, E-stop, human-active, and gate failures are reviewed.
- Operator documentation covers credentials, disclosure, approval, recovery,
  disabling action mode, memory deletion, and current limitations.
- Version and changelog are updated, redistribution rights are reviewed, and a
  human explicitly approves release.

## Disable and recover

Set `policy.mode="read_only"` to remove provider action schemas and Host
approval dispatch. Stop the Agent process and MCP child to disable operation.
For failures, inspect `agent trace <run_id>`; never replay an uncertain action.
Current checkpoints are non-resumable, so start a new run after the required
human re-observation.

The project remains experimental until isolated E4 evidence and a release
review are complete.
