"""Injected controller for one focus-taking local Decision Card window."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC
from typing import Callable, Protocol, runtime_checkable

from .decision_cards import DecisionCard, DecisionSelection
from .operator_localization import (
    OperatorLocale,
    decision_button_label,
    localized_visual,
    localize_fixed_text,
    operator_text,
)
from .operator_visuals import (
    OperatorVisualRole,
    OperatorVisualToken,
    operator_visual,
)
from .workflow_checklist import WorkflowChecklist


class DecisionCardWindowError(RuntimeError):
    """A fixed local-card failure without card or desktop content."""


def decision_attention_visual() -> OperatorVisualToken:
    """Return the shared attention token used by every approval card."""

    return operator_visual(OperatorVisualRole.NEEDS_INPUT)


@dataclass(frozen=True)
class DecisionCardButton:
    option_id: str
    label: str


@dataclass(frozen=True)
class WorkflowBreadcrumb:
    """One trusted workflow location; it carries no checklist or authority."""

    current: int
    total: int
    label: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.current, bool)
            or not isinstance(self.current, int)
            or isinstance(self.total, bool)
            or not isinstance(self.total, int)
            or not 1 <= self.current <= self.total <= 999
        ):
            raise DecisionCardWindowError("DECISION_CARD_WORKFLOW_INVALID")
        if (
            not isinstance(self.label, str)
            or not self.label.strip()
            or self.label != self.label.strip()
            or len(self.label) > 120
            or any(ord(character) < 32 for character in self.label)
        ):
            raise DecisionCardWindowError("DECISION_CARD_WORKFLOW_TEXT_INVALID")

    @classmethod
    def from_checklist(cls, checklist: WorkflowChecklist) -> WorkflowBreadcrumb:
        """Derive a breadcrumb only from one validated current workflow row."""

        if (
            not isinstance(checklist, WorkflowChecklist)
            or checklist.current_step_id is None
            or checklist.current_step_number is None
        ):
            raise DecisionCardWindowError("DECISION_CARD_WORKFLOW_INVALID")
        current = next(
            step
            for step in checklist.steps
            if step.step_id == checklist.current_step_id
        )
        return cls(
            current=checklist.current_step_number,
            total=len(checklist.steps),
            label=current.label,
        )


@dataclass(frozen=True)
class OperatorStepContext:
    """Exact approval action plus an optional trusted workflow breadcrumb."""

    current: int
    total: int
    label: str
    application: str
    workflow: WorkflowBreadcrumb | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.current, bool)
            or not isinstance(self.current, int)
            or isinstance(self.total, bool)
            or not isinstance(self.total, int)
            or not 1 <= self.current <= self.total <= 999
        ):
            raise DecisionCardWindowError("DECISION_CARD_STEP_INVALID")
        for value in (self.label, self.application):
            if (
                not isinstance(value, str)
                or not value.strip()
                or len(value) > 120
                or any(ord(character) < 32 for character in value)
            ):
                raise DecisionCardWindowError("DECISION_CARD_STEP_TEXT_INVALID")
        if self.workflow is not None and not isinstance(
            self.workflow,
            WorkflowBreadcrumb,
        ):
            raise DecisionCardWindowError("DECISION_CARD_WORKFLOW_INVALID")


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
    step_context: Callable[[], OperatorStepContext | None] | None = None
    locale: OperatorLocale = OperatorLocale.EN_US

    def __post_init__(self) -> None:
        if not isinstance(self.locale, OperatorLocale):
            raise DecisionCardWindowError("DECISION_CARD_LOCALE_INVALID")

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
            DecisionCardButton(
                option.option_id,
                decision_button_label(self.locale, option.option_id, option.title),
            )
            for option in card.options
        )
        content = self._content(card)
        context = self.step_context() if self.step_context is not None else None
        if context is not None and not isinstance(context, OperatorStepContext):
            raise DecisionCardWindowError("DECISION_CARD_STEP_INVALID")
        attention = localized_visual(self.locale, decision_attention_visual())
        title = operator_text(self.locale, "decision_required")
        # Exactly four lines, always, in the shared HUD tier order: accent
        # micro-label, the one thing being decided, then the counts and
        # application that qualify it. A backend zips these against a fixed
        # type scale, so the count must not vary with the context.
        instruction_lines = [
            f"{attention.label.upper()}  ·  {operator_text(self.locale, 'approval_locked')}",
            operator_text(self.locale, "choose_bounded_option"),
            "",
            "",
        ]
        if context is not None:
            title = (
                f"{attention.label} · "
                f"{operator_text(self.locale, 'approval_locked_title')}"
            )
            instruction_lines[1] = localize_fixed_text(self.locale, context.label)
            instruction_lines[2] = (
                f"{operator_text(self.locale, 'approval')} {context.current}/{context.total}"
                f"  ·  {context.application}"
            )
            if context.workflow is not None:
                instruction_lines[3] = (
                    f"{operator_text(self.locale, 'workflow')} "
                    f"{context.workflow.current}/{context.workflow.total}"
                    f"  ·  {localize_fixed_text(self.locale, context.workflow.label)}"
                )
        instruction = "\n".join(instruction_lines)
        try:
            async with asyncio.timeout(timeout_seconds + 2):
                option_id = await asyncio.to_thread(
                    self.api.choose,
                    title=title,
                    instruction=instruction,
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

    def _content(self, card: DecisionCard) -> str:
        def estimate(value, unit: str) -> str:  # noqa: ANN001
            if value.minimum is None:
                return operator_text(self.locale, "not_estimated")
            provenance = localize_fixed_text(
                self.locale, value.kind.value.replace("_", " ").capitalize()
            )
            localized_unit = localize_fixed_text(self.locale, unit)
            if value.minimum == value.maximum == 0:
                none = localize_fixed_text(self.locale, "None")
                return f"{none} ({provenance})"
            if value.minimum == value.maximum:
                return f"{value.minimum} {localized_unit} ({provenance})"
            return (
                f"{value.minimum}–{value.maximum} {localized_unit}"
                f" ({provenance})"
            )

        def readable(value: str) -> str:
            return localize_fixed_text(
                self.locale, value.replace("_", " ").capitalize()
            )

        def fingerprint(value: str) -> str:
            return f"{value[:10]}…{value[-6:]}"

        lines = [
            operator_text(self.locale, "decision_scope"),
            localize_fixed_text(
                self.locale, "This card controls one bounded desktop action only."
            ),
            localize_fixed_text(
                self.locale,
                "A recommendation is advice, not permission for later actions.",
            ),
            "",
            operator_text(self.locale, "your_choices"),
        ]
        for index, option in enumerate(card.options, start=1):
            recommendation = (
                f" — {operator_text(self.locale, 'recommended')}"
                if option.option_id == card.recommended_option_id
                else ""
            )
            confidence = readable(option.confidence.kind.value)
            if option.confidence.label is not None:
                confidence = (
                    f"{readable(option.confidence.label.value)}"
                    f" ({readable(option.confidence.kind.value).lower()})"
                )
            lines.extend(
                [
                    f"{index}. {localize_fixed_text(self.locale, option.title)}{recommendation}",
                    f"   {operator_text(self.locale, 'outcome')}: "
                    f"{localize_fixed_text(self.locale, option.effect)}.",
                    f"   {operator_text(self.locale, 'benefit')}: "
                    f"{'; '.join(localize_fixed_text(self.locale, value) for value in option.benefits)}.",
                    f"   {operator_text(self.locale, 'tradeoff')}: "
                    f"{'; '.join(localize_fixed_text(self.locale, value) for value in option.costs)}.",
                    f"   {operator_text(self.locale, 'risk')}: "
                    f"{'; '.join(localize_fixed_text(self.locale, value) for value in option.risks)}.",
                    f"   {operator_text(self.locale, 'can_be_undone')}: "
                    f"{operator_text(self.locale, 'yes' if option.reversible else 'no')}.",
                    f"   {operator_text(self.locale, 'expected_time')}: "
                    + estimate(option.expected_time_seconds, "seconds")
                    + ".",
                    f"   {operator_text(self.locale, 'compute_cost')}: "
                    + estimate(option.expected_tokens, "tokens")
                    + ".",
                    f"   {operator_text(self.locale, 'confidence')}: {confidence}.",
                    "",
                ]
            )
        lines.extend(
            [
                operator_text(self.locale, "safe_exit"),
                localize_fixed_text(
                    self.locale, "Esc, close, or timeout denies this action."
                ),
                "",
                operator_text(self.locale, "support_fingerprint"),
                fingerprint(card.card_digest),
            ]
        )
        return "\n".join(lines)

    def _evidence_content(self, card: DecisionCard) -> str:
        binding = card.binding

        def readable(value: str) -> str:
            return localize_fixed_text(
                self.locale, value.replace("_", " ").capitalize()
            )

        def fingerprint(value: str) -> str:
            return f"{value[:10]}…{value[-6:]}"

        lines = [
            operator_text(self.locale, "safety_checks"),
            "- " + localize_fixed_text(
                self.locale, "The current screen evidence is bound to this card."
            ),
            "- " + localize_fixed_text(
                self.locale,
                "If the task, policy, application, or target changes, this card expires.",
            ),
            "- " + localize_fixed_text(
                self.locale, "Choosing an option does not authorize any later action."
            ),
            "",
            operator_text(self.locale, "evidence_available"),
            *(
                f"- {readable(reference.kind.value)}"
                for reference in card.evidence
            ),
            "",
            operator_text(self.locale, "still_unknown"),
            *(
                f"- {readable(fact.value)}" for fact in card.unknown_facts
            ),
            "",
            operator_text(self.locale, "technical_verification"),
            f"- {localize_fixed_text(self.locale, 'Screen state')}: {fingerprint(binding.state_digest)}",
            f"- {localize_fixed_text(self.locale, 'Safety policy')}: {fingerprint(binding.policy_digest)}",
            f"- {localize_fixed_text(self.locale, 'Task')}: {fingerprint(binding.task_digest)}",
            f"- {localize_fixed_text(self.locale, 'Tool registry')}: {fingerprint(binding.registry_digest)}",
            f"- {localize_fixed_text(self.locale, 'Target object')}: {fingerprint(binding.object_digest)}",
            f"- {localize_fixed_text(self.locale, 'Evidence set')}: {fingerprint(binding.evidence_digest)}",
            f"- {localize_fixed_text(self.locale, 'Card')}: {fingerprint(card.card_digest)}",
            f"- {localize_fixed_text(self.locale, 'Expires')}: {card.expires_at.astimezone(UTC).strftime('%H:%M:%S UTC')}",
            "",
            localize_fixed_text(
                self.locale,
                "Fingerprints help support staff correlate records. They grant no authority.",
            ),
        ]
        return "\n".join(lines)


__all__ = [
    "DecisionCardButton",
    "DecisionCardWindow",
    "DecisionCardWindowApi",
    "DecisionCardWindowError",
    "OperatorStepContext",
    "WorkflowBreadcrumb",
    "decision_attention_visual",
]
