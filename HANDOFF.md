# Maintainer handoff

> **Internal engineering notes.** This file preserves operational knowledge for
> maintainers. It is not the product specification; start with
> [README.md](README.md) and [docs/README.md](docs/README.md) for the current
> public documentation.

## Current shape

The codebase is an experimental Windows-only MCP server with eight tools,
a typed Driver Contract v1.0.0, and a single in-process Windows implementation.
The shared core is testable with fake drivers; desktop integration is exercised
by explicit smoke scripts.

Before changing behavior, inspect the current worktree and run the unit suite:

~~~powershell
git status --short --branch
.\.venv\Scripts\python.exe -m pytest -q
~~~

## Source map

~~~text
src/computer_use_mcp/
  contract.py          typed, platform-free Driver Contract
  core.py              session refs, snapshots, stale relocation
  server.py            FastMCP tools and action guard orchestration
  gate.py              foreground owner-chain allowlist
  human_activity.py    synchronous yield after human input
  safety.py            confirmation, e-stop, screenshot redaction
  audit.py             JSONL records
  dpi.py               DPI-awareness bootstrap
  drivers/windows.py   UIA, Win32, capture, process ownership

scripts/               on-device smoke and VMware helper
tests/                 side-effect-free unit tests
out/                   ignored disposable probes and artifacts
docs/                  canonical English documentation
~~~

## Hard-earned implementation facts

1. **Set DPI awareness early.** It must happen before UIA/capture libraries
   initialize, or coordinate alignment breaks under display scaling.
2. **Use native key events for chords.** Win32 `keybd_event` is used for
   combinations such as `Ctrl+S`; do not assume `uiautomation.SendKeys`
   handles every chord correctly.
3. **Foreground is a real resource.** Background processes may not directly
   activate a window. Keyboard actions and focus-based typing need the intended
   foreground target.
4. **Owned dialogs are special.** Save dialogs can be owned top-level windows
   rather than ordinary desktop siblings; `list_windows()` deliberately uses
   Win32 enumeration that includes them.
5. **Modern Notepad is not just an Edit control.** Its document surface can
   expose a writable ValuePattern, and one visible menu item may appear with
   multiple UIA control types. The driver deduplicates by geometry and name.
6. **Browser UIA is lazy.** A first Chromium traversal may only materialize
   accessibility content; warm-up is best effort and must not steal foreground.
7. **Primary display is the supported coordinate domain.** Do not silently
   extend the current model to secondary monitors or region offsets.
8. **Refs are session state.** They accumulate across snapshots; stale actions
   get one role/name relocation attempt. Snapshot the target scope before
   acting across windows so the driver has fresh native handles.
9. **Same-desktop UIA is not background-safe.** A controlled ValuePattern
   operation can alter foreground state. Use an isolated runtime for true
   background work.

## Guardrail checklist for new actions

When adding an action tool, decide explicitly:

- Does it need e-stop and audit? (Usually yes; neither should be skipped.)
- Can it contend with local human input?
- Is foreground allowlist verification appropriate?
- Does its target need dangerous-action confirmation?
- Which direct unit test and on-device smoke demonstrate the behavior?

Document any intentional exception such as `activate_window`, which skips the
foreground allowlist only because it is itself the foreground-changing action.

## Validation policy

~~~powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
git diff --check
~~~

The `scripts/smoke_*.py` scripts can interact with real applications. Do not
run them casually on a sensitive or active workstation. Use a read-only probe
in `out/` to understand a new application before implementing behavior around
its UIA tree.

## Documentation maintenance

- English is canonical. The Chinese root quick-start is intentionally shorter,
  so update it when setup, safety defaults, or supported capability summaries
  change.
- Keep current behavior in the README, configuration page, and tool reference.
- Keep design directions in [docs/DESIGN.md](docs/DESIGN.md) and
  [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md).
- Keep contract changes synchronized with `contract.py`.

Avoid restoring sentence-by-sentence bilingual copies; they obscure the current
status and create needless translation drift.
