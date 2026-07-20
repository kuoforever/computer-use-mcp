# Telemetry contract

> **Status: port implemented, exporter not.** The telemetry port and its no-op
> default exist and the Agent run and tool boundary are instrumented. No
> OpenTelemetry SDK, exporter, collector, or dashboard is part of this
> repository yet. Treat every OTLP reference below as **planned**.

## Three kinds of data, three authorities

The most common way to get this wrong is to let a trace answer a question it
cannot answer. This project keeps three data kinds separate and does not let
them impersonate each other:

| Data | Question it answers | May be lost? |
| --- | --- | --- |
| **Audit** | Which operation boundary was crossed, under whose authorization | No |
| **Durable state** (WAL, ledger, checkpoint) | What may be resumed, and what must stop | No |
| **Telemetry** | How long things took, how often they fail, in aggregate | **Yes** |

**Telemetry is never an authority.** A span is not evidence that a side effect
happened. A missing span is not evidence that one did not. Recovery,
completion, and replay decisions read durable state and nothing else.

This is enforced structurally, not by convention: `telemetry.py` has no
knowledge of run state, and every call the runner makes goes through a wrapper
that swallows exceptions. A failing exporter degrades observability and changes
nothing else. See `tests/agent/test_runner_telemetry.py`, where a port whose
every method raises still produces an identical run outcome.

## Span hierarchy

Implemented today:

```
agent.run                      root, one per run
  tool.boundary                one per requested tool call
```

Planned, in roughly this order:

```
agent.run
  agent.prepare
  desktop.discover_tools
  provider.turn                one per model turn
  tool.boundary
    policy.evaluate
    grounding.validate
    approval.wait              only when approval is required
    continuation.write_intent
    mcp.dispatch
    tool.result_validate
    post_action.observe        side effects only
    checkpoint.persist
  recovery.classify            resume paths only
  report.project
```

`tool.boundary` is deliberately observed **from the call site**, not from
inside `AgentRunner._execute_requested_call_boundary`. That method is the sole
authoritative path from a request to MCP dispatch, and a repository test asserts
that policy, grounding, budget, approval, write-ahead, dispatch, and result
validation all remain visible in one function. Telemetry must not reshape the
path it observes, so it wraps the call instead of splitting it.

## Attributes

Attribute names are an **allowlist** in `telemetry.ALLOWED_ATTRIBUTES`. An
unreviewed name is rejected rather than passed through, so recording something
new is a deliberate review step rather than an accident.

Values may be a bool, an int, a short single-line string (a fixed code), or a
tuple of such strings. Strings are capped at 64 characters, because telemetry
carries codes, not content.

| Attribute | Example | Rule |
| --- | --- | --- |
| `run.phase` | `running`, `completed`, `failed` | allowed |
| `provider.name` | `openai`, `anthropic` | allowed; never a key or a request |
| `tool.name` | `ui_snapshot`, `click` | allowed |
| `tool.effect` | `observation`, `side_effect` | allowed |
| `policy.disposition` | `allow`, `deny`, `approval` | allowed |
| `dispatch.certainty` | `not_dispatched`, `dispatched`, `unknown` | allowed |
| `result.status` / `result.code` | fixed reviewed codes | allowed; never a message |
| tool arguments | — | only a `SafeArgumentSummary` shape: key names and counts |
| `duration.ms`, `tokens.*`, `bytes.*` | integers | allowed |
| campaign or item identity | digest or stable non-sensitive key | never business content |

**Never recorded:** task text, model output, typed text, OCR text, window
titles, page content, full URLs or query strings, security tokens, API keys, or
any error message body. A second guard rejects a reviewed name that later drifts
toward content — a name containing `text`, `prompt`, `task`, `url`, `title`,
`secret`, or `credential` is refused even if someone adds it to the allowlist.

Tests assert the **absence** of content, not only the presence of structure:
`test_spans_carry_no_task_or_desktop_content` runs a real bounded workflow and
fails if the task, the model's answer, or the tool result text appears in any
recorded attribute.

## Metrics

Planned counters and histograms, none implemented yet:

- `agent_runs_total{status, provider, mode}`, `agent_run_duration_ms`
- `provider_turn_duration_ms`, `input_tokens_total`, `output_tokens_total`
- `mcp_tool_calls_total{tool, status, effect}`, `mcp_tool_duration_ms`
- `policy_denials_total`, `approval_requests_total`, `approval_wait_ms`
- `dispatch_uncertain_total`, `recovery_attempts_total`, `recovery_success_total`
- `campaign_items_committed_total`, `duplicate_prevented_total`
- `checkpoint_write_duration_ms`, `wal_write_failures_total`

Metric labels must stay low-cardinality. A run id, a URL, or an error message is
never a label.

## Default behavior

The default port is `NoOpTelemetry`. It allocates one shared span object, opens
no connection, performs no attribute validation, and retains nothing. An
offline CLI invocation, the test suite, and the release preflight therefore
never depend on external infrastructure, and no configuration is required to
stay silent.

`InMemoryTelemetry` exists for tests. It records span structure and validates
every attribute strictly, which is what makes the privacy assertions meaningful.

## Not implemented

- No OpenTelemetry SDK dependency, and no `observability` optional extra.
- No OTLP, Jaeger, Tempo, Prometheus, or Grafana wiring, and no dashboard.
- No metrics: `record_metric` exists on the port and is not yet called by the
  runner.
- No spans below `tool.boundary`, and no `provider.turn` or recovery spans.
- No trace/run correlation identifier is exported, because nothing exports yet.

When an exporter adapter is added it must live outside the domain, behind an
optional dependency, disabled by default, and it must not become a recovery
authority.
