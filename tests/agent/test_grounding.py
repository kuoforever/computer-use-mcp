from __future__ import annotations

import base64

import pytest

from computer_use_agent.grounding import GroundingError, GroundingState
from computer_use_agent.tool_registry import get_tool_spec
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _result(name: str, *, text: str = "", image: bool = False) -> ToolResult:
    return ToolResult(
        CallIdentity("run_1", "turn_1", f"call_{name}"),
        name,
        ToolResultStatus.SUCCESS,
        DispatchCertainty.DISPATCHED,
        sanitized_text=text,
        images=(ImageContent("image/png", _PNG, 1, 1),) if image else (),
    )


def test_refs_windows_and_coordinates_require_current_generation_observations() -> None:
    state = GroundingState().observe(
        _result("ui_snapshot", text='ref_7 | button "OK" | (0,0,1,1) | enabled'),
        generation=3,
        epoch=1,
    )
    state = state.observe(
        _result("list_windows", text='* 42 | app.exe | "App"'),
        generation=3,
        epoch=2,
    )
    state = state.observe(_result("screenshot", image=True), generation=3, epoch=3)

    state.validate(
        ToolCall(CallIdentity("run_1", "turn_2", "click_ref"), "click", {"ref": "ref_7"}),
        get_tool_spec("click"),
        generation=3,
    )
    state.validate(
        ToolCall(
            CallIdentity("run_1", "turn_2", "activate"),
            "activate_window",
            {"window_id": "42"},
        ),
        get_tool_spec("activate_window"),
        generation=3,
    )
    state.validate(
        ToolCall(CallIdentity("run_1", "turn_2", "click_xy"), "click", {"x": 0, "y": 0}),
        get_tool_spec("click"),
        generation=3,
    )

    with pytest.raises(GroundingError, match="MCP_GENERATION_CHANGED"):
        state.validate(
            ToolCall(
                CallIdentity("run_1", "turn_2", "stale"),
                "click",
                {"ref": "ref_7"},
            ),
            get_tool_spec("click"),
            generation=4,
        )
    with pytest.raises(GroundingError, match="GROUNDING_REQUIRED"):
        state.validate(
            ToolCall(
                CallIdentity("run_1", "turn_2", "outside"),
                "click",
                {"x": 1, "y": 0},
            ),
            get_tool_spec("click"),
            generation=3,
        )


def test_invalidation_removes_all_action_authority() -> None:
    state = GroundingState().observe(
        _result("list_windows", text='* 42 | app.exe | "App"'),
        generation=1,
        epoch=1,
    )

    with pytest.raises(GroundingError, match="GROUNDING_REQUIRED"):
        state.invalidate().validate(
            ToolCall(
                CallIdentity("run_1", "turn_2", "activate"),
                "activate_window",
                {"window_id": "42"},
            ),
            get_tool_spec("activate_window"),
            generation=1,
        )
