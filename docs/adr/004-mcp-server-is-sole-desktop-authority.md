# ADR-004: MCP Server is the sole desktop execution authority

Status: Accepted
Date: 2026-07-21

## Context

Desktop actions (mouse, keyboard, window focus, screenshot) touch the shared
Windows session. The Host has three obvious ways to reach them:

1. Through the MCP server, over stdio, one tool call at a time
2. Directly from the Host process, importing the driver in-process
3. From any component (planner, supervisor, worker, campaign) that wants to
   skip the stdio hop for performance or convenience

## Decision drivers

- Every side-effecting call must land in the same WAL, run under the same
  approval and grounding rules, and be attributable to one Agent Run
- A second path multiplies audit surface: a leak, a bypass, or a divergence in
  gate / safety logic between paths is a whole class of bug
- The cross-process boundary is a feature, not overhead: it forces
  serialization and prevents a rogue in-process import from acquiring input
  focus without the runner noticing

## Considered options

### 1. Multiple execution paths for performance

*Rejected.* The stdio hop costs milliseconds. A GUI action takes tens of
milliseconds to observe and confirm. The performance win is imaginary; the
audit loss is real.

### 2. Read-only driver access outside MCP (e.g. screenshots for planning)

*Rejected.* A screenshot is bounded read-only state that other components
would like. But the rule survives only if there are zero exceptions — "just
this one more read" is how the bypass grows. Read-only surfaces belong in MCP
tools with their own schema and audit.

## Decision

**Every desktop-touching call goes through the project's stdio MCP server, over
the Driver Contract v1.0.0, and only from the Agent Runner's WAL dispatch
site.** Planner, Supervisor, Campaign runtime, Recovery, and future Operator
UI must not import the driver directly.

## Consequences

- One grep answers "who could have moved the mouse": the runner's dispatch
  boundary
- CI runs `check_docs_consistency.py` so that a new tool is a documented
  surface, not an ad-hoc import
- A future remote desktop or VM worker inherits this rule by construction:
  remote MCP transport swaps the transport, not the authority model
- Cost: a new desktop capability means shipping a new MCP tool, not importing
  the driver from a convenient place. This is by design.

Related: [ADR-001](001-uncertain-dispatch-is-never-auto-replayed.md),
[ADR-003](003-custom-durability-vs-workflow-engine.md).
