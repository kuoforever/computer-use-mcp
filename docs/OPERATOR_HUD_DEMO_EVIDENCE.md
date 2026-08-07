# Complete Chrome-to-Word run with the rebuilt Operator HUD

> **Result: PASS — retained real-environment run on 2026-08-02.**
> Three defects were found in the Presence halo while trying to observe it, and
> all three are fixed. The halo's own behaviour is verified programmatically
> against the real window, not by eye; a Demo run with the fixes in place has
> not yet been performed.
>
> The run was authorized by
> [its live evidence plan](OPERATOR_HUD_LIVE_EVIDENCE_PLAN.md), which records
> the preconditions, abort criteria, and what the run would not establish.

## Claim

The bounded Chrome-to-Word Demo completed end to end while driven by the
rebuilt operator surfaces: the workflow Progress HUD fed by
`DemoWorkflowProgress`, the rebuilt Decision Card, and the Presence halo.

This is bounded evidence for one fixed public page and one fixture document. It
is not a claim of arbitrary web understanding, authenticated browser
automation, general Office automation, or universal GUI capability. The
provider is a fixed deterministic script and has no authority.

## Retained run

| Field | Value |
| --- | --- |
| Run ID | `cross-app-demo-20260802-141038-994636` |
| Result | `PASS` |
| Durable phase | `SUCCESS` |
| Tool calls | `17 / 17` |
| Approved side effects | `7 / 7` |
| Model turns | `18 / 20` |
| Document SHA-256 | `2a9bf27accdb691393f8820bdd53b3fa558e98b8408c9df3c7c786c687dc3901` |
| Dispatch | Existing Runner and stdio project MCP only |

Verified independently of the script's own claim: the saved DOCX is a valid
19-entry package, and reading `word/document.xml` directly finds the fixed
`VERIFIED PORTAL FOLLOW-UP` marker followed by the four fixed summary lines.
The durable checkpoint records `phase=SUCCESS` with no event body — only
`task_length` — so the redaction contract held.

Cleanup closed exactly the two launched fixtures, one close request each,
disposition `windows_closed`, scope `exact_launched_processes_only`. The
operator's pre-existing Chrome windows were not touched.

## Operator observations

The run existed to observe the HUD, so the operator's direct observations are
the evidence for the surfaces that cannot be captured:

| Observation | Result |
| --- | --- |
| Workflow breadcrumb on the card matched the Progress HUD's current chapter | **Confirmed** |
| Progress HUD showed chapters rather than tool-call budgets | Confirmed by the run's own surface wiring; no budget line was reported |
| Full-screen Presence halo visible during the run | **Not visible — three defects, see below** |
| Alt+Tab availability while a card was open | **Not tested this run** |

## Three defects behind one symptom: the halo was never visible

The operator saw the Progress window's accent but no screen-edge halo at any
point, across three complete runs. Chasing it by eye found one cause at a time
and each fix looked right in isolation. Instrumenting the run settled it.

`scripts/demo_cross_app.py` now carries a presence probe that records every
projection the halo is asked to show and samples the native window from its own
thread. A window with a pending update region has not been painted. The report
is written into `final-state.json`, so this evidence never rests on someone
saying they saw a halo -- which matters, because Presence is
`WDA_EXCLUDEFROMCAPTURE` and can never appear in a screenshot.

The sampled run `cross-app-demo-20260802-144124-559107` reported
`projection_count: 0`, `samples_painted: 0`, `samples_window_absent: 32`: the
surface was never synced and the window never existed.

### Defect 1: the halo was never pumped

`RunPresenceCoordinator` had no worker thread and never called a message pump,
unlike `RunProgressCoordinator`. A Win32 window that is never pumped never
receives `WM_PAINT`. The halo was created, visible, and layered with a colour
key, and it drew no border and no phase tab -- which for a colour-keyed window
means fully transparent.

Measured directly: without a pump the update region stayed
`(0, 0, 2560, 1600)`; one `pump()` cleared it. Every place the halo had been
tested -- `show_presence_phases.py`, `smoke_presence_window.py`,
`smoke_hud_composition.py` -- pumps it. The Demo never did, so the halo had
never been visible in a real run, before or after any change made this week.

The coordinator now owns a UI thread and pumps, mirroring the progress side, and
a test asserts the Demo's `_presence()` supplies a pump.

### Defect 2: presence is permanently suppressed at the first approval

The cause is exact.

`runner.py` releases presence before a focus-taking approval:

```python
if isinstance(self.ports.approvals, FocusTakingApprovalPort):
    if self.ports.approvals.focus_taking:
        safe_presence.release()
```

`FailSilentLifecycle.release()` calls `_suppress()`, which sets
`_suppressed = True` permanently and then calls the port's `release()`. Every
later `on_phase` is discarded. The first approval arrives within seconds of the
run starting, so the halo is torn down almost immediately and never returns.

This is a terminal operation used to express a transient yield. The presence
model already has the right vocabulary for the intended behaviour:
`PresencePhase.WAITING_APPROVAL` with `DesktopAuthority.WAITING`, which
`scripts/show_presence_phases.py` holds for inspection. The design intends the
halo to change state during an approval, not to disappear for the rest of the
run.

`GDA-HUD-001`'s acceptance names this clause directly: *approval-wait
visibility is explicitly specified and verified*. `yield_authority` now
expresses the yield reversibly, and the ordering the safety test pins --
yield, then card, then dispatch -- is unchanged.

### Defect 3: introduced while fixing defect 1, caught by the probe

`RunPhase.CREATED` closes any stale surface at the start of every run. The
first pumped implementation treated that close as "stop the worker", so the
worker started, saw a stop already set, and exited before syncing anything --
which is what the sampled run above recorded. Closing the window and ending the
lifecycle are now distinct, and a test pins the CREATED-then-active sequence.

This one is worth stating plainly: it was introduced by the fix and would have
shipped as another "still no halo" had the run not been instrumented.

### Verification

Replaying the Demo's exact phase order against the real halo window, checking
existence, visibility, and whether the update region is clear:

```
after CREATED          NO WINDOW
after OBSERVING        visible=True painted=True
after PLANNING         visible=True painted=True
during approval yield  visible=True painted=True
after EXECUTING        visible=True painted=True
second approval yield  visible=True painted=True
after VERIFYING        visible=True painted=True
after SUCCESS          NO WINDOW
errors: 0
```

`CREATED` correctly shows nothing and `SUCCESS` correctly destroys the window.
Both approval yields keep a painted halo. **A complete Demo run has not been
performed since these fixes**, so the retained run above still records a run
whose halo was invisible.

Keeping the halo up during an approval is safe, and that is now demonstrated
rather than assumed: `scripts/smoke_hud_composition.py` shows the halo stays
click-through (`HTTRANSPARENT`) and non-activating (`MA_NOACTIVATE`) with the
Decision Card open, so it cannot swallow the clicks meant for the card.

## First attempt: the desktop must be left alone during startup

An earlier attempt, `cross-app-demo-20260802-140826-542018`, failed at the
first tool call with `DEMO_CONTROLLED_WINDOW_NOT_FOUND`. It is retained as
failed evidence.

The provider binds Chrome with `require_foreground=True`, a hardening added so
a stale same-title browser cannot be bound. The Demo launches Chrome, then
starts the MCP server, and only then issues `list_windows`, so the launched
window has to still be foreground when that call lands.

A diagnostic showed the launched window correctly foreground with the correct
title at five and nine seconds, and foreground on a different Chrome window by
fifteen seconds. **The operator was interacting with the machine throughout
that diagnostic and reports having probably clicked elsewhere.** Nothing here
distinguishes spontaneous foreground drift from ordinary local input, and local
input is the simpler explanation. It should not be recorded as one.

The retry passed with the desktop untouched during startup.

The durable conclusion is an operating requirement, not a defect: the Demo
cannot pre-activate its own window, because activation is approval number one,
so it depends on its freshly launched window still being foreground when the
first observation lands. **The desktop must be left alone from launch until the
first Decision Card appears.** That requirement was not written down anywhere
before this run; it is now in the live evidence plan.

Starting the MCP server before launching the fixtures would shorten the window
without changing any authority. That is an optional robustness change, not a
fix for a demonstrated defect.

## Promotion boundary

This retains one complete Chrome-to-Word run against the rebuilt HUD. It does
not establish 100% or 125% DPI acceptance, a real Alt+Tab press, universal GUI
capability, provider or model capability, or release readiness. No
`GDA-HUD-*` row is promoted to passed on the strength of this run alone;
`GDA-HUD-001` in particular is now blocked on the defect this run found.
