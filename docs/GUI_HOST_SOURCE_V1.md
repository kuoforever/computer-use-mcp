# GUI Host and Session source v1

Status: implemented for offline integration only. Date: 2026-09-07.

`GDA-GUI-002` connects the observation coordinator to real Runner bookkeeping
and real MCP Session refs. The OS-facing driver and desktop contents are fake
in all retained tests. There is no model invocation, live desktop evidence,
action dispatcher, CLI activation or automatic rich export.

## Concrete path

`collect_host_gui_observation(runner, task)` validates/detaches the task, obtains
the ordinary application run lock through `AgentRunner.prepare`, starts the
existing `RunRecorder`, discovers/verifies the existing tool registry and
collects one observation bundle. Its private `_RunnerSource` sends only the
fixed `list_windows`, scoped `ui_snapshot`, `screenshot` sequence through
`AgentRunner._execute_requested_call_boundary`. No second `call_tool` dispatch
site was added to the Runner. UUID call identities identify real Host requests;
no fictitious provider turn is consumed or recorded.

Generation comes from `StdioDesktopMCP.generation`; epoch and tool budgets come
from the returned `RunState` after the ordinary Runner result bookkeeping.
The existing boundary still performs schema, policy, budget, grounding, recorder
and outcome handling. Two metadata reads bracket that fixed sequence; they are
bounded auxiliary resource reads, not additional model/tool ledger calls.

The MCP server can register `gui-observation://session/{scope}` only through
explicit `build_server(gui_observation_enabled=True)` construction. It defaults
to false and has no CLI or environment toggle. It is a read-only MCP resource,
not a model-advertised tool. A client with access to an explicitly enabled
server can discover/read it: Host-only routing is an integration boundary, not
a separate cryptographic authentication mechanism.

`Session.inspect_gui_observation` reads its own driver's strict metadata and
its own native/ref/scope tables. Its bounded version-1 receipt carries the
verified window/control state and only matching, explicitly scoped Session
refs. `StdioDesktopMCP.inspect_gui_metadata` reads this resource over the same
discovered client session, under the same operation lock, without reconnect or
retry. URI, MIME type, content count, exact JSON fields, duplicate keys, size,
scope, geometry, boolean types and ref identity sets are checked. A failed
resource read invalidates the session instead of returning partial facts.

## Failure, privacy and lifecycle boundaries

The resource is limited to 64 controls/refs and 65,536 UTF-8 bytes, with a
five-second maximum client read timeout. The coordinator retains its separate
two-second default / five-second maximum elapsed acceptance budget. This is
endpoint consistency, not atomic UI capture, hard cancellation of synchronous
OS reads, occlusion proof or action authorization.

This narrow Host entry rejects enabled privacy/continuation or attached
cooperative-control/presence/progress ports before acquiring resources. It must
not silently bypass those lifecycles. Their integration, a live entry point,
and a model client remain outside this slice. The plain observation bundle
stays in memory; normal redacted trace/checkpoint output contains no window
title, control name, screenshot or raw result text. Session resource contents
are local sensitive observations and must never enter Full Cycle Lane A.

The Host closes the connection before recording successful collection and
releases the application lock on success, metadata failure, budget rejection,
cancellation and cleanup failure. Existing UNKNOWN_OUTCOME evidence is never
rewritten as a clean cancellation or replayed. `SUCCESS` here means only that
one observation bundle was collected and its connection closed; it does not
mean that a desktop task or Chrome-to-Word workflow succeeded.

## Reproduction

```powershell
.venv\Scripts\python.exe -B -m pytest tests/agent/test_gui_host_source.py tests/agent/test_gui_observation.py -q
.venv\Scripts\python.exe -B scripts/validate_gui_host_handoff.py --consumer-root C:\Users\Alienware\raml-diagnostic-v1
```

The tests use real `AgentRunner`, `RunRecorder`, `StdioDesktopMCP`, MCP SDK
client/server memory streams, `build_server`, `Session` and protocol conversion.
No native desktop methods or process launch run. Negatives include disabled
resources, metadata changes, bad wire data, budget exhaustion, actual MCP
session reconnection, timeout, cancellation and cleanup failure.

The cross-repository script pins model consumer
`42428dde8b706be9d70003358c183d16ab057e9a` and both unchanged consumer source
hashes. It projects the real-code/fake-desktop bundle and compiles one simulated
native click into an inert `click_ref`. All execution/model/live flags remain
false. Older scripts/reports keep their original pins; use a checkout at each
documented pin when reproducing historical receipts. Sequencing remains owned
by `PROJECT_STATUS.md`.
