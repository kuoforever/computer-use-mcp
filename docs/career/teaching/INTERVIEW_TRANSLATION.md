# Interview translation

> **Status: shared teaching protocol v1 with Guarded Desktop Agent profile
> revision 2.**

Every completed step may record a learning or interview angle, including a
valid failure, invalid attempt, or blocked gate. Turn that material into a
submission-ready interview answer only after it passes the
[resume-promotion gate](EVIDENCE_DISCIPLINE.md#resume-promotion-gate). A feature
list is not an interview answer; the answer must connect a real problem,
personal ownership, engineering choices, verification, and limits.

## Six-part engineering answer mapped to STAR

| Engineering part | STAR role | Question answered |
| --- | --- | --- |
| Problem | Situation | What failure or user need existed? |
| Constraint | Situation | What safety, authority, platform, or evidence boundary applied? |
| Objective + personal ownership | Task | What exact outcome and slice were you responsible for? |
| Decision | Action | What design was chosen and what alternative was rejected? |
| Implementation | Action | Which contracts, states, components, and failure paths changed? |
| Verification + limit | Result | What passed, what failed, and what remains unverified? |

STAR is the delivery shape; the six parts prevent it from losing technical
depth or evidence boundaries.

## Answer lengths

### 30-second version

1. one-sentence problem and constraint;
2. one sentence on your exact action and key mechanism;
3. one verified result plus one honest limit.

### Two-minute version

1. describe the failure window or user need;
2. name your personal slice;
3. explain the chosen invariant and rejected alternative;
4. walk one consequential state or data path;
5. give deterministic and, if available, real-surface evidence; and
6. close with the evidence ceiling and next honest gate.

## Ownership-safe language

Use verbs at the level you can prove:

| Confirmed contribution | Suitable verbs |
| --- | --- |
| Owned the contract and trade-off | designed, defined, led |
| Implemented a bounded module | implemented, built, integrated |
| Added tests or evidence | verified, evaluated, instrumented, reproduced |
| Diagnosed and fixed an observed defect | diagnosed, debugged, repaired |
| Contributed within a larger slice | contributed to, implemented the ... portion |

Do not use a stronger verb because the repository contains the result. Mention
coding-agent assistance directly when asked: model output was a proposal, while
the human owned scope, evidence, review, and merge decisions actually performed.

## Deep-dive preparation per resume item

Each item should prepare:

- one real failure or debugging story;
- one rejected alternative and trade-off;
- one state transition, data flow, or authority boundary that can be drawn;
- one deterministic test and one real-surface record when available;
- three questions that go from architecture to failure windows to evidence;
  and
- an explicit `do not claim` boundary.

Useful interviewer questions include:

- Why was this invariant necessary?
- What happens immediately before and after the uncertain boundary?
- Why was fail-closed behavior preferable to a fallback?
- How did you distinguish mock coverage from real-system evidence?
- What result falsified the first diagnosis?
- Which simpler alternative was rejected, and why?
- What would have to pass before you widened the claim?

The agent may inspect, implement, test, explain, and propose wording. The user
owns product intent, personal-contribution claims, operator observations,
credentials/accounts, and final job-application choices.
