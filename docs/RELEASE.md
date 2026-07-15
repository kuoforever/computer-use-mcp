# Agent release and operator checklist

> **Status: implemented release gate documentation; release not yet approved.**
> Automated CI covers offline E0-E2 and wheel installation. Live provider and
> isolated desktop evidence remain explicit human gates.

Run the matching local preflight from a clean candidate checkout:

~~~powershell
.\.venv\Scripts\computer-use-agent.exe release preflight `
  --root . `
  --artifacts out\release-preflight `
  --report out\release-preflight.json
~~~

The command reads `HEAD` and the complete working tree before and after all
gates. It fails if either endpoint is dirty, the commit changes, public package
versions differ, Ruff/pytest/diff checks fail, the frozen replay or workflow
E1/E2 manifest drifts, a replay target test fails/skips, a safety escape occurs,
or the wheel cannot be built and smoke-tested
in a temporary no-deps environment. Report schema v4 records both candidate
checks, UTC generation time, Python version/implementation, non-path
platform identity, and an independent replay gate with canonical fixture and
manifest hashes plus case/test counts, so evidence cannot silently retain only
the starting identity or an unspecified local runtime. Build
isolation and dependency resolution are disabled, so all required
development/build dependencies must already be installed. Provider credentials
and all other non-allowlisted host variables are excluded, E3 is forced off,
Python user site loading is disabled, and pip is fixed to no-index/no-input
with user configuration ignored. The allowlist retains only reviewed
platform, path, home, locale, and temporary-directory variables needed by
Git, Python, build, and venv. This limits environment transfer; it is not an OS
sandbox. No desktop path is invoked.
The JSON evidence intentionally excludes subprocess output and cannot satisfy
CI, E3, E4, license, changelog, reviewer, or approval gates.
One local preflight records one Python runtime; supported-version evidence still
comes from the CI Python 3.11-3.13 matrix.

## Automated pull-request gates

`.github/workflows/ci.yml` runs on Windows for Python 3.11, 3.12, and 3.13 with
read-only repository permissions. It performs:

1. editable development installation;
2. Ruff over `src`, `tests`, and `scripts`;
3. the full pytest suite, with credentialed E3 tests skipped by default;
4. the OpenAI stateless-replay E2 module with retained JUnit evidence;
5. deterministic `agent eval` with a retained JSON report;
6. wheel build; and
7. clean wheel installation, CLI help, and E1/E2 smoke.

No CI job receives provider credentials, launches the real MCP executable, or
controls a desktop. E3 and E4 must never be silently added to the default job.

## Human release gates

Before tagging a release, record evidence for every item:

Use [Agent release evidence record](RELEASE_EVIDENCE.md) as the review template.
`NOT RUN` documents a missing gate; it does not turn that gate into a pass.

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
