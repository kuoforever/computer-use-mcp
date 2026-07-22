from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from computer_use_agent.presence import (
    DesktopAuthority,
    PresenceMotion,
    PresencePhase,
    PresencePreferences,
    PresenceSnapshot,
    PresenceStateError,
    project_presence,
)


@pytest.mark.parametrize("phase", tuple(PresencePhase))
def test_every_host_phase_has_a_fixed_nonempty_presentation(phase: PresencePhase) -> None:
    authority = (
        DesktopAuthority.WAITING
        if phase is PresencePhase.PAUSED
        else DesktopAuthority.HELD
    )

    view = project_presence(PresenceSnapshot(phase, authority))

    assert view is not None
    assert view.phase == phase.value
    assert view.label and view.glyph
    assert view.motion in {motion.value for motion in PresenceMotion}
    if view.motion in {PresenceMotion.STEADY.value, PresenceMotion.FIXED_WARNING.value}:
        assert view.animation_interval_ms is None
    assert 0 <= view.color_rgb <= 0xFFFFFF


@pytest.mark.parametrize(
    "snapshot",
    [
        PresenceSnapshot(PresencePhase.OBSERVING, DesktopAuthority.RELEASED),
        PresenceSnapshot(
            PresencePhase.EXECUTING,
            DesktopAuthority.HELD,
            estop_engaged=True,
        ),
        PresenceSnapshot(
            PresencePhase.VERIFYING,
            DesktopAuthority.HELD,
            terminal_closed=True,
        ),
        PresenceSnapshot(
            PresencePhase.PLANNING,
            DesktopAuthority.HELD,
            preferences=PresencePreferences(enabled=False),
        ),
    ],
)
def test_release_estop_terminal_and_user_disable_hide_indicator(
    snapshot: PresenceSnapshot,
) -> None:
    assert project_presence(snapshot) is None


def test_reduced_motion_and_high_contrast_are_explicit_not_color_only() -> None:
    view = project_presence(
        PresenceSnapshot(
            PresencePhase.WAITING_APPROVAL,
            DesktopAuthority.WAITING,
            preferences=PresencePreferences(reduced_motion=True, high_contrast=True),
        )
    )

    assert view is not None
    assert view.label == "Waiting approval"
    assert view.glyph == "APPROVAL"
    assert view.motion == PresenceMotion.PULSE.value
    assert view.motion_enabled is False
    assert view.animation_interval_ms is None
    assert view.high_contrast is True
    assert view.color_rgb == 0xFFFFFF


def test_display_model_has_no_identity_content_or_authority_fields() -> None:
    view = project_presence(
        PresenceSnapshot(PresencePhase.EXECUTING, DesktopAuthority.HELD)
    )
    assert view is not None

    payload = view.as_display_dict()

    assert set(payload) == {
        "phase",
        "label",
        "glyph",
        "color_rgb",
        "motion",
        "motion_enabled",
        "animation_interval_ms",
        "high_contrast",
    }
    rendered = json.dumps(payload)
    for forbidden in (
        "task",
        "run_id",
        "campaign_id",
        "window_title",
        "target",
        "argument",
        "approve",
        "dispatch",
    ):
        assert forbidden not in rendered.lower()


def test_presence_snapshot_rejects_inconsistent_or_untyped_state() -> None:
    with pytest.raises(PresenceStateError, match="PRESENCE_AUTHORITY_INCONSISTENT"):
        PresenceSnapshot(PresencePhase.PAUSED, DesktopAuthority.HELD)
    with pytest.raises(PresenceStateError, match="PRESENCE_SNAPSHOT_INVALID"):
        PresenceSnapshot("EXECUTING", DesktopAuthority.HELD)  # type: ignore[arg-type]
    with pytest.raises(PresenceStateError, match="PRESENCE_PREFERENCES_INVALID"):
        PresencePreferences(reduced_motion=1)  # type: ignore[arg-type]


def test_frozen_snapshot_cannot_be_repurposed_after_projection() -> None:
    snapshot = PresenceSnapshot(PresencePhase.OBSERVING, DesktopAuthority.HELD)
    with pytest.raises(FrozenInstanceError):
        snapshot.phase = PresencePhase.EXECUTING  # type: ignore[misc]
