# Decision Card approval on-device evidence

> **Status: bounded native approval smoke retained 2026-07-22.** This record
> demonstrates the opt-in, three-choice Win32 Decision Card through the production
> `ApprovalPort` and ordinary Runner boundary. It is not human usability,
> real-provider, real-MCP-child, or application acceptance evidence.

## Exact scope

- Implementation commit: `ee1afab49d0050650a01bed9dffe9878ce8cab58`
- Command: `.venv\Scripts\python.exe scripts\smoke_decision_card.py`
- Host path: production `AgentRunner`, `DecisionCardApprovalPort`,
  `DecisionCardWindow`, and `Win32DecisionCardWindowApi`, with deterministic
  fake provider and desktop MCP ports.
- Desktop scope: one operator-approved interactive Windows primary display.
- Selection scope: UI Automation verified the three custom choices and evidence
  affordance, the probe programmatically selected the exact-effect command link
  on the first card, and the second card's native five-second timeout expired.
- Safety scope: the approved action was synthetic and reached only the fake
  desktop port; no external application or business object was changed.

## Retained result

~~~text
RESULT: PASS (card foreground 0x700578; authority yielded; three bounded options and evidence affordance rendered; approved choice used ordinary dispatch and verification; five-second timeout denied with zero side-effect dispatch; prior foreground restored)
~~~

The first run released the passive Agent presence exactly once before the
focus-taking card, correlated the exact-effect choice to the pending approval,
and sent the synthetic action through the Runner's sole existing desktop
dispatch site followed by its ordinary verification observation. UI Automation
observed exact-effect approval, human takeover, denial, and the collapsed
`Show bounded evidence` control on the native Task Dialog. The second run closed
on the native timeout, returned `APPROVAL_DENIED`, and left the fake desktop call
sequence at its initial observation only. The card restored the prior foreground
window after both paths.

## Offline controls retained with this gate

- approval requests bind run state, policy, task, registry, object, and evidence
  digests; the Runner recomputes every digest after the human boundary;
- close, timeout, surface error, malformed or unknown selection, expiry,
  missing binding, and binding drift deny without side-effect dispatch;
- cancellation propagates instead of being converted into approval;
- the native card offers exact-effect approval, human takeover, and denial; it
  has no recommendation and keeps the console approval path as the default;
- handoff produces a distinct `decision_card_handoff` denial and the integration
  test proves it reaches no side-effect dispatch;
- expanded evidence contains only fixed classifications, unknown-fact enums,
  expiry, and SHA-256 evidence/Host/card digests;
- the window controller and native backend have no desktop execution method or
  alternate MCP path.

The exact implementation gate passed Ruff, mypy across 97 source files, and
the full offline suite with `1215 passed, 5 skipped` before the retained probe.

## Supported claim and remaining boundary

This supports a bounded **Desktop verified** claim for the opt-in Windows
Decision Card approval boundary. The selection was automated and the provider
and desktop ports were fake, so it does not establish human comprehension,
accessibility, real process-to-process MCP behavior, a human-selected handoff,
resumable defer/re-observe semantics, or application acceptance. Windows-only
three-choice presentation, one primary display, and one exact action remain the
implemented boundary.

The next operator gate is Host-owned persisted semantics for re-observe or
defer, without widening approval or dispatch authority, followed by an isolated
human-operated cross-application UX scenario.

Related: [Decision Card model evidence](DECISION_CARD_MODEL_EVIDENCE.md),
[Operator experience](OPERATOR_EXPERIENCE.md),
[Approved actions](APPROVALS.md),
[Capability status](CAPABILITY_STATUS.md), and
[Execution plan](EXECUTION_PLAN.md).
