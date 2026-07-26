# Operator progress viewer

> **Status: reducer, passive window, live polling, independent-run grouping,
> campaign progress, honest checkpoint telemetry, and opt-in ordinary-run,
> bounded plan-run, read-only recovery, plus fixed campaign execution lifecycle
> wiring implemented.**
> The pure checkpoint-to-view-model reducer (delivery step 1) is implemented and
> offline tested in `computer_use_agent.progress_view`. The passive
> non-activating window (delivery step 2) is implemented in
> `computer_use_agent.progress_window` over an injectable native surface and
> offline tested against a recording fake; its real ctypes backend lives in
> `computer_use_agent.progress_window_win32` and its non-activation was
> confirmed on a live desktop over synthetic records by the operator-approved
> `scripts/smoke_progress_window.py` ([retained evidence](PROGRESS_WINDOW_EVIDENCE.md),
> 2026-07-22). Atomic live checkpoint polling (delivery step 3) is implemented
> and offline tested in `computer_use_agent.progress_poller`, including the
> `computer_use_agent.atomic_file` publish/read contract it required
> ([measurements](CHECKPOINT_PUBLISH_EVIDENCE.md)); it followed a real
> `RunRecorder` transition to the drawn window on a live desktop with the
> foreground unchanged and every concurrent publish succeeding
> ([retained evidence](PROGRESS_POLLER_EVIDENCE.md), 2026-07-22). Independent
> runs are now grouped into fixed Attention, In progress, and History sections,
> with strict timestamp validation, deterministic newest-first ordering, and a
> global display cap that prioritizes attention. Campaigns are read through a
> stable, lock-free snapshot of their validated control files and grouped into
> Campaign attention, Active campaigns, and Campaign history without taking
> execution authority. The projection remains strictly read-only.
> Agent `run`, `resume`, bounded observation-only `plan run`, and explicit
> read-only recovery can now opt into a dedicated background UI thread that
> wakes after durable checkpoints and closes on E-stop/final cleanup. Native
> ordinary-run lifecycle evidence is
> [retained here](PROGRESS_LIFECYCLE_EVIDENCE.md).
> One persisted observation-pending run also has bounded read-only
> [recovery lifecycle evidence](RECOVERY_PROGRESS_LIFECYCLE_EVIDENCE.md).
> The three fixed MCP-backed campaign execution commands start the same poller
> over validated campaign state; zero-port campaign control commands remain
> window-free. The fixed synthetic command has retained
> [native lifecycle evidence](CAMPAIGN_PROGRESS_LIFECYCLE_EVIDENCE.md); BOSS
> campaign lifecycle wiring remains offline-only.

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
state_dir/campaigns/<campaign_id>/{manifest,items,batches,heartbeat,handoff}
~~~

Reuse the strict, path-safe checkpoint reader used by `agent report`. Do not
read trace JSONL, continuation artifacts, screenshots, task text, page text, or
provider messages.

## Checkpoint compatibility and telemetry

Every newly written v1 checkpoint can display:

- run ID;
- phase and fixed terminal failure code;
- last update time;
- creation time and elapsed time at the last checkpoint;
- model/tool calls;
- provider/tool latency totals;
- aggregate input/output token numbers plus whether every model turn reported
  both values;
- successful screenshot count, generic image-result count, and tool-failure
  count.

Older v1 checkpoints may omit `created_at`,
`metrics.provider_usage_report_count`, and `metrics.screenshot_results`. The
reader keeps those facts unavailable rather than interpreting their absence as
zero. No checkpoint can reliably display:

- whether a nonterminal run is alive, blocked, or crashed.

The MVP must label these honestly. Do not infer `RUNNING` or `BLOCKED` from a
nonterminal phase alone.

The backward-compatible fields are:

~~~json
{
  "created_at": "...",
  "metrics": {
    "provider_usage_report_count": 0,
    "screenshot_results": 0
  }
}
~~~

`provider_usage_report_count` advances only when both provider token values are
non-negative integers. Coverage is known only when it equals the consumed model
turn count. `screenshot_results` advances only for a successful result from the
reviewed `screenshot` tool, never for an arbitrary image-bearing result.
Campaign workers separately provide a coarse heartbeat and lease state in the
campaign manifest.

## Status projection

Use a fixed mapping:

| Source state | Display state |
| --- | --- |
| `WAITING_APPROVAL` | Waiting approval |
| `SUCCESS` | Complete |
| `FAILED` | Failed |
| `UNKNOWN_OUTCOME` | Uncertain; re-observe before retry |
| `CANCELLED` | Cancelled |
| Other nonterminal run phase | In progress at last checkpoint; liveness unknown |
| Fresh campaign heartbeat and consistent lease | Running |
| Expired heartbeat or lease | Stale; inspect before reclaim |
| `CHALLENGE` campaign state | Challenge; operator attention |

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
| Attention  2                                      |
| run_cd34  Waiting approval                        |
| run_ef56  Uncertain; re-observe before retry      |
| In progress  1                                    |
| run_ab12  last checkpoint; liveness unknown       |
| History  1                                        |
| run_gh78  Complete                                |
+----------------------------------------------------+
~~~

Do not display task text, document text, titles, screenshots, typed values,
model prose, arbitrary errors, credentials, or account identifiers.

## Multi-session behavior

- Independent run checkpoints are grouped by fixed operator relevance:
  Attention (`WAITING_APPROVAL` / `UNKNOWN_OUTCOME`), In progress (other
  nonterminal checkpoints, without claiming liveness), then History.
- Within each group, sort by strictly validated timezone-aware `updated_at`
  descending and use run ID as a stable tie-breaker.
- Apply one global display cap and allocate it in group order so terminal
  history cannot hide a waiting or uncertain run.
- Group campaign control state only by its validated `campaign_id`; never infer
  campaign membership from a run ID or conversational context.
- Never merge conversational context from different Codex sessions.
- Existing run IDs are immutable; duplicate or path-unsafe IDs fail closed.
- Campaign groups allocate their independent cap to attention first, then active
  work and history; each group sorts newest-first by validated control time.
- Bound scanning to the same maximum used by `agent report`.
- A corrupt record makes that record unavailable; it must not contaminate a
  valid record or produce a partially trusted view model.

## Acceptance checks

1. Opening, refreshing, moving, or changing topmost state does not alter the
   foreground HWND in passive mode.
2. Run and campaign IDs remain separate and correctly regroup under rapid
   atomic file replacement.
3. The reader returns the previous or next complete checkpoint, never a mixed
   record.
4. Unknown versions, symlinks, malformed metrics, and unsafe paths fail closed.
5. Redaction tests prove forbidden fields cannot enter the view model.
6. Legacy unknown token coverage, screenshot count, elapsed time, and
   nonterminal liveness are not displayed as zero or running facts.
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
   the real ctypes backend is `computer_use_agent.progress_window_win32`, whose
   live-desktop non-activation is confirmed by the operator-approved
   `scripts/smoke_progress_window.py` with
   [retained evidence](PROGRESS_WINDOW_EVIDENCE.md).
3. Atomic live checkpoint polling. **Implemented** in
   `computer_use_agent.progress_poller`: `ProgressPoller.poll_once` rebuilds the
   projection and redraws only when the rendered view actually changed, and
   `run()` loops on an injected clock. A scan that fails closed discards the
   last good view rather than leaving stale facts on screen that would read as
   current; a single corrupt record stays isolated as unavailable. Building this
   surfaced a Windows hazard — a reader blocked the checkpoint publish and could
   fail a run — now removed by the `computer_use_agent.atomic_file` contract and
   measured in [checkpoint publish evidence](CHECKPOINT_PUBLISH_EVIDENCE.md).
   The live path is confirmed on-device by the operator-approved
   `scripts/smoke_progress_poller.py`, which drives real checkpoints into the
   real window while publishing concurrently
   ([retained evidence](PROGRESS_POLLER_EVIDENCE.md)).
4. Multi-run grouping. **Implemented** in `computer_use_agent.progress_view`
   and `computer_use_agent.progress_window`: checkpoints require a bounded,
   timezone-aware `updated_at`; `group_progress_views` rejects duplicates and
   inconsistent phase/terminal flags, produces fixed relevance groups, and
   sorts each newest-first with a stable run-ID tie-breaker. Rendering applies
   one 20-run cap in group order, so Attention cannot be displaced by newer
   History. Reducer/window/poller tests cover grouping, regrouping after a live
   phase transition, equal timestamps, corrupt timestamps, duplicate IDs, and
   rapid atomic replacement. The updated live poller smoke moved one of two
   independent runs from In progress to History after a real terminal
   checkpoint while preserving foreground and 400/400 concurrent publishes
   ([retained evidence](PROGRESS_POLLER_EVIDENCE.md)).
5. Campaign progress after the long-running task manifest. **Implemented** in
   `computer_use_agent.campaign`, `campaign_host_status`, `progress_view`, and
   `progress_window`: a bounded stable double-read snapshots validated campaign
   control files without acquiring the global execution lock, refuses a
   concurrently changing or malformed snapshot, and projects only campaign ID,
   fixed status, aggregate item counts, and validated update time. Rendering
   gives campaign attention priority under a separate 10-campaign cap. Tests
   prove the reader does not block 150 consecutive atomic heartbeat publishes,
   isolates one corrupt campaign, follows a live Running-to-Paused transition
   while the writer lock remains held, and excludes campaign kind, policy and
   schema digests, item keys, worker run IDs, and handoff content.
   **Checkpoint telemetry refinement is also implemented:** creation time is
   preserved across updates, provider-usage coverage and successful screenshots
   are counted independently, elapsed time is derived only from validated
   timestamps, and legacy missing fields remain explicitly unavailable.
6. Integrate shared presence and Decision Card state only through pure operator
   view-model contracts; keep execution and approval out of the passive window.
   **The separate primary-display presence and Decision Card surfaces now
   exist. Ordinary `run`/`resume`, bounded `plan run`, and explicit read-only
   recovery progress lifecycle wiring is implemented through an independent
   fail-silent port and background UI thread. Recovery notifications follow
   the existing durable CAS and cannot authorize replay. The three fixed
   MCP-backed campaign execution commands start the same poller without
   inventing a run phase; zero-port control commands remain window-free.
   Broader cross-surface integration remains.**
