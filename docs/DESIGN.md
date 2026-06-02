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

- **前台进程闸门 + allowlist（已定实现方式）**：按**进程树**判定——前台窗口的进程，只要它**或任一祖先进程**在 allowlist 里就放行（授权 `weixin.exe`，其渲染子进程 `Wechatappex` 自动算自己人，避免本项目踩过的"子进程名授权不了"坑）。再加**瞬时抖动自动重试 1–2 次**（前台短暂变化时重试，而非直接报错）。
- **snapshot 脱敏**：password 类控件不回 value。
- **截图打码**：敏感窗口涂实心块。
- **危险动作二次确认**：发送 / 删除 / 提交 / 付款先停一下。
- **操作审计日志** + **全局急停热键**（一键 abort）。

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
- ⚠️ **语言 = Python（仅 A 路径）** —— 核心语言随 A/B 落地形态待定（B 路径核心转 TS/Go）
- ✅ **ui_snapshot 裁剪 v0 默认** —— 见 A 节
- ✅ **前台闸门 = 进程树判定 + 瞬时重试** —— 见 E 节
- ✅ **首个端到端场景 = 记事本三步阶梯** —— 见下
- ✅ **License = 暂不定 / 私有**（暂不放 LICENSE 文件）

## 首个里程碑：记事本三步阶梯

- **v0.0 只读冒烟**：`screenshot` + `ui_snapshot` 前台窗口，验证 bbox 与截图坐标对齐——先把最难的"坐标统一 / DPI"零风险验掉。
- **v0.1**：记事本里用 UIA `ValuePattern` 输入一行文字。
- **v0.2**：`Ctrl+S` → 处理"另存为"弹窗 → 按 `ref` 点"保存"（验多窗口 + ref 点击）。
> Win11 新版记事本是 WinUI，UIA 树略复杂；若 v0.1 折腾，可临时退回经典记事本 / 纯 Win32 目标。

## 仍待定 / TODO

- [ ] **v0 落地形态 A/B**（决定核心语言：进程内 Python vs 原生 helper + TS/Go 核心）
- [ ] 冻结 **Driver Contract v1**（待首个 Windows 驱动验证可行性后 freeze）
- [ ] `ui_snapshot` 深度上限、是否保留层级关系、文本 run 合并
- [ ] allowlist 配置形态（toml / CLI 参数 / 环境变量）
- [ ] License（暂私有，将来再议）
