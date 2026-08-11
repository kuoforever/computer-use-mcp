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
| Kimi `kimi-k2.6` China | `PASS` | `PASS`, including synthetic image | retained |
| MiniMax `MiniMax-M2.7` China | `PASS` | `PASS`; image-returning tools withdrawn | retained |

Together these records cover four exact provider/model/route candidates. They do not
prove desktop behavior, authorize any new runtime surface, or establish that
every model offered by any provider is compatible with the current adapters.

## 2026-08-11: MiniMax `MiniMax-M2.7` China full fake-MCP E3

| Field | Sanitized reviewed value |
| --- | --- |
| Provider route | MiniMax Anthropic Messages-compatible, `region = "cn"`, fixed `https://api.minimaxi.com/anthropic` |
| Explicit model ID | `MiniMax-M2.7` |
| Exact implementation commit | `2c6a7ccebb09095ef796d25028ab2de6453738cc` |
| Exact pytest command | `.\.venv\Scripts\python.exe -m pytest tests\agent\test_minimax_integration.py -m minimax_integration -q` |
| Fixed outcome | `5 passed in 51.51s` |
| Setup cell | formal `config setup --provider minimax --model MiniMax-M2.7 --region cn` plus `config doctor` passed SDK, isolated credential, executable, working-directory, and 13-tool discovery checks; generated TOML held no secret |
| Ordinary/continuation cell | two real model turns completed one `list_windows` fake-MCP call and its tool-result continuation; the child reported that provider secrets were absent |
| Planner/structured/final cell | exact-schema prompt output was Host-compiled before one fake-MCP observation and one tool-free final response |
| Image-capability cell | the live ordinary request omitted both `screenshot` and `capture_region`; the model returned without a tool call and fake MCP received zero calls |
| Timeout cell | one-second Host provider timeout returned fixed `PROVIDER_TIMEOUT` with zero MCP tool calls |
| Execution boundary | harmless stdio/fake MCP only; zero side effects, Windows Driver calls, real desktop reads, or application actions |

The first five-cell run passed four cases and failed closed at Planner with
fixed `PLANNER_REQUEST_FAILED`. A structure-only diagnostic retained no model
text or reasoning and showed `end_turn` with one signed `thinking` block before
one `text` block. After the Planner accepted only validated reasoning before
exactly one text block, a single-cell rerun reached the fake `list_windows`
call/result/observation sequence and then stopped at fixed
`EXECUTOR_FINAL_UNCERTAIN`. A second structure-only diagnostic showed the same
strict `thinking`-then-`text` response shape at the final boundary.

The bounded repair is shared by Anthropic Messages one-shot Planner/final
adapters: zero or more valid signed `thinking` or opaque
`redacted_thinking` blocks may precede exactly one text block. Reasoning is
validated and discarded; it never enters the compiled plan, final result,
trace, continuation, or error text. Reasoning after text, missing signatures,
duplicate text, tool blocks, unknown content, non-`end_turn`, and malformed
output still fail closed. Ordinary tool continuation remains unchanged and
continues to preserve only strictly validated reasoning blocks for exact replay.

The exact-commit passing rerun used only `MINIMAX_API_KEY` through the operator
environment and did not set a model environment override: the harness itself
hard-pins `MiniMax-M2.7` and fails on another explicit model. One earlier
exact-commit attempt was invalid because the clipboard changed before pytest;
HTTP header construction stopped locally before any provider request. No
credential, clipboard content, prompt, model prose, reasoning, signature, tool
output, response identifier, or local state path is retained here.

This result proves neither MiniMax global nor another MiniMax model. The image
cell proves schema withdrawal for image-returning tools, not MiniMax image
input or a synthetic-image final cycle. The harness used a conservative
128,000-token context setting and does not validate the provider's maximum
context. No real desktop, application, E4, release, sibling provider, or
cross-region credential compatibility is promoted.

## 2026-08-11: Kimi `kimi-k2.6` China full fake-MCP E3

| Field | Sanitized reviewed value |
| --- | --- |
| Provider route | Kimi Chat Completions, `region = "cn"`, fixed `https://api.moonshot.cn/v1` |
| Explicit model ID | `kimi-k2.6` |
| Exact implementation commit | `e350603eb43c224f38f6e7b2c18189f6b2e2b7e7` |
| Exact pytest command | `.\.venv\Scripts\python.exe -m pytest tests\agent\test_kimi_integration.py -m kimi_integration -q` |
| Fixed outcome | `5 passed in 29.81s` |
| Invalid attempt | an earlier exact-commit attempt passed setup/doctor but failed four provider cells at authentication because the clipboard held a MiniMax key; it grants no capability evidence |
| Ordinary/continuation cell | two real model turns completed one `list_windows` fake-MCP call and its tool-result continuation |
| Planner/structured/final cell | prompted JSON Object was Host-compiled before one fake-MCP observation and one tool-free final response |
| Image cell | one synthetic 1x1 PNG crossed the reviewed Planner/final image boundary; no real pixels were captured |
| Timeout cell | one-second Host provider timeout returned fixed `PROVIDER_TIMEOUT` with zero MCP tool calls |
| Setup cell | formal `config setup --provider kimi --model kimi-k2.6 --region cn` plus `config doctor` passed SDK, isolated credential, executable, working-directory, and 13-tool discovery checks; generated TOML held no secret |
| Execution boundary | harmless stdio/fake MCP only; zero side effects, Windows Driver calls, real desktop reads, or application actions |

The initial live ordinary tool continuation passed. Initial Planner attempts
failed closed: first because the integration child process did not inherit its
test-local application root, then because K2.6 default thinking consumed the
entire 512-token one-shot reserve and returned `finish_reason=length` with no
answer content. A diagnostic native strict-schema request also returned a
non-contract plan despite accepting the schema. The bounded repair therefore
keeps Kimi Planner in prompted JSON Object mode with unchanged Host compilation
and disables thinking only for `cn` + `kimi-k2.6` one-shot Planner/final calls.
The global route and sibling models remain unchanged, and ordinary tool-calling
continuation keeps its reasoning-capable behavior.

The exact-commit passing rerun used only the route-specific
`MOONSHOT_CN_API_KEY` supplied through the operator environment and did not set
a model environment variable: the harness itself hard-pins `kimi-k2.6` and
fails on another explicit model. One earlier rerun stopped before pytest because
the clipboard was empty and made no provider request. The separate authentication
failure was invalidated after the operator clarified that the then-current
clipboard held a MiniMax credential. No key was written to configuration, MCP
environment, subprocess evidence, or this record. This result does not promote
Kimi global, another Kimi model, another provider, a real desktop or
application, E4, release, or cross-gateway credential compatibility.

## 2026-08-07: feature-freeze candidate revalidation

Both bounded E3 modules passed from clean, branch-reachable commit `23e71a5`.
Each provider exercised the ordinary read/tool/result/final cycle and bounded
`plan run` against the harmless fake stdio MCP child with zero side effects and
no Windows driver:

| Provider | Explicit model ID | Fixed outcome |
| --- | --- | --- |
| OpenAI | `gpt-5.6-terra` | `2 passed in 21.35s` |
| Anthropic Claude | `claude-sonnet-5` | `2 passed in 21.15s` |

The worktree was clean before and after. No credential, prompt, model prose,
tool output, provider response identity, or local state path is retained. The
complete surrounding non-E4 matrix and its limits are in
[Feature-freeze non-E4 evidence](FEATURE_FREEZE_NON_E4_EVIDENCE.md).

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
content block. This is retained as the historical reproduction for a
model-specific compatibility gap, not as a failure of the passing Claude E3
record above.

## 2026-07-17: Sonnet 5 reasoning-block compatibility revalidation

| Field | Sanitized reviewed value |
| --- | --- |
| Commit | `c99d65c` |
| Provider | Anthropic Claude Messages API |
| Explicit model ID | `claude-sonnet-5` |
| Review time (UTC) | `2026-07-17T13:52:45Z` |
| Exact pytest command | `.\.venv\Scripts\python.exe -m pytest tests\agent\test_anthropic_integration.py -m anthropic_integration -q` |
| Fixed outcome | `2 passed in 20.10s` |
| Ordinary case | reasoning-compatible read -> tool -> result -> final-answer cycle passed |
| Planner/Executor case | exact bounded observation-only `plan run` CLI cycle passed |
| Execution boundary | harmless fake stdio MCP child; zero side effects; no Windows driver or real desktop |

The exact implementation commit strictly preserves signed `thinking` and
opaque `redacted_thinking` blocks inside private Claude tool-result continuation
history while excluding them from canonical model text and redacted trace. The
run used the explicit opt-in flag and an operator-environment credential. No
credential, reasoning content, signature, task/final text, tool output,
provider identifier, raw traffic, or local state artifact is retained here.

## Promotion boundary

The historical OpenAI/Claude pair has retained passing records for the two
bounded fake-MCP cases, so those historical dual-provider E3 rows may move from
`PARTIAL` to `YES`. E4 remains separate and requires the isolated desktop
runbook. The Sonnet 5 compatibility repair is retained for the exact
implementation commit above, but remains model-scoped and does not convert E3
into an all-model compatibility claim.
