# Cooperative Pause, Takeover, and Resume

> **Status: implemented and offline verified for the installed
> `public-web-word` Runner loops; native desktop acceptance is pending.** This is
> same-process cooperative control, not crash recovery, remote control, campaign
> control, or an operating-system input lock.

## Operator commands

Use the same config that started the fixed workflow:

~~~powershell
guarded-desktop-agent task control --config C:\absolute\path\public-web-word.toml
guarded-desktop-agent task pause --config C:\absolute\path\public-web-word.toml
guarded-desktop-agent task takeover --config C:\absolute\path\public-web-word.toml
guarded-desktop-agent task resume --config C:\absolute\path\public-web-word.toml
~~~

Every command also accepts `--json`. `--run-id` is optional only when exactly
one non-closed controlled run exists. The control commands never call a
provider, MCP, desktop driver, or application themselves.

`pause` and `takeover` initially create only a request. **Do not touch the
shared desktop while the state is `pause_requested`.** The live Runner must
finish the current external call, reach a reviewed safe boundary, persist a
`PAUSED` checkpoint, close its presence authority, and then publish
`status=paused` with `authority=released`. Only that acknowledged state means
the operator owns the desktop lane.

After human work, call `task resume` and stop desktop input. The Runner changes
through `resume_requested` and `resuming`, discards prior grounding and approval
authority, and advertises only observation tools until one successful fresh
observation is durable. Only then does the control record return to `active`.

## State and authority contract

| Control status | Desktop authority | Meaning |
| --- | --- | --- |
| `active` | `agent` | No cooperative request is pending. |
| `pause_requested` | `agent` | Request recorded; the Runner may still be finishing provider or MCP work. |
| `paused` | `released` | A durable safe-boundary checkpoint exists; local human takeover is allowed. |
| `resume_requested` | `released` | Operator has finished; human input must stop while Runner wakes. |
| `resuming` | `agent` | Old grounding is invalid and a fresh successful observation is mandatory. |
| `closed` | `none` | The controlled Runner loop ended; inspect its ordinary run outcome. |

The reviewed safe boundaries are `before_provider`, `before_tool`, and
`after_approval`. The request does not interrupt an in-flight provider or MCP
call. In particular, a side effect that is already dispatched or might have
been dispatched is never relabeled as paused: an uncertain result remains
terminal `UNKNOWN_OUTCOME` and is never replayed.

## Decision Card takeover

For the installed `public-web-word` workflow, the four-choice Decision Card
offers exact-effect approval, re-observe, human takeover, and deny. Human
takeover creates the same digest-bound policy decision and then enters the same
cooperative safe-boundary path; the stale action is recorded as known not
dispatched and consumes no side-effect budget.

This does not redefine the older `Defer` choice used by other approval
surfaces. `Defer` remains a non-resumable stopped checkpoint that requires a
new run. It cannot be continued with `task resume`.

## Persistence and trust boundary

The Host writes one strict version-1 record at:

~~~text
state_dir/runs/<run_id>/control.json
~~~

It contains only safe identifiers, an owner-token digest, a root-constrained
Runner state path, sequence/status/request enums, authority, fresh-observation
requirement, safe-boundary/checkpoint numbers, outcome, and timestamps. It
contains no task, provider content, model prose, approval payload, screenshot,
tool arguments, tool result, credential, memory, or continuation data.

Mutations use an independent short OS-backed lock and atomic replace. External
pause/resume requires the main Agent run lease to be held and exactly one live
control record to be unambiguous. Resume additionally requires the exact
`PAUSED` checkpoint sequence and `requires_reobservation` state. Missing,
corrupt, stale, ambiguous, symlinked, mismatched, or unsupported state fails
closed.

Cooperative control is deliberately incompatible with the sensitive
continuation WAL. Crash recovery remains conservative and starts through its
existing reviewed paths; it never reconstructs this same-process authority
handoff.

The record is private local runtime state. It is not an automatic Full Cycle
export input and adds no data lane or second desktop dispatch path. The Runner
and existing MCP server remain the only route to desktop tools.

## Current evidence boundary

Offline tests cover the local CAS lifecycle, live-lease and exact-checkpoint
binding, human/JSON CLI commands, nested reopen-verifier state, safe pause before
tool dispatch, Decision Card takeover, stale-call rejection, observation-only
resumption, fresh-observation acknowledgement, early continuation rejection,
and `UNKNOWN_OUTCOME` precedence over a late pause request.

They do not prove real provider timing, Windows focus behavior, operator hand
timing, application correctness, multi-display behavior, E4, or release
readiness. Those gates remain deferred until feature freeze.
