# Driver Contract v1（驱动契约）

> 这是**通用核心**与**平台原生驱动**之间唯一的边界。把这十几个原语和数据结构定死，上层（MCP / snapshot / 安全 / loop）一行不用改，下层每平台各实现一份。**契约即架构本体**——语言、进程内/外都是契约之下的可替换细节。

## 设计不变量（三条铁律）

1. **裁剪下推**：`get_tree` 由**驱动**按 `PruneOpts` 就地裁剪后再返回；核心只定**策略**，不接收原始全树（避免跨进程传 5000 节点爆掉）。
2. **单一坐标空间**：某次 `capture_screen` 返回的图是 `W×H` 像素；**同一时刻**所有 `bbox` 与传给 `click(x,y)` 的坐标，**都在这同一个 `W×H` 像素栅格里**。驱动负责内部 logical↔physical 归一，对外只暴露一套空间——这就是"视觉模型与文本模型对得齐"的保证。
3. **闸门是驱动原语**：查"前台窗口归属进程链"是平台相关的（驱动给），"祖先在不在 allowlist"的判定是通用的（核心做）。

## 坐标约定

- 原点 = **主显示器左上角 (0,0)**；多屏按 OS 虚拟桌面布局排列。
- 所有 `Rect` / `click` 坐标都在「**当次截图的像素栅格**」中。
- `Image` 附带 `scale` 与各显示器 `bounds`，供需要时换算，但**默认无需换算**（不变量 2 已保证一致）。

## 数据结构

```
Rect   { x, y, w, h }                       # 共享像素空间

Image  { png: bytes,
         width, height,                     # bbox 共享的像素栅格
         scale: float,                       # 主屏 DPI 缩放(1.0/1.5/2.0…)
         displays: [{ id, bounds: Rect, scale, primary: bool }] }

Window { id: string,                         # 稳定窗口 id
         title: string,
         bounds: Rect,
         owner: { pid, name },               # 拥有该窗口的前台进程
         owner_chain: [{ pid, name }],       # self → … → 根祖先（闸门用）
         is_foreground: bool }

Node   { native_id: string,                  # 驱动可解析的句柄(Win RuntimeId / mac AX token / atspi path)
         role: string,                       # 归一化控件类型(Button/Edit/CheckBox/…)
         name: string,                       # ≤ name_max_len
         value: string | null,               # password 脱敏或 N/A 时为 null
         bbox: Rect,
         states: [enabled, focused, selected, …],
         patterns: [invoke, value, selectionitem, toggle, expand, …] }  # 支持的动作

PruneOpts { scope: "foreground" | window_id | "all",
            control_types: [..] | "default",
            include_offscreen: false,
            max_nodes: 200,
            name_max_len: 100,
            redact_password: true }
```

> `ref`（`ref_7` 这种）是**核心**层概念，不在契约里：核心维护 `ref ↔ native_id` 映射表并处理失效。驱动只认 `native_id`。

## 原语（contract v1）

```
capabilities()                  -> { contract_version, platform, features[] }
capture_screen(region?: Rect)   -> Image
list_windows()                  -> [Window]
foreground_owner_chain()        -> [{ pid, name }]          # 闸门便捷查询
get_tree(opts: PruneOpts)       -> { nodes: [Node], truncated: int }   # truncated = 被 max_nodes 砍掉数
find(opts: PruneOpts, query)    -> { nodes: [Node], truncated: int }
invoke(native_id)               -> Result
set_value(native_id, text)      -> Result                   # 优先于模拟键盘
select(native_id)               -> Result
click(x, y, button?, modifiers?)-> Result                   # 坐标=共享空间
key(combo)                      -> Result
type(text)                      -> Result
```

**错误码**：`STALE_ELEMENT`（native_id 解析不到了）、`NOT_INVOKABLE`、`OUT_OF_BOUNDS`、`PERMISSION_DENIED`、`DRIVER_ERROR`。

## 平台实现映射（参考，非契约一部分）

| 原语 | Windows | macOS | Linux |
|---|---|---|---|
| capture_screen | DXGI/GDI（`mss`） | ScreenCaptureKit / CGWindowList | X11 XGetImage / Wayland portal |
| get_tree | UIA（uiautomation / FlaUI） | AXUIElement（pyobjc / Swift） | AT-SPI |
| invoke / set_value / select | InvokePattern / ValuePattern / SelectionItemPattern | AXPress / AXValue / AXSelect | AT-SPI Action / EditableText |
| click / key / type | SendInput | CGEvent | XTest / uinput |
| owner_chain | GetForegroundWindow+pid+父进程(Toolhelp) | AX pid + proc 父链 | _NET_ACTIVE_WINDOW + /proc |

## 版本化

- `contract_version` 用 semver；驱动通过 `capabilities()` 声明。
- 核心拒绝**大版本不匹配**的驱动；小版本向后兼容。
- 任何原语签名/数据结构变更 → 升版本，并在本文件 changelog 记录。

## Changelog

- **v1（draft）**：首版草案。`capture_screen / list_windows / foreground_owner_chain / get_tree / find / invoke / set_value / select / click / key / type` + 上述数据结构。**未冻结**，实现首个 Windows 驱动验证可行性后再 freeze 为 v1.0。
