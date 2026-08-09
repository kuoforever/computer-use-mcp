"""Inert H8B all-of dependency-edge contract.

Edges are immutable identifiers only. They carry no condition expression,
callable, retry, compensation, any-of rule, tool, argument, provider, Runner,
MCP, desktop, approval, or dispatch authority.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


MAX_TREE_DEPENDENCIES = 128
MAX_TREE_DEPENDENCY_FAN_IN = 16
MAX_TREE_GRAPH_DEPTH = 24
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class TreeDependencyError(ValueError):
    """Fixed, content-free failure for a malformed dependency edge."""


def _require_identifier(value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise TreeDependencyError("TREE_DEPENDENCY_INVALID")
    return value


@dataclass(frozen=True, order=True)
class TreeDependency:
    """One prerequisite-to-dependent all-of edge."""

    prerequisite_id: str
    dependent_id: str

    def __post_init__(self) -> None:
        _require_identifier(self.prerequisite_id)
        _require_identifier(self.dependent_id)
        if self.prerequisite_id == self.dependent_id:
            raise TreeDependencyError("TREE_DEPENDENCY_SELF_REFERENCE")

    def to_payload(self) -> dict[str, str]:
        return {
            "prerequisite_id": self.prerequisite_id,
            "dependent_id": self.dependent_id,
        }


__all__ = [
    "MAX_TREE_DEPENDENCIES",
    "MAX_TREE_DEPENDENCY_FAN_IN",
    "MAX_TREE_GRAPH_DEPTH",
    "TreeDependency",
    "TreeDependencyError",
]
