# Reliability benchmark evidence

> **Status: retained synthetic result, 2026-07-20.** This is a durability
> experiment over synthetic items and a fake side-effect sink. It is **not**
> application acceptance, not provider evidence, and not desktop evidence. It
> says nothing about any real application.

## Reviewed environment

| Field | Value |
| --- | --- |
| Commit | `f028119a11d2` (plus the reviewed benchmark and demo repairs under test) |
| Runtime | Windows 11, Python 3.13.7 |
| Items per run | 100 synthetic |
| Repetitions | 5 per scenario |
| Total runs | 30 |
| Provider | none; 0 tokens on this path |

Machine-readable result: [`benchmark-report.json`](benchmark-report.json).

Reproduce with:

~~~powershell
.\.venv\Scripts\python.exe scripts\run_reliability_benchmark.py `
  --root out\benchmark --items 100 --repetitions 5 `
  --json out\benchmark-report.json --markdown out\benchmark-report.md
~~~


100 synthetic items per run, 5 repetitions per scenario, 30 runs total.

**Result: PASS** — 0 duplicate side effects across all runs.

Every number below is a median with p95 in parentheses, computed across all repetitions. No run is selected for being the best one. An item parked for human attention is a correct outcome, not a failure.

| Scenario | Committed | Uncertain | Duplicates | Wall ms | Recovery ms |
| --- | --- | --- | --- | --- | --- |
| `clean` | 100 | 0 | 0 | 9810 (10020) | 0 (0) |
| `crash_after_claim` | 100 | 0 | 0 | 11245 (13605) | 10089 (11960) |
| `crash_after_dispatch_intent` | 99 | 1 | 0 | 12595 (12817) | 9945 (10336) |
| `crash_after_side_effect_completion` | 100 | 0 | 0 | 13622 (14461) | 7436 (8004) |
| `crash_after_commit` | 100 | 0 | 0 | 12370 (12969) | 3977 (4298) |
| `crash_before_projection` | 100 | 0 | 0 | 12266 (12655) | 42 (55) |

## What each scenario asserts

- **`clean`** — every item commits; no fault is injected
- **`crash_after_claim`** — the lease exists but no work was done; the item is re-claimed
- **`crash_after_dispatch_intent`** — outcome unknown; the item is parked UNCERTAIN and never replayed
- **`crash_after_side_effect_completion`** — an exact receipt exists; reconcile bookkeeping without dispatching again
- **`crash_after_commit`** — the item is already COMMITTED; recovery skips it entirely
- **`crash_before_projection`** — every item is durable; the report is a projection and is rebuilt

## Boundaries

- Synthetic items and a fake durable side-effect sink. This is a reliability experiment, not application acceptance, and it says nothing about any real application.
- 0 tokens means this path has no provider, not that an Agent run is free.
- Timings come from one machine and one Python runtime. Treat them as a regression baseline, not a hardware claim.
