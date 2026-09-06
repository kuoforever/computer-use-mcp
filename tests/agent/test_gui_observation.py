from __future__ import annotations

import base64
import asyncio
from contextlib import nullcontext
from dataclasses import replace
import sys
from types import SimpleNamespace

import pytest

from computer_use_agent.gui_observation import (
    StampedObservation,
    collect_gui_observation as collect_async,
)
from computer_use_agent.types import (
    CallIdentity,
    DispatchCertainty,
    ImageContent,
    ToolCall,
    ToolResult,
    ToolResultStatus,
)
from computer_use_mcp.core import Session
from computer_use_mcp.contract import Node, Rect, TreeResult
from computer_use_mcp.gui_metadata import (
    GuiMetadataError,
    VerifiedControl,
    VerifiedGuiState,
    strict_tree,
)

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
TASK = dict(
    version=1,
    request_id="gui-producer",
    target_scope="314",
    target=dict(name="Document", role="edit"),
)


def collect_gui_observation(*args, **kwargs):
    return asyncio.run(collect_async(*args, **kwargs))


class FakeSource:
    def __init__(self, fault=""):
        self.fault = fault
        self.epoch = 0
        self.generation = 7
        self.calls = []
        self.inspections = 0
        self.control = VerifiedControl("1-2", "edit", "Document", (0, 0, 1, 1), True, True, True)
        self.metadata = VerifiedGuiState("314", "314", (0, 0, 1, 1), (0, 0, 1, 1), (self.control,))
        node = Node("1-2", "Edit", "Document", None, Rect(0, 0, 1, 1), ["enabled", "focused"], [])
        self.session = Session(SimpleNamespace(get_tree=lambda opts: TreeResult([node], 0)))

    def state(self):
        return self.generation, self.epoch

    async def inspect(self, scope):
        self.inspections += 1
        if self.fault == "property":
            raise GuiMetadataError("GUI_PROPERTY_READ_FAILED")
        if self.fault == "changed" and self.inspections == 2:
            return replace(self.metadata, controls=(replace(self.control, focused=False),))
        return self.metadata

    async def resolve_ref(self, ref):
        if self.fault == "ref":
            return "unknown"
        return self.session._native_by_ref.get(ref, "")

    async def read(self, tool, arguments):
        self.epoch += 1
        self.calls.append(tool)
        identity = CallIdentity("gui-run", "gui-turn", f"read-{self.epoch}")
        if tool == "list_windows":
            text = '* 314 | editor.exe | "Document"'
        elif tool == "ui_snapshot":
            text = self.session.ui_snapshot("314")
            if self.fault == "truncated":
                text += "\n# incomplete: missing"
            if self.fault == "name":
                text = text.replace('"Document"', '"Other"')
            if self.fault == "empty":
                text = "# (no interactive elements in scope)"
            if self.fault == "state":
                text = text.replace("enabled", "disabled")
        else:
            text = ""
        result = ToolResult(
            identity,
            tool,
            ToolResultStatus.SUCCESS,
            DispatchCertainty.DISPATCHED,
            sanitized_text=text,
            images=(ImageContent("image/png", PNG, 1, 1),) if tool == "screenshot" else (),
        )
        stamp = StampedObservation(
            ToolCall(identity, tool, arguments), result, self.generation, self.epoch
        )
        if self.fault == "generation" and tool == "ui_snapshot":
            self.generation += 1
        if self.fault == "epoch" and tool == "ui_snapshot":
            self.epoch += 1
        if self.fault == "identity" and tool == "ui_snapshot":
            stamp = replace(
                stamp,
                call=ToolCall(CallIdentity("other", "gui-turn", identity.call_id), tool, arguments),
            )
        return stamp


def test_complete_producer_derives_facts_from_real_result_types_and_session_refs():
    source = FakeSource()
    bundle = collect_gui_observation(TASK, source, clock=lambda: 1.0)
    value = bundle.to_dict()
    assert source.calls == ["list_windows", "ui_snapshot", "screenshot"]
    assert source.inspections == 2
    assert value["task"]["current_epoch"] == 3
    assert value["task"]["runtime_generation"] == 7
    assert value["host_facts"]["control_states"] == {"ref_1": {"enabled": True, "visible": True}}
    assert value["host_facts"]["window_bounds"] == [0, 0, 1, 1]
    assert value["host_facts"]["frame_origin"] == [0, 0]
    assert value["host_facts"]["coherent_complete_projection"] is True
    assert value["execution_authorized"] is False
    assert bundle.image == PNG
    value["host_facts"]["control_states"].clear()
    assert bundle.to_dict()["host_facts"]["control_states"]


@pytest.mark.parametrize(
    "fault",
    [
        "property",
        "changed",
        "ref",
        "truncated",
        "name",
        "empty",
        "state",
        "generation",
        "epoch",
        "identity",
    ],
)
def test_inconsistent_collection_never_returns_facts(fault):
    with pytest.raises(GuiMetadataError):
        collect_gui_observation(TASK, FakeSource(fault), clock=lambda: 1.0)


def test_time_budget_and_nonmonotonic_clock():
    for later in [5.0, -1.0, float("nan")]:
        clock = iter([0.0, later]).__next__
        with pytest.raises(GuiMetadataError, match="GUI_OBSERVATION_TIMEOUT"):
            collect_gui_observation(TASK, FakeSource(), clock=clock)


def control(**overrides):
    values = dict(
        ControlTypeName="EditControl",
        Name="Document",
        BoundingRectangle=SimpleNamespace(left=0, top=0, right=1, bottom=1),
        IsEnabled=True,
        IsOffscreen=False,
        HasKeyboardFocus=True,
        GetRuntimeId=lambda: [1, 2],
        GetChildren=lambda: [],
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def root(*controls):
    return SimpleNamespace(GetChildren=lambda: list(controls))


def test_strict_tree_no_fallback_and_no_partial_data():
    assert strict_tree(root(control()), (0, 0, 1, 1))[0].enabled is True
    for attr in ["IsEnabled", "IsOffscreen", "HasKeyboardFocus", "BoundingRectangle"]:
        node = control()
        delattr(node, attr)
        with pytest.raises(GuiMetadataError, match="GUI_PROPERTY_READ_FAILED"):
            strict_tree(root(control(), node), (0, 0, 1, 1))


@pytest.mark.parametrize(
    "change",
    [
        dict(IsEnabled=1),
        dict(IsOffscreen=None),
        dict(Name='bad"name'),
        dict(ControlTypeName="HyperlinkControl"),
        dict(GetRuntimeId=lambda: []),
    ],
)
def test_strict_tree_rejects_unknown_or_lossy_values(change):
    with pytest.raises(GuiMetadataError):
        strict_tree(root(control(**change)), (0, 0, 1, 1))


def test_strict_tree_rejects_duplicates_and_limits():
    with pytest.raises(GuiMetadataError, match="GUI_NATIVE_ID_DUPLICATE"):
        strict_tree(root(control(), control()), (0, 0, 1, 1))
    node = control()
    for _ in range(13):
        node = control(ControlTypeName="PaneControl", GetChildren=lambda child=node: [child])
    with pytest.raises(GuiMetadataError, match="GUI_TREE_LIMIT"):
        strict_tree(root(node), (0, 0, 1, 1))


def test_strict_tree_records_disabled_and_offscreen_without_promoting_them():
    row = strict_tree(root(control(IsEnabled=False, IsOffscreen=True)), (0, 0, 1, 1))[0]
    assert not row.enabled and not row.visible


def test_metadata_geometry_and_boolean_types():
    with pytest.raises(GuiMetadataError):
        VerifiedControl("x", "edit", "D", (0, 0, 1, 1), 1, True, False)
    with pytest.raises(GuiMetadataError):
        VerifiedGuiState("314", "315", (0, 0, 1, 1), (0, 0, 1, 1), ())
    with pytest.raises(GuiMetadataError):
        VerifiedGuiState("314", "314", (0, 0, 2, 2), (0, 0, 1, 1), ())


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reader with all OS calls replaced")
@pytest.mark.parametrize("fault", ["", "rect", "origin", "foreground", "property", "minimized"])
def test_windows_reader_uses_checked_os_facts_without_desktop_io(monkeypatch, fault):
    from computer_use_mcp.drivers import windows

    def get_rect(hwnd, pointer):
        pointer._obj.left = pointer._obj.top = 0
        pointer._obj.right = pointer._obj.bottom = 1
        return 0 if fault == "rect" else 1

    user32 = SimpleNamespace(
        IsWindow=lambda hwnd: 1,
        IsWindowVisible=lambda hwnd: 1,
        IsIconic=lambda hwnd: fault == "minimized",
        GetWindowRect=get_rect,
    )
    monkeypatch.setattr(windows.ctypes.windll, "user32", user32)
    monitor = dict(left=10 if fault == "origin" else 0, top=0, width=1, height=1)
    monkeypatch.setattr(
        windows.mss, "mss", lambda: nullcontext(SimpleNamespace(monitors=[monitor, monitor]))
    )
    node = control()
    if fault == "property":
        del node.IsEnabled
    monkeypatch.setattr(windows.auto, "ControlFromHandle", lambda hwnd: root(node))
    driver = windows.WindowsDriver.__new__(windows.WindowsDriver)
    foreground = iter([314, 315 if fault == "foreground" else 314])
    monkeypatch.setattr(driver, "_foreground_hwnd", lambda: next(foreground))
    if fault:
        with pytest.raises(GuiMetadataError):
            driver.inspect_gui_metadata("314")
    else:
        state = driver.inspect_gui_metadata("314")
        assert state == FakeSource().metadata
        assert state.controls[0].native_id == windows.WindowsDriver._native_id(node)


@pytest.mark.parametrize("text", ["", "malformed", '* 314 | e | "x"\n  314 | e | "x"'])
def test_malformed_window_text_is_rejected(text):
    class Source(FakeSource):
        async def read(self, tool, arguments):
            stamp = await super().read(tool, arguments)
            if tool == "list_windows":
                return replace(stamp, result=replace(stamp.result, sanitized_text=text))
            return stamp

    with pytest.raises(GuiMetadataError, match="GUI_WINDOW_LIST_INVALID"):
        collect_gui_observation(TASK, Source(), clock=lambda: 1.0)


def test_ref_resolution_cannot_mutate_ledger_after_endpoint_check():
    class Source(FakeSource):
        async def resolve_ref(self, ref):
            self.epoch += 1
            return await super().resolve_ref(ref)

    with pytest.raises(GuiMetadataError, match="GUI_LEDGER_CHANGED"):
        collect_gui_observation(TASK, Source(), clock=lambda: 1.0)


def test_invalid_task_never_reads_source():
    source = FakeSource()
    with pytest.raises(GuiMetadataError, match="GUI_TARGET_INVALID"):
        collect_gui_observation({**TASK, "target": {"name": "D\n", "role": "edit"}}, source)
    assert not source.calls and source.inspections == 0


def test_cancelled_async_read_does_not_retry_or_return_facts():
    async def scenario():
        entered = asyncio.Event()

        class Source(FakeSource):
            async def read(self, tool, arguments):
                self.calls.append(tool)
                entered.set()
                await asyncio.Future()
                raise AssertionError("unreachable")

        source = Source()
        task = asyncio.create_task(collect_async(TASK, source))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert source.calls == ["list_windows"]
        assert source.inspections == 1

    asyncio.run(scenario())
