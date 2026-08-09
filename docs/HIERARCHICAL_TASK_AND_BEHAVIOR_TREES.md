# Hierarchical task and behavior trees

> **Status: H1-H7 implemented and offline verified; H8 remains planned.**
> Versioned nodes, canonical tree digests, reviewed structural limits, pure
> status reduction, lossless linear-plan projection, and private atomic tree
> persistence plus digest-bound next-leaf compilation now compose with the
> existing observation-only Runtime Executor. H4 adds no second Runner/MCP
> dispatch site or new approval, retry, replay, recovery, or campaign authority.
> Its evidence is offline fake-port evidence only.

## Prior decisions this inherits

This design adds no new invariants. It is constrained by decisions that are
already accepted, and every rule below is a consequence of one of them:

| Decision | Consequence for trees |
| --- | --- |
| [ADR-001](adr/001-uncertain-dispatch-is-never-auto-replayed.md) | A selector or retry decorator may never react to an uncertain boundary. |
| [ADR-003](adr/003-custom-durability-vs-workflow-engine.md) | The tree extends the project's own ledger; it does not become or import a workflow engine, and node visits are not activity retries. |
| [ADR-004](adr/004-mcp-server-is-sole-desktop-authority.md) | No tree code dispatches MCP; every boundary reuses the sole Runner path. |
| [ADR-005](adr/005-model-output-is-untrusted-data-not-authority.md) | A model-proposed tree is a candidate to compile, never authority to execute. |
| [ADR-006](adr/006-durable-state-is-the-source-of-truth.md) | Node state is durable evidence; an in-memory tree walk is never the record. |
| [ADR-007](adr/007-one-active-lease-per-foreground-desktop.md) | No `parallel` node may imply concurrent foreground desktop authority. |

ADR-003 deserves particular attention here. Hierarchical control flow with
retries, fallbacks, and reusable subtrees is exactly the shape that invites a
workflow engine back in. The delivery sequence below is written so that the
tree remains a projection over the existing plan store rather than a second
execution history.

## Why this is needed

The current `TaskPlan` is deliberately bounded and linear. That shape is useful
for proving the first observation-only Planner/Executor path, but it cannot
represent common universal-GUI control flow without repeatedly returning to an
unstructured model loop:

- optional login, dialog, or onboarding branches;
- UIA -> document text -> OCR -> visual grounding fallbacks;
- bounded pagination, search refinement, and mode recovery;
- reusable subgoals such as finding a window or opening a matching result;
- local failure of one strategy without failing an unrelated parent goal; and
- explicit postconditions at both step and subgoal boundaries.

The planned design therefore adds hierarchical task state and reviewed behavior
templates. It does not replace the existing run state machine.

## Three-layer control model

~~~text
RunPhase state machine
  -> hierarchical task tree
      -> reviewed behavior subtree or primitive planned step
          -> sole Runner call boundary
              -> grounding, policy, budget, approval, WAL, MCP, re-observation
~~~

Each layer has a different responsibility:

1. The existing `RunPhase` state machine remains the lifecycle, safety,
   checkpoint, cancellation, and recovery authority.
2. The hierarchical task tree represents goals, subgoals, ordered work,
   observed conditions, and bounded alternative strategies.
3. Behavior trees are versioned, host-reviewed skill templates. They propose
   the next boundary but never dispatch a tool or grant authority.

There must not be a second MCP dispatch site or a second implementation of
approval, policy, grounding, budgets, write-ahead, or verification.

### Run-phase projection

The relationship between the two state layers must be explicit, or the tree
becomes a competing lifecycle authority. The rule is one-directional: the tree
never sets a run phase, and `RunPhase` is never derived from a tree walk. The
host records phases from the same boundary events it records today, and the
tree contributes only the leaf identity that boundary belongs to.

| Tree situation | Recorded phase | Required behavior |
| --- | --- | --- |
| Evaluating conditions, selecting the next leaf | unchanged | Local reduction produces no phase record. |
| Fresh observation for a condition or verify node | `OBSERVING` | Ordinary observation accounting; conditions may only read this epoch. |
| Host compiling a model-proposed candidate | `PLANNING` | Compilation is not a boundary; a rejected candidate fails closed. |
| Leaf awaiting approval | `WAITING_APPROVAL` | The tree does not advance; denial is terminal for that leaf, never a selector input. |
| Durable defer on a leaf | `PAUSED` | The tree snapshot is the resume point; refs and conditions are re-derived, never reused. |
| Leaf boundary dispatched | `EXECUTING` | Exactly one leaf may be `in_progress` at this moment. |
| Verify node after a boundary | `VERIFYING` | A postcondition needs fresh observation; a stale epoch fails closed. |
| Root reduced to `completed` after the terminal response | `SUCCESS` | Only `final_response` may terminalize a run. |
| Root reduced to `failed`, `blocked`, or `cancelled` | `FAILED` / `CANCELLED` | Ordinary terminal accounting for the whole tree. |
| Uncertain leaf boundary | `UNKNOWN_OUTCOME` | No node transition at all; live authority closes; continuation WAL is retained. |

`CREATED` remains a run fact that precedes any tree. A tree may exist across
several phase records, but a phase record never spans two leaves.

## Planned task-tree contract

The first hierarchical contract should support only a small closed set of
host-defined node kinds:

| Node | Purpose |
| --- | --- |
| `goal` | Named goal or subgoal with explicit success criteria. |
| `sequence` | Visit children in host-defined order. |
| `choice` | Select one eligible branch from verified observation facts. |
| `condition` | Evaluate a typed, non-authorizing fact from the current observation epoch. |
| `tool_step` | Compile one candidate `ToolCall` for the existing Runner boundary. |
| `verify` | Check a typed postcondition after fresh observation. |
| `subtree` | Invoke one pinned, reviewed behavior-template version. |
| `final_response` | Produce the single terminal, tool-free response boundary. |

Every node uses the existing durable step vocabulary unchanged. It is the exact
`PlanStepStatus` set already persisted by the plan store:

~~~text
pending
in_progress
completed
failed
blocked
cancelled
~~~

The tree adds no seventh status. In particular it must not add
`unknown_outcome` as a node state, because uncertainty is already represented
one layer up and adding it here would create a second representation of the
same fact.

The current Executor establishes that precedent: when a boundary returns an
uncertain outcome it performs *no* step transition at all. The leaf stays
`in_progress`, the run records `RunPhase.UNKNOWN_OUTCOME`, and the continuation
WAL is deliberately preserved rather than deleted. Tree execution must behave
identically — an uncertain leaf is a leaf whose durable status was never
advanced, not a leaf marked with an uncertainty status.

Reusing the vocabulary also satisfies the migration acceptance condition below
without a data rewrite: a linear plan is the degenerate tree of one `sequence`
over existing steps, and existing persisted statuses remain valid as-is.

Parent state is a deterministic projection of child evidence, using the same
reduction precedence the plan store already applies (`failed`, then `blocked`,
then `cancelled`, then all-`completed`, then `in_progress`, then `pending`).
The projection must be reconstructible from the canonical ledger and exact tree
version. Persisted node state is evidence, not tool authority.

The contract must bind at least:

- run, task, registry, policy, and tree digests;
- stable host-generated node IDs and parent IDs;
- maximum depth, node count, visits, and wall-clock lifetime;
- per-node and aggregate tool, token, side-effect, and retry budgets;
- condition source, observation epoch, window identity, and freshness;
- behavior-template identity and immutable version; and
- the correlated call, result, observation, and verification evidence for each
  completed boundary.

## Planned behavior-tree subset

The first behavior-tree implementation should remain intentionally smaller than
general behavior-tree frameworks.

Supported initially:

- `sequence`;
- `selector`;
- typed observation-only `condition`;
- one-boundary `action`;
- mandatory `verify`;
- host policy `guard`;
- `bounded_retry` with a fixed host maximum; and
- pinned `subtree`.

Deferred initially:

- parallel desktop actions;
- arbitrary script or expression nodes;
- unbounded loops or recursion;
- model-defined node kinds;
- implicit compensation;
- dynamic budget expansion;
- automatic approval; and
- retry or fallback after an uncertain dispatch.

The desktop has one foreground window, focus, pointer, and keyboard. A
`parallel` node could later coordinate independent read-only computation, but
it must not imply concurrent foreground desktop authority.

## Result propagation and fail-closed rules

Behavior control flow must distinguish known strategy failure from loss of
execution knowledge:

| Child result | Parent behavior |
| --- | --- |
| Condition is false | A selector may evaluate its next eligible branch. |
| Known, verified strategy failure | A selector may use a separately bounded fallback. |
| Success with verified postcondition | The parent may advance. |
| Approval denied or authority expired | Stop; do not reinterpret as a strategy failure. |
| Policy, budget, grounding, or version conflict | Stop or block according to the existing host decision. |
| Uncertain boundary outcome | Perform no node transition, stop the complete tree, and close live authority immediately. |

An uncertain click, key, submission, or other side effect must never cause a
selector or retry decorator to try another branch. Recovery continues to obey
the existing rule that uncertain side effects are not automatically replayed.

## World-state and condition model

Conditions must not read arbitrary model prose or stale UI handles. The H5
world-state projection contains typed facts with:

- source and extraction method;
- observation and MCP generation;
- capture time and freshness;
- window/process identity;
- confidence or explicit unknown state; and
- supporting evidence digest.

Facts are invalidated when their source generation, target window, or required
freshness changes. UI refs remain generation-bound and cannot be stored as
cross-run memory or durable behavior-template parameters.

The world-state projection helps choose control flow. It is not an approval,
policy, completion, or recovery authority.

## Planner and model boundary

Model output remains untrusted data. A model may eventually:

- select a host-disclosed behavior template;
- bind schema-validated non-sensitive parameters;
- propose a bounded task-tree candidate; and
- request replanning after fresh observations.

The host must compile that proposal into the closed node contract, derive all
effect and approval metadata from the reviewed registry, enforce structural
and budget limits, and bind the resulting tree by digest.

A model may not:

- create executable code;
- invent tools, node kinds, authority, approvals, or policy facts;
- enlarge retry, depth, token, call, or side-effect limits;
- declare observations or verification complete without correlated evidence;
- turn a failed approval or safety guard into a fallback condition; or
- continue a tree after `RunPhase.UNKNOWN_OUTCOME`.

## Campaign and item scope

The campaign layer already owns day-scale work: a manifest, an append-only item
ledger, bounded batches, leases, heartbeats, and cross-session handoff. A tree
must not duplicate or reinterpret any of it.

The intended scope is therefore narrow:

- A tree is scoped to **one run** and, inside a campaign, to **one claimed
  item**. There is no campaign-level tree and no batch-level tree.
- The item ledger remains the durable progression authority. A tree may inform
  a single `DISCOVERED -> CLAIMED -> OBSERVED -> EXTRACTED -> COMMITTED`
  transition through the existing commit path; it never writes item state
  directly and never invents a transition the ledger does not already permit.
- Item selection, batch bounds, retryable classification, exhaustion, and
  terminal handoff stay with the coordinator. A `selector` inside a tree
  chooses a strategy for the current item; it never chooses the next item.
- Tree budgets are nested inside the batch budget, never additive to it. A tree
  cannot extend a lease, and lease loss stops the tree the same way authority
  expiry does.
- A tree does not survive a handoff. A fresh owner re-derives its tree from the
  reviewed template registry and fresh observation, exactly as it re-derives
  refs today.

The practical near-term target is the per-item observation ladder that the BOSS
runtime currently expresses as fixed code: UIA, escalation to document text,
then the bounded OCR path. That ladder is a `selector` with typed conditions
and mandatory verification, which makes it the natural first application — and
the natural first test that the tree adds no authority the fixed runtime lacked.

## Persistence and execution

Tree execution should extend the existing plan-store approach rather than
introduce another workflow authority:

1. Load one exact tree snapshot under the existing application `RunLock`.
2. Compare sequence and tree digest before every transition.
3. Mark only the selected next leaf `in_progress`.
4. Compile at most one external boundary.
5. Route that boundary through the sole Runner path.
6. Commit correlated result and fresh observation evidence.
7. Verify the leaf postcondition.
8. Deterministically reduce ancestor state and persist one new snapshot.

A tick may perform local condition evaluation and state reduction, but it should
produce at most one external tool boundary. Crash reconciliation must repair
only known completed evidence and must never redispatch uncertain work.

## Implemented H1 boundary

`src/computer_use_agent/hierarchical_control.py` implements the first inert
contract layer:

- the closed `goal`, `sequence`, `choice`, `condition`, `tool_step`, `verify`,
  `subtree`, and `final_response` node set;
- stable node/parent IDs, ordered child bindings, exactly one final response,
  complete reachability, cycle rejection, and bounded depth/node/child counts;
- tree-level visits/lifetime limits plus per-node and aggregate tool, token,
  side-effect, and retry budgets, all bound into canonical JSON and SHA-256;
- exact reuse of `PlanStepStatus` with pure total parent reduction;
- a pure reducer that recomputes ancestor projections from leaf evidence but
  deliberately does not authorize transitions; and
- lossless projection of an existing strict linear `TaskPlan` as one inert
  `sequence` without retaining raw task text or executable arguments.

Direct construction fails closed on malformed identities, digests, bindings,
budgets, versions, topology, or non-canonical parent state. H1 has no parser for
model candidates and no store or runtime entry point. H2 owns persistence and
CAS; H3 owns next-leaf compilation. [ADR-010](adr/010-tree-uncertainty-remains-outside-node-state.md)
keeps uncertain dispatch exclusively in the outer run state.

## Implemented H2 boundary

`src/computer_use_agent/tree_store.py` adds one private
`runs/<run_id>/task-tree.json` snapshot under the existing application
`RunLock`:

- strict versioned decoding rejects unknown fields, malformed identities,
  non-canonical parent state, registry drift, and tree/envelope digest drift;
- create is pending-only and never intentionally replaces an existing tree;
- replacement requires the exact current sequence and tree digest, increments
  the sequence once, and permits only a canonical status projection over the
  unchanged H1 structure, limits, budgets, and identities;
- a bounded `0600` temporary file is flushed and fsynced before atomic replace,
  with deterministic fault-injection seams before every persistence boundary;
  restart reads only the last complete snapshot; and
- the module has no provider, Runner, MCP, campaign, desktop, policy, approval,
  retry, replay, or dispatch port.

H2 intentionally does not decide whether a status transition is legal and does
not select a leaf. Those pure control decisions belong to H3. This keeps the
store durable evidence rather than a second execution authority.

## Implemented H3 boundary

`src/computer_use_agent/hierarchical_compiler.py` consumes one immutable H1
tree plus its H2 sequence and returns exactly one of four pure results:

- `boundary`: at most one inert leaf identity bound to the exact sequence,
  tree digest, run, tree, node kind, and reviewed leaf binding;
- `waiting`: one exact ordered leaf is already `in_progress`, so no boundary is
  emitted again;
- `terminal`: the canonical root is complete, failed, blocked, or cancelled;
  or
- `blocked`: a `choice` needs H5 typed fresh facts and cannot yet select a
  branch.

The compiler rejects multiple active leaves, an active leaf that skips earlier
work, an active leaf inside a terminal tree, registry drift, and malformed
sequence/binding data. Its separate pure transition reducer permits only the
current ordered leaf to follow the existing `PlanStepStatus` transition graph;
terminal state cannot re-enter. Boundaries contain no task text, arguments,
tool object, callable, authority, or dispatch method. The frozen H3 trace covers
initial selection, active waiting, ordered advancement, completion, and every
known terminal result without executing or persisting anything.

## Implemented H4 boundary

`src/computer_use_agent/hierarchical_runtime.py` is a port-free status
projection consumed optionally by the existing `RuntimeExecutorSession`:

- the Host projects only an observation-only linear `TaskPlan`, binds it to the
  current reviewed policy digest, and creates the plan and tree under the same
  existing application `RunLock`;
- H3 must select the exact plan step, then H2 durably marks that leaf
  `in_progress` before the existing plan CAS, WAL, and sole Runner boundary;
- known results update the plan first, pass the existing correlated-ledger
  check, and only then terminalize the exact tree leaf;
- unknown or post-dispatch failure leaves both plan and tree `in_progress`,
  preserves the continuation, closes live authority, and offers no retry or
  dispatch method; and
- an explicit same-lock repair can only re-project exact durable plan statuses
  into the fixed tree structure. It cannot call provider, approval, MCP, or
  desktop ports and cannot change an `in_progress` plan into a retryable state.

The tool-free final-response leaf uses its existing dedicated WAL and provider
port ordering. Side-effect plans are rejected before store creation or tool
discovery. Deterministic tests cover exact pre-boundary ordering, success,
known failure, uncertainty, cancellation, tree/plan commit failures, local-only
repair, final-response completion, zero replay, and the unchanged sole Runner
dispatch-site invariant. No live provider, MCP, desktop, application, E4, or
release evidence is claimed.

## Implemented H5 boundary

`src/computer_use_agent/world_state.py` adds a pure, bounded, non-persistent
fact and condition contract:

- each boolean, integer, bounded text, or identifier fact is `observed` or
  explicitly `unknown` and binds one successful reviewed observation call;
- the source tool fixes the extraction method to UI Automation, window
  enumeration, document text, OCR, or pixel measurement; there is no model
  extraction method;
- evidence retains only run/turn/call identity, observation epoch, MCP
  generation, capture time, source-text length/digest, bounded image
  digest/dimensions, and optional exact window/process identity — never raw
  observation text or image bytes;
- window-scoped facts require exact window ID, process ID, and process name;
  run-scoped facts carry no window binding and gain no window authority;
- facts have a Host-bounded maximum age. Run, epoch, generation, window, type,
  clock, or age drift returns an unavailable inspection with no value or
  evidence/fact digest; and
- typed equality conditions are deliberately three-valued. Only a fresh known
  fact can be `true` or `false`; missing, unknown, mismatched, or stale facts are
  `unavailable`, so a selector cannot mistake lost evidence for known false.

Snapshots are canonical, digest-bound, empty-state capable, and limited to 128
facts. H5 has no store, provider, Runner, MCP, desktop, approval, tree
transition, retry, replay, or automatic-learning port. H5 itself neither
chooses a branch nor advances a node. Evidence remains offline and injected
only.

## Implemented H6 boundary

`src/computer_use_agent/behavior_templates.py` adds the first immutable Host
registry and deliberately contains one template only:

- `boss.per_item_observation_ladder` version 1 is pinned by exact ID, version,
  and canonical SHA-256 digest; lookup has no latest-version, unknown-version,
  or digest fallback;
- its selector rungs exactly reproduce the existing fixed BOSS order: foreground
  UIA, foreground document text, bounded OCR, bounded crop, and screenshot;
- every rung revalidates the current reviewed tool as observation-only, binds
  its exact argument shape, and freezes its safety-baseline requirements. OCR
  therefore retains `title_matched_image_redaction`; the template cannot bypass
  a missing baseline;
- only explicit `INCOMPLETE` advances. The registry delegates to the existing
  pure BOSS reducer and rejects any ladder, terminal-status, or exhaustion-code
  drift rather than inventing a transition;
- an H1 `subtree` leaf may bind the exact template pin and its five-observation,
  zero-side-effect, zero-retry budget, but receives no tool name, arguments,
  call identity, or dispatch method; and
- the existing BOSS semantic runtime now obtains the same tools, arguments, and
  reducer decisions through that exact pin. Provider disclosure, the sole
  Runner boundary, budgets, handoff, and policy denial remain unchanged.

The offline matrix freezes both template and registry digests, compares every
legal ladder progression, sufficient exit, terminal handoff, and exhausted
handoff with the pre-H6 reducer, rejects skips and malformed pins, and proves
side-effect tools or safety-baseline drift cannot enter the template. H6 adds
no store, provider, Runner, MCP, desktop, approval, retry, replay, learning, or
new side-effect authority. It is not application or live evidence.

## Implemented H7 boundary

`src/computer_use_agent/hierarchical_side_effects.py` and the dedicated H7
Runtime Executor entry accept only one exact pending linear sequence:
observation, one side effect, verification observation, then final response.

- The independent review gate runs before store creation or tool discovery and
  derives effects plus approval metadata from the reviewed plan/registry.
- H4 and the public Planner/Executor remain observation-only. H7 opts one
  internal session into side-effect preflight without adding a dispatch site.
- The tree leaf is durable `in_progress` before the existing plan CAS and
  Runner boundary. Runner alone owns grounding, policy, risk classification,
  approval, budgets, WAL, MCP dispatch, and post-action state.
- A successful dispatched action clears verified observation state. Final
  response remains impossible until the exact next observation restores fresh
  verification; action-result content is excluded from final provider input.
- Denial is terminal, defer is known blocked/paused, unknown outcome retains
  the exact active leaf and WAL, and a dispatched known error is blocked with
  verification debt plus retained WAL. None can become selector or retry input.

The [deterministic isolated-application evidence](H7_BOUNDED_SIDE_EFFECT_EVIDENCE.md)
covers the exact success, denial, defer, unknown, dispatched-error, malformed
shape, and missing-verification paths. It is injected-port evidence only and
does not claim a real provider, MCP child, Windows desktop, external
application, E4, or release result.

## Initial behavior-template candidates

The first reviewed templates should exercise useful universal-GUI mechanisms
without broad side-effect authority:

1. ensure a target window is present and freshly identified;
2. find a control through a bounded UIA/document-text/OCR/visual ladder;
3. wait for a stable observation with a fixed timeout;
4. dismiss an optional, positively identified dialog;
5. search and open a matching result;
6. traverse a bounded number of pages;
7. recover a known application mode from fresh observation; and
8. verify navigation or document state after an action.

Each template needs deterministic fake tests, adversarial condition tests,
crash-boundary tests, and isolated application evidence before promotion.

## Delivery sequence

These phases use the `H` prefix in the
[taxonomy map](CAPABILITY_STATUS.md#taxonomy-map). They are a delivery order,
not a product priority sequence.

| Phase | Deliverable | Gate before the next phase |
| --- | --- | --- |
| `H1` | **Implemented/offline verified:** versioned node schema, canonical tree digest, structural limits, deterministic state reduction, and linear-plan projection. | Passed: reduction is pure and total over the existing status vocabulary; the contract exposes no execution port. |
| `H2` | **Implemented/offline verified:** private tree store with `RunLock`, sequence/tree-digest CAS, strict restart decoding, and no external ports. | Passed: every injected pre-commit persistence failure leaves no create snapshot or the exact prior update snapshot. |
| `H3` | **Implemented/offline verified:** pure digest-bound next-leaf compiler, legal ordered leaf transitions, and frozen offline trace fixtures. | Passed: every tick yields zero or one inert boundary and never persists or dispatches; unresolved choice facts fail closed. |
| `H4` | **Implemented/offline verified:** observation-only linear trees through the existing Runtime Executor and sole Runner boundary. | Passed: policy, approval, grounding, budget, WAL, re-observation, uncertainty, and single-dispatch-site tests remain green; side effects fail before external work. |
| `H5` | **Implemented/offline verified:** typed world-state facts, content-free observation evidence, exact window/process binding, bounded freshness, and three-valued equality conditions. | Passed: stale epochs, generation/window drift, expiry, unknown/missing/type mismatch, and clock rollback are unavailable rather than false and expose no fact value. |
| `H6` | **Implemented/offline verified:** one exact-version reviewed template registry, starting with the per-item observation ladder. | Passed: exact tools, arguments, safety baselines, reducer outcomes, terminal handoffs, and budget reproduce the fixed runtime with no added authority. |
| `H7` | **Implemented/offline verified:** one exact observation/action/verification-observation/final sequence through the existing Runtime Executor and sole Runner boundary. | Passed: separate shape/authority review plus deterministic isolated-application success, denial, defer, unknown, dispatched-error, and missing-verification evidence with zero new authority. |
| `H8` | Read-only parallel computation or richer graph dependencies. | Only after serialized desktop authority and crash semantics remain proven. |

`H1`-`H3` add no runtime behavior at all. H4 composes only the already
supported observation/final-response plan and adds no new external authority.
`H7` is the first phase that widens the internal hierarchical runtime, and it
inherits the existing approval review rather than defining its own. No public
Planner/Executor or application workflow is widened by H7.

`H1` also produces one architecture decision record for the single constraint
here that reads as over-strict without its context: node state reuses the
existing step vocabulary and never records uncertainty, so a tree cannot
represent "this leaf failed uncertainly" at all. That is a direct consequence
of [ADR-001](adr/001-uncertain-dispatch-is-never-auto-replayed.md), and it is
the rule most likely to be relaxed by someone who has not read it.

## Acceptance conditions

The complete hierarchical runtime is not accepted until all of the following
are true. H1-H7 satisfy the schema, limit, digest, state-vocabulary,
linear-plan compatibility, private persistence/CAS/crash boundaries, pure
next-leaf/transition subset, existing observation-runtime composition, exact
single-action/verification gate, and
typed fresh-fact condition boundary plus exact pinned-template registry:

- no tree code directly dispatches MCP;
- existing policy, approval, grounding, budget, WAL, and re-observation tests
  pass unchanged;
- every external boundary is correlated to one exact tree leaf;
- all structural and visit limits fail closed before execution;
- selector fallback occurs only after a known eligible result;
- an uncertain boundary stops the complete tree with zero automatic replay and
  leaves its leaf durably untransitioned;
- node state uses the existing step vocabulary with no added status;
- a crash at every persistence boundary has a deterministic offline outcome;
- model-generated candidates cannot create authority or expand limits;
- a tree neither writes campaign item state nor selects the next item; and
- current linear plans remain readable as the degenerate single-`sequence`
  tree, with no persisted-status rewrite.

