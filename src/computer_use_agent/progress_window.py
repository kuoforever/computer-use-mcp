"""Passive, non-activating operator progress window (delivery step 2).

This implements delivery step 2 and the rendering half of step 4 of the
[operator progress viewer](../../docs/PROGRESS_VIEWER.md): draw the small window
that shows the reducer's grouped view models without ever taking foreground or
keyboard focus. `progress_view` decides *what* a viewer may display and how runs
are grouped; this module decides *how* those groups are drawn, and its central
promise is that drawing changes nothing an operator was doing.

That promise is made structural, the same way redaction was in step 1:

* The window is created ``WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST``
  over a bare ``WS_POPUP`` — it has no taskbar button and cannot be activated.
* Every native operation goes through :class:`ProgressWindowApi`, whose surface
  deliberately has **no** activate, focus, or foreground-setting method. The
  only show is ``show_noactivate`` and the only reposition is
  ``reposition_noactivate``. A controller written against this interface cannot
  take focus because there is no call that would.

So the acceptance check "opening, refreshing, moving, or changing topmost state
does not alter the foreground HWND" is provable against a recording fake without
a desktop; the real ``Win32ProgressWindowApi`` only has to honour the same
non-activating flags, and the isolated smoke confirms it does on a live desktop.

The window renders only the whitelisted lines produced here from already
redaction-safe :class:`~computer_use_agent.progress_view.RunProgressView`
records, so no task text, title, prose, or credential can reach a pixel.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .operator_localization import (
    OperatorLocale,
    localized_visual,
    localize_fixed_text,
    operator_text,
)
from .operator_visuals import (
    OperatorVisualRole,
    OperatorVisualToken,
    operator_visual,
)
from .progress_view import (
    CampaignProgressView,
    ProgressProjection,
    RunProgressView,
    group_campaign_views,
    group_progress_views,
)
from .workflow_checklist import (
    WorkflowChecklist,
    WorkflowStatus,
    WorkflowStepStatus,
)

# The passive window is a monitoring surface, not a console: it shows a bounded
# newest slice rather than an unbounded scroll. The reducer already caps the
# scan; this caps what is drawn so a large ``state_dir`` can never grow the
# window without bound.
MAX_DISPLAYED_RUNS = 20
MAX_DISPLAYED_CAMPAIGNS = 10
_MAX_LINE_CHARS = 120
_MAX_LISTED_UNAVAILABLE = 5

# Documented Win32 window styles. Kept named here so both the controller's
# create call and its tests refer to one source, and a reviewer can see the
# exact non-activating flag set without opening the native adapter.
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

#: Extended style for the passive window: never activates, no taskbar button,
#: stays above ordinary windows.
PASSIVE_EX_STYLE = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
#: Base style: a borderless popup with no controls that could take focus.
PASSIVE_STYLE = WS_POPUP


def _clip(line: str) -> str:
    """Bound one rendered line so a long but validated run id cannot overflow."""

    if len(line) <= _MAX_LINE_CHARS:
        return line
    return line[: _MAX_LINE_CHARS - 1] + "…"


def _run_lines(
    view: RunProgressView,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> tuple[str, ...]:
    """Render one run as a bounded, whitelisted block of display lines.

    Only fields already present on the redaction-safe view model are read, so
    forbidden checkpoint content cannot be introduced here. Unknown facts are
    labelled honestly rather than shown as a misleading zero or "running".
    """

    if view.is_terminal:
        step = view.tool_calls.used
    else:
        step = min(view.tool_calls.used + 1, view.tool_calls.limit)
    phase = localize_fixed_text(
        locale,
        view.phase.replace("_", " ").title(),
    )
    display_state = localize_fixed_text(locale, view.display_state)
    head = operator_text(
        locale,
        "progress_run_head",
        run_id=view.run_id,
        step=step,
        limit=view.tool_calls.limit,
        phase=phase,
        state=display_state,
    )
    if view.needs_reobserve:
        # Acceptance check 7: distinct, and never a retry affordance — this is a
        # passive label, not a button.
        head += "  " + operator_text(locale, "reobserve_marker")

    calls = operator_text(
        locale,
        "progress_run_calls",
        model_used=view.model_calls.used,
        model_limit=view.model_calls.limit,
        tool_used=view.tool_calls.used,
        tool_limit=view.tool_calls.limit,
    )

    token_note = operator_text(
        locale,
        "coverage_known" if view.token_coverage_known else "coverage_unknown",
    )
    screenshot_note = (
        str(view.screenshot_results)
        if view.screenshot_count_known
        else operator_text(locale, "screenshots_unavailable")
    )
    usage = operator_text(
        locale,
        "progress_run_usage",
        input_tokens=view.input_tokens,
        output_tokens=view.output_tokens,
        coverage=token_note,
        screenshots=screenshot_note,
        failures=view.tool_failures,
    )

    if view.is_terminal:
        if view.duration_ms is not None:
            usage += (
                f"  ran {view.duration_ms}ms"
                if locale is OperatorLocale.EN_US
                else f"  已运行 {view.duration_ms}ms"
            )
    else:
        if view.elapsed_known and view.duration_ms is not None:
            usage += (
                f"  elapsed {view.duration_ms}ms at checkpoint"
                if locale is OperatorLocale.EN_US
                else f"  检查点已用时 {view.duration_ms}ms"
            )
        # A checkpoint cannot prove a nonterminal run is still alive.
        usage += (
            "  liveness unknown"
            if locale is OperatorLocale.EN_US
            else "  当前是否存活未知"
        )

    return (_clip(head), _clip(calls), _clip(usage))


def _campaign_lines(
    view: CampaignProgressView,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> tuple[str, ...]:
    """Render only the bounded aggregate facts admitted by the campaign view."""

    head = (
        f"{view.campaign_id}  "
        f"{localize_fixed_text(locale, view.display_state)}"
    )
    counts = operator_text(
        locale,
        "progress_campaign_counts",
        completed=view.completed_count,
        discovered=view.discovered_count,
        retryable=view.retryable_count,
        uncertain=view.uncertain_count,
    )
    return (_clip(head), _clip(counts))


_WORKFLOW_STATUS_ROLES = {
    WorkflowStatus.NOT_STARTED: OperatorVisualRole.NOT_STARTED,
    WorkflowStatus.RUNNING: OperatorVisualRole.IN_PROGRESS,
    WorkflowStatus.NEEDS_INPUT: OperatorVisualRole.NEEDS_INPUT,
    WorkflowStatus.PAUSED: OperatorVisualRole.PAUSED,
    WorkflowStatus.VERIFYING: OperatorVisualRole.VERIFYING,
    WorkflowStatus.READY: OperatorVisualRole.READY,
    WorkflowStatus.FAILED: OperatorVisualRole.FAILED,
    WorkflowStatus.UNCERTAIN: OperatorVisualRole.NEEDS_INSPECTION,
    WorkflowStatus.CANCELLED: OperatorVisualRole.CANCELLED,
}
_WORKFLOW_STEP_LABELS = {
    WorkflowStepStatus.NOT_STARTED: "Not started",
    WorkflowStepStatus.IN_PROGRESS: "In progress",
    WorkflowStepStatus.WAITING_APPROVAL: "Needs input",
    WorkflowStepStatus.COMPLETED: "Completed",
    WorkflowStepStatus.SKIPPED: "Skipped",
    WorkflowStepStatus.FAILED: "Failed",
    WorkflowStepStatus.UNCERTAIN: "Needs inspection",
}
_WORKFLOW_STEP_GLYPHS = {
    WorkflowStepStatus.NOT_STARTED: "○",
    WorkflowStepStatus.IN_PROGRESS: "●",
    WorkflowStepStatus.WAITING_APPROVAL: "◆",
    WorkflowStepStatus.COMPLETED: "✓",
    WorkflowStepStatus.SKIPPED: "–",
    WorkflowStepStatus.FAILED: "×",
    WorkflowStepStatus.UNCERTAIN: "!",
}


def workflow_visual(
    status: WorkflowStatus,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> OperatorVisualToken:
    """Return the shared visual token for one validated workflow status."""

    if not isinstance(status, WorkflowStatus):
        raise ProgressWindowError("PROGRESS_WORKFLOW_STATUS_INVALID")
    return localized_visual(locale, operator_visual(_WORKFLOW_STATUS_ROLES[status]))


def render_workflow_summary_lines(
    checklist: WorkflowChecklist,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> tuple[str, ...]:
    """Render one trusted workflow as a compact human-readable HUD summary.

    Approval counts and tool-call budgets are deliberately absent. The summary
    answers only the global operator questions: what workflow is this, what is
    its overall state, how many chapters are complete/skipped/not started, and
    which fixed chapter/application currently owns attention.
    """

    if not isinstance(checklist, WorkflowChecklist):
        raise ProgressWindowError("PROGRESS_WORKFLOW_INVALID")
    visual = workflow_visual(checklist.status, locale)
    total = len(checklist.steps)
    count_parts = [
        operator_text(locale, "completed_count", count=checklist.completed_count)
    ]
    if checklist.skipped_count:
        count_parts.append(
            operator_text(locale, "skipped_count", count=checklist.skipped_count)
        )
    count_parts.append(
        operator_text(locale, "not_started_count", count=checklist.not_started_count)
    )
    count_parts.append(operator_text(locale, "total_count", count=total))

    if checklist.current_step_id is None:
        current_line = {
            WorkflowStatus.NOT_STARTED: operator_text(locale, "ready_to_begin"),
            WorkflowStatus.READY: operator_text(
                locale, "all_workflow_steps_resolved"
            ),
            WorkflowStatus.CANCELLED: operator_text(
                locale, "no_workflow_step_active"
            ),
        }.get(checklist.status, operator_text(locale, "no_workflow_step_active"))
        action_line = "—"
        application_line = operator_text(locale, "no_application_active")
    else:
        current = next(
            step
            for step in checklist.steps
            if step.step_id == checklist.current_step_id
        )
        current_line = (
            operator_text(
                locale,
                "current_step",
                current=checklist.current_step_number,
                total=total,
            )
            if current.status is not WorkflowStepStatus.WAITING_APPROVAL
            else operator_text(
                locale,
                "approval_needed_step",
                current=checklist.current_step_number,
                total=total,
            )
        )
        action_line = localize_fixed_text(locale, current.label)
        application_line = localize_fixed_text(locale, current.application)

    return tuple(
        _clip(line)
        for line in (
            f"{operator_text(locale, 'product_name').upper()}  ·  {visual.label.upper()}",
            localize_fixed_text(locale, checklist.title),
            "  ·  ".join(count_parts),
            current_line,
            action_line,
            application_line,
        )
    )


def render_workflow_detail_lines(
    checklist: WorkflowChecklist,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> tuple[str, ...]:
    """Extend the compact summary with every bounded, Host-owned checklist row."""

    lines = list(render_workflow_summary_lines(checklist, locale))
    lines.append(operator_text(locale, "workflow_checklist"))
    for index, step in enumerate(checklist.steps, start=1):
        lines.append(
            _clip(
                f"{_WORKFLOW_STEP_GLYPHS[step.status]}  {index}  "
                f"{localize_fixed_text(locale, step.label)}"
            )
        )
        lines.append(
            _clip(
                f"    {localize_fixed_text(locale, step.application)}  ·  "
                f"{localize_fixed_text(locale, _WORKFLOW_STEP_LABELS[step.status])}"
            )
        )
    return tuple(lines)


def workflow_accessible_name(
    lines: Sequence[str],
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> str:
    """Compress the fixed six-line workflow summary into one bounded UIA name."""

    summary = tuple(lines)
    if (
        len(summary) != 6
        or not summary[0].startswith(
            f"{operator_text(locale, 'product_name').upper()}  ·  "
        )
        or any(not isinstance(line, str) or len(line) > _MAX_LINE_CHARS for line in summary)
    ):
        raise ProgressWindowError("PROGRESS_ACCESSIBLE_SUMMARY_INVALID")
    status = summary[0].partition("·")[2].strip().capitalize()
    current = summary[3].replace("·", ".").capitalize()
    if locale is OperatorLocale.ZH_CN:
        return (
            f"电脑操作。{status}。流程 {summary[1]}。{current}。"
            f"{summary[4]}。应用 {summary[5]}。"
        )
    return (
        f"Computer Use. {status}. Workflow {summary[1]}. {current}. "
        f"{summary[4]}. Application {summary[5]}."
    )


def render_progress_lines(
    projection: ProgressProjection,
    *,
    workflow: WorkflowChecklist | None = None,
    expanded: bool = False,
    locale: OperatorLocale = OperatorLocale.EN_US,
) -> tuple[str, ...]:
    """Project a bounded scan into the exact lines the passive window draws.

    The result is a flat, bounded tuple of plain strings. It carries a header
    with honest run counts, fixed operator-relevance groups, and one block per
    shown run (newest-first within each group, globally capped at
    :data:`MAX_DISPLAYED_RUNS`). Attention is allocated first so terminal
    history cannot hide a waiting or uncertain run.
    """

    if not isinstance(expanded, bool):
        raise ProgressWindowError("PROGRESS_EXPANDED_INVALID")
    if workflow is not None:
        return (
            render_workflow_detail_lines(workflow, locale)
            if expanded
            else render_workflow_summary_lines(workflow, locale)
        )
    if expanded:
        raise ProgressWindowError("PROGRESS_WORKFLOW_UNAVAILABLE")

    total = len(projection.views)
    shown = min(total, MAX_DISPLAYED_RUNS)
    campaign_total = len(projection.campaigns)
    campaign_shown = min(campaign_total, MAX_DISPLAYED_CAMPAIGNS)
    if campaign_total or projection.unavailable_campaign_ids or projection.unavailable_campaign_unnamed:
        header = operator_text(
            locale,
            "progress_header_campaigns",
            campaign_shown=campaign_shown,
            campaign_total=campaign_total,
            shown=shown,
            total=total,
        )
    else:
        header = operator_text(
            locale,
            "progress_header_runs",
            shown=shown,
            total=total,
        )
    lines: list[str] = [_clip(header)]

    remaining_campaigns = MAX_DISPLAYED_CAMPAIGNS
    for campaign_group in group_campaign_views(projection.campaigns):
        if remaining_campaigns <= 0:
            break
        campaign_views = campaign_group.views[:remaining_campaigns]
        group_total = len(campaign_group.views)
        group_shown = len(campaign_views)
        count = (
            str(group_total)
            if group_shown == group_total
            else f"{group_shown}/{group_total}"
        )
        lines.append(
            _clip(f"{localize_fixed_text(locale, campaign_group.label)}  {count}")
        )
        for campaign_view in campaign_views:
            lines.extend(_campaign_lines(campaign_view, locale))
        remaining_campaigns -= group_shown

    if projection.unavailable_campaign_ids:
        unavailable_campaigns = projection.unavailable_campaign_ids
        listed = ", ".join(unavailable_campaigns[:_MAX_LISTED_UNAVAILABLE])
        suffix = "" if len(unavailable_campaigns) <= _MAX_LISTED_UNAVAILABLE else ", …"
        lines.append(
            _clip(
                operator_text(
                    locale,
                    "progress_unavailable_campaigns",
                    count=len(unavailable_campaigns),
                    listed=listed,
                    suffix=suffix,
                )
            )
        )
    if projection.unavailable_campaign_unnamed:
        lines.append(
            _clip(
                operator_text(
                    locale,
                    "progress_hidden_campaigns",
                    count=projection.unavailable_campaign_unnamed,
                )
            )
        )

    remaining = MAX_DISPLAYED_RUNS
    for run_group in group_progress_views(projection.views):
        if remaining <= 0:
            break
        run_views = run_group.views[:remaining]
        group_total = len(run_group.views)
        group_shown = len(run_views)
        count = str(group_total) if group_shown == group_total else f"{group_shown}/{group_total}"
        lines.append(
            _clip(f"{localize_fixed_text(locale, run_group.label)}  {count}")
        )
        for run_view in run_views:
            lines.extend(_run_lines(run_view, locale))
        remaining -= group_shown

    unavailable = projection.unavailable_run_ids
    if unavailable:
        listed = ", ".join(unavailable[:_MAX_LISTED_UNAVAILABLE])
        suffix = "" if len(unavailable) <= _MAX_LISTED_UNAVAILABLE else ", …"
        lines.append(
            _clip(
                operator_text(
                    locale,
                    "progress_unavailable_runs",
                    count=len(unavailable),
                    listed=listed,
                    suffix=suffix,
                )
            )
        )
    if projection.unavailable_unnamed:
        lines.append(
            _clip(
                operator_text(
                    locale,
                    "progress_hidden_runs",
                    count=projection.unavailable_unnamed,
                )
            )
        )

    return tuple(lines)


@runtime_checkable
class ProgressWindowApi(Protocol):
    """The minimal native surface the passive window needs — and no more.

    There is intentionally no ``activate``, ``focus``, ``foreground(set)``, or
    ``bring_to_top`` method. The only show is non-activating and the only
    reposition is non-activating, so a controller written against this interface
    cannot steal foreground: the operation simply does not exist to call.
    ``foreground()`` is read-only and exists only so a test or smoke can assert
    the foreground HWND was unchanged.
    """

    def create(self, *, ex_style: int, style: int, title: str) -> int: ...

    def set_lines(self, hwnd: int, lines: Sequence[str]) -> None: ...

    def set_workflow_lines(
        self,
        hwnd: int,
        *,
        compact_lines: Sequence[str],
        expanded_lines: Sequence[str],
        expanded: bool,
        accent_rgb: int,
        on_toggle: Callable[[bool], None],
    ) -> None: ...

    def show_noactivate(self, hwnd: int) -> None: ...

    def reposition_noactivate(self, hwnd: int, *, x: int, y: int, topmost: bool) -> None: ...

    def foreground(self) -> int: ...

    def destroy(self, hwnd: int) -> None: ...


class ProgressWindowError(RuntimeError):
    """A fixed passive-window failure that never embeds checkpoint content."""


@dataclass
class PassiveProgressWindow:
    """Drive one passive progress window over an injected native API.

    The controller holds no checkpoint content: it turns a projection into
    whitelisted lines via :func:`render_progress_lines` and hands only those to
    the API. Position and topmost state are remembered so a topmost toggle can
    reposition without moving the window.
    """

    api: ProgressWindowApi
    title: str = "Computer Use"
    locale: OperatorLocale = OperatorLocale.EN_US
    _hwnd: int | None = field(default=None, init=False)
    _x: int = field(default=24, init=False)
    _y: int = field(default=24, init=False)
    _topmost: bool = field(default=True, init=False)
    _projection: ProgressProjection | None = field(default=None, init=False, repr=False)
    _workflow: WorkflowChecklist | None = field(default=None, init=False, repr=False)
    _expanded: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.locale, OperatorLocale):
            raise ProgressWindowError("PROGRESS_LOCALE_INVALID")

    @property
    def hwnd(self) -> int | None:
        return self._hwnd

    @property
    def expanded(self) -> bool:
        return self._expanded

    def open(
        self,
        projection: ProgressProjection,
        *,
        workflow: WorkflowChecklist | None = None,
        expanded: bool | None = None,
    ) -> int:
        """Create the window with workflow steps visible unless explicitly collapsed."""

        if self._hwnd is not None:
            self.update(projection, workflow=workflow, expanded=expanded)
            return self._hwnd
        initial_expanded = workflow is not None if expanded is None else expanded
        self._remember_content(projection, workflow, initial_expanded)
        hwnd = self.api.create(ex_style=PASSIVE_EX_STYLE, style=PASSIVE_STYLE, title=self.title)
        self._hwnd = hwnd
        self._set_content(hwnd)
        self.api.show_noactivate(hwnd)
        return hwnd

    def update(
        self,
        projection: ProgressProjection,
        *,
        workflow: WorkflowChecklist | None = None,
        expanded: bool | None = None,
    ) -> None:
        """Refresh without activation, preserving an operator's checklist toggle."""

        hwnd = self._require_open()
        if expanded is None:
            next_expanded = self._expanded if workflow is not None else False
        else:
            next_expanded = expanded
        self._remember_content(projection, workflow, next_expanded)
        self._set_content(hwnd)

    def set_expanded(self, expanded: bool) -> None:
        """Switch checklist detail without focus, activation, or authority."""

        hwnd = self._require_open()
        if not isinstance(expanded, bool):
            raise ProgressWindowError("PROGRESS_EXPANDED_INVALID")
        if self._projection is None or self._workflow is None:
            raise ProgressWindowError("PROGRESS_WORKFLOW_UNAVAILABLE")
        self._expanded = expanded
        self._set_content(hwnd)

    def toggle_details(self) -> None:
        """Toggle the bounded checklist while preserving workflow state."""

        self.set_expanded(not self._expanded)

    def move(self, x: int, y: int) -> None:
        """Reposition non-activated, preserving the current topmost state."""

        self._x, self._y = x, y
        self._reposition()

    def set_topmost(self, topmost: bool) -> None:
        """Toggle always-on-top without moving or activating the window."""

        self._topmost = topmost
        self._reposition()

    def close(self) -> None:
        """Destroy the window. Idempotent; a closed window can be reopened."""

        if self._hwnd is None:
            return
        self.api.destroy(self._hwnd)
        self._hwnd = None
        self._projection = None
        self._workflow = None
        self._expanded = False

    def _reposition(self) -> None:
        hwnd = self._require_open()
        self.api.reposition_noactivate(hwnd, x=self._x, y=self._y, topmost=self._topmost)

    def _require_open(self) -> int:
        if self._hwnd is None:
            raise ProgressWindowError("PROGRESS_WINDOW_NOT_OPEN")
        return self._hwnd

    def _remember_content(
        self,
        projection: ProgressProjection,
        workflow: WorkflowChecklist | None,
        expanded: bool,
    ) -> None:
        if not isinstance(expanded, bool):
            raise ProgressWindowError("PROGRESS_EXPANDED_INVALID")
        if expanded and workflow is None:
            raise ProgressWindowError("PROGRESS_WORKFLOW_UNAVAILABLE")
        self._projection = projection
        self._workflow = workflow
        self._expanded = expanded

    def _set_content(self, hwnd: int) -> None:
        if self._projection is None:
            raise ProgressWindowError("PROGRESS_PROJECTION_UNAVAILABLE")
        if self._workflow is None:
            self.api.set_lines(
                hwnd,
                render_progress_lines(self._projection, locale=self.locale),
            )
            return
        self.api.set_workflow_lines(
            hwnd,
            compact_lines=render_workflow_summary_lines(self._workflow, self.locale),
            expanded_lines=render_workflow_detail_lines(self._workflow, self.locale),
            expanded=self._expanded,
            accent_rgb=workflow_visual(self._workflow.status, self.locale).color_rgb,
            on_toggle=self._on_native_toggle,
        )

    def _on_native_toggle(self, expanded: bool) -> None:
        if not isinstance(expanded, bool):
            return
        self._expanded = expanded


__all__ = [
    "MAX_DISPLAYED_CAMPAIGNS",
    "MAX_DISPLAYED_RUNS",
    "PASSIVE_EX_STYLE",
    "PASSIVE_STYLE",
    "PassiveProgressWindow",
    "ProgressWindowApi",
    "ProgressWindowError",
    "render_progress_lines",
    "render_workflow_detail_lines",
    "render_workflow_summary_lines",
    "workflow_accessible_name",
    "workflow_visual",
]
