# Decision Card model offline evidence

> **Status: fake-only model gate retained 2026-07-22.** This record covers pure
> Decision Card compilation and deterministic choice validation. It does not
> cover a graphical window, focus/yield behavior, `ApprovalPort` integration,
> desktop dispatch, provider quality, or application acceptance.

## Exact scope

- Implementation commit: `6d399b3ba3d7494b567aa2c247ce37e4963bb67f`
- Production module: `src/computer_use_agent/decision_cards.py`
- Dedicated tests: `tests/agent/test_decision_cards.py`
- Test command:
  `\.venv\Scripts\pytest.exe -q tests\agent\test_decision_cards.py`
- Full gate: Ruff clean, mypy clean across 80 source modules, and
  `1200 passed, 5 skipped`.

## Retained controls

The 22 dedicated tests establish that:

- each card has exactly two or three unique options and at least one explicit
  deny, defer, or human-takeover exit;
- card inputs accept only fixed Host enums, safe identifiers, SHA-256 digests,
  timezone-aware bounded expiry, and bounded evidence/unknown-fact lists;
- titles, effects, benefits, costs, risks, reversibility, authority scope, and
  fallback are fixed compiler mappings rather than model or desktop prose;
- time/token estimates are explicitly unknown, configured ranges, or measured
  ranges; confidence is unknown or labeled uncalibrated, so numeric precision
  cannot appear without provenance;
- compilation is deterministic, and a recommended option never becomes a
  selection by itself;
- decision ID, card digest, option ID, expiry, and every state, policy, task,
  registry, object, and evidence digest are rechecked before accepting a choice;
- missing input, malformed identity, expiry, and any binding drift return fixed
  non-authoritative failure states with no selected option;
- deny, defer, and human takeover are distinct tested results, with only human
  takeover marking desktop authority for release;
- choosing the exact-effect option returns only
  `requires_separate_approval=true`; it does not create an approval decision;
- the module contains no `ApprovalPort`, `ToolCall`, `request_approval`, or
  `call_tool` boundary.

## Supported claim and next gate

This supports an **Offline verified / fake-only** claim for bounded Decision
Card data, trade-off provenance, deterministic compilation, and fail-closed
selection validation. The card remains advisory data without execution or
approval authority.

The next gate is a focus-taking local Decision Card adapter that first yields
Agent desktop authority, defaults to deny/defer on close, timeout, interruption,
or malformed response, and returns any exact-effect choice through the existing
`ApprovalPort`. It must not add a second MCP dispatch path.

Related: [Operator experience](OPERATOR_EXPERIENCE.md),
[Approved actions](APPROVALS.md), [Capability status](CAPABILITY_STATUS.md), and
[Execution plan](EXECUTION_PLAN.md).
