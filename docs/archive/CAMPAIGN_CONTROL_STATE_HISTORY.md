# Archived campaign control-state implementation history

> **Status: historical, non-normative.** This record preserves the incremental
> control-state sequence that previously dominated `EXECUTION_PLAN.md` and
> `LONG_RUNNING_TASKS.md`. Use the active roadmap, capability dashboard, and
> long-running contract for current behavior and next work.

## Why this was archived

The campaign foundation was deliberately built in small, fail-closed changes.
The resulting chronological prose was useful while each boundary was under
review, but it made the active roadmap read like a commit diary and obscured
the present integration gap: no campaign worker, CLI path, provider, MCP, or
application operation is connected.

The complete pre-consolidation prose remains available in Git at commit
`45e177d` in `docs/EXECUTION_PLAN.md` and `docs/LONG_RUNNING_TASKS.md`. The
table below is the compact review index, not a replacement for Git history.

## Preserved chronology

| Commit | Increment |
| --- | --- |
| `d147041` | Campaign manifest, item ledger, atomic persistence, and fixed handoff foundation |
| `3692c04` | Bounded batch lifecycle ledger |
| `af74850` | Bounded item claim leases |
| `8c03735` | Locked stale-lease recovery |
| `64bbd05` | Durable bounded heartbeat record |
| `ec3214b` | Durable campaign pause/resume state |
| `8c08d6a` | Locked stale-heartbeat owner recovery |
| `d0b15be` | Status-aware handoff directives |
| `5453eff` | Handoff validation against current durable state |
| `9b55881` | Read-only resume preflight |
| `c50ff47` | Bounded resume batch planning |
| `4c32c40` | Claimed-item identity and application re-observation preflight |
| `5653a04` | Resume blocking for in-flight observed/extracted items |
| `45a24d8` | Confirmed `OBSERVED` persistence boundary |
| `2838807` | Bounded extraction preflight |
| `aff8ada` | Confirmed `EXTRACTED` persistence boundary |
| `c973919` | Result-verification and commit preflight |
| `4cd8b1d` | Verified `COMMITTED` transition and continued batch progression |
| `d1dd419` | Clean finished-run heartbeat transfer |
| `7d12e73` | Exhausted-campaign completion boundary |
| `e64ee13` | Read-only completed-campaign heartbeat-retirement preflight |

Later commits completed the resumed-item sequence, terminal batch/handoff
projection, repeated run transfer, no-eligible-item classification, completed
manifest transition, and byte-stable completed handoff. Each increment kept
provider, MCP, desktop, action, and CLI ports disconnected.

## Stable outcome of the sequence

The resulting offline control plane supports:

- strict campaign manifests and append-only item/batch ledgers;
- stable item ordinals, bounded leases, and injected-time validation;
- `DISCOVERED -> CLAIMED -> OBSERVED -> EXTRACTED -> COMMITTED` read-only item
  boundaries;
- fixed hard-limit and plan-complete batch termination;
- heartbeat, pause, stale inspection, and reviewed ownership transfer;
- deterministic handoff projection and validation;
- restart/resume control-state progression without free-form item selection;
- exhausted-campaign completion and terminal handoff; and
- idempotent/fail-closed behavior under repetition, drift, stale ownership, or
  incomplete evidence.

This is control-state evidence, not an executable campaign. The next active
gate is one synthetic read-only worker path through the existing Agent boundary.
