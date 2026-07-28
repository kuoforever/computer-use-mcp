# Coding-agent instructions

## Start here

For every Codex or other coding-agent session:

1. Read `PROJECT_STATUS.md`.
2. Read `docs/FULLCYCLE_INTEGRATION.md` for bridge work.
3. Read `docs/PROJECT_OVERVIEW.md` and `docs/CAPABILITY_STATUS.md` only when the
   active task needs broader product context.
4. Inspect `git status --short --branch` before editing.

`PROJECT_STATUS.md` owns the active task and closure backlog. `HANDOFF.md`
contains durable maintainer facts. Capability claims remain owned by
`docs/CAPABILITY_STATUS.md`.

## Current delivery rule

The repository is in closure mode. Work only on the active `GDA-FC-*` item.
Do not resume planned hierarchical control, application campaigns, universal
GUI, Multi-Agent, continual-learning, platform-driver, or operator-UI work
unless `PROJECT_STATUS.md` explicitly changes the active scope.

## Invariants

- The MCP server and existing Runner remain the only desktop dispatch path.
- Model output is untrusted data, never authority.
- Unknown side-effect outcomes are never automatically replayed.
- Refs never silently degrade to coordinates.
- New exports are read-only, bounded, versioned, redacted, and fail closed.
- No API key, token, memory, continuation, screenshot, raw task, model prose,
  or raw tool-result text enters the automatic Full Cycle export.
- Offline tests cannot promote provider, desktop, application, or release
  evidence.

## Editing and validation

- Prefer small single-purpose changes.
- Update tests and the owning contract in the same change.
- Do not rewrite dated evidence.
- Do not update archived plans as if they were current.
- Run the validation commands listed in `PROJECT_STATUS.md`.
- At session end, update the backlog and exact next task without adding a
  second competing project tracker.
