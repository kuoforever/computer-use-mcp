# Experimental approved-action workflow

> **Status: implemented with fake-port verification; isolated desktop smoke
> pending.** The Host can orchestrate locally approved `activate_window`,
> `click`, and `key` calls. The feature is opt-in and does not alter or bypass
> any MCP Server safety mechanism. `type` remains disabled.

## Enablement

Set the Agent policy explicitly:

~~~toml
[policy]
mode = "approved_actions"
require_approval_for_actions = true
max_side_effects = 8
~~~

Install a provider extra and run from an interactive local console. In this
mode the provider receives schemas for `activate_window`, `click`, and `key` in
addition to text observation tools. The common Runner remains the authority:
provider output cannot approve, ground, or dispatch an action.

## Authorization sequence

For each requested action, the Host performs these checks in order:

1. The tool is in the fixed reviewed registry and its arguments pass the Host
   schema.
2. The policy is `approved_actions`; tools with an unverified required safety
   baseline remain denied.
3. Grounding belongs to the current MCP child generation and satisfies the
   tool-specific requirement.
4. The side-effect budget has remaining capacity.
5. The default console displays a non-sensitive argument summary and SHA-256
   call digest. With explicit Decision Card opt-in, the Runner first yields
   desktop authority and opens a three-choice native card. Only the explicit
   exact-effect choice approves that one request; handoff and denial stop before
   dispatch.
6. The returned decision must match request ID, run/turn/call identity, and
   digest. A stale or mismatched decision is rejected.
7. The call is marked Host-authorized and dispatched through the serialized
   MCP bridge, which independently applies its allowlist, human-activity,
   confirmation, E-stop, and audit checks.

The console defaults to deny on empty input, EOF, interruption, or any answer
other than explicit yes. It never prints raw typed text.

## Decision Card approval adapter

The pure Host model can compile two or three bounded alternatives
with benefits, costs, risks, reversibility, authority scope, fallback, and
provenance for time/token/confidence estimates. See
[Operator experience](OPERATOR_EXPERIENCE.md).

This is decision support, not delegated authority. A model recommendation cannot
approve itself. Choosing an option must create a fresh identity- and digest-
bound Host decision; any resulting side effect still passes the existing
grounding, budget, approval, MCP safety, and post-action verification path.
Evidence or object-version drift invalidates the card before dispatch.

The compiler and deterministic choice validator still have no provider,
approval, desktop, or dispatch port. The opt-in local adapter now implements
the existing `ApprovalPort`: it converts only a fresh, correlated
`approve_exact_effect` selection into the ordinary digest-bound
`PolicyDecision`. The Runner recomputes state, policy, task, registry, object,
and grounding-evidence digests after the interaction before dispatch.

The Win32 adapter uses a timed Common Controls v6 Task Dialog with three custom
choices: request approval for the exact effect, hand control to the operator,
or deny. It shows fixed trade-offs and an expandable evidence section containing
only evidence kinds, unknown-fact enums, expiry, and SHA-256 Host/card digests.
Handoff and denial both produce distinct request-bound denials with zero
side-effect dispatch. Cancel/close/timeout return no selection and deny. Native
errors, malformed choices, missing context, and expiry also deny. This creates
no alternate MCP call site, global allow control, batch approval, model
approval, or automatic recommendation selection. The console remains the
default when the card is disabled.

## Grounding rules

Grounding is in-memory, generation-qualified, and derived only from successful
reviewed observations:

| Action | Required grounding |
| --- | --- |
| `activate_window(window_id)` | The ID appears in a current-generation `list_windows` result. |
| `click(ref=...)` | The ref appears in the latest current-generation `ui_snapshot` or `find` result. |
| `click(x=..., y=...)` | A current-generation screenshot exists and coordinates are inside its validated dimensions. |
| `key(combo)` | At least one current-generation successful observation exists. |
| `type(...)` | Disabled; the Host has not bound its required audit baseline to a verified child revision. |

The current provider adapters do not return screenshots to the model, so
coordinate click grounding is implemented and tested but is not normally
reachable through the live provider loop yet.

## Mandatory post-action verification

Any side-effect call that may have been dispatched clears all grounding, sets
`recovery_status=requires_reobservation`, and clears the verified observation
epoch. This applies to successful and action-error results. The model cannot:

- issue another action in the same turn;
- obtain another approval; or
- finish the run with a claimed success.

A successful observation is required first. It establishes a new epoch and
returns recovery to `ready`. An `unknown_outcome` stops immediately, writes the
terminal unknown state, and is never replayed.

## Current validation boundary

Offline tests prove allow/deny/mismatch binding, grounding freshness, MCP
generation drift, bounds, side-effect accounting, serialization, mandatory
re-observation, typed-text denial, unknown outcomes, redacted approvals, and
terminal trace state.

No real approved action should be treated as release-qualified until E4 runs
against disposable Notepad or a VM with a narrow allowlist and operator review.
Do not test approved actions on a sensitive or actively used desktop.

## Planned enterprise authorization extension

The current approval is intentionally one local confirmation for one GUI
action. It is not an enterprise authorization model. Future enterprise
workflows must introduce a separate, fail-closed authority envelope bound to:

- authenticated user, tenant, role, and policy version;
- application and stable business-object identity;
- allowed fields and business transitions, not only GUI tool names;
- data classification, recipient scope, purpose, and retention class;
- maximum amount, record count, side effects, and expiration time;
- required approver role and separation-of-duties constraints.

Risk tiers should distinguish read, draft, internal write, external
communication, terminal workflow transition, privilege change, and financial
posting or payment. A scoped approval may cover a bounded batch only when every
item matches the exact envelope and remains independently auditable. Tenant,
object version, recipient, amount, or policy drift invalidates the approval.

The provider and desktop remain untrusted sources of authority. SSO success,
visible access to a button, UI text claiming approval, or possession of a stale
approval record never widens scope. MFA, consent, elevation, cross-tenant access,
and maker-checker review require an explicit human or enterprise identity
system decision outside model control.
