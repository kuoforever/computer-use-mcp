# 设计文档 — computer-use-mcp

> 状态：设计中。本文件记录已拍板的决策与待定问题，是后续写代码的依据。

## 0. 三条总原则

1. **与模型无关**：MCP server 只暴露工具，不关心谁在调。换模型不改 server。
2. **双模式输入**：同时输出 `screenshot`（图，视觉模型用）和 `ui_snapshot`（文本树，纯文本模型用）。客户端按模型能力各取所需。
3. **Windows 优先，接口预留**：把 `Screen / Input / Tree` 抽成接口，先实现 Windows，将来好上 macOS(AX) / Linux(AT-SPI)。

### 为什么是双模式？——DeepSeek 的硬限制

电脑操作 = 看屏幕 → 决定点哪 → 输出坐标，**要求视觉**。
而 **DeepSeek 主力 API（V3 / R1）是纯文本、不吃图片**（DeepSeek-VL 是另一套开源权重，不在主流 API）。
所以纯文本模型只能走 `ui_snapshot`（按控件名/ref 点击），不能靠截图坐标。

**驱动模型矩阵：**

| 模型 | 视觉 | 走哪条路 |
| --- | --- | --- |
| Claude / GPT-4o | ✅ | screenshot + 坐标（也可用 ref） |
| Qwen2.5-VL / UI-TARS / GLM-4V | ✅ | screenshot + 坐标（专练过 GUI grounding） |
| DeepSeek V3 / R1 | ❌ | **仅** ui_snapshot + ref |

> 若目标是"中国模型做电脑操作"，**视觉系（Qwen-VL / UI-TARS）比 DeepSeek 更顺**；DeepSeek 更适合当"读文本树做决策"的大脑。

---

## 架构：驱动契约（ports & adapters）

**采纳跨平台驱动架构**：通用核心 + 平台原生驱动，边界是一份语言无关的契约（详见 [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md)）。

| 层 | 放什么 | 平台相关 |
| --- | --- | --- |
| **通用核心** | MCP 工具/schema、`ui_snapshot` 序列化、裁剪**策略**、`find` 语义、`ref` 表与生命周期、**安全层**（allowlist/闸门判定/脱敏/审计/二次确认）、agent loop、config | ❌ |
| **平台驱动** | 截屏、枚举窗口+前台+**进程归属链**、取无障碍树、invoke/set-value/select、模拟键鼠、DPI/坐标归一 | ✅ 每平台一份 |

**三条铁律**（详见契约）：① 裁剪下推到驱动；② 单一坐标空间（截图像素 = bbox = click 坐标）；③ 闸门"查归属链"是驱动原语、"判 allowlist"是核心。

**落地形态（A/B）待定**——契约先定，实现分阶段：
- **A**：核心 + Win 驱动都用 Python（进程内），最快出 v0。
- **B**：核心 TS/Go + 平台原生 helper（Win=C#/FlaUI、Mac=Swift），最稳最未来化，但摊子大且核心语言改掉 Python。
> 契约不变，A/B 换里子不伤上层。真要上 Mac 时再按平台逐个选。

---

## A. `ui_snapshot` 表示与裁剪（双模式的心脏）

- **格式**：扁平列表，不是缩进树。每行示例：
  ```
  ref_7 | button "发送" | (1003,565,50,24) | enabled
  ```
  扁平 + 稳定 `ref` → 最省 token、最好引用。参考 Playwright accessibility snapshot / 浏览器扩展的 read_page。
- **裁剪（最难）**：只保留**前台窗口**内、**可见 + 可交互**的元素（button / edit / list item / checkbox / link / menu item…），扔掉装饰容器和离屏节点。
- **`find(query)` 工具**：模型先按名字/角色找，只回匹配项，避免每步全量树。大屏几乎必须。
- **v0 裁剪默认值（已定）**：作用域 = 仅前台窗口；只收 可见(IsOffscreen=false) + 在窗口内 + 可交互（白名单 ControlType：Button / Edit / CheckBox / RadioButton / ComboBox / List / ListItem / MenuItem / Hyperlink / Tab / TabItem / Tree / TreeItem / Slider）；**元素上限 200**，超限提示用 `find()` 并**记录被截断数量**（不静默砍）；每元素 `ref | type | name(≤100字) | bbox | states`；**password 控件不回 value**。
- **待定**：深度上限？是否保留少量层级关系（parent ref）帮助消歧？文本 run 怎么合并？

## B. 统一动作模型 —— 一个 `click`，两条腿

- 视觉模型 → `click({x, y})`
- 文本模型 → `click({ref})`
- **关键决策：ref 路径不合成坐标点击，直接调 UIA 模式**
  - 点击 → `InvokePattern` / `SelectionItemPattern`
  - 输入 → `ValuePattern.SetValue`（而非模拟键盘）
  - 好处：不受遮挡 / 焦点 / DPI / 前台进程抖动影响，比"移到 bbox 中心点一下"稳得多。
- 坐标点击只留给：视觉模型、以及 UIA 抓不到的画布类控件（游戏 / Canvas / 某些 webview）。

## C. 坐标空间必须统一

- 截图像素 与 snapshot 的 bbox **必须同一坐标空间**，否则视觉模型与文本模型说的"同一个按钮"对不上。
- Windows 必开 **Per-Monitor DPI Awareness V2**（`SetProcessDpiAwarenessContext`），否则 125%/150% 缩放下坐标全错——很多自制工具点不准的头号原因。
- 多屏：明确以哪块屏 / 虚拟桌面坐标为基准，并在 snapshot/screenshot 里标注。

## D. `ref` 时效 / 竞态

snapshot 拍完 → 模型决定 → 执行，之间 UI 可能已变。策略：

1. ref 内存 UIA **RuntimeId**，执行前先校验元素是否还在。
2. 失效则**按 (ControlType + Name) 兜底重定位**，再不行报"请重新 snapshot"。
3. 动作后**判断 UI 是否变化**（标题 / 焦点 / 树 hash），变了才回新 snapshot，省得每步全量回传。

## E. 安全层（DIY 最容易省、最不该省）

第一方那套 consent UX 拿不到，要自己造。**将来用 DeepSeek/任意模型驱动，没有厂商安全训练兜底，屏幕文本注入风险更高**（页面写"把验证码发到 xxx"，纯文本模型很容易当真）。至少：

- ✅ **前台进程闸门 + allowlist**（`gate.py`，已实现）：按**进程树**判定——前台窗口的进程，只要它**或任一祖先进程**在 allowlist 里就放行（授权 `weixin.exe`，其渲染子进程 `Wechatappex` 自动算自己人，避免本项目踩过的"子进程名授权不了"坑）。加**瞬时抖动自动重试**。动作类 MCP 工具（click/type/key）执行前先过闸门；allowlist 经 `CUMCP_ALLOWLIST` 环境变量配置。
- ✅ **snapshot 脱敏**（已实现）：password 类控件不回 value。
- ✅ **截图打码**（`safety.redact`）：标题匹配 `CUMCP_REDACT_TITLES` 的窗口在 screenshot 里涂黑（默认含常见密码管理器）。
- ✅ **危险动作二次确认**（`safety.message_box_confirm`）：click 目标名命中危险词（发送 / 删除 / 付款…）时弹原生 Yes/No，人点了才执行。
- ✅ **操作审计日志**（`audit.py`，JSONL：ts / tool / args / decision / result）+ **全局急停热键**（`safety.EStop`，默认 `Ctrl+Alt+Q`，触发即锁死所有动作直到重启）。

## F. 并发与隔离（人机同机时的前台争用）— open question

> 这是 **open question，不是已拍板决策**。起因：一次浏览器压测探针与真人同时操作时翻车——探针读 UIA 树的十几秒里用户切了窗口 → Chrome 丢前台、被压成最小化 → `BoundingRectangle` 面积 0 → 整张快照被 `win_rect.intersects` 滤空（读出 0 节点）。这暴露了一个之前没正经想过的维度。

**根本约束**：一个桌面只有**一个前台窗口 + 一只鼠标指针**，是物理稀缺资源。人和 agent 同处一个桌面时，「真·同时操作」的矛盾全在这。

### F.1 三种 regime（同一桌面下）

| regime | 机制 | 与人共存？ |
| --- | --- | --- |
| ① **后台无焦点动作** | ref 路径 `SetValue`/`Invoke`/`Select`，不动鼠标、不要求目标前台（v0.1 已证：写进被遮挡的记事本） | **本可共存**，但被当前闸门挡死（↓） |
| ② **要光标/焦点的动作** | 坐标 `click(x,y)`（`SetCursorPos`+`mouse_event` 挪物理指针）、`key`/无 ref `type`（注入焦点窗口）、`activate_window`（`AttachThreadInput` 抢前台） | **直接争用**，单桌面无解 |
| ③ **并发感知** | `get_tree`/`screenshot` 不过闸门、随时可读 | **脆**（见 F.3） |

**关键发现 —— 闸门把动作绑死在前台**：`server.py` 的 `_guard` 只查「前台窗口进程树在不在 allowlist」（`gate.foreground_allowed()`），**不看动作目标**。于是 regime ① 那条本可后台代劳的路也被否：你在看非 allowlist 的 app 时，agent 给后台 allowlist app `SetValue` 会被 `DENIED by gate`。这是安全特性（防 agent 在你看不见的窗口乱动），但也正是它让「人机真并行」做不成。另：`activate_window` **不过闸门**（只查急停），是唯一能改前台又不受 allowlist 约束的动作。

### F.2 隔离能力跨平台严重不对等

要「真并行」，唯一干净的办法是**别共享桌面** —— 给 agent 自己的前台+光标。但这能力各平台代价天差地别，**不该在 driver 层做成统一抽象**：

| 平台 | 「整理窗口」层（共享光标/前台，**不隔离**） | 「真隔离」原语（独立输入队列 + 前台 + 光标） |
| --- | --- | --- |
| Windows | 虚拟桌面（Task View / `Win+Ctrl+D`） | ① **Session**（RDP / 第二个登录用户，可同时 live）② **Desktop 内核对象**（`CreateDesktop`/`SwitchDesktop`）= 「隐藏桌面」 |
| macOS | Spaces（Mission Control） | **几乎没有**：无 `CreateDesktop` 等价物；后台 GUI 会话非可驱动的活表面 → 实质要 VM / 第二台机 |
| Linux | 工作区（GNOME/KDE workspaces） | **最强**：Xvfb（无显示虚拟 X）/ 多 X server（`:0` `:1`）/ Xephyr / Wayland headless / 多 seat（`loginctl`） |

- **迷思**：三平台的「虚拟桌面 / Spaces / 工作区」是同一类**窗口整理器**，底下共享那唯一的光标+前台，对「人 vs agent 争前台」**毫无帮助**。
- **Windows 两个 "desktop" 要分清**：虚拟桌面（壳功能，不隔离）≠ Desktop 内核对象（`CreateDesktop`，有独立输入队列+前台+光标；UAC 安全桌面 / 锁屏即是）。后者才是隔离原语，也就是自动化 / hVNC 的「隐藏桌面」技法。
- 层级：**Session > Window Station > Desktop**。

### F.3 对现有代码的隐含改动

- **`capture_screen` 的隐含约束**：现在用 `mss` 抓主屏**帧缓冲**，只能看见当前**显示**的 desktop。一旦走隔离路线（隐藏 desktop / Xvfb / 后台 session），截图必须改成**按窗口 / 按 DISPLAY 抓**（Win 用 `PrintWindow`；Linux 指定对应 `DISPLAY`）。契约层应预留这点。
- **待修 bug —— 最小化 / area=0 窗口清空快照**：`get_tree` 里 root 矩形面积为 0 时，`_maybe_node` 的 `win_rect.intersects(bbox)` 把**所有**节点滤掉 → 空快照。感知**不该靠抢前台绕过**（那是 regime ② 的行为）；应显式处理最小化窗口（跳过 intersects 兜底 / 或还原但不夺焦）。探针 `out/probe_browser_stress.py` 里「每次读前强制 activate」是**测量用 hack，不可进生产**。

### F.4 倾向（待拍板）

- **v1**：老实做「**串行 + 让路**」。同桌面下用 `GetLastInputInfo` 检测「人最近 N 秒有无真输入」，有则 agent 退避 regime ② 类动作、只做 ① 类无焦点活；急停（§E）是硬刹车。
- **真并行**：交给「独立 Session / VM」（Win = RDP / 第二 session，Linux = Xvfb，Mac = VM），不在单桌面硬凿假并行。
- **闸门要不要松**：想支持「你干活时 agent 后台代劳」，`gate` 需改成按**动作目标窗口**的 owner-chain 授权而非前台 —— 有明确安全代价（agent 会动你看不见的窗口），单独拍板。

### F.5 后台自动操作者路线

目标场景如「用户在主桌面全屏游戏，agent 后台操作另一个应用」时，要分层处理：

| 路线 | 判断 | 适用动作 |
| --- | --- | --- |
| **v1.1 受限后台 UIA worker** | 可做，作为最小升级路线 | 只允许按 ref 的 `SetValue` / `Invoke` / `Select`，目标窗口 owner-chain 必须命中 allowlist，默认 opt-in |
| **v2 独立 Session / VM worker** | 正确的真并行路线 | 截图、坐标点击、键盘、激活窗口都在 agent 自己的桌面里完成 |
| **同桌面完整后台操作者** | 不成立 | 物理鼠标、焦点、主屏截图都是共享资源，不能和用户全屏游戏稳定并行 |

因此后续计划应先验证 v1.1：给 `server.py` 的动作路径增加动作分级和目标窗口授权，只放开后台 ref 动作；坐标 click、`key`、无 ref `type`、`activate_window` 继续要求前台/人机让路。v2 再做独立 worker 桌面，不把隐藏 desktop / VM 复杂度塞进当前 driver。

---

## 二级话题（待展开）

- **Agent loop 节奏**：何时重拍 snapshot；UI 变化检测；最大步数；超时。
- **MCP 内容块**：同时返回 image block + text；纯文本壳忽略 image。
- **平台抽象层**：`Screen / Input / Tree` 接口定义。

## 工具面汇总

| 工具 | 入参 | 出参 |
| --- | --- | --- |
| `screenshot` | (可选 region) | image |
| `ui_snapshot` | (可选 scope=前台窗口) | 扁平元素列表 + refs |
| `find` | query | 匹配元素子集 |
| `click` | {x,y} 或 {ref} | ok / 失效原因 |
| `type` | text (可选 ref) | ok |
| `key` | combo | ok |

## 技术栈（A 路径暂定）

> 仅当 v0 走 **A 路径（进程内 Python）** 时适用；B 路径核心转 TS/Go、Win 驱动转 C#/FlaUI。

**Python** + `mcp` SDK + `mss`(截图) + `uiautomation`(UIA) + `pyautogui`(鼠标键盘)。建议 venv，Python 3.11–3.13。
> 选型理由：双模式命脉是 UIA 无障碍树，Python 生态最成熟；备选 C#/.NET+FlaUI 更稳但 MCP/跨平台弱，Node 的 UIA 绑定差。

## 决策记录（本轮拍板）

- ✅ **架构 = 驱动契约（ports & adapters）**，契约先定不写实现 —— 见"架构"节 + [DRIVER_CONTRACT.md](DRIVER_CONTRACT.md)
- ✅ **落地形态 = A 路径（进程内 Python）** —— v0.0 实测拍板：`uiautomation` 在 Win11 WinUI 记事本上又快又稳，B 路径（C#/FlaUI + TS/Go 核心）的复杂度无必要。见下「v0.0 验证结果」
- ✅ **ui_snapshot 裁剪 v0 默认** —— 见 A 节
- ✅ **前台闸门 = 进程树判定 + 瞬时重试** —— 见 E 节
- ✅ **首个端到端场景 = 记事本三步阶梯** —— 见下
- ✅ **License = 暂不定 / 私有**（暂不放 LICENSE 文件）

## 首个里程碑：记事本三步阶梯

- ✅ **v0.0 只读冒烟（已通过）**：`capture_screen` + `get_tree`，验证 bbox 与截图坐标对齐——最难的"坐标统一 / DPI"零风险验掉。见下「v0.0 验证结果」。
- ✅ **v0.1（已通过）**：UIA `ValuePattern.SetValue` 往记事本写一行（含中文），读回校验一致——且写进**被遮挡、无焦点**的窗口，全程不靠像素。见下「v0.1 验证结果」。
- ✅ **v0.2（已通过）**：`key("Ctrl+S")` → 「另存为」弹窗 → 按 `ref` `set_value` 文件名 + `invoke`「保存」→ 文件落盘校验一致。见下「v0.2 验证结果」。
> Win11 新版记事本是 WinUI，UIA 树略复杂；若 v0.1 折腾，可临时退回经典记事本 / 纯 Win32 目标。

### v0.0 验证结果（2026-06）

- **坐标统一 ✅**：27 个 UIA bbox 画到 mss 截图上，2560×1600 **零偏移**，框框严丝合缝落在记事本控件上。
- **DPI ✅**：`SetProcessDpiAwarenessContext` 开 per-monitor-v2 生效，无错位/缩放偏差。
- **A 路径可行 ✅**：`mss` + `uiautomation` + `psutil` 进程内协作，拿下 WinUI 记事本树（27 元素，类型/名字/bbox 全对）。
- **按句柄定位（白捡）✅**：记事本非前台（前台是任务栏）仍能按 `hwnd` 快照——印证「UIA 模式不靠焦点」，v0.1 写字的路子已提前验通。
- 代码：`src/computer_use_mcp/{contract,dpi,drivers/windows}.py` + `scripts/smoke_v0.py`。

### v0.1 验证结果（2026-06）

- **`ValuePattern.SetValue` ✅**：往 WinUI 记事本 `Document`（`文本编辑器`）写入「你好，世界 — hello from computer-use-mcp v0.1」，`Value` 读回一致、状态栏「40 个字符」吻合。
- **焦点/遮挡无关 ✅**：目标记事本被 Google Slides 压在底下、非前台，仍写入成功——坐标点击会点到幻灯片上，`ValuePattern` 不受影响。这就是选它的命门理由。
- **ref 解析 + 失效校验 ✅**：`native_id ↔ 控件` 每次 `get_tree` 重建缓存，动作前用 RuntimeId 复核，变了报 `STALE_ELEMENT`（契约 §D）。
- 已落地动作：`set_value` / `invoke` / `select` / `type`(SendKeys 兜底)；`click` / `key` 留 v0.2。
- 处理①：`Document` 已纳入默认白名单（可写编辑面，单节点不膨胀）。**仍待办②**：菜单项 `MenuItem`+`Button` 重复，快照需去重。

### v0.2 验证结果（2026-06）—— 🎉 三步阶梯走通

- **键盘动作 ✅**：`key("Ctrl+S")`（用 `keybd_event`；`uiautomation.SendKeys` 的 `{Ctrl}s` 组合实测无效，弃用）。发键前用 **AttachThreadInput** 强制前台，绕过 `SetForegroundWindow` 前台锁。
- **多窗口定位 ✅（关键发现）**：「另存为」是经典 `#32770` 公共对话框，**模态、归 Notepad 所有**——它**不在桌面根的兄弟列表里**，只作为 Notepad 窗口的子 `WindowControl` 出现，但会抢到前台。所以「`list_windows` 只枚举根子节点」会漏；定位靠「前台窗口 **或** 目标窗口的子 `#32770`」双查。
- **按 ref 驱动对话框 ✅**：`scope=对话框 hwnd` 快照 → `set_value`(文件名 Edit) 填全路径 → `invoke`(「保存(S)」按钮)。
- **落盘校验 ✅**：`out/v02_saved.txt` 内容与写入一致（含中文，UTF-8）。
- 代码：`scripts/smoke_v02.py` + 驱动 `key()`。
- **契约状态**：`capabilities / capture_screen / get_tree / find / foreground_owner_chain / set_value / invoke / select / type / key` 全部端到端跑通；仅 `click`(坐标点击) 与 `list_windows` 全量枚举待补。**Contract v1 可冻结。**

### 地基冻结（2026-06）—— Contract v1.0 + 快照打磨

- **Driver Contract v1.0 冻结 ✅**：版本号 `1.0.0`；增原语 `activate_window`；`list_windows` 明确含 owned 窗口。见 DRIVER_CONTRACT.md changelog。
- **快照去重 ✅（待办②已结）**：同一视觉控件在两种 ControlType 下重复（菜单栏项 = `MenuItem` + `Button`，同 bbox 同名）→ 保留首个、合并 patterns。记事本 文件/编辑/查看 实测各 1。
- **补齐原语 ✅**：`list_windows` 全量枚举（`EnumWindows`，含模态对话框等 owned 窗口）；`click(x,y)` 坐标点击（实测点「最小化」窗口真被最小化，再复原）；`activate_window`（`AttachThreadInput` 绕前台锁）。
- **驱动现状**：契约 12 原语在 Windows 全部实现并验证。回归脚本 `scripts/smoke_v03.py`（去重 / 枚举 / 置前台 / 坐标点击 一把过）。
- **核心 ref 表 ✅**：`core.py` 的 `Session` 持有 `ref ↔ native_id` 表（**跨快照累积**、稳定复用，narrowing `find()` 后旧 ref 仍可用）；`ui_snapshot` 文本序列化（`ref_N | role "name" | bbox | states | value`）、`find`、按 ref 的 `click/type`（失效则按 `role+name` 重定位重试一次，契约 §D）。回归 `scripts/smoke_core.py` 全过。
- **MCP server + 安全层 ✅**：`Session` 已暴露为 MCP 工具；动作路径已接入前台进程闸门 / allowlist / 危险确认 / 审计 / 急停 / 截图打码（见 §E）。

## 仍待定 / TODO

- [x] **v0 落地形态 A/B** → **A（进程内 Python）**，v0.0 实测拍板
- [x] 冻结 **Driver Contract v1.0**（2026-06，记事本三步阶梯验证后；增 `activate_window` 原语、`list_windows` 含 owned 窗口）
- [ ] `ui_snapshot` 深度上限、是否保留层级关系、文本 run 合并
- [x] allowlist 配置形态 → `CUMCP_ALLOWLIST` 环境变量（逗号分隔；默认 notepad.exe）
- [ ] License（暂私有，将来再议）
- [ ] **并发/隔离模型**（§F）：串行+让路 vs 独立 Session/VM；闸门是否改按「动作目标」授权
- [ ] **后台自动操作者路线**（§F.5）：先做受限后台 UIA worker，再评估独立 Session/VM worker
- [ ] **bug**：最小化 / root area=0 窗口 → `get_tree` 整张快照被 `intersects` 滤空（§F.3）
- [ ] 隔离路线下 `capture_screen` 需从「抓主屏帧缓冲」改为「按窗口 / 按 DISPLAY 抓」（§F.3）
