"""Host-owned desktop grounding derived only from reviewed observations."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .tool_registry import GroundingRequirement, ToolSpec
from .types import ToolCall, ToolResult


_REF = re.compile(r"(?m)^(ref_\d+)\s+\|")
_WINDOW = re.compile(r"(?m)^[ *]\s*([^\s|]+)\s+\|")


class GroundingError(RuntimeError):
    """Fixed grounding failure without observation or argument content."""


@dataclass(frozen=True)
class GroundingState:
    generation: int | None = None
    observation_epoch: int | None = None
    refs: frozenset[str] = frozenset()
    window_ids: frozenset[str] = frozenset()
    screenshot_size: tuple[int, int] | None = None
    has_observation: bool = False

    def observe(self, result: ToolResult, *, generation: int, epoch: int) -> "GroundingState":
        if not result.ok:
            return self
        if self.generation != generation:
            base = GroundingState(generation=generation)
        else:
            base = self
        refs = base.refs
        windows = base.window_ids
        screenshot_size = base.screenshot_size
        if result.tool_name in {"ui_snapshot", "find"}:
            refs = frozenset(_REF.findall(result.sanitized_text))
        elif result.tool_name == "list_windows":
            windows = frozenset(_WINDOW.findall(result.sanitized_text))
        elif result.tool_name == "screenshot" and result.images:
            screenshot_size = (result.images[0].width, result.images[0].height)
        return GroundingState(
            generation=generation,
            observation_epoch=epoch,
            refs=refs,
            window_ids=windows,
            screenshot_size=screenshot_size,
            has_observation=True,
        )

    def invalidate(self) -> "GroundingState":
        return GroundingState()

    def validate(self, call: ToolCall, spec: ToolSpec, *, generation: int) -> None:
        if self.generation is None:
            raise GroundingError("GROUNDING_REQUIRED")
        if self.generation != generation:
            raise GroundingError("MCP_GENERATION_CHANGED")
        requirement = spec.grounding
        if requirement is GroundingRequirement.NONE:
            return
        if requirement is GroundingRequirement.RECENT_OBSERVATION:
            if not self.has_observation:
                raise GroundingError("GROUNDING_REQUIRED")
            return
        if requirement is GroundingRequirement.OBSERVED_WINDOW:
            if call.arguments.get("window_id") not in self.window_ids:
                raise GroundingError("GROUNDING_REQUIRED")
            return
        if requirement is GroundingRequirement.REF_OR_SCREENSHOT:
            ref = call.arguments.get("ref")
            if isinstance(ref, str):
                if ref not in self.refs:
                    raise GroundingError("GROUNDING_REQUIRED")
                return
            x = call.arguments.get("x")
            y = call.arguments.get("y")
            if self.screenshot_size is None or not isinstance(x, int) or not isinstance(y, int):
                raise GroundingError("GROUNDING_REQUIRED")
            width, height = self.screenshot_size
            if not 0 <= x < width or not 0 <= y < height:
                raise GroundingError("GROUNDING_REQUIRED")
            if call.name == "drag":
                to_x = call.arguments.get("to_x")
                to_y = call.arguments.get("to_y")
                if (
                    not isinstance(to_x, int)
                    or not isinstance(to_y, int)
                    or not 0 <= to_x < width
                    or not 0 <= to_y < height
                ):
                    raise GroundingError("GROUNDING_REQUIRED")
            return
        raise GroundingError("GROUNDING_REQUIRED")


__all__ = ["GroundingError", "GroundingState"]
