# EXECUTION_PLAN — 下一阶段开工计划

> 当前阶段：Windows v1 技术闭环已完成，下一步不是继续堆功能，而是把它从“可演示 Alpha”推进到“真实应用可稳定使用的 MVP”。

本计划按“能最快降低不确定性、最少扩大架构面”的顺序排。默认只做 Windows 路径；macOS / Linux、隐藏桌面 / VM、后台目标授权都先不展开。

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

## 4. 暂不做

- **macOS / Linux driver**：等 Windows MVP 稳定后再做，避免同时调三套 accessibility 栈。
- **隐藏桌面 / VM 真并行**：这是运行环境能力，不应塞进 v1 driver 抽象。
- **按动作目标窗口授权的 gate**：价值明确，但安全边界变化大，必须单独评审。
- **大规模重构 contract**：当前 contract 已能支撑 Windows v1，优先用实现经验驱动下一次版本变化。

---

## 5. 推荐开工顺序

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
