"""Atomic live checkpoint polling for the passive progress window (step 3).

Delivery step 3 of the [operator progress viewer](../../docs/PROGRESS_VIEWER.md):
keep the step-2 window showing current facts by re-reading the state directory
on an interval. Steps 1 and 2 decided what may be displayed and how it is drawn
without taking focus; this step decides *when* it is redrawn, and its central
promise is that a live view never shows something that was never true.

Two properties carry that promise:

* **Atomic reads.** Checkpoints are written with ``tempfile.mkstemp`` +
  ``os.replace``, so a poll observes either the previous or the next complete
  record — never a mixture. The poller adds no buffering or partial parsing that
  could reintroduce a torn read.
* **Stale data is discarded, not shown.** If a scan fails closed (a symlinked
  runs directory, an oversized scan), the poller does **not** keep the last good
  lines on screen where they would read as current. It replaces them with a
  fixed unavailable banner, because a stale view presented as live is exactly
  the dishonesty the reducer's ``*_known`` flags exist to prevent.

A single corrupt run stays isolated: the reducer already reports it as
unavailable without contaminating valid records, and the window renders that
count. Only directory-level tampering invalidates the whole view.

The poller drives the window solely through :class:`PassiveProgressWindow`, so
it inherits the non-activating contract: polling can never move foreground.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .progress_view import ProgressProjection, ProgressViewError, build_progress_projection
from .progress_window import PassiveProgressWindow, render_progress_lines

_EMPTY_PROJECTION = ProgressProjection(views=(), unavailable_run_ids=(), unavailable_unnamed=0)

#: Default seconds between scans. Slow enough that a large ``state_dir`` costs
#: little, fast enough that an operator sees a phase change promptly.
DEFAULT_INTERVAL_SECONDS = 2.0

#: Shown when the whole scan fails closed. It states the failure and nothing
#: else: no path, no error text, no checkpoint content.
SCAN_UNAVAILABLE_LINES = (
    "Computer Use  progress unavailable",
    "state scan failed closed; last view discarded",
)


@dataclass(frozen=True)
class PollOutcome:
    """What one poll observed and whether it changed the screen."""

    redrew: bool
    scan_failed: bool
    run_count: int
    unavailable_count: int


@dataclass
class ProgressPoller:
    """Refresh a passive progress window from ``state_dir`` on an interval.

    ``sleep`` is injected so the loop can be driven deterministically in tests
    without real time passing.
    """

    state_dir: Path
    window: PassiveProgressWindow
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS
    sleep: Callable[[float], None] = time.sleep
    _last_lines: tuple[str, ...] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.state_dir, Path) or not self.state_dir.is_absolute():
            raise ValueError("state_dir must be an absolute Path")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

    def poll_once(self) -> PollOutcome:
        """Scan once and redraw only when the rendered view actually changed.

        Redrawing an unchanged view would repaint the window for no reason, so
        the poller compares rendered lines and skips the update. This keeps a
        quiet desktop quiet and makes "nothing changed" observable in tests.
        """

        try:
            projection = build_progress_projection(self.state_dir)
        except (ProgressViewError, OSError):
            # Directory-level failure: the whole view is untrustworthy.
            return self._draw(SCAN_UNAVAILABLE_LINES, scan_failed=True, runs=0, unavailable=0)

        return self._draw(
            render_progress_lines(projection),
            scan_failed=False,
            runs=len(projection.views),
            unavailable=len(projection.unavailable_run_ids) + projection.unavailable_unnamed,
        )

    def run(
        self,
        *,
        max_polls: int | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> tuple[PollOutcome, ...]:
        """Poll until ``max_polls`` is reached or ``should_stop`` returns True.

        The window is opened by the first poll and left open; the caller owns
        closing it. Sleeping happens only *between* polls, so a single-poll run
        costs no delay.
        """

        outcomes: list[PollOutcome] = []
        while max_polls is None or len(outcomes) < max_polls:
            if should_stop is not None and should_stop():
                break
            outcomes.append(self.poll_once())
            more = max_polls is None or len(outcomes) < max_polls
            if more and not (should_stop is not None and should_stop()):
                self.sleep(self.interval_seconds)
        return tuple(outcomes)

    def _draw(
        self, lines: tuple[str, ...], *, scan_failed: bool, runs: int, unavailable: int
    ) -> PollOutcome:
        changed = lines != self._last_lines
        if changed:
            self._render(lines)
            self._last_lines = lines
        return PollOutcome(
            redrew=changed,
            scan_failed=scan_failed,
            run_count=runs,
            unavailable_count=unavailable,
        )

    def _render(self, lines: tuple[str, ...]) -> None:
        """Push lines to the window, opening it non-activated on first use."""

        if self.window.hwnd is None:
            # Open with an empty projection, then set the real lines: the window
            # must never appear before it has content to show.
            self.window.open(_EMPTY_PROJECTION)
        self.window.api.set_lines(self.window.hwnd, lines)


__all__ = [
    "DEFAULT_INTERVAL_SECONDS",
    "SCAN_UNAVAILABLE_LINES",
    "PollOutcome",
    "ProgressPoller",
]
