# Provider support

> **Status: eight provider identities and their reviewed service-region routes
> are implemented and offline verified; credentialed testing is retained only
> for the earlier OpenAI and Anthropic scopes.** No new regional route made a
> real API request in this implementation slice. Its live E3/E4 and application
> gates remain deferred until the matching regional accounts and credentials
> exist.

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
| `deepseek` | `global` | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` |
| `glm` | `cn` | `ZAI_API_KEY` | `https://open.bigmodel.cn/api/paas/v4` |
| `glm` | `global` | `ZAI_GLOBAL_API_KEY` | `https://api.z.ai/api/paas/v4` |
| `minimax` | `cn` | `MINIMAX_API_KEY` | `https://api.minimaxi.com/anthropic` |
| `minimax` | `global` | `MINIMAX_GLOBAL_API_KEY` | `https://api.minimax.io/anthropic` |

Omitting `region` preserves the pre-region defaults: `global` for OpenAI,
Anthropic, Kimi, and DeepSeek; `cn-beijing` for Qwen and Doubao; and `cn` for
GLM and MiniMax. Kimi currently has only the reviewed global route. The catalog
does not invent a China route merely because a vendor has a domestic product.

The current `config setup` recommendations are account-dependent starting
points, not retained live evidence: `gpt-5.6-terra`, `claude-sonnet-5`,
`qwen3.7-plus`, `doubao-seed-2-0-lite-260215`, `kimi-k2.6`,
`deepseek-v4-pro`, `glm-5.2`, and `MiniMax-M2.7`. An operator may pass an
explicit model ID; they remain responsible for verifying that account's model
access and setting accurate context/output limits.

The provider and region snapshot was reviewed on 2026-08-10 against the official
[Kimi API and model docs](https://platform.kimi.ai/docs/api/overview),
[Qwen regional workspace docs](https://www.alibabacloud.com/help/en/model-studio/use-workspace),
[Doubao Responses guide](https://www.volcengine.com/docs/82379/1795150),
[BytePlus ModelArk endpoint docs](https://docs.byteplus.com/en/docs/ModelArk/1399008),
[DeepSeek API model/pricing page](https://api-docs.deepseek.com/quick_start/pricing?article_id=article_1779470751466_8),
[GLM model overview](https://docs.bigmodel.cn/cn/guide/start/model-overview), and
[MiniMax Anthropic-compatible API](https://platform.minimax.io/docs/api-reference/text-anthropic-api).
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
- Provider credentials remain Host environment variables. They are neither
  stored in TOML nor inherited by the MCP child, offline tests, or release
  subprocesses.
- New configuration uses typed `[provider].region`; Qwen additionally requires
  `[provider].workspace_id`. The Host constructs the URL from those fields.
  Fixed-endpoint providers reject `[provider].base_url`; Qwen accepts it only
  as a legacy migration form with an exact reviewed workspace URL. Arbitrary
  proxies or rerouting are never authorized.

## Setup

Kimi uses the OpenAI SDK extra without using OpenAI identity or credentials:

~~~powershell
python -m pip install -e ".[agent-openai]"
$env:MOONSHOT_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider kimi --model kimi-k2.6
guarded-desktop-agent config doctor --config `
  "$env:LOCALAPPDATA\computer-use-agent\agent.toml"
~~~

Qwen also needs its account-specific workspace ID and matching regional key:

~~~powershell
$env:DASHSCOPE_AP_SOUTHEAST_1_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider qwen --model qwen3.7-plus `
  --region ap-southeast-1 --workspace-id "<WorkspaceId>"
~~~

MiniMax China and global accounts are explicit independent routes:

~~~powershell
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

## Deferred live gate

No Kimi, Qwen, Doubao, DeepSeek, GLM, or MiniMax credential was created or used
for this slice. Before promoting any one of them beyond offline support:

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
