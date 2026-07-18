# On-device synthetic campaign evidence

> **Status: fixed three-command on-device path passed 2026-07-18.** This
> evidence covers only the exact one-item `synthetic:list_windows` campaign and
> its durable fresh-run resume boundary. It is not a general campaign worker,
> provider result, application workflow, or notification bridge.

## Reviewed boundary

- Source commit before this documentation update: `bb0f483`.
- Campaign: `campaign_evidence_20260718`.
- Initial run: `run_evidence_20260718_1`.
- Replacement run: `run_evidence_20260718_2`.
- Policy: `readonly-v1`, zero allowed side effects, and zero input-token use.
- Desktop surface: the project `computer-use-mcp.exe` through the sole Runner
  dispatch boundary.
- Provider: forbidden by the fixed synthetic runtime; no provider call opened.

The local evidence scope is
`%LOCALAPPDATA%/computer-use-agent/evidence-20260718`. It contains the manifest,
item and batch ledgers, heartbeat, deterministic handoff, two run checkpoints,
and two redacted traces.

## Three-command result

1. `prepare-synthetic` created the sole reviewed manifest, batch, claim, and
   `synthetic:list_windows` item in `CLAIMED` state.
2. `run-claimed-synthetic` dispatched exactly one `list_windows` observation,
   reduced it to a non-sensitive count of six, verified content digest
   `7806bb6883012ae3365feef5155c9f30e20714673e86288894d8669f833d6a83`,
   persisted `COMMITTED`, closed with `ITEM_LIMIT`, and wrote handoff.
3. `resume-synthetic` transferred ownership to the replacement run and
   reconstructed `NO_ELIGIBLE_ITEMS` with next item ordinal 2.

The first trace contains four redacted events: task metadata, one empty-argument
tool call, one successful correlated result, and one observation. The tool
result retained only text length 277 and latency 189 ms, not window titles. Its
terminal checkpoint reports one tool call, zero failures, zero retries, zero
model calls, zero tokens, and 833 ms run duration. The replacement run made no
tool, provider, or desktop call and reached `SUCCESS` in 27 ms.

The aggregate local report contains two terminal successful runs, one total
tool call, zero failures, zero model calls, zero tokens, and a 1.0 success rate.

## Promotion boundary

This result fills the desktop-evidence cell only for the fixed synthetic
campaign seam. It does not connect item selection, provider turns, side
effects, BOSS items, campaign completion, or automatic heartbeat retirement.
The next runtime gate is the bounded read-only terminal-status projection and
fake-host polling contract already specified in
[Long-running tasks](LONG_RUNNING_TASKS.md).
