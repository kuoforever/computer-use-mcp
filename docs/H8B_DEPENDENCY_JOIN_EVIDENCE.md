# H8B dependency and join evidence

> **Status: implemented, offline verified, and merged through PR #318 on 2026-08-09.**

## Scope

H8B adds tree contract v3 while retaining the envelope-v1 tree store and exact
v1/v2 readability. The new data is limited to canonical immutable all-of
dependency identifiers and a local `join` node. A v3 `parallel` node may hold
general child subtrees, but each tick still returns at most one inert leaf
boundary and an active external leaf blocks every second external boundary.

Dependency data contains no task text, tool name, arguments, fact value,
observation content, approval, provider, Runner, MCP, desktop port, script,
callable, retry, compensation, any-of rule, or dispatch method.

## Deterministic evidence

The focused H8B matrix proves:

- strict v3 shape, canonical payload and frozen v2/v3 digests;
- rejection of missing endpoints, self/duplicate/non-canonical edges,
  control-node dependents, fan-in over 16, more than 128 edges, graph depth over
  24, and cycles involving dependency, structural, ordered-sibling, or
  reduction edges;
- local join reduction across pending, in-progress, completed, cancelled,
  blocked, and failed inputs using the existing deterministic precedence;
- stable node-ID choice among ready leaves, dependency gating, no join boundary,
  and exactly one external boundary with no second boundary during an active
  external leaf;
- strict v1-v3 store decoding, cross-version field rejection, semantic
  rejection after digest recomputation, immutable-structure CAS, and restart
  readability; and
- unchanged H8A condition-only evaluation when a v3 parallel node directly
  contains H5 conditions.

The complete repository gate and GitHub matrix are recorded in
`PROJECT_STATUS.md` and the implementation pull request after publication.

## Claim boundary

This is source/offline evidence only. H8B does not execute dependencies or
joins through the Runtime, Runner, MCP, provider, Windows desktop, or an
external application. It adds no parallel external dispatch, policy,
grounding, approval, side-effect, retry, replay, choice, fallback, learning,
E4, or release authority. H8C and L5 remain separately gated.
