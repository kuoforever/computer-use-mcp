# H7 bounded side-effect evidence

> **Result: deterministic isolated-application gate passed on 2026-08-09.**
> This is offline evidence through injected ports. It is not real MCP, Windows
> desktop, provider, external-application, E4, or release evidence.

## Reviewed scope

H7 adds one dedicated internal runtime entry point for exactly this fixed plan
shape:

~~~text
fresh reviewed observation
  -> one reviewed side effect
      -> fresh reviewed verification observation
          -> tool-free final response
~~~

The plan remains inert data. The H7 review gate requires all four steps to be
pending, derives the tool effects and approval metadata from the current
reviewed registry, rejects sensitive tool arguments through the existing plan
contract, and permits exactly one side effect. The linear H1 tree binds the
exact plan, policy, registry, task, run, sequence, and digest under the same
application `RunLock`.

No tree module gained a provider, approval, MCP, desktop, retry, replay, or
dispatch port. `executor_runtime.py` still contains one call to the existing
`AgentRunner._execute_requested_call_boundary`; it contains no direct
`desktop.call_tool` call.

## Isolated application matrix

`tests/agent/test_hierarchical_side_effects.py` supplies a deterministic
isolated toggle application behind the ordinary DesktopMCP protocol. The
production plan store, tree store, H3 leaf compiler, Runner boundary, Host
policy, approval binding, continuation WAL, grounding state, ledger, trace,
post-action recovery state, and final-response compiler remain real.

| Case | Observed result |
| --- | --- |
| Exact success | `ui_snapshot -> click -> ui_snapshot` dispatched in order; one digest-bound approval was requested; the application changed only after approval; final response received the two observations and no action-result content |
| Missing verification | Final response was rejected while the post-action observation remained pending |
| Approval denied | The action leaf became known failed; no action reached the isolated application |
| Approval deferred | The exact leaf became blocked and the run recorded `PAUSED/APPROVAL_DEFERRED`; no action dispatch or unknown-outcome classification occurred |
| Unknown action outcome | Plan and tree action leaves remained `in_progress`, the WAL was preserved, the session closed, and no verification or replay occurred |
| Dispatched action error | The exact leaf became blocked with `requires_reobservation`, the WAL was preserved, and no retry or final response occurred |
| Unsafe shape | Missing pre-observation, reordered action, a second action, and non-exact step counts failed before store creation or tool discovery |

On the exact-success path, the action first invalidated verified observation
state. Only the following successful observation restored
`verified_observation_epoch == observation_epoch` and `recovery_status=ready`.
The final compiler then validated the canonical ledger topology, exact ALLOW
decision digest, three tool calls, one side effect, and two observation epochs.
It deliberately omitted side-effect result text from provider input.

## Boundary retained

- The ordinary H4 and public `ask` / `plan run` entries remain observation-only.
- Current Host policy still decides allow, deny, exact approval, re-observe,
  defer, or takeover. Tree state cannot forge or suppress that decision.
- Grounding, safety baselines, side-effect budgets, approval revalidation, WAL,
  dispatch, result validation, and post-action state remain inside Runner.
- Known pre-dispatch denial is terminal. Unknown outcomes remain untransitioned
  and non-replayable. A known dispatched error retains verification debt and
  WAL rather than being treated as safely complete.
- H7 adds no selector fallback, retry, recovery executor, CLI, Planner tool
  scope, behavior-template promotion, application campaign, or learning route.

## Limits

This evidence uses an injected isolated application and fake approval surface.
It does not claim a real provider, MCP child, Windows input, foreground app,
visual result, cooperative-control action, E4, or release result. Any public or
application-specific H7 product path requires its own reviewed scope and exact
evidence.
