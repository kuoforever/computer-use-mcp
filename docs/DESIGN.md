# 目标架构设计 / Target Architecture Design — computer-use-mcp

> 本文件按**预期实现版本**书写，描述项目完整做成后的架构形态、边界和设计约束。当前进度和开工顺序见 [EXECUTION_PLAN.md](EXECUTION_PLAN.md)，历史交接记录见 [../HANDOFF.md](../HANDOFF.md)。
>
> This document describes the **target implementation** architecture, boundaries, and design constraints. For current progress and implementation order, see [EXECUTION_PLAN.md](EXECUTION_PLAN.md). For historical handoff notes, see [../HANDOFF.md](../HANDOFF.md).

## 1. 设计原则 / Design Principles

1. **与模型无关**：MCP server 只暴露工具，不关心调用方是 Claude Code、Codex、Cline，还是其他 MCP client。
   **Model-agnostic**: the MCP server exposes tools and does not care whether the caller is Claude Code, Codex, Cline, or another MCP client.
2. **双模式感知**：同时支持 `screenshot` 和 `ui_snapshot`。视觉模型可以看图，纯文本模型可以读控件树。
   **Dual-mode perception**: support both `screenshot` and `ui_snapshot`. Vision models can inspect images; text-only models can read control trees.
3. **双路径动作**：视觉路径按坐标点击；文本路径按 `ref` 调无障碍模式。ref 路径不合成坐标点击。
   **Dual-path actions**: vision paths click by coordinates; text paths call accessibility patterns by `ref`. Ref paths do not synthesize coordinate clicks.
4. **安全默认拒绝**：动作默认需要授权、确认、审计和急停兜底。
   **Deny-by-default safety**: actions require authorization, confirmation, audit, and e-stop fallback by default.
5. **平台驱动可替换**：核心依赖 Driver Contract，不直接依赖 Windows / macOS / Linux 专属 API。
   **Replaceable platform drivers**: the core depends on the Driver Contract, not directly on Windows / macOS / Linux APIs.

## 2. 目标架构 / Target Architecture

```text
MCP client
  └─ stdio transport
      └─ MCP server
          ├─ Tool schema and handlers
          ├─ Session / ref table / snapshot serialization
          ├─ Safety gate / confirmation / audit / e-stop
          └─ Driver Contract
              ├─ Windows driver: UIA + Win32
              ├─ macOS driver: AX
              └─ Linux driver: AT-SPI
```

| 层 / Layer | 职责 / Responsibility | 平台相关 / Platform-specific |
| --- | --- | --- |
| MCP server | 暴露工具、参数校验、返回内容块<br>Expose tools, validate parameters, return content blocks | 否 / No |
| Core Session | `ref` 生命周期、snapshot 文本序列化、`find`、失效重定位<br>Ref lifecycle, snapshot serialization, `find`, stale-ref relocation | 否 / No |
| Safety layer | allowlist gate、危险确认、审计、急停、脱敏<br>Allowlist gate, dangerous-action confirmation, audit, e-stop, redaction | 部分依赖驱动进程链 / Partly depends on driver owner chains |
| Driver Contract | 截图、窗口枚举、控件树、动作原语、坐标空间约束<br>Screenshots, window enumeration, control trees, action primitives, coordinate constraints | 边界 / Boundary |
| Platform driver | UIA / AX / AT-SPI、截图、输入、DPI、窗口和进程归属<br>UIA / AX / AT-SPI, screenshots, input, DPI, window and process ownership | 是 / Yes |

质量属性约束见 [QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md)，技术栈边界见 [TECH_STACK.md](TECH_STACK.md)。

See [QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md) for quality constraints and [TECH_STACK.md](TECH_STACK.md) for technology boundaries.

## 3. Driver Contract 不变量 / Driver Contract Invariants

Driver Contract 是核心和平台驱动之间唯一的边界，详见 [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md)。

The Driver Contract is the only boundary between the core and platform drivers. See [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md).

1. **裁剪下推**：平台驱动按 `PruneOpts` 裁剪后返回节点，核心不接收原始全树。
   **Push pruning down**: platform drivers return nodes after applying `PruneOpts`; the core does not receive raw full trees.
2. **单一坐标空间**：截图像素、UIA / AX / AT-SPI bbox、`click(x,y)` 坐标共享同一像素栅格。
   **Single coordinate space**: screenshot pixels, UIA / AX / AT-SPI bounding boxes, and `click(x,y)` share one pixel grid.
3. **归属链由驱动提供**：驱动负责查窗口和进程归属链，核心负责按 allowlist 判定。
   **Owner chains come from drivers**: drivers resolve window and process ownership; the core applies allowlist policy.

Contract 变更规则：

Contract change rules:

- 改原语签名或数据结构必须升 `contract_version`。
  Primitive signature or data-structure changes must bump `contract_version`.
- 小版本保持向后兼容。
  Minor versions remain backward compatible.
- 核心拒绝大版本不匹配的 driver。
  The core rejects drivers with incompatible major versions.
- 上层代码不得绕开 contract 直接调用平台 API。
  Upper layers must not bypass the contract to call platform APIs directly.

## 4. 感知模型 / Perception Model

### 4.1 `screenshot`

`screenshot` 返回图像内容，主要服务视觉模型和视觉 grounding。

`screenshot` returns image content, mainly for vision models and visual grounding.

目标约束 / Target constraints:

- 默认坐标空间与 `ui_snapshot` bbox 一致。
  Its default coordinate space matches `ui_snapshot` bounding boxes.
- 支持 region 截图时，返回内容必须说明 region 和坐标基准。
  Region screenshots must report the region and coordinate basis.
- 敏感窗口按标题或策略打码。
  Sensitive windows are redacted by title or policy.
- 后台 / 隔离 worker 场景不能假设主屏帧缓冲，需要显式窗口级截图或独立 DISPLAY 截图能力。
  Background or isolated-worker scenarios cannot assume the main-screen framebuffer and need explicit window-level or independent-DISPLAY screenshots.

### 4.2 `ui_snapshot`

`ui_snapshot` 返回扁平控件列表，而不是完整缩进树。

`ui_snapshot` returns a flat list of controls, not a full indented tree.

典型行格式 / Typical line format:

```text
ref_7 | Button "保存" | bbox=(1003,565,50,24) | enabled | patterns=invoke
```

目标约束 / Target constraints:

- 每个节点包含 `ref`、role、name、bbox、states、patterns 和必要 value。
  Each node includes `ref`, role, name, bbox, states, patterns, and necessary value.
- password 控件不返回明文 value。
  Password controls do not return plaintext values.
- 默认只返回可见、可交互、在 scope 内的节点。
  By default, only visible, interactive, in-scope nodes are returned.
- 节点数超过上限时返回 `truncated`，不静默丢弃。
  When node count exceeds the cap, return `truncated` instead of silently dropping nodes.
- `find(query)` 用于大窗口或复杂页面的 token 控制。
  `find(query)` controls token cost for large windows and complex pages.
- 文本 run 合并、parent ref、层级消歧由真实内容页证据驱动。
  Text-run merging, parent refs, and hierarchy disambiguation are driven by real content-page evidence.

## 5. 动作模型 / Action Model

| 动作 / Action | 路径 / Path | 边界 / Boundary |
| --- | --- | --- |
| `click({ref})` | 无障碍模式 / Accessibility pattern | `Invoke` / `SelectionItem` / 平台等价能力 |
| `type(text, ref)` | 无障碍模式 / Accessibility pattern | `ValuePattern.SetValue` / AX value / AT-SPI EditableText |
| `click({x,y})` | 坐标路径 / Coordinate path | 会移动物理指针，属于 foreground-required<br>Moves physical pointer; foreground-required |
| `key(combo)` | 全局键盘路径 / Global keyboard path | 发送给当前焦点，属于 foreground-required<br>Sent to current focus; foreground-required |
| `type(text)` | 焦点输入路径 / Focus typing path | 无 ref 时发送给当前焦点，属于 foreground-required<br>Without ref, sent to current focus; foreground-required |
| `activate_window(id)` | 前台路径 / Foreground path | 改变用户前台窗口，属于 foreground-required<br>Changes user foreground window; foreground-required |

ref 动作原则：

Ref action principles:

- 优先使用平台无障碍动作，不把 ref 转成 bbox 中心点。
  Prefer platform accessibility actions; do not convert refs to bbox-center clicks.
- 执行动作前校验 `native_id` 是否仍有效。
  Validate that `native_id` is still valid before executing.
- 失效时可按 role + name 做一次重定位。
  If stale, attempt one relocation by role + name.
- 重定位失败返回可解释错误，要求重新 snapshot。
  If relocation fails, return an explainable error and require a new snapshot.

## 6. 安全模型 / Safety Model

动作执行顺序：

Action execution order:

```text
request
  -> e-stop check
  -> action classification
  -> gate decision
  -> dangerous action confirmation
  -> driver action
  -> audit record
  -> result
```

目标能力 / Target capabilities:

- allowlist 支持进程树归属链。
  Allowlist supports process ownership chains.
- foreground-required 动作必须检查前台授权和人机让路条件。
  Foreground-required actions check foreground authorization and human-coexistence conditions.
- 同桌面 ref 动作不保证后台安全：受控 Notepad 探针确认 `SetValue` 可在输入 tick 未变化时切换前台。
  Same-desktop ref actions are not guaranteed background-safe: a controlled Notepad probe confirmed that `SetValue` can change foreground without an input-tick change.
- 危险动作命中策略后弹确认。
  Dangerous actions trigger confirmation when policy matches.
- 所有动作写 JSONL 审计日志。
  All actions write JSONL audit logs.
- 急停触发后拒绝所有动作直到重启。
  After e-stop, all actions are rejected until restart.
- 感知路径也要做脱敏，但不应为了读取而抢前台。
  Perception paths also redact sensitive data, but must not steal foreground to read.

## 7. 人机共存模型 / Human Coexistence Model

单一桌面只有一个前台窗口、一只鼠标指针和一个键盘焦点。目标设计不把同桌面完整后台操作者伪装成可行能力。

A single desktop has one foreground window, one mouse pointer, and one keyboard focus. The target design does not pretend that a full same-desktop background operator is viable.

| 等级 / Class | 动作 / Actions | 策略 / Policy |
| --- | --- | --- |
| `safe_local` | 本机受限动作<br>Guarded local actions | allowlist + 人机让路 + 确认 + 审计<br>Allowlist + human yielding + confirmation + audit |
| `full_control_local` | 本机完整截图、坐标、键盘、前台控制<br>Full local screenshots, coordinates, keyboard, and foreground control | 显式授权；保留急停和审计<br>Explicit authorization; retain e-stop and audit |
| `isolated_worker` | 截图、坐标、键盘、前台都在独立环境内<br>Screenshot, coordinates, keyboard, and foreground all inside an isolated environment | VM / 独立 Session / Xvfb |

人最近有鼠标或键盘输入时，foreground-required 动作应返回可解释拒绝，例如 `HUMAN_ACTIVE`，而不是抢控制权。

When recent human mouse or keyboard input is detected, foreground-required actions should return an explainable rejection such as `HUMAN_ACTIVE`, not seize control.

## 8. 浏览器与复杂应用 / Browsers and Complex Apps

浏览器、Electron、微信等复杂应用需要实测驱动策略。

Browsers, Electron apps, WeChat, and similar complex apps require evidence-driven strategies.

目标约束 / Target constraints:

- Chrome / Chromium 首次 UIA 读取需要 accessibility warmup 或稳定读取策略。
  Chrome / Chromium first UIA reads need accessibility warmup or another stable-read strategy.
- 内容页 snapshot 必须暴露截断状态和节点统计，便于判断是否需要 parent ref 或序列化增强。
  Content-page snapshots expose truncation state and node statistics to justify parent refs or serialization enhancements.
- owned 对话框必须被 `list_windows` 覆盖。
  Owned dialogs must be covered by `list_windows`.
- 进程树 allowlist 需要覆盖浏览器 / Electron / 微信的渲染子进程。
  Process-tree allowlists must cover renderer subprocesses for browsers, Electron apps, and WeChat.
- 对 UIA 不可靠的 canvas / 游戏类界面，坐标路径仍可用，但必须遵守 foreground-required 规则。
  For canvas or game-style surfaces where UIA is unreliable, coordinate paths remain available but must follow foreground-required rules.

### 8.1 浏览器内容页探针结论 / Browser Content-Page Probe Findings

2026-07-10 在真实 Chrome 内容页上观察到：CAIE 页面为 66 个节点；Wikipedia
``Artificial intelligence`` 稳定后为 134 个节点（88 个 Hyperlink，约 3,509 token），默认
`max_nodes=200` 均未截断，`find("intelligence")` 约为完整快照的 1/16。重复的
`(role, name)` 组覆盖约 11% 的节点；多数是浏览器框架或 `[show]` 按钮，少量是可由当前
`ref` 直接消歧的同名链接。列表页仅暴露 65 个节点，说明 UIA 规模不能由 DOM 规模推断。

The 2026-07-10 probes found 66 nodes on CAIE and, after stabilization, 134 nodes
on Wikipedia ``Artificial intelligence`` (88 hyperlinks, about 3,509 tokens).
Neither reached the default 200-node cap, and `find("intelligence")` was about
16x smaller than the full snapshot. Duplicate `(role, name)` groups covered about
11% of nodes, mainly browser chrome or `[show]` controls; the few duplicate links
remain directly addressable by their current `ref`. A list page exposed only 65
nodes, so DOM size is not a proxy for UIA snapshot size.

结论 / Decision: v1 保持扁平 `ref` 和 `max_nodes=200`，暂不增加 parent ref、层级结构或文本
run 合并。新 renderer 在后台可长期只返回框架树；生产代码绝不为感知抢前台，而是在检测到
该形态时显式标记 snapshot 为 incomplete。后续应在动态 Web app 或超过 200 个 UIA 节点的
页面复测后再重新评估。

Decision: keep flat refs and `max_nodes=200` in v1. Do not add parent refs,
hierarchy, or text-run merging yet. A background renderer can keep returning a
frame-only tree; production code must never steal foreground for perception and
instead marks that shape as incomplete. Revisit this decision with a dynamic web
app or a page exceeding 200 UIA nodes.

## 9. 后台 worker 路线 / Background Worker Route

目标把本机控制与后台 worker 拆成三类：

The target design splits local control and background workers into three routes:

| 路线 / Route | 能力 / Capability | 约束 / Constraint |
| --- | --- | --- |
| 本机安全模式<br>Safe local mode | 受 allowlist 与人机让路约束的操作<br>Actions constrained by allowlist and human yielding | 默认模式<br>Default mode |
| 本机全权限模式<br>Full-control local mode | 完整截图、点击、键盘、前台控制<br>Full screenshots, clicks, keyboard, and foreground control | 显式授权；影响当前桌面<br>Explicit authorization; affects the current desktop |
| 独立 worker 环境<br>Isolated worker environment | 完整截图、点击、键盘、前台控制<br>Full screenshots, clicks, keyboard, and foreground control | VM / 独立 Session / Xvfb；不影响主桌面<br>VM / independent session / Xvfb; does not affect the main desktop |

The current P8 prototype uses VMware Workstation Pro as the VM runtime. Host
orchestration is intentionally thin: `scripts/vmware_worker.py` starts an
existing `.vmx`, waits for VMware Tools, and invokes the worker in the guest.
It is not a VM image builder and it is not the final transport layer between the
host agent and guest MCP server.

不支持的路线：
Unsupported routes:

- 同一桌面里完整后台操作者。
  Full background operator on the same desktop.
- 将 `SetValue` / `Invoke` / `Select` 视为通用的无前台副作用动作。
  Treating `SetValue`, `Invoke`, or `Select` as generally foreground-free actions.
- 默认开启后台动作。
  Background actions enabled by default.
- 通过抢前台来伪装后台截图或后台感知。
  Faking background screenshots or perception by stealing foreground.

## 10. 测试与可观测性 / Testing and Observability

| 类型 / Type | 覆盖 / Coverage |
| --- | --- |
| pytest | `core.Session`、`gate`、`safety`、`audit`、fake driver |
| on-device smoke | Windows 真实桌面、真实窗口、真实对话框、输入和截图<br>Real Windows desktop, windows, dialogs, input, and screenshots |
| probe | 新应用 / 新浏览器场景的一次性观察，输出到 `out/`<br>One-off observations for new app or browser scenarios, written to `out/` |

目标可观测性：

Target observability:

- 动作失败返回具体错误码和上下文。
  Action failures return concrete error codes and context.
- `ui_snapshot` / `find` 返回 `truncated`。
  `ui_snapshot` / `find` return `truncated`.
- 审计日志可 grep、可 diff、可关联动作结果。
  Audit logs are grep-able, diff-able, and linkable to action results.
- 真实 app probe 记录节点数量、角色分布、截断和消歧证据。
  Real-app probes record node counts, role distributions, truncation, and disambiguation evidence.

## 11. 文档分工 / Documentation Roles

| 文档 / Document | 分工 / Role |
| --- | --- |
| [../README.md](../README.md) | 目标能力、运行方式和文档入口<br>Target capabilities, run flow, and documentation entry |
| [DESIGN.md](DESIGN.md) | 目标架构和设计约束<br>Target architecture and design constraints |
| [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md) | 核心与平台驱动的稳定契约<br>Stable contract between core and platform drivers |
| [TECH_STACK.md](TECH_STACK.md) | 目标技术栈和平台边界<br>Target tech stack and platform boundaries |
| [QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md) | 质量属性、设计约束、验收信号<br>Quality attributes, design constraints, acceptance signals |
| [EXECUTION_PLAN.md](EXECUTION_PLAN.md) | 从当前代码推进到目标版本的实施路线<br>Implementation path from current code to target version |
| [../HANDOFF.md](../HANDOFF.md) | 当前状态、历史验证记录和接手提示<br>Current state, historical validation notes, and handoff hints |
