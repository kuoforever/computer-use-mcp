# Reliability demo: crash a campaign, resume it, prove no duplicate

> **Status: deterministic and offline.** This demo touches no desktop, calls no
> provider, and costs no tokens. It exercises durability semantics, not GUI
> automation. Real desktop evidence lives in the separate
> [BOSS](../BOSS_EVIDENCE.md) and [E4](../E4_EVIDENCE.md) records.

## What it demonstrates

A multi-item campaign is killed at a named boundary. A second process, with
nothing in memory from the first, reads durable state and decides — per item —
whether it may continue, must reconcile, or must stop and ask for a human.

The claim is not "it recovered." It is that recovery does exactly one of three
things, and that which one is chosen follows from evidence rather than a guess.

## Run it

```bash
# clean run
python scripts/demo_reliability_campaign.py --state-dir out/demo-clean --items 5

# crash after an item is durably committed, then resume
python scripts/demo_reliability_campaign.py --state-dir out/demo-f1 --items 5 \
    --fault-point after_item_commit --fault-ordinal 2

# crash between the durable intent and the side-effect result
python scripts/demo_reliability_campaign.py --state-dir out/demo-f2 --items 5 \
    --fault-point after_dispatch_intent --fault-ordinal 3
```

Each invocation prints one sanitized JSON report and exits non-zero if any
duplicate side effect was attempted. `--state-dir` must be empty; the demo never
reuses a directory, so a run is always reproducible from scratch.

## Fault points

Faults are named and repeatable. A random kill would prove nothing: it could
land anywhere, and a single lucky success would be indistinguishable from a
correct system. Each point below sits on one side of a specific durability
boundary.

| Fault point | Killed after | Recovery must |
| --- | --- | --- |
| `after_item_claim` | The lease exists, no work done | Release the lease and re-claim |
| `after_dispatch_intent` | The sink intent is durable, the result is not | Park the item as `UNCERTAIN`. **Never retry.** |
| `after_side_effect_completion` | The sink result is durable, `COMMITTED` is not | Reconcile from the exact receipt. Do not dispatch again. |
| `after_item_commit` | `COMMITTED` is durable | Skip the item entirely |
| `before_final_projection` | Every item is durable, the report is not | Rebuild the report; nothing was lost |

Configure them programmatically, or through `CUA_DEMO_FAULT_POINT` and
`CUA_DEMO_FAULT_ORDINAL`. Absent configuration means no fault, so a production
path cannot inherit one by accident.

## The three recovery classes

Recovery reads the durable ledger and the sink, and every in-flight item lands in
exactly one class:

1. **Known completed.** The sink holds an accepted receipt for the item's
   idempotency key. The effect provably happened; only local bookkeeping is
   behind. It is caught up from that receipt and nothing is dispatched.
2. **Known not dispatched.** The sink has no record at all. The item is released
   for a normal retry.
3. **Unknown.** The sink holds an intent with no result. The effect may or may
   not have happened. The item becomes `UNCERTAIN`, which is terminal in the
   ledger, and a human decides. Attention is scoped to that item; the rest of
   the campaign still completes.

The third class is the point of the demo. A system that retries here is not
"more resilient" — it is one that will double-send, double-delete, or double-pay
the first time a network hiccup coincides with a crash.

## Why the fake sink is two-phase

A sink we can always query cannot express uncertainty: after a crash we would
simply ask it what happened, and case 3 would never occur. Real GUI side effects
are not queryable that way.

So the sink appends a `pending` record before performing the effect and an
`accepted` record after, each fsynced. A crash between the two is exactly the
unknown case. The sink also *rejects and records* a repeated idempotency key
rather than silently absorbing it — a sink that deduplicated for us would hide
the very bug this demo exists to expose.

## Privacy

The report contains only hashes and counters: a campaign digest, item counts,
and side-effect counters. No page text, URL, query token, account identifier, or
recruiter-visible content is written anywhere, in this demo or its state
directory. Synthetic item keys are generated (`demo-item-0001`), not scraped.

## Honest limits

- This is a **synthetic reliability demo**, not application acceptance. It says
  nothing about whether any real task succeeds.
- The side effect is a fake sink. It proves the campaign's dispatch and recovery
  semantics, not that a real GUI action is idempotent.
- `0 tokens` here means this path has no provider, not that an Agent run is free.
- Item counts are bounded by `MAX_DEMO_ITEMS`. The larger forced-restart
  benchmark is separate work and is not claimed here.

## Where the code lives

| Piece | Location |
| --- | --- |
| Fault points, sink, driver, report | [`src/computer_use_agent/demo_campaign.py`](../../src/computer_use_agent/demo_campaign.py) |
| Runnable demo | [`scripts/demo_reliability_campaign.py`](../../scripts/demo_reliability_campaign.py) |
| Fault matrix tests | [`tests/agent/test_demo_campaign.py`](../../tests/agent/test_demo_campaign.py) |

Item lifecycle, lease ownership, and the committed prefix all come from the
existing `CampaignStore` and `BatchCoordinator`. The demo adds no second state
machine and no second desktop execution path.
