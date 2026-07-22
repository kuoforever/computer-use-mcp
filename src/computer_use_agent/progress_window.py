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

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .progress_view import ProgressProjection, RunProgressView, group_progress_views

# The passive window is a monitoring surface, not a console: it shows a bounded
# newest slice rather than an unbounded scroll. The reducer already caps the
# scan; this caps what is drawn so a large ``state_dir`` can never grow the
# window without bound.
MAX_DISPLAYED_RUNS = 20
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


def _run_lines(view: RunProgressView) -> tuple[str, ...]:
    """Render one run as a bounded, whitelisted block of display lines.

    Only fields already present on the redaction-safe view model are read, so
    forbidden checkpoint content cannot be introduced here. Unknown facts are
    labelled honestly rather than shown as a misleading zero or "running".
    """

    head = f"{view.run_id}  {view.display_state}"
    if view.needs_reobserve:
        # Acceptance check 7: distinct, and never a retry affordance — this is a
        # passive label, not a button.
        head += "  [re-observe]"

    calls = (
        f"  calls  model {view.model_calls.used}/{view.model_calls.limit}"
        f"  tool {view.tool_calls.used}/{view.tool_calls.limit}"
    )

    token_note = "known" if view.token_coverage_known else "coverage unknown"
    usage = (
        f"  tokens in {view.input_tokens} out {view.output_tokens} ({token_note})"
        f"  images {view.image_results}  fails {view.tool_failures}"
    )

    if view.is_terminal:
        if view.duration_ms is not None:
            usage += f"  ran {view.duration_ms}ms"
    else:
        # Checkpoint v1 cannot prove a nonterminal run is still alive.
        usage += "  liveness unknown"

    return (_clip(head), _clip(calls), _clip(usage))


def render_progress_lines(projection: ProgressProjection) -> tuple[str, ...]:
    """Project a bounded scan into the exact lines the passive window draws.

    The result is a flat, bounded tuple of plain strings. It carries a header
    with honest run counts, fixed operator-relevance groups, and one block per
    shown run (newest-first within each group, globally capped at
    :data:`MAX_DISPLAYED_RUNS`). Attention is allocated first so terminal
    history cannot hide a waiting or uncertain run.
    """

    total = len(projection.views)
    shown = min(total, MAX_DISPLAYED_RUNS)
    lines: list[str] = [_clip(f"Computer Use  runs {shown}/{total}")]

    remaining = MAX_DISPLAYED_RUNS
    for group in group_progress_views(projection.views):
        if remaining <= 0:
            break
        group_views = group.views[:remaining]
        group_total = len(group.views)
        group_shown = len(group_views)
        count = str(group_total) if group_shown == group_total else f"{group_shown}/{group_total}"
        lines.append(_clip(f"{group.label}  {count}"))
        for view in group_views:
            lines.extend(_run_lines(view))
        remaining -= group_shown

    unavailable = projection.unavailable_run_ids
    if unavailable:
        listed = ", ".join(unavailable[:_MAX_LISTED_UNAVAILABLE])
        suffix = "" if len(unavailable) <= _MAX_LISTED_UNAVAILABLE else ", …"
        lines.append(_clip(f"unavailable ({len(unavailable)}): {listed}{suffix}"))
    if projection.unavailable_unnamed:
        lines.append(_clip(f"hidden unsafe records: {projection.unavailable_unnamed}"))

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
    _hwnd: int | None = field(default=None, init=False)
    _x: int = field(default=24, init=False)
    _y: int = field(default=24, init=False)
    _topmost: bool = field(default=True, init=False)

    @property
    def hwnd(self) -> int | None:
        return self._hwnd

    def open(self, projection: ProgressProjection) -> int:
        """Create and show the window non-activated; refresh it if already open."""

        if self._hwnd is not None:
            self.update(projection)
            return self._hwnd
        hwnd = self.api.create(ex_style=PASSIVE_EX_STYLE, style=PASSIVE_STYLE, title=self.title)
        self._hwnd = hwnd
        self.api.set_lines(hwnd, render_progress_lines(projection))
        self.api.show_noactivate(hwnd)
        return hwnd

    def update(self, projection: ProgressProjection) -> None:
        """Refresh the drawn lines without re-showing or activating the window."""

        hwnd = self._require_open()
        self.api.set_lines(hwnd, render_progress_lines(projection))

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

    def _reposition(self) -> None:
        hwnd = self._require_open()
        self.api.reposition_noactivate(hwnd, x=self._x, y=self._y, topmost=self._topmost)

    def _require_open(self) -> int:
        if self._hwnd is None:
            raise ProgressWindowError("PROGRESS_WINDOW_NOT_OPEN")
        return self._hwnd


__all__ = [
    "MAX_DISPLAYED_RUNS",
    "PASSIVE_EX_STYLE",
    "PASSIVE_STYLE",
    "PassiveProgressWindow",
    "ProgressWindowApi",
    "ProgressWindowError",
    "render_progress_lines",
]
