# Continual learning and verified experience evolution

> **Status: L0-L3 implemented and offline verified.** The current
> runtime also implements explicitly confirmed local memory. It does not automatically extract memories,
> generate or promote workflows, route from a cross-run strategy policy, or update
> model weights. This document defines the complete-product direction and the
> gates required before any of those claims are valid.

## Goal

Repeated work should make the Agent measurably better at the same class of task
without turning untrusted history into authority. Improvement means a higher
verified completion rate or lower total cost per verified outcome while
preserving safety, privacy, object identity, and human approval boundaries.

The intended loop is:

~~~text
bounded execution episode
  -> outcome, correction, cost, and evidence record
  -> candidate fact, procedure, or strategy
  -> isolated replay and held-out evaluation
  -> reviewed promotion
  -> context-aware strategy selection
  -> monitoring, decay, rollback, or retirement
~~~

This is not permission to learn CAPTCHA bypasses, evade anti-automation
controls, weaken approvals, retain secrets, or experiment with production side
effects.

## Four-layer model

| Layer | Meaning | Current project boundary | Complete-product direction |
| --- | --- | --- | --- |
| 1. Factual memory | Stable preferences, application constraints, and verified facts | Explicit, user-confirmed `preference` and `verified_procedure` records with scope, provenance, expiry, and deletion | Suggest bounded candidate memories from repeated evidence; require confirmation or a separately reviewed promotion policy before use |
| 2. Procedural memory | A reusable, versioned way to perform a task | A procedure can be stored as text, but there is no executable Skill package or automatic extraction | Compile successful trajectories into candidate workflows with preconditions, invariants, recovery branches, tests, and rollback metadata; promote only after replay evaluation |
| 3. Strategy learning | Choose among valid procedures using measured context, success, cost, and risk | L3 compares equivalent reviewed procedure evidence offline and emits a visible, non-executing shadow recommendation; no runtime selector consumes it | Later allow bounded contextual-bandit-style routing only for equivalent, low-risk strategies |
| 4. Model learning | Change model parameters from accumulated episodes | No local or project-specific weight updates | Deliberately deferred offline research; any training export requires a separate consent, privacy, redaction, evaluation, and rollback boundary |

The near-term differentiator is Layers 2 and 3: a verified
experience-to-workflow pipeline plus cost-aware strategy selection. It should
not be marketed as model training or full reinforcement learning.

## Public-product comparison

This comparison is a time-stamped architecture reference based on the publicly
documented product surfaces on 2026-07-17. It is not a permanent competitive
claim.

### Codex

Codex documents several adjacent mechanisms:

- `AGENTS.md` provides durable project instructions;
- local Memories can preserve useful context learned from eligible prior tasks;
- Skills package reusable workflows, scripts, references, and assets;
- hooks can capture analytics or produce persistent memory; and
- Record & Replay can turn a demonstrated computer-use workflow into a Skill.

Together these cover factual and procedural memory well. They also provide
inputs for strategy selection, but the public surface does not describe a
project-local reward loop that compares trajectories, promotes strategies from
held-out results, and continuously updates routing weights.

Official references: [Codex customization](https://learn.chatgpt.com/docs/customization/overview),
[Memories](https://learn.chatgpt.com/docs/customization/memories),
[Skills](https://learn.chatgpt.com/docs/build-skills), and
[Record & Replay](https://learn.chatgpt.com/docs/extend/record-and-replay).

### Claude Code

Claude Code documents a similar set of mechanisms:

- `CLAUDE.md` provides explicit persistent project guidance;
- Auto Memory records project-specific commands, architecture facts,
  debugging findings, style preferences, and workflow habits;
- Skills package reusable workflows and can load when the task matches;
- hooks apply deterministic or model-judged lifecycle behavior; and
- subagents can preload Skills and be selected by task description.

These mechanisms also cover factual and procedural memory and can influence
runtime choices. The public surface does not describe a closed, project-local
policy optimizer driven by verified success, token cost, takeover cost, and
risk.

Official references: [Claude Code memory](https://code.claude.com/docs/en/memory),
[features](https://code.claude.com/docs/en/features-overview),
[hooks](https://code.claude.com/docs/en/hooks-guide), and
[subagents](https://code.claude.com/docs/en/sub-agents).

For both products, provider use of opted-in data to improve a later general
model is separate from a user's Agent learning a project-specific policy or
updating weights online. See the current [OpenAI data-use policy](https://help.openai.com/en/articles/5722486-api-data-usage-policies)
and [Claude Code data-use policy](https://code.claude.com/docs/en/data-usage).

## Episode evidence

A learning episode must be derived from retained Host facts rather than model
claims. Its control record should include:

- task class, application and version, fixture or stable object identity, and
  relevant environment features;
- procedure and strategy version, provider/model identity, tool registry, and
  policy version;
- terminal result such as `VERIFIED_SUCCESS`, `VERIFIED_FAILURE`, `CHALLENGED`,
  `CONFLICTED`, `UNCERTAIN`, `HUMAN_COMPLETED`, or `CANCELLED`;
- exact verification evidence and whether any external effect was committed;
- provider tokens, observation volume, model/tool/search calls, retries,
  latency, recovery work, and human takeover time;
- approvals, Decision Card choice, corrections, E-stop, policy denial, and
  authority scope; and
- redaction, retention class, and missing-metric coverage.

`UNCERTAIN`, challenged, policy-denied, or human-completed work is never
silently relabeled as Agent success. Missing cost data is unknown, not zero.
Raw screenshots, typed values, credentials, messages, hidden reasoning, and
arbitrary page text do not enter the learning control plane.

## Implemented L0 boundary

`src/computer_use_agent/episode_outcome.py` builds one in-memory, read-only,
versioned normalized episode from the already validated redacted Full Cycle run
record. It may optionally associate one exact latest campaign item while the
caller holds the existing `RunLock`; item keys and content digests are excluded.

The fixed run-scoped cost vector always contains every reviewed dimension:
model/tool/side-effect/search/OCR calls, provider tokens, observation and result
volume, image/screenshot counts, provider/tool/run latency, retries, recovery,
policy decisions, tool failures, human takeover time/corrections, and E-stop
activations. Each dimension carries `value`, `observed`, and
`complete | partial | missing` coverage. Unknown provider usage, ambiguous
latency, unrecorded duration, and current human/E-stop metrics therefore remain
`null`; they never become zero. Campaign batch counters are not mixed into a
run vector or attributed to one item.

Run labels come only from terminal durable phases. Exact campaign item facts
may narrow a successful classification to `CHALLENGED` or
`VERIFIED_FAILURE`; incompatible run/item facts become `CONFLICTED`, and
`UNCERTAIN` is never relabeled as success. `HUMAN_COMPLETED` is not emitted
because no current durable source proves it. Metrics reconcile against both the
trace events and checkpoint budgets before an episode is returned.

L0 writes no store or export and has no candidate generation, memory injection,
strategy scoring/routing, provider, Runner, MCP, desktop, approval, retry,
replay, promotion, or training port. Its output repeats the Full Cycle privacy
declarations and is restricted to offline evaluation.

## Implemented L1 boundary

`src/computer_use_agent/learning_quarantine.py` adds a separate private SQLite
quarantine and a deliberately narrow extractor:

- one candidate must correlate the same `VERIFIED_SUCCESS` L0 episode, run,
  verified observation epoch, H5 snapshot, and current H5 context;
- ordinary H5 inspection must still find the fact fresh under the exact run,
  epoch, MCP generation, window identity, clock, and maximum-age pins;
- only known boolean and integer values are eligible. Text, identifiers,
  unknown facts, stale facts, arbitrary page content, model prose, raw tool
  results, screenshots, UI references, window titles, typed text, and obvious
  secret-bearing identifiers are rejected before a database is created;
- the record retains only typed value, logical fact ID, scope, exact source
  digests, reviewed extraction method/tool, epoch/generation, optional window
  identity digest, timestamps, and an explicit no-authority/no-injection
  capability declaration;
- candidate IDs are deterministic over the source episode, fact digest, and
  extractor version. Duplicate or previously deleted source facts cannot be
  silently re-created; and
- the store is permission-restricted, versioned, bounded to 1,000 candidate
  histories and 64 events per candidate with the final slot reserved for
  deletion, and uses transactional record-plus-event writes.
  Reads revalidate the strict record, index columns, digests, contiguous event
  chain, revision chain, and current-record binding.

The operator may list, explicitly confirm, edit, expire, or delete a candidate
through `learning candidates`. Every mutation requires the exact revision;
editing a confirmed value returns it to `suggested`. Expiry makes it inactive,
and deletion removes candidate content while retaining a digest-only audit
tombstone. These controls never write `memory.sqlite3`, and even a `confirmed`
candidate remains quarantine-only: no provider context builder, policy,
strategy selector, promotion path, Runner, MCP, desktop, or execution path can
read it.

L1 evidence is deterministic and offline. It proves fresh-source correlation,
content rejection before persistence, no memory injection, exact CAS lifecycle,
transaction rollback, tamper detection, natural and explicit expiry, and
content deletion. It is not application, live, promotion, strategy-selection,
training, E4, or release evidence.

## Implemented L2 boundary

`src/computer_use_agent/verified_procedures.py` adds a versioned, deliberately
non-executable procedure contract plus pure isolated replay and lifecycle
reducers:

- a definition binds exact task/application/version, current reviewed tool
  registry, policy digest, generator version, source episode digests, sorted
  boolean/integer preconditions, and at most 32 forward-only logical steps;
- each step retains only a logical operation ID and digest of reviewed tool
  metadata. It contains no arguments, task text, model prose, tool result,
  screenshot, ref, coordinates, window/object identity, approval, recipient,
  payload, or secret;
- action steps keep the registry's side-effect/approval metadata, require fresh
  observation, stop on failure, and can succeed only into a verification
  observation. Only a verified boolean/integer postcondition can end in
  `verified_success`; observation/verification failures may use bounded
  forward-only recovery branches;
- strict versioned fixtures contain only logical facts, operation outcomes,
  dispatch certainty, approval/freshness booleans, verified typed values, and a
  visible integer cost vector. Source and held-out episode digests cannot
  overlap, and fixture order/digests are deterministic;
- replay is a pure in-memory reducer. Missing/drifted fixtures fail incomplete,
  uncertain action outcome stops without replay, and a simulated dispatch
  without approval or fresh observation is counted as both a safety escape and
  authority regression; and
- activation evaluation requires at least two ordered held-out fixtures, exact
  suite equality with the baseline, complete verified success, zero safety
  escapes, zero authority regressions, and either better verified outcomes or
  Pareto-lower visible costs.

The explicit lifecycle is `CANDIDATE -> EVALUATING -> SHADOW -> ACTIVE ->
DEPRECATED -> RETIRED`, with pre-activation `REJECTED` and exact reviewed
`ROLLED_BACK` paths. Every transition uses a revision, monotonic timestamp, and
digest-linked audit event. `SHADOW`, `ACTIVE`, and rollback require explicit
review; activation recomputes the held-out gate and rollback must match the
definition's exact baseline pin. Candidate lifetime is capped at 365 days.

These labels remain data only. No Runner, MCP, provider, desktop, policy,
approval, explicit-memory, L1-quarantine, strategy selector, persistence, or
runtime procedure loader imports this module. L2 therefore proves an isolated
evaluation and rollback contract, not automatic extraction, runtime promotion,
application success, live learning, training, E4, or release readiness.

## Implemented L3 boundary

`src/computer_use_agent/shadow_strategies.py` adds a pure comparison layer over
reviewed L2 evidence:

- one strict versioned policy exposes a non-negative integer weight for every
  L2 replay-cost dimension, its candidate bound, fixed hard gates, active-tie
  behavior, canonical digest, and `runtime_selection=false`;
- every input contains a complete digest-linked L2 lifecycle plus one current
  frozen evaluation. Exactly one procedure must be data-only `ACTIVE`; every
  alternative must be data-only `SHADOW`, explicitly reviewed, unexpired at
  the supplied comparison time, and bound to its exact definition;
- an equivalence digest requires the same task/application/version, reviewed
  registry, Host policy, typed preconditions, ordered side-effect tool and
  approval/fresh-observation profile, and terminal verified postconditions.
  Observation methods may differ, but authority or verification scope may not;
- all procedures must use the exact same ordered held-out suite. Incomplete or
  unverified results, safety escapes, authority regressions, suite drift,
  duplicate procedures, or zero/multiple active baselines fail before scoring;
- the visible reward vector retains fixture count, verified successes,
  incomplete results, safety escapes, authority regressions, and all nine L2
  costs. Output also retains every weight, per-dimension weighted contribution,
  total penalty, L2 evidence digest, and exact procedure pin; and
- candidates are sorted canonically. Only a strictly lower weighted penalty
  recommends one shadow procedure; equal or worse cost deterministically keeps
  the active baseline. Reversing input order reproduces the same digest.

The recommendation is private content-free evaluation data, not a routing
decision. No Runner, MCP, provider, desktop, policy, approval, memory,
L1-quarantine, persistence, CLI, procedure promotion, online exploration,
training, application, live, E4, or release path imports or consumes L3.

## Candidate extraction and promotion

Model-generated candidates are untrusted proposals. They cannot change policy,
approve an action, widen a scope, establish object identity, or become active
merely because they came from a successful trace.

A procedural candidate should declare:

- task and application scope;
- stable preconditions and identity requirements;
- bounded observation and action steps;
- expected postconditions and verification method;
- recovery branches and explicit stop conditions;
- required approvals and non-transferable authority;
- known application/provider/version compatibility;
- source episode digests and candidate generator version; and
- expiry, owner, rollback target, and retirement conditions.

Promotion requires versioned fixtures, isolated replay, held-out cases, zero
safety escapes, no authority regression, and a reviewed improvement over the
active baseline. One successful trajectory is evidence for a candidate, not a
promotion decision. High-risk procedures always require human review.

Use explicit lifecycle states:

~~~text
CANDIDATE -> EVALUATING -> SHADOW -> ACTIVE -> DEPRECATED -> RETIRED
                  |          |         |
                  +----------+---------+-> REJECTED or ROLLED_BACK
~~~

Every transition is auditable and reversible. A changed application version,
policy, tool schema, authority model, or repeated outcome regression can expire
an active artifact automatically; it cannot auto-relax the relevant gate.

## Cost-aware strategy selection

Strategy selection compares only procedures that already satisfy the same
safety and authority requirements. Hard gates are lexicographic: a scalar
reward must never compensate for an unauthorized action, uncertain duplicate,
or missing verification.

Within an equivalent safe set, record a reward vector such as:

~~~text
verified outcome
token and observation cost
wall-clock latency
retry and recovery cost
human takeover cost
reversibility and residual risk
~~~

A weighted score may be used for reporting, but the underlying vector and
weights must remain visible. L3 now performs that offline comparison and shows
shadow recommendations without changing execution. Later bounded routing may
use context such as application version, observation availability, task shape,
and prior fixture results.

Online exploration is forbidden for external communication, financial effects,
identity or tenant changes, destructive actions, authentication challenges, and
unknown side-effect recovery. Those paths use a reviewed deterministic strategy
or human decision.

## Token optimization

The objective is cost per verified outcome, not shortest prompt or fewest model
calls. A candidate that saves input tokens but causes extra screenshots,
retries, takeovers, or failures is not an improvement.

Learning should be able to recommend:

- the cheapest sufficient observation source for a known decision;
- when to reuse a verified scoped procedure instead of rediscovering it;
- the smallest relevant memory and workflow package;
- when repeated local attempts cost more than bounded read-only research;
- when a provider-context rotation or item-local context is cheaper; and
- when to stop and request a Decision Card rather than consume an open-ended
  retry budget.

All recommendations remain subject to the existing request-byte, token-window,
cumulative-input, retry, time, approval, and action budgets.

## Safety and privacy invariants

1. Memory, procedures, and strategy scores are data, never authority.
2. Learning cannot bypass authentication, CAPTCHA, MFA, rate limits, explicit
   site blocks, tenant boundaries, elevation, or secure desktop.
3. Human corrections are evidence about outcome or preference, not blanket
   permission for future actions.
4. A procedure never carries an old UI reference, window identity, approval,
   recipient binding, payload digest, or object version into a new run.
5. Every state-changing execution re-observes and passes ordinary Host policy,
   grounding, approval, and post-action verification.
6. Production traces are not training data by default. Export, retention, and
   provider disclosure require separate explicit policy.
7. Candidate generation and evaluation have bounded token, time, storage, and
   search budgets and cannot run arbitrary learned code.
8. Operators can inspect, disable, delete, expire, pin, demote, and roll back
   every learned artifact.

## Demo and acceptance evidence

The [Universal GUI demo](UNIVERSAL_GUI_DEMO.md) should eventually contain a
learning segment backed by multiple pre-recorded training episodes and separate
held-out tasks. A valid demonstration shows:

1. repeated execution evidence producing a bounded candidate;
2. a rejected or corrected candidate, proving that extraction is not automatic
   authority;
3. isolated replay and held-out evaluation;
4. reviewed promotion to `SHADOW` and then `ACTIVE`;
5. a later matching task selecting the promoted procedure with provenance;
6. an improvement in verified completion or total cost per verified outcome;
7. drift causing expiry, fallback, or rollback; and
8. unchanged approval, challenge, and uncertain-side-effect behavior.

Replaying the same episode used to generate the candidate is not held-out
evidence. One edited showcase run cannot establish a learning improvement.

## Delivery sequence

| Phase | Deliverable | Exit gate |
| --- | --- | --- |
| L0. Instrumentation | **Implemented/offline verified:** normalized redacted episode outcome and fixed explicit-coverage cost vector derived only from existing trace/campaign evidence | Passed: missing/partial metrics remain explicit, costs reconcile with trace/checkpoint budgets, and outcome conflicts fail closed without live or learning authority |
| L1. Suggested facts | **Implemented/offline verified:** fresh boolean/integer H5 facts correlated with one successful L0 episode enter an isolated private quarantine with exact revisioned lifecycle controls | Passed: no automatic injection; text, identifiers, secrets, raw content, stale/unknown evidence, and ineligible episodes are rejected; operator can list, confirm, edit, expire, or delete without creating explicit memory |
| L2. Verified procedures | **Implemented/offline verified:** content-free versioned workflow data, frozen typed fixtures, pure replay/evaluation, reviewed digest-linked lifecycle, and exact rollback pins | Passed: at least two disjoint held-out fixtures, full verified success, exact baseline suite, zero safety escapes/authority regressions, and verified-outcome or Pareto-cost improvement before data-only `ACTIVE` |
| L3. Shadow strategy policy | **Implemented/offline verified:** exact-equivalence comparison of one reviewed data-only `ACTIVE` baseline and reviewed data-only `SHADOW` candidates with a complete visible reward vector, weights, contributions, and deterministic recommendation | Passed: frozen evidence reproduces independent of input order; suite/authority/verification drift, expiry, hard-outcome failure, safety escape, authority regression, duplicate/multiple baselines, forged score, and forged recommendation fail closed; output has no runtime-selection port |
| L4. Bounded adaptive routing | Context-aware selection among already approved, equivalent low-risk procedures | Canary limits, drift detection, rollback, and no regression in approval or authority gates |
| L5. Offline model research | Separately consented, redacted dataset export and isolated fine-tuning experiment | Independent privacy, security, evaluation, deployment, and rollback approval; outside the default product claim |

Layers and phases are intentionally independent. The project can deliver useful
continual improvement through verified memories, workflows, and strategy routing
without ever performing Layer 4 model-weight learning.
