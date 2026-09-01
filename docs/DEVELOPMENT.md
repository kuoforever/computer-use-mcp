# Development and validation

> **Status: current maintainer workflow.** Unit tests are designed to run
> without desktop side effects; smoke scripts are not.

## Development installation

For the canonical Windows/Python 3.13 contributor environment, run the
repository-owned bootstrap from the repository root:

~~~powershell
.\scripts\bootstrap_dev.ps1
~~~

The script creates or reuses `.venv`, rejects a stale lock, installs the
Windows/Python 3.13 `.[dev]` baseline from
`requirements/dev-py313-windows.lock` with package hashes enforced, and then
installs this checkout in editable mode without re-resolving dependencies. It
does not activate or delete an environment. A fresh environment is the exact
reproducible baseline; rerunning against an existing environment converges the
locked packages but deliberately does not remove separately installed extras.
Use `-EnvironmentPath .venv-clean` when a separate clean environment is useful.

The lock covers the same core plus `dev` dependency profile used by routine CI.
Provider SDKs, Playwright, observability, and the Temporal proof of concept
remain task-specific extras and are not silently installed into every
contributor environment. Install an explicit extra only when that work is in
scope, for example `.[agent-openai]` or `.[agent]`.

The project still tests Python 3.11 through 3.13 on Windows. Python 3.11/3.12
compatibility work may use the existing non-locked installation path and must
rely on the CI matrix for cross-version evidence:

~~~powershell
py -3.12 -m venv .venv-312
.\.venv-312\Scripts\python.exe -m pip install -e ".[dev]"
~~~

The required Python 3.13 quality cell installs the hash-locked baseline and
then installs the checkout editable with no dependency resolution. Python
3.11/3.12 remain floating compatibility cells because the current lock is
explicitly 3.13-only. A separate scheduled or manually dispatched Python 3.13
floating canary runs the offline suite to reveal upstream dependency drift
without making pull-request resolution non-deterministic.

When using a legacy non-UTF-8 console, set `$env:PYTHONUTF8 = "1"` before
running scripts that emit non-ASCII text.

## Updating the development lock

After changing project or `dev` dependencies, regenerate the lock on Windows
with Python 3.13:

~~~powershell
.\scripts\update_dev_lock.ps1
~~~

The updater keeps its pinned `pip-tools` environment under ignored `out/`,
emits no local index URL or machine path, and binds the result to the complete
`pyproject.toml` content using an LF-normalized SHA-256 so Git checkout line
endings cannot cause a false stale-lock result. Review the dependency and hash
diff. The bootstrap and offline contract test fail closed when
`pyproject.toml` changes without a matching lock update.

The repository `.gitattributes` makes tracked text LF-canonical and marks
binary document/image/archive formats explicitly. Do not work around an EOL
diff with a global Git setting or a mass renormalization inside an unrelated
feature slice.

## Fast validation

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest tests\agent\test_openai_replay_evaluation.py -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\guarded-desktop-agent.exe eval --cases evals\cases --report out\e1-e2.json
.\.venv\Scripts\python.exe -m build --wheel
git diff --check
~~~

Run these checks for documentation-only changes as appropriate; code changes
that touch a driver, safety boundary, or action path need the matching desktop
smoke as well.

GitHub Actions preserves the required `Offline quality (Python 3.11/3.12/3.13)`
contexts and repeats the offline suite across all three versions. Only the
locked 3.13 cell runs Ruff, mypy, documentation consistency, crash/replay, and
deterministic report gates; their reports are uploaded once. The separate
scheduled/manual floating canary and the clean wheel-install smoke do not enable
live provider or desktop tests. Every third-party Action is pinned to an
immutable commit. See [Release checklist](RELEASE.md).

For a clean release-candidate checkout, `guarded-desktop-agent release preflight`
composes the same local checks and writes sanitized evidence plus retained
E1/E2 and wheel hashes under `out/`. It deliberately uses `build
--no-isolation` and `pip install --no-deps`; install the `dev` extra before
running it. A working tree with milestone edits is expected to fail the clean
candidate gate until those edits are reviewed and committed.
The preflight checks the candidate identity again after every gate. Do not move
`HEAD`, stage files, or edit the working tree while it runs; either endpoint
drift makes the v5 evidence fail closed. The report records UTC and the current
Python/platform identity without retaining a user name, host name, or executable
path. It also records the independent crash-reconstruction and replay gates'
canonical fixture and manifest hashes plus case/test counts. It describes one local runtime; use CI for supported Python matrix
evidence.
Its child processes do not inherit arbitrary shell variables. If a local tool
requires another environment variable, review and add that exact platform
requirement to the allowlist with a regression test; do not restore broad host
environment inheritance. Pip index/input/config discovery and Python user site
loading remain disabled for the preflight.

## Desktop smoke scripts

Scripts named `scripts/smoke_*.py` interact with the real desktop. They can
start Notepad, move focus, issue keys, create dialogs, and interact with browser
windows. Close sensitive applications and obtain operator approval before
running them.

| Script | Primary coverage |
| --- | --- |
| `smoke_v0.py` | DPI and coordinate alignment |
| `smoke_v01.py` | UIA value-setting |
| `smoke_v02.py` | Save dialog and ref actions |
| `smoke_v03.py` | Window enumeration, activation, deduplication, and coordinate clicks |
| `smoke_core.py` | Session refs and snapshot serialization |
| `smoke_server.py` | MCP tool wiring and foreground gate |
| `smoke_safety.py` | Confirmation, e-stop, redaction, and audit |

Use `out/` for disposable probes and generated artifacts; it is intentionally
ignored by Git. Promote repeatable observations into a smoke or unit test rather
than retaining a one-off probe as production behavior.

## Change boundaries

- Keep `contract.py` platform-free. The shared core must not import Windows,
  macOS, or Linux driver modules.
- Update [Driver Contract](DRIVER_CONTRACT.md) and its changelog when changing
  a primitive or shared data structure.
- New action tools must be evaluated against the e-stop, human-activity,
  allowlist, confirmation, and audit behavior in `server.py`.
- Update the English canonical docs in the same change when behavior changes.
  Update the Chinese quick-start when its installation, safety, or supported
  capability summary changes.
- Keep target capabilities out of current-runtime documentation; record them in
  [the roadmap](EXECUTION_PLAN.md) instead.

For implementation-specific operational notes, see [Maintainer handoff](../HANDOFF.md).
