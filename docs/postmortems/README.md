# Postmortems

Blameless analyses of failures that actually happened on this project, with the
timeline, root cause, trigger, detection gap, and — most importantly — what the
result does *not* license.

A postmortem here is not a bug-fix note. It exists when the interesting part is
why the failure was invisible, not what the patch was.

| Incident | Date | Summary |
| --- | --- | --- |
| [`activate_window` foreground lock](2026-07-15-activate-window-foreground-lock.md) | 2026-07-15 | Input queues were attached — the wrong pair. No postcondition existed to catch it. |
| [Shared ctypes prototype table](2026-08-01-hud-shared-ctypes-prototype-table.md) | 2026-08-01 | Two HUD adapters pinned the same process-wide function prototype. Each verified alone; only opening both exposed it. |
| [Presence halo: three causes](2026-08-02-presence-halo-three-causes.md) | 2026-08-02 | Three independent causes behind one symptom, none of them the suspected one. |

Related: [architecture decision records](../adr/) for the rules these incidents
informed.
