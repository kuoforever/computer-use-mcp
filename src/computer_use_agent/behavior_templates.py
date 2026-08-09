"""Pinned, reviewed, and non-executing behavior-template registry.

Templates in this module are immutable Host data.  They can describe one inert
next observation boundary, but they cannot persist state, call a provider,
dispatch through Runner or MCP, or grant policy, approval, retry, or replay
authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Mapping, Sequence

from .boss_semantic_extraction import (
    BOSS_OBSERVATION_LADDER,
    BossObservationAttempt,
    BossObservationDecision,
    BossObservationDecisionState,
    BossObservationSource,
    BossObservationStatus,
    decide_next_boss_observation,
)
from .hierarchical_control import TreeBudget, TreeNode, TreeNodeKind
from .tool_registry import ToolValidationError, get_tool_spec
from .types import ToolEffect


BEHAVIOR_TEMPLATE_CONTRACT_VERSION = 1
BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID = "boss.per_item_observation_ladder"
BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION = 1
MAX_BEHAVIOR_TEMPLATE_RUNGS = 16
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class BehaviorTemplateError(ValueError):
    """Content-free rejection of an invalid template or exact pin."""


class BehaviorControlKind(str, Enum):
    SELECTOR = "selector"


class BehaviorArgumentBinding(str, Enum):
    FOREGROUND_SCOPE = "foreground_scope"
    CLAIMED_REGION = "claimed_region"
    EMPTY = "empty"


_BOSS_RUNG_BINDINGS: Mapping[
    BossObservationSource, tuple[str, BehaviorArgumentBinding]
] = MappingProxyType(
    {
        BossObservationSource.UIA: (
            "ui_snapshot",
            BehaviorArgumentBinding.FOREGROUND_SCOPE,
        ),
        BossObservationSource.DOCUMENT_TEXT: (
            "document_text",
            BehaviorArgumentBinding.FOREGROUND_SCOPE,
        ),
        BossObservationSource.OCR: (
            "ocr",
            BehaviorArgumentBinding.CLAIMED_REGION,
        ),
        BossObservationSource.CROPPED_IMAGE: (
            "capture_region",
            BehaviorArgumentBinding.CLAIMED_REGION,
        ),
        BossObservationSource.SCREENSHOT: (
            "screenshot",
            BehaviorArgumentBinding.EMPTY,
        ),
    }
)


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_INVALID")
    return value


def _require_digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_INVALID")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


@dataclass(frozen=True)
class BehaviorTemplateRung:
    """One reviewed observation strategy with no call identity or authority."""

    source: BossObservationSource
    tool_name: str
    argument_binding: BehaviorArgumentBinding
    required_safety_baselines: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source, BossObservationSource)
            or not isinstance(self.argument_binding, BehaviorArgumentBinding)
            or not isinstance(self.required_safety_baselines, tuple)
            or any(
                not isinstance(value, str) or not value
                for value in self.required_safety_baselines
            )
            or len(set(self.required_safety_baselines))
            != len(self.required_safety_baselines)
        ):
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_INVALID")
        try:
            spec = get_tool_spec(self.tool_name)
        except (ToolValidationError, TypeError) as exc:
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_INVALID") from exc
        if (
            spec.effect is not ToolEffect.OBSERVATION
            or spec.requires_host_approval
            or spec.invalidates_observation
            or spec.required_safety_baselines != self.required_safety_baselines
        ):
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_AUTHORITY_INVALID")
        if _BOSS_RUNG_BINDINGS.get(self.source) != (
            self.tool_name,
            self.argument_binding,
        ):
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_BINDING_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "argument_binding": self.argument_binding.value,
            "required_safety_baselines": list(self.required_safety_baselines),
            "source": self.source.value,
            "tool_name": self.tool_name,
        }


@dataclass(frozen=True)
class ReviewedBehaviorTemplate:
    """One exact immutable version; lookup never selects a latest version."""

    template_id: str
    version: int
    control: BehaviorControlKind
    rungs: tuple[BehaviorTemplateRung, ...]
    terminal_statuses: tuple[BossObservationStatus, ...]
    exhaustion_stop_code: str
    budget: TreeBudget
    requires_explicit_incomplete: bool = True
    contract_version: int = BEHAVIOR_TEMPLATE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        _require_identifier(self.template_id)
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or not 1 <= self.version <= 2_147_483_647
            or not isinstance(self.contract_version, int)
            or isinstance(self.contract_version, bool)
            or self.contract_version != BEHAVIOR_TEMPLATE_CONTRACT_VERSION
            or not isinstance(self.control, BehaviorControlKind)
            or not isinstance(self.rungs, tuple)
            or not 1 <= len(self.rungs) <= MAX_BEHAVIOR_TEMPLATE_RUNGS
            or not all(isinstance(rung, BehaviorTemplateRung) for rung in self.rungs)
            or len({rung.source for rung in self.rungs}) != len(self.rungs)
            or not isinstance(self.terminal_statuses, tuple)
            or not self.terminal_statuses
            or not all(
                isinstance(status, BossObservationStatus)
                for status in self.terminal_statuses
            )
            or len(set(self.terminal_statuses)) != len(self.terminal_statuses)
            or any(
                status
                in {BossObservationStatus.SUFFICIENT, BossObservationStatus.INCOMPLETE}
                for status in self.terminal_statuses
            )
            or not isinstance(self.exhaustion_stop_code, str)
            or _IDENTIFIER.fullmatch(self.exhaustion_stop_code) is None
            or not isinstance(self.budget, TreeBudget)
            or self.budget.tool_calls != len(self.rungs)
            or self.budget.side_effects != 0
            or self.budget.retries != 0
            or self.requires_explicit_incomplete is not True
        ):
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_INVALID")

    def to_payload(self) -> dict[str, object]:
        return {
            "budget": self.budget.to_payload(),
            "contract_version": self.contract_version,
            "control": self.control.value,
            "exhaustion_stop_code": self.exhaustion_stop_code,
            "requires_explicit_incomplete": self.requires_explicit_incomplete,
            "rungs": [rung.to_payload() for rung in self.rungs],
            "template_id": self.template_id,
            "terminal_statuses": [status.value for status in self.terminal_statuses],
            "version": self.version,
        }

    @property
    def digest(self) -> str:
        return sha256(_canonical(self.to_payload())).hexdigest()


@dataclass(frozen=True)
class BehaviorTemplatePin:
    template_id: str
    version: int
    digest: str

    def __post_init__(self) -> None:
        _require_identifier(self.template_id)
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or not 1 <= self.version <= 2_147_483_647
        ):
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_PIN_INVALID")
        _require_digest(self.digest)

    def to_payload(self) -> dict[str, object]:
        return {
            "digest": self.digest,
            "template_id": self.template_id,
            "version": self.version,
        }


BOSS_PER_ITEM_OBSERVATION_TEMPLATE = ReviewedBehaviorTemplate(
    template_id=BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID,
    version=BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION,
    control=BehaviorControlKind.SELECTOR,
    rungs=(
        BehaviorTemplateRung(
            BossObservationSource.UIA,
            "ui_snapshot",
            BehaviorArgumentBinding.FOREGROUND_SCOPE,
        ),
        BehaviorTemplateRung(
            BossObservationSource.DOCUMENT_TEXT,
            "document_text",
            BehaviorArgumentBinding.FOREGROUND_SCOPE,
        ),
        BehaviorTemplateRung(
            BossObservationSource.OCR,
            "ocr",
            BehaviorArgumentBinding.CLAIMED_REGION,
            ("title_matched_image_redaction",),
        ),
        BehaviorTemplateRung(
            BossObservationSource.CROPPED_IMAGE,
            "capture_region",
            BehaviorArgumentBinding.CLAIMED_REGION,
        ),
        BehaviorTemplateRung(
            BossObservationSource.SCREENSHOT,
            "screenshot",
            BehaviorArgumentBinding.EMPTY,
        ),
    ),
    terminal_statuses=(
        BossObservationStatus.AUTH_REQUIRED,
        BossObservationStatus.CHALLENGE_REQUIRED,
        BossObservationStatus.RATE_LIMITED,
        BossObservationStatus.SITE_BLOCKED,
        BossObservationStatus.CONTENT_UNAVAILABLE,
    ),
    exhaustion_stop_code="BOSS_OBSERVATION_LADDER_EXHAUSTED",
    budget=TreeBudget(tool_calls=5),
)
BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN = BehaviorTemplatePin(
    template_id=BOSS_PER_ITEM_OBSERVATION_TEMPLATE.template_id,
    version=BOSS_PER_ITEM_OBSERVATION_TEMPLATE.version,
    digest=BOSS_PER_ITEM_OBSERVATION_TEMPLATE.digest,
)

REVIEWED_BEHAVIOR_TEMPLATES = (BOSS_PER_ITEM_OBSERVATION_TEMPLATE,)
REVIEWED_BEHAVIOR_TEMPLATES_BY_KEY: Mapping[
    tuple[str, int], ReviewedBehaviorTemplate
] = MappingProxyType(
    {
        (template.template_id, template.version): template
        for template in REVIEWED_BEHAVIOR_TEMPLATES
    }
)


def reviewed_behavior_registry_digest() -> str:
    return sha256(
        _canonical([template.to_payload() for template in REVIEWED_BEHAVIOR_TEMPLATES])
    ).hexdigest()


def resolve_reviewed_behavior_template(
    pin: BehaviorTemplatePin,
) -> ReviewedBehaviorTemplate:
    """Resolve only an exact id/version/digest pin, without fallback."""

    if not isinstance(pin, BehaviorTemplatePin):
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_PIN_INVALID")
    template = REVIEWED_BEHAVIOR_TEMPLATES_BY_KEY.get(
        (pin.template_id, pin.version)
    )
    if template is None or template.digest != pin.digest:
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_PIN_MISMATCH")
    return template


def boss_per_item_observation_sources(
    pin: BehaviorTemplatePin,
) -> tuple[BossObservationSource, ...]:
    template = resolve_reviewed_behavior_template(pin)
    sources = tuple(rung.source for rung in template.rungs)
    if (
        template.template_id != BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID
        or sources != BOSS_OBSERVATION_LADDER
    ):
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_RUNTIME_MISMATCH")
    return sources


def bind_boss_observation_request(
    pin: BehaviorTemplatePin,
    source: BossObservationSource,
    *,
    region: Mapping[str, int],
) -> tuple[str, dict[str, object]]:
    """Return inert reviewed request data; this function never creates a call."""

    template = resolve_reviewed_behavior_template(pin)
    if template.template_id != BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID:
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_RUNTIME_MISMATCH")
    matching = tuple(rung for rung in template.rungs if rung.source is source)
    if len(matching) != 1:
        raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_SOURCE_INVALID")
    rung = matching[0]
    if rung.argument_binding is BehaviorArgumentBinding.FOREGROUND_SCOPE:
        arguments: dict[str, object] = {"scope": "foreground"}
    elif rung.argument_binding is BehaviorArgumentBinding.EMPTY:
        arguments = {}
    else:
        if (
            not isinstance(region, Mapping)
            or set(region) != {"x", "y", "w", "h"}
            or any(
                not isinstance(region[name], int) or isinstance(region[name], bool)
                for name in ("x", "y", "w", "h")
            )
            or region["x"] < 0
            or region["y"] < 0
            or region["w"] <= 0
            or region["h"] <= 0
            or region["w"] * region["h"] > 4_000_000
        ):
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_REGION_INVALID")
        arguments = {name: region[name] for name in ("x", "y", "w", "h")}
    return rung.tool_name, arguments


def decide_pinned_boss_observation(
    pin: BehaviorTemplatePin,
    attempts: Sequence[BossObservationAttempt],
) -> BossObservationDecision:
    """Apply the existing reducer only when its complete contract is pinned."""

    template = resolve_reviewed_behavior_template(pin)
    sources = boss_per_item_observation_sources(pin)
    decision = decide_next_boss_observation(attempts)
    if decision.state is BossObservationDecisionState.OBSERVE:
        if decision.next_source is None or decision.next_source not in sources:
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_RUNTIME_MISMATCH")
    elif decision.state is BossObservationDecisionState.HANDOFF:
        allowed_stop_codes = {
            template.exhaustion_stop_code,
            *(f"BOSS_{status.value}" for status in template.terminal_statuses),
        }
        if decision.stop_code not in allowed_stop_codes:
            raise BehaviorTemplateError("BEHAVIOR_TEMPLATE_RUNTIME_MISMATCH")
    return decision


def reviewed_subtree_node(
    pin: BehaviorTemplatePin,
    *,
    node_id: str,
    parent_id: str | None = None,
) -> TreeNode:
    """Bind one H1 subtree leaf to an exact reviewed template version."""

    template = resolve_reviewed_behavior_template(pin)
    return TreeNode(
        node_id=node_id,
        parent_id=parent_id,
        kind=TreeNodeKind.SUBTREE,
        template_id=template.template_id,
        template_version=template.version,
        template_digest=template.digest,
        budget=template.budget,
    )


__all__ = [
    "BEHAVIOR_TEMPLATE_CONTRACT_VERSION",
    "BOSS_PER_ITEM_OBSERVATION_TEMPLATE",
    "BOSS_PER_ITEM_OBSERVATION_TEMPLATE_ID",
    "BOSS_PER_ITEM_OBSERVATION_TEMPLATE_PIN",
    "BOSS_PER_ITEM_OBSERVATION_TEMPLATE_VERSION",
    "MAX_BEHAVIOR_TEMPLATE_RUNGS",
    "REVIEWED_BEHAVIOR_TEMPLATES",
    "REVIEWED_BEHAVIOR_TEMPLATES_BY_KEY",
    "BehaviorArgumentBinding",
    "BehaviorControlKind",
    "BehaviorTemplateError",
    "BehaviorTemplatePin",
    "BehaviorTemplateRung",
    "ReviewedBehaviorTemplate",
    "bind_boss_observation_request",
    "boss_per_item_observation_sources",
    "decide_pinned_boss_observation",
    "resolve_reviewed_behavior_template",
    "reviewed_behavior_registry_digest",
    "reviewed_subtree_node",
]
