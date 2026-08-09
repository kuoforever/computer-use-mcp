# H8C safe choice evidence

> **Status: implemented and offline verified on 2026-08-09; publication active.**

## Scope

H8C adds contract v4 fixed-order choice events and keeps the tree-store envelope
at version 1. Candidate branch gates are typed H5 conditions evaluated over one
immutable snapshot/context with at most four local workers. Selection is always
resolved in Host order and persisted before a branch can expose an external
boundary.

Persisted events contain only identifiers, enum values, sequence numbers, and
SHA-256 digests. They contain no task text, condition value, observation text,
image bytes, tool arguments, approval, provider, Runner, MCP, desktop port,
script, callable, retry, replay, or dispatch method.

## Deterministic evidence

The focused matrix proves:

- all true/false/unavailable arrangements, first-true priority when several
  gates are true, actual worker overlap, and deterministic Host-order results;
- earlier unavailable blocks with the exact store bytes unchanged, while all
  false forms one known terminal choice failure;
- the first selection is sequence/tree/snapshot/context/digest bound, survives
  restart, and cannot be replaced after ordinary context drift;
- fresh pre-boundary false and exact fresh false verification after a completed
  zero-side-effect reviewed observation can evaluate only later branches;
- all remaining false terminates, while missing/stale verification, observation
  mismatch, or any branch side-effect budget fails closed;
- approval or permission denial, authority/grounding/policy/budget conflict,
  cancellation, dispatched error, missing verification, unknown outcome, and
  side-effect failure are never fallback inputs;
- evaluator exceptions and CAS conflicts preserve the exact prior store bytes;
  and
- v1-v4 payload/digest/decode compatibility, cross-version fields, malformed
  choice shapes, re-signed selection tampering, and restart decoding are strict.

The complete repository gate passed `2441 passed, 8 skipped`, Ruff, mypy over
161 source files, docs consistency, and `git diff --check`. Publication evidence
is recorded in `PROJECT_STATUS.md` and the implementation pull request.

## Claim boundary

This is source/offline evidence only. No choice or fallback was executed through
a provider, Runner, MCP child, Windows desktop, or external application. H8C
adds no approval, policy, grounding, side-effect, retry, replay, learning, E4,
or release authority. L5 remains separately consented and inactive.
