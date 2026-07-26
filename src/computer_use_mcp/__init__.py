"""Guarded Desktop Agent — safety-governed desktop automation for Windows.

Layering (ports & adapters):
  contract.py        the language-agnostic driver boundary (no platform imports)
  dpi.py             DPI-awareness bootstrap (ctypes only; load before screen/UIA)
  drivers/windows.py the Windows driver implementing the contract

See docs/DRIVER_CONTRACT.md and docs/DESIGN.md.
"""

__version__ = "0.1.0"
PRODUCT_NAME = "Guarded Desktop Agent"
DISTRIBUTION_NAME = "guarded-desktop-agent"
MCP_SERVER_NAME = "guarded-desktop-mcp"

__all__ = [
    "DISTRIBUTION_NAME",
    "MCP_SERVER_NAME",
    "PRODUCT_NAME",
    "__version__",
]
