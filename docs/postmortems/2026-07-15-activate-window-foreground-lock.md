# Postmortem: `activate_window` could not take the foreground

Date of incident: 2026-07-15 (session alias `boss-chrome-01`)
Date of verified repair: 2026-07-18
Status: Repaired, regression-tested, retained in [E4 evidence](../E4_EVIDENCE.md)

## Summary

During a live read-only BOSS probe, the Codex desktop app took the foreground.
The `safe_local` gate then correctly denied a Chrome action. Recovering from
that required activating Chrome again — and two attempts to activate a valid,
still-listed Chrome window both failed:

~~~text
ERROR DRIVER_ERROR: could not bring window to foreground
~~~

Nothing was corrupted and no wrong action was taken. The gate held. The failure
was that the tool could not restore the precondition it needed to continue, so
the session dead-ended.

## Timeline

| When | What |
| --- | --- |
| 2026-07-15 | Live probe. Codex regains foreground; gate denies Chrome action; two `activate_window` attempts fail on a valid handle. Defect recorded with a stated *hypothesis*, not a conclusion. |
| 2026-07-15 | Follow-up plan written: isolated activation helper accounting for caller/foreground/target threads, cleanup in `finally`, foreground verification, unit tests, manual regression. |
| 2026-07-18 | Repair implemented and unit tested. Five-case regression passed in the isolated VM. |
| 2026-07-18 | Post-repair on-device run (`boss-mcp-post-repair-01`): activation succeeded for the sole returned Chrome window. |

## Root cause

Windows does not let an arbitrary process seize the foreground. A caller can
only succeed if it belongs to the input queue group that currently owns it.

The pre-repair driver attached the **existing foreground thread to the target
window thread** — but the MCP caller thread was never part of that attachment.
The process actually making the `SetForegroundWindow` call therefore stayed
outside the input group, and Windows applied the foreground lock.

The distinction matters: the code did attach input queues, so it looked like it
had handled the foreground-lock problem. It attached the wrong pair.

## Trigger

Another application (the Codex desktop app) taking the foreground.

This is not exotic — it happens whenever the operator alt-tabs. But it does not
happen in a session where the target application is the only thing in front,
which is how the tool had mostly been exercised until then.

## Detection gap

Two gaps, and the second is the one worth fixing.

1. **No test could reach the code.** Activation called `ctypes.windll.user32`
   directly at the point of use. There was no seam, so its ordering and cleanup
   contract was unreachable offline and only observable by moving real windows
   on a real desktop.

2. **The failure had no postcondition to fail against.** The native calls were
   made and their return values treated as the outcome. A call sequence that
   returns without raising, yet leaves a different window in front, produced no
   error. Absent a check of *what actually ended up in the foreground*, this class
   of bug can only be found by a human noticing the wrong window.

The offline fixtures were not "insufficiently detailed." They were absent for
this path by construction, because the code had no injection point.

## Repair

`_activate_window_with_api(hwnd, user32, kernel32)` in
`src/computer_use_mcp/drivers/windows.py`, with the native API objects passed in
— the docstring states the reason plainly: it makes ordering and cleanup
testable without touching the real desktop.

Behavior:

1. Fail with `STALE_ELEMENT` if the window no longer exists.
2. Restore a minimized target before anything else, and fail if it stays iconic.
3. Return early, doing nothing, if the target is already foreground and was not
   minimized.
4. Attach the **caller** thread to both the foreground and the target threads,
   skipping identical or duplicate pairings.
5. `BringWindowToTop`, then `SetForegroundWindow`.
6. Detach every successful attachment in reverse order in a `finally`, and
   report a cleanup failure rather than swallowing it.
7. Re-assert the restore if the window went iconic again during detachment.
8. **Verify `GetForegroundWindow() == hwnd` and fail if not.**

Step 8 is the substantive change. Steps 4 and 7 fix the mechanism; step 8 is
what makes any future regression in this area impossible to report as success.

## Regression tests

`tests/test_windows_activation.py`, driving injected fakes:

- attach ordering, and reverse detach
- partial attach failure still detaches every successful pair
- cleanup attempts all detaches and reports failure
- already-foreground is idempotent, with no attachment or restore
- minimized restore before attachment; re-restore if activation re-minimizes;
  final restore postcondition failure is reported
- stale numeric handle fails before any thread or activation call
- invalid text window id fails without loading native APIs
- **native success without the foreground postcondition is a failure**
- `SetForegroundWindow` failure still detaches all pairs

Plus the five-case on-device regression in the isolated VM, recorded in
[E4 evidence](../E4_EVIDENCE.md) with a sanitized result digest.

## What this does *not* license

- It does not make activation reliable against every application. Windows may
  still refuse the foreground for reasons outside this code path; the postcondition
  reports that honestly rather than fixing it.
- The E4 result is scoped to the reviewed VM, models, and repair tree. It is not
  a general Windows compatibility claim.
- It says nothing about multi-monitor or background activation, both of which
  remain unsupported.
- The 2026-07-18 post-repair run covered **one** Chrome window on one machine.

## What generalized

The specific bug was an attachment pair. The reusable lesson is the one in the
detection gap: **a desktop operation without a verified postcondition cannot
fail correctly.** Native calls report that they were made, not that they
worked. Where the two differ, the system must check the world, not the return
value.

That principle also underpins
[ADR-001](../adr/001-uncertain-dispatch-is-never-auto-replayed.md) — post-action
observation exists for the same reason — and
[ADR-002](../adr/002-ref-actions-never-silently-fall-back-to-coordinates.md),
where "the click was issued" is likewise not evidence that the intended element
received it.

## Unknown

- Whether the pre-repair code ever succeeded across processes by luck, or had
  always been broken for that case. The retained records do not establish this.
- The exact Windows revision of the 2026-07-15 host. The repair was verified on
  the E4 VM revision recorded in that document.
