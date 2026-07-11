# Agent 项目增强任务说明（给 Codex）

## 项目背景

当前项目：

Secure Cloud LLM Agent Runtime / Computer-use Agent Host

目标：

将现有 Agent Host 从安全 Computer-use Agent MVP 提升为符合 Cloud LLM
Agent 系统研发岗位要求的工程级项目。

现有架构：

CLI → AgentRunner → Policy / Context / Memory / Trace → Provider Adapter
→ OpenAI Responses API / Claude Messages API → MCP Bridge →
computer-use-mcp → Desktop Execution

## 当前实现审计（2026-07-11）

以下结论以当前源码、测试和 CLI 行为为准。全量测试为 `144 passed`，
`ruff check src tests` 通过。当前 Agent Host 是**已测试的安全基础层**，还不是
可运行的 LLM 桌面 Agent。

| 能力 | 状态 | 当前证据与缺口 |
| --- | --- | --- |
| Provider-neutral 数据契约 | 已实现 | 已有 ToolCall、ToolResult、ModelTurn、RunState、预算、审批、恢复状态和 LedgerEvent；尚未形成可执行、可持久化的完整状态机。 |
| 八个 MCP 工具注册表 | 已实现 | 固定 schema、参数校验、服务端工具发现一致性校验、结果校验和敏感字段元数据均有测试。 |
| MCP 安全基线 | 已实现 | 原有 allowlist、人类活动检测、确认、E-stop、audit 架构保持不变；type 审计只保留长度/存在性等不可逆元数据。 |
| CLI / 配置 / Run Lock | 已实现基础 | `config validate`、`run --dry-run`、安全子进程环境和单运行锁可用；非 dry-run 会主动失败关闭。 |
| 本地 stdio MCP Bridge | 已实现 | 固定直接启动、bounded transport、工具发现、generation 重建、超时/取消/未知结果分类、文本与 PNG 转换均有离线及真实 stdio fixture 测试。 |
| Host Policy | 部分实现 | 已有 read-only/action 分类和初始预算；尚无审批编排、预算消耗、动作串行化和 observation freshness 执行循环。 |
| OpenAI / Claude adapter | 已实现只读文本竖切 | 两个 provider 均复用统一 Runner、Policy 和 registry；已有 optional SDK、wire-format fixture、CLI 路由和显式门禁的 fake-MCP E3 用例。真实 E3 证据仍需操作者提供凭证执行。 |
| observe → act → verify | 未实现 | Runner 目前只创建初始 RunState 并管理锁，没有模型循环、工具调度、验证和最终结果。 |
| State persistence / recovery | 未实现 | 没有状态转换表、原子持久化、resume/cancel 命令和异常恢复流程。 |
| Context Manager | 仅契约 | 有事件类型，没有 reducer、token/context budget 压缩实现。 |
| SQLite Memory | 未实现 | 只有配置中的数据库路径，没有 schema、存取、过期、删除和秘密拒绝实现。 |
| Trace | 未实现 | 没有 JSONL writer、redaction pipeline 或 `agent trace <run_id>`。 |
| Evaluation | 部分实现 | E0 与首批只读 E1 已覆盖；OpenAI/Claude E3 opt-in 用例使用真实 provider API 和无桌面副作用的 fake MCP child。尚无 `evals/cases`、report、完整 E1/E2 和隔离桌面 smoke。 |

因此，原文中的 “OpenAI / Claude adapter、observe → act → verify、SQLite
Memory、Trace” 均应理解为目标设计，不能作为当前已运行能力对外描述。

## 当前开发约束与优先级

1. 暂不重构现有 MCP Server 安全架构，只在 Agent Host 层增加限制和编排。
2. 第一优先级是跑通**只读最小闭环**：provider turn → reviewed MCP observation
   → 对应 tool result continuation → final answer。
3. 每个增量必须同时包含离线测试、失败关闭测试和可执行文档。
4. 在只读闭环、E1/E2 和 trace 稳定前，不引入 queue、multi-agent、Redis、
   FastAPI、OpenTelemetry 或 Docker 作为主线依赖。
5. 动作能力最后接入，必须保留 host approval、单动作串行和动作后重新观察；
   桌面 smoke 只允许在隔离 Notepad/VM 环境执行。

------------------------------------------------------------------------

# 总目标

升级为：

支持任务规划、工具调用、状态恢复、上下文管理、记忆、评测、可观测性的
Cloud LLM Agent Runtime。

重点：

1.  Agent Execution Framework
2.  Workflow Orchestration
3.  State Management
4.  Task Scheduling
5.  Evaluation System
6.  Observability
7.  Production Readiness

------------------------------------------------------------------------

# P0 必须完成

P0 按以下可交付顺序执行，而不是同时铺开所有生产化组件：

1. 单 provider 只读可运行闭环及 fixture contract tests。
2. 第二 provider 复用同一 runner/registry/policy contract。
3. E1/E2 确定性工作流与对抗安全测试。
4. 状态持久化、保守恢复、redacted trace 与 trace CLI。
5. 本地审批和隔离环境下的低风险动作闭环。
6. Context reducer 与显式 SQLite Memory。

每一步的完成标准都必须是“CLI 可执行 + 测试可复现 + 文档可操作”，不能只以
新增类、接口或设计文档判定完成。

## 1. Agent State Machine

实现：

-   CREATED
-   OBSERVING
-   PLANNING
-   WAITING_APPROVAL
-   EXECUTING
-   VERIFYING
-   SUCCESS
-   FAILED
-   UNKNOWN_OUTCOME
-   CANCELLED

要求：

-   状态持久化
-   状态转换校验
-   非法跳转禁止
-   异常恢复

目标：

体现状态管理和执行恢复能力。

------------------------------------------------------------------------

## 2. Planner-Executor 架构

升级：

User Task ↓ Planner Agent ↓ Task Plan ↓ Executor ↓ Tool Calls ↓ Verifier
↓ Final Result

Task Plan 保存：

-   task_id
-   steps
-   action
-   tool
-   status

要求：

-   多步骤任务
-   执行计划保存
-   每一步状态管理
-   失败恢复

------------------------------------------------------------------------

## 3. Trace 系统增强

记录：

-   Task
-   Planner Decision
-   LLM Request
-   Tool Call
-   Tool Result
-   Verification
-   Final Output

增加：

-   latency
-   token usage
-   model
-   tool耗时
-   error
-   retry次数

提供：

agent trace `<run_id>`{=html}

------------------------------------------------------------------------

## 4. Evaluation Framework

目录：

evals/ - cases/ - reports/

支持：

-   固定任务测试
-   工具轨迹验证
-   成功率统计
-   延迟统计
-   Token统计

目标：

实现 Agent 评测、badcase 分析、回归测试。

------------------------------------------------------------------------

# P1 强烈建议

## 5. Task Queue / Worker

架构：

API ↓ Task Queue ↓ Worker ↓ Agent Runtime ↓ Result Store

支持：

-   长任务
-   重试
-   超时
-   取消

可使用：

-   asyncio worker
-   Redis Queue
-   Celery

------------------------------------------------------------------------

## 6. Context Manager

管理：

-   Conversation History
-   Task State
-   Tool Result
-   Observation
-   Policy Decision

支持：

-   Context Budget
-   自动压缩
-   保留关键状态

------------------------------------------------------------------------

## 7. Memory 完善

SQLite schema：

memory:

-   id
-   type
-   content
-   source
-   scope
-   expiry
-   created_at

允许：

-   用户确认偏好
-   verified procedure

禁止：

-   password
-   API key
-   screenshot
-   raw input
-   未验证内容

------------------------------------------------------------------------

# P2 提升竞争力

## 8. 简单 Multi-Agent

实现：

Supervisor Agent

| 

\|-- Research Agent \|-- Executor Agent \|-- Reviewer Agent

职责：

Supervisor： 任务拆分

Research： 信息收集

Executor： 工具执行

Reviewer： 结果检查

------------------------------------------------------------------------

## 9. Observability

增加：

-   success rate
-   tool failure rate
-   average latency
-   token usage
-   cost

可选：

OpenTelemetry

------------------------------------------------------------------------

## 10. Docker 化

提供：

-   Dockerfile
-   docker-compose.yml

包含：

-   Agent Host
-   Redis
-   SQLite/Postgres

------------------------------------------------------------------------

# 简历包装目标

项目名称：

Secure Cloud LLM Agent Runtime

项目描述：

设计并实现面向企业场景的 Cloud LLM Agent Runtime，支持 OpenAI 与 Claude
多模型适配，通过 MCP 实现工具调用和安全执行。构建 Planner-Executor
工作流，实现任务拆解、状态管理、上下文控制、记忆机制和异常恢复。设计
Trace 与 Evaluation Framework，对 Agent 行为进行回归测试、badcase
分析和性能优化。

技术关键词：

Python FastAPI OpenAI Responses API Claude API MCP Agent Runtime
Workflow Engine State Machine Redis SQLite Docker Evaluation Tracing LLM
Tool Calling

------------------------------------------------------------------------

# 开发原则

1.  不破坏现有 MCP Server。
2.  不降低已有安全约束。
3.  保持 Provider-neutral。
4.  优先工程落地。
5.  每个功能必须包含：
    -   测试
    -   Trace
    -   文档

最终目标：

项目能够回答：

-   Agent 如何规划任务？
-   如何执行多步骤任务？
-   如何恢复失败？
-   如何管理上下文？
-   如何评测效果？
-   如何保证线上稳定？
