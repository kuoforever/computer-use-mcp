# Two HUD adapters shared one ctypes prototype table

> **Status: postmortem, 2026-08-01.** Moved from `PROJECT_STATUS.md` on
> 2026-08-07. Blameless analysis; not capability evidence.

**Detection gap:** each surface was verified alone. Only opening both
together exposed the collision.


The workflow HUD would not have appeared in a real Demo run, and would not have
said so. `GDA-HUD-005` and `GDA-HUD-006` were verified with each surface driven
alone; opening both together for `GDA-HUD-009` is what exposed it.

`ctypes.windll.user32` returns one cached library object per process, and every
function on it carries a single mutable `argtypes`/`restype`. The Decision Card
and the Progress HUD each define their own `_MONITORINFO` and each pinned
`GetMonitorInfoW.argtypes` to a pointer to its own type. Constructing the card
adapter made the progress adapter's `byref` of a structurally identical type
raise `ArgumentError`, so the progress window failed to open.
`scripts/demo_cross_app.py` builds the card adapter before the Runner opens the
progress window, and `DemoWorkflowProgress` is fail-silent by design, so the
checklist would simply have been missing with `error_count` latched and nothing
on screen.

Every adapter now takes a private library handle through
`computer_use_agent.win32_dll.private_windll`; only the Python-side prototype
tables are private, the loaded DLLs are unchanged. Three offline tests pin it:
the adapters hold distinct handles, prototyping one handle cannot reach another
or the process-wide table, and the exact ordering the Demo uses no longer
breaks the progress adapter.

Isolating the handles then exposed a second latent dependency: the text
measurement helper had been inheriting `CreateFontW`, `SelectObject`, and
`DeleteObject` prototypes that an adapter happened to set on the shared table.
On a private handle nothing had declared them and a default `c_int` return
truncated a 64-bit handle. It now declares every prototype it uses.
