# Resume evidence index

> **Status: current derived job-application view, reviewed against repository
> owners on 2026-08-10.** These items are not capability owners, a final resume,
> or proof of personal authorship.

## Item index

| ID | Highlight | Strongest relevant scope |
| --- | --- | --- |
| `GDA-01` | [Safety-governed Agent Runtime](GDA-01-safety-runtime.md) | Offline plus selected exact live paths |
| `GDA-02` | [Crash recovery without duplicate side effects](GDA-02-crash-recovery.md) | Synthetic reliability benchmark |
| `GDA-03` | [Provider-neutral regional routing](GDA-03-provider-routing.md) | Eight profiles offline; narrower live scope |
| `GDA-04` | [Installed Windows product integration](GDA-04-windows-product.md) | Exact Notepad and Chrome/Word evidence |
| `GDA-05` | [Native operator UX and accessibility](GDA-05-operator-ux.md) | Bounded native and human evidence |
| `GDA-06` | [Hierarchical control](GDA-06-hierarchical-control.md) | H1-H8 offline evidence |
| `GDA-07` | [Evidence-driven engineering](GDA-07-evidence-engineering.md) | Repository-wide process |

## Selection workflow

1. Extract five to eight exact `must-have` and `preferred` JD keywords.
2. Select at most three or four non-overlapping items.
3. Prefer the strongest relevant evidence layer, not the largest feature list.
4. Confirm personal ownership and rewrite the candidate bullet in your own words.
5. Open every linked source before submission and retain all stated limits.

A one-page graduate resume should normally use one project summary and three or
four bullets. This index is intentionally longer so different JDs can select
different evidence.

## Evidence vocabulary

| Level | What it supports | What it does not support |
| --- | --- | --- |
| Implemented | Code and contract exist | Correctness or live behavior |
| Offline verified | Deterministic tests/gates passed | Provider, desktop, or application behavior |
| Provider verified | A named provider/model request passed | Desktop or application behavior |
| Desktop verified | A bounded native Windows path passed | General application coverage |
| Application verified | One named end-to-end application scope passed | Universal GUI or production deployment |
| Release verified | Exact candidate release gates passed | A wider environment than the release record |

## JD selection map

| Target role | Start with | Add when the JD emphasizes |
| --- | --- | --- |
| AI Agent / LLM application | GDA-01, 03, 04 | GDA-05 for HITL UX; GDA-06 for planning |
| Backend / reliability | GDA-02, 01, 07 | GDA-06 for concurrency/state machines |
| Windows / client platform | GDA-04, 05, 01 | GDA-02 for recovery |
| AI platform / provider integration | GDA-03, 01, 07 | GDA-02 for continuation/recovery |
| Safety / evaluation / quality | GDA-01, 07, 02 | GDA-05 for human evidence |
