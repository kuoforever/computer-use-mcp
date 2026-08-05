# ADR-002: A ref action never silently falls back to a coordinate click

Status: Accepted
Date: 2026-07-20
Clarified: 2026-08-05

## Context

`ui_snapshot()` returns UIA controls with session-scoped `ref_N` handles and
bounding boxes. A model then asks for `click(ref="ref_7")`.

Between the snapshot and the click, the desktop can change: the element is
destroyed, the list scrolls, a dialog opens over it, the window moves, or the
application rebuilds its tree. The driver discovers this when the native handle
no longer resolves.

At that moment the bounding box from the snapshot is still sitting in memory,
and clicking its center is one line of code away. That line is the subject of
this decision.

## Decision drivers

- **Correctness of the target.** A click is only correct if it lands on the
  thing the model meant.
- **Failure visibility.** A wrong click and a refused click cost very different
  amounts to diagnose.
- **Model ergonomics.** Refusing too eagerly makes the tool unusable on any
  dynamic UI.

## Considered options

### 1. Fall back to the cached bounding box center

If the ref is stale, click the center of where it used to be.

*Rejected.* The cached box describes where the element *was*. The reasons a ref
goes stale are precisely the reasons that location now holds something else: the
list scrolled and row 7 is now row 4's old position; a modal opened and the
center point is on its backdrop; the element was destroyed and a differently
labeled button reflowed into place.

The failure mode is the worst available one. The model asked to click "Save
draft", the system clicked whatever occupies those pixels — possibly "Delete" —
and reported success. An unrecoverable action is taken, the trace says it went
fine, and the only way to discover it is downstream damage. The system converted
"I cannot confirm the target" into a confident wrong action.

### 2. Re-snapshot and click by position index

On staleness, take a fresh snapshot and use the element at the same index.

*Rejected.* Index is not identity. A newly loaded row, a lazily materialized
Chromium node, or a collapsed group shifts every index after it. This has the
same failure mode as option 1 with more machinery, and it looks principled
enough to survive review.

### 3. Always fail on staleness, never relocate

*Rejected as too strict.* Real UI trees churn constantly, especially in
Chromium-family windows where a first traversal may only materialize
accessibility content. Failing on every stale handle would push the model toward
coordinate clicks — the exact outcome this ADR exists to prevent.

## Decision

A stale ref from an explicit window-id scope gets **one bounded relocation
attempt by identity**, then fails. A stale ref from the dynamic `foreground` or
`all` selector fails immediately and requires a fresh observation.

Relocation searches the fresh tree for a node with the **same role and the same
name**, inside the explicit window-id scope token that first minted the ref, and
among those matches picks the one nearest the original center. Later snapshot
or find calls cannot change that per-ref relocation domain. Role and name are
the identity; geometry is only a tie-breaker between candidates that already
match. If no candidate matches, the call fails with `STALE_ELEMENT` and the
caller is told to re-snapshot.

`foreground` and `all` are selectors, not stable window identities. Once the
original native handle reports stale, either token returns `STALE_ELEMENT`
without another tree query, candidate semantic action, coordinate action, or
ref-map mutation. This avoids retargeting a ref after foreground or window-set
drift without expanding the Driver contract.

An accepted relocation uses the complete fresh Node for the single semantic
retry and updates the cached node, forward native binding, and reverse binding
together. If the candidate native id is already owned by another ref, relocation
fails closed without acting on that candidate or changing either binding. This
keeps the session maps bijective after native-handle churn.

Explicitly forbidden:

- Clicking a cached bounding box center after a failed relocation.
- Relocating by geometry alone, or by position index.
- Relocating in the scope of a later, unrelated observation.
- Relocating a stale ref minted from the dynamic `foreground` or `all` token.
- Stealing a native handle already bound to another ref.
- Reporting success when the target could not be confirmed.

Coordinate clicking remains available as `click(x=..., y=...)`. It is a
**separate, explicit request** by the caller, for visual or canvas targets UIA
cannot express. The distinction is the point: a coordinate click is the model
knowingly accepting pixel-space risk, never the system quietly downgrading a
semantic request.

## Consequences

**Positive.** A ref action either hits the element the model named or fails
loudly. Wrong-target actions from stale state are structurally excluded. The
`STALE_ELEMENT` code gives the model a specific, actionable recovery: observe
again.

**Negative.** Models see more failures, and a caller that does not handle
`STALE_ELEMENT` will stall on dynamic UIs. Dynamic-scope refs now require a new
observation rather than receiving a transparent recovery attempt. Eligible
explicit-window relocation costs a full extra tree traversal on the failure
path. Applications with duplicate role+name pairs inside that same explicit
window can still relocate to the wrong one of the two — identity is only as good
as what UIA exposes, which is a real remaining limit, not a solved problem.

**Future migration point.** If a driver ever exposes a stable per-element
identity (an automation id honored across rebuilds), relocation should prefer it
over role+name, which would narrow the duplicate-name gap above.

## Evidence

Implemented:

- `_act_on_ref` and `_relocate` in `src/computer_use_mcp/core.py`: one retry
  after a `STALE_ELEMENT` result only for an explicit window-id scope, matching
  on `role` and `name` in the ref's original scope token, nearest-center
  tie-break, complete-Node retry, and explicit failure when no candidate exists.
  Dynamic `foreground` and `all` tokens fail before `_relocate`.
- `_rebind` in `src/computer_use_mcp/core.py`: reverse-owner conflicts fail
  closed; accepted relocation updates cached Node plus both map directions and
  releases the old reverse entry.
- `_press` returns `NOT_INVOKABLE` when a resolved ref exposes neither
  `Invoke` nor `SelectionItem`; it never calls the coordinate driver for that
  ref.
- `click(ref=...)` and `click(x=..., y=...)` are separate argument forms in
  `src/computer_use_mcp/server.py`; the ref path additionally runs the dangerous
  target confirmation.
- Relocation is specified in the Driver Contract, section D.

Tested offline:

- `tests/test_core.py::test_stale_foreground_ref_does_not_relocate_into_new_foreground_window`
- `tests/test_core.py::test_stale_all_scope_ref_does_not_query_or_act_on_relocation_candidate`
- `tests/test_core.py::test_later_observation_cannot_move_ref_relocation_scope`
- `tests/test_core.py::test_foreign_scope_candidate_is_never_used_when_original_scope_has_none`
- `tests/test_core.py::test_successful_relocation_rebinds_node_and_native_maps_bijectively`
- `tests/test_core.py::test_relocation_reverse_collision_fails_before_candidate_action`
- `tests/test_core.py::test_same_native_cross_scope_reuses_ref_and_first_scope`
- `tests/test_core.py::test_unknown_ref_fails_without_any_driver_call`
- `tests/test_core.py::test_ref_without_semantic_action_never_falls_back_to_coordinates`

Not verified: relocation quality across applications that expose duplicate
role+name pairs. The behavior in that case is defined (nearest center wins) but
no evidence establishes it picks the intended element.
