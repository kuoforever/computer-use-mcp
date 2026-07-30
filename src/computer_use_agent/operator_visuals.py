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


__all__ = [
    "OperatorVisualError",
    "OperatorVisualRole",
    "OperatorVisualToken",
    "operator_visual",
]
