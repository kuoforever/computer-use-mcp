# Continual learning and verified experience evolution

> **Status: planned architecture.** The current runtime implements only
> explicitly confirmed local memory. It does not automatically extract memories,
> generate or promote workflows, optimize a cross-run strategy policy, or update
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
| 3. Strategy learning | Choose among valid procedures using measured context, success, cost, and risk | The model can replan inside one run; traces and metrics exist, but no cross-run policy learns which strategy works best | Begin with offline scoring and shadow recommendations, then allow bounded contextual-bandit-style routing only for equivalent, low-risk strategies |
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
weights must remain visible. Initial releases should score policies offline and
show shadow recommendations without changing execution. Later bounded routing
may use context such as application version, observation availability, task
shape, and prior fixture results.

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
| L0. Instrumentation | Normalized episode outcome and complete cost vector derived from existing trace/campaign evidence | Missing metrics remain explicit; outcome labels reconcile with durable state |
| L1. Suggested facts | Read-only candidate extraction into a quarantine store | No automatic injection; secrets and forbidden content rejected; operator can confirm, edit, expire, or delete |
| L2. Verified procedures | Versioned candidate workflow schema, deterministic fixtures, replay evaluator, lifecycle, and rollback | Held-out improvement and zero safety escapes before `ACTIVE` |
| L3. Shadow strategy policy | Offline comparison and non-executing recommendations with visible reward vector | Recommendations reproduce from frozen evidence and never alter live execution |
| L4. Bounded adaptive routing | Context-aware selection among already approved, equivalent low-risk procedures | Canary limits, drift detection, rollback, and no regression in approval or authority gates |
| L5. Offline model research | Separately consented, redacted dataset export and isolated fine-tuning experiment | Independent privacy, security, evaluation, deployment, and rollback approval; outside the default product claim |

Layers and phases are intentionally independent. The project can deliver useful
continual improvement through verified memories, workflows, and strategy routing
without ever performing Layer 4 model-weight learning.
