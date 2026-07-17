# Provider E3 evidence

> **Status: maintained sanitized provider evidence.** This page records reviewed
> opt-in E3 outcomes without credentials, prompts, model prose, tool output,
> provider response identifiers, or user-local state paths. A provider row
> applies only to the exact commit and bounded test cases shown below.

## Current provider matrix

| Provider | Ordinary Agent cycle | Bounded `plan run` cycle | Evidence state |
| --- | --- | --- | --- |
| OpenAI | `PASS` | `PASS` | `PARTIAL` at the dual-provider capability level |
| Anthropic Claude | `NOT RUN` | `NOT RUN` | pending |

The OpenAI result establishes one provider slice. It does not complete the
dual-provider E3 gate, prove desktop behavior, or authorize any new runtime
surface. Anthropic was not run because a funded credential was not available;
`NOT RUN` is not a failure result.

## 2026-07-17: OpenAI bounded fake-MCP E3

| Field | Sanitized reviewed value |
| --- | --- |
| Commit | `0acab3b` |
| Provider | OpenAI Responses API |
| Explicit model ID | `gpt-5.6-terra` |
| Review time (UTC) | `2026-07-17T10:39:59Z` |
| Exact pytest command | `.\.venv\Scripts\python.exe -m pytest tests\agent\test_openai_integration.py -m openai_integration -q` |
| Fixed outcome | `2 passed in 17.53s` |
| Ordinary case | one read -> tool -> result -> final-answer cycle passed |
| Planner/Executor case | exact bounded observation-only `plan run` CLI cycle passed |
| Execution boundary | harmless fake stdio MCP child; zero side effects; no Windows driver or real desktop |

The run used the explicit opt-in flag, a credential supplied only through the
operator environment, and the reviewed model ID above. The committed record
contains no credential, task/final text, tool output, provider identifier, raw
traffic, or local state artifact.

## Promotion boundary

The next E3 gate is the same two bounded cases through Anthropic Claude with an
explicit reviewed model ID. Only after both providers have retained passing
records may the dual-provider E3 rows move from `PARTIAL` to `YES`. E4 remains
separate and requires the isolated desktop runbook.
