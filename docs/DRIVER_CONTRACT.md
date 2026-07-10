# Driver Contract v1.0 / 驱动契约 v1.0

> 这是**通用核心**与**平台原生驱动**之间唯一的边界。契约定义原语和数据结构；语言、进程内/外实现、平台技术栈都是契约之下的可替换细节。
>
> This is the only boundary between the **shared core** and **native platform drivers**. The contract defines primitives and data structures; language choice, in-process or out-of-process implementation, and platform technology are replaceable details beneath the contract.

## 1. 设计不变量 / Design Invariants

1. **裁剪下推**：`get_tree` 由驱动按 `PruneOpts` 就地裁剪后再返回；核心只定策略，不接收原始全树。
   **Push pruning down**: `get_tree` is pruned by the driver using `PruneOpts` before return; the core defines policy and does not receive raw full trees.
2. **单一坐标空间**：某次 `capture_screen` 返回的图是 `W x H` 像素；同一时刻所有 `bbox` 与传给 `click(x,y)` 的坐标都在同一个像素栅格里。
   **Single coordinate space**: an image returned by `capture_screen` is a `W x H` pixel grid; at the same moment, every `bbox` and `click(x,y)` coordinate uses that same grid.
3. **归属链由驱动提供**：查窗口和进程归属链是平台相关的；驱动提供归属链，核心负责 allowlist 判定。
   **Owner chains come from drivers**: resolving window and process ownership is platform-specific; drivers provide owner chains and the core applies allowlist policy.

## 2. 坐标约定 / Coordinate Conventions

- 原点 = 主显示器左上角 `(0,0)`；多屏按 OS 虚拟桌面布局排列。
  Origin = top-left of the primary display `(0,0)`; multi-monitor layouts follow the OS virtual desktop layout.
- 所有 `Rect` / `click` 坐标都在当次截图的像素栅格中。
  All `Rect` and `click` coordinates are in the pixel grid of the corresponding screenshot.
- `Image` 附带 `scale` 与各显示器 `bounds`，供需要时换算。默认不需要调用方换算。
  `Image` includes `scale` and display `bounds` for conversions when needed. Callers do not need conversions by default.

## 3. 数据结构 / Data Structures

```text
Rect   { x, y, w, h }                       # shared pixel space

Image  { png: bytes,
         width, height,                     # pixel grid shared by bbox
         scale: float,                      # primary display DPI scale
         displays: [{ id, bounds: Rect, scale, primary: bool }] }

Window { id: string,                        # stable window id
         title: string,
         bounds: Rect,
         owner: { pid, name },
         owner_chain: [{ pid, name }],      # self -> ancestors
         is_foreground: bool }

Node   { native_id: string,                 # Win RuntimeId / mac AX token / AT-SPI path
         role: string,                      # normalized role
         name: string,                      # <= name_max_len
         value: string | null,              # null for password or unavailable values
         bbox: Rect,
         states: [enabled, focused, selected, ...],
         patterns: [invoke, value, selectionitem, toggle, expand, ...] }

PruneOpts { scope: "foreground" | window_id | "all",
            control_types: [..] | "default",
            include_offscreen: false,
            max_nodes: 200,
            name_max_len: 100,
            redact_password: true }
```

`ref`（如 `ref_7`）是核心层概念，不在契约里。核心维护 `ref <-> native_id` 映射表并处理失效；驱动只认 `native_id`。

`ref`, such as `ref_7`, is a core-layer concept and is not part of the driver contract. The core maintains the `ref <-> native_id` map and handles staleness; drivers only understand `native_id`.

## 4. 原语 / Primitives

```text
capabilities()                  -> { contract_version, platform, features[] }
capture_screen(region?: Rect)   -> Image
list_windows()                  -> [Window]
foreground_owner_chain()        -> [{ pid, name }]
get_tree(opts: PruneOpts)       -> { nodes: [Node], truncated: int }
find(opts: PruneOpts, query)    -> { nodes: [Node], truncated: int }
invoke(native_id)               -> Result
set_value(native_id, text)      -> Result
select(native_id)               -> Result
click(x, y, button?, modifiers?)-> Result
key(combo)                      -> Result
type(text)                      -> Result
activate_window(window_id)      -> Result
```

说明 / Notes:

- `list_windows()` 返回所有可见顶层窗口，包括 owned 对话框；Z 序靠前在先。
  `list_windows()` returns all visible top-level windows, including owned dialogs, ordered by Z-order.
- `get_tree()` / `find()` 的 `truncated` 表示被 `max_nodes` 裁掉的节点数。
  `truncated` in `get_tree()` / `find()` is the number of nodes cut by `max_nodes`.
- `set_value()` 优先于模拟键盘。
  `set_value()` is preferred over simulated keyboard input.
- `click(x,y)` 使用共享像素坐标空间。
  `click(x,y)` uses the shared pixel coordinate space.
- `activate_window()` 改变前台窗口，属于 foreground-required 能力。
  `activate_window()` changes the foreground window and is a foreground-required capability.

## 5. 错误码 / Error Codes

| 错误码 / Error | 含义 / Meaning |
| --- | --- |
| `STALE_ELEMENT` | `native_id` 无法解析或元素已失效 / `native_id` cannot be resolved or the element is stale |
| `NOT_INVOKABLE` | 目标不支持请求的无障碍动作 / Target does not support the requested accessibility action |
| `OUT_OF_BOUNDS` | 坐标不在有效截图空间内 / Coordinates are outside the valid screenshot space |
| `PERMISSION_DENIED` | 平台或权限拒绝 / Platform or permission denied |
| `DRIVER_ERROR` | 驱动内部错误 / Internal driver error |

## 6. 平台映射 / Platform Mapping

| 原语 / Primitive | Windows | macOS | Linux |
| --- | --- | --- | --- |
| `capture_screen` | DXGI / GDI / `mss` | ScreenCaptureKit / CGWindowList | X11 XGetImage / Wayland portal |
| `get_tree` | UIA (`uiautomation` / FlaUI) | AXUIElement (`pyobjc` / Swift) | AT-SPI |
| `invoke` / `set_value` / `select` | InvokePattern / ValuePattern / SelectionItemPattern | AXPress / AXValue / AXSelect | AT-SPI Action / EditableText |
| `click` / `key` / `type` | SendInput / Win32 | CGEvent | XTest / uinput |
| `owner_chain` | Window hwnd + pid + parent process chain | AX pid + process parent chain | `_NET_ACTIVE_WINDOW` + `/proc` |

## 7. 版本化 / Versioning

- `contract_version` 使用 semver；驱动通过 `capabilities()` 声明。
  `contract_version` uses semver and is declared by drivers through `capabilities()`.
- 核心拒绝大版本不匹配的驱动；小版本保持向后兼容。
  The core rejects drivers with incompatible major versions; minor versions remain backward compatible.
- 任何原语签名或数据结构变更都必须升版本，并在 changelog 记录。
  Any primitive signature or data-structure change must bump the version and be recorded in the changelog.

## 8. Changelog / 变更记录

- **v1 draft / 草案**：定义 `capture_screen`、`list_windows`、`foreground_owner_chain`、`get_tree`、`find`、`invoke`、`set_value`、`select`、`click`、`key`、`type` 和核心数据结构。
  Defined `capture_screen`, `list_windows`, `foreground_owner_chain`, `get_tree`, `find`, `invoke`, `set_value`, `select`, `click`, `key`, `type`, and the core data structures.
- **v1.0 frozen, 2026-06 / 已冻结**：经 Windows 驱动和记事本三步阶梯端到端验证后冻结。新增 `activate_window(window_id)`；明确 `list_windows` 必须包含 owned 窗口。
  Frozen after end-to-end validation with the Windows driver and the Notepad three-step ladder. Added `activate_window(window_id)` and clarified that `list_windows` must include owned windows.
