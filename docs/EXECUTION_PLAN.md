# EXECUTION_PLAN / 目标版本实施路线

> 本文件不是目标态设计文档，而是把当前代码推进到 README / DESIGN 所描述目标版本的实施路线。目标能力、架构和质量属性分别见 [../README.md](../README.md)、[DESIGN.md](DESIGN.md)、[QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md)。
>
> This is not the target-state design document. It is the implementation path from the current codebase to the target version described in README / DESIGN. For target capabilities, architecture, and quality attributes, see [../README.md](../README.md), [DESIGN.md](DESIGN.md), and [QUALITY_ATTRIBUTES.md](QUALITY_ATTRIBUTES.md).

路线按“最快降低不确定性、最少扩大架构面”的顺序排。默认先把 Windows 路径做成稳定 MVP；macOS / Linux、隐藏桌面 / VM 作为目标路线记录，不作为第一阶段默认开工项。

The route is ordered by fastest uncertainty reduction and smallest architecture expansion. The default first step is to stabilize the Windows MVP; macOS / Linux and hidden desktop / VM routes are recorded as target routes, not first-phase defaults.

## 0. 开工原则 / Working Principles

- **先修已知 bug，再做新能力**：最小化窗口导致 `ui_snapshot` 读空，是明确缺陷，优先级高于 parent ref、跨平台等设计题。
  **Fix known bugs before adding capability**: minimized windows causing empty `ui_snapshot` is a known defect and takes priority over parent refs or cross-platform design work.
- **不要靠抢前台修感知问题**：`ui_snapshot` / `screenshot` 属于感知路径，不应强行 `activate_window`。
  **Do not fix perception by stealing foreground**: `ui_snapshot` / `screenshot` are perception paths and should not force `activate_window`.
- **安全默认不放松**：是否改成按动作目标窗口授权，需要单独决策，不能顺手改。
  **Do not loosen safety by default**: switching to target-window authorization is a separate decision and must not happen incidentally.
- **真实桌面测试要显式标注副作用**：会启动应用、移动窗口、点击或输入的脚本继续放 `scripts/smoke_*.py`；一次性探针放 `out/`。
  **Mark real-desktop side effects explicitly**: scripts that launch apps, move windows, click, or type stay in `scripts/smoke_*.py`; one-off probes go to `out/`.
- **Contract v1.0 不随便动**：改 `contract.py` 字段或原语签名，必须同步改 [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md) 并说明版本影响。
  **Do not casually change Contract v1.0**: changing `contract.py` fields or primitive signatures requires updating [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md) and explaining version impact.

## 1. 第一阶段：Windows MVP 稳定化 / Phase 1: Stabilize Windows MVP

### P0. 修复最小化 / root area=0 导致快照清空

### P0. Fix empty snapshots for minimized windows / root area=0

**目标**：窗口最小化或 root `BoundingRectangle` 面积为 0 时，`get_tree` 不应因为 `win_rect.intersects(bbox)` 把整棵树滤空。

**Goal**: When a window is minimized or its root `BoundingRectangle` area is 0, `get_tree` must not filter the entire tree to empty through `win_rect.intersects(bbox)`.

范围 / Scope:

- `src/computer_use_mcp/drivers/windows.py`
- 必要时补只读 probe 或 smoke，验证“不抢前台也不会误报整树为空”。
  Add a read-only probe or smoke if needed to verify that the tree is not falsely reported as empty without stealing foreground.

验收 / Acceptance:

- 最小化 Notepad / Chrome 返回明确状态或可用节点，而不是静默 0 节点。
  Minimized Notepad / Chrome returns explicit status or usable nodes, not a silent 0-node result.
- 生产代码不引入“读快照前强制 activate”的 hack。
  Production code does not force activation before reading snapshots.
- `git diff --check` 通过。
  `git diff --check` passes.

### P1. 固化浏览器 UIA 快照热身策略

### P1. Stabilize browser UIA snapshot warmup

**目标**：Chrome / Chromium 首次读取 UIA 树时可能懒加载 accessibility，第一次结果可能不完整；目标是把这个行为做成稳定策略。

**Goal**: Chrome / Chromium may lazily load accessibility on first UIA read, producing incomplete first results. The goal is to turn this into a stable strategy.

验收 / Acceptance:

- 内容页冷启动读取不依赖人工等待。
  Content-page cold reads do not depend on manual waiting.
- 如果仍截断，返回结果明确提示 truncation / incomplete。
  If still truncated, results explicitly report truncation / incompleteness.
- 不为了浏览器读取而抢前台。
  Browser reads do not steal foreground.

### P2. 加“人最近在操作则退避”的串行让路机制

### P2. Add human-active yielding

**目标**：同一桌面下，人和 agent 共享前台窗口与物理鼠标。第一阶段只做串行让路，不做假并行。

**Goal**: On the same desktop, user and agent share foreground and physical mouse. The first phase implements serial yielding, not fake parallelism.

验收 / Acceptance:

- 人刚动过鼠标或键盘时，争用类动作返回 `HUMAN_ACTIVE` 或等价可解释拒绝。
  When the user recently used mouse or keyboard, contending actions return `HUMAN_ACTIVE` or an equivalent explainable rejection.
- 无忙等、无后台线程抢控制权。
  No busy waiting and no background thread that seizes control.
- 阈值可通过环境变量调整，默认保守。
  Threshold is configurable by environment variable and conservative by default.

## 2. 第二阶段：真实 app 场景验证 / Phase 2: Real-App Validation

### P3. 浏览器内容页压测 / Browser content-page stress test

**目标**：用真实内容页决定是否需要 parent ref / 层级结构，而不是先做抽象设计。

**Goal**: Use real content pages to decide whether parent refs or hierarchy are needed, instead of designing abstractions first.

观察项 / Observe:

- `max_nodes=200` 是否频繁截断。
  Whether `max_nodes=200` truncates frequently.
- 同名按钮 / 链接是否导致 ref 消歧困难。
  Whether duplicate button / link names make ref disambiguation difficult.
- `find(query)` 是否足够省 token。
  Whether `find(query)` saves enough tokens.
- 文本 run 是否需要合并。
  Whether text runs need merging.

产出 / Output:

- 将结论写回 [DESIGN.md](DESIGN.md)。
  Write conclusions back to [DESIGN.md](DESIGN.md).
- 如果 parent ref 必须做，再列 contract 影响；否则只增强序列化层。
  If parent refs are necessary, list contract impact; otherwise improve only serialization.

### P4. 进程树闸门实测 / Process-tree gate validation

**目标**：验证 allowlist 的“祖先进程命中即放行”在真实多进程应用中成立；微信只是可选样本，不是产品前提。

**Goal**: Verify ancestor-process allowlist authorization in a real multi-process application. WeChat is an optional sample, not a product prerequisite.

验收 / Acceptance:

- 主进程与渲染 / helper 子进程的归属链能被正确识别。
  Owner chains for a primary process and renderer/helper child processes are identified correctly.
- 拒绝路径和放行路径都有记录。
  Both rejection and allow paths are recorded.
- 不扩大默认 allowlist。
  Default allowlist is not expanded.

## 3. 第三阶段：工程化硬化 / Phase 3: Engineering Hardening

### P5. 把可纯测的部分收敛成 pytest

### P5. Move pure-testable logic into pytest

优先覆盖 / Priority coverage:

- `core.Session` 的 ref 表、序列化、失效重定位逻辑。
  `core.Session` ref table, serialization, and stale-ref relocation.
- `gate.Gate` 的 allowlist / 祖先进程判断。
  `gate.Gate` allowlist and ancestor-process logic.
- `safety` 的危险词判断、截图打码边界。
  `safety` dangerous-word detection and screenshot-redaction boundaries.
- `audit.AuditLog` 的 JSONL 写入格式。
  `audit.AuditLog` JSONL write format.

保留真实桌面的 `scripts/smoke_*.py` 作为 on-device 集成测试，不伪装成无副作用单测。

Keep real-desktop `scripts/smoke_*.py` as on-device integration tests; do not pretend they are side-effect-free unit tests.

### P6. 版本与发布卫生 / Version and release hygiene

- `pyproject.toml` 版本升到能代表目标状态的版本，例如 `0.1.0`。
  Bump `pyproject.toml` version to represent the target state, for example `0.1.0`.
- 决定 License：继续私有就明确写“暂不发布”；准备开源再补 LICENSE。
  Decide the license: if private, state "not published"; if open-source, add LICENSE.
- 清理已合并分支和过期文档说法。
  Clean up merged branches and stale document wording.

## 4. 后台自动操作者升级路线 / Background Operator Upgrade Route

目标场景：用户在主桌面全屏游戏或正常工作时，agent 在后台替用户操作另一个应用。

Target scenario: the user is gaming full-screen or working on the main desktop while the agent operates another app in the background.

| 目标 / Target | 可行性 / Feasibility | 边界 / Boundary |
| --- | --- | --- |
| 受限同桌面 UIA worker<br>Limited same-desktop UIA worker | 不可靠 / Not reliable | 受控 Notepad `SetValue` 在输入 tick 未变化时仍切换前台；不作为产品能力<br>Controlled Notepad `SetValue` changed foreground without an input-tick change; not a product capability |
| 真隔离后台操作者<br>Truly isolated background operator | 高，但要独立运行环境<br>High, but needs isolated runtime | agent 需要自己的前台、鼠标、键盘、截图；走 RDP / 第二 Session / VM / Xvfb<br>Agent needs its own foreground, mouse, keyboard, screenshot source; use RDP / second Session / VM / Xvfb |
| 同桌面完整后台操作者<br>Full same-desktop background operator | 不成立 / Not viable | 坐标点击、全局键盘、主屏截图共享同一桌面资源<br>Coordinate clicks, global keyboard, and main-screen screenshots share desktop resources |

### P7. v1.1：本机全权限控制模式 / Full-control local mode

- 引入显式运行模式：`safe_local`、`full_control_local`、`isolated_worker`。
  Introduce explicit operating modes: `safe_local`, `full_control_local`, and `isolated_worker`.
- `full_control_local` 允许 agent 使用前台、鼠标和键盘操作任意本机窗口。
  `full_control_local` allows the agent to use foreground, mouse, and keyboard on any local window.
- 全权限模式必须明确授权；急停和审计保持启用，危险确认由策略配置。
  Full-control mode requires explicit authorization; e-stop and audit remain enabled, while dangerous confirmation is policy-configurable.
- 审计记录运行模式与动作结果。
  Audit records the operating mode and action outcome.

### P8. v1.2：VM worker 原型 / VM worker prototype

- 在独立 Windows VM 内启动 worker，拥有独立桌面、截图源、鼠标和键盘。
  Start a worker in an independent Windows VM with its own desktop, screenshot source, mouse, and keyboard.
- 主机为 Windows Home 时优先 VM，不把 RDP Host 作为默认实现路径。
  On Windows Home hosts, prefer a VM rather than RDP Host as the default implementation path.
- 先验证 worker 内端到端 MCP 操作，再设计主机编排。
  Validate end-to-end MCP control inside the worker before designing host orchestration.

### P9. v2：隔离 worker 编排 / Isolated worker orchestration

优先路线 / Priority routes:

1. Windows VM。
   Windows VM.
2. Windows 第二登录 Session（环境支持时）。
   Windows second login Session when the environment supports it.
3. Linux Xvfb / 独立 DISPLAY。
   Linux Xvfb / independent DISPLAY.
4. macOS VM / 第二台机。
   macOS VM / second machine.

设计影响 / Design impact:

- worker 需要自己的 driver 实例、截图源、输入源、allowlist、安全审计。
  Worker needs its own driver instance, screenshot source, input source, allowlist, and audit.
- `capture_screen` 不能假设主屏帧缓冲。
  `capture_screen` cannot assume the main-screen framebuffer.
- MCP server 需要区分“本机桌面 worker”和“隔离 worker”。
  MCP server must distinguish local desktop workers from isolated workers.

### P10. v2.x：Windows 隐藏 Desktop 实验 / Windows hidden Desktop experiment

**目标**：评估 `CreateDesktop` / `SwitchDesktop` 这类 Windows 内核 Desktop 对象能否作为轻量隔离层。

**Goal**: Evaluate whether Windows kernel Desktop objects such as `CreateDesktop` / `SwitchDesktop` can serve as a lightweight isolation layer.

结论：只作为实验路线，不作为 v2 首选。

Conclusion: experimental route only, not the preferred v2 route.

## 5. 非第一阶段目标 / Not First-Phase Targets

- macOS / Linux driver：等 Windows MVP 稳定后再做。
  macOS / Linux drivers: implement after Windows MVP is stable.
- 隐藏桌面真并行：优先考虑 RDP / VM / 第二 Session。
  Hidden-desktop true parallelism: prefer RDP / VM / second Session first.
- 默认开启全权限模式：本机全权限控制必须显式授权。
  Full-control mode enabled by default: local full control must require explicit authorization.
- 大规模重构 contract：由实现经验驱动，不预先重写。
  Large contract rewrite: driven by implementation evidence, not preemptive redesign.

## 6. 推荐开工顺序 / Recommended Start Order

```powershell
git status --short --branch
git switch -c codex/fix-minimized-snapshot

# 改 P0 / Implement P0
.\.venv\Scripts\python.exe -m compileall -q src scripts
git diff --check

# 如果改了真实桌面路径，再跑对应 smoke；注意会操作桌面
# If real desktop paths changed, run the corresponding smoke; it will operate the desktop.
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe scripts\smoke_core.py
```

完成 P0 后再进入 P1。不要同时开 P0/P1/P2，三者都碰感知 / 前台边界，混在一个提交里会降低可回滚性。

Finish P0 before starting P1. Do not mix P0/P1/P2 in one change, because all three touch perception and foreground boundaries and would reduce rollback clarity.

如果要验证“后台自动操作者”方向，先开 P7，不要直接做 P9/P10。

If validating the background-operator direction, start with P7 rather than jumping directly to P9/P10.
