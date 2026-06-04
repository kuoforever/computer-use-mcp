"""computer-use-mcp — model-agnostic computer-use MCP server (Windows first).

Layering (ports & adapters):
  contract.py        the language-agnostic driver boundary (no platform imports)
  dpi.py             DPI-awareness bootstrap (ctypes only; load before screen/UIA)
  drivers/windows.py the Windows driver implementing the contract

See docs/DRIVER_CONTRACT.md and docs/DESIGN.md.
"""

__version__ = "0.0.0"
