# Operator progress viewer

> **Status: reducer and passive window shell implemented; live polling not yet.**
> The pure checkpoint-to-view-model reducer (delivery step 1) is implemented and
> offline tested in `computer_use_agent.progress_view`. The passive
> non-activating window (delivery step 2) is implemented in
> `computer_use_agent.progress_window` over an injectable native surface and
> offline tested against a recording fake; its real ctypes backend lives in
> `computer_use_agent.progress_window_win32` and is exercised only by the
> operator-approved `scripts/smoke_progress_window.py`, which has **not** been
> run on-device yet. Live checkpoint polling, multi-run grouping, and campaign
> state remain planned. The projection stays read-only over validated
> checkpoints and future campaign state.

This passive projection is one surface of the planned
[Operator experience](OPERATOR_EXPERIENCE.md). The desktop presence indicator
and focus-taking Decision Card have separate behavior and authority boundaries;
they must not be implemented as hidden controls inside this viewer.

## Goal

Show several concurrent or historical runs without requiring the operator to
return to Codex and without becoming an action or replay surface.

## Data sources

MVP reads only:

~~~text
state_dir/runs/<run_id>/state.json
state_dir/campaigns/<campaign_id>/manifest.json   # after campaigns exist
~~~

Reuse the strict, path-safe checkpoint reader used by `agent report`. Do not
read trace JSONL, continuation artifacts, screenshots, task text, page text, or
provider messages.

## Checkpoint v1 limitations

The current checkpoint can display:

- run ID;
- phase and fixed terminal failure code;
- last update time;
- model/tool calls;
- provider/tool latency totals;
- aggregate input/output token numbers;
- image-result and tool-failure counts.

It cannot reliably display:

- active elapsed time, because `created_at` is absent and `run_duration_ms`
  exists only for terminal runs;
- screenshot count, because `image_results` counts all returned images;
- whether zero tokens means reported zero or missing provider usage;
- whether a nonterminal run is alive, blocked, or crashed.

The MVP must label these honestly. Do not infer `RUNNING` or `BLOCKED` from a
nonterminal phase alone.

## Planned checkpoint additions

A backward-compatible checkpoint revision or new version should add:

~~~json
{
  "created_at": "...",
  "metrics": {
    "provider_usage_report_count": 0,
    "screenshot_results": 0
  }
}
~~~

Campaign workers additionally provide a coarse heartbeat and lease state in
the campaign manifest. Older checkpoint versions remain readable with unknown
fields displayed as unavailable.

## Status projection

Use a fixed mapping:

| Source state | Display state |
| --- | --- |
| `WAITING_APPROVAL` | Waiting approval |
| `SUCCESS` | Complete |
| `FAILED` | Failed |
| `UNKNOWN_OUTCOME` | Uncertain; re-observe before retry |
| `CANCELLED` | Cancelled |
| Other checkpoint v1 phase | In progress at last checkpoint; liveness unknown |
| Future fresh campaign heartbeat and valid lease | Running |
| Future expired heartbeat or lease | Stale; inspect before reclaim |
| Future `CHALLENGE` campaign state | Waiting for operator |

## Window behavior

The default overlay is passive:

- create a tool window with non-activating behavior;
- show or refresh it without changing the foreground window;
- use `SetWindowPos(..., SWP_NOACTIVATE)` for position/topmost updates;
- do not expose keyboard focus, execution controls, or editable fields;
- make always-on-top optional and persisted locally.

If a later version supports interactive selection, it must define one of:

1. pointer interaction that preserves `WS_EX_NOACTIVATE`; or
2. an explicit inspect mode that may take focus and therefore triggers normal
   human-activity yielding.

The spec must not promise both arbitrary keyboard interaction and zero focus
change.

Approval choices and human takeover belong to an explicit Decision Card or
operator mode. Opening that surface first yields Agent desktop authority and
may then take focus; closing it does not silently return authority or approve an
action.

## Layout

~~~text
+ Computer Use --------------------------------------+
| campaign: saved-jobs     40 / 300      last 00:12  |
| run_ab12  PLANNING       calls 6/9     usage known |
| tokens    in 18.4k       out 2.1k      images 2    |
|----------------------------------------------------|
| run_cd34  WAITING_APPROVAL               00:31     |
| run_ef56  UNKNOWN_OUTCOME       re-observe         |
+----------------------------------------------------+
~~~

Do not display task text, document text, titles, screenshots, typed values,
model prose, arbitrary errors, credentials, or account identifiers.

## Multi-session behavior

- Group by `campaign_id` when present and otherwise by independent `run_id`.
- Never merge conversational context from different Codex sessions.
- Existing run IDs are immutable; duplicate or path-unsafe IDs fail closed.
- Sort active campaigns first, then by validated update timestamp.
- Bound scanning to the same maximum used by `agent report`.
- A corrupt record makes that record unavailable; it must not contaminate a
  valid record or produce a partially trusted view model.

## Acceptance checks

1. Opening, refreshing, moving, or changing topmost state does not alter the
   foreground HWND in passive mode.
2. Two run IDs and two campaign IDs remain separate under rapid atomic file
   replacement.
3. The reader returns the previous or next complete checkpoint, never a mixed
   record.
4. Unknown versions, symlinks, malformed metrics, and unsafe paths fail closed.
5. Redaction tests prove forbidden fields cannot enter the view model.
6. Checkpoint v1 unknown token coverage and liveness are not displayed as zero
   or running facts.
7. `UNKNOWN_OUTCOME` is visually distinct and never presents a retry button.

## Delivery sequence

1. Pure checkpoint-to-view-model reducer and tests. **Implemented** in
   `computer_use_agent.progress_view`: `checkpoint_to_view` reduces one
   validated checkpoint and `build_progress_projection` scans a bounded
   `state_dir`, isolating corrupt or unsafely named records.
2. Passive non-activating window with synthetic records. **Implemented** in
   `computer_use_agent.progress_window`: `render_progress_lines` renders the
   step-1 view models into bounded, whitelisted lines, and
   `PassiveProgressWindow` drives them over the `ProgressWindowApi` surface —
   which deliberately exposes no activate, focus, or foreground-setting call, so
   a controller written against it cannot take focus. The window is created
   `WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST` over `WS_POPUP`, shown
   with `SW_SHOWNOACTIVATE`, and repositioned with `SWP_NOACTIVATE`. Acceptance
   check 1 is proven in injectable form (foreground unchanged across
   open/refresh/move/topmost/close) by `tests/agent/test_progress_window.py`;
   the real ctypes backend is `computer_use_agent.progress_window_win32` and is
   confirmed on a live desktop only by the operator-approved
   `scripts/smoke_progress_window.py`.
3. Atomic live checkpoint polling.
4. Multi-run grouping.
5. Campaign progress after the long-running task manifest is implemented.
6. Integrate shared presence and Decision Card state only through the pure
   operator view-model contracts; keep execution and approval out of the
   passive window.
