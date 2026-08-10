# GDA-02 — Crash recovery without duplicate side effects

> **Status: current candidate resume item; retained synthetic evidence only.**

- **JD tags:** backend reliability, WAL, checkpoint, lease, CAS, idempotency,
  recovery, fault injection.
- **Candidate bullet (ZH):** 构建基于 checkpoint、lease、CAS 与 intent/receipt
  evidence 的保守恢复机制；在 30 次、每次 100 个 synthetic item 的故障注入
  基准中保持 0 duplicate side effects，并把无回执窗口停在 `UNCERTAIN` 而非
  自动重试。
- **Candidate bullet (EN):** Built conservative checkpoint/lease/CAS recovery
  with intent and receipt evidence; a retained 30-run, 100-item synthetic fault
  benchmark recorded zero duplicate side effects and parked uncertain dispatches.
- **Evidence level:** retained synthetic reliability evidence only.
- **Sources:** [reliability benchmark](../../benchmark/README.md),
  [continuation contract](../../CONTINUATION.md), and
  [long-running tasks](../../LONG_RUNNING_TASKS.md).
- **Do not claim:** production traffic, real external transactions, provider or
  application acceptance, or hardware-independent timing.
- **Interview expansion:** compare crash-before-dispatch, crash-after-intent,
  crash-after-effect, and crash-after-commit; explain why stopping can be the
  correct result.
