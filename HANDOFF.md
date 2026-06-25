# HANDOFF — computer-use-mcp

> 给下一个接手的 agent（可能是 Codex）/ 人的冷启动文档。最后更新：2026-06。
> 深度设计见 [docs/DESIGN.md](docs/DESIGN.md)、契约见 [docs/DRIVER_CONTRACT.md](docs/DRIVER_CONTRACT.md)。
> 本文件是**入口**：先读这一篇，再按需翻那两篇。

---

## 0. TL;DR（30 秒）

一个**与模型无关**的 computer-use **MCP server**，让任意 MCP 壳（Claude Code / Cline / Codex…）截屏并控制 **Windows** 桌面。双模式：`screenshot`（视觉模型按坐标）+ `ui_snapshot`（文本模型按控件 `ref`）。

**当前状态：v1 功能完整、带完整安全层、可连接使用。** 在真实 Win11 上端到端验证过（记事本三步阶梯 + Chrome 只读探针）。`Driver Contract v1.0` 已冻结。只在 Windows + 一个干净 app（记事本）上充分验证过；浏览器只做了只读探针；微信进程树闸门尚未实测。

架构分层（ports & adapters）：
```
MCP 壳 ──stdio──> server.py(8 工具) ──> gate.py(allowlist 闸门) + safety.py + audit.py
                                          └─> core.py(Session: ref 表) ──> contract.py(v1.0 冻结)
                                                                            └─> drivers/windows.py(12 原语)
```

---

## 1. 怎么跑起来

环境：**Windows 11，Python 3.13.7**（`py -3`），venv 在 `.venv/`。鼠标键盘走 ctypes + `uiautomation.SendKeys`，**不用 pyautogui**。

```powershell
# 安装（首次）
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .

# 跑 MCP server（stdio transport）
$env:CUMCP_ALLOWLIST = "notepad.exe"      # 动作只在 allowlist 的 app 前台时执行
.\.venv\Scripts\computer-use-mcp.exe       # 或: python -m computer_use_mcp.server

# 跑冒烟（每层一个；会真的操作桌面，有可见副作用）
$env:PYTHONUTF8 = "1"                      # 控制台是 GBK，必须设这个否则中文 print 崩
.\.venv\Scripts\python.exe scripts\smoke_v0.py     # 坐标/DPI 对齐
.\.venv\Scripts\python.exe scripts\smoke_v01.py    # ValuePattern 写字
.\.venv\Scripts\python.exe scripts\smoke_v02.py    # Ctrl+S 存盘按 ref
.\.venv\Scripts\python.exe scripts\smoke_v03.py    # 去重/枚举/置前台/坐标点击
.\.venv\Scripts\python.exe scripts\smoke_core.py   # ref 表 + 序列化
.\.venv\Scripts\python.exe scripts\smoke_server.py # MCP 工具 + 闸门
.\.venv\Scripts\python.exe scripts\smoke_safety.py # 确认/急停/打码/审计
```

> 冒烟脚本**会启动真实记事本、动 Chrome 窗口**等——它们是 on-device 集成测试，不是纯单测。一次性探针放 `out/`（gitignored）。

---

## 2. 已做 & 验证

| 模块 / 里程碑 | 状态 | 冒烟 |
| --- | --- | --- |
| Driver Contract v1.0（冻结，12 原语） | ✅ | — |
| `drivers/windows.py`（12 原语全实现） | ✅ | 各 smoke |
| v0.0 坐标/DPI 对齐 | ✅ | smoke_v0 |
| v0.1 `ValuePattern.SetValue` 写字（焦点无关） | ✅ | smoke_v01 |
| v0.2 `Ctrl+S` → 另存为弹窗 → 按 ref 点保存 | ✅ | smoke_v02 |
| 快照去重 + `list_windows` 全量 + `click(x,y)` + `activate_window` | ✅ | smoke_v03 |
| `core.py` Session：ref 表 + ui_snapshot 序列化 + 失效重定位 | ✅ | smoke_core |
| `server.py` MCP server，8 工具 | ✅ | smoke_server |
| 安全层 §E：闸门 / 危险确认 / 审计 / 急停 / 截图打码 | ✅ | smoke_safety |

**MCP 工具（8）**：感知 `ui_snapshot` / `find` / `screenshot` / `list_windows`（不闸门，password 在 snapshot 脱敏）；动作 `click` / `type` / `key` / `activate_window`（先过：急停→闸门→危险确认→执行→审计）。

---

## 3. 文件地图

```
src/computer_use_mcp/
├── contract.py   Driver Contract v1.0：Rect/Image/Window/Node/PruneOpts/Result + Driver ABC + 错误码。纯 stdlib，无平台依赖。改它=升版本。
├── dpi.py        DPI 感知 bootstrap（纯 ctypes）。必须在 import mss/uiautomation 之前调用。
├── drivers/
│   └── windows.py  WindowsDriver：mss(截图)+uiautomation(UIA)+psutil(进程树)+ctypes(键鼠/前台)。12 原语。
├── core.py       Session：模型面 API。ref↔native_id 表（跨快照累积）、ui_snapshot 文本序列化、失效重定位。平台无关。
├── gate.py       Gate：前台进程树 allowlist 闸门（祖先在 allowlist 即放行 + 瞬时重试）。
├── safety.py     is_dangerous() / message_box_confirm() / EStop(急停热键) / redact(截图打码)。
├── audit.py      AuditLog：JSONL 操作审计。
└── server.py     FastMCP server，把 Session 暴露成 8 工具，动作裹 _guard(急停+闸门)+危险确认+审计。entry: main()。
scripts/  smoke_v0 v01 v02 v03 core server safety   每层一个 on-device 冒烟
out/      gitignored：截图产物、audit_test.jsonl、一次性 probe_*.py
docs/     DESIGN.md（决策记录+验证结果）、DRIVER_CONTRACT.md（契约 v1.0）
```

---

## 4. 关键决策（别轻易推翻，背景在 DESIGN.md）

- **A 路径（进程内 Python）**，不是 B（C#/FlaUI + TS/Go 核心）。实测拍板：uiautomation 在 WinUI 上又快又稳。要上 Mac 再按平台逐个选；contract 不变。
- **`ref` 路径直接调 UIA 模式**（Invoke / SetValue / SelectionItem），**不合成坐标点击**。好处：不受焦点/遮挡/DPI 影响（v0.1 写进被 Chrome 压住的记事本就是靠这个）。坐标点击只给视觉模型 + UIA 抓不到的 canvas/游戏。
- **Contract v1.0 已冻结**：改原语签名/数据结构 → 升 semver + 记 DRIVER_CONTRACT.md changelog。
- **安全默认拒绝**：动作类工具默认过前台 allowlist 闸门；没有厂商安全兜底，这是 DIY 的命门控制。
- **License 暂私有**，不放 LICENSE。

---

## 5. 踩过的坑 / 硬知识（最值钱的一节）

1. **DPI 必须最先设**：`dpi.enable_dpi_awareness()` 要在 import `mss`/`uiautomation` **之前**调（看任意 smoke 顶部的 import 顺序）。否则 125%/150% 缩放下坐标全错——头号翻车点。
2. **控制台 GBK**：脚本里 `sys.stdout.reconfigure(encoding="utf-8")` + 运行带 `$env:PYTHONUTF8=1`，否则中文/bidi 字符（如 U+200E）`print` 直接崩。
3. **`uiautomation.SendKeys('{Ctrl}s')` 实测不触发组合键** → `key()` 改用 ctypes `keybd_event`。别改回 SendKeys 组合键。
4. **前台锁**：后台进程不能直接 `SetForegroundWindow` → `activate_window` 用 `AttachThreadInput` 绕过。键盘类动作（`key`、向焦点 `type`）执行前要先 `activate_window`。
5. **另存为对话框 = `#32770`，归 Notepad 所有（owned），不在桌面根的兄弟列表**。所以 `list_windows` 用 `EnumWindows`（含 owned 窗口）；定位对话框 = 「前台窗口」**或**「目标窗口的子 `#32770`」双查（见 smoke_v02 的 `find_save_dialog`）。
6. **新版记事本（WinUI）**：正文编辑区是 `Document` 控件（带可写 `ValuePattern`，**不是** `Edit`）；菜单项 文件/编辑/查看 同时以 `MenuItem`+`Button` 出现（同 bbox 同名）→ `get_tree` 已按 `(bbox, name)` 去重并合并 patterns。
7. **Chrome（只读探针 out/probe_browser.py 的发现）**：① 最小化窗口快照为空（bbox 面积 0），先 `ShowWindow(SW_RESTORE)`；② **懒加载 a11y**——第一次 UIA 走树会触发 Chromium 现搭无障碍树，**第二次（隔 ~1s）才齐**（实测 42→55 节点、Document 3→8、Hyperlink 0→2）。浏览器快照建议**读两次**或加 `--force-renderer-accessibility`。新标签页内容少、没触发截断；**内容重的页面还没压测过**。
8. **坐标空间**：只截**主屏**，原点 (0,0)。多屏/副屏未处理（窗口在副屏会落到图外/负坐标）。`capture_screen(region=…)` 路径的 bbox 偏移也还没做（v0.0 注释标了）。
9. **ref 生命周期**：Session 的 ref 表**跨快照累积、不清空**，所以 `find()` 收窄后旧 ref 仍可用；动作时若 `STALE_ELEMENT` 才按 `(role, name)` 重定位重试一次。
10. **动作解析依赖上一次 get_tree 的缓存**：跨窗口操作要先对目标窗口 `get_tree(scope=hwnd)` 再动作（driver 的 `_node_cache` 每次 get_tree 重建）。
11. **git CRLF 警告无害**（仓库存 LF，Windows 工作区 CRLF，提交时正常化）。

---

## 6. 配置（环境变量）

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `CUMCP_ALLOWLIST` | 动作放行的进程名（逗号分隔，进程树任一祖先命中即放行） | `notepad.exe` |
| `CUMCP_REDACT_TITLES` | screenshot 里要涂黑的窗口标题子串 | 常见密码管理器 |
| `CUMCP_ESTOP` | 急停热键组合 | `ctrl+alt+q` |
| `CUMCP_AUDIT` | 审计日志路径 | `audit/actions.jsonl` |

急停：按住热键 → 锁死所有动作直到**重启 server**（latch）。

---

## 7. 待办 / 下一步（按价值排序）

可直接执行的开工计划见 [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md)。下面是长期 backlog。

1. **浏览器内容页压测**（最有信息量）：在 Chrome 打开内容重的页面，跑 `out/probe_browser.py`，看 `max_nodes=200` 截断、`find()` 省 token、同名元素歧义。→ 这才是「要不要 parent ref 层级」的真实依据。
2. **固化「浏览器快照热身」**：在内容页确认坑 7② 的模式后，让 `Session.ui_snapshot` 对浏览器读两次（或暴露 warmup 开关 / force-accessibility）。
3. **微信进程树闸门实测**：`weixin.exe` → 渲染子进程 `Wechatappex`，验证祖先放行逻辑（gate.py 的招牌场景，至今没真测过）。
4. **快照层级 / parent ref**（由 #1 驱动；DESIGN「消歧」待定项）。
5. **多屏坐标空间**（坑 8）：虚拟桌面跨屏、per-monitor scale。
6. **macOS / Linux 驱动**：契约已冻结，照 DRIVER_CONTRACT.md 的平台映射各实现一份（Mac=AX/pyobjc 或 Swift，Linux=AT-SPI）。
7. **测试硬化**：把 on-device smokes 收敛成可重复的 pytest（目前依赖真实桌面、手跑）。
8. **杂项**：删已合并的 `feat/v0.0-windows-driver` 分支、定 License、`ui_snapshot` 深度上限/文本 run 合并。

---

## 8. Git 状态 & 约定

- 主线在 **`main`**；v1 这批工作以 `--no-ff` 合并（merge commit `d243456`）。
- 开工前用 `git status --short --branch` 确认本地与远端状态，避免把 `out/` 探针或真实桌面副产物混入提交。
- 已合并分支 `feat/v0.0-windows-driver` 还在（可删）。
- 约定：在 default 分支上动手前先开分支；提交信息末尾带 `Co-Authored-By` trailer；一次性探针写 `out/`（gitignored），正式回归冒烟写 `scripts/`。

---

## 9. 给 Codex（接手者）的提示

- **经验性优先**：碰真实 UI（新 app / 对话框）时，先写 `out/probe_*.py` **只读探针**把真实 UIA 树打出来看，再写实现——本项目一路这么干，省了大量瞎猜。
- **改完跑对应 smoke**：每层都有一个 on-device 冒烟，是回归网。
- **契约神圣**：`contract.py` 改签名/结构 → 升版本 + 记 changelog；上层（core/server/safety）不应 import 任何平台模块。
- **加新动作工具**：务必裹 `server.py` 的 `_guard`（急停+闸门）+ 必要时危险确认 + `audit.record`。
- **环境**：Windows + GBK 控制台，跑脚本带 `$env:PYTHONUTF8=1`；别引入 `pyautogui`（已移除）。
- 不确定的设计取舍，先翻 DESIGN.md 的「决策记录 / 验证结果」，多半已经拍过板，别重复纠结。
