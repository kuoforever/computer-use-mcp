# Provider support

> **Status: eight cloud identities plus one loopback-only `local_openai`
> identity are implemented and offline verified at their named boundaries;
> credentialed testing is retained for the earlier OpenAI and Anthropic scopes
> plus exact Kimi `kimi-k2.6` and MiniMax `MiniMax-M2.7` China routes and the
> exact DeepSeek `deepseek-v4-pro` global and Doubao
> `doubao-seed-2-0-lite-260215` China routes plus exact Qwen `qwen3.7-plus`
> Beijing and GLM `glm-5.2` China routes.** Local support currently covers
> text-only Planner/final construction, not native ordinary tool calling. Other
> cloud routes, local E3, E4, and application gates remain deferred.

## Support matrix

Wire compatibility never aliases provider identity. Each profile has its own
credential variable, reviewed endpoint, model ID, capability flags,
continuation identity, setup check, and evidence state.

| Provider name | Wire family | SDK extra | Planner JSON mode | Image input |
| --- | --- | --- | --- | --- |
| `openai` | Responses | `agent-openai` | native JSON Schema | yes |
| `anthropic` | Messages | `agent-anthropic` | native JSON Schema | yes |
| `qwen` | Responses-compatible | `agent-openai` | exact schema in prompt, then Host validation | yes |
| `doubao` | Responses-compatible | `agent-openai` | exact schema in prompt, then Host validation | yes |
| `kimi` | Chat Completions-compatible | `agent-openai` | JSON object plus Host validation | yes |
| `deepseek` | Chat Completions-compatible | `agent-openai` | JSON object plus Host validation | no |
| `glm` | Chat Completions-compatible | `agent-openai` | JSON object plus Host validation | only reviewed `glm-*v*` model IDs |
| `minimax` | Anthropic Messages-compatible | `agent-anthropic` | exact schema in prompt, then Host validation | no |
| `local_openai` | loopback Chat Completions-compatible | `agent-openai` | exact schema in prompt, then Host validation | no |

`[provider].region` selects only one catalog entry below. Every entry fixes the
credential-variable identity and endpoint; there is no automatic cross-region
fallback.

| Provider | Region | Credential variable | Reviewed endpoint |
| --- | --- | --- | --- |
| `openai` | `global` | `OPENAI_API_KEY` | `https://api.openai.com/v1` |
| `anthropic` | `global` | `ANTHROPIC_API_KEY` | `https://api.anthropic.com` |
| `qwen` | `cn-beijing` | `DASHSCOPE_API_KEY` | `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1` |
| `qwen` | `ap-southeast-1` | `DASHSCOPE_AP_SOUTHEAST_1_API_KEY` | `https://<WorkspaceId>.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1` |
| `qwen` | `ap-northeast-1` | `DASHSCOPE_AP_NORTHEAST_1_API_KEY` | `https://<WorkspaceId>.ap-northeast-1.maas.aliyuncs.com/compatible-mode/v1` |
| `qwen` | `eu-central-1` | `DASHSCOPE_EU_CENTRAL_1_API_KEY` | `https://<WorkspaceId>.eu-central-1.maas.aliyuncs.com/compatible-mode/v1` |
| `doubao` | `cn-beijing` | `ARK_API_KEY` | `https://ark.cn-beijing.volces.com/api/v3` |
| `doubao` | `ap-southeast-1` | `BYTEPLUS_ARK_API_KEY` | `https://ark.ap-southeast.bytepluses.com/api/v3` |
| `kimi` | `global` | `MOONSHOT_API_KEY` | `https://api.moonshot.ai/v1` |
| `kimi` | `cn` | `MOONSHOT_CN_API_KEY` | `https://api.moonshot.cn/v1` |
| `deepseek` | `global` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| `glm` | `cn` | `ZAI_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` |
| `glm` | `global` | `ZAI_GLOBAL_API_KEY` | `https://api.z.ai/api/paas/v4` |
| `minimax` | `cn` | `MINIMAX_API_KEY` | `https://api.minimaxi.com/anthropic` |
| `minimax` | `global` | `MINIMAX_GLOBAL_API_KEY` | `https://api.minimax.io/anthropic` |
| `local_openai` | `local` | optional `LOCAL_OPENAI_API_KEY` | required `http://127.0.0.1:<port>/v1` or `http://[::1]:<port>/v1` |

Omitting `region` preserves the pre-region defaults: `global` for OpenAI,
Anthropic, Kimi, and DeepSeek; `cn-beijing` for Qwen and Doubao; and `cn` for
GLM and MiniMax; `local` is fixed for `local_openai`. Kimi `global` and `cn`
use separate Host credential variables and never fall back across gateways.

The current `config setup` recommendations are account-dependent starting
points, not retained live evidence: `gpt-5.6-terra`, `claude-sonnet-5`,
`qwen3.7-plus`, `doubao-seed-2-0-lite-260215`, `kimi-k2.6`,
`deepseek-v4-pro`, `glm-5.2`, and `MiniMax-M2.7`. `local_openai` deliberately
has no recommended model because the Host cannot infer what an operator serves;
both model ID and endpoint are required. Operators remain responsible for model
access and accurate context/output limits.

The provider and region snapshot was reviewed on 2026-08-11 against the official
[Kimi global API docs](https://platform.kimi.ai/docs/api/overview),
[Kimi China API docs](https://platform.kimi.com/docs/api/overview),
[Qwen regional workspace docs](https://www.alibabacloud.com/help/en/model-studio/use-workspace),
[Doubao Responses guide](https://www.volcengine.com/docs/82379/1795150),
[BytePlus ModelArk endpoint docs](https://docs.byteplus.com/en/docs/ModelArk/1399008),
[DeepSeek API model/pricing page](https://api-docs.deepseek.com/quick_start/pricing?article_id=article_1779470751466_8),
[GLM model overview](https://docs.bigmodel.cn/cn/guide/start/model-overview),
[MiniMax global Anthropic-compatible API](https://platform.minimax.io/docs/api-reference/text-anthropic-api), and
[MiniMax China Anthropic-compatible API](https://platform.minimaxi.com/docs/api-reference/text-chat-anthropic).
Documentation review chooses request shapes; only credentialed tests can prove
the exact account/model behavior.

## Implemented boundary

- Ordinary provider loops, one-shot Planner calls, and tool-free final-response
  calls route through one catalog-backed factory.
- Responses-compatible profiles retain response-ID continuation. OpenAI Chat
  Completions-compatible profiles retain bounded local message history.
  Messages-compatible profiles retain bounded local Messages history.
- Continuation v8 binds exact provider name, model, protocol, region, and
  effective endpoint. A compatible wire format cannot resume under another
  vendor or service region. Strict v7 and original OpenAI/Anthropic v6 records
  remain readable under their narrower legacy identity contracts.
- The Responses request contract is versioned. Legacy OpenAI contract v3 state
  is verified before one-way migration to v4; incompatible drift fails before
  network I/O.
- Text-only profiles never receive image-returning tool schemas. A final request,
  tool result, or restored continuation that would carry an image fails before
  provider I/O.
- The Host still validates every returned tool name and argument against its
  own reviewed registry. Prompt-only structured output is not trusted as a
  provider guarantee; it passes through the same strict local compiler.
- The exact `glm` + `cn` + `glm-5.2` one-shot Planner wire requests string
  field `arguments` because a valid live JSON response was not conformant to
  the Host-requested Planner wire: it returned unreviewed `arguments_` instead
  of requested `arguments_json`. The Host accepts only that exact reviewed
  field for this route, decodes it to an object, and then runs the unchanged
  tool/argument compiler. Invented, old, duplicate, sibling-route, and sibling-
  model forms fail closed.
- Messages-compatible one-shot Planner/final responses may contain only valid
  signed `thinking` or opaque `redacted_thinking` blocks before exactly one
  text block. The Host validates and discards that reasoning before compilation
  or final output; malformed, late, duplicate, tool, or unknown blocks fail
  closed. Ordinary Messages continuation retains its stricter exact replay.
- Provider credentials remain Host environment variables. They are neither
  stored in TOML nor inherited by the MCP child, offline tests, or release
  subprocesses.
- New configuration uses typed `[provider].region`; Qwen additionally requires
  `[provider].workspace_id`. The Host constructs the URL from those fields.
  Fixed-endpoint providers reject `[provider].base_url`; Qwen accepts it only
  as a legacy migration form with an exact reviewed workspace URL. Arbitrary
  cloud proxies, non-loopback local endpoints, and unreviewed rerouting are
  never authorized.
- `local_openai` is the sole dynamic-endpoint exception. Its parser accepts
  only literal IPv4/IPv6 loopback over `http`, one explicit nonzero port, and
  exact `/v1`; it rejects `localhost`, LAN/public hosts, userinfo, query,
  fragment, and other paths. It never starts, downloads, or manages a server.
- Local Planner/final calls reuse the Chat Completions adapters in text-only,
  prompt-schema mode. Ordinary native tool calling fails before SDK client
  construction as `PROVIDER_TOOL_CALLING_UNVERIFIED`; `public-web-word` setup
  fails with the same code. This boundary stays closed until exact E3.

## Setup

Kimi uses the OpenAI SDK extra without using OpenAI identity or credentials:

~~~powershell
python -m pip install -e ".[agent-openai]"
$env:MOONSHOT_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider kimi --model kimi-k2.6
guarded-desktop-agent config doctor --config `
  "$env:LOCALAPPDATA\computer-use-agent\agent.toml"
~~~

The China gateway is explicit and uses an isolated Host credential name:

~~~powershell
$env:MOONSHOT_CN_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider kimi --model kimi-k2.6 `
  --region cn
~~~

The China and global gateways expose the same reviewed model ID here, but
their account keys are not assumed interchangeable. Only the exact `cn` +
`kimi-k2.6` route disables model thinking for one-shot Planner/final calls to
keep bounded structured output and final text inside the configured reserve.
The global route, sibling models, and ordinary tool-calling turns keep their
prior behavior.

DeepSeek uses one fixed global route and a text-only exact candidate here:

~~~powershell
$env:DEEPSEEK_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider deepseek `
  --model deepseek-v4-pro --region global
~~~

Qwen also needs its account-specific workspace ID and matching regional key:

~~~powershell
$env:DASHSCOPE_AP_SOUTHEAST_1_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider qwen --model qwen3.7-plus `
  --region ap-southeast-1 --workspace-id "<WorkspaceId>"
~~~

MiniMax China and global accounts are explicit independent routes:

~~~powershell
$env:MINIMAX_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider minimax --model MiniMax-M2.7 `
  --region cn

$env:MINIMAX_GLOBAL_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider minimax --model MiniMax-M2.7 `
  --region global
~~~

An existing Qwen TOML containing only the reviewed `base_url` remains readable
and continues to use `DASHSCOPE_API_KEY`. Regenerate it with `config setup` or
`config init` to migrate to `region + workspace_id`; do not combine the legacy
field with either new field.

Use `agent-anthropic` for Anthropic or MiniMax, `agent-openai` for the other
profiles, and `agent` when both SDK families are required. `config doctor`
checks only SDK/key presence and the configured MCP discovery contract; it
does not send a provider request.

One local text-only Planner/final configuration is created explicitly:

~~~powershell
guarded-desktop-agent config setup --provider local_openai `
  --model "operator-selected-model" `
  --base-url "http://127.0.0.1:11434/v1"
~~~

`LOCAL_OPENAI_API_KEY` may be set for a loopback server that enforces a key; it
is optional otherwise. `config doctor` does not probe the endpoint, and this
support does not claim compatibility with any named server or model.

## Remaining live gates

Kimi `kimi-k2.6` and MiniMax `MiniMax-M2.7` on their exact `cn` routes,
DeepSeek `deepseek-v4-pro` on its exact `global` route, and Doubao
`doubao-seed-2-0-lite-260215` plus Qwen `qwen3.7-plus` on their exact
`cn-beijing` routes plus GLM `glm-5.2` on its exact `cn` route have retained
bounded model-pinned exact-commit E3 results in
[Provider E3 evidence](E3_EVIDENCE.md). Before promoting another route beyond
offline support:

1. create the provider account in the intended service region and set only that
   route's documented Host credential;
2. confirm the exact available model ID and account endpoint/region;
3. run the harmless fake-MCP E3 matrix for ordinary, Planner, final response,
   tool calling, structured output, image capability, timeout, and continuation;
4. fix only defects observed against that exact provider/model candidate;
5. retain sanitized evidence with the exact region identity, then separately decide whether an isolated E4 or
   real-application gate is authorized.

Passing one provider or model does not promote a sibling profile, later model,
desktop action, application, or release.

The exact DeepSeek gate required no production adapter repair. Its ordinary
cell proves two-turn continuation but not live `reasoning_content`; its
text-only image cell proves tool-schema withdrawal rather than image input,
and its small workload does not validate the configured maximum context.

The exact GLM China gate first passed four cells and failed closed only at
Planner. Structure-only diagnostics retained no model content and showed that
the valid JSON response was not conformant to the Host-requested Planner wire:
it returned unreviewed `arguments_` instead of requested `arguments_json`.
Disabling thinking and strengthening the prompt did not change that result.
The bounded repair asks only `glm` + `cn` + `glm-5.2` for string field
`arguments`, then uses the same exact-key, allowed-tool, JSON-object, and
reviewed-schema Host compilation. It does not accept `arguments_`, multiple
aliases, object-valued wire arguments, the global route, or sibling models.
The passing matrix proves one bounded local-history continuation and text-only
image-tool withdrawal, not image input, maximum context/output, E4, or release.

The exact Doubao China gate also required no production adapter repair. Its
first valid matrix passed four cells and exposed only that the shared 1x1 fake
PNG was below the route's 14-pixel minimum image dimension. An exact-marker
16x16 synthetic fixture plus a deterministic legacy-fixture test repaired the
harness; the clean full matrix then passed. Its ordinary cell proves bounded
Responses continuation and its image cell proves only that single synthetic
input, not arbitrary images, maximum context, or the BytePlus route.

The exact Qwen Beijing gate uses the account-specific generated
`https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`
endpoint and retains no workspace value. Its clean pre-repair matrix exposed
intermittent, otherwise-valid Planner contract JSON inside exactly one
lowercase Markdown JSON fence. The bounded production repair applies only to
`qwen` + `cn-beijing` + `qwen3.7-plus` Planner output, enforces the original
64 KiB response limit before removing the exact wrapper, and then invokes the
unchanged Host compiler. Any other wrapper, route, model, ordinary turn, or
final response keeps the prior fail-closed behavior. The passing matrix proves
one bounded Responses continuation and one 16x16 synthetic-image cycle, not
arbitrary images, maximum context, another Qwen region/model, E4, or release.

Local E3 is separately deferred by the user. Before enabling native ordinary
tool calling for any exact local server/model candidate, retain a harmless
fake-MCP matrix for Planner, final response, tool schema/call behavior,
structured output, timeout, continuation, and declared modality. A different
server, model, quantization, template, or port remains a separate candidate.
