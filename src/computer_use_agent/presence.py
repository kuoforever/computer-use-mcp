"""Pure, redaction-safe state for the passive desktop presence indicator.

The projection accepts only host-owned enums and booleans. It has no run ID,
task text, model prose, target title, action arguments, or execution callback,
so private or authoritative content cannot reach the presence surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .operator_visuals import OperatorVisualRole, operator_visual
from .types import JSONValue


class PresenceStateError(ValueError):
    """Raised when host presence state is internally inconsistent."""


class PresencePhase(str, Enum):
    OBSERVING = "OBSERVING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    INSPECT = "INSPECT"


class DesktopAuthority(str, Enum):
    HELD = "HELD"
    WAITING = "WAITING"
    RELEASED = "RELEASED"


class PresenceMotion(str, Enum):
    STEADY = "STEADY"
    SLOW = "SLOW"
    DIRECTIONAL = "DIRECTIONAL"
    SHORT_PULSE = "SHORT_PULSE"
    PULSE = "PULSE"
    FIXED_WARNING = "FIXED_WARNING"


@dataclass(frozen=True)
class PresencePreferences:
    enabled: bool = True
    reduced_motion: bool = False
    high_contrast: bool = False

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, bool)
            for value in (self.enabled, self.reduced_motion, self.high_contrast)
        ):
            raise PresenceStateError("PRESENCE_PREFERENCES_INVALID")


@dataclass(frozen=True)
class PresenceSnapshot:
    """One validated Host-owned lifecycle snapshot, never an authority token."""

    phase: PresencePhase
    authority: DesktopAuthority
    estop_engaged: bool = False
    terminal_closed: bool = False
    preferences: PresencePreferences = PresencePreferences()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.phase, PresencePhase)
            or not isinstance(self.authority, DesktopAuthority)
            or not isinstance(self.estop_engaged, bool)
            or not isinstance(self.terminal_closed, bool)
            or not isinstance(self.preferences, PresencePreferences)
        ):
            raise PresenceStateError("PRESENCE_SNAPSHOT_INVALID")
        if self.phase is PresencePhase.PAUSED and self.authority is DesktopAuthority.HELD:
            raise PresenceStateError("PRESENCE_AUTHORITY_INCONSISTENT")


@dataclass(frozen=True)
class PresenceView:
    """The complete fixed allowlist a native indicator may render."""

    phase: str
    visual_role: str
    label: str
    glyph: str
    color_rgb: int
    motion: str
    motion_enabled: bool
    animation_interval_ms: int | None
    high_contrast: bool

    def as_display_dict(self) -> dict[str, JSONValue]:
        return {
            "phase": self.phase,
            "visual_role": self.visual_role,
            "label": self.label,
            "glyph": self.glyph,
            "color_rgb": self.color_rgb,
            "motion": self.motion,
            "motion_enabled": self.motion_enabled,
            "animation_interval_ms": self.animation_interval_ms,
            "high_contrast": self.high_contrast,
        }


_PRESENTATION: dict[
    PresencePhase,
    tuple[OperatorVisualRole, PresenceMotion],
] = {
    PresencePhase.OBSERVING: (
        OperatorVisualRole.OBSERVING,
        PresenceMotion.STEADY,
    ),
    PresencePhase.PLANNING: (
        OperatorVisualRole.PLANNING,
        PresenceMotion.SLOW,
    ),
    PresencePhase.EXECUTING: (
        OperatorVisualRole.EXECUTING,
        PresenceMotion.DIRECTIONAL,
    ),
    PresencePhase.VERIFYING: (
        OperatorVisualRole.VERIFYING,
        PresenceMotion.SHORT_PULSE,
    ),
    PresencePhase.RECOVERING: (
        OperatorVisualRole.RECOVERING,
        PresenceMotion.SLOW,
    ),
    PresencePhase.WAITING_APPROVAL: (
        OperatorVisualRole.NEEDS_INPUT,
        PresenceMotion.PULSE,
    ),
    PresencePhase.PAUSED: (
        OperatorVisualRole.PAUSED,
        PresenceMotion.STEADY,
    ),
    PresencePhase.INSPECT: (
        OperatorVisualRole.NEEDS_INSPECTION,
        PresenceMotion.FIXED_WARNING,
    ),
}

_MOTION_INTERVAL_MS: dict[PresenceMotion, int | None] = {
    PresenceMotion.STEADY: None,
    PresenceMotion.SLOW: 1_000,
    PresenceMotion.DIRECTIONAL: 250,
    PresenceMotion.SHORT_PULSE: 300,
    PresenceMotion.PULSE: 500,
    PresenceMotion.FIXED_WARNING: None,
}


def project_presence(snapshot: PresenceSnapshot) -> PresenceView | None:
    """Return a fixed presentation, or ``None`` when the halo must be absent."""

    if not isinstance(snapshot, PresenceSnapshot):
        raise PresenceStateError("PRESENCE_SNAPSHOT_INVALID")
    if (
        not snapshot.preferences.enabled
        or snapshot.estop_engaged
        or snapshot.terminal_closed
        or snapshot.authority is DesktopAuthority.RELEASED
    ):
        return None

    visual_role, motion = _PRESENTATION[snapshot.phase]
    token = operator_visual(visual_role)
    color = token.color_rgb
    if snapshot.preferences.high_contrast:
        color = 0xFFFFFF
    motion_enabled = not snapshot.preferences.reduced_motion
    return PresenceView(
        phase=snapshot.phase.value,
        visual_role=token.role.value,
        label=token.label,
        glyph=token.glyph,
        color_rgb=color,
        motion=motion.value,
        motion_enabled=motion_enabled,
        animation_interval_ms=(
            _MOTION_INTERVAL_MS[motion] if motion_enabled else None
        ),
        high_contrast=snapshot.preferences.high_contrast,
    )


__all__ = [
    "DesktopAuthority",
    "PresenceMotion",
    "PresencePhase",
    "PresencePreferences",
    "PresenceSnapshot",
    "PresenceStateError",
    "PresenceView",
    "project_presence",
]
