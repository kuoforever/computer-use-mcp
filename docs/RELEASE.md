# Agent release and operator checklist

> **Status: implemented release gate documentation; release not yet approved.**
> Automated CI covers offline E0-E2 and wheel installation. Live provider and
> isolated desktop evidence remain explicit human gates; scoped E3/E4 records
> exist, but no candidate release is approved by those records alone.

Run the matching local preflight from a clean candidate checkout:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe release preflight `
  --root . `
  --artifacts out\release-preflight `
  --report out\release-preflight.json
~~~

The command reads `HEAD` and the complete working tree before and after all
gates. It fails if either endpoint is dirty, the commit changes, public package
versions differ, Ruff/pytest/diff checks fail, the frozen crash-reconstruction,
replay, or workflow E1/E2 manifest drifts, an independent target test fails/skips,
a safety escape occurs,
or the wheel cannot be built and smoke-tested
in a temporary no-deps environment. Report schema v5 records both candidate
checks, UTC generation time, Python version/implementation, non-path
platform identity, and independent crash-reconstruction and replay gates with
canonical fixture and manifest hashes plus case/test counts, so evidence cannot silently retain only
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
4. the crash-reconstruction E2 classifier and exact-call runtime matrix with retained JUnit evidence;
5. the OpenAI stateless-replay E2 module with retained JUnit evidence;
6. deterministic `agent eval` with a retained JSON report;
7. wheel build; and
8. clean wheel installation with both provider extras, CLI help, OpenAI and
   Claude `config init` / `config doctor` / `config validate`, exact
   thirteen-tool installed-MCP discovery, and E1/E2 smoke.

The wheel job sets explicit dummy strings only to exercise documented
credential-presence checks. It launches the real installed MCP executable for
one `initialize` / `list_tools` handshake per provider, so normal MCP startup
may initialize its audit directory and emergency-stop polling. It sends no
provider request, invokes no MCP tool, reads no desktop content, and performs no
desktop action. No CI job receives a valid provider credential or runs E3/E4;
those gates must never be silently added to the default job.

## Human release gates

Before tagging a release, record evidence for every item:

Use [Agent release evidence record](RELEASE_EVIDENCE.md) as the review template.
`NOT RUN` documents a missing gate; it does not turn that gate into a pass.
The current pre-release automated/E3/native audit and its explicit missing
human/hardware/E4/application gates are retained in
[Feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md); that audit
is not release approval.

- CI is green on all supported Python versions.
- The wheel artifact installs in a clean Windows environment.
- OpenAI and Claude retain their reviewed E3 baseline; exact Kimi `cn` +
  `kimi-k2.6`, MiniMax `cn` + `MiniMax-M2.7`, DeepSeek `global` +
  `deepseek-v4-pro`, and Doubao `cn-beijing` +
  `doubao-seed-2-0-lite-260215`, and Qwen `cn-beijing` + `qwen3.7-plus` cells
  are also retained. Every other provider
  profile, route, or sibling model advertised by that release must separately pass its
  exact model/endpoint harmless-fake-MCP E3 matrix; offline compatibility is
  not a waiver, and these records alone are not release approval.
- All four cells in the [E4 isolated desktop smoke runbook](E4_SMOKE.md) pass
  only in disposable Notepad or a VM with a narrow allowlist.
- Read-only and one locally approved low-risk action complete with post-action
  observation for every provider profile included in the desktop release claim.
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
Use explicit `agent recover` only for a strictly eligible persisted boundary;
uncertain dispatches, pending side effects, drift, corruption, and expired
records require a new run after the required human re-observation.

## Install, roll back, or remove a released build

A release is consumed as a built wheel, not as this working tree. An editable
install (`pip install -e .`) tracks whatever is checked out and therefore cannot
be rolled back; do not use one to evaluate a release.

Install a specific version into a clean environment:

~~~powershell
py -3 -m venv .release-venv
.\.release-venv\Scripts\python.exe -m pip install `
  --disable-pip-version-check guarded_desktop_agent-<version>-py3-none-any.whl
.\.release-venv\Scripts\python.exe -c "import importlib.metadata as m; print(m.version('guarded-desktop-agent'))"
~~~

Verify the artifact before installing it. The preflight report records the
wheel filename and its SHA-256; compare against the file you received:

~~~powershell
(Get-FileHash guarded_desktop_agent-<version>-py3-none-any.whl -Algorithm SHA256).Hash.ToLower()
~~~

Roll back by installing the previous wheel over the current one, or by deleting
the environment and recreating it. Removing the package leaves user data in
place:

~~~powershell
.\.release-venv\Scripts\python.exe -m pip uninstall -y guarded-desktop-agent
~~~

State, memory, traces, checkpoints, and campaign ledgers live under the
configured `agent.state_dir`, and audit records under the configured MCP audit
path. Neither is removed by uninstalling; delete them explicitly if the machine
is being decommissioned. Downgrading does not migrate durable state — a ledger
written by a newer version may be rejected by an older one, so finish or
abandon an in-flight campaign before rolling back.

The project remains experimental until the retained E4 evidence is rerun as
required for the release candidate and the full release review is complete.
