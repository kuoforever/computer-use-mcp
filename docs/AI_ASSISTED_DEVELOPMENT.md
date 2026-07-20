# AI-assisted development

> **Status: a statement of practice, not a policy proposal.** This describes how
> this repository is actually built.

Much of the code and documentation here was drafted with coding agents (Codex
and Claude Code). This page states what that means and where responsibility
sits, because "who actually decided this?" is a fair question to ask of a
repository with dense design documents and fast-moving pull requests.

## The working rule

**Model output is an untrusted proposal.**

That is the same stance the runtime takes toward a model's tool calls, and it is
applied to the development process for the same reason: a plausible-looking
suggestion is not evidence that it is correct, safe, or even that the thing it
describes exists.

## Split of responsibility

| Agents are used for | The author is responsible for |
| --- | --- |
| Drafting implementations against a stated contract | The contract, the threat model, and what the system is allowed to do |
| Proposing test cases and edge cases | Which invariants matter, and which must be verified on a real desktop rather than mocked |
| Refactoring, docstrings, translation, formatting | Every capability claim, and the evidence level assigned to it |
| Searching the codebase and summarizing existing behavior | Running real provider, desktop, and application verification |
| Drafting documentation and ADR structure | The decisions in the ADRs, and the rejected options being real |
| Reviewing diffs for the author to consider | Merging, and the behavior of anything merged |

The right-hand column is not delegated. In particular, **no evidence level in
[Capability status](CAPABILITY_STATUS.md) is ever promoted because tests
passed** — promotion requires a run that actually happened, on the surface being
claimed.

## Guardrails that exist because of how the repo is built

Several conventions in this repository are a direct response to the failure
modes of agent-assisted work:

- **Layered evidence.** Design, implementation, offline verification, provider
  verification, desktop verification, and application verification are separate
  columns. A detailed contract is not implementation; a passing unit test is not
  a desktop result. This exists because the most common agent failure is
  describing a planned capability in the present tense.
- **Dated evidence is immutable.** Records keep the numbers their own run
  observed. They are never "updated to the latest" — that would destroy the
  time semantics that make them evidence at all.
- **Current-state documents are checked in CI** against the reviewed tool
  registry, rather than maintained by hand, because hand-synchronized status
  text drifts on nearly every commit.
- **Fail-closed defaults.** Unknown outcomes stop; unreviewed environment keys
  are rejected; a stale ref fails rather than degrading. Generated code tends
  toward helpful fallbacks, and helpful fallbacks are how silent wrong actions
  happen.
- **Small, single-purpose pull requests**, each stating what it does *not*
  claim.

## Known limits of this arrangement

- Review attention is finite. A large generated diff receives less scrutiny per
  line than a small hand-written one, and this repository has produced large
  diffs.
- Offline tests can be written to pass by construction. Where a mock could
  fake a result that only a real desktop can establish, the claim belongs in a
  dated evidence record instead — but nothing structurally prevents an
  over-mocked test from looking like coverage.
- Documentation is the easiest thing to over-produce and the hardest to keep
  true. The consistency check covers tool counts and running totals; it does not
  verify prose.

## What is not claimed

- That the project was "built by AI." Design decisions, boundaries, evidence
  standards, verification, and merges are the author's.
- That every line was hand-written. It was not.
- That agent-assisted code is held to a lower standard. It is held to the same
  gates as anything else: lint, offline suite, documentation consistency, and
  explicit human verification for anything touching a real provider, a real
  desktop, or a real application.

## For reviewers and interviewers

The useful questions are not "did a model write this?" but:

- Which invariant does this enforce, and where is it tested?
- What evidence level does this claim, and what run supports it?
- What was deliberately *not* built, and why?

The [ADRs](adr/) and [postmortems](postmortems/) exist to answer that third
question, which is the one generated code never answers on its own.
