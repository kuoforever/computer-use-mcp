"""Tests for the passive, non-activating operator progress window (step 2).

These exercise the controller and the line renderer against a recording fake
native API, so the non-activating contract and structural redaction are proven
without a desktop. The real ctypes backend is out of scope here; it is verified
by the operator-approved ``scripts/smoke_progress_window.py``.
"""
from __future__ import annotations

import pytest

from computer_use_agent.progress_view import (
    CallBudget,
    CampaignProgressView,
    ProgressProjection,
    RunProgressView,
)
from computer_use_agent.progress_window import (
    MAX_DISPLAYED_CAMPAIGNS,
    MAX_DISPLAYED_RUNS,
    PASSIVE_EX_STYLE,
    PASSIVE_STYLE,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST,
    WS_POPUP,
    PassiveProgressWindow,
    ProgressWindowApi,
    ProgressWindowError,
    render_progress_lines,
    render_workflow_detail_lines,
    render_workflow_summary_lines,
    workflow_accessible_name,
)
from computer_use_agent.demo_cross_app import DEMO_WORKFLOW
from computer_use_agent.operator_localization import OperatorLocale
from computer_use_agent.workflow_checklist import WorkflowStatus

FORBIDDEN = "PROGRESS_TASK_SECRET"

# Any focus/activation entry point a real Win32 window could offer. The fake
# raises if the controller ever reaches for one, so "cannot take focus" is
# asserted structurally rather than by inspecting flags alone.
_FORBIDDEN_CALLS = frozenset(
    {"activate", "set_focus", "set_foreground", "bring_to_top", "show", "focus"}
)


class FakeProgressWindowApi:
    """A fake :class:`ProgressWindowApi` that records the call sequence.

    Its foreground never changes: nothing on the real interface can move it, so
    a stable value here mirrors the real contract. Reaching for a focus-taking
    call (which the interface does not define) raises immediately.
    """

    def __init__(self, foreground: int = 4242) -> None:
        self.calls: list[tuple] = []
        self.lines: dict[int, tuple[str, ...]] = {}
        self.workflow_lines: dict[
            int,
            tuple[tuple[str, ...], tuple[str, ...]],
        ] = {}
        self.toggle_handlers: dict[int, object] = {}
        self._foreground = foreground
        self._next_hwnd = 1000
        self.alive: set[int] = set()

    def create(self, *, ex_style: int, style: int, title: str) -> int:
        self._next_hwnd += 1
        hwnd = self._next_hwnd
        self.alive.add(hwnd)
        self.calls.append(("create", ex_style, style, title, hwnd))
        return hwnd

    def set_lines(self, hwnd: int, lines) -> None:
        self.workflow_lines.pop(hwnd, None)
        self.toggle_handlers.pop(hwnd, None)
        self.lines[hwnd] = tuple(lines)
        self.calls.append(("set_lines", hwnd, tuple(lines)))

    def set_workflow_lines(
        self,
        hwnd: int,
        *,
        compact_lines,
        expanded_lines,
        expanded: bool,
        accent_rgb: int,
        on_toggle,
    ) -> None:
        variants = (tuple(compact_lines), tuple(expanded_lines))
        self.workflow_lines[hwnd] = variants
        self.toggle_handlers[hwnd] = on_toggle
        self.lines[hwnd] = variants[1] if expanded else variants[0]
        self.calls.append(("set_workflow_lines", hwnd, expanded, accent_rgb))

    def show_noactivate(self, hwnd: int) -> None:
        self.calls.append(("show_noactivate", hwnd))

    def reposition_noactivate(self, hwnd: int, *, x: int, y: int, topmost: bool) -> None:
        self.calls.append(("reposition_noactivate", hwnd, x, y, topmost))

    def foreground(self) -> int:
        return self._foreground

    def destroy(self, hwnd: int) -> None:
        self.alive.discard(hwnd)
        self.workflow_lines.pop(hwnd, None)
        self.toggle_handlers.pop(hwnd, None)
        self.calls.append(("destroy", hwnd))

    def click_workflow_toggle(self, hwnd: int) -> None:
        variants = self.workflow_lines[hwnd]
        expanded = self.lines[hwnd] == variants[1]
        next_expanded = not expanded
        self.lines[hwnd] = variants[1] if next_expanded else variants[0]
        handler = self.toggle_handlers[hwnd]
        assert callable(handler)
        handler(next_expanded)

    def __getattr__(self, name: str):  # pragma: no cover - only hit on misuse
        if name in _FORBIDDEN_CALLS:
            raise AssertionError(f"passive window must never call {name!r}")
        raise AttributeError(name)

    def kinds(self) -> list[str]:
        return [call[0] for call in self.calls]


def _view(run_id: str, *, phase: str = "PLANNING", **over) -> RunProgressView:
    base = dict(
        run_id=run_id,
        phase=phase,
        display_state="In progress at last checkpoint; liveness unknown",
        is_terminal=False,
        liveness_known=False,
        needs_reobserve=False,
        model_calls=CallBudget(used=1, limit=3),
        tool_calls=CallBudget(used=2, limit=4),
        input_tokens=11,
        output_tokens=5,
        token_coverage_known=False,
        image_results=0,
        screenshot_results=0,
        screenshot_count_known=False,
        tool_failures=0,
        elapsed_known=False,
        duration_ms=None,
        failure_code=None,
    )
    base.update(over)
    return RunProgressView(**base)


def _projection(*views: RunProgressView, unavailable=(), unnamed: int = 0) -> ProgressProjection:
    return ProgressProjection(
        views=tuple(views),
        unavailable_run_ids=tuple(unavailable),
        unavailable_unnamed=unnamed,
    )


def _campaign(campaign_id: str, *, status: str = "RUNNING", **over) -> CampaignProgressView:
    base = dict(
        campaign_id=campaign_id,
        status=status,
        display_state="In progress",
        is_terminal=False,
        needs_attention=False,
        discovered_count=5,
        completed_count=2,
        retryable_count=1,
        uncertain_count=0,
        updated_at_us=1,
    )
    base.update(over)
    return CampaignProgressView(**base)


def test_recording_api_satisfies_the_interface() -> None:
    assert isinstance(FakeProgressWindowApi(), ProgressWindowApi)


def test_open_creates_nonactivating_window_and_shows_without_focus() -> None:
    api = FakeProgressWindowApi()
    window = PassiveProgressWindow(api)

    hwnd = window.open(_projection(_view("run_ab12")))

    create = next(call for call in api.calls if call[0] == "create")
    assert create[1] == PASSIVE_EX_STYLE
    # The exact non-activating flag set a reviewer cares about.
    assert create[1] & WS_EX_NOACTIVATE
    assert create[1] & WS_EX_TOOLWINDOW
    assert create[1] & WS_EX_TOPMOST
    assert create[2] == PASSIVE_STYLE == WS_POPUP
    # Shown, but only non-activated; the window is populated before it appears.
    assert api.kinds() == ["create", "set_lines", "show_noactivate"]
    assert window.hwnd == hwnd


def test_full_cycle_never_changes_foreground() -> None:
    # Acceptance check 1, in injectable form: open, refresh, move, retop, close —
    # the foreground HWND the operator was using is untouched throughout.
    api = FakeProgressWindowApi(foreground=777)
    window = PassiveProgressWindow(api)
    before = api.foreground()

    window.open(_projection(_view("run_a")))
    window.update(
        _projection(
            _view(
                "run_a",
                phase="SUCCESS",
                display_state="Ready",
                is_terminal=True,
                liveness_known=True,
            )
        )
    )
    window.move(120, 240)
    window.set_topmost(False)
    window.close()

    assert api.foreground() == before == 777
    assert "reposition_noactivate" in api.kinds()
    # Move keeps position for a later topmost toggle without re-moving.
    move = next(c for c in api.calls if c[0] == "reposition_noactivate")
    assert (move[2], move[3], move[4]) == (120, 240, True)
    retop = [c for c in api.calls if c[0] == "reposition_noactivate"][-1]
    assert (retop[2], retop[3], retop[4]) == (120, 240, False)


def test_reopen_after_close_and_idempotent_close() -> None:
    api = FakeProgressWindowApi()
    window = PassiveProgressWindow(api)

    window.open(_projection(_view("run_a")))
    window.close()
    window.close()  # idempotent: no second destroy
    assert api.kinds().count("destroy") == 1

    window.open(_projection(_view("run_b")))
    assert window.hwnd in api.alive


def test_open_twice_refreshes_instead_of_recreating() -> None:
    api = FakeProgressWindowApi()
    window = PassiveProgressWindow(api)

    first = window.open(_projection(_view("run_a")))
    second = window.open(
        _projection(
            _view(
                "run_a",
                phase="SUCCESS",
                display_state="Ready",
                is_terminal=True,
                liveness_known=True,
            )
        )
    )

    assert first == second
    assert api.kinds().count("create") == 1
    assert api.lines[first][1:]  # refreshed lines present


def test_operations_before_open_fail_closed() -> None:
    window = PassiveProgressWindow(FakeProgressWindowApi())
    for action in (
        lambda: window.update(_projection(_view("run_a"))),
        lambda: window.move(1, 2),
        lambda: window.set_topmost(True),
    ):
        with pytest.raises(ProgressWindowError):
            action()


def test_rendered_lines_exclude_forbidden_content() -> None:
    # The view model has no field for task text/title/prose, so structurally
    # nothing forbidden can appear. Guard against a future field leaking in.
    lines = render_progress_lines(_projection(_view("run_ok")))
    blob = "\n".join(lines)
    assert FORBIDDEN not in blob
    assert "http" not in blob


def test_workflow_summary_answers_global_progress_questions() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    assert render_workflow_summary_lines(checklist) == (
        "COMPUTER USE  ·  IN PROGRESS",
        "Public-source research brief update",
        "2 completed  ·  3 not started  ·  6 total",
        "CURRENT STEP 3 OF 6",
        "Open the research brief",
        "Microsoft Word",
    )


def test_workflow_accessible_name_contains_only_the_bounded_operator_summary() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    name = workflow_accessible_name(render_workflow_summary_lines(checklist))

    assert name == (
        "Computer Use. In progress. Workflow Public-source research brief update. "
        "Current step 3 of 6. Open the research brief. Application Microsoft Word."
    )
    assert len(name) <= 600


def test_simplified_chinese_workflow_keeps_unknown_application_text() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    lines = render_workflow_summary_lines(checklist, OperatorLocale.ZH_CN)
    name = workflow_accessible_name(lines, OperatorLocale.ZH_CN)

    assert lines == (
        "电脑操作  ·  进行中",
        "公开来源研究简报更新",
        "已完成 2 项  ·  未开始 3 项  ·  共 6 项",
        "当前第 3/6 步",
        "打开研究简报",
        "Microsoft Word",
    )
    assert name == (
        "电脑操作。进行中。流程 公开来源研究简报更新。当前第 3/6 步。"
        "打开研究简报。应用 Microsoft Word。"
    )

    detail = render_workflow_detail_lines(checklist, OperatorLocale.ZH_CN)
    assert detail[6] == "流程清单"
    assert detail[7:9] == (
        "✓  1  准备受控演示工作区",
        "    演示准备  ·  已完成",
    )

    setup = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        current_step_id="prepare_workspace",
    )
    assert render_workflow_summary_lines(setup, OperatorLocale.ZH_CN)[5] == (
        "演示准备"
    )


def test_simplified_chinese_diagnostic_progress_preserves_run_id() -> None:
    lines = "\n".join(
        render_progress_lines(
            _projection(_view("run_operator_owned")),
            locale=OperatorLocale.ZH_CN,
        )
    )

    assert "run_operator_owned" in lines
    assert "第 3/4 步" in lines
    assert "覆盖范围未知" in lines
    assert "当前是否存活未知" in lines


def test_workflow_summary_hides_tool_budget_and_run_diagnostics() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.NEEDS_INPUT,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    lines = render_progress_lines(
        _projection(_view("run_internal")),
        workflow=checklist,
    )
    blob = "\n".join(lines)

    assert lines[0] == "COMPUTER USE  ·  NEEDS INPUT"
    assert lines[3] == "APPROVAL NEEDED · STEP 3 OF 6"
    assert "run_internal" not in blob
    assert "model" not in blob
    assert "tool" not in blob


def test_workflow_attention_uses_the_shared_amber_visual_role() -> None:
    api = FakeProgressWindowApi()
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.NEEDS_INPUT,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    PassiveProgressWindow(api).open(_projection(), workflow=checklist)

    call = next(item for item in api.calls if item[0] == "set_workflow_lines")
    assert call[3] == 0xF2C94C


def test_expanded_workflow_lists_every_step_and_human_status() -> None:
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    lines = render_workflow_detail_lines(checklist)

    assert len(lines) == 19
    assert lines[6] == "WORKFLOW CHECKLIST"
    assert lines[7:13] == (
        "✓  1  Prepare the controlled demo workspace",
        "    Demo setup  ·  Completed",
        "✓  2  Review the public collaboration guide",
        "    Google Chrome  ·  Completed",
        "●  3  Open the research brief",
        "    Microsoft Word  ·  In progress",
    )
    assert lines[-2:] == (
        "○  6  Verify the saved document",
        "    Microsoft Word  ·  Not started",
    )


def test_expanded_workflow_rejects_missing_workflow() -> None:
    with pytest.raises(
        ProgressWindowError,
        match="PROGRESS_WORKFLOW_UNAVAILABLE",
    ):
        render_progress_lines(_projection(), expanded=True)


def test_passive_window_can_open_and_refresh_with_workflow_summary() -> None:
    api = FakeProgressWindowApi()
    window = PassiveProgressWindow(api)
    running = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace",),
        current_step_id="review_public_source",
    )
    verifying = DEMO_WORKFLOW.project(
        WorkflowStatus.VERIFYING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    hwnd = window.open(_projection(), workflow=running)
    window.update(_projection(), workflow=verifying)

    assert api.lines[hwnd][0] == "COMPUTER USE  ·  VERIFYING"
    assert api.foreground() == 4242


def test_passive_workflow_defaults_expanded_and_preserves_operator_collapse() -> None:
    api = FakeProgressWindowApi()
    window = PassiveProgressWindow(api)
    checklist = DEMO_WORKFLOW.project(
        WorkflowStatus.RUNNING,
        completed_step_ids=("prepare_workspace", "review_public_source"),
        current_step_id="open_research_brief",
    )

    hwnd = window.open(_projection(), workflow=checklist)
    expanded_lines = api.lines[hwnd]
    window.toggle_details()
    compact_lines = api.lines[hwnd]
    window.update(_projection(), workflow=checklist)

    assert len(compact_lines) == 6
    assert len(expanded_lines) == 19
    assert api.lines[hwnd] == compact_lines
    assert window.expanded is False
    assert api.foreground() == 4242

    api.click_workflow_toggle(hwnd)
    assert window.expanded is True
    assert api.lines[hwnd] == expanded_lines


def test_diagnostic_progress_cannot_expand_as_workflow() -> None:
    window = PassiveProgressWindow(FakeProgressWindowApi())
    window.open(_projection(_view("run_a")))

    with pytest.raises(
        ProgressWindowError,
        match="PROGRESS_WORKFLOW_UNAVAILABLE",
    ):
        window.set_expanded(True)


def test_unknown_facts_are_labelled_not_faked() -> None:
    lines = "\n".join(render_progress_lines(_projection(_view("run_mid"))))
    assert "coverage unknown" in lines
    assert "screenshots unavailable" in lines
    assert "liveness unknown" in lines
    # A nonterminal run is never labelled running.
    assert "running" not in lines.lower()


def test_known_usage_screenshots_and_checkpoint_elapsed_are_rendered() -> None:
    lines = "\n".join(
        render_progress_lines(
            _projection(
                _view(
                    "run_known",
                    token_coverage_known=True,
                    screenshot_results=2,
                    screenshot_count_known=True,
                    elapsed_known=True,
                    duration_ms=321,
                )
            )
        )
    )

    assert "(known)" in lines
    assert "screenshots 2" in lines
    assert "elapsed 321ms at checkpoint" in lines
    assert "liveness unknown" in lines


def test_reobserve_is_marked_and_never_a_retry_button() -> None:
    view = _view(
        "run_unsure",
        phase="UNKNOWN_OUTCOME",
        display_state="Needs inspection; re-observe before retry",
        is_terminal=True,
        needs_reobserve=True,
    )
    lines = "\n".join(render_progress_lines(_projection(view)))
    assert "[re-observe]" in lines
    assert "retry" not in lines.lower().replace("re-observe before retry", "")


def test_terminal_duration_shown_only_when_present() -> None:
    done = _view(
        "run_done",
        phase="SUCCESS",
        display_state="Ready",
        is_terminal=True,
        duration_ms=1234,
    )
    lines = "\n".join(render_progress_lines(_projection(done)))
    assert "ran 1234ms" in lines
    assert "liveness unknown" not in lines


def test_header_counts_and_newest_first_bounded_display() -> None:
    views = [
        _view(f"run_{i:03d}", updated_at_us=i) for i in range(MAX_DISPLAYED_RUNS + 5)
    ]
    lines = render_progress_lines(_projection(*views))

    assert lines[0] == f"Computer Use  runs {MAX_DISPLAYED_RUNS}/{len(views)}"
    assert lines[1] == f"In progress  {MAX_DISPLAYED_RUNS}/{len(views)}"
    # Newest checkpoint first within the group; oldest excess dropped.
    assert lines[2].startswith(f"run_{len(views) - 1:03d}")
    body = "\n".join(lines)
    assert "run_000" not in body and "run_004" not in body
    assert f"run_{len(views) - 1:03d}" in body


def test_grouping_prioritizes_attention_over_newer_history() -> None:
    views = [
        _view(
            f"run_done_{i:03d}",
            phase="SUCCESS",
            display_state="Ready",
            is_terminal=True,
            updated_at_us=1000 + i,
        )
        for i in range(MAX_DISPLAYED_RUNS)
    ]
    views.append(
        _view(
            "run_needs_operator",
            phase="WAITING_APPROVAL",
            display_state="Needs input",
            updated_at_us=1,
        )
    )

    lines = render_progress_lines(_projection(*views))
    blob = "\n".join(lines)

    assert lines[1] == "Attention  1"
    assert lines[2].startswith("run_needs_operator")
    assert "History  19/20" in lines
    assert "run_done_000" not in blob


def test_grouping_uses_stable_run_id_order_for_equal_timestamps() -> None:
    lines = render_progress_lines(
        _projection(
            _view("run_b", updated_at_us=7),
            _view("run_a", updated_at_us=7),
        )
    )

    assert lines[1] == "In progress  2"
    assert lines[2].startswith("run_a")
    assert lines[5].startswith("run_b")


def test_unavailable_and_unsafe_records_are_surfaced_not_hidden() -> None:
    lines = "\n".join(
        render_progress_lines(
            _projection(_view("run_ok"), unavailable=("run_bad1", "run_bad2"), unnamed=3)
        )
    )
    assert "unavailable (2): run_bad1, run_bad2" in lines
    assert "hidden unsafe records: 3" in lines


def test_long_run_id_line_is_bounded() -> None:
    long_id = "r" + "a" * 130
    lines = render_progress_lines(_projection(_view(long_id)))
    assert all(len(line) <= 120 for line in lines)


def test_campaigns_render_before_runs_with_aggregate_counts_only() -> None:
    projection = _projection(_view("run_a"))
    projection = ProgressProjection(
        projection.views,
        projection.unavailable_run_ids,
        projection.unavailable_unnamed,
        campaigns=(
            _campaign(
                "campaign_paused",
                status="PAUSED",
                display_state="Paused",
                needs_attention=True,
            ),
            _campaign("campaign_active"),
        ),
    )

    lines = render_progress_lines(projection)
    blob = "\n".join(lines)

    assert lines[0] == "Computer Use  campaigns 2/2  runs 1/1"
    assert lines.index("Campaign attention  1") < lines.index("Active campaigns  1")
    assert lines.index("Active campaigns  1") < lines.index("In progress  1")
    assert "items 2/5 complete  retryable 1  uncertain 0" in blob
    assert FORBIDDEN not in blob


def test_campaign_render_cap_preserves_attention_first() -> None:
    campaigns = tuple(
        _campaign(
            f"campaign_history_{index}",
            status="COMPLETED",
            display_state="Ready",
            is_terminal=True,
            updated_at_us=100 + index,
        )
        for index in range(MAX_DISPLAYED_CAMPAIGNS)
    ) + (
        _campaign(
            "campaign_needs_operator",
            status="STALE",
            display_state="Stale; inspect before reclaim",
            needs_attention=True,
        ),
    )
    projection = ProgressProjection((), (), 0, campaigns=campaigns)

    lines = render_progress_lines(projection)
    blob = "\n".join(lines)

    assert lines[1] == "Campaign attention  1"
    assert "campaign_needs_operator" in blob
    assert "Campaign history  9/10" in lines
