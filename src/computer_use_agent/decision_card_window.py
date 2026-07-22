"""Injected controller for one focus-taking local Decision Card window."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .decision_cards import DecisionCard, DecisionSelection


class DecisionCardWindowError(RuntimeError):
    """A fixed local-card failure without card or desktop content."""


@dataclass(frozen=True)
class DecisionCardButton:
    option_id: str
    label: str


@runtime_checkable
class DecisionCardWindowApi(Protocol):
    """Blocking native choice boundary; it owns close and timeout handling."""

    def choose(
        self,
        *,
        title: str,
        instruction: str,
        content: str,
        expanded_information: str,
        buttons: tuple[DecisionCardButton, ...],
        timeout_seconds: int,
    ) -> str | None: ...


@dataclass
class DecisionCardWindow:
    api: DecisionCardWindowApi

    async def choose(
        self, card: DecisionCard, *, timeout_seconds: int
    ) -> DecisionSelection | None:
        if not isinstance(card, DecisionCard):
            raise DecisionCardWindowError("DECISION_CARD_WINDOW_INPUT_INVALID")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or not 5 <= timeout_seconds <= 3_600
        ):
            raise DecisionCardWindowError("DECISION_CARD_WINDOW_TIMEOUT_INVALID")
        buttons = tuple(
            DecisionCardButton(option.option_id, option.title)
            for option in card.options
        )
        content = self._content(card)
        try:
            async with asyncio.timeout(timeout_seconds + 2):
                option_id = await asyncio.to_thread(
                    self.api.choose,
                    title="Decision required",
                    instruction="Choose one bounded option",
                    content=content,
                    expanded_information=self._evidence_content(card),
                    buttons=buttons,
                    timeout_seconds=timeout_seconds,
                )
        except TimeoutError:
            return None
        if option_id is None or option_id not in {
            option.option_id for option in card.options
        }:
            return None
        return DecisionSelection(card.decision_id, card.card_digest, option_id)

    @staticmethod
    def _content(card: DecisionCard) -> str:
        def estimate(value) -> str:  # noqa: ANN001
            if value.minimum is None:
                return value.kind.value
            return f"{value.kind.value} {value.minimum}-{value.maximum}"

        lines = [
            f"Class: {card.decision_class.value}",
            f"Application: {card.application.value}",
            f"Intended effect: {card.intended_effect.value}",
            f"Recipient scope: {card.recipient_scope.value}",
            "Recommendation is advisory and grants no authority.",
            "",
        ]
        for index, option in enumerate(card.options, start=1):
            recommendation = (
                " [Recommended]"
                if option.option_id == card.recommended_option_id
                else ""
            )
            lines.extend(
                [
                    f"{index}. {option.title}{recommendation}",
                    f"Effect: {option.effect}",
                    f"Benefit: {'; '.join(option.benefits)}",
                    f"Cost: {'; '.join(option.costs)}",
                    f"Risk: {'; '.join(option.risks)}",
                    f"Reversible: {'yes' if option.reversible else 'no'}",
                    f"Expected time seconds: {estimate(option.expected_time_seconds)}",
                    f"Expected tokens: {estimate(option.expected_tokens)}",
                    "Confidence: "
                    + option.confidence.kind.value
                    + (
                        ""
                        if option.confidence.label is None
                        else f" {option.confidence.label.value}"
                    ),
                    f"Authority: {option.required_authority.value}",
                    f"Fallback: {option.fallback.value}",
                    "",
                ]
            )
        lines.append("Close or timeout denies this request.")
        return "\n".join(lines)

    @staticmethod
    def _evidence_content(card: DecisionCard) -> str:
        binding = card.binding
        lines = [
            "Evidence references (SHA-256 digests only):",
            *(
                f"- {reference.kind.value}: {reference.digest}"
                for reference in card.evidence
            ),
            "",
            "Unknown facts:",
            *(
                f"- {fact.value}" for fact in card.unknown_facts
            ),
            "",
            "Host binding digests:",
            f"- state: {binding.state_digest}",
            f"- policy: {binding.policy_digest}",
            f"- task: {binding.task_digest}",
            f"- registry: {binding.registry_digest}",
            f"- object: {binding.object_digest}",
            f"- evidence: {binding.evidence_digest}",
            f"- card: {card.card_digest}",
            f"- expires: {card.expires_at.isoformat()}",
            "",
            "These digests are correlation evidence, not execution authority.",
        ]
        return "\n".join(lines)


__all__ = [
    "DecisionCardButton",
    "DecisionCardWindow",
    "DecisionCardWindowApi",
    "DecisionCardWindowError",
]
