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
5. The console displays a non-sensitive argument summary and SHA-256 call
   digest. Only an explicit `y` or `yes` approves that one request.
6. The returned decision must match request ID, run/turn/call identity, and
   digest. A stale or mismatched decision is rejected.
7. The call is marked Host-authorized and dispatched through the serialized
   MCP bridge, which independently applies its allowlist, human-activity,
   confirmation, E-stop, and audit checks.

The console defaults to deny on empty input, EOF, interruption, or any answer
other than explicit yes. It never prints raw typed text.

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
