# Provider E3 evidence

> **Status: maintained sanitized provider evidence.** This page records reviewed
> opt-in E3 outcomes without credentials, prompts, model prose, tool output,
> provider response identifiers, or user-local state paths. A provider row
> applies only to the exact commit and bounded test cases shown below.

## Current provider matrix

| Provider | Ordinary Agent cycle | Bounded `plan run` cycle | Evidence state |
| --- | --- | --- | --- |
| OpenAI | `PASS` | `PASS` | retained |
| Anthropic Claude | `PASS` | `PASS` | retained |

Together these records complete the bounded dual-provider E3 gate. They do not
prove desktop behavior, authorize any new runtime surface, or establish that
every model offered by either provider is compatible with the current adapters.

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

## 2026-07-17: Anthropic Claude bounded fake-MCP E3

| Field | Sanitized reviewed value |
| --- | --- |
| Commit | `2ba02f6` |
| Provider | Anthropic Claude Messages API |
| Explicit model ID | `claude-haiku-4-5-20251001` |
| Review time (UTC) | `2026-07-17T13:29:00Z` |
| Exact pytest command | `.\.venv\Scripts\python.exe -m pytest tests\agent\test_anthropic_integration.py -m anthropic_integration -q` |
| Fixed outcome | `2 passed in 14.57s` |
| Ordinary case | one read -> tool -> result -> final-answer cycle passed |
| Planner/Executor case | exact bounded observation-only `plan run` CLI cycle passed |
| Execution boundary | harmless fake stdio MCP child; zero side effects; no Windows driver or real desktop |

The tested commit is the exact evidence-producing commit and has the same tree
as merge commit `ef883ea` on `main`. The run used the explicit opt-in flag, a
credential supplied only through the operator environment, and the reviewed
model ID above. The committed record contains no credential, task/final text,
tool output, provider identifier, raw traffic, or local state artifact.

### Model compatibility boundary

A separate bounded attempt on the same tested commit with explicit model ID
`claude-sonnet-5` produced `1 passed, 1 failed in 21.10s`: the exact `plan run`
case passed, while the ordinary Agent cycle failed closed with
`ANTHROPIC_RESPONSE_INVALID` when the model returned an unsupported `thinking`
content block. This is retained as a model-specific compatibility gap, not as
a failure of the passing Claude E3 record above. Supporting that block requires
a separately reviewed runtime change that preserves Claude continuation and
signature semantics; it is outside this evidence-only change.

## Promotion boundary

Both providers now have retained passing records for the two bounded fake-MCP
cases, so the dual-provider E3 rows may move from `PARTIAL` to `YES`. E4 remains
separate and requires the isolated desktop runbook. The Sonnet 5 compatibility
gap above also remains separate from both the completed E3 gate and E4.
