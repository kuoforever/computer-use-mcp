# Live evidence plan: complete Chrome-to-Word run with the rebuilt HUD

Status: **executed on 2026-08-02.** Date written: 2026-08-01. The result and
what it found are in
[the run evidence](OPERATOR_HUD_DEMO_EVIDENCE.md); this document is retained
unedited except for the startup requirement the run itself established.

`PROJECT_STATUS.md` requires an explicit evidence plan before an on-device
smoke runs on an active desktop. This is that plan for the one run the
remaining HUD work has converged on. It is short on purpose: the Demo already
exists and has passed twice before. What is new is the HUD it drives.

## Why this run is not a repeat

The last complete run, `cross-app-demo-20260730-042826`, passed against the old
HUD. Since then every operator surface changed, and one of the changes means
the previous passes cannot be transferred:

- the workflow Progress HUD is now driven by `DemoWorkflowProgress` instead of
  the generic `state_dir` poller, so the six Host-owned chapters replace
  tool-call budgets on screen;
- the Decision Card was rebuilt: fixed geometry, painted header, owner-drawn
  choices, one detail region instead of two nested scrollers;
- the Presence halo scaled by 1.0 on a scaled display and now scales correctly,
  which is why it was reported as invisible;
- **the workflow HUD would not have appeared at all.** Two adapters shared one
  ctypes prototype table, and the Demo's construction order made the Progress
  window fail to open, silently. That was fixed on 2026-08-01 and has never
  been exercised by a complete run.

So this run is the first that can show the rebuilt HUD end to end. Six isolated
live smokes cover the surfaces individually and in composition; none of them
opens the Runner, the MCP server, Chrome, or Word.

## Preconditions, verified on this machine on 2026-08-01

| Requirement | State |
| --- | --- |
| `chrome.exe` at the reviewed path | present |
| `WINWORD.EXE` at the reviewed path | present |
| `.venv\Scripts\guarded-desktop-mcp.exe` | present |
| `demo_templates\word-collaboration-research.docx` | present |
| Offline gate | passing |

Before starting, the operator should also confirm: no unsaved work in any open
Word window, and no personal Chrome window that must not be disturbed. The Demo
launches its own Chrome with a fresh empty profile and its own Word instance,
and its cleanup closes only the exact processes it launched.

**Leave the desktop alone from launch until the first Decision Card appears.**
The Demo binds its Chrome window by requiring it to be foreground, and it
cannot pre-activate that window because activation is approval number one. It
launches Chrome, starts the MCP server, and only then observes; clicking
another window in that interval binds nothing and the run fails closed with
`DEMO_CONTROLLED_WINDOW_NOT_FOUND`. This happened on the first attempt on
2026-08-02. After each approval, keep hands off for a few seconds as well: the
approval-to-dispatch readiness needs three consecutive healthy idle samples.

## What the run does

One fixed provider script, seventeen tool calls, seven approvals. The provider
is not a model and has no authority; the Runner remains the only policy,
approval, grounding, budget, and MCP dispatch path.

Budgets are `max_model_turns=20`, `max_tool_calls=17`, `max_side_effects=7`.
Each Decision Card has a 180-second timeout.

The seven approvals the operator must answer, in order:

1. Open the public source (Chrome activation)
2. Scroll to the next article section (`PageDown`)
3. Switch to the research notes (Word activation)
4. Focus the document editor (click)
5. Move to the follow-up section (`Ctrl+End`)
6. Type the verified source summary (fixed text)
7. Save and preserve the document (`Ctrl+S`)

Nothing else is dispatched. A card that times out, is closed, or is dismissed
with `Esc` is a denial, and a denied gate is never replayed.

## What the operator watches for

This run exists to observe the HUD, so the things worth looking at are:

- the halo is visible throughout, and visibly changes at the approval boundary;
- the Progress HUD shows the six chapters and advances through them, and never
  shows a tool-call budget;
- each Decision Card names the exact action, the application, `APPROVAL n/7`,
  and a workflow breadcrumb that matches the Progress HUD's current chapter;
- Chrome and Word stay foreground during passive updates, and the card alone
  takes focus when it appears;
- nothing covers the part of Chrome or Word the operator needs to read.

## Abort

The MCP panic hotkey aborts every action. `Esc` on any card denies. Closing the
card denies. Any of these ends the run safely; none replays.

## What is retained

The run writes to `out\cross-app-demo\runs\<stamp>\`:

- `initial-state.json` — empty browser profile, pristine DOCX hash, absence of
  the typed marker, fixed browser geometry, cleanup contract;
- `final-state.json` — outcome, failure class if any, fixture identity, close
  count, disposition, exit and process-running snapshots;
- the disposable DOCX;
- the redacted trace and checkpoint under the run's state directory.

If the run passes, a dated evidence document records the run ID, tool-call and
side-effect counts, and the exact HUD observations. Screenshots of the Decision
Card and Progress HUD may be retained through the existing fail-closed capture
helper. **Presence cannot be captured** — it is `WDA_EXCLUDEFROMCAPTURE` by
design and must not be made capturable to produce an image. Its evidence is the
operator's direct observation, recorded as such.

## If it fails

A failed run is failed evidence. It is recorded with its failure class and it
does **not** replace the existing passing records for `GDA-DEMO-001` and
`GDA-DEMO-002`. This already happened once: the exploratory run
`cross-app-demo-20260730-044009-247254` ended after five tool calls with a
known `DENIED_BY_GATE`, and it is retained as a failure.

Cleanup runs from a `finally` block regardless: it posts `WM_CLOSE` only to the
visible unowned top-level windows of the exact launched PIDs, force-terminates
only if owned windows remain after the bounded wait, and never scans or
terminates by executable name. Pre-existing Chrome and Word windows are not
touched.

## What this run will not establish

- universal GUI capability, arbitrary web understanding, or general Office
  automation — it is bounded to one fixed public page and one fixture document;
- 100% or 125% DPI acceptance, which needs display scaling changed;
- a real Alt+Tab press, which the operator must perform;
- any provider or model capability, since the provider is a fixed script.

## Go/no-go

The plan needs the operator present for roughly five minutes to answer seven
approvals. It is safe to defer: nothing else in the backlog depends on it
except the three rows that name it, and no row will be promoted without it.
