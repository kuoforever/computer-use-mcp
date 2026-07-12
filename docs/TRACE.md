# Agent run checkpoints and redacted traces

> **Status: implemented inspection and metrics baseline.** Live non-dry Agent runs write an
> atomic safe checkpoint and append-only redacted JSONL events. Records support
> inspection and conservative recovery decisions; automatic resume and action
> replay are not implemented.

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
bounded to 1 MiB; checkpoints are bounded to 64 KiB. Readers reject malformed
JSON, version drift, sequence drift, run-ID mismatch, truncation, and an event
count that disagrees with the checkpoint.

## Run phases

The implemented transition validator recognizes:

`CREATED`, `OBSERVING`, `PLANNING`, `WAITING_APPROVAL`, `EXECUTING`,
`VERIFYING`, `SUCCESS`, `FAILED`, `UNKNOWN_OUTCOME`, and `CANCELLED`.

The current read-only Runner uses `CREATED -> OBSERVING -> PLANNING`, moves to
`EXECUTING` for each authorized observation, records the resulting observation,
and returns to `PLANNING`. Terminal phases cannot transition. Illegal jumps
fail closed. `WAITING_APPROVAL` and `VERIFYING` are reserved for the future
approved-action workflow.

`SUCCESS` is written only after the desktop bridge closes cleanly. Fixed
failure codes are checkpointed for reviewed Runner failures. Cancellation is
recorded as `CANCELLED`; an uncertain MCP result is `UNKNOWN_OUTCOME`.

## Redaction contract

Neither checkpoint nor JSONL trace stores:

- task text or final model prose;
- provider response IDs or raw provider errors;
- observation/UI text, window titles, or screenshots;
- typed values, passwords, API keys, or arbitrary tool error text.

The checkpoint stores lengths, policy/recovery versions, phase, observation
epochs, event count, budgets, terminal code, update time, and bounded aggregate
metrics. A successful run stores final-text length only.

Trace events store reviewed semantic metadata. Tool results retain status,
dispatch certainty, fixed code, text length, and image count, not their
content. Tool calls use `SafeArgumentSummary`; `type.text` is represented only
by presence and length plus whether a ref was supplied.

## Metrics

Each model-turn trace event records integer provider latency and normalized
input/output token counts. Each dispatched tool-result event records integer
tool latency. The checkpoint aggregates model/tool call counts, token totals,
provider/tool latency, non-success tool results, screenshot-result count, and
terminal wall-clock run duration. Missing provider token usage is counted as
zero. `retry_count` is currently zero because the host never automatically
retries provider calls or desktop actions.

Metrics contain no task, model response, observation, image, typed value,
provider identifier, or raw error content. Cost is deliberately not estimated:
the host has no reviewed, versioned provider pricing input.

## Inspection and recovery

Inspect one record without starting a provider or MCP child:

~~~powershell
.\.venv\Scripts\computer-use-agent.exe trace <run_id> --config agent.toml
~~~

The command emits the validated checkpoint, aggregate metrics, and events as JSON. It does not
repair, mutate, resume, or delete the record.

All current records have `resume_allowed=false` because the sanitized record
does not contain raw task/provider conversation state and correctness cannot be
reconstructed from it. Recovery is deliberately conservative:

- `SUCCESS`: no recovery action;
- `UNKNOWN_OUTCOME`: a human must re-observe before starting a new run;
- incomplete, failed, or cancelled: inspect the trace, then start a new run.

The host never automatically replays a tool call. Automated resume requires a
future reviewed persistence format, explicit transition/replay invariants, and
additional E2 recovery cases.
