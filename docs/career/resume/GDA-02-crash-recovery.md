# GDA-02 — Conservative recovery and synthetic duplicate suppression

> **Status: current candidate item; retained benchmark is synthetic.**
> Personal ownership: `TBC`. Submission-ready only after `My scope` is filled.

## Quick select

| Field | Guidance |
| --- | --- |
| Primary roles | Backend reliability, distributed state, workflow engines, Agent infrastructure |
| Position | Lead |
| Evidence ceiling | Separate offline Agent continuation contracts plus a synthetic campaign/fake-sink benchmark |
| Use when | The JD mentions WAL, checkpointing, leases, CAS, idempotency, recovery, saga, or fault injection |
| Skip when | The role expects proven production transactions or distributed-service throughput |
| Exact JD keywords | `write-ahead log`, `checkpoint`, `lease`, `CAS`, `idempotency`, `reconciliation`, `fault injection` |

## Resume copy

**Short ZH:** 实现 conservative Agent WAL recovery；另在独立 fake-sink
benchmark 的 30×100 synthetic-item、6 类故障运行中记录 0 duplicate，缺失
回执停为 `UNCERTAIN` 而非重放。

**Evidence-rich ZH:** 将 Agent continuation 建模为 `prepared -> dispatch_intent ->
completed` 的 sequence/digest-bound WAL，并以 checkpoint、锁与 CAS 进行保守
恢复；在独立的 campaign fault benchmark 中覆盖 6 类故障窗口、30 次共
3,000 个 synthetic items processed，记录 0 duplicate side effects，未知结果
不重试。

**Short EN:** Built conservative Agent WAL recovery and separately retained a
30-run, 3,000-item synthetic campaign benchmark with zero duplicate side
effects across six crash windows.

**Evidence-rich EN:** Implemented sequence- and digest-bound Agent continuation WAL
recovery, while a separate lease-backed synthetic campaign benchmark recorded
zero duplicate side effects and parked dispatch-intent gaps as `UNCERTAIN`
instead of replaying them.

**My scope to confirm:** Distinguish the Agent continuation/WAL work you owned
from the campaign benchmark, fault harness, analysis, and documentation you ran.

## Fact card

| Dimension | Evidence-backed fact |
| --- | --- |
| Problem | A crash can occur before dispatch, after intent, after the external effect, or after durable bookkeeping |
| Constraint | External side effects cannot be made truly atomic with local state, and missing receipts do not prove failure |
| Decision | Reconcile only correlated known completion; re-observe or stop on uncertainty; never promise exactly-once external effects |
| Agent mechanism | Private atomic continuation with `prepared`, `dispatch_intent`, and `completed` boundaries plus sequence/digest checks and bounded recovery |
| Benchmark mechanism | Campaign item ledger, claim lease, fake durable side-effect sink, and six injected crash scenarios |
| Verified result | 30 runs, 100 items per run, 0 duplicate side effects; `crash_after_dispatch_intent` records a median of 1 `UNCERTAIN` item per run |

## Proof map

| Claim | Owner/evidence |
| --- | --- |
| Exact benchmark environment, scenarios, and metrics | [Reliability benchmark](../../benchmark/README.md) |
| Agent continuation and crash classification | [Continuation contract](../../CONTINUATION.md) |
| Campaign lease, idempotency, and `UNCERTAIN` rules | [Long-running tasks](../../LONG_RUNNING_TASKS.md#idempotency-and-uncertain-actions) |

## Interview card

- **S:** duplicate work is dangerous when a crash hides whether an effect happened.
- **T:** state the continuation, campaign, benchmark, or analysis portion you owned.
- **A:** classify crash-before-dispatch, after-intent, after-effect receipt, and
  after-commit separately; reconcile evidence instead of retrying by default.
- **R:** 30 × 100 synthetic items over six scenarios, zero duplicates, with
  intentional `UNCERTAIN` parking when outcome evidence is missing.
- **Trade-off:** availability is sacrificed for certainty; a parked item can be
  the correct outcome.
- **Debug story:** explain why an exact receipt permits bookkeeping repair while
  an intent without receipt cannot prove either success or failure.

Deep-dive questions:

1. Why is “at least once plus idempotency” still insufficient for an unobservable GUI effect?
2. Which state transitions require CAS, and which benchmark fact does not prove CAS?
3. How would you test crash recovery without selecting only the best timing run?

## Claim limits

Do not merge the two evidence sources into one claim: the synthetic benchmark
does not prove the full Agent checkpoint/WAL/CAS stack. Do not claim production
traffic, real external transactions, exactly-once delivery, provider/application
acceptance, or hardware-independent latency.
