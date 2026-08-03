"""Host-owned presentation pacing and content-free action feedback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class InteractionPacing:
    """Bounded presentation delays that never change action authority."""

    name: str
    pointer_move_ms: int
    pre_action_seconds: float
    post_action_seconds: float
    type_wait_seconds: float


INTERACTION_PACING = {
    "fast": InteractionPacing("fast", 90, 0.02, 0.04, 0.012),
    "normal": InteractionPacing("normal", 180, 0.04, 0.08, 0.025),
    "deliberate": InteractionPacing("deliberate", 320, 0.08, 0.14, 0.035),
}


def resolve_interaction_pacing(value: str | None) -> InteractionPacing | None:
    """Resolve an optional operator-owned speed name without silent fallback."""

    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    try:
        return INTERACTION_PACING[normalized]
    except KeyError as exc:
        raise ValueError(
            "interaction_speed must be fast, normal, deliberate, or unset"
        ) from exc


@runtime_checkable
class ActionFeedback(Protocol):
    """Passive feedback only; text and key values are deliberately absent."""

    def show_pointer(self, x: int, y: int, *, action: str) -> None: ...

    def show_keyboard(
        self,
        *,
        action: str,
        total_units: int = 0,
        estimated_seconds: float = 0.0,
    ) -> None: ...

    def clear(self) -> None: ...


__all__ = [
    "ActionFeedback",
    "INTERACTION_PACING",
    "InteractionPacing",
    "resolve_interaction_pacing",
]
