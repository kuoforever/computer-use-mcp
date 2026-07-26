"""Composable reviewed capabilities between scenario workers and MCP tools.

Capabilities are declarative authority envelopes, not new dispatch sites.  A
scenario composes them; the resulting MCP tool set is still advertised and
executed only by :class:`AgentRunner`.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


_REVIEWED_TOOLS = frozenset(
    {
        "list_windows",
        "ui_snapshot",
        "document_text",
        "screenshot",
        "capture_region",
        "ocr",
        "activate_window",
        "click",
        "scroll",
        "drag",
        "type",
        "key",
    }
)
_EFFECTS = frozenset({"observation", "navigation", "draft", "external", "critical"})


@dataclass(frozen=True)
class WorkerCapability:
    name: str
    effect: str
    tools: tuple[str, ...]
    preconditions: tuple[str, ...]
    postconditions: tuple[str, ...]
    stop_states: tuple[str, ...]
    requires_approval: bool = False
    invalidates_grounding: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.name, str)
            or not self.name
            or self.effect not in _EFFECTS
            or not isinstance(self.tools, tuple)
            or not self.tools
            or len(set(self.tools)) != len(self.tools)
            or not set(self.tools) <= _REVIEWED_TOOLS
        ):
            raise ValueError("worker capability is invalid")
        for values in (self.preconditions, self.postconditions, self.stop_states):
            if (
                not isinstance(values, tuple)
                or len(set(values)) != len(values)
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise ValueError("worker capability is invalid")
        if self.effect in {"external", "critical"} and not self.requires_approval:
            raise ValueError("externally visible capabilities require approval")
        if self.effect == "observation" and (
            self.requires_approval or self.invalidates_grounding
        ):
            raise ValueError("observation capabilities cannot grant effects")


def _cap(
    name: str,
    effect: str,
    tools: tuple[str, ...],
    pre: tuple[str, ...] = (),
    post: tuple[str, ...] = (),
    stops: tuple[str, ...] = (),
    *,
    approval: bool = False,
    invalidates: bool = False,
) -> WorkerCapability:
    return WorkerCapability(
        name=name,
        effect=effect,
        tools=tools,
        preconditions=pre,
        postconditions=post,
        stop_states=stops,
        requires_approval=approval,
        invalidates_grounding=invalidates,
    )


WORKER_CAPABILITIES = (
    _cap(
        "window_topology",
        "observation",
        ("list_windows",),
        post=("window_owner_chain_observed",),
        stops=("SECURE_DESKTOP", "CAPTURE_UNAVAILABLE"),
    ),
    _cap(
        "structured_observation",
        "observation",
        ("ui_snapshot",),
        pre=("target_window_identified",),
        post=("structured_state_observed",),
        stops=("ACCESSIBILITY_INCOMPLETE",),
    ),
    _cap(
        "semantic_document_observation",
        "observation",
        ("document_text",),
        pre=("target_scope_identified",),
        post=("bounded_document_text_observed",),
        stops=("SEMANTIC_TEXT_UNAVAILABLE",),
    ),
    _cap(
        "bounded_ocr_fallback",
        "observation",
        ("ocr", "capture_region"),
        pre=("primary_display_region_grounded",),
        post=("bounded_visual_text_observed",),
        stops=("OCR_UNCERTAIN", "CAPTURE_UNAVAILABLE"),
    ),
    _cap(
        "visual_state",
        "observation",
        ("capture_region", "screenshot"),
        pre=("primary_display_scope_grounded",),
        post=("pixel_state_observed",),
        stops=("CAPTURE_UNAVAILABLE",),
    ),
    _cap(
        "stable_identity_revalidation",
        "observation",
        ("ui_snapshot", "document_text", "ocr"),
        pre=("stable_item_identity_declared",),
        post=("application_state_verified", "item_identity_verified"),
        stops=("IDENTITY_DRIFT", "ITEM_AMBIGUOUS"),
    ),
    _cap(
        "challenge_detection",
        "observation",
        ("list_windows", "ui_snapshot", "document_text", "ocr"),
        post=("challenge_state_classified",),
        stops=("CHALLENGE", "LOGIN_REQUIRED", "MFA_REQUIRED"),
    ),
    _cap(
        "window_activation",
        "navigation",
        ("list_windows", "activate_window"),
        pre=("window_owner_chain_observed",),
        post=("foreground_target_verified",),
        stops=("ACTIVATION_FAILED", "OWNERSHIP_STALE"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "pointer_navigation",
        "navigation",
        ("ui_snapshot", "click"),
        pre=("fresh_ref_or_coordinates", "item_identity_verified"),
        post=("navigation_state_reobserved",),
        stops=("STALE_REFERENCE", "MODE_DRIFT"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "viewport_navigation",
        "navigation",
        ("screenshot", "scroll"),
        pre=("primary_display_coordinates_grounded", "item_identity_verified"),
        post=("viewport_state_reobserved",),
        stops=("VIEWPORT_DRIFT", "MODE_DRIFT"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "canvas_manipulation",
        "navigation",
        ("screenshot", "drag"),
        pre=("drag_endpoints_grounded", "item_identity_verified"),
        post=("canvas_state_reobserved",),
        stops=("OBJECT_IDENTITY_DRIFT", "VIEWPORT_DRIFT", "UNKNOWN_OUTCOME"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "keyboard_navigation",
        "navigation",
        ("ui_snapshot", "key"),
        pre=("foreground_target_verified", "focus_verified"),
        post=("navigation_state_reobserved",),
        stops=("FOCUS_DRIFT", "MODE_DRIFT"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "bounded_text_entry",
        "draft",
        ("ui_snapshot", "type"),
        pre=("foreground_target_verified", "editor_focus_verified"),
        post=("entered_text_digest_verified",),
        stops=("EDITOR_IDENTITY_DRIFT", "VALUE_VERIFICATION_FAILED"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "mode_recovery",
        "navigation",
        ("list_windows", "ui_snapshot", "key"),
        pre=("mode_state_observed",),
        post=("safe_mode_reestablished",),
        stops=("MODAL_OPERATION_UNKNOWN", "HUMAN_HANDOFF_REQUIRED"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "post_action_verification",
        "observation",
        ("ui_snapshot", "document_text", "ocr", "capture_region"),
        pre=("action_dispatch_recorded",),
        post=("application_visible_effect_classified",),
        stops=("UNKNOWN_OUTCOME", "VERIFICATION_CONFLICT"),
    ),
    _cap(
        "external_commit",
        "external",
        ("ui_snapshot", "click", "key"),
        pre=("exact_effect_approved", "idempotency_preflight_complete"),
        post=("external_effect_verified",),
        stops=("UNKNOWN_OUTCOME", "VERSION_CONFLICT", "AUTHORITY_EXPIRED"),
        approval=True,
        invalidates=True,
    ),
    _cap(
        "critical_commit",
        "critical",
        ("ui_snapshot", "click", "key"),
        pre=("maker_checker_verified", "exact_effect_approved"),
        post=("critical_effect_reconciled",),
        stops=("UNKNOWN_OUTCOME", "MAKER_CHECKER_REQUIRED", "AUTHORITY_EXPIRED"),
        approval=True,
        invalidates=True,
    ),
)

WORKER_CAPABILITIES_BY_NAME: Mapping[str, WorkerCapability] = MappingProxyType(
    {capability.name: capability for capability in WORKER_CAPABILITIES}
)

_BASE_REVIEW = (
    "window_topology",
    "structured_observation",
    "stable_identity_revalidation",
    "challenge_detection",
    "post_action_verification",
)
_DOCUMENT = _BASE_REVIEW + (
    "semantic_document_observation",
    "bounded_ocr_fallback",
)
_VISUAL = _BASE_REVIEW + ("bounded_ocr_fallback", "visual_state")
_NAVIGATION = (
    "window_activation",
    "pointer_navigation",
    "viewport_navigation",
    "keyboard_navigation",
)
_DRAFT = _NAVIGATION + ("bounded_text_entry",)

SCENARIO_CAPABILITY_COMPOSITIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "A1": _DOCUMENT + _NAVIGATION,
        "A2": _DOCUMENT + _DRAFT,
        "A3": _VISUAL + _DRAFT + ("external_commit",),
        "A4": _DOCUMENT + _DRAFT + ("canvas_manipulation",),
        "A5": _DOCUMENT + ("visual_state",) + _NAVIGATION,
        "A6": _VISUAL + _DRAFT + ("canvas_manipulation", "mode_recovery"),
        "A7": _DOCUMENT + _DRAFT + ("external_commit",),
        "A8": _VISUAL + _DRAFT + (
            "canvas_manipulation",
            "mode_recovery",
            "external_commit",
        ),
        "A9": _VISUAL + _DRAFT + ("canvas_manipulation", "mode_recovery"),
        "A10": _DOCUMENT + _DRAFT + ("mode_recovery",),
        "A11": _VISUAL + _DRAFT + ("mode_recovery",),
        "A12": _VISUAL + _DRAFT + ("canvas_manipulation", "mode_recovery"),
        "A13": _VISUAL + _DRAFT + ("critical_commit",),
        "A14": _DOCUMENT + _DRAFT + ("external_commit",),
        "A15": _DOCUMENT + _DRAFT + ("external_commit",),
        "A16": _DOCUMENT + _DRAFT + ("critical_commit",),
        "A17": _DOCUMENT + _DRAFT + ("external_commit",),
        "A18": _DOCUMENT + ("visual_state",) + _NAVIGATION,
        "A19": _VISUAL + _DRAFT + ("critical_commit",),
    }
)


def capabilities_for_scenario(scenario_id: str) -> tuple[WorkerCapability, ...]:
    try:
        names = SCENARIO_CAPABILITY_COMPOSITIONS[scenario_id]
        return tuple(WORKER_CAPABILITIES_BY_NAME[name] for name in names)
    except (KeyError, TypeError) as exc:
        raise KeyError("WORKER_SCENARIO_UNSUPPORTED") from exc


def capabilities_for_composition(
    scenario_id: str,
    capability_names: tuple[str, ...] = (),
) -> tuple[WorkerCapability, ...]:
    """Resolve an explicit composition, or one built-in example composition."""

    if capability_names:
        try:
            return tuple(
                WORKER_CAPABILITIES_BY_NAME[name] for name in capability_names
            )
        except (KeyError, TypeError) as exc:
            raise KeyError("WORKER_CAPABILITY_UNSUPPORTED") from exc
    return capabilities_for_scenario(scenario_id)


def tools_for_scenario(scenario_id: str) -> frozenset[str]:
    return frozenset(
        tool
        for capability in capabilities_for_scenario(scenario_id)
        for tool in capability.tools
    )


def tools_for_composition(
    scenario_id: str,
    capability_names: tuple[str, ...] = (),
) -> frozenset[str]:
    return frozenset(
        tool
        for capability in capabilities_for_composition(
            scenario_id,
            capability_names,
        )
        for tool in capability.tools
    )


__all__ = [
    "SCENARIO_CAPABILITY_COMPOSITIONS",
    "WORKER_CAPABILITIES",
    "WORKER_CAPABILITIES_BY_NAME",
    "WorkerCapability",
    "capabilities_for_composition",
    "capabilities_for_scenario",
    "tools_for_composition",
    "tools_for_scenario",
]
