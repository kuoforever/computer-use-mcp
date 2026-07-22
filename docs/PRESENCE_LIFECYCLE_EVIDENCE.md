# Host presence lifecycle on-device evidence

> **Status: ordinary Agent lifecycle smoke retained 2026-07-22.** This record
> demonstrates the default-off Host coordinator driving the real Win32 halo
> from durable `AgentRunner` phases. It does not establish broader runtime,
> real-provider, real-MCP-child, multi-monitor, or abrupt-process coverage.

## Exact scope

- Implementation commit: `ab7b033580783e6dc9f174c53944e7d617a88fed`
- Command:
  `\.venv\Scripts\python.exe scripts\smoke_presence_lifecycle.py`
- Host path: production `AgentRunner` and `RunRecorder`, with deterministic fake
  provider/MCP/approval ports and the production `RunPresenceCoordinator`,
  `PassivePresenceWindow`, and `Win32PresenceWindowApi`.
- Desktop scope: one operator-approved interactive Windows primary display.
- Safety scope: observation-only fake calls; the probe changed only its own halo
  and temporary user-local run records.

## Retained result

~~~text
RESULT: PASS (foreground unchanged at 0x10614; durable labels ['Observing', 'Planning', 'Planning', 'Executing', 'Observing', 'Planning', 'Planning']; one HWND reused; terminal success and MCP ABORTED destroyed the halo)
~~~

The ordinary successful run produced its fixed presentation only after each
corresponding checkpoint publish, reused one native HWND across all nonterminal
phases, returned `Complete`, and destroyed the window at `SUCCESS`. A second
ordinary run returned a synthetic, schema-valid MCP `ABORTED` result; the Host
coordinator immediately latched the surface off, and later planning/terminal
notifications did not reopen it. Neither run changed the foreground window.

## Offline controls retained with this gate

- `RunRecorder` invokes the phase observer only after the atomic checkpoint
  succeeds; injected checkpoint failure produces no phase notification.
- observer and native-surface exceptions are swallowed, bounded to one recorded
  coordinator failure, and never alter the run result;
- `ABORTED` and `HUMAN_ACTIVE` latch authority loss before later phase records;
- success, failure, unknown outcome, cancellation, and final cleanup close the
  surface idempotently;
- configuration is strict, default-off, and lazily constructs the Win32 backend
  only for explicit ordinary `run`/`resume` opt-in;
- the lifecycle port accepts only `RunPhase`, E-stop, and release notifications.
  It has no task, target, model text, approval, input, or execution method.

The exact implementation gate passed Ruff, mypy across 79 source modules, and
the full offline suite with `1178 passed, 5 skipped` before the retained desktop
probe.

## Supported claim and remaining boundary

This supports a bounded **Desktop verified** claim for ordinary `run`/`resume`
presence lifecycle integration on the primary display. The MCP result in the
E-stop case was deterministic and fake; it does not prove process-to-process
teardown latency from a live MCP child. Planned execution, campaigns, recovery,
multi-monitor routing, capture technologies beyond the retained standalone
smoke, and abrupt Host termination remain unverified.

The next operator gate is fake-only Decision Card view models through the
existing `ApprovalPort`, without adding an execution path. Broader presence
runtime wiring should be added only when each runtime has a single durable
Host-owned lifecycle source.

Related: [Standalone presence evidence](PRESENCE_WINDOW_EVIDENCE.md),
[Operator experience](OPERATOR_EXPERIENCE.md),
[Capability status](CAPABILITY_STATUS.md), and
[Execution plan](EXECUTION_PLAN.md).
