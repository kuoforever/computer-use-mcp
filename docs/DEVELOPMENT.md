# Development and validation

> **Status: current maintainer workflow.** Unit tests are designed to run
> without desktop side effects; smoke scripts are not.

## Development installation

~~~powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
~~~

The project targets Python 3.11 through 3.13 on Windows. When using a legacy
non-UTF-8 console, set `$env:PYTHONUTF8 = "1"` before running scripts that
emit non-ASCII text.

## Fast validation

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\computer-use-agent.exe eval --cases evals\cases --report out\e1-e2.json
.\.venv\Scripts\python.exe -m build --wheel
git diff --check
~~~

Run these checks for documentation-only changes as appropriate; code changes
that touch a driver, safety boundary, or action path need the matching desktop
smoke as well.

GitHub Actions repeats the offline suite on Windows/Python 3.11-3.13 and runs a
clean wheel-install smoke. It never enables live provider or desktop tests.
See [Release checklist](RELEASE.md).

For a clean release-candidate checkout, `computer-use-agent release preflight`
composes the same local checks and writes sanitized evidence plus retained
E1/E2 and wheel hashes under `out/`. It deliberately uses `build
--no-isolation` and `pip install --no-deps`; install the `dev` extra before
running it. A working tree with milestone edits is expected to fail the clean
candidate gate until those edits are reviewed and committed.

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
