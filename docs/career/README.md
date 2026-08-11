# Career and teaching hub

> **Status: current navigation and maintenance contract, reviewed 2026-08-10.**
> Resume content schema: `2`. Shared teaching protocol: `1`.
> Guarded Desktop Agent teaching profile revision: `2`.

This directory keeps two related but different kinds of material:

| Category | Entry | Nature |
| --- | --- | --- |
| Job-application evidence | [Resume evidence](resume/) | A derived view: one Markdown file per candidate highlight, selected and shortened from project evidence |
| Collaboration method | [Teaching collaboration](teaching/) | An interaction policy: how non-trivial delivery work is explained, interpreted, and translated into interview evidence |

The resume pages answer “what can be supported?” Teaching pages answer “how
should we work and learn?” Neither replaces the canonical project tracker.

## Authority model

Resume claims follow this source hierarchy:

1. [Project status](../../PROJECT_STATUS.md) owns active sequencing, compact
   current closure, and the exact resume point after a detour.
2. The archived [2026-08-11 project-status
   snapshot](../archive/PROJECT_STATUS_SNAPSHOT_2026-08-11.md#closure-backlog)
   preserves earlier closure and merge facts; it is non-normative for current
   sequencing.
3. [Capability status](../CAPABILITY_STATUS.md) owns current capability and
   evidence levels.
4. Contract and dated evidence documents own exact behavior, environment,
   metrics, failures, and limitations.
5. Files under `resume/` may select and compress those facts, but may not
   promote, widen, or silently reconcile conflicting owner documents.

Repository evidence proves what the project did. It does not prove which parts
one person designed, implemented, tested, debugged, or documented. Every item
therefore carries a personal-ownership checkpoint before it becomes
submission-ready.

Teaching authority remains in [AGENTS.md](../../AGENTS.md). The modules here
make that requirement operational; conversation carries step-by-step teaching,
while `PROJECT_STATUS.md` remains the only project tracker.

## Evidence distinctions

Keep `Implemented`, `Offline`, `Provider`, `Desktop`, `Application`, `Human`,
and `Release` evidence separate. A mock, detailed contract, green CI job, or
old candidate cannot fill a live or current-candidate cell. A valid negative
result may support engineering judgment; an invalid or unattributable attempt
supports only the need to rerun.

## Maintenance rules

- Keep one candidate highlight per Markdown file and maintain selection logic
  in the resume index rather than copying bullets between files.
- Update an item only after reading its current owner and evidence sources.
- Preserve exact negative results and exclusions; do not rewrite dated evidence
  to match a later implementation.
- Add durable career material only for a meaningful design, implementation,
  verified result, valid negative result, or postmortem—not every conversation.
- Teaching remains in conversation plus these reusable rules; do not create a
  second learning or delivery tracker.
- A change to shared teaching semantics requires a coordinated protocol-version
  update in all participating repositories. Project-local examples, stop rules,
  and profiles may evolve under their own revision without widening that task.
