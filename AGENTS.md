# Coding-agent instructions

## Start here

For every Codex or other coding-agent session:

1. Read `PROJECT_STATUS.md`.
2. Read `docs/FULLCYCLE_INTEGRATION.md` for bridge work.
3. Read `docs/career/teaching/README.md` before non-trivial
   implementation or validation work.
4. Read `docs/PROJECT_OVERVIEW.md` and `docs/CAPABILITY_STATUS.md` only when the
   active task needs broader product context.
5. Inspect `git status --short --branch` before editing.

`PROJECT_STATUS.md` owns the active task and closure backlog. `HANDOFF.md`
contains durable maintainer facts. Capability claims remain owned by
`docs/CAPABILITY_STATUS.md`.

## Teaching-oriented collaboration

The detailed, mandatory workflow lives in
`docs/career/teaching/README.md`. It owns the before/during/after step
protocol, interview translation, and resume-evidence threshold. `AGENTS.md`
owns the requirement to follow it.

Teaching must not weaken the single active objective, validation, safety,
cross-repository boundaries, or evidence discipline. Prefer clear Chinese with
exact English technical terms, and never present planned or unverified work as
experience.

## Codex and Claude Code coordination

`AGENTS.md` is the shared source of truth for coding-agent behavior.
`CLAUDE.md` is a lightweight Claude Code entry point that follows this file;
do not duplicate the full policy there.

- Re-read `PROJECT_STATUS.md` and inspect `git status` before editing,
  including when taking over from the other coding agent.
- Treat existing uncommitted changes as user- or peer-owned. Do not overwrite,
  revert, or silently rework them; coordinate scope and preserve unrelated
  edits.
- Prefer one implementation owner for a bounded slice. A second agent may
  review or independently validate it, but must not make overlapping edits
  without an explicit handoff.
- Every handoff must name the outcome, modified files, exact validation and
  results, unresolved risks or limitations, and the single next action.
- A reviewing agent must inspect the code and evidence and run proportionate
  checks itself. It must not convert another agent's summary into a verified
  capability claim without evidence.
- Cross-repository handoffs must preserve the Full Cycle resume point and the
  Runtime/Full Cycle authority and data-lane boundaries in the canonical
  tracker.
- Keep `main` as the only persistent development branch. Start each bounded
  change on a new feature branch, merge it only through a clear PR, then delete
  the merged branch locally and remotely. Use an explicit archive tag for a
  deliberately retired checkpoint that must remain recoverable; do not keep a
  dormant development branch for that purpose.

## Current delivery rule

Work only on the single active item named by `PROJECT_STATUS.md`; do not
hard-code an active task ID in this guide. Paused or completed Full Cycle,
Demo, HUD, and core Runtime items resume only when the user and canonical
status explicitly change scope. Preserve every recorded safe resume point.

Do not resume planned hierarchical control, broad application campaigns,
universal GUI, Multi-Agent, continual-learning, platform-driver, or unrelated
operator-UI work unless `PROJECT_STATUS.md` explicitly changes the active
scope.

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
