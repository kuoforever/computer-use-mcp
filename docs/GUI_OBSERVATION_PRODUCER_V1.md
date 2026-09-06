# Internal GUI observation producer v1

Status: implemented, offline-tested only. Date: 2026-09-06.

`GDA-GUI-001` implements an offline-tested producer for the model-lifecycle
PR #96 observation projector. It is not registered as an MCP tool, CLI command,
Runner route, provider, automatic export, or desktop execution capability.

## Contract and ownership

`computer_use_agent.gui_observation.collect_gui_observation` is async and takes a version-1
task containing only `request_id`, positive numeric `target_scope`, and a target
`name` / `role`. A trusted internal `ObservationSource` supplies three actual
`ToolCall` / `ToolResult` pairs, the Host's generation / observation epoch,
strict metadata inspections, and the issuing Session's ref-to-native-ID lookup.
The caller cannot supply the four missing Host facts or choose result epochs.
Reads, inspections and ref resolution are awaited to match the async
`DesktopMCPPort`; cancellation propagates without retry or a partial bundle.
`state()` is a synchronous read of the Host's current in-memory ledger state.

The coordinator requests `list_windows`, explicitly scoped `ui_snapshot`, then
`screenshot`. Calls must succeed, share run / turn / generation, have unique IDs
and increasing epochs, and match the current ledger. The final screenshot epoch
becomes the context epoch. The bundle holds canonical JSON bytes and separate
PNG bytes; neither is persisted or transmitted by this API. `to_dict()` returns
a detached copy. Raw observations and images remain local sensitive data and
must never enter the automatic Full Cycle export.

A concrete Host `ObservationSource` adapter is **not implemented or wired** in
this slice. It must later use the existing Runner/MCP boundary, actual ledger
stamps and actual issuing Session refs. Arbitrary application callbacks do not
become authenticated evidence merely by implementing this Python protocol.

## How the four fact groups are derived

| Fact | Required evidence |
| --- | --- |
| Window bounds | Checked `GetWindowRect` for the explicit visible, non-minimized foreground HWND |
| Primary frame origin | Monitor enumeration with origin `(0, 0)` and dimensions equal to the returned screenshot |
| Coherent complete projection | Equal strict metadata before/after the three reads, unchanged generation, correctly ordered epochs, stable final ledger, complete matching visible-control set, and elapsed-time budget |
| Verified control states | Direct UIA property reads without fallbacks, matched to each snapshot ref through its native runtime ID |

`WindowsDriver.inspect_gui_metadata` is an optional internal method, separate
from the unchanged Driver v1 abstract contract. It uses strict UIA reads rather
than the legacy best-effort `get_tree` properties. Missing properties, invalid
IDs, duplicate controls, unsupported roles, ambiguous/truncated text, geometry
outside the window/frame, state mismatches and changed foreground fail closed.

The v1 projection accepts only named button/edit/document controls. Structural
pane/group/window/text/custom nodes are traversed but not proposed as targets.
The walk rejects more than 512 visited nodes, depth beyond 12, or more than 64
projected controls. Unknown actionable roles fail closed. It does not establish
support for arbitrary Chrome or Word accessibility trees. `visible` means UIA
`IsOffscreen == False`, not an independent occlusion or pixel-visibility proof.

The default time budget is two seconds, configurable up to five. It is a
post-read acceptance limit, not cancellation of a blocking OS read. Equal
endpoint observations do not prove an atomic capture or exclude a transient
change followed by restoration. This bounded consistency assertion is the
meaning of `coherent_complete_projection`; the name must not be interpreted as
an OS transaction guarantee. Action-time re-observation, grounding, policy,
approval, budgets, WAL and the sole desktop boundary remain required.

The SHA-256 binding covers the exact task, three stamped results and image hash
using the consumer's `gui-observation-projection-v1` domain. It detects accidental
mixing or mutation; it is not a signature or an authorization token. Every
returned bundle and compiled downstream proposal has `execution_authorized=false`.

## Reproduction and evidence ceiling

Use the Runtime development environment; no model or live desktop is needed:

```powershell
.venv\Scripts\python.exe -B -m pytest tests/agent/test_gui_observation.py -q
.venv\Scripts\python.exe -B scripts/validate_gui_observation_handoff.py --consumer-root C:\Users\Alienware\raml-diagnostic-v1
```

The second command requires the consumer at
`924c07db6c72cbcae4ae941d1191272f0ffc9e14` and verifies both consumer source
hashes before importing it. It feeds a synthetic one-pixel screenshot plus real
Runtime result types and Session-generated refs through the existing projector
and native proposal compiler. Four missing fact groups become zero; a simulated
native click becomes an inert `click_ref`; image/task/result mutations and a
changed current epoch are rejected. No local model is invoked and no click runs.
The Windows-reader tests replace every OS interaction with fake objects.

Historical model-side reports pin the earlier Runtime source. They remain
unchanged historical evidence and are not refreshed to conceal source drift.
This receipt proves interface compatibility at the stated consumer revision,
not model quality, live collection, workflow success, save correctness, or
Chrome-to-Word end-to-end readiness. Sequencing belongs to `PROJECT_STATUS.md`.
