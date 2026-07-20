# Postmortems

Blameless analyses of failures that actually happened on this project, with the
timeline, root cause, trigger, detection gap, and — most importantly — what the
result does *not* license.

A postmortem here is not a bug-fix note. It exists when the interesting part is
why the failure was invisible, not what the patch was.

| Incident | Date | Summary |
| --- | --- | --- |
| [`activate_window` foreground lock](2026-07-15-activate-window-foreground-lock.md) | 2026-07-15 | Input queues were attached — the wrong pair. No postcondition existed to catch it. |

Related: [architecture decision records](../adr/) for the rules these incidents
informed.
