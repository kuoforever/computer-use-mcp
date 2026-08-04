# Guarded Desktop Agent

**A durable, safety-governed computer-use runtime for Windows.**

Formerly `computer-use-mcp`. The new name distinguishes this repository and
its project-local MCP server from platform-provided computer-use plugins.
Legacy Python import paths, state directories, environment variables, and
console commands remain supported during the compatibility window.

[中文快速开始](README.zh-CN.md) · [Architecture](#architecture) · [Reliability demo](#try-the-reliability-demo) · [Evidence dashboard](docs/CAPABILITY_STATUS.md) · [Documentation](docs/README.md)

> **Status: experimental.** Windows-only, foreground desktop, primary display.
> The English documentation is canonical. Every claim below links to retained
> evidence; read [Honest limits](#honest-limits) before assuming more.

Letting a model click around a desktop is easy. Knowing *what it was allowed to
do*, *what it actually did*, and *what is safe to retry after the process dies*
is the hard part. This project keeps those layers separate: UI Automation,
bounded OCR, and bounded region capture for observation, an explicit policy and approval boundary, a single
desktop execution authority, and durable evidence that outlives a crash.

## What this proves

- **13 reviewed MCP tools** over stdio — `ui_snapshot`, `find`, `list_windows`,
  `screenshot`, `capture_region`, `ocr`, `document_text`, `activate_window`,
  `click`, `scroll`, `drag`, `type`, and `key` — with
  fixed schemas, argument validation, and discovery-mismatch checks.
- **Two provider paths** (OpenAI and Claude) behind one provider-neutral tool
  contract, with [retained dual-provider evidence](docs/E3_EVIDENCE.md).
- **Fresh grounding before a side effect**, and mandatory observation after it.
- **Recovery that never auto-replays an uncertain action.** A dispatch intent
  with no correlated completion stops for a human instead of guessing.
- **Versioned Full Cycle handoff, frozen locally at `324ff2fb`.** An offline CLI
  exports the reviewed runtime manifest and existing redacted run evidence
  without opening provider, desktop, MCP, approval, memory, or continuation
  ports. Lane B rich capture remains deferred and disabled by default.
- **Offline CI** on Windows across Python 3.11–3.13, plus a wheel clean-install
  smoke ([workflow](.github/workflows/ci.yml) ·
  [runs](https://github.com/kuoforever/guarded-desktop-agent/actions/workflows/ci.yml)).

## Measured results

| Result | Evidence |
| --- | --- |
| Forced-crash campaign: killed mid-flight, resumed in a fresh process, **0 duplicate side effects** at every fault point | [Reliability demo](docs/demo/README.md) |
| Reliability benchmark: **30 runs × 100 items**, a crash injected at every named fault point, **0 duplicate side effects**, every item either committed or parked for a human | [Benchmark evidence](docs/benchmark/README.md) |
| Windows activation repair: a five-case regression passed in an isolated VM | [E4 evidence](docs/E4_EVIDENCE.md) |
| Bounded OCR recovered a static tab that UIA omitted, matched to one UIA card | [OCR evidence](docs/BOSS_OCR_EVIDENCE.md) |
| One real BOSS page: 7 stable public job keys, 0 duplicates, 0 retries, 0 tokens — **measured under a contract the discovery-pass ledger has since replaced** | [Discovery evidence](docs/BOSS_CAMPAIGN_DISCOVERY_EVIDENCE.md) |
| Current BOSS discovery contract: 2 distinct on-device passes, 12 stable public job keys, 0 duplicates, 0 provider calls, 0 side effects | [Multi-pass discovery evidence](docs/BOSS_CAMPAIGN_MULTIPAGE_EVIDENCE.md) |
| Clean BOSS item/restart gate: 12 discovered identities, 3 consecutive fresh-run commits, 0 local correction, provider calls, tokens, retryable items, or uncertain items | [Clean item/restart evidence](docs/BOSS_ITEM_RESTART_CLEAN_EVIDENCE.md) |
| Partial BOSS item/restart diagnostic: 3 identity commits, clean post-fix stale-owner recovery, 0 provider calls, with two discovered defects explicitly retained | [Item/restart diagnostic evidence](docs/BOSS_ITEM_RESTART_DIAGNOSTIC_EVIDENCE.md) |

Each record supports **only its own scope**. None is application acceptance, and
none makes this a general-purpose worker. The superseded one-page row remains
for history; the current-contract row proves externally progressed discovery
only. The clean item/restart row proves public-identity processing and fresh-run
handoff, not semantic extraction, provider execution, automatic navigation, or
complete application acceptance.

The [capability dashboard](docs/CAPABILITY_STATUS.md) states, per layer, what is
designed, implemented, offline-verified, provider-verified, desktop-verified,
and application-verified.

For the external model lifecycle, use the bounded Lane A bridge:

~~~powershell
guarded-desktop-agent fullcycle manifest `
  --output C:\absolute\path\runtime-manifest.json

guarded-desktop-agent fullcycle export-run `
  --config C:\absolute\path\agent.toml `
  --run-id <run-id> `
  --output C:\absolute\path\run-export.json
~~~

These files support reliability, safety, failure, sequence, and verifier
evaluation. They intentionally contain no screenshots or raw semantic content
and are not multimodal training episodes. See
[Full Cycle integration](docs/FULLCYCLE_INTEGRATION.md).

## Architecture

```mermaid
flowchart TB
    OP[Operator / MCP client] --> AR
    PA[Provider adapter<br/>OpenAI · Claude] --> AR
    AR[Agent Runner<br/>sole dispatch boundary] --> PG
    PG[Policy · approval · grounding] --> SRV
    SRV[MCP server<br/>SOLE DESKTOP EXECUTION AUTHORITY] --> WD
    WD[Windows driver<br/>UIA · capture · input]
    AR -. evidence .-> DS[(Durable state<br/>checkpoint · WAL · ledger · trace)]
    SRV -. evidence .-> DS
```

**The MCP server is the only path to the desktop.** No provider adapter, plan,
or campaign reaches the driver another way, so every desktop effect crosses the
same policy, grounding, and audit boundary exactly once.

## Why this is different

- **Least privilege by default.** `safe_local` gates actions on the foreground
  window's *process ancestry*, not just its executable name, and yields while a
  human is typing.
- **A ref is intent, not a coordinate.** A `ref` action never silently degrades
  into a center-point click: a stale or occluded element fails loudly instead of
  clicking whatever moved into that pixel.
- **Uncertainty is a first-class state.** Known-completed, known-not-dispatched,
  and unknown are distinct outcomes. Only the first two may proceed on their own.
- **Evidence integrity is maintained by CI, not by hand.** Dated records keep the
  numbers their own run observed; current-state documents are checked against the
  reviewed tool registry.

## Try the reliability demo

Offline: no provider, no desktop, no tokens. Kill a multi-item campaign at a
named fault point and watch a fresh process decide what it may resume.

~~~powershell
# crash between the durable intent and the side-effect result
.\.venv\Scripts\python.exe scripts\demo_reliability_campaign.py `
    --state-dir out\demo --items 5 `
    --fault-point after_dispatch_intent --fault-ordinal 3
~~~

The item whose outcome is unknown is parked as `UNCERTAIN` for a human, the rest
of the campaign still completes, and the command exits non-zero if a duplicate
side effect was ever attempted. The [runbook](docs/demo/README.md) has the full
fault matrix.

## Safety first

Desktop actions can move the pointer, change focus, type text, and invoke UI
controls. Start with `safe_local`, keep the allowlist narrow, and use a
non-sensitive test application such as Notepad.

For project-wide autonomous reviewed actions, set Host policy
`mode = "agentic_actions"` and `require_approval_for_actions = false` while
leaving MCP in `safe_local`. This removes per-action prompts without removing
the allowlist, local-input yielding, budgets, E-stop, audit, or no-replay rules.

`full_control_local` deliberately bypasses the foreground allowlist and
human-activity yielding checks. It still has audit logging and an emergency
stop, but it should be used only when an operator explicitly intends to hand
over the local desktop.

Read [Configuration and safety](docs/CONFIGURATION.md) before enabling action
tools.

## Quick start

Create a virtual environment and install the package:

~~~powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
~~~

Run the server in its default safe mode. The example limits foreground actions
to Notepad:

~~~powershell
$env:CUMCP_ALLOWLIST = "notepad.exe"
.\.venv\Scripts\guarded-desktop-mcp.exe
~~~

Register the executable with an MCP client using that client's stdio-server
configuration. Prefer an absolute executable path so the client does not depend
on an activated virtual environment:

~~~json
{
  "command": "C:\\absolute\\path\\to\\guarded-desktop-agent\\.venv\\Scripts\\guarded-desktop-mcp.exe",
  "env": {
    "CUMCP_ALLOWLIST": "notepad.exe"
  }
}
~~~

The exact configuration wrapper varies by MCP client; the command and
environment values above are the portable part.

The legacy `computer-use-mcp` and `computer-use-agent` entry points remain
aliases for existing integrations. New configurations should use
`guarded-desktop-mcp` and `guarded-desktop-agent`.

## Typical workflow

1. Call `ui_snapshot()` to obtain a flat list of interactive controls and
   their `ref_N` handles, call `ocr(x, y, w, h)` for bounded static text, call
   `capture_region(x, y, w, h)` for one cropped image, or call `screenshot()`
   for whole-display visual inspection.
2. Prefer `click(ref="ref_N")` and `type(text, ref="ref_N")` when UIA
   exposes the target. These use accessibility patterns rather than synthetic
   coordinate clicks.
3. Use `click(x=..., y=...)` only for visual/canvas-style targets that UIA
   cannot expose. Coordinates share the primary-display pixel space shown by
   `screenshot()`.
4. Inspect the returned result and audit log before proceeding with another
   action.

## Tool surface

| Tool | Current behavior |
| --- | --- |
| `ui_snapshot(scope="foreground")` | Returns a flat, capped UIA control list with session-scoped refs. |
| `find(query, scope="foreground")` | Returns a smaller matching subset of a UIA snapshot. |
| `list_windows()` | Lists visible top-level windows, including owned dialogs. |
| `screenshot()` | Returns a PNG of the primary display; it has no MCP region parameter. |
| `capture_region(x, y, w, h)` | Returns a grounding envelope plus a PNG of one explicit primary-display region. |
| `ocr(x, y, w, h)` | Recognizes bounded text runs in one explicit primary-display region. |
| `activate_window(window_id)` | Attempts to restore and activate a listed window; success requires the driver to verify that it became foreground. |
| `click(ref=...)` / `click(x=..., y=...)` | Invokes an accessible control or performs a coordinate click. |
| `type(text, ref=None)` | Sets an accessible value when a ref is supplied, otherwise types into focus. |
| `key(combo)` | Sends a key chord to the foreground window. |

See the exact parameters, ref lifecycle, safeguards, and errors in
[Tool reference](docs/TOOLS.md).

## Honest limits

- **Windows only**, Python 3.11 through 3.13, stdio MCP transport. macOS, Linux,
  multi-monitor grounding, and isolated-worker orchestration are roadmap items,
  not current capabilities.
- **Foreground desktop, primary display.** This is not a background worker.
- **Not a browser automation framework.** Chromium-family UIA trees may be
  incomplete until accessibility content is exposed; verify per application.
- **No application acceptance.** The retained BOSS records cover bounded
  read-only observation of specific pages. They do not support any claim about
  automated applications, messages, or a general campaign worker.
- `screenshot()` captures the primary display only. Multi-monitor coordinate
  support is not yet implemented.
- A shared desktop has one foreground window, pointer, and keyboard focus.
  This project does not promise safe, parallel background control on that
  desktop.
- The VMware helper can start an existing VM, but it does not create the guest,
  start its MCP server, or provide host-to-guest MCP transport.
- Screenshot redaction is title-substring based; it is not comprehensive secret
  detection.

## Documentation

| Need | Read |
| --- | --- |
| Inspect the frozen Full Cycle Runtime baseline or intentionally reopen work | [Project status](PROJECT_STATUS.md) |
| Use this Runtime from the Multimodal LLM Full Cycle project | [Full Cycle integration](docs/FULLCYCLE_INTEGRATION.md) |
| Understand the complete project, every feature family, implementation path, quality attribute, status, and next gate | [Project overview](docs/PROJECT_OVERVIEW.md) |
| Find the right document | [Documentation index](docs/README.md) |
| See what is implemented, verified, or still planned | [Capability status](docs/CAPABILITY_STATUS.md) |
| Run the crash/resume reliability demo and read its fault matrix | [Reliability demo](docs/demo/README.md) |
| Configure modes, safeguards, and environment variables | [Configuration and safety](docs/CONFIGURATION.md) |
| Use the MCP API exactly | [Tool reference](docs/TOOLS.md) |
| Understand the implementation architecture | [Design](docs/DESIGN.md) |
| Understand why a safety rule exists, and what was rejected | [Architecture decision records](docs/adr/) |
| Read a failure analysis with root cause and detection gap | [Postmortems](docs/postmortems/) |
| Know how coding agents are used here and who is responsible | [AI-assisted development](docs/AI_ASSISTED_DEVELOPMENT.md) |
| Implement a platform driver | [Driver Contract](docs/DRIVER_CONTRACT.md) |
| Test or maintain the project | [Development](docs/DEVELOPMENT.md) and [Maintainer handoff](HANDOFF.md) |
| Report a vulnerability, or see what counts as one | [Security policy](SECURITY.md) |
| See what changed in a packaged version | [Changelog](CHANGELOG.md) |
| See completed and future work | [Roadmap](docs/EXECUTION_PLAN.md) |
| Review the planned full Agent Host | [Agent implementation plan](docs/AGENT_IMPLEMENTATION_PLAN.md) |
| Design day-scale resumable work | [Long-running tasks](docs/LONG_RUNNING_TASKS.md) |
| Run staged real-application campaigns and coverage benchmarks | [Application evaluation matrix](docs/APPLICATION_EVALUATION_MATRIX.md) |
| Review the planned one-campaign complete-product showcase | [Universal GUI demo](docs/UNIVERSAL_GUI_DEMO.md) |
| Reduce model context and observation cost | [Token efficiency](docs/TOKEN_EFFICIENCY.md) |
| Review the planned computer-use indicator, progress UI, and decision experience | [Operator experience](docs/OPERATOR_EXPERIENCE.md) |

## License

Licensed under the [Apache License 2.0](LICENSE). You may use, modify, and
distribute this project, including commercially, subject to the license terms.
