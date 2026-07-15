# Full Agent Safety MVP Implementation Plan

> **Status: in progress.** The dual-provider text/screenshot workflow, explicit memory,
> state/trace baseline, E1/E2 baseline, and fake-verified approved-action
> orchestration and initial-checkpoint crash recovery are implemented. Isolated action smoke,
> broader resumable state, and release review remain; offline CI and local
> release preflight are active.
> This work does not weaken the MCP server's runtime safety guarantees.

## Implementation audit (2026-07-14)

The repository currently provides a tested foundation, not a completed safety
MVP. The status below is based on source inspection plus the current offline
preflight and CI evidence. Exact pass/skip counts belong in each generated
report rather than this audit because the suite changes with every milestone.

| Area | Current implementation | Evidence / limitation |
| --- | --- | --- |
| Canonical contract | Implemented | Provider-neutral calls, results, usage, approval records, ledger events, budgets, recovery status, and MCP descriptors live in `types.py`. This is a data contract, not a persisted execution state machine. |
| Task planning | Contract, private persistence, one-shot Planner port, isolated OpenAI/Claude adapters, pure Executor preflight, and bounded non-executing session implemented; runtime not connected | `planning.py` provides a strict 64 KiB/16-step JSON compiler and pure transitions. `plan_store.py` adds strict private CAS snapshots under the application RunLock. The one-shot OpenAI/Claude Planner path remains tool-free and non-executable. `executor.py` revalidates exact run/task/registry/snapshot state and reconstructs only fresh `requested` calls. `BoundedExecutorSession` keeps one live store lock, caps observation preparation at four, allows one outstanding call, requires lossless monotonic ledger state and exact correlated result/transition evidence, and closes on unknown outcome while leaving that step `in_progress`. It has no external ports and performs no policy, approval, recovery, trace, MCP, or execution. Runtime consumption remains a separate milestone. |
| Reviewed desktop tools | Implemented | All eight tools have fixed host/MCP schemas, argument validation, discovery mismatch checks, result validation, sensitivity metadata, and tests. |
| Existing server safety baseline | Implemented | Typed-text audit records retain length/presence metadata rather than raw text; regression tests cover success and failure paths. Existing gate, human-activity, confirmation, E-stop, and audit architecture remains unchanged. |
| Configuration and CLI | Implemented experimental slice | Strict validation, safe child environment, user-local paths, run lock, offline commands, dual-provider runs, explicit memory, trace inspection, and opt-in console-approved actions are wired. |
| Local stdio MCP bridge | Implemented | Fixed direct child launch, bounded/redacted transport, paginated discovery verification, lifecycle/generation handling, timeout and cancellation classification, no automatic replay, bounded text/PNG conversion, and real harmless stdio fixture tests. |
| Host policy | Implemented fake-verified action baseline with one shared call boundary | Read-only default, tool/side-effect budgets, current-generation grounding, digest/identity-bound local approval, serialized calls, re-observation, verification requirement, and unknown-outcome stop are implemented. The provider loop delegates every normalized request to the sole Runner MCP dispatch site, which also retains write-ahead and result validation; a future Executor must reuse this boundary. `type` remains denied; isolated desktop validation remains. |
| OpenAI / Claude providers | Implemented text/image/action-schema slice | Both adapters default to text and bounded screenshot observation tools, encode provider-native image continuations, and enforce configurable canonical-JSON request byte caps before SDK calls. They expose `activate_window`, `click`, and `key` only in approved mode; `type` remains unadvertised. Wire fixtures, CLI routing, and gated fake-MCP E3 exist. |
| Workflow and recovery | Partial | Observe/approve/act/reobserve/answer executes with phase checkpoints. Opt-in continuation v5 can chain 1-4 reviewed read-only recovery calls under one lock, while each external call retains its own durable intent/completion boundary. A fully persisted provider response with no tool calls terminalizes locally with zero external calls and removes the sensitive continuation. Provider-requested actions are correlation-checked and terminalized as a fixed local failure with zero dispatch; completed side effects permit one mandatory `ui_snapshot` and then stop. Unknown outcomes, uncertain dispatches, pending side effects, drift, and unbounded recovery remain fail-closed. |
| Context, memory, and trace | Partial | Provider-only event reduction preserves required atomic groups; explicit SQLite preference/procedure add/list/expiry/delete plus per-run exact-scope retrieval/injection and conservative rejection rules exist. Final outbound requests have deterministic UTF-8 JSON byte gates plus required provider/model context-window and output-reserve gates. Claude can pack oldest complete local tool-use/result pairs without splitting images or committing failed candidates. OpenAI remote continuation stays fail-closed by default, while every request asks for portable encrypted reasoning and continuation v5 carries correlated token usage, exact initial input, ordered canonical provider-output batches, a request-contract v3 digest, and a safe memory marker. Explicit read-only recovery can compile that digest-bound envelope plus its exact persisted tool results into one stateless request; unknown, missing, reordered, mismatched, side-effecting, or over-budget history fails before dispatch, and request failure never falls back or replaces the remote chain. Policy can also stop before another provider call after cumulative reported input tokens reach a configured cap. Atomic safe checkpoints, redacted JSONL, phase validation, per-run token/latency/tool metrics, strict cross-run reports, and `agent trace` exist. Model-generated semantic compression and broader resumable state remain. |
| Evaluation and CI | Partial | Windows/Python 3.11-3.13 CI runs Ruff, full offline tests, separately reported crash-reconstruction and OpenAI stateless-replay E2 gates, thirteen-case workflow E1/E2 JSON reports, canonical manifest verification, wheel build, and clean-install CLI smoke. A local fail-closed preflight repeats those gates with a minimal reviewed child environment, no pip index/input/config discovery or dependencies downloaded during build/install, reconciles public version sources, rechecks clean source and `HEAD` after the gates, and emits sanitized hashes/counts plus UTC and non-path runtime identity. Preflight report v5 binds the crash gate to its 15-case fixture and exact-call runtime matrix and the replay gate to its nine-case fixture. Both record canonical fixture and manifest SHA-256 values plus targeted test counts. Crash recovery verifies exact provider/MCP call counts, local-only final-response success, local-only recovered-action failure, and zero action replay; replay verifies exact wire order, fail-closed transcript rejection, remote-chain preservation, and zero historical MCP dispatch. Provider E3 remains explicit; isolated E4/E5 evidence remains. |

The dual-provider observation slice is runnable but experimental. Documentation
must distinguish it from the complete safety MVP until both providers,
persistence, trace/evaluation gates, approved action verification, and isolated
desktop evidence exist.

## Goal

Build a local, CLI-first Agent Host that can use the existing Windows desktop
MCP server with either OpenAI or Anthropic Claude. The MVP includes:

- OpenAI Responses API and Claude Messages API provider adapters.
- A host-enforced, bounded `observe -> act -> verify` workflow.
- Explicit, local persistent memory with provenance and expiry.
- Sanitized run traces, deterministic offline evaluation, isolated desktop
  smoke tests, and CI gates.

The existing `computer-use-mcp` server remains the only desktop execution
authority. The Agent Host must use it over local stdio; it must not import its
`Session`, Windows driver, or native control code directly.

## Scope and architecture

~~~text
CLI
  -> AgentRunner / Policy / Context / Memory / Trace
      -> OpenAI Responses adapter
      -> Claude Messages adapter
      -> local stdio MCP bridge
          -> computer-use-mcp
              -> Gate / human activity / confirmation / E-stop / audit
              -> Windows UI Automation and Win32 driver
~~~

The Agent Host is provider-neutral above the adapter boundary. It accepts and
emits canonical host types rather than OpenAI or Anthropic SDK objects:

- `ModelTurn`: model text, normalized tool calls, usage, and provider response
  identifier.
- `ToolCall`: call identifier, name, validated arguments, and provider-neutral
  status.
- `ToolResult`: structured success or error result, plus sanitized text and
  image content when appropriate.
- `RunState`: task, policy version, observation epoch, budgets, event log, and
  recovery status.

The model-specific adapters compile the same reviewed tool registry into each
provider's wire format. OpenAI uses function calls and matching
`function_call_output` items; Claude uses `tool_use` and matching `tool_result`
blocks. The common runner never compares natural-language output between
providers; it evaluates canonical tool traces and safety outcomes instead.

The project will use its own local stdio MCP client. Anthropic's remote MCP
connector cannot connect directly to this server because it is a local stdio
server; Anthropic documents client-side MCP helpers for this local-client use
case. See [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
and [Claude MCP connector](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector).

## Planned package boundary

~~~text
src/computer_use_agent/
  __init__.py
  cli.py                 # run, remember, eval, and trace commands
  config.py              # file and environment configuration; no stored keys
  types.py               # canonical provider-neutral data types and ports
  planning.py            # non-executable TaskPlan contract and candidate compiler
  planner.py             # one-shot untrusted plan-candidate provider port
  plan_store.py          # private atomic non-executable plan snapshots
  executor.py            # pure non-authorizing plan-step preflight compiler
  runner.py              # bounded observe -> act -> verify state machine
  policy.py              # action authorization, budgets, retries, and run lock
  approvals.py           # console/native approval port
  tool_registry.py       # reviewed schemas for the current eight MCP tools
  desktop_mcp.py         # local stdio client, tool validation, result conversion
  context.py             # canonical event ledger and context-budget reduction
  memory.py              # explicit-only local SQLite memory store
  trace.py               # redacted JSONL traces and reproducibility metadata
  providers/
    openai.py            # Responses API adapter
    anthropic.py         # Claude Messages API adapter
tests/agent/
evals/cases/
docs/AGENT.md
docs/EVALUATION.md
agent.example.toml
~~~

The MCP server package remains independent of the optional provider SDKs.
Provider dependencies and their console entry point should be optional package
extras so an MCP-only installation remains lightweight and model-agnostic.

## Security invariants

The following rules are non-negotiable for the MVP:

1. The host can add restrictions but cannot bypass the MCP server's allowlist,
   human-activity checks, confirmation, E-stop, or audit behavior.
2. The default host mode is read-only. `activate_window`, `click`, `type`, and
   `key` require explicit host approval in the first release.
3. The host executes at most one side-effecting desktop call at a time. A model
   request for multiple calls is rejected or serialized through the same policy
   decision; it is never executed in parallel.
4. Every state-changing action invalidates desktop grounding. A new observation
   is required before the next action.
5. A timeout, crash, or provider failure after dispatch is an
   `unknown_outcome`; the host must not replay the action automatically.
6. The tool registry is a fixed, reviewed allowlist of the current eight MCP
   tools. Unknown tools, invalid schemas, malformed arguments, and server tool
   set mismatches fail closed.
7. The MCP child gets a fixed executable, argv, cwd, and constrained
   environment. It is not launched through a shell and does not receive model
   provider API keys.
8. Prompt text, tool output, UI text, and memories are untrusted data. They
   cannot alter host policy or grant permissions.

Before the Agent Host is introduced, the current server audit path must be
hardened: typed text must be represented only by safe metadata such as length
and field presence, never a truncated prefix. The existing server receives the
raw `text` argument before it writes an audit record, so truncation alone is
not sufficient protection.

## Context and persistent memory

The host owns a canonical event ledger:

~~~text
user task -> assistant turn/tool call -> tool result -> assistant turn
~~~

Provider-specific conversation identifiers may be used as an optimization, but
correctness and recovery must remain possible by replaying the canonical log.
Context reduction must preserve policy decisions, call/result pairs, the most
recent verified observation, and an explicit truncation marker.

Persistent memory is opt-in and local. The MVP stores only user-confirmed
preferences or verified app procedures, each with source, scope, expiry, and
deletion support. It must not store screenshots, UI references, passwords,
OTP values, API keys, raw typed text, or unverified content derived from the
desktop. Memory cannot authorize an action.

State files belong under a user-local application directory rather than the
repository. Run traces and long-term memory use separate stores.

## Phased implementation plan

| Phase | Dependencies | Deliverables | Exit gate |
| --- | --- | --- | --- |
| 0. Contract and threat model | None | Canonical types, ports, tool-registry specification, trust boundaries, configuration model, and acceptance matrix | Both providers can be described through the same `ToolCall`/`ToolResult` contract; all eight tools have reviewed schemas. |
| 1. Existing safety baseline | 0 | Typed-text audit redaction, regression tests, and host safety configuration policy | No raw typed text, screenshot payload, or API key can appear in server audit or host trace fixtures. |
| 2. Agent foundation | 0-1 | Package skeleton, CLI, configuration, fakes, `AgentRunner` ports, and local run lock | CLI help and all unit tests run without a provider key, MCP child, or desktop side effect. |
| 3. Desktop MCP bridge | 2 | stdio child lifecycle, tool discovery verification, static registry, schema validation, and text/image result conversion | Unknown tool, bad arguments, timeout, and child restart produce structured fail-closed outcomes. |
| 4. OpenAI provider | 2-3 | Responses adapter, function-schema compiler, sequential tool loop, and opt-in live integration test | A fixture proves `function_call` -> matching `function_call_output`; all calls pass common policy and trace checks. |
| 5. Claude provider | 2-3 | Messages adapter, Claude tool-schema compiler, tool-result continuation loop, and opt-in live integration test | A fixture proves `tool_use` -> matching `tool_result`; it passes the same adapter contract suite as OpenAI. |
| 6. Workflow, context, and memory | 3-5 | Observation freshness, approval flow, budgets, recovery state, context reducer, and explicit SQLite memory | Refs do not survive MCP restart; actions require re-observation; memory rejects secrets, UI refs, and untrusted promotion. |
| 7. Trace, evaluation, and CI | 1-6 | Redacted trace store, deterministic evaluation cases, adversarial safety suite, isolated desktop smokes, and CI jobs | Offline checks are green; safety escapes are zero; both providers pass low-risk isolated smoke scenarios. |
| 8. Release review | 7 | Documentation, configuration example, versioning, release checklist, and operator guide | All release gates below pass and a human reviews trace samples and model disclosures. |

## Provider adapter contract

The adapters have different wire protocols but identical host behavior:

| Concern | OpenAI adapter | Claude adapter | Host rule |
| --- | --- | --- | --- |
| Tool definition | Function with JSON Schema parameters | Tool with JSON Schema input schema | Compile from one reviewed registry. |
| Tool request | Function call with JSON arguments | `tool_use` block with structured input | Validate before dispatch. |
| Tool result | `function_call_output` linked by call identifier | `tool_result` linked by tool-use identifier | Preserve the exact identifier and record a canonical result. |
| Multiple requests | Request sequential calls and enforce host serialization | Enforce host serialization regardless of model behavior | One desktop action at a time. |
| Provider failure | Return normalized provider error | Return normalized provider error | Do not automatically fail over during an active run. |

Automatic provider switching is deliberately out of scope. A provider error after
an action is dispatched produces `unknown_outcome` and requires human
re-observation. A new run may select a different provider.

## Evaluation and release gates

Evaluation is trace-based, not wording-based. Each case records an input,
initial state, expected tool trace, and expected safety outcome.

| Level | Environment | Required checks |
| --- | --- | --- |
| E0: contracts | Fully offline | Schema validation, adapter normalization, context reduction, audit redaction, and dispatcher behavior. |
| E1: deterministic workflow | Fake model and fake desktop tools | Observe-select-act-verify, stale refs, tool failures, and exact expected action traces. |
| E2: adversarial safety | Fake model and fake desktop tools | Prompt injection, malformed/unknown calls, human-active, gate denial, E-stop, denied approval, repeats, and parallel calls. Zero unauthorized actions are allowed. |
| E3: provider integration | Opt-in provider API plus fake MCP server | One low-cost read -> tool -> result -> final-answer cycle per provider. |
| E4: isolated desktop smoke | Disposable Notepad or VM, narrow allowlist, explicit approval | Both providers complete read-only and low-risk action scenarios with post-action verification. |
| E5: release regression | CI plus scheduled/manual isolated smoke | Freeze successful and failed traces; rerun after prompt, schema, adapter, or policy changes. |

CI must run E0-E2 without provider credentials or desktop side effects. E3 is
explicitly opt-in. E4 and E5 must run only against an isolated environment,
never a developer's active desktop.

## Definition of done

The safety MVP is complete only when all of the following are true:

- A local CLI can start one safe Agent run with either configured provider.
- The same canonical tool registry, policy, context ledger, memory rules, and
  trace format work for both providers.
- A state-changing action cannot occur without host approval, MCP safety
  checks, and a subsequent verification observation.
- All persistent data is redacted by design and memory is explicitly managed.
- Contract, workflow, and adversarial evaluation suites pass deterministically.
- Each provider passes an isolated, low-risk desktop smoke scenario.
- Operator documentation explains credentials, data disclosure, approvals,
  limitations, recovery, and how to disable the host.

## Deliberately deferred work

The first release does not include a web UI, multi-agent handoffs, automatic
provider arbitration, arbitrary remote MCP servers, shell/browser/code-execution
tools, background desktop concurrency, automatic approval, vector retrieval,
automatic memory extraction, multi-monitor grounding, macOS/Linux drivers,
cloud trace storage, or user accounts.

## Estimate and sequencing

The complete safety MVP is estimated at 16-24 focused engineering days. A
practical sequence is:

1. Complete phases 0-3 to establish a safe, testable provider-neutral core.
2. Complete the OpenAI adapter and offline evaluation baseline.
3. Add the Claude adapter against the same contract tests.
4. Add context, explicit memory, trace, and recovery behavior.
5. Finish adversarial tests, isolated desktop smoke, CI, and release review.

The highest-risk schedule items are desktop side-effect testing and the desired
approval granularity, not the basic provider SDK integrations.

## Immediate implementation order

To prioritize runnable capability, tests, and operator documentation without
refactoring the existing safety architecture, use these increments:

1. **Read-only vertical slice:** implement one provider adapter first, the
   bounded model/tool continuation loop, budget accounting, observation
   freshness, sanitized in-memory ledger events, and a real `agent run`. Keep
   all action tools denied. Add fixture-based adapter contract tests and one
   fake-MCP CLI integration test.
2. **Second provider on the same contract:** add the other adapter without
   branching runner behavior. Run the identical normalization, call-ID,
   multiple-call serialization, timeout, and disclosure tests against both.
3. **Deterministic workflow evaluation:** create `evals/cases` and E1/E2 tests
   for exact canonical traces, stale refs, malformed/parallel calls, injection,
   denied approval, gate/E-stop/human-active results, and unknown outcomes.
4. **Run persistence and inspection:** add explicit transition validation,
   atomic state checkpoints, conservative resume rules, redacted JSONL traces,
   and `agent trace <run_id>`. A dispatched uncertain action must never resume
   by replaying it.
5. **Approved actions:** connect the local approval port and enforce one action
   at a time plus mandatory post-action observation. Validate first with fakes,
   then only in an isolated Notepad/VM smoke environment.
6. **Context and explicit memory:** add budget-aware context reduction and the
   opt-in SQLite store after the runnable workflow and traces are stable.
7. **Release documentation and CI:** document credentials, disclosure,
   configuration, recovery, trace inspection, limitations, and disablement;
   gate E0-E2 in CI and keep provider/desktop tests opt-in and isolated.

Planner-Executor expansion, queues/workers, multi-agent delegation,
OpenTelemetry, Redis, FastAPI, and Docker remain later enhancements. They must
not delay the read-only vertical slice or be described as implemented before
executable evidence exists.
