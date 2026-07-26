from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from computer_use_agent.config import MCPLaunchConfig
from computer_use_agent.desktop_mcp import MCPBridgeError, MCPCallCancelled, StdioDesktopMCP
from computer_use_agent.tool_registry import reviewed_mcp_descriptors
from computer_use_agent.types import (
    CallIdentity,
    DesktopMCPPort,
    ToolCall,
    ToolCallStatus,
    ToolResultStatus,
    to_json_value,
)


def _reviewed_tools() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            name=descriptor.name,
            inputSchema=to_json_value(descriptor.input_schema),
            outputSchema=to_json_value(descriptor.output_schema),
        )
        for descriptor in reviewed_mcp_descriptors()
    ]


def _page(
    tools: list[SimpleNamespace] | None = None,
    *,
    next_cursor: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        tools=_reviewed_tools() if tools is None else tools,
        nextCursor=next_cursor,
    )


def _text_result(text: str, *, is_error: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        isError=is_error,
        content=[SimpleNamespace(type="text", text=text)],
        structuredContent=None,
    )


def _call(
    name: str = "list_windows",
    arguments: dict[str, object] | None = None,
    *,
    status: ToolCallStatus = ToolCallStatus.AUTHORIZED,
    call_id: str = "call_1",
) -> ToolCall:
    return ToolCall(
        identity=CallIdentity(run_id="run_1", turn_id="turn_1", call_id=call_id),
        name=name,
        arguments=arguments or {},
        status=status,
    )


class ScriptedSession:
    def __init__(
        self,
        *,
        pages: dict[str | None, object] | None = None,
        results: tuple[object, ...] = (),
        block_startup: bool = False,
        block_call: bool = False,
        block_close: bool = False,
    ) -> None:
        self.pages = pages or {None: _page()}
        self.results = deque(results)
        self.block_startup = block_startup
        self.block_call = block_call
        self.block_close = block_close
        self.startup_entered = asyncio.Event()
        self.startup_release = asyncio.Event()
        self.call_entered = asyncio.Event()
        self.call_release = asyncio.Event()
        self.close_entered = asyncio.Event()
        self.close_release = asyncio.Event()
        self.close_cancellations = 0
        self.list_cursors: list[str | None] = []
        self.calls: list[tuple[str, dict[str, object], object]] = []

    async def list_tools(self, cursor: str | None = None) -> object:
        self.list_cursors.append(cursor)
        page = self.pages[cursor]
        if isinstance(page, BaseException):
            raise page
        return page

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
        read_timeout_seconds: object = None,
    ) -> object:
        copied_arguments = dict(arguments or {})
        self.calls.append((name, copied_arguments, read_timeout_seconds))
        self.call_entered.set()
        if self.block_call:
            await self.call_release.wait()
        if not self.results:
            raise RuntimeError("no scripted MCP result")
        result = self.results.popleft()
        if isinstance(result, BaseException):
            raise result
        return result


class FakeSessionFactory:
    def __init__(
        self,
        *sessions: ScriptedSession,
        close_error: bool = False,
    ) -> None:
        self.sessions = deque(sessions)
        self.close_error = close_error
        self.enter_calls = 0
        self.exit_calls = 0
        self.launches: list[tuple[MCPLaunchConfig, float]] = []

    def __call__(self, launch: MCPLaunchConfig, timeout_seconds: float):
        @asynccontextmanager
        async def lease():
            if not self.sessions:
                raise RuntimeError("no scripted MCP session")
            session = self.sessions.popleft()
            self.enter_calls += 1
            self.launches.append((launch, timeout_seconds))
            session.startup_entered.set()
            try:
                if session.block_startup:
                    await session.startup_release.wait()
                yield session
            finally:
                self.exit_calls += 1
                session.close_entered.set()
                while session.block_close and not session.close_release.is_set():
                    try:
                        await session.close_release.wait()
                    except asyncio.CancelledError:
                        session.close_cancellations += 1
                if self.close_error:
                    raise RuntimeError("scripted close failure")

        return lease()


def _launch(tmp_path: Path) -> MCPLaunchConfig:
    return MCPLaunchConfig(
        executable=tmp_path / "computer-use-mcp.exe",
        args=("--stdio",),
        cwd=tmp_path,
        environment={"CUMCP_ALLOWLIST": "notepad.exe"},
    )


def test_start_verifies_registry_before_dispatch_and_close_is_idempotent(
    tmp_path: Path,
) -> None:
    session = ScriptedSession(results=(_text_result("window list"),))
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> None:
        assert isinstance(bridge, DesktopMCPPort)
        descriptors = await bridge.discover_tools()
        assert len(descriptors) == 13
        assert bridge.generation == 1

        result = await bridge.call_tool(_call())
        assert result.status is ToolResultStatus.SUCCESS
        assert result.sanitized_text == "window list"
        await bridge.close()
        await bridge.close()

    asyncio.run(scenario())

    assert session.list_cursors == [None]
    assert session.calls[0][0:2] == ("list_windows", {})
    assert factory.enter_calls == 1
    assert factory.exit_calls == 1
    assert bridge.closed


def test_supervisor_task_can_call_and_close_after_discovery_task_returns(tmp_path: Path) -> None:
    session = ScriptedSession(results=(_text_result("supervised"),))
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def discover_then_return() -> None:
        await bridge.discover_tools()

    async def scenario() -> object:
        discovery_task = asyncio.create_task(discover_then_return())
        await discovery_task
        call_task = asyncio.create_task(bridge.call_tool(_call()))
        result = await call_task
        close_task = asyncio.create_task(bridge.close())
        await close_task
        return result

    result = asyncio.run(scenario())

    assert result.status is ToolResultStatus.SUCCESS
    assert result.sanitized_text == "supervised"
    assert bridge.closed
    assert factory.exit_calls == 1


def test_call_before_discovery_and_after_close_never_starts_or_dispatches(
    tmp_path: Path,
) -> None:
    session = ScriptedSession(results=(_text_result("unused"),))
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> tuple[object, object]:
        before = await bridge.call_tool(_call(call_id="before"))
        await bridge.close()
        after = await bridge.call_tool(_call(call_id="after"))
        return before, after

    before, after = asyncio.run(scenario())

    for result in (before, after):
        assert result.status is ToolResultStatus.TRANSPORT_ERROR
        assert result.code == "MCP_TRANSPORT_ERROR"
    assert factory.enter_calls == 0
    assert session.calls == []


def test_policy_unknown_tool_and_bad_arguments_are_rejected_before_dispatch(
    tmp_path: Path,
) -> None:
    session = ScriptedSession()
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> tuple[object, object, object]:
        await bridge.discover_tools()
        requested = await bridge.call_tool(
            _call(status=ToolCallStatus.REQUESTED, call_id="requested")
        )
        unknown = await bridge.call_tool(_call("shell", {"command": "whoami"}, call_id="shell"))
        bad_click = await bridge.call_tool(_call("click", {"x": 1}, call_id="click"))
        await bridge.close()
        return requested, unknown, bad_click

    requested, unknown, bad_click = asyncio.run(scenario())

    assert requested.status is ToolResultStatus.REJECTED
    assert requested.code == "POLICY_DENIED"
    assert unknown.status is ToolResultStatus.REJECTED
    assert unknown.code == "SCHEMA_MISMATCH"
    assert bad_click.status is ToolResultStatus.REJECTED
    assert bad_click.code == "SCHEMA_MISMATCH"
    assert session.calls == []


def test_discovery_drift_closes_generation_and_cannot_dispatch(tmp_path: Path) -> None:
    tools = _reviewed_tools()
    tools.append(SimpleNamespace(name="shell", inputSchema={"type": "object"}))
    session = ScriptedSession(pages={None: _page(tools)})
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> object:
        with pytest.raises(MCPBridgeError) as raised:
            await bridge.discover_tools()
        assert raised.value.code == "SCHEMA_MISMATCH"
        return await bridge.call_tool(_call())

    result = asyncio.run(scenario())

    assert result.status is ToolResultStatus.TRANSPORT_ERROR
    assert result.code == "MCP_CHILD_EXITED_BEFORE_DISPATCH"
    assert session.calls == []
    assert factory.exit_calls == 1


def test_paginated_discovery_checks_every_page(tmp_path: Path) -> None:
    tools = _reviewed_tools()
    pages = {
        None: _page(tools[:4], next_cursor="page-2"),
        "page-2": _page(
            tools[4:] + [SimpleNamespace(name="shell", inputSchema={"type": "object"})]
        ),
    }
    session = ScriptedSession(pages=pages)
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    with pytest.raises(MCPBridgeError) as raised:
        asyncio.run(bridge.discover_tools())

    assert raised.value.code == "SCHEMA_MISMATCH"
    assert session.list_cursors == [None, "page-2"]
    assert factory.exit_calls == 1


def test_startup_timeout_is_not_dispatched_and_cleans_partial_lease(tmp_path: Path) -> None:
    session = ScriptedSession(block_startup=True)
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(
        _launch(tmp_path),
        timeout_seconds=0.01,
        session_factory=factory,
    )

    with pytest.raises(MCPBridgeError) as raised:
        asyncio.run(bridge.discover_tools())

    assert raised.value.code == "MCP_TIMEOUT_BEFORE_DISPATCH"
    assert session.calls == []
    assert factory.enter_calls == 1
    assert factory.exit_calls == 1


def test_post_dispatch_timeout_invalidates_generation_without_replay_and_can_restart(
    tmp_path: Path,
) -> None:
    first = ScriptedSession(results=(_text_result("late"),), block_call=True)
    second = ScriptedSession(results=(_text_result("fresh"),))
    factory = FakeSessionFactory(first, second)
    bridge = StdioDesktopMCP(
        _launch(tmp_path),
        # Keep the synthetic timeout short without making restart discovery
        # depend on sub-10 ms scheduling on slower CI Python versions.
        timeout_seconds=0.25,
        session_factory=factory,
    )

    async def scenario() -> tuple[object, object, object]:
        await bridge.discover_tools()
        timed_out = await bridge.call_tool(_call(call_id="timed-out"))
        before_restart = await bridge.call_tool(_call(call_id="before-restart"))
        assert bridge.generation == 1

        await bridge.discover_tools()
        assert bridge.generation == 2
        after_restart = await bridge.call_tool(_call(call_id="after-restart"))
        await bridge.close()
        return timed_out, before_restart, after_restart

    timed_out, before_restart, after_restart = asyncio.run(scenario())

    assert timed_out.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert timed_out.code == "MCP_TRANSPORT_ERROR"
    assert before_restart.status is ToolResultStatus.TRANSPORT_ERROR
    assert before_restart.code == "MCP_CHILD_EXITED_BEFORE_DISPATCH"
    assert after_restart.status is ToolResultStatus.SUCCESS
    assert after_restart.sanitized_text == "fresh"
    assert len(first.calls) == 1
    assert len(second.calls) == 1
    assert factory.enter_calls == 2
    assert factory.exit_calls == 2


def test_post_dispatch_cancellation_propagates_with_unknown_outcome_and_closes_child(
    tmp_path: Path,
) -> None:
    session = ScriptedSession(results=(_text_result("late"),), block_call=True)
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def owner() -> object:
        await bridge.discover_tools()
        return await bridge.call_tool(_call())

    async def scenario() -> tuple[object, bool]:
        owner_task = asyncio.create_task(owner())
        await session.call_entered.wait()
        owner_task.cancel()
        try:
            await owner_task
        except MCPCallCancelled as cancelled:
            result = cancelled.result
        else:
            raise AssertionError("post-dispatch cancellation must propagate")
        was_cancelled = owner_task.cancelled()
        await bridge.close()
        return result, was_cancelled

    result, was_cancelled = asyncio.run(scenario())

    assert result.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert result.code == "MCP_TRANSPORT_ERROR"
    assert was_cancelled
    assert len(session.calls) == 1
    assert factory.exit_calls == 1
    assert bridge.closed


def test_cancellation_during_cleanup_still_carries_unknown_outcome(tmp_path: Path) -> None:
    session = ScriptedSession(results=(EOFError("secret-eof"),), block_close=True)
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def owner() -> object:
        await bridge.discover_tools()
        return await bridge.call_tool(_call("key", {"combo": "Ctrl+S"}))

    async def scenario() -> object:
        owner_task = asyncio.create_task(owner())
        await session.close_entered.wait()
        owner_task.cancel()
        session.close_release.set()
        try:
            await owner_task
        except MCPCallCancelled as cancelled:
            result = cancelled.result
        else:
            raise AssertionError("cleanup cancellation must carry the dispatched result")
        await bridge.close()
        return result

    result = asyncio.run(scenario())

    assert result.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert result.code == "MCP_TRANSPORT_ERROR"
    assert len(session.calls) == 1
    assert factory.exit_calls == 1


def test_malformed_post_dispatch_action_result_is_unknown_and_drops_generation(
    tmp_path: Path,
) -> None:
    secret = "server-secret-value"
    session = ScriptedSession(results=(_text_result(secret),))
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> object:
        await bridge.discover_tools()
        return await bridge.call_tool(_call("key", {"combo": "Ctrl+S"}))

    result = asyncio.run(scenario())

    assert result.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert result.dispatch.value == "dispatched"
    assert result.code == "MCP_PROTOCOL_ERROR"
    assert secret not in repr(result)
    assert factory.exit_calls == 1


def test_server_exception_for_side_effect_invalidates_generation(tmp_path: Path) -> None:
    secret = "typed-secret-from-server"
    session = ScriptedSession(results=(_text_result(secret, is_error=True),))
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> tuple[object, object]:
        await bridge.discover_tools()
        failed = await bridge.call_tool(_call("type", {"text": secret}, call_id="type"))
        next_call = await bridge.call_tool(_call(call_id="next"))
        return failed, next_call

    failed, next_call = asyncio.run(scenario())

    assert failed.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert failed.dispatch.value == "dispatched"
    assert failed.sanitized_text == ""
    assert secret not in repr(failed)
    assert next_call.status is ToolResultStatus.TRANSPORT_ERROR
    assert next_call.code == "MCP_CHILD_EXITED_BEFORE_DISPATCH"
    assert factory.exit_calls == 1


def test_post_dispatch_eof_is_unknown_once_and_requires_rediscovery(tmp_path: Path) -> None:
    secret = "eof-secret-message"
    session = ScriptedSession(results=(EOFError(secret),))
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> tuple[object, object]:
        await bridge.discover_tools()
        failed = await bridge.call_tool(_call("key", {"combo": "Ctrl+S"}, call_id="eof"))
        next_call = await bridge.call_tool(_call(call_id="next"))
        return failed, next_call

    failed, next_call = asyncio.run(scenario())

    assert failed.status is ToolResultStatus.UNKNOWN_OUTCOME
    assert failed.dispatch.value == "unknown"
    assert failed.code == "MCP_TRANSPORT_ERROR"
    assert secret not in repr(failed)
    assert len(session.calls) == 1
    assert next_call.status is ToolResultStatus.TRANSPORT_ERROR
    assert next_call.code == "MCP_CHILD_EXITED_BEFORE_DISPATCH"
    assert factory.exit_calls == 1


def test_discovery_transport_failure_is_structured_and_closes_child(tmp_path: Path) -> None:
    session = ScriptedSession(pages={None: EOFError("child exited")})
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    with pytest.raises(MCPBridgeError) as raised:
        asyncio.run(bridge.discover_tools())

    assert raised.value.code == "MCP_TRANSPORT_ERROR"
    assert "child exited" not in str(raised.value)
    assert factory.exit_calls == 1


def test_close_failure_still_marks_bridge_closed_and_clears_generation(tmp_path: Path) -> None:
    session = ScriptedSession()
    factory = FakeSessionFactory(session, close_error=True)
    bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=factory)

    async def scenario() -> None:
        await bridge.discover_tools()
        with pytest.raises(MCPBridgeError) as raised:
            await bridge.close()
        assert raised.value.code == "MCP_TRANSPORT_ERROR"
        await bridge.close()

    asyncio.run(scenario())

    assert bridge.closed
    assert factory.exit_calls == 1


def test_close_timeout_keeps_owner_handle_for_supervisor_retry(tmp_path: Path) -> None:
    session = ScriptedSession(block_close=True)
    factory = FakeSessionFactory(session)
    bridge = StdioDesktopMCP(
        _launch(tmp_path),
        close_timeout_seconds=0.01,
        session_factory=factory,
    )

    async def scenario() -> None:
        await bridge.discover_tools()
        with pytest.raises(MCPBridgeError) as raised:
            await bridge.close()
        assert raised.value.code == "MCP_TRANSPORT_ERROR"
        assert bridge.closed
        assert session.close_cancellations >= 1

        session.close_release.set()
        await bridge.close()

    asyncio.run(scenario())

    assert factory.exit_calls == 1
    assert bridge.closed


def test_abandoned_owner_failure_is_consumed_without_event_loop_secret(
    tmp_path: Path,
) -> None:
    import gc

    secret = "owner-task-secret-exception"
    session = ScriptedSession()
    fail_owner = asyncio.Event()
    owner_exited = asyncio.Event()

    def session_factory(_launch: MCPLaunchConfig, _timeout: float):
        @asynccontextmanager
        async def lease():
            owner_task = asyncio.current_task()
            assert owner_task is not None

            async def trigger_failure() -> None:
                await fail_owner.wait()
                owner_task.cancel()

            trigger_task = asyncio.create_task(trigger_failure())
            try:
                yield session
            finally:
                trigger_task.cancel()
                try:
                    await trigger_task
                except asyncio.CancelledError:
                    pass
                owner_exited.set()
                raise RuntimeError(secret)

        return lease()

    async def scenario() -> list[dict[str, object]]:
        contexts: list[dict[str, object]] = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda _loop, context: contexts.append(context))
        bridge = StdioDesktopMCP(_launch(tmp_path), session_factory=session_factory)
        await bridge.discover_tools()
        fail_owner.set()
        await owner_exited.wait()
        await asyncio.sleep(0)
        del bridge
        gc.collect()
        await asyncio.sleep(0)
        return contexts

    contexts = asyncio.run(scenario())

    assert secret not in repr(contexts)
    assert contexts == []
