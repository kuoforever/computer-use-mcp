"""Host policy dispositions and hard initial budgets."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .config import AGENTIC_ACTIONS_MODE, APPROVED_ACTIONS_MODE, PolicyConfig
from .tool_registry import ToolSpec
from .types import RunBudget, ToolEffect


class PolicyDisposition(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


@dataclass(frozen=True)
class HostPolicy:
    """Immutable projection of reviewed policy configuration."""

    version: str
    config: PolicyConfig

    @classmethod
    def from_config(cls, version: str, config: PolicyConfig) -> "HostPolicy":
        if not isinstance(version, str) or not version.strip():
            raise ValueError("policy version must be a non-empty string")
        if not isinstance(config, PolicyConfig):
            raise ValueError("config must be a PolicyConfig")
        return cls(version=version, config=config)

    def initial_budget(self) -> RunBudget:
        return RunBudget(
            max_model_turns=self.config.max_model_turns,
            max_tool_calls=self.config.max_tool_calls,
            max_side_effects=self.config.max_side_effects,
            max_input_tokens=self.config.max_input_tokens,
        )

    def disposition(
        self,
        tool: ToolSpec,
        *,
        satisfied_safety_baselines: frozenset[str] = frozenset(),
    ) -> PolicyDisposition:
        if not isinstance(satisfied_safety_baselines, frozenset) or not all(
            isinstance(baseline, str) and baseline
            for baseline in satisfied_safety_baselines
        ):
            raise ValueError(
                "satisfied_safety_baselines must be a frozenset of non-empty strings"
            )
        if not set(tool.required_safety_baselines).issubset(
            satisfied_safety_baselines
        ):
            return PolicyDisposition.DENY
        if tool.effect is ToolEffect.OBSERVATION:
            return PolicyDisposition.ALLOW
        if self.config.mode == APPROVED_ACTIONS_MODE:
            return PolicyDisposition.APPROVAL_REQUIRED
        if self.config.mode == AGENTIC_ACTIONS_MODE:
            return PolicyDisposition.ALLOW
        return PolicyDisposition.DENY
