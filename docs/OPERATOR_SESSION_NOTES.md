# Operator session notes

> **Status: maintained evidence and planned follow-ups.** This document records
> sanitized findings from interactive desktop sessions. It is not a runtime
> contract and does not make a planned capability available.

## Recording boundary

Use this file for reproducible findings, design decisions, and follow-up work
that should survive the original Codex session. Keep raw runtime material in the
configured user-local Agent `state_dir`; do not commit task text, model prose,
UI text dumps, window titles, screenshots, typed values, credentials, or other
private data.

The machine-readable source of truth for a run remains:

~~~text
state_dir/
  runs/<run_id>/state.json
  traces/<run_id>.jsonl
~~~

See [Agent traces](TRACE.md) for the redaction and validation contract. Entries
below should use an opaque run or session alias when the real identifier is not
needed to reproduce a finding.

## Session index

| Date | Session alias | Surface | Scope | Result |
| --- | --- | --- | --- | --- |
| 2026-07-15 | `boss-chrome-01` | Codex desktop, local MCP, Chrome | Read-only BOSS interested-jobs probe and observation-cost check | Integration works; window reactivation defect reproduced |
| 2026-07-18 | `boss-mcp-post-repair-01` | Agent bounded stdio bridge, project MCP, Chrome | Read-only post-repair BOSS home observation | Activation and bounded UIA observation passed; human-active gate stopped further navigation |
| 2026-07-18 | `synthetic-campaign-device-01` | Fixed campaign CLI, Runner, project MCP | Three-command synthetic `list_windows` campaign | Commit, handoff, and fresh-run exhausted resume passed with zero provider calls |
| 2026-07-19 | `boss-campaign-page-01` | Fixed campaign CLI, Runner, project MCP, Chrome | One-page read-only BOSS identity discovery | Seven stable identities retained; zero provider and side-effect calls |
| 2026-07-23 | `boss-campaign-multipass-01` | Fixed campaign CLI, Runner, project MCP, Chrome | Current-contract two-pass BOSS identity discovery | Twelve stable identities retained across distinct source digests; zero provider and side-effect calls |
| 2026-07-23 | `boss-item-restart-diagnostic-01` | Fixed campaign CLI, Runner, project MCP, Chrome | Three read-only identity commits and stale-owner restart diagnostic | Three commits retained; two integration defects found and fixed; clean post-fix stale recovery; not acceptance evidence |

## 2026-07-23: current-contract BOSS multi-pass discovery

- The first attempt observed a BOSS city-recruitment page, failed closed with
  `BOSS_DISCOVERY_NO_IDENTITIES`, and left both campaign ledgers empty.
- Operator-controlled project MCP navigation used the unique BOSS Chrome
  window, bounded OCR, and one `End` key to select and progress the
  interested-jobs surface outside the fixed campaign command.
- Two fixed `campaign observe-boss-page` runs each dispatched one foreground
  `ui_snapshot` through Runner and the project MCP.
- The passes retained eight and four new identities respectively, with zero
  duplicates and distinct source digests. The final item ledger contains twelve
  stable keys.
- The campaign files and redacted traces contain no full URL, `securityId`,
  source marker, page text, or credential. No provider or side-effect call ran.

See [the retained multi-pass evidence](BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md).

## 2026-07-15: Chrome and BOSS live probe

### Environment and integration

- The project-local `computer_use_local` MCP server was loaded by Codex after a
  restart and exposed the expected observation and action tools.
- A real stdio handshake completed and the server could list Chrome windows,
  inspect interactive controls, navigate within the existing signed-in session,
  and capture screenshots.
- The probe was read-only with respect to recruitment activity. It did not send
  messages, apply to jobs, or modify the interested-job list.

### Sanitized recruitment observations

The BOSS interested-jobs view reported 67 entries. Four visible cards were used
as the sample:

| Company | Role | Location | Compensation | Experience |
| --- | --- | --- | --- | --- |
| Black Lake Technologies | Agent development engineer | Shanghai, Changning | 30-50K, 15 months | Not specified |
| vivo | AI R&D engineer, Agent platform | Hangzhou, Yuhang | 30-60K | 3-5 years |
| Yunlian Jinhui | Agent engineer | Beijing, Xicheng | 30-60K | Not specified |
| MOVA | AI Agent engineer | Suzhou, Wuzhong | 20-40K, 15 months | Not specified |

The Black Lake role emphasizes industrial decision workflows, RAG, planning,
tool use, constrained multi-step decisions, and combining LLMs with rules,
optimization, or scheduling. The vivo role emphasizes an enterprise Agent
platform, multi-Agent and workflow capabilities, vertical applications, and
production backend or model-serving experience. These summaries are a snapshot
of the visible page on the session date, not a durable representation of the
postings.

### Observation-cost findings

| Observation | Measured serialized size | Finding |
| --- | ---: | --- |
| Full current UI snapshot | 5,756 characters, 86 lines | Useful for discovery but repetitive |
| `find("立即沟通")` | 91 characters, 2 lines | About 98% smaller than the full snapshot |
| `find("岗位职责")` | 50 characters, 2 lines, no match | Static job-description text was absent from the interactive UI Automation tree |
| Screenshot PNG result | 1,643,252 base64 characters | Necessary for some page content, but base64 size is not a model-token measurement |

Use `find` as the default observation compressor for known interactive targets.
Do not assume it can replace screenshot, OCR, or document-text extraction for
static page content. Provider-reported input/output token totals in the Agent
trace are the authoritative cost measurements when available.

### Reproduced defect: `activate_window`

After the Codex desktop app regained the foreground, the safe-local foreground
gate correctly denied a Chrome action. Chrome was still present in
`list_windows`, but two attempts to activate the same valid window failed with:

~~~text
ERROR DRIVER_ERROR: could not bring window to foreground
~~~

The current Windows driver attaches the existing foreground thread to the
target window thread before calling `BringWindowToTop` and
`SetForegroundWindow`. The MCP caller thread is not part of that attachment.
This is consistent with a Windows foreground-lock failure; it is a working
hypothesis, not yet a confirmed root cause.

Priority follow-up:

1. Add an isolated Windows activation helper that accounts for the caller,
   foreground, and target input threads, restores every attachment in `finally`,
   and verifies the resulting foreground handle.
2. Preserve the existing human-activity and emergency-stop gates.
3. Add unit tests for attach/detach ordering, already-foreground behavior,
   minimized-window restoration, failed Win32 calls, and cleanup after errors.
4. Add a manual Windows regression that switches from Chrome to Codex and then
   activates the previously observed Chrome handle.

## 2026-07-18: post-repair BOSS home observation

The project-local executable completed a real stdio handshake through the
Agent Host bridge and exposed exactly the reviewed eight tools. In `safe_local`
mode, with Chrome allowlisted and the 2.5-second human-idle threshold retained,
`activate_window` succeeded for the sole returned Chrome window. The server
then used its own UIA address-bar ref to navigate to the signed-in BOSS home
page and retained a bounded observation.

The BOSS snapshot contained 126 lines and 10,760 serialized characters.
`find("BOSS")` reduced it to three interactive matches, while
`find("感兴趣")` and `find("岗位职责")` returned no match on the home page.
The attempted user-menu expansion was rejected as `HUMAN_ACTIVE`; the idle gate
was not bypassed and the interested-jobs view was not opened in this session.
No message, application, saved-job mutation, upload, or screenshot occurred.

The sanitized retained record is [BOSS observation evidence](BOSS_EVIDENCE.md).

## 2026-07-18: on-device synthetic campaign

The fixed three-command CLI prepared the sole reviewed synthetic claim,
dispatched one `list_windows` observation through Runner, persisted the item as
`COMMITTED`, wrote deterministic handoff, and transferred ownership to a fresh
run that returned `NO_ELIGIBLE_ITEMS`. The result retained two successful run
checkpoints and redacted traces with one total tool call, zero failures, zero
retries, zero provider calls, and zero tokens. See
[Synthetic campaign evidence](SYNTHETIC_CAMPAIGN_EVIDENCE.md).

## 2026-07-19: one-page BOSS campaign discovery

The first foreground attempt safely observed the wrong surface and retained no
identity. A second attempt reached the intended signed-in BOSS page and exposed
a real UIA contract mismatch: Chrome used `hyperlink`, and the bounded source
marker was present on same-page company links rather than each job link. No
campaign item was written by either failed run.

After narrowing the parser to the observed role and same-snapshot BOSS source
proof, a fresh fixed campaign dispatched one `ui_snapshot`, retained seven
stable public job keys, and reached `SUCCESS` with zero provider calls, zero
side effects, and zero retries. The repository retains no raw snapshot, title,
role/company content, full URL, query value, screenshot, or credential. See
[BOSS campaign discovery evidence](BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md).

## Planned operator progress window

> **Historical proposal.** The current design owner is
> [Operator progress viewer](PROGRESS_VIEWER.md); keep this section only as the
> live session's original motivation and do not evolve a second UI contract
> here.

The normative design has moved to [Operator progress viewer](PROGRESS_VIEWER.md).
This section remains as the originating session record and must not override
that specification.

### Goal

Show progress without requiring the operator to switch back to Codex, while
remaining visibly separate from the automation and unable to execute or replay
desktop actions.

### MVP design

- A small Windows tool window reads validated, redacted `state.json` checkpoints
  from the configured `state_dir` on a short polling interval.
- It groups records by `run_id`, shows all active or recently completed runs,
  and lets the operator select one. This covers work originating in other Codex
  sessions without merging their private conversational context.
- The selected card shows phase, elapsed time, model/tool call counts,
  input/output token totals when reported, screenshot count, last fixed status
  code, and whether the run is waiting, blocked, complete, or uncertain.
- The window is non-activating and does not steal focus from Chrome or another
  controlled application. Always-on-top is optional and user-controlled.
- The UI never displays raw task text, UI observations, titles, screenshots,
  typed values, model responses, or arbitrary errors. It uses only fields
  allowed by the existing trace redaction contract.
- The viewer has no MCP action tools, provider credentials, replay path, or
  write access to run records. A corrupt or incompatible checkpoint is shown as
  unavailable rather than partially trusted.

The first implementation should reuse atomic checkpoints instead of adding IPC.
An event stream can be considered later only if polling latency becomes a
measured problem.

### Suggested compact layout

~~~text
+ Computer Use --------------------------------+
| boss-chrome-01       EXECUTING        02:14   |
| Step: desktop observation                      |
| Model 6   Tools 9   In 18.4k   Out 2.1k      |
| Screenshots 2        Status: running           |
|------------------------------------------------|
| other-run-02         WAITING_APPROVAL   00:31  |
| other-run-03         SUCCESS            05:08  |
+------------------------------------------------+
~~~

### Acceptance checks

- Opening or updating the viewer never changes the foreground window.
- Two concurrently present run IDs remain separate and cannot overwrite each
  other's displayed state.
- Checkpoint replacement during a read produces either the previous complete
  state or the next complete state, never a mixed display.
- Redaction tests prove that forbidden raw fields cannot reach view-model data.
- Unknown versions, malformed metrics, symlinks, and path-unsafe run IDs fail
  closed consistently with `agent report`.
- `SUCCESS`, `FAILED`, `UNKNOWN_OUTCOME`, and `CANCELLED` are visually distinct;
  uncertain outcomes instruct the operator to re-observe rather than retry.

## Adding findings from another session

Append one sanitized entry to the session index and use this template. If the
source has a runtime `run_id`, keep the detailed machine data in `state_dir` and
record only an opaque alias or the minimum identifier needed for correlation.

~~~markdown
## YYYY-MM-DD: short session title

- Session alias:
- Surface and target application:
- Goal and authorization boundary:
- Reproducible observation:
- Evidence or measurements:
- Decision:
- Follow-up and priority:
- Privacy check: no raw task/UI/screenshot/typed-value content committed
~~~

## Prioritized backlog from these sessions

1. **P1:** implement the read-only, non-activating multi-run progress window on
   top of validated Agent checkpoints.
2. **P1:** add a bounded static-content observation path, such as document text
   extraction or OCR, for content missing from the UI Automation tree.
3. **P1:** implement the bounded read-only terminal-status projection and
   fake-host polling tests without adding a second execution path.
4. **P1:** after bounded static-content observation is available, retain a
   separate BOSS interested-jobs result without bypassing `HUMAN_ACTIVE`.
5. **P1:** implement the observation ladder and measurement fields from
   [Token efficiency](TOKEN_EFFICIENCY.md).
6. **P1:** execute the BOSS, Google Docs, and WeChat staged cases from
   [Application evaluation matrix](APPLICATION_EVALUATION_MATRIX.md), beginning
   with read-only/draft-only tiers.
7. **P2:** execute the dedicated Douyin real-time-media and infinite-feed case
   with a test account after bounded multi-source observation is available;
   begin read-only and keep like, follow, comment, message, and publish actions
   outside the baseline.
8. **P2:** evaluate delta snapshots and configurable snapshot node limits after
   collecting provider-reported token measurements.
