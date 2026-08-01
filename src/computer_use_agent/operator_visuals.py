"""Shared, fixed operator-state vocabulary and visual roles.

Tokens are presentation data only. They carry no run identity, task content,
approval authority, execution callback, or provider-derived prose.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OperatorVisualError(ValueError):
    """Fixed failure for an invalid shared visual role."""


class OperatorVisualRole(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    OBSERVING = "observing"
    PLANNING = "planning"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    RECOVERING = "recovering"
    NEEDS_INPUT = "needs_input"
    PAUSED = "paused"
    READY = "ready"
    NEEDS_INSPECTION = "needs_inspection"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class OperatorVisualToken:
    """One immutable label/glyph/color tuple shared across HUD surfaces."""

    role: OperatorVisualRole
    label: str
    glyph: str
    color_rgb: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role, OperatorVisualRole)
            or not isinstance(self.label, str)
            or not self.label
            or not isinstance(self.glyph, str)
            or not self.glyph
            or isinstance(self.color_rgb, bool)
            or not isinstance(self.color_rgb, int)
            or not 0 <= self.color_rgb <= 0xFFFFFF
        ):
            raise OperatorVisualError("OPERATOR_VISUAL_TOKEN_INVALID")


_TOKENS = {
    OperatorVisualRole.NOT_STARTED: OperatorVisualToken(
        OperatorVisualRole.NOT_STARTED,
        "Not started",
        "READY",
        0x828282,
    ),
    OperatorVisualRole.IN_PROGRESS: OperatorVisualToken(
        OperatorVisualRole.IN_PROGRESS,
        "In progress",
        "ACTIVE",
        0x2F80ED,
    ),
    OperatorVisualRole.OBSERVING: OperatorVisualToken(
        OperatorVisualRole.OBSERVING,
        "Observing",
        "EYE",
        0x2F80ED,
    ),
    OperatorVisualRole.PLANNING: OperatorVisualToken(
        OperatorVisualRole.PLANNING,
        "Planning",
        "PLAN",
        0x8E5BE8,
    ),
    OperatorVisualRole.EXECUTING: OperatorVisualToken(
        OperatorVisualRole.EXECUTING,
        "Executing",
        "ACTION",
        0x27AE60,
    ),
    OperatorVisualRole.VERIFYING: OperatorVisualToken(
        OperatorVisualRole.VERIFYING,
        "Verifying",
        "VERIFY",
        0x00A7B5,
    ),
    OperatorVisualRole.RECOVERING: OperatorVisualToken(
        OperatorVisualRole.RECOVERING,
        "Recovering",
        "RECOVERY",
        0xE67E22,
    ),
    OperatorVisualRole.NEEDS_INPUT: OperatorVisualToken(
        OperatorVisualRole.NEEDS_INPUT,
        "Needs input",
        "APPROVAL",
        0xF2C94C,
    ),
    OperatorVisualRole.PAUSED: OperatorVisualToken(
        OperatorVisualRole.PAUSED,
        "Paused",
        "PAUSED",
        0xBDBDBD,
    ),
    OperatorVisualRole.READY: OperatorVisualToken(
        OperatorVisualRole.READY,
        "Ready",
        "DONE",
        0x27AE60,
    ),
    OperatorVisualRole.NEEDS_INSPECTION: OperatorVisualToken(
        OperatorVisualRole.NEEDS_INSPECTION,
        "Needs inspection",
        "INSPECT",
        0xEB5757,
    ),
    OperatorVisualRole.FAILED: OperatorVisualToken(
        OperatorVisualRole.FAILED,
        "Failed",
        "FAILED",
        0xEB5757,
    ),
    OperatorVisualRole.CANCELLED: OperatorVisualToken(
        OperatorVisualRole.CANCELLED,
        "Cancelled",
        "CANCELLED",
        0x828282,
    ),
}


def operator_visual(role: OperatorVisualRole) -> OperatorVisualToken:
    if not isinstance(role, OperatorVisualRole):
        raise OperatorVisualError("OPERATOR_VISUAL_ROLE_INVALID")
    return _TOKENS[role]


@dataclass(frozen=True)
class OperatorSurfaceTokens:
    """The fixed chrome every HUD surface draws on.

    Status colour already came from one contract; background, text, and
    hairline did not, which is how Presence, Progress, and the Decision Card
    drifted onto three different dark greys. These are RGB, matching
    :attr:`OperatorVisualToken.color_rgb`; a platform backend converts.
    """

    background_rgb: int
    surface_rgb: int
    text_rgb: int
    muted_text_rgb: int
    hairline_rgb: int

    def __post_init__(self) -> None:
        for value in (
            self.background_rgb,
            self.surface_rgb,
            self.text_rgb,
            self.muted_text_rgb,
            self.hairline_rgb,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 0xFFFFFF
            ):
                raise OperatorVisualError("OPERATOR_SURFACE_TOKEN_INVALID")


@dataclass(frozen=True)
class OperatorTypeTier:
    """One shared text tier: point size plus weight."""

    points: int
    weight: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.points, bool)
            or not isinstance(self.points, int)
            or not 6 <= self.points <= 48
            or self.weight not in {OPERATOR_WEIGHT_NORMAL, OPERATOR_WEIGHT_SEMIBOLD}
        ):
            raise OperatorVisualError("OPERATOR_TYPE_TIER_INVALID")


OPERATOR_WEIGHT_NORMAL = 400
OPERATOR_WEIGHT_SEMIBOLD = 600

#: The canonical HUD chrome. These are the values the workflow Progress HUD
#: already shipped, so adopting them moves the Decision Card without repainting
#: a surface that already reads correctly.
OPERATOR_SURFACE = OperatorSurfaceTokens(
    background_rgb=0x13171E,
    # An elevated pane must be legible as its own region, including the system
    # scrollbar drawn inside it. The first value sat too close to the
    # background and the scroll affordance disappeared into the card.
    surface_rgb=0x232A36,
    text_rgb=0xF5F5F5,
    muted_text_rgb=0xB8B8B8,
    hairline_rgb=0x39424F,
)

#: The shared type scale. An uppercase accent micro-label introduces a surface,
#: one large semibold line names the current thing, and muted body text carries
#: the counts and application that qualify it.
OPERATOR_TYPE_MICRO_LABEL = OperatorTypeTier(9, OPERATOR_WEIGHT_SEMIBOLD)
OPERATOR_TYPE_TITLE = OperatorTypeTier(16, OPERATOR_WEIGHT_SEMIBOLD)
OPERATOR_TYPE_META = OperatorTypeTier(10, OPERATOR_WEIGHT_NORMAL)
OPERATOR_TYPE_ACTION = OperatorTypeTier(11, OPERATOR_WEIGHT_SEMIBOLD)


__all__ = [
    "OPERATOR_SURFACE",
    "OPERATOR_TYPE_ACTION",
    "OPERATOR_TYPE_META",
    "OPERATOR_TYPE_MICRO_LABEL",
    "OPERATOR_TYPE_TITLE",
    "OPERATOR_WEIGHT_NORMAL",
    "OPERATOR_WEIGHT_SEMIBOLD",
    "OperatorSurfaceTokens",
    "OperatorTypeTier",
    "OperatorVisualError",
    "OperatorVisualRole",
    "OperatorVisualToken",
    "operator_visual",
]
