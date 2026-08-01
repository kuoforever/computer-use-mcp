"""Hold each Presence halo phase long enough for an operator to inspect it.

`GDA-HUD-001` records the original complaint: no visible full-screen halo was
seen during a live run. Every existing probe flips through phases in
milliseconds and then asserts structure, which is exactly why nobody could
confirm the halo with their eyes -- including the approval-wait state, which is
the one the operator reported as missing.

This is a visual review surface, not a probe. It holds one phase at a time for
a fixed interval and prints what should be on screen, so the halo can be
compared against what is actually visible.

No Runner, MCP server, provider, application, approval, or desktop action is
opened. Every phase and authority value below is fixed synthetic state.

The halo is click-through and non-activating, so it cannot interrupt whatever
is in the foreground while it is held.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from operator_hud_review_guard import (
    ReviewAlreadyRunningError,
    exclusive_review,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from computer_use_agent.presence import (  # noqa: E402
    DesktopAuthority,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
)
from computer_use_agent.presence_window import (  # noqa: E402
    PassivePresenceWindow,
    presence_geometry,
)
from computer_use_agent.presence_window_win32 import (  # noqa: E402
    Win32PresenceWindowApi,
)

#: Phase and the desktop authority that truthfully accompanies it. The
#: approval-wait row is the point of this script: authority is released to the
#: operator, and the halo must stay visible while it is.
_REVIEW_SEQUENCE: tuple[tuple[PresencePhase, DesktopAuthority], ...] = (
    (PresencePhase.OBSERVING, DesktopAuthority.HELD),
    (PresencePhase.PLANNING, DesktopAuthority.HELD),
    (PresencePhase.EXECUTING, DesktopAuthority.HELD),
    (PresencePhase.WAITING_APPROVAL, DesktopAuthority.WAITING),
    (PresencePhase.VERIFYING, DesktopAuthority.HELD),
    (PresencePhase.PAUSED, DesktopAuthority.WAITING),
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Hold each Presence halo phase for inspection. No Runner, MCP, "
            "provider, application, or desktop action is opened."
        )
    )
    parser.add_argument(
        "--hold-seconds",
        type=float,
        default=6.0,
        help="Seconds to hold each phase (default: 6.0).",
    )
    parser.add_argument(
        "--reduced-motion",
        action="store_true",
        help="Review the reduced-motion and high-contrast projection instead.",
    )
    parser.add_argument(
        "--phase",
        choices=[phase.value for phase, _ in _REVIEW_SEQUENCE],
        help="Hold only this phase instead of the whole sequence.",
    )
    args = parser.parse_args()

    if not 0.5 <= args.hold_seconds <= 120.0:
        print("hold-seconds must be between 0.5 and 120.0")
        return 2

    sequence = _REVIEW_SEQUENCE
    if args.phase is not None:
        sequence = tuple(
            row for row in _REVIEW_SEQUENCE if row[0].value == args.phase
        )

    preferences = PresencePreferences(
        reduced_motion=args.reduced_motion,
        high_contrast=args.reduced_motion,
    )

    try:
        with exclusive_review("presence-phases"):
            api = Win32PresenceWindowApi()
            window = PassivePresenceWindow(api)
            foreground_before = api.foreground()
            geometry = presence_geometry(api.display_bounds())
            print(
                f"halo {geometry.width}x{geometry.height} at "
                f"({geometry.x},{geometry.y}), border {geometry.border_px}px, "
                f"label inset {geometry.label_inset_px}px"
            )
            print(f"foreground before: {foreground_before:#x}")
            print("the halo is click-through; the foreground stays usable\n")
            try:
                for phase, authority in sequence:
                    window.sync(
                        PresenceSnapshot(
                            phase=phase,
                            authority=authority,
                            estop_engaged=False,
                            preferences=preferences,
                        )
                    )
                    api.pump()
                    print(
                        f"holding {phase.value:<17} authority={authority.value:<8} "
                        f"for {args.hold_seconds:g}s"
                    )
                    deadline = time.monotonic() + args.hold_seconds
                    while time.monotonic() < deadline:
                        api.pump()
                        time.sleep(0.05)
            finally:
                window.close()
                api.pump()
            foreground_after = api.foreground()
            print(f"\nforeground after: {foreground_after:#x}")
            if foreground_after != foreground_before:
                print(
                    "NOTE: the foreground changed during the review. The halo "
                    "cannot move it, so this was local input, not the halo."
                )
            print("halo released")
    except ReviewAlreadyRunningError:
        print("another presence review is already running")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
