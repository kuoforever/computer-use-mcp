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
)

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
        self.lines[hwnd] = tuple(lines)
        self.calls.append(("set_lines", hwnd, tuple(lines)))

    def show_noactivate(self, hwnd: int) -> None:
        self.calls.append(("show_noactivate", hwnd))

    def reposition_noactivate(self, hwnd: int, *, x: int, y: int, topmost: bool) -> None:
        self.calls.append(("reposition_noactivate", hwnd, x, y, topmost))

    def foreground(self) -> int:
        return self._foreground

    def destroy(self, hwnd: int) -> None:
        self.alive.discard(hwnd)
        self.calls.append(("destroy", hwnd))

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
        display_state="Running",
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
                display_state="Complete",
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
                display_state="Complete",
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


def test_unknown_facts_are_labelled_not_faked() -> None:
    lines = "\n".join(render_progress_lines(_projection(_view("run_mid"))))
    assert "coverage unknown" in lines
    assert "liveness unknown" in lines
    # A nonterminal run is never labelled running.
    assert "running" not in lines.lower()


def test_reobserve_is_marked_and_never_a_retry_button() -> None:
    view = _view(
        "run_unsure",
        phase="UNKNOWN_OUTCOME",
        display_state="Uncertain; re-observe before retry",
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
        display_state="Complete",
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
            display_state="Complete",
            is_terminal=True,
            updated_at_us=1000 + i,
        )
        for i in range(MAX_DISPLAYED_RUNS)
    ]
    views.append(
        _view(
            "run_needs_operator",
            phase="WAITING_APPROVAL",
            display_state="Waiting approval",
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
                display_state="Paused; operator attention",
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
            display_state="Complete",
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
