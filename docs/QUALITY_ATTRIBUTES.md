# Quality Attributes / 质量属性 — computer-use-mcp

> 本文按**预期实现版本**书写，记录目标系统必须满足的质量属性。每个属性都对应设计约束和验收信号，用于后续实现、测试和 review。
>
> This document describes the quality attributes required by the **target implementation**. Each attribute includes design constraints and acceptance signals for implementation, testing, and review.

## 1. Safety / 安全默认拒绝

**目标**：agent 只能在明确授权边界内操作桌面；危险动作必须可拦截、可确认、可追溯。

**Goal**: The agent can operate the desktop only inside explicit authorization boundaries. Dangerous actions must be interceptable, confirmable, and traceable.

**设计约束 / Design constraints**:

- 动作类工具默认先过 allowlist gate。
  Action tools pass through the allowlist gate by default.
- allowlist 基于窗口 owner-chain / 进程树归属链。
  The allowlist is based on window owner chains and process ownership chains.
- 危险动作需要二次确认。
  Dangerous actions require a second confirmation.
- 急停触发后锁死所有动作，直到 server 重启。
  After e-stop, all actions are locked until the server restarts.
- 本机全权限模式必须显式授权，且急停和审计不可关闭。
  Full-control local mode must be explicitly authorized, and e-stop and audit cannot be disabled.

**验收信号 / Acceptance signals**:

- 非授权应用上的 foreground-required 动作被拒绝。
  Foreground-required actions against unauthorized apps are rejected.
- 审计日志记录动作、参数摘要、决策和结果。
  Audit logs record action, argument summary, decision, and result.
- `screenshot` 和 `ui_snapshot` 不泄露已知敏感窗口 / password 字段。
  `screenshot` and `ui_snapshot` do not leak known sensitive windows or password fields.

## 2. Correctness / 桌面操作正确性

**目标**：模型看到的位置、控件 ref 和实际执行目标一致。

**Goal**: The position seen by the model, the control ref, and the actual execution target are consistent.

**设计约束 / Design constraints**:

- 截图像素、控件 bbox、坐标点击使用同一坐标空间。
  Screenshot pixels, control bounding boxes, and coordinate clicks use the same coordinate space.
- Windows 进程启动早期必须启用 DPI awareness。
  DPI awareness must be enabled early in the Windows process.
- ref 路径不合成坐标点击，优先调用平台无障碍模式。
  Ref paths do not synthesize coordinate clicks; they prefer platform accessibility patterns.
- ref 失效时只做一次可解释重定位，失败则要求重新 snapshot。
  A stale ref gets at most one explainable relocation attempt; failure requires a new snapshot.

**验收信号 / Acceptance signals**:

- DPI 缩放下 bbox 仍与截图对齐。
  Bounding boxes still align with screenshots under DPI scaling.
- `click(ref)` 不受遮挡和焦点影响。
  `click(ref)` is unaffected by occlusion and focus.
- 失效 ref 返回 `STALE_ELEMENT` 或等价可解释错误，而不是误点其他控件。
  Stale refs return `STALE_ELEMENT` or an equivalent explainable error instead of clicking the wrong control.

## 3. Reliability / 真实桌面稳定性

**目标**：面对真实 app 的窗口状态、owned 对话框、UIA / AX / AT-SPI 懒加载和前台抖动时，不静默失败。

**Goal**: The system does not fail silently when real apps introduce window-state changes, owned dialogs, lazy accessibility loading, or foreground jitter.

**设计约束 / Design constraints**:

- `list_windows` 包含 owned 对话框。
  `list_windows` includes owned dialogs.
- `get_tree` 对最小化 / root area=0 情况返回明确状态或可用节点，不能静默 0 节点。
  For minimized windows or root area=0, `get_tree` returns an explicit state or usable nodes, not a silent 0-node result.
- 浏览器快照使用 warmup 或稳定读取策略。
  Browser snapshots use warmup or another stable-read strategy.
- 感知路径不能靠强制抢前台来掩盖问题。
  Perception paths cannot hide issues by forcing foreground activation.

**验收信号 / Acceptance signals**:

- 最小化窗口不产生误导性空快照。
  Minimized windows do not produce misleading empty snapshots.
- 浏览器内容页冷启动读取结果稳定，或明确提示截断 / 不完整。
  Browser content pages produce stable cold-start reads or explicitly report truncation / incompleteness.
- on-device smoke 覆盖真实窗口和对话框路径。
  On-device smokes cover real windows and dialog paths.

## 4. Human Coexistence / 人机共存

**目标**：同一桌面下不假装可以真并行；会争用鼠标、键盘、前台的动作必须让路。

**Goal**: On the same desktop, the system does not pretend true parallelism exists. Actions that contend for mouse, keyboard, or foreground must yield.

**设计约束 / Design constraints**:

- 坐标点击、全局按键、无 ref 输入、激活窗口属于 foreground-required 动作。
  Coordinate clicks, global keys, ref-less typing, and window activation are foreground-required actions.
- 人最近有输入时，foreground-required 动作退避。
  Foreground-required actions yield when recent human input is detected.
- 同桌面 ref 动作不保证后台兼容：受控 Notepad `SetValue` 已在输入 tick 未变化时切换前台。
  Same-desktop ref actions are not guaranteed background-compatible: controlled Notepad `SetValue` changed foreground without an input-tick change.
- 真后台操作者走独立 VM / Session / Xvfb，而不是单桌面硬凿。
  True background operators use independent VM / session / Xvfb environments rather than forcing same-desktop parallelism.

**验收信号 / Acceptance signals**:

- 人刚操作过鼠标/键盘时，争用类动作返回 `HUMAN_ACTIVE` 或等价可解释拒绝。
  When the user recently used mouse or keyboard, contending actions return `HUMAN_ACTIVE` or an equivalent explainable rejection.
- 审计日志记录运行模式、worker 标识和动作结果。
  Audit logs record the operating mode, worker identity, and action result.
- 不通过 `activate_window` 伪装后台感知或后台截图。
  `activate_window` is not used to fake background perception or background screenshots.

## 5. Observability / 可观测与可诊断

**目标**：当 agent 拒绝、失败、截断或误读时，人能快速判断问题在安全闸门、驱动、无障碍树、坐标空间还是应用本身。

**Goal**: When the agent rejects, fails, truncates, or misreads, a human can quickly identify whether the issue is in the safety gate, driver, accessibility tree, coordinate space, or app itself.

**设计约束 / Design constraints**:

- 动作结果包含可解释失败原因。
  Action results include explainable failure reasons.
- `ui_snapshot` / `find` 返回截断数量，不静默丢节点。
  `ui_snapshot` and `find` return truncation counts and do not silently drop nodes.
- 一次性真实 app 探针写入 `out/`，正式回归脚本写入 `scripts/`。
  One-off real-app probes write to `out/`; formal regression scripts live in `scripts/`.
- 审计日志采用 JSONL，便于 grep、diff 和后续分析。
  Audit logs use JSONL for grep, diff, and later analysis.

**验收信号 / Acceptance signals**:

- `DENIED by gate`、`STALE_ELEMENT`、`OUT_OF_BOUNDS`、`DRIVER_ERROR` 等路径能区分。
  Paths such as `DENIED by gate`, `STALE_ELEMENT`, `OUT_OF_BOUNDS`, and `DRIVER_ERROR` are distinguishable.
- 浏览器内容页压测能产出节点数量、截断、角色分布和歧义证据。
  Browser content-page stress tests produce node counts, truncation, role distribution, and ambiguity evidence.
- 失败 smoke 能从输出定位到具体层。
  Failed smokes expose enough output to locate the failing layer.

## 6. Testability / 可测试性

**目标**：纯逻辑可自动测试，真实桌面副作用用明确 smoke 覆盖，不把两者混在一起。

**Goal**: Pure logic is automatically testable, while real-desktop side effects are covered by explicit smokes. The two are not mixed.

**设计约束 / Design constraints**:

- `core.Session`、`gate`、`safety`、`audit` 用 pytest 覆盖。
  `core.Session`, `gate`, `safety`, and `audit` are covered with pytest.
- 真实桌面脚本保留为 on-device smoke，并在文档中标注副作用。
  Real-desktop scripts remain on-device smokes and document their side effects.
- 新增真实 app 能力前先写 probe 观察无障碍树实际形态。
  Before adding real-app support, write probes to observe the actual accessibility tree shape.

**验收信号 / Acceptance signals**:

- `python -m pytest` 能跑无桌面副作用的测试集合。
  `python -m pytest` runs a test set without desktop side effects.
- `scripts/smoke_*.py` 覆盖每个关键桌面路径。
  `scripts/smoke_*.py` covers each critical desktop path.
- 修改驱动后至少跑对应 smoke 和 `git diff --check`。
  After driver changes, the corresponding smoke and `git diff --check` are run.

## 7. Portability / 可移植性

**目标**：通用核心不绑定 Windows；平台差异被限制在 driver 边界和运行环境编排中。

**Goal**: The shared core is not bound to Windows. Platform differences are constrained to driver boundaries and runtime orchestration.

**设计约束 / Design constraints**:

- `contract.py` 是核心和平台驱动唯一边界。
  `contract.py` is the only boundary between the core and platform drivers.
- 通用核心不得 import Windows / macOS / Linux 专属模块。
  The shared core must not import Windows / macOS / Linux-specific modules.
- Contract 变更必须升版本并更新 [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md)。
  Contract changes must bump the version and update [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md).
- 隔离 worker 建模为运行环境能力，不塞进普通平台 driver 分支。
  Isolated workers are modeled as runtime capabilities, not as normal platform-driver branches.

**验收信号 / Acceptance signals**:

- 新平台可以通过实现 Driver Contract 接入。
  New platforms can integrate by implementing the Driver Contract.
- 核心测试可以用 fake driver 跑。
  Core tests can run with a fake driver.
- 平台 driver 可以独立 smoke，而不改 MCP 工具语义。
  Platform drivers can be smoked independently without changing MCP tool semantics.

## 8. Performance / 性能与 token 成本

**目标**：桌面感知足够快，返回内容足够小，模型能在有限 token 内稳定决策。

**Goal**: Desktop perception is fast enough, returned content is compact enough, and models can make stable decisions within a limited token budget.

**设计约束 / Design constraints**:

- `get_tree` 裁剪下推到驱动，不把原始全树传给核心。
  `get_tree` pruning is pushed down into the driver; raw full trees are not passed to the core.
- `ui_snapshot` 默认扁平、短字段、节点上限。
  `ui_snapshot` is flat by default, uses short fields, and has a node cap.
- 大屏和复杂页面优先用 `find(query)` 缩小上下文。
  Large screens and complex pages prefer `find(query)` to narrow context.
- 文本 run 合并和 parent ref 由真实内容页证据驱动。
  Text-run merging and parent refs are driven by real content-page evidence.

**验收信号 / Acceptance signals**:

- 默认 snapshot 超限时有明确 `truncated`。
  Default snapshots clearly report `truncated` when over the cap.
- `find()` 对常见查询能明显减少返回内容。
  `find()` significantly reduces returned content for common queries.
- 浏览器内容页压测能说明是否需要 parent ref 或序列化增强。
  Browser content-page stress tests can justify whether parent refs or serialization enhancements are needed.

## 9. Maintainability / 可维护性

**目标**：项目按小步验证推进，不因为过早抽象或混合提交失去可回滚性。

**Goal**: The project advances through small validated steps and remains reversible by avoiding premature abstraction and mixed-scope commits.

**设计约束 / Design constraints**:

- 影响感知、前台、安全边界的改动分开提交。
  Changes that affect perception, foreground behavior, or safety boundaries are committed separately.
- 新动作工具统一经过安全 gate、危险确认和 audit。
  New action tools go through the safety gate, dangerous-action confirmation, and audit.
- 一次性 probe 不进入正式代码路径。
  One-off probes do not enter the production code path.
- 文档记录设计取舍，避免重复争论已验证过的问题。
  Documentation records design tradeoffs to avoid repeating already-validated debates.

**验收信号 / Acceptance signals**:

- 每个里程碑能对应到具体 smoke / probe / 文档结论。
  Each milestone maps to a concrete smoke, probe, or documentation conclusion.
- `README.md` 讲目标能力，`DESIGN.md` 讲目标架构，`EXECUTION_PLAN.md` 讲实施路线，`TECH_STACK.md` 讲技术边界，本文讲质量属性。
  `README.md` covers target capabilities, `DESIGN.md` target architecture, `EXECUTION_PLAN.md` implementation path, `TECH_STACK.md` technology boundaries, and this document quality attributes.
- review 时能按质量属性逐项检查改动风险。
  Reviews can check change risk against the quality attributes one by one.
