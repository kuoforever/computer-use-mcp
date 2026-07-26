from __future__ import annotations

import tomllib
from pathlib import Path

from computer_use_mcp import (
    DISTRIBUTION_NAME,
    MCP_SERVER_NAME,
    PRODUCT_NAME,
)
from computer_use_mcp.server import build_server


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_product_and_mcp_names() -> None:
    assert PRODUCT_NAME == "Guarded Desktop Agent"
    assert DISTRIBUTION_NAME == "guarded-desktop-agent"
    assert MCP_SERVER_NAME == "guarded-desktop-mcp"

    server = build_server(driver=object(), start_estop=False)
    assert server.name == MCP_SERVER_NAME


def test_distribution_exposes_canonical_and_compatibility_commands() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == DISTRIBUTION_NAME
    assert project["scripts"] == {
        "guarded-desktop-mcp": "computer_use_mcp.server:main",
        "guarded-desktop-agent": "computer_use_agent.cli:main",
        "computer-use-mcp": "computer_use_mcp.server:main",
        "computer-use-agent": "computer_use_agent.cli:main",
    }
