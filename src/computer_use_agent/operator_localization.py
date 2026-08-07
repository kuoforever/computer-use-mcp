"""Bounded presentation localization for native operator surfaces.

Only visible, Host-owned copy enters this module.  Internal option ids, enums,
persisted JSON, policy decisions, approval authority, and dispatch behavior stay
locale-neutral.  Unknown Host labels are preserved verbatim rather than guessed.
"""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from dataclasses import replace
from enum import Enum

from .operator_visuals import (
    OperatorVisualRole,
    OperatorVisualToken,
)
from .win32_dll import private_windll


AUTO_OPERATOR_LOCALE = "auto"
SUPPORTED_OPERATOR_LOCALE_PREFERENCES = frozenset(
    {AUTO_OPERATOR_LOCALE, "en-US", "zh-CN"}
)
_LOCALE_NAME_MAX_LENGTH = 85


class OperatorLocalizationError(ValueError):
    """Fixed presentation-localization failure without operator content."""


class OperatorLocale(str, Enum):
    EN_US = "en-US"
    ZH_CN = "zh-CN"


_ENGLISH_COPY = {
    "all_workflow_steps_resolved": "ALL WORKFLOW STEPS RESOLVED",
    "application": "Application",
    "approval": "APPROVAL",
    "approval_locked": "APPROVAL LOCKED",
    "approval_locked_title": "approval locked",
    "approval_needed_step": "APPROVAL NEEDED · STEP {current} OF {total}",
    "approval_notice_body": "Approval needed. Return to the open decision window.",
    "approval_notice_title": "Guarded Desktop Agent",
    "benefit": "Benefit",
    "can_be_undone": "Can be undone",
    "choose_bounded_option": "Choose one bounded option",
    "completed_count": "{count} completed",
    "compute_cost": "Compute cost",
    "confidence": "Confidence",
    "countdown": "Closes in {seconds}s",
    "coverage_known": "known",
    "coverage_unknown": "coverage unknown",
    "current_step": "CURRENT STEP {current} OF {total}",
    "decision_details": "Decision details",
    "decision_required": "Decision required",
    "decision_scope": "Decision scope",
    "evidence_available": "Evidence available",
    "expected_time": "Expected time",
    "hide_details": "Hide details",
    "hide_steps": "HIDE STEPS",
    "no": "No",
    "no_application_active": "No application is active",
    "no_workflow_step_active": "NO WORKFLOW STEP IS ACTIVE",
    "not_estimated": "Not estimated",
    "not_started_count": "{count} not started",
    "outcome": "Outcome",
    "product_name": "Computer Use",
    "presence_window_title": "Computer Use active",
    "progress_campaign_counts": "  items {completed}/{discovered} complete  retryable {retryable}  uncertain {uncertain}",
    "progress_header_campaigns": "Computer Use  campaigns {campaign_shown}/{campaign_total}  runs {shown}/{total}",
    "progress_header_runs": "Computer Use  runs {shown}/{total}",
    "progress_hidden_campaigns": "hidden unsafe campaign records: {count}",
    "progress_hidden_runs": "hidden unsafe records: {count}",
    "progress_run_calls": "  calls  model {model_used}/{model_limit}  tool {tool_used}/{tool_limit}",
    "progress_run_head": "{run_id}  STEP {step}/{limit}  {phase}  {state}",
    "progress_run_usage": "  tokens in {input_tokens} out {output_tokens} ({coverage})  screenshots {screenshots}  fails {failures}",
    "progress_summary": "Progress summary",
    "progress_unavailable_campaigns": "campaigns unavailable ({count}): {listed}{suffix}",
    "progress_unavailable_runs": "unavailable ({count}): {listed}{suffix}",
    "reobserve_marker": "[re-observe]",
    "screenshots_unavailable": "unavailable",
    "ready_to_begin": "READY TO BEGIN",
    "recommended": "recommended",
    "result_unknown": "Result unknown — do not retry automatically",
    "risk": "Risk",
    "safe_exit": "Safe exit",
    "safety_checks": "Safety checks",
    "show_details": "Show details",
    "show_steps": "SHOW STEPS",
    "skipped_count": "{count} skipped",
    "still_unknown": "Still unknown",
    "support_fingerprint": "Support fingerprint",
    "technical_verification": "Technical verification (short fingerprints)",
    "total_count": "{count} total",
    "tradeoff": "Trade-off",
    "workflow": "WORKFLOW",
    "workflow_checklist": "WORKFLOW CHECKLIST",
    "yes": "Yes",
    "your_choices": "Your choices",
}

_CHINESE_COPY = {
    "all_workflow_steps_resolved": "所有流程步骤已完成",
    "application": "应用",
    "approval": "审批",
    "approval_locked": "审批已锁定",
    "approval_locked_title": "审批已锁定",
    "approval_needed_step": "需要审批 · 第 {current}/{total} 步",
    "approval_notice_body": "需要审批。请返回已打开的决策窗口。",
    "approval_notice_title": "受保护的桌面智能体",
    "benefit": "收益",
    "can_be_undone": "可以撤销",
    "choose_bounded_option": "请选择一项",
    "completed_count": "已完成 {count} 项",
    "compute_cost": "计算成本",
    "confidence": "置信度",
    "countdown": "{seconds} 秒后关闭",
    "coverage_known": "已知",
    "coverage_unknown": "覆盖范围未知",
    "current_step": "当前第 {current}/{total} 步",
    "decision_details": "决策详情",
    "decision_required": "需要决策",
    "decision_scope": "决策范围",
    "evidence_available": "已有证据",
    "expected_time": "预计时间",
    "hide_details": "收起详情",
    "hide_steps": "收起步骤",
    "no": "否",
    "no_application_active": "当前没有活动应用",
    "no_workflow_step_active": "当前没有活动流程步骤",
    "not_estimated": "未估算",
    "not_started_count": "未开始 {count} 项",
    "outcome": "结果",
    "product_name": "电脑操作",
    "presence_window_title": "电脑操作进行中",
    "progress_campaign_counts": "  项目 {completed}/{discovered} 已完成  可重试 {retryable}  不确定 {uncertain}",
    "progress_header_campaigns": "电脑操作  活动 {campaign_shown}/{campaign_total}  运行 {shown}/{total}",
    "progress_header_runs": "电脑操作  运行 {shown}/{total}",
    "progress_hidden_campaigns": "已隐藏不安全的活动记录：{count}",
    "progress_hidden_runs": "已隐藏不安全的运行记录：{count}",
    "progress_run_calls": "  调用  模型 {model_used}/{model_limit}  工具 {tool_used}/{tool_limit}",
    "progress_run_head": "{run_id}  第 {step}/{limit} 步  {phase}  {state}",
    "progress_run_usage": "  token 输入 {input_tokens} 输出 {output_tokens}（{coverage}）  截图 {screenshots}  失败 {failures}",
    "progress_summary": "进度摘要",
    "progress_unavailable_campaigns": "活动不可用（{count}）：{listed}{suffix}",
    "progress_unavailable_runs": "运行不可用（{count}）：{listed}{suffix}",
    "reobserve_marker": "[重新观察]",
    "screenshots_unavailable": "不可用",
    "ready_to_begin": "可以开始",
    "recommended": "推荐",
    "result_unknown": "结果未知——不要自动重试",
    "risk": "风险",
    "safe_exit": "安全退出",
    "safety_checks": "安全检查",
    "show_details": "显示详情",
    "show_steps": "显示步骤",
    "skipped_count": "已跳过 {count} 项",
    "still_unknown": "仍未知",
    "support_fingerprint": "支持指纹",
    "technical_verification": "技术校验（短指纹）",
    "total_count": "共 {count} 项",
    "tradeoff": "代价",
    "workflow": "流程",
    "workflow_checklist": "流程清单",
    "yes": "是",
    "your_choices": "你的选择",
}

_BUTTON_COPY = {
    OperatorLocale.EN_US: {
        "option_approve_exact_effect": "Approve once",
        "option_reobserve": "Check screen again",
        "option_defer": "Pause and inspect",
        "option_deny": "Stop task",
        "option_human_takeover": "Take control",
    },
    OperatorLocale.ZH_CN: {
        "option_approve_exact_effect": "仅批准这一次",
        "option_reobserve": "重新检查屏幕",
        "option_defer": "暂停并检查",
        "option_deny": "停止任务",
        "option_human_takeover": "接管桌面",
    },
}

_VISUAL_COPY = {
    OperatorVisualRole.NOT_STARTED: ("未开始", "就绪"),
    OperatorVisualRole.IN_PROGRESS: ("进行中", "活动"),
    OperatorVisualRole.OBSERVING: ("正在观察", "观察"),
    OperatorVisualRole.PLANNING: ("正在规划", "规划"),
    OperatorVisualRole.EXECUTING: ("正在执行", "操作"),
    OperatorVisualRole.VERIFYING: ("正在验证", "验证"),
    OperatorVisualRole.RECOVERING: ("正在恢复", "恢复"),
    OperatorVisualRole.NEEDS_INPUT: ("需要确认", "审批"),
    OperatorVisualRole.PAUSED: ("已暂停", "暂停"),
    OperatorVisualRole.READY: ("已就绪", "完成"),
    OperatorVisualRole.NEEDS_INSPECTION: ("需要检查", "检查"),
    OperatorVisualRole.FAILED: ("失败", "失败"),
    OperatorVisualRole.CANCELLED: ("已取消", "取消"),
}

_FIXED_CHINESE = {
    "Public-source research brief update": "公开来源研究简报更新",
    "Prepare the controlled demo workspace": "准备受控演示工作区",
    "Demo setup": "演示准备",
    "Review the public collaboration guide": "查看公开协作指南",
    "Open the research brief": "打开研究简报",
    "Add the verified source note": "添加已验证的来源说明",
    "Save the research brief": "保存研究简报",
    "Verify the saved document": "验证已保存的文档",
    "This card controls one bounded desktop action only.": "此卡仅控制一次受限的桌面操作。",
    "A recommendation is advice, not permission for later actions.": "推荐只是建议，并不授权之后的操作。",
    "Esc, close, or timeout denies this action.": "按 Esc、关闭窗口或等待超时都会拒绝此操作。",
    "The current screen evidence is bound to this card.": "当前屏幕证据已绑定到此卡。",
    "If the task, policy, application, or target changes, this card expires.": "如果任务、策略、应用或目标发生变化，此卡就会失效。",
    "Choosing an option does not authorize any later action.": "选择一个选项不会授权之后的任何操作。",
    "Fingerprints help support staff correlate records. They grant no authority.": "指纹可帮助支持人员关联记录，但不授予任何权限。",
    "Re-observe before continuing": "继续前重新观察",
    "No external effect occurs during the fresh observation": "重新观察期间不会产生外部影响",
    "refreshes Host evidence": "刷新主机证据",
    "preserves the bounded workflow": "保留受限流程",
    "uses additional observation and model capacity": "使用额外的观察和模型资源",
    "the application may drift again": "应用可能再次发生变化",
    "Request approval for one exact effect": "请求批准一次确切操作",
    "The exact effect remains blocked until a separate approval succeeds": "在另行审批成功前，该确切操作仍被阻止",
    "may complete the intended bounded effect": "可能完成预期的受限操作",
    "requires a separate local approval": "需要另行本地审批",
    "the effect may be externally visible or irreversible": "该操作可能对外可见或不可逆",
    "Defer and preserve handoff": "暂停并保留交接信息",
    "No effect occurs and the decision remains for later inspection": "不会执行操作，并保留此决策供稍后检查",
    "avoids acting on incomplete evidence": "避免依据不完整的证据执行操作",
    "delays completion": "延迟完成",
    "the underlying application may continue to change": "底层应用可能继续变化",
    "Deny or cancel the proposed effect": "拒绝或取消拟议操作",
    "The proposed effect is not authorized": "拟议操作未获授权",
    "prevents the proposed external effect": "阻止拟议的外部操作",
    "the requested task may remain incomplete": "请求的任务可能无法完成",
    "manual cleanup may still be required": "可能仍需手动清理",
    "Hand control to the operator": "将控制权交给操作员",
    "Agent desktop authority is released before manual work": "手动操作前会释放智能体的桌面权限",
    "keeps the operator in direct control": "让操作员保持直接控制",
    "requires manual completion": "需要手动完成",
    "automatic progress stops": "自动执行将停止",
    "Unknown": "未知",
    "Configured range": "配置范围",
    "Measured range": "测量范围",
    "Uncalibrated": "未校准",
    "Low": "低",
    "Medium": "中",
    "High": "高",
    "None": "无",
    "seconds": "秒",
    "tokens": "个 token",
    "Checkpoint": "检查点",
    "Observation": "观察",
    "Policy": "策略",
    "Object version": "对象版本",
    "Active target": "活动目标",
    "Recipient identity": "接收方身份",
    "Completion outcome": "完成结果",
    "Safety checks": "安全检查",
    "Screen state": "屏幕状态",
    "Safety policy": "安全策略",
    "Task": "任务",
    "Tool registry": "工具注册表",
    "Target object": "目标对象",
    "Evidence set": "证据集",
    "Card": "决策卡",
    "Expires": "失效时间",
    "Not started": "未开始",
    "In progress": "进行中",
    "Observing": "正在观察",
    "Planning": "正在规划",
    "Executing": "正在执行",
    "Verifying": "正在验证",
    "Recovering": "正在恢复",
    "Needs input": "需要确认",
    "Paused": "已暂停",
    "Ready": "已就绪",
    "Needs inspection": "需要检查",
    "Failed": "失败",
    "Cancelled": "已取消",
    "Completed": "已完成",
    "Skipped": "已跳过",
    "Attention": "需要关注",
    "History": "历史",
    "Campaign attention": "活动需要关注",
    "Active campaigns": "进行中的活动",
    "Campaign history": "活动历史",
    "In progress at last checkpoint; liveness unknown": "上次检查点仍在进行；当前是否存活未知",
    "Needs inspection; re-observe before retry": "需要检查；重试前请重新观察",
    "Needs input; challenge": "需要确认；存在挑战",
    "Failed; inspect before resume": "失败；恢复前请检查",
    "Needs inspection; stale before reclaim": "需要检查；重新接管前状态已过期",
    "Needs inspection; state invalid": "需要检查；状态无效",
}


def _system_locale_name() -> str:
    kernel32 = private_windll("kernel32")
    kernel32.GetUserDefaultLocaleName.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
    kernel32.GetUserDefaultLocaleName.restype = ctypes.c_int
    buffer = ctypes.create_unicode_buffer(_LOCALE_NAME_MAX_LENGTH)
    if not kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
        raise OSError("OPERATOR_SYSTEM_LOCALE_UNAVAILABLE")
    return str(buffer.value)


def resolve_operator_locale(
    preference: str,
    *,
    system_locale_loader: Callable[[], str] | None = None,
) -> OperatorLocale:
    """Resolve one strict preference without letting locale affect authority."""

    if (
        not isinstance(preference, str)
        or preference not in SUPPORTED_OPERATOR_LOCALE_PREFERENCES
    ):
        raise OperatorLocalizationError("OPERATOR_LOCALE_INVALID")
    if preference != AUTO_OPERATOR_LOCALE:
        return OperatorLocale(preference)
    loader = _system_locale_name if system_locale_loader is None else system_locale_loader
    try:
        observed = loader()
        if not isinstance(observed, str):
            raise TypeError("system locale must be text")
        normalized = observed.replace("_", "-").lower()
    except Exception:
        return OperatorLocale.EN_US
    if normalized.startswith("zh-hans") or normalized in {"zh-cn", "zh-sg"}:
        return OperatorLocale.ZH_CN
    return OperatorLocale.EN_US


def operator_text(locale: OperatorLocale, key: str, **values: object) -> str:
    """Render one reviewed copy key; arbitrary runtime text is never formatted."""

    if not isinstance(locale, OperatorLocale):
        raise OperatorLocalizationError("OPERATOR_LOCALE_INVALID")
    table = _ENGLISH_COPY if locale is OperatorLocale.EN_US else _CHINESE_COPY
    if not isinstance(key, str) or key not in table:
        raise OperatorLocalizationError("OPERATOR_COPY_KEY_INVALID")
    try:
        return table[key].format(**values)
    except (KeyError, ValueError) as exc:
        raise OperatorLocalizationError("OPERATOR_COPY_FORMAT_INVALID") from exc


def decision_button_label(
    locale: OperatorLocale,
    option_id: str,
    fallback: str,
) -> str:
    """Localize a known option id while preserving an unknown Host label."""

    if not isinstance(locale, OperatorLocale):
        raise OperatorLocalizationError("OPERATOR_LOCALE_INVALID")
    if not isinstance(option_id, str) or not isinstance(fallback, str):
        raise OperatorLocalizationError("OPERATOR_DECISION_COPY_INVALID")
    return _BUTTON_COPY[locale].get(option_id, fallback)


def localize_fixed_text(locale: OperatorLocale, value: str) -> str:
    """Translate reviewed Host copy and preserve every unmapped bounded value."""

    if not isinstance(locale, OperatorLocale) or not isinstance(value, str):
        raise OperatorLocalizationError("OPERATOR_FIXED_COPY_INVALID")
    if locale is OperatorLocale.EN_US:
        return value
    return _FIXED_CHINESE.get(value, value)


def localized_visual(
    locale: OperatorLocale,
    token: OperatorVisualToken,
) -> OperatorVisualToken:
    """Translate label/glyph while keeping the exact semantic role and color."""

    if not isinstance(locale, OperatorLocale) or not isinstance(
        token, OperatorVisualToken
    ):
        raise OperatorLocalizationError("OPERATOR_VISUAL_COPY_INVALID")
    if locale is OperatorLocale.EN_US:
        return token
    label, glyph = _VISUAL_COPY[token.role]
    return replace(token, label=label, glyph=glyph)


__all__ = [
    "AUTO_OPERATOR_LOCALE",
    "OperatorLocale",
    "OperatorLocalizationError",
    "SUPPORTED_OPERATOR_LOCALE_PREFERENCES",
    "decision_button_label",
    "localize_fixed_text",
    "localized_visual",
    "operator_text",
    "resolve_operator_locale",
]
