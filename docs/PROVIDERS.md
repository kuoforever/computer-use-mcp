# Provider support

> **Status: eight provider identities are implemented and offline verified;
> credentialed testing is retained only for the earlier OpenAI and Anthropic
> scopes.** Kimi, Qwen, Doubao, DeepSeek, GLM, and MiniMax have not made a real
> API request in this implementation slice. Their live E3/E4 and application
> gates are intentionally deferred until accounts and credentials exist.

## Support matrix

Wire compatibility never aliases provider identity. Each profile has its own
credential variable, reviewed endpoint, model ID, capability flags,
continuation identity, setup check, and evidence state.

| Provider name | Wire family | SDK extra | Credential variable | Endpoint rule | Planner JSON mode | Image input |
| --- | --- | --- | --- | --- | --- | --- |
| `openai` | Responses | `agent-openai` | `OPENAI_API_KEY` | fixed OpenAI API | native JSON Schema | yes |
| `anthropic` | Messages | `agent-anthropic` | `ANTHROPIC_API_KEY` | fixed Anthropic API | native JSON Schema | yes |
| `qwen` | Responses-compatible | `agent-openai` | `DASHSCOPE_API_KEY` | required account workspace URL ending in `.maas.aliyuncs.com/compatible-mode/v1` | exact schema in prompt, then Host validation | yes |
| `doubao` | Responses-compatible | `agent-openai` | `ARK_API_KEY` | fixed Ark API v3 | exact schema in prompt, then Host validation | yes |
| `kimi` | Chat Completions-compatible | `agent-openai` | `MOONSHOT_API_KEY` | fixed Moonshot API v1 | JSON object plus Host validation | yes |
| `deepseek` | Chat Completions-compatible | `agent-openai` | `DEEPSEEK_API_KEY` | fixed DeepSeek API | JSON object plus Host validation | no |
| `glm` | Chat Completions-compatible | `agent-openai` | `ZAI_API_KEY` | fixed BigModel API v4 | JSON object plus Host validation | only reviewed `glm-*v*` model IDs |
| `minimax` | Anthropic Messages-compatible | `agent-anthropic` | `MINIMAX_API_KEY` | fixed MiniMax Anthropic endpoint | exact schema in prompt, then Host validation | no |

The current `config setup` recommendations are account-dependent starting
points, not retained live evidence: `gpt-5.6-terra`, `claude-sonnet-5`,
`qwen3.7-plus`, `doubao-seed-2-0-lite-260215`, `kimi-k2.6`,
`deepseek-v4-pro`, `glm-5.2`, and `MiniMax-M2.7`. An operator may pass an
explicit model ID; they remain responsible for verifying that account's model
access and setting accurate context/output limits.

The added-provider snapshot was reviewed on 2026-08-10 against the official
[Kimi API and model docs](https://platform.kimi.ai/docs/api/overview),
[Qwen model catalog](https://help.aliyun.com/en/model-studio/models),
[Doubao Responses guide](https://www.volcengine.com/docs/82379/1795150),
[DeepSeek API model/pricing page](https://api-docs.deepseek.com/quick_start/pricing?article_id=article_1779470751466_8),
[GLM model overview](https://docs.bigmodel.cn/cn/guide/start/model-overview), and
[MiniMax Anthropic-compatible model API](https://platform.minimaxi.com/docs/api-reference/models/anthropic/list-models).
Documentation review chooses request shapes; only credentialed tests can prove
the exact account/model behavior.

## Implemented boundary

- Ordinary provider loops, one-shot Planner calls, and tool-free final-response
  calls route through one catalog-backed factory.
- Responses-compatible profiles retain response-ID continuation. OpenAI Chat
  Completions-compatible profiles retain bounded local message history.
  Messages-compatible profiles retain bounded local Messages history.
- Continuation v7 binds exact provider name, model, protocol, and effective
  endpoint. A compatible wire format cannot resume under another vendor.
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
- Fixed-endpoint providers reject `[provider].base_url`. Qwen is the only
  configurable endpoint and accepts only the reviewed HTTPS workspace shape;
  arbitrary proxies or rerouting are not silently authorized.

## Setup

Kimi uses the OpenAI SDK extra without using OpenAI identity or credentials:

~~~powershell
python -m pip install -e ".[agent-openai]"
$env:MOONSHOT_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider kimi --model kimi-k2.6
guarded-desktop-agent config doctor --config `
  "$env:LOCALAPPDATA\computer-use-agent\agent.toml"
~~~

Qwen also needs its account-specific workspace-compatible endpoint:

~~~powershell
$env:DASHSCOPE_API_KEY = "<credential>"
guarded-desktop-agent config setup --provider qwen --model qwen3.7-plus `
  --base-url "https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
~~~

Use `agent-anthropic` for Anthropic or MiniMax, `agent-openai` for the other
profiles, and `agent` when both SDK families are required. `config doctor`
checks only SDK/key presence and the configured MCP discovery contract; it
does not send a provider request.

## Deferred live gate

No Kimi, Qwen, Doubao, DeepSeek, GLM, or MiniMax credential was created or used
for this slice. Before promoting any one of them beyond offline support:

1. create the provider account and set only its documented Host credential;
2. confirm the exact available model ID and account endpoint/region;
3. run the harmless fake-MCP E3 matrix for ordinary, Planner, final response,
   tool calling, structured output, image capability, timeout, and continuation;
4. fix only defects observed against that exact provider/model candidate;
5. retain sanitized evidence, then separately decide whether an isolated E4 or
   real-application gate is authorized.

Passing one provider or model does not promote a sibling profile, later model,
desktop action, application, or release.
