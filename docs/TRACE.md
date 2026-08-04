# Agent run checkpoints and redacted traces

> **Status: implemented inspection and metrics baseline.** Live non-dry Agent runs write an
> atomic safe checkpoint and append-only redacted JSONL events. Records support
> inspection and conservative recovery decisions. Explicit resume is limited
> to an initial checkpoint before any provider/tool call; actions are never replayed.

## Storage layout

Records remain under the configured user-local `[agent].state_dir`:

~~~text
state_dir/
  runs/<run_id>/state.json
  traces/<run_id>.jsonl
~~~

The run ID is restricted to a 1-128 character path-safe identifier. Existing
records are never overwritten. Checkpoints are written to a sibling temporary
file, flushed, and atomically replaced. Trace lines are appended, flushed, and
bounded to 1 MiB each and 16 MiB per run; checkpoints are bounded to 64 KiB.
Readers reject symbolic-link redirection of the state/run/trace path, malformed
JSON, version drift, sequence drift, run-ID mismatch, truncation, and an event
count that disagrees with the checkpoint.

## Run phases

The implemented transition validator recognizes:

`CREATED`, `OBSERVING`, `PLANNING`, `WAITING_APPROVAL`, `EXECUTING`,
`VERIFYING`, `SUCCESS`, `FAILED`, `UNKNOWN_OUTCOME`, and `CANCELLED`.

The Runner uses `CREATED -> OBSERVING -> PLANNING`, moves to `EXECUTING` for
authorized observations, and returns to `PLANNING` after recording the result.
Approved side effects pass through `WAITING_APPROVAL`, then `EXECUTING`, then
`VERIFYING` before the next planning or terminal decision. Terminal phases
cannot transition. Illegal jumps fail closed.

`SUCCESS` is written only after the desktop bridge closes cleanly. Fixed
failure codes are checkpointed for reviewed Runner failures. Cancellation is
recorded as `CANCELLED`; a result-carrying post-dispatch MCP cancellation is an
uncertain MCP result and remains `UNKNOWN_OUTCOME` even while task cancellation
is re-propagated.

## Redaction contract

Neither checkpoint nor JSONL trace stores:

- task text or final model prose;
- provider response IDs or raw provider errors;
- observation/UI text, window titles, or screenshots;
- typed values, passwords, API keys, or arbitrary tool error text.

The checkpoint stores lengths, policy/recovery versions, phase, observation
epochs, event count, budgets, terminal code, creation/update times, and bounded
aggregate metrics. A successful run stores final-text length only. Older v1
checkpoints without the backward-compatible creation and coverage fields remain
readable.

Trace events store reviewed semantic metadata. Tool results retain status,
dispatch certainty, fixed code, text length, and image count, not their
content. Tool calls use `SafeArgumentSummary`; `type.text` is represented only
by presence and length plus whether a ref was supplied.

## Metrics

Each model-turn trace event records integer provider latency and normalized
input/output token counts. Each dispatched tool-result event records integer
tool latency. The checkpoint aggregates model/tool call counts, token totals,
provider/tool latency, non-success tool results, image-result count, successful
`screenshot` result count, complete provider-usage report count, and terminal
wall-clock run duration. Token totals still treat missing provider usage as
zero, but `provider_usage_report_count` makes coverage explicit: the viewer
calls token coverage known only when every consumed model turn supplied both
input and output usage. `screenshot_results` counts the reviewed screenshot tool
rather than every image-bearing result. `retry_count` is currently zero because
the host never automatically retries provider calls or desktop actions.

Metrics contain no task, model response, observation, image, typed value,
provider identifier, or raw error content. Cost is deliberately not estimated:
the host has no reviewed, versioned provider pricing input.

## Inspection and recovery

Inspect one record without starting a provider or MCP child:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe trace <run_id> --config agent.toml
~~~

The command emits the validated checkpoint, aggregate metrics, and events as JSON. It does not
repair, mutate, resume, or delete the record.

Classify recovery without starting external ports or mutating the record:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe recovery <run_id> --config agent.toml
~~~

The output contains only run ID, phase, fixed action/reason, resume eligibility,
and task length. An initial `resume_initial` classification remains conditional
on supplying the original task to the separate `resume` command.

When opt-in continuation persistence is enabled, execute one reviewed read-only
recovery boundary by default with an explicit confirmation flag:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe recover <run_id> `
  --config agent.toml --task "<original task>" --execute-read-only
~~~

To chain a bounded sequence, add `--max-steps N` where `N` is 1-4. All steps
hold the same run lock, and every external call still receives its own durable
intent and completion commit.

The command can dispatch one pending observation from a completed provider turn,
send one new provider continuation after a completed observation, or issue one
synthetic `ui_snapshot` after a completed side effect and then stop. It acquires
the run lock, persists a sequence-checked dispatch intent before the call, and
persists completion afterward. A call failure leaves the intent uncertain and
non-replayable. The default remains one external call; the reviewed hard cap is four.
A fully persisted provider response with no tool calls requires no external
step: the command verifies its final ledger/provider correlation, atomically
advances the safe checkpoint to `SUCCESS`, records final-text length only,
deletes `continuation.json`, and returns the already persisted final text.
Hidden function calls, sequence drift, or mismatched provider state fail closed.
A completed provider turn that requests any action is never sent to policy,
approval, or MCP during recovery. After strict call/provider correlation, the
command advances the checkpoint to `FAILED` with
`RECOVERED_ACTION_REQUESTED`, deletes the continuation, reports the blocked
call count, and exits nonzero. Multiple calls grant no additional authority.

Aggregate all local checkpoints without opening JSONL traces:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe report --config agent.toml
~~~

The report includes phase counts, terminal success rate, fixed failure-code
counts, metric coverage, totals, and average provider/tool/run latency. Legacy
v1 checkpoints without metrics remain in phase counts but do not contribute
invented metric values. The scan is bounded to 10,000 path-safe run directories
and fails closed on invalid directories, symlinks, corrupt checkpoints, unknown
metric fields, or malformed values. It never reads trace JSONL content.

Only `CREATED` or initial `OBSERVING` records with one task-length event, zero
consumed budgets, no observation epoch, and ready recovery state have
`resume_allowed=true`. Resume requires the original task; its length and policy
version must match. The command may reclaim only a well-formed OS-unlocked
crash lease, then restarts discovery without replaying provider or tool work:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe resume <run_id> `
  --config agent.toml --task "<original task>"
~~~

Any later phase fails closed as `RUN_NOT_RESUMABLE`. Close a non-terminal crash
record explicitly with:

~~~powershell
.\.venv\Scripts\guarded-desktop-agent.exe cancel <run_id> --config agent.toml
~~~

Recovery remains deliberately conservative:

- `SUCCESS`: no recovery action;
- `UNKNOWN_OUTCOME`: a human must re-observe before starting a new run;
- later incomplete, failed, or cancelled: inspect the trace, then start a new run.

The same rules are implemented as a fixed recovery classification used by the
resume attach path: `resume_initial/INITIAL_CHECKPOINT`,
`start_new_run/PROVIDER_OR_TOOL_PROGRESS`, `human_reobserve/UNKNOWN_OUTCOME`,
or `none/RUN_SUCCEEDED`. Policy/task/budget drift at an otherwise initial phase
classifies as `start_new_run/CHECKPOINT_MISMATCH`.

The host never automatically replays a tool call. Dispatch intent without a
completion, pending side effects, unknown outcomes, and configuration or
identity drift remain non-executable.
