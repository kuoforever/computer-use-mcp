# Live checkpoint polling on-device evidence

> **Status: bounded on-device live-polling, run grouping, and campaign progress smoke
> retained 2026-07-22.** This record demonstrates that the operator progress
> poller (delivery steps 3-5 of the [progress viewer](PROGRESS_VIEWER.md)) follows
> real checkpoint and campaign control state on a live Windows desktop,
> regroups runs and a campaign after real transitions, stays passive, and does
> not block either atomic publisher. It is not presence-indicator,
> Decision-Card, application-acceptance, or release evidence.

## Reviewed boundary

- Source commit for the latest campaign-progress run:
  `d5c7b86f5a1333be55bdfa3628c42fb67f126d7f`.
- Preceding independent-run grouping source commit:
  `b4974d0b14a0c63d7b59ec309783750441956c15`.
- Interpreter: CPython 3.13.7 from the checked-out virtual environment.
- Surface: `scripts/smoke_progress_poller.py`, driving the real
  `ProgressPoller` -> `PassiveProgressWindow` -> `Win32ProgressWindowApi` chain
  over real checkpoints published by a real `RunRecorder`.
- Scope: one operator-approved interactive desktop session and one temporary
  state directory holding two runs and one synthetic campaign. Read-only with
  respect to every other window.
- Excluded: provider calls, MCP calls, desktop automation, real agent runs, and
  any write or click that changes another window's state.

## What was exercised

Unlike the [step-2 smoke](PROGRESS_WINDOW_EVIDENCE.md), which drew synthetic view
models, this probe closes the loop on real state:

1. Two runs (`run_live`, `run_idle`) are created through `RunRecorder`.
2. The poller opens the real window and draws the first real projection.
3. A writer thread republishes `run_idle`'s checkpoint 400 times while the
   poller concurrently scans and reads the same directory — the exact
   read/publish race a live viewer creates.
4. The initial projection must place both nonterminal runs under
   `In progress  2`.
5. `run_live` is then transitioned `PLANNING` -> `SUCCESS`; the next real poll
   must redraw as `In progress  1` plus `History  1`, moving only the terminal
   run while keeping both IDs separate.
6. Foreground HWND and `GetLastInputInfo` are compared across the whole session;
   the run is discarded as inconclusive if local input occurred.
7. A synthetic campaign starts with a fresh heartbeat under `Active campaigns`.
   The writer retains the global execution lock while publishing 400 heartbeat
   replacements alongside the checkpoint replacements. The campaign is then
   paused and must move to `Campaign attention` on the next poll.

## Result

Three consecutive runs on 2026-07-22 each reported:

~~~text
RESULT: PASS (foreground unchanged at 0x30040; 400/400 publishes succeeded
under a live poller; live SUCCESS transition reached the window; two runs kept
separate; no task text)
~~~

So, on a real desktop: the foreground stayed `0x00030040` throughout; every one
of the 400 concurrent publishes succeeded; a real phase transition reached the
drawn surface; the two runs stayed separate; and the run's task text never
entered the view.

After delivery step 4 was implemented, the updated smoke was run on the
preceding independent-run grouping commit above and reported:

~~~text
RESULT: PASS (foreground unchanged at 0xb0598; 400/400 publishes succeeded
under a live poller; live SUCCESS transition regrouped one of two independent
runs into History; no task text)
~~~

The updated result retains every original assertion and additionally proves the
real drawn projection moved one run from `In progress` to `History` after its
atomic checkpoint transition. The other independent run stayed in its original
group, and the foreground remained `0x000b0598`.

After delivery step 5 was implemented, the smoke was run on the exact campaign
source commit above and reported:

~~~text
RESULT: PASS (foreground unchanged at 0xb0598; 400/400 checkpoint+campaign
publishes succeeded; live SUCCESS transition regrouped one of two independent
runs into History; live campaign transition regrouped Active into Attention;
no private content)
~~~

This latest result retains the two-run check and proves the passive campaign
reader can observe through a held execution lock without blocking 400 paired
atomic publishes. The campaign changed groups only after its durable status
transition. Campaign kind, policy/schema digests, worker run ID, and private
task text did not enter the drawn lines.

## Control: the probe has teeth

A passing assertion is only meaningful if it can fail. The same workload was
re-run with the publish path reverted to the pre-fix `os.replace` (patched in a
scratch harness; the repository was not modified):

| Publish path | Publishes failed | Smoke result |
| --- | --- | --- |
| `publish_atomically` (current) | 0 / 400 | PASS |
| plain `os.replace` (pre-fix) | 23 / 400 | FAIL (exit 1) |

Every pre-fix failure is a hard `CHECKPOINT_WRITE_FAILED`, which fails the
agent's run. The on-device rate (5.75%) is lower than the 61.9% measured offline
in [`atomic_file`](../src/computer_use_agent/atomic_file.py) because this probe
polls at a realistic interval with window message pumping between scans rather
than in a pure tight loop. The hazard and the fix both reproduce on-device; only
the collision rate differs with polling pressure.

## Supported claim and next gate

This closes the on-device gates for live checkpoint polling, bounded
independent-run regrouping, and bounded campaign progress, and supports the
Operator UI **Desktop verified** cell in [Capability status](CAPABILITY_STATUS.md)
for those bounded slices. It does not demonstrate the Attention-priority cap on
a live desktop, grouping beyond two runs, campaign heartbeat display, the
presence indicator, Decision Cards, DPI or reduced-motion behaviour, or any
long-duration soak.

Remaining after this gate: the presence indicator and fake-only Decision Card
view models stay sequenced behind the passive surfaces per the
[roadmap](EXECUTION_PLAN.md). This smoke is bounded and is not a long soak.

Related: [Capability status](CAPABILITY_STATUS.md),
[Operator progress viewer](PROGRESS_VIEWER.md),
[Passive window evidence](PROGRESS_WINDOW_EVIDENCE.md).
