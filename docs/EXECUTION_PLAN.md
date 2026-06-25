# EXECUTION_PLAN — 下一阶段开工计划

> 当前阶段：Windows v1 技术闭环已完成，下一步不是继续堆功能，而是把它从“可演示 Alpha”推进到“真实应用可稳定使用的 MVP”。

本计划按“能最快降低不确定性、最少扩大架构面”的顺序排。默认只做 Windows 路径；macOS / Linux、隐藏桌面 / VM 作为 v2 路线记录，不作为当前阶段默认开工项。

---

## 0. 开工原则

- **先修已知 bug，再做新能力**：最小化窗口导致 `ui_snapshot` 读空，是明确缺陷，优先级高于 parent ref、跨平台等设计题。
- **不要靠抢前台修感知问题**：`ui_snapshot` / `screenshot` 属于感知路径，不应强行 `activate_window`，否则会和真人操作直接争用。
- **安全默认不放松**：当前动作闸门按前台 allowlist 判断。是否改成“按动作目标窗口授权”单独决策，不能顺手改。
- **真实桌面测试要显式标注副作用**：会启动应用、移动窗口、点击/输入的脚本继续放 `scripts/smoke_*.py`；一次性探针放 `out/`，不入库。
- **Contract v1.0 不随便动**：改 `contract.py` 的字段或原语签名，必须同步改 `docs/DRIVER_CONTRACT.md` 并说明版本影响。

---

## 1. 第一阶段：Windows v1 稳定化

### P0. 修复最小化 / root area=0 导致快照清空

**目标**：窗口最小化或 root `BoundingRectangle` 面积为 0 时，`get_tree` 不应因为 `win_rect.intersects(bbox)` 把整棵树滤空。

建议范围：

- `src/computer_use_mcp/drivers/windows.py`
- 必要时补一个只读 probe 或 smoke，验证“不抢前台也不会误报整树为空”

验收标准：

- 对最小化的 Notepad / Chrome，`ui_snapshot` 返回明确状态或可用节点，而不是静默 0 节点。
- 生产代码里不引入“读快照前强制 activate”的 hack。
- `git diff --check` 通过。

### P1. 固化浏览器 UIA 快照热身策略

**目标**：Chrome / Chromium 首次读取 UIA 树时会懒加载 a11y，第一次结果可能不完整；要把这个行为做成稳定策略。

建议范围：

- 先用内容页 probe 确认现象：第一次 / 第二次节点数量、Document/Hyperlink 数量差异。
- 再决定实现位置：优先放在 `Session.ui_snapshot` 或 Windows driver 内部的浏览器特例，不改变公共 contract。

验收标准：

- 内容页冷启动读取时，不依赖人工等待也能拿到稳定快照。
- 如果仍截断，返回结果要明确提示 truncation，不能静默丢节点。
- 不为了浏览器读取而抢前台。

### P2. 加“人最近在操作则退避”的串行让路机制

**目标**：同一桌面下，人和 agent 共享前台窗口与物理鼠标。v1 先做串行让路，不做假并行。

建议实现：

- Windows 下用 `GetLastInputInfo` 判断最近 N 秒是否有人类输入。
- 只对会争用前台/光标的动作生效：坐标 `click(x,y)`、`key()`、无 ref `type()`、`activate_window()`。
- 对 ref 路径 `SetValue` / `Invoke` / `Select` 暂不放松 gate；是否允许后台目标授权另开决策。

验收标准：

- 人刚动过鼠标/键盘时，争用类动作返回可解释的拒绝结果，例如 `HUMAN_ACTIVE` / `DENIED by human activity`。
- 无忙等、无后台线程抢控制权。
- 默认阈值可通过环境变量调整，默认值保守。

---

## 2. 第二阶段：真实 app 场景验证

### P3. 浏览器内容页压测

**目标**：用真实内容页决定是否需要 parent ref / 层级结构，而不是先做抽象设计。

要观察：

- `max_nodes=200` 是否频繁截断。
- 同名按钮/链接是否导致 ref 消歧困难。
- `find(query)` 是否足够省 token。
- 文本 run 是否需要合并。

产出：

- 将结论写回 `docs/DESIGN.md`。
- 如果 parent ref 必须做，再列 contract 影响；否则只在序列化层增强。

### P4. 微信进程树闸门实测

**目标**：验证 allowlist 的“祖先进程命中即放行”是否覆盖微信 / 子渲染进程场景。

验收标准：

- `weixin.exe` / `WechatAppEx` 等进程树能被正确识别。
- 拒绝路径和放行路径都有记录。
- 不扩大默认 allowlist。

---

## 3. 第三阶段：工程化硬化

### P5. 把可纯测的部分收敛成 pytest

优先覆盖：

- `core.Session` 的 ref 表、序列化、失效重定位逻辑（用 fake driver）。
- `gate.Gate` 的 allowlist / 祖先进程判断（可 mock）。
- `safety` 的危险词判断、截图打码边界。
- `audit.AuditLog` 的 JSONL 写入格式。

保留：

- 真实桌面的 `scripts/smoke_*.py` 继续作为 on-device 集成测试，不强行伪装成无副作用单测。

验收标准：

- `python -m pytest` 至少能跑一批无桌面副作用的测试。
- README / HANDOFF 区分“纯测试”和“真实桌面冒烟”。

### P6. 版本与发布卫生

- `pyproject.toml` 版本从 `0.0.0` 升到能代表当前状态的版本，例如 `0.1.0`。
- 决定 License：继续私有就明确写“暂不发布”；准备开源再补 LICENSE。
- 清理已合并分支和过期文档说法。

---

## 4. 后台自动操作者升级路线

目标场景：用户在主桌面全屏游戏或正常工作时，agent 在后台替用户操作另一个应用。

这里必须拆成两个目标，不能混成一个“后台开关”：

| 目标 | 可行性 | 边界 |
| --- | --- | --- |
| **受限后台 UIA worker** | 高 | 只做 `SetValue` / `Invoke` / `Select` 这类 ref 动作；不动鼠标、不抢焦点、不发全局键盘 |
| **真隔离后台操作者** | 高，但要独立运行环境 | agent 需要自己的前台、鼠标、键盘、截图；应走 RDP / 第二 Session / VM / Xvfb |
| **同桌面完整后台操作者** | 不成立 | 坐标点击、全局键盘、主屏截图都共享同一个桌面资源，会和用户直接争用 |

### P7. v1.1：受限后台 ref 动作

**目标**：允许 agent 在用户看其他应用时，对后台 allowlist 窗口执行安全的 ref 动作。

建议实现：

- 动作分级：
  - `background_safe`：按 ref 的 `SetValue` / `Invoke` / `Select`。
  - `foreground_required`：坐标 `click(x,y)`、`key()`、无 ref `type()`、`activate_window()`。
- 新增 gate 模式：从“前台进程 allowlist”扩展为“动作目标窗口 owner-chain allowlist”。
- 默认关闭，需要显式环境变量开启，例如 `CUMCP_BACKGROUND_REF_ACTIONS=1`。
- 后台动作必须进入 audit，日志里明确记录 `background_ref_action=true`、目标 hwnd、目标进程链。

验收标准：

- 用户前台在非 allowlist 应用时，agent 可以对后台 allowlist 窗口执行 ref `SetValue` / `Invoke`。
- 坐标点击、全局按键、无 ref 输入、激活窗口仍被拒绝。
- 拒绝信息能说明是 `FOREGROUND_REQUIRED`，而不是笼统失败。
- 安全文档明确说明：开启后 agent 可能操作用户看不见的后台窗口。

### P8. v1.2：后台感知增强

**目标**：让后台窗口可被更可靠地读取，但不承诺视觉截图等同于前台。

建议方向：

- 先完成 P0 / P1：最小化窗口快照、浏览器 a11y warmup。
- 研究 Windows 窗口级截图：`PrintWindow` / DWM thumbnail / app-specific fallback。
- `screenshot` 继续默认主屏帧缓冲；窗口级截图如果实现，应作为显式能力或参数，不能悄悄改变语义。

验收标准：

- 后台窗口 `ui_snapshot` 比当前更稳定。
- 对无法截图的后台窗口返回明确错误或降级说明。
- 不通过抢前台来伪造后台截图。

### P9. v2：独立 worker 桌面 / Session

**目标**：实现“用户全屏游戏，agent 像另一个操作者一样完整操作电脑”的真后台能力。

优先路线：

1. Windows RDP / 第二登录 Session / VM。
2. Linux Xvfb / 独立 DISPLAY。
3. macOS VM / 第二台机。

设计影响：

- worker 需要自己的 driver 实例、截图源、输入源、allowlist、安全审计。
- `capture_screen` 不能假设主屏帧缓冲。
- MCP server 需要区分“本机桌面 worker”和“隔离 worker”。
- 这属于运行环境编排，不应塞进当前 Windows driver 的普通分支里。

### P10. v2.x：Windows 隐藏 Desktop 实验

**目标**：评估 `CreateDesktop` / `SwitchDesktop` 这类 Windows 内核 Desktop 对象能否作为轻量隔离层。

风险：

- 现代浏览器、GPU 窗口、输入法、权限/UAC、剪贴板、窗口创建位置都可能踩坑。
- 截图和 UIA 访问方式会明显不同于当前主桌面路径。
- 工程复杂度接近“自己维护一个 hVNC/隐藏桌面自动化栈”。

结论：只作为实验路线，不作为 v2 首选。

---

## 5. 暂不做

- **macOS / Linux driver**：等 Windows MVP 稳定后再做，避免同时调三套 accessibility 栈。
- **隐藏桌面真并行**：这是运行环境能力，不应塞进 v1 driver 抽象；优先考虑 RDP / VM / 第二 Session。
- **默认开启后台动作**：后台 ref 动作必须显式 opt-in，不能作为默认行为。
- **大规模重构 contract**：当前 contract 已能支撑 Windows v1，优先用实现经验驱动下一次版本变化。

---

## 6. 推荐开工顺序

```powershell
git status --short --branch
git switch -c codex/fix-minimized-snapshot

# 改 P0
.\.venv\Scripts\python.exe -m compileall -q src scripts
git diff --check

# 如果改了真实桌面路径，再跑对应 smoke；注意会操作桌面
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe scripts\smoke_core.py
```

完成 P0 后再进入 P1。不要同时开 P0/P1/P2，三者都碰感知/前台边界，混在一个提交里会降低可回滚性。

如果要验证“后台自动操作者”方向，先开 P7，不要直接做 P9/P10。P7 能用最小改动验证核心价值：标准 UIA app 是否值得支持后台 ref 操作。
